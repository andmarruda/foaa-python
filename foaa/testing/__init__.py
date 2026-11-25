"""Test doubles that ship with FOAA, so users can test their own flowers without a real LLM."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from foaa.flowers.common import ModelRequest, ModelResponse, ToolCall

Reply = ModelResponse | str | Callable[[ModelRequest], ModelResponse | str]


def reply(content: str = "", *tool_calls: ToolCall) -> ModelResponse:
    return ModelResponse(content=content, tool_calls=tuple(tool_calls))


def json_reply(data: Mapping[str, Any]) -> ModelResponse:
    return ModelResponse(content="```json\n" + json.dumps(data) + "\n```")


def tool_call(
    name: str, arguments: Mapping[str, Any] | None = None, call_id: str = "call_1"
) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=dict(arguments or {}))


class ScriptedModel:
    """A :class:`~foaa.flowers.common.ModelPort` that answers from a script.

    Each reply is a :class:`ModelResponse`, a plain string, or a function of the request.
    Every request is recorded in :attr:`requests` for assertions.
    """

    def __init__(self, replies: Iterable[Reply] = (), *, default: Reply | None = None) -> None:
        self._replies = list(replies)
        self._default = default
        self.requests: list[ModelRequest] = []

    def queue(self, *replies: Reply) -> ScriptedModel:
        self._replies.extend(replies)
        return self

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if self._replies:
            item = self._replies.pop(0)
        elif self._default is not None:
            item = self._default
        else:
            raise AssertionError("ScriptedModel ran out of replies")
        if callable(item):
            item = item(request)
        return ModelResponse(item) if isinstance(item, str) else item
