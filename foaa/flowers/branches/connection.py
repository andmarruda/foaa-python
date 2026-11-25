from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from foaa.flowers.common.model import ToolSpec


@dataclass(frozen=True, slots=True)
class ToolResult:
    content: str
    is_error: bool = False
    structured: Mapping[str, Any] | None = None


@runtime_checkable
class McpConnection(Protocol):
    """A branch: one MCP **client** connection (Constitution, Principle I).

    *What can this flower reach, use, or activate?* ``name`` is how policies refer to it:
    a tool is governed as ``"<connection name>/<tool name>"``.
    """

    name: str

    async def list_tools(self) -> Sequence[ToolSpec]: ...

    async def call_tool(self, tool: str, arguments: Mapping[str, Any]) -> ToolResult: ...


ToolHandler = Callable[[Mapping[str, Any]], Awaitable[str | ToolResult]]


class InMemoryMcpConnection:
    """A connection whose tools are plain async functions. For tests and local prototypes."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._tools: dict[str, tuple[ToolSpec, ToolHandler]] = {}

    def add_tool(
        self,
        spec: ToolSpec,
        handler: ToolHandler,
    ) -> InMemoryMcpConnection:
        self._tools[spec.name] = (spec, handler)
        return self

    async def list_tools(self) -> Sequence[ToolSpec]:
        return [spec for spec, _ in self._tools.values()]

    async def call_tool(self, tool: str, arguments: Mapping[str, Any]) -> ToolResult:
        if tool not in self._tools:
            return ToolResult(f"unknown tool {tool!r}", is_error=True)
        _, handler = self._tools[tool]
        output = await handler(arguments)
        return output if isinstance(output, ToolResult) else ToolResult(output)
