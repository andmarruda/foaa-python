"""Adapter for the official MCP Python SDK (``pip install foaa[mcp]``).

This is the only module allowed to touch the ``mcp`` package, and it does so by duck typing
an already-initialized ``mcp.ClientSession``. The user owns the session's lifecycle
(``stdio_client``, ``streamablehttp_client``, ``async with``...), so FOAA stays a pure MCP
client and never manages servers (Constitution, scope).

Example::

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async with stdio_client(StdioServerParameters(command="my-server")) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            github = McpSessionConnection("github", session)
            petal = Petal("engineer", model, mcp=[github], policy=...)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from foaa.flowers.branches.connection import ToolResult
from foaa.flowers.common.model import ToolSpec


class _ClientSessionLike(Protocol):
    async def list_tools(self) -> Any: ...

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any: ...


class McpSessionConnection:
    """Wraps an ``mcp.ClientSession`` as a FOAA branch."""

    def __init__(self, name: str, session: _ClientSessionLike, *, cache_tools: bool = True) -> None:
        self.name = name
        self._session = session
        self._cache_tools = cache_tools
        self._tools: list[ToolSpec] | None = None

    async def list_tools(self) -> Sequence[ToolSpec]:
        if self._tools is not None and self._cache_tools:
            return self._tools
        result = await self._session.list_tools()
        tools = [_to_spec(tool) for tool in getattr(result, "tools", [])]
        self._tools = tools
        return tools

    async def call_tool(self, tool: str, arguments: Mapping[str, Any]) -> ToolResult:
        result = await self._session.call_tool(tool, dict(arguments))
        content = getattr(result, "content", None)
        if content is None:
            # SDK 2.x may answer with a non-content result (e.g. the server needs more input).
            kind = type(result).__name__
            return ToolResult(f"tool {tool!r} returned {kind} without content", is_error=True)
        texts = [
            getattr(block, "text", "")
            for block in content
            if getattr(block, "type", None) == "text"
        ]
        structured = _attr(result, "structured_content", "structuredContent")
        return ToolResult(
            content="\n".join(text for text in texts if text),
            is_error=bool(_attr(result, "is_error", "isError")),
            structured=structured if isinstance(structured, Mapping) else None,
        )


def _attr(obj: Any, snake: str, camel: str) -> Any:
    """Read a field from either SDK generation: 2.x uses snake_case, 1.x camelCase."""
    value = getattr(obj, snake, None)
    return value if value is not None else getattr(obj, camel, None)


def _to_spec(tool: Any) -> ToolSpec:
    annotations = getattr(tool, "annotations", None)
    read_only = bool(_attr(annotations, "read_only_hint", "readOnlyHint")) if annotations else False
    schema = _attr(tool, "input_schema", "inputSchema")
    return ToolSpec(
        name=str(tool.name),
        description=str(getattr(tool, "description", "") or ""),
        input_schema=schema if isinstance(schema, Mapping) else {"type": "object"},
        read_only=read_only,
    )
