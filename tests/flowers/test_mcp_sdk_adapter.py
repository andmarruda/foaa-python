"""The MCP SDK adapter is tested against duck-typed fakes, so the core suite needs no ``mcp``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from foaa import McpSessionConnection


@dataclass
class Annotations:
    readOnlyHint: bool | None = None


@dataclass
class Tool:
    name: str
    description: str | None = None
    inputSchema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})
    annotations: Annotations | None = None


@dataclass
class TextContent:
    text: str
    type: str = "text"


@dataclass
class CallToolResult:
    content: list[Any]
    isError: bool = False
    structuredContent: dict[str, Any] | None = None


@dataclass
class ListToolsResult:
    tools: list[Tool]


class FakeSession:
    def __init__(self) -> None:
        self.list_calls = 0
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def list_tools(self) -> ListToolsResult:
        self.list_calls += 1
        return ListToolsResult(
            [
                Tool("get_file", "Read", annotations=Annotations(readOnlyHint=True)),
                Tool("push", None),
            ]
        )

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> CallToolResult:
        self.calls.append((name, arguments))
        return CallToolResult(
            [TextContent("hello"), TextContent("world")], structuredContent={"ok": 1}
        )


async def test_tools_are_mapped_with_read_only_hints_and_cached() -> None:
    session = FakeSession()
    connection = McpSessionConnection("github", session)

    tools = await connection.list_tools()
    await connection.list_tools()

    assert [(t.name, t.read_only) for t in tools] == [("get_file", True), ("push", False)]
    assert tools[1].description == ""
    assert session.list_calls == 1


async def test_call_results_join_text_content() -> None:
    session = FakeSession()
    result = await McpSessionConnection("github", session).call_tool("get_file", {"path": "a"})
    assert result.content == "hello\nworld"
    assert result.structured == {"ok": 1}
    assert session.calls == [("get_file", {"path": "a"})]
