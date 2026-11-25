"""The model contract: what FOAA sends to an LLM and what it expects back.

This is the full contract an LLM adapter implements. See ``docs/adapters.md`` for the
mapping rules and ``foaa.testing.conformance`` for the executable checks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant", "tool"]

#: Tool names FOAA sends always match this, so they are valid on every major provider.
TOOL_NAME_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class StopReason:
    """Normalized stop reasons. Adapters map provider values onto these when they can."""

    END = "end"  # the model finished its answer
    TOOL_USE = "tool_use"  # the model is waiting for tool results
    MAX_TOKENS = "max_tokens"  # the answer was cut by the output limit
    REFUSAL = "refusal"  # the provider declined the request (safety)
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool the model may call. Mirrors the MCP tool description (JSON Schema input)."""

    name: str
    description: str = ""
    input_schema: Mapping[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    read_only: bool = False


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Message:
    """One turn of the conversation.

    * ``provider_content``: opaque, provider-native content of an assistant turn, copied from
      :attr:`ModelResponse.provider_content`. Adapters that need the exact original blocks
      back (for example reasoning blocks during a tool loop) replay it; others ignore it.
    * ``is_error``: on a ``tool`` message, the tool failed or the call was denied.
    """

    role: Role
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    provider_content: Any = None
    is_error: bool = False

    @classmethod
    def system(cls, content: str) -> Message:
        return cls("system", content)

    @classmethod
    def user(cls, content: str) -> Message:
        return cls("user", content)

    @classmethod
    def assistant(
        cls,
        content: str,
        tool_calls: Sequence[ToolCall] = (),
        *,
        provider_content: Any = None,
    ) -> Message:
        return cls("assistant", content, tuple(tool_calls), provider_content=provider_content)

    @classmethod
    def tool(cls, tool_call_id: str, content: str, *, is_error: bool = False) -> Message:
        return cls("tool", content, tool_call_id=tool_call_id, is_error=is_error)


@dataclass(frozen=True, slots=True)
class ModelRequest:
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """What an adapter returns.

    * ``content``: the text of the answer (may be empty when only tools are called).
    * ``tool_calls``: every tool the model wants to call, with parsed ``arguments``.
    * ``stop_reason``: one of :class:`StopReason` (or ``None`` when unknown).
    * ``usage``: token counts, ideally ``input_tokens`` and ``output_tokens``.
    * ``provider_content``: optional opaque native content to replay on the next request.
    """

    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Mapping[str, int] = field(default_factory=dict)
    stop_reason: str | None = None
    provider_content: Any = None


@runtime_checkable
class ModelPort(Protocol):
    """The only thing FOAA needs from an LLM provider (Constitution, Principle IV).

    Adapters for Anthropic, OpenAI-compatible APIs, local models, or any agent framework
    implement this single method. The core never imports a provider SDK.
    """

    async def complete(self, request: ModelRequest) -> ModelResponse: ...
