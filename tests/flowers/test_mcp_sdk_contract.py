"""Contract test against the real ``mcp`` SDK types. Skipped when ``foaa[mcp]`` is absent."""

from __future__ import annotations

from typing import Any

import pytest

from foaa import McpSessionConnection

types = pytest.importorskip("mcp.types")


class RealTypesSession:
    """A session that answers with genuine ``mcp.types`` objects, no server needed."""

    async def list_tools(self) -> Any:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="get_file",
                    description="Read a file",
                    inputSchema={"type": "object", "properties": {"path": {"type": "string"}}},
                    annotations=types.ToolAnnotations(readOnlyHint=True),
                ),
                types.Tool(name="push", inputSchema={"type": "object"}),
            ]
        )

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"called {name}")],
            structuredContent={"ok": True},
            isError=False,
        )


async def test_adapter_reads_real_sdk_objects() -> None:
    connection = McpSessionConnection("github", RealTypesSession())

    tools = await connection.list_tools()
    assert [(t.name, t.read_only) for t in tools] == [("get_file", True), ("push", False)]
    assert "path" in tools[0].input_schema["properties"]

    result = await connection.call_tool("get_file", {"path": "a"})
    assert result.content == "called get_file"
    assert result.structured == {"ok": True}
    assert result.is_error is False
