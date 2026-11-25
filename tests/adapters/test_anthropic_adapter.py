from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from foaa import Message, ModelRequest, StopReason, ToolCall, ToolSpec
from foaa.adapters import AnthropicModel

TOOL = ToolSpec("weather__get_current", "Weather", {"type": "object", "properties": {}})


def block(**fields: Any) -> SimpleNamespace:
    return SimpleNamespace(**fields)


class FakeMessages:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def create(self, **params: Any) -> Any:
        self.calls.append(params)
        return self.response


class FakeClient:
    def __init__(self, response: Any) -> None:
        self.messages = FakeMessages(response)
        self.beta = SimpleNamespace(messages=FakeMessages(response))


def response(*content: Any, stop: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        content=list(content),
        stop_reason=stop,
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=None,
        ),
    )


async def test_request_is_translated_to_messages_api_shape() -> None:
    model = AnthropicModel(FakeClient(response()), fallbacks=None, effort="high")
    native = [block(type="thinking", thinking=""), block(type="tool_use", id="t1", name="x")]
    request = ModelRequest(
        messages=(
            Message.system("You are a center."),
            Message.user("Plan this."),
            Message.assistant(
                "",
                [ToolCall("t1", "weather__get_current", {"city": "Lisbon"})],
                provider_content=native,
            ),
            Message.tool("t1", "Sunny"),
            Message.tool("t2", "error: down", is_error=True),
        ),
        tools=(TOOL,),
    )

    params = model.build_params(request)

    assert params["model"] == "claude-opus-5-5"
    assert params["max_tokens"] == 16_000
    assert params["system"] == "You are a center."
    assert params["cache_control"] == {"type": "ephemeral"}
    assert params["output_config"] == {"effort": "high"}
    assert params["tools"] == [
        {"name": TOOL.name, "description": "Weather", "input_schema": dict(TOOL.input_schema)}
    ]
    user, assistant, results = params["messages"]
    assert user == {"role": "user", "content": "Plan this."}
    assert assistant["content"] is native  # replayed untouched (reasoning blocks included)
    assert results["role"] == "user"
    assert [b["tool_use_id"] for b in results["content"]] == ["t1", "t2"]  # one turn
    assert [b["is_error"] for b in results["content"]] == [False, True]


def test_assistant_without_native_content_is_rebuilt_as_blocks() -> None:
    params = AnthropicModel(FakeClient(response())).build_params(
        ModelRequest(
            messages=(
                Message.user("hi"),
                Message.assistant("Let me check.", [ToolCall("t1", "x", {"a": 1})]),
            )
        )
    )
    assert params["messages"][1]["content"] == [
        {"type": "text", "text": "Let me check."},
        {"type": "tool_use", "id": "t1", "name": "x", "input": {"a": 1}},
    ]


async def test_fallbacks_use_the_beta_endpoint_by_default() -> None:
    client = FakeClient(response(block(type="text", text="ok")))
    await AnthropicModel(client).complete(ModelRequest(messages=(Message.user("hi"),)))

    assert client.messages.calls == []
    sent = client.beta.messages.calls[0]
    assert sent["betas"] == ["server-side-fallback-2026-07-01"]
    assert sent["fallbacks"] == "default"


async def test_without_fallbacks_the_plain_endpoint_is_used() -> None:
    client = FakeClient(response(block(type="text", text="ok")))
    await AnthropicModel(client, fallbacks=None).complete(ModelRequest((Message.user("hi"),)))
    assert client.beta.messages.calls == []
    assert "fallbacks" not in client.messages.calls[0]


async def test_response_is_parsed_into_text_tool_calls_usage_and_native_content() -> None:
    blocks = [
        block(type="thinking", thinking=""),
        block(type="text", text="Checking the weather."),
        block(type="tool_use", id="t1", name="weather__get_current", input={"city": "Lisbon"}),
    ]
    client = FakeClient(response(*blocks, stop="tool_use"))

    result = await AnthropicModel(client).complete(ModelRequest((Message.user("hi"),)))

    assert result.content == "Checking the weather."
    assert result.tool_calls == (ToolCall("t1", "weather__get_current", {"city": "Lisbon"}),)
    assert result.stop_reason == StopReason.TOOL_USE
    assert result.usage == {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0}
    assert result.provider_content == blocks


async def test_refusal_is_normalized() -> None:
    client = FakeClient(response(stop="refusal"))
    result = await AnthropicModel(client).complete(ModelRequest((Message.user("hi"),)))
    assert result.stop_reason == StopReason.REFUSAL
    assert result.content == ""
