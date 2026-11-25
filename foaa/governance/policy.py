from __future__ import annotations

import fnmatch
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from enum import StrEnum


class ActionKind(StrEnum):
    """What an agent or subagent is trying to use."""

    SKILL = "skill"
    RAG = "rag"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class Action:
    """A single capability use, checked against a policy before it happens.

    ``target`` is the skill name, the RAG source name, or ``"<connection>/<tool>"`` for MCP
    tools. ``read_only`` comes from the tool's own annotations when available.
    """

    kind: ActionKind
    target: str
    read_only: bool = False

    def describe(self) -> str:
        return f"{self.kind.value}:{self.target}"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    requires_review: bool
    reason: str


def _matches(target: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(target, pattern) for pattern in patterns)


def _frozen(values: Collection[str]) -> frozenset[str]:
    if isinstance(values, str):  # a bare string is almost always a mistake: "*" vs ("*",)
        return frozenset({values})
    return frozenset(values)


@dataclass(frozen=True)
class Policy:
    """The governance boundary of an agent (center/bee) or subagent (petal).

    Deny-by-default: anything not matched by an allow pattern is rejected
    (Constitution, Principle II). Patterns use shell wildcards (``"github/*"``, ``"docs-*"``).

    * ``skills`` / ``rag_sources`` / ``tools``: allow lists.
    * ``review_tools``: tools that are allowed only after a human (gardener) approves.
    * ``restricted``: denied for every kind, always wins (``"*/delete_*"``, ``"secrets"``).
    * ``read_only_tools_only``: only tools annotated as read-only pass (review tools excepted).
    * ``max_*``: budgets that keep autonomy bounded.
    """

    name: str
    skills: Collection[str] = field(default_factory=frozenset)
    rag_sources: Collection[str] = field(default_factory=frozenset)
    tools: Collection[str] = field(default_factory=frozenset)
    review_tools: Collection[str] = field(default_factory=frozenset)
    restricted: Collection[str] = field(default_factory=frozenset)
    read_only_tools_only: bool = False
    max_steps: int = 8
    max_tool_calls: int = 16
    max_retrieved_documents: int = 6

    def __post_init__(self) -> None:
        for name in ("skills", "rag_sources", "tools", "review_tools", "restricted"):
            object.__setattr__(self, name, _frozen(getattr(self, name)))
        if self.max_steps < 1:
            raise ValueError("max_steps must be >= 1")
        if self.max_tool_calls < 0 or self.max_retrieved_documents < 0:
            raise ValueError("budgets cannot be negative")

    # -- factories ---------------------------------------------------------------------------

    @classmethod
    def deny_all(cls, name: str = "deny-all") -> Policy:
        """Nothing is allowed. The safe default when the user does not provide a policy."""
        return cls(name=name)

    @classmethod
    def for_center(
        cls,
        name: str = "center-default",
        *,
        skills: Collection[str] = ("*",),
        rag_sources: Collection[str] = ("*",),
        tools: Collection[str] = ("*",),
        restricted: Collection[str] = (),
        max_steps: int = 6,
    ) -> Policy:
        """Default for a center: read and understand, do not execute (Constitution, I).

        Every skill and RAG source handed to the center is usable, but only read-only MCP
        tools pass. The center coordinates; the petals do the work.
        """
        return cls(
            name=name,
            skills=skills,
            rag_sources=rag_sources,
            tools=tools,
            restricted=restricted,
            read_only_tools_only=True,
            max_steps=max_steps,
        )

    @classmethod
    def for_petal(
        cls,
        name: str,
        *,
        skills: Collection[str] = ("*",),
        rag_sources: Collection[str] = ("*",),
        tools: Collection[str] = (),
        review_tools: Collection[str] = (),
        restricted: Collection[str] = (),
        read_only_tools_only: bool = False,
        max_steps: int = 8,
        max_tool_calls: int = 16,
    ) -> Policy:
        """A petal policy: skills and RAG handed to it are usable, tools must be listed."""
        return cls(
            name=name,
            skills=skills,
            rag_sources=rag_sources,
            tools=tools,
            review_tools=review_tools,
            restricted=restricted,
            read_only_tools_only=read_only_tools_only,
            max_steps=max_steps,
            max_tool_calls=max_tool_calls,
        )

    # -- evaluation --------------------------------------------------------------------------

    def evaluate(self, action: Action) -> PolicyDecision:
        if _matches(action.target, self.restricted):
            return PolicyDecision(False, False, f"{action.describe()} is restricted by {self.name}")

        if action.kind is ActionKind.TOOL:
            return self._evaluate_tool(action)

        allow_list = self.skills if action.kind is ActionKind.SKILL else self.rag_sources
        if _matches(action.target, allow_list):
            return PolicyDecision(True, False, f"allowed by {self.name}")
        return PolicyDecision(False, False, f"{action.describe()} is not allowed by {self.name}")

    def _evaluate_tool(self, action: Action) -> PolicyDecision:
        if _matches(action.target, self.review_tools):
            return PolicyDecision(True, True, f"{action.describe()} requires review ({self.name})")
        if not _matches(action.target, self.tools):
            return PolicyDecision(
                False, False, f"{action.describe()} is not allowed by {self.name}"
            )
        if self.read_only_tools_only and not action.read_only:
            return PolicyDecision(
                False, False, f"{self.name} allows only read-only tools; {action.target} is not"
            )
        return PolicyDecision(True, False, f"allowed by {self.name}")
