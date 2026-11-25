from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from foaa import Message, ModelRequest, StopReason, ToolCall, ToolSpec
from foaa.adapters import OpenAICompatibleModel

TOOL = ToolSpec("weather__get_current", "Weather", {"type": "object", "properties": {}})


class FakeClient:
    def __init__(self, response: Any) -> None:
        self.calls: list[dict[str, Any]] = []

        async def create(**params: Any) -> Any:
            self.calls.append(params)
            return response

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


def completion(message: Any, finish: str = "stop") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3),
    )


def test_request_is_translated_to_chat_completions_shape() -> None:
    model = OpenAICompatibleModel(
        FakeClient(None), model="qwen3", max_tokens=500, max_tokens_param="max_completion_tokens"
    )
    params = model.build_params(
        ModelRequest(
            messages=(
                Message.system("sys"),
                Message.user("hi"),
                Message.assistant("", [ToolCall("c1", "weather__get_current", {"city": "Lisbon"})]),
                Message.tool("c1", "Sunny"),
            ),
            tools=(TOOL,),
        )
    )

    assert params["model"] == "qwen3"
    assert params["max_completion_tokens"] == 500
    assert params["tools"][0] == {
        "type": "function",
        "function": {
            "name": TOOL.name,
            "description": "Weather",
            "parameters": dict(TOOL.input_schema),
        },
    }
    system, _user, assistant, tool = params["messages"]
    assert system == {"role": "system", "content": "sys"}
    assert assistant["content"] is None
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"city": "Lisbon"}
    assert tool == {"role": "tool", "tool_call_id": "c1", "content": "Sunny"}


async def test_response_is_parsed() -> None:
    call = SimpleNamespace(
        id="c1",
        function=SimpleNamespace(name="weather__get_current", arguments='{"city":"Lisbon"}'),
    )
    message = SimpleNamespace(content=None, tool_calls=[call])
    model = OpenAICompatibleModel(FakeClient(completion(message, "tool_calls")), model="m")

    result = await model.complete(ModelRequest((Message.user("hi"),)))

    assert result.content == ""
    assert result.tool_calls == (ToolCall("c1", "weather__get_current", {"city": "Lisbon"}),)
    assert result.stop_reason == StopReason.TOOL_USE
    assert result.usage == {"input_tokens": 12, "output_tokens": 3}


async def test_invalid_tool_arguments_fail_visibly() -> None:
    call = SimpleNamespace(id="c1", function=SimpleNamespace(name="x", arguments="{not json"))
    model = OpenAICompatibleModel(
        FakeClient(completion(SimpleNamespace(content="", tool_calls=[call]), "tool_calls")),
        model="m",
    )
    result = await model.complete(ModelRequest((Message.user("hi"),)))
    assert result.tool_calls[0].arguments == {"_invalid_arguments": "{not json"}


async def test_content_filter_maps_to_refusal() -> None:
    model = OpenAICompatibleModel(
        FakeClient(completion(SimpleNamespace(content="", tool_calls=None), "content_filter")),
        model="m",
    )
    result = await model.complete(ModelRequest((Message.user("hi"),)))
    assert result.stop_reason == StopReason.REFUSAL
