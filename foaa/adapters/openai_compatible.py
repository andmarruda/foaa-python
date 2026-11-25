"""Adapter for any OpenAI-compatible Chat Completions API (``pip install foaa[openai]``).

One adapter covers OpenAI, Azure OpenAI, and the many servers that speak the same protocol
(Ollama, vLLM, LM Studio, Groq, OpenRouter, DeepSeek, ...). Pass an ``openai.AsyncOpenAI``
client pointed wherever you want; FOAA never imports the SDK.

    from openai import AsyncOpenAI
    from foaa.adapters import OpenAICompatibleModel

    local = OpenAICompatibleModel(
        AsyncOpenAI(base_url="http://localhost:11434/v1", api_key="ollama"), model="qwen3"
    )

Tool calling must be supported by the served model for petals that use MCP tools.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from foaa.flowers.common import (
    Message,
    ModelRequest,
    ModelResponse,
    StopReason,
    ToolCall,
)

_STOP_REASONS = {
    "stop": StopReason.END,
    "tool_calls": StopReason.TOOL_USE,
    "function_call": StopReason.TOOL_USE,
    "length": StopReason.MAX_TOKENS,
    "content_filter": StopReason.REFUSAL,
}


class OpenAICompatibleModel:
    """A :class:`~foaa.flowers.common.ModelPort` over ``chat.completions.create``."""

    def __init__(
        self,
        client: Any,
        *,
        model: str,
        max_tokens: int | None = None,
        max_tokens_param: str = "max_tokens",
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        """
        :param max_tokens_param: some providers and newer models expect
            ``"max_completion_tokens"`` instead of ``"max_tokens"``.
        :param extra: any additional ``chat.completions.create`` parameters, passed through.
        """
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.max_tokens_param = max_tokens_param
        self.extra = dict(extra or {})

    async def complete(self, request: ModelRequest) -> ModelResponse:
        response = await self.client.chat.completions.create(**self.build_params(request))
        return parse_response(response)

    def build_params(self, request: ModelRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model,
            "messages": to_openai_messages(request.messages),
        }
        if request.tools:
            params["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": dict(tool.input_schema),
                    },
                }
                for tool in request.tools
            ]
        if self.max_tokens is not None:
            params[self.max_tokens_param] = self.max_tokens
        params.update(self.extra)
        return params


def to_openai_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        if message.role in ("system", "user"):
            converted.append({"role": message.role, "content": message.content})
        elif message.role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": message.content or None}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(dict(call.arguments)),
                        },
                    }
                    for call in message.tool_calls
                ]
            converted.append(entry)
        else:  # tool
            converted.append(
                {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
            )
    return converted


def _arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"_invalid_arguments": str(raw)}  # the tool fails visibly instead of guessing
    return value if isinstance(value, dict) else {"_invalid_arguments": str(raw)}


def parse_response(response: Any) -> ModelResponse:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ModelResponse(content="", stop_reason=StopReason.OTHER)
    choice = choices[0]
    message = choice.message
    tool_calls = tuple(
        ToolCall(id=call.id, name=call.function.name, arguments=_arguments(call.function.arguments))
        for call in (getattr(message, "tool_calls", None) or [])
    )
    finish = getattr(choice, "finish_reason", None)
    usage_obj = getattr(response, "usage", None)
    usage = {
        target: value
        for source, target in (
            ("prompt_tokens", "input_tokens"),
            ("completion_tokens", "output_tokens"),
        )
        if isinstance(value := getattr(usage_obj, source, None), int)
    }
    return ModelResponse(
        content=getattr(message, "content", None) or "",
        tool_calls=tool_calls,
        usage=usage,
        stop_reason=_STOP_REASONS.get(finish or "", StopReason.OTHER if finish else None),
    )
