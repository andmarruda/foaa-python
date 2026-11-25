"""Native adapter for Claude through the Anthropic Messages API (``pip install foaa[anthropic]``).

Pass an ``anthropic.AsyncAnthropic`` client (or a Bedrock / Vertex / Foundry Anthropic client
with the same ``messages.create`` surface). FOAA never imports the SDK; the user owns the
client, its credentials, retries, and timeouts.

    from anthropic import AsyncAnthropic
    from foaa.adapters import AnthropicModel

    model = AnthropicModel(AsyncAnthropic())                  # claude-opus-5-5 by default
    petal = Petal("research", model, prompt="...")

Behavior worth knowing:

* **Assistant turns are replayed untouched.** During a tool loop the full ``response.content``
  (including reasoning blocks) is kept in ``provider_content`` and sent back as-is, as the
  Messages API requires.
* **Refusals** are reported as ``StopReason.REFUSAL``; petals turn them into failed results
  and centers escalate. With ``fallbacks="default"`` (the default) the API first retries a
  declined request on a fallback model server-side (beta ``server-side-fallback-2026-07-01``).
  That parameter only exists on the first-party Claude API: pass ``fallbacks=None`` on
  Amazon Bedrock, Vertex AI, or Microsoft Foundry.
* **Prompt caching** is on by default (top-level automatic ``cache_control``), which pays off
  because a center or petal resends the same system prompt and tools on every step.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from foaa.flowers.common import (
    Message,
    ModelRequest,
    ModelResponse,
    StopReason,
    ToolCall,
)

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_STOP_REASONS = {
    "end_turn": StopReason.END,
    "stop_sequence": StopReason.END,
    "tool_use": StopReason.TOOL_USE,
    "max_tokens": StopReason.MAX_TOKENS,
    "refusal": StopReason.REFUSAL,
}


class AnthropicModel:
    """A :class:`~foaa.flowers.common.ModelPort` over the Anthropic Messages API."""

    def __init__(
        self,
        client: Any,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 16_000,
        effort: str | None = None,
        cache: bool = True,
        fallbacks: str | Sequence[Mapping[str, Any]] | None = "default",
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        """
        :param client: an ``AsyncAnthropic`` (or compatible) client.
        :param effort: ``"low" | "medium" | "high" | "xhigh" | "max"``; ``None`` keeps the
            model's default (``medium`` on Claude Opus 5.5).
        :param fallbacks: server-side refusal fallbacks, ``"default"`` or a list such as
            ``[{"model": "claude-opus-4-8"}]``; ``None`` disables them.
        :param extra: any additional ``messages.create`` parameters, passed through.
        """
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        self.cache = cache
        self.fallbacks = fallbacks
        self.extra = dict(extra or {})

    async def complete(self, request: ModelRequest) -> ModelResponse:
        params = self.build_params(request)
        if self.fallbacks is not None:
            response = await self.client.beta.messages.create(
                betas=[FALLBACK_BETA], fallbacks=self.fallbacks, **params
            )
        else:
            response = await self.client.messages.create(**params)
        return parse_response(response)

    def build_params(self, request: ModelRequest) -> dict[str, Any]:
        """Translate a FOAA request into ``messages.create`` keyword arguments."""
        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": to_anthropic_messages(request.messages),
        }
        if system:
            params["system"] = system
        if request.tools:
            params["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": dict(tool.input_schema),
                }
                for tool in request.tools
            ]
        if self.cache:
            params["cache_control"] = {"type": "ephemeral"}
        if self.effort:
            params["output_config"] = {"effort": self.effort}
        params.update(self.extra)
        return params


def to_anthropic_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """System turns go to ``system``; tool results become ``tool_result`` blocks in one
    ``user`` turn; assistant turns replay ``provider_content`` when present."""
    converted: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            continue
        if message.role == "user":
            converted.append({"role": "user", "content": message.content})
        elif message.role == "assistant":
            converted.append({"role": "assistant", "content": _assistant_content(message)})
        else:  # tool
            block = {
                "type": "tool_result",
                "tool_use_id": message.tool_call_id,
                "content": message.content,
                "is_error": message.is_error,
            }
            previous = converted[-1] if converted else None
            if (
                previous is not None
                and previous["role"] == "user"
                and isinstance(previous["content"], list)
                and all(b.get("type") == "tool_result" for b in previous["content"])
            ):
                previous["content"].append(block)  # parallel calls: one user turn
            else:
                converted.append({"role": "user", "content": [block]})
    return converted


def _assistant_content(message: Message) -> Any:
    if message.provider_content is not None:
        return message.provider_content
    blocks: list[dict[str, Any]] = []
    if message.content:
        blocks.append({"type": "text", "text": message.content})
    blocks.extend(
        {"type": "tool_use", "id": call.id, "name": call.name, "input": dict(call.arguments)}
        for call in message.tool_calls
    )
    return blocks


def parse_response(response: Any) -> ModelResponse:
    content = list(getattr(response, "content", None) or [])
    text = "".join(
        getattr(block, "text", "") for block in content if getattr(block, "type", None) == "text"
    )
    tool_calls = tuple(
        ToolCall(id=block.id, name=block.name, arguments=dict(getattr(block, "input", None) or {}))
        for block in content
        if getattr(block, "type", None) == "tool_use"
    )
    raw_stop = getattr(response, "stop_reason", None)
    usage_obj = getattr(response, "usage", None)
    usage = {
        key: value
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
        if isinstance(value := getattr(usage_obj, key, None), int)
    }
    return ModelResponse(
        content=text,
        tool_calls=tool_calls,
        usage=usage,
        stop_reason=_STOP_REASONS.get(raw_stop or "", StopReason.OTHER if raw_stop else None),
        provider_content=content,
    )
