"""Branches: governed reach to tools and systems. FOAA is an MCP client only."""

from foaa.flowers.branches.connection import (
    InMemoryMcpConnection,
    McpConnection,
    ToolHandler,
    ToolResult,
)
from foaa.flowers.branches.mcp_sdk import McpSessionConnection

__all__ = [
    "InMemoryMcpConnection",
    "McpConnection",
    "McpSessionConnection",
    "ToolHandler",
    "ToolResult",
]
