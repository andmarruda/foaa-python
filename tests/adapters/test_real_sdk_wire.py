"""Wire tests: the real ``anthropic`` / ``openai`` SDK clients talk to a local fake server.

No API key and no network: this proves the SDKs accept the parameters the adapters build,
serialize them as the APIs expect, and that real SDK response objects parse correctly.
Skipped when the SDKs are not installed (``uv run --with anthropic --with openai pytest``).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from foaa import (
    Assignment,
    InMemoryEventBus,
    InMemoryMcpConnection,
    Petal,
    Policy,
    RunContext,
    StopReason,
    ToolSpec,
)
from foaa.adapters import AnthropicModel, OpenAICompatibleModel


class FakeServer:
    """Answers queued JSON bodies and records every request (path, headers, body)."""

    def __init__(self) -> None:
        self.replies: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("content-length", 0))
                server.requests.append(
                    {
                        "path": self.path,
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                        "body": json.loads(self.rfile.read(length) or b"{}"),
                    }
                )
                payload = json.dumps(server.replies.pop(0)).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: Any) -> None:
                return None

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def server() -> Iterator[FakeServer]:
    fake = FakeServer()
    yield fake
    fake.httpd.shutdown()


def anthropic_message(content: list[dict[str, Any]], stop: str) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 20, "output_tokens": 7},
    }


def weather_connection() -> InMemoryMcpConnection:
    async def get_current(args: Any) -> str:
        return f"Sunny in {args['city']}"

    return InMemoryMcpConnection("weather").add_tool(
        ToolSpec(
            "get_current",
            "Current weather",
            {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
            read_only=True,
        ),
        get_current,
    )


async def test_anthropic_sdk_round_trip_through_a_petal_tool_loop(server: FakeServer) -> None:
    anthropic = pytest.importorskip("anthropic")
    thinking = {"type": "thinking", "thinking": "", "signature": "sig-1"}
    server.replies = [
        anthropic_message(
            [
                thinking,
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "weather__get_current",
                    "input": {"city": "Lisbon"},
                },
            ],
            "tool_use",
        ),
        anthropic_message(
            [{"type": "text", "text": '{"conclusion": "Sunny", "confidence": 0.9}'}], "end_turn"
        ),
    ]
    client = anthropic.AsyncAnthropic(api_key="test", base_url=server.url, max_retries=0)
    petal = Petal(
        "forecaster",
        AnthropicModel(client),
        prompt="You forecast.",
        mcp=[weather_connection()],
        policy=Policy.for_petal("forecaster", tools={"weather/*"}),
    )

    result = await petal.run(
        Assignment("forecaster", "Weather in Lisbon?"),
        RunContext(flower_id="f", correlation_id="g", bus=InMemoryEventBus()),
    )

    assert result.succeeded and result.conclusion == "Sunny"
    first, second = server.requests
    assert first["path"].startswith("/v1/messages")
    assert "server-side-fallback-2026-07-01" in first["headers"].get("anthropic-beta", "")
    assert first["body"]["fallbacks"] == "default"
    assert first["body"]["system"].startswith("You forecast.")
    assert first["body"]["tools"][0]["name"] == "weather__get_current"
    assert first["body"]["cache_control"] == {"type": "ephemeral"}

    # second call: the assistant turn is replayed verbatim (thinking block + signature)
    assistant, tool_turn = second["body"]["messages"][1:]
    assert assistant["content"][0] == thinking
    assert assistant["content"][1]["id"] == "toolu_1"
    assert tool_turn["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "toolu_1",
            "content": "Sunny in Lisbon",
            "is_error": False,
        }
    ]


async def test_anthropic_refusal_through_the_sdk(server: FakeServer) -> None:
    anthropic = pytest.importorskip("anthropic")
    server.replies = [anthropic_message([], "refusal")]
    client = anthropic.AsyncAnthropic(api_key="test", base_url=server.url, max_retries=0)
    petal = Petal("p", AnthropicModel(client, fallbacks=None))

    result = await petal.run(Assignment("p", "x"), RunContext(flower_id="f", correlation_id="g"))

    assert not result.succeeded
    assert "refusal" in result.conclusion
    assert "anthropic-beta" not in server.requests[0]["headers"]


async def test_openai_sdk_round_trip(server: FakeServer) -> None:
    openai = pytest.importorskip("openai")
    server.replies = [
        {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 0,
            "model": "qwen3",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "weather__get_current",
                                    "arguments": '{"city": "Lisbon"}',
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13},
        }
    ]
    client = openai.AsyncOpenAI(api_key="test", base_url=server.url, max_retries=0)
    model = OpenAICompatibleModel(client, model="qwen3", max_tokens=256)

    from foaa import Message, ModelRequest

    response = await model.complete(
        ModelRequest(
            (Message.system("sys"), Message.user("Weather?")),
            tools=(ToolSpec("weather__get_current", "w", {"type": "object"}),),
        )
    )

    assert response.stop_reason == StopReason.TOOL_USE
    assert response.tool_calls[0].arguments == {"city": "Lisbon"}
    assert response.usage == {"input_tokens": 9, "output_tokens": 4}
    body = server.requests[0]["body"]
    assert server.requests[0]["path"].endswith("/chat/completions")
    assert body["max_tokens"] == 256
    assert body["tools"][0]["function"]["name"] == "weather__get_current"
