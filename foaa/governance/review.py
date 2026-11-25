from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from foaa.governance.policy import Action


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    """What the gardener sees before approving a sensitive action."""

    action: Action
    actor: str
    flower_id: str
    correlation_id: str
    reason: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    approved: bool
    reviewer: str
    comment: str = ""


@runtime_checkable
class ReviewGate(Protocol):
    """Human-in-the-loop port (the gardener).

    Implementations may ask a person through a UI, a chat message, a ticket... The action
    stays blocked until ``review`` returns (Constitution, Principle II).
    """

    async def review(self, request: ReviewRequest) -> ReviewDecision: ...


class DenyAllReviewGate:
    """Default gate: when no gardener is configured, sensitive actions do not happen."""

    async def review(self, request: ReviewRequest) -> ReviewDecision:
        return ReviewDecision(False, "deny-all-gate", "no review gate configured")


class ApproveAllReviewGate:
    """Approves everything. For local experiments and tests only."""

    async def review(self, request: ReviewRequest) -> ReviewDecision:
        return ReviewDecision(True, "approve-all-gate", "auto-approved")


class CallbackReviewGate:
    """Adapts any async function into a review gate."""

    def __init__(self, callback: Callable[[ReviewRequest], Awaitable[ReviewDecision]]) -> None:
        self._callback = callback

    async def review(self, request: ReviewRequest) -> ReviewDecision:
        return await self._callback(request)
