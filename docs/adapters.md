# LLM adapters: the contract

FOAA does not depend on any LLM provider. A center or petal talks to a model through one
port, and anything that implements it can be plugged in:

```python
class ModelPort(Protocol):
    async def complete(self, request: ModelRequest) -> ModelResponse: ...
```

This page is the contract for writing an adapter. The executable version of the same
contract is the conformance kit, [`foaa.testing.conformance`](../foaa/testing/conformance.py).

---

## Adapters that ship with FOAA

Both receive a client **you** create, so FOAA never imports a provider SDK, and you keep
full control of credentials, retries, timeouts, proxies, and platforms.

| Adapter | Install | Covers |
|---|---|---|
| `AnthropicModel` | `foaa[anthropic]` | Claude via the Messages API (first-party, and Bedrock / Vertex / Foundry clients with the same surface) |
| `OpenAICompatibleModel` | `foaa[openai]` | OpenAI, Azure OpenAI, Ollama, vLLM, LM Studio, Groq, OpenRouter, DeepSeek, and anything that speaks Chat Completions |

```python
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from foaa.adapters import AnthropicModel, OpenAICompatibleModel

claude = AnthropicModel(AsyncAnthropic())  # claude-opus-5-5 by default
local = OpenAICompatibleModel(
    AsyncOpenAI(base_url="http://localhost:11434/v1", api_key="ollama"), model="qwen3"
)

center = Anther("product", claude, petals=[Petal("writer", local), ...])
```

Different agents can use different models. A common pattern is a strong model for the
center and cheaper models for petals.

### `AnthropicModel` defaults worth knowing

* **Model:** `claude-opus-5-5`, `max_tokens=16000`. `effort=` sets `output_config.effort`.
* **Refusal fallbacks are on** (`fallbacks="default"`, beta `server-side-fallback-2026-07-01`):
  when a request is declined, the API retries it on a fallback model inside the same call.
  This parameter exists only on the first-party Claude API, so pass `fallbacks=None` on
  Bedrock, Vertex AI, or Foundry, or if you prefer a plain refusal.
* **Prompt caching is on** (`cache=True`): a center or petal resends the same system prompt
  and tools on every step, so caching cuts cost and latency.
* **Assistant turns are replayed verbatim** through `provider_content`, as the Messages API
  requires during tool loops (reasoning blocks included).

---

## The request: what an adapter receives

`ModelRequest` has three fields:

| Field | Meaning | Rules |
|---|---|---|
| `messages` | The conversation, in order | see the table below |
| `tools` | Tools the model may call (`ToolSpec`) | already filtered by policy; may be empty |
| `metadata` | `flower.id`, `agent.name`, `agent.role` | informational; use for logs or tags, or ignore |

### Messages

| `role` | Fields used | Translate to |
|---|---|---|
| `system` | `content` | the provider's system prompt. There may be more than one; join them in order. |
| `user` | `content` | a user turn |
| `assistant` | `content`, `tool_calls`, `provider_content` | an assistant turn. **If `provider_content` is not `None`, send it back exactly as you returned it.** Otherwise rebuild the turn from `content` and `tool_calls`. |
| `tool` | `content`, `tool_call_id`, `is_error` | the result of one tool call, linked by **the same id** the model produced. Consecutive tool messages answer one assistant turn: group them if the provider requires it (Anthropic does). |

### Tools

| `ToolSpec` field | Translate to |
|---|---|
| `name` | the tool name, **unchanged**. FOAA guarantees it matches `^[A-Za-z0-9_-]{1,64}$`, e.g. `github__get_file`. |
| `description` | the tool description |
| `input_schema` | a JSON Schema object; pass it as the provider's parameters schema |
| `read_only` | informational only; governance already used it |

---

## The response: what an adapter returns

| `ModelResponse` field | Required | Rules |
|---|---|---|
| `content` | yes | the answer text; `""` when the model only calls tools |
| `tool_calls` | yes, when the model calls tools | each `ToolCall(id, name, arguments)`: the provider's id, the exact tool name, and `arguments` **parsed into a dict** (never a JSON string) |
| `stop_reason` | recommended | normalize to `StopReason`: `end`, `tool_use`, `max_tokens`, `refusal`, `other` |
| `usage` | recommended | at least `input_tokens` and `output_tokens`; extra keys are welcome |
| `provider_content` | only if the provider needs it | opaque native content of the assistant turn; FOAA stores it and hands it back on the next request |

---

## What an adapter does **not** do

The harness already handles these, so adapters stay small (typically 50–150 lines):

* the tool loop (calling tools, budgets, retries of the conversation);
* governance (which tools, skills, and RAG sources are allowed) and the gardener's reviews;
* events and observability;
* parsing the JSON answers of centers and petals (the model answers in text; no JSON mode
  or structured-output feature is required).

**Hard requirement:** to use MCP tools, the model must support tool calling. Agents without
tools work with any chat model.

Raise an exception for transport or authentication errors. The petal turns it into a failed
result, and the center escalates.

---

## Proving an adapter is correct

1. **Unit tests with a fake client.** Check the translation both ways. See
   `tests/adapters/test_anthropic_adapter.py` and `tests/adapters/test_openai_adapter.py`.
2. **Wire tests with the real SDK against a local fake server.** No API key is needed, and the
   test proves the SDK accepts your parameters. See `tests/adapters/test_real_sdk_wire.py`.
3. **Live conformance against the real model:**

   ```python
   from foaa.testing.conformance import assert_conformance


   async def test_my_adapter() -> None:
       await assert_conformance(MyAdapter(client, model="..."))
   ```

   | Check | Required | Catches |
   |---|---|---|
   | text reply | yes | wrong response shape, empty answers, phantom tool calls |
   | system prompt is honored | yes | system messages dropped or misplaced |
   | tool call | yes | renamed tools, missing ids, arguments left as JSON strings |
   | tool result round trip | yes | wrong `tool_call_id`, assistant turn not replayed, results ignored |
   | failed tool result is accepted | yes | `is_error` results rejected by the provider |
   | token usage reported | no (warning) | missing `input_tokens` / `output_tokens` |
   | stop reason normalized | no (warning) | raw provider stop reasons leaking through |

   In this repository the live checks are opt-in:
   `FOAA_LIVE=1 uv run --with anthropic pytest tests/adapters -k live`.
