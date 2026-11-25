from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from foaa.common import RiskLevel
from foaa.edd.events import types
from foaa.governance.policy import Action, Policy
from foaa.governance.review import ReviewGate, ReviewRequest


class Emit(Protocol):
    """How the governor reports what it decided, without knowing who emits the event."""

    def __call__(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        risk_level: RiskLevel = RiskLevel.NONE,
        requires_review: bool = False,
    ) -> Awaitable[None]: ...


@dataclass(frozen=True, slots=True)
class Authorization:
    allowed: bool
    reason: str
    reviewed: bool = False


ReviewContext = Callable[[], tuple[str, str]]  # -> (flower_id, correlation_id)


class Governor:
    """Applies a policy and, when needed, the gardener's review. Every denial is observable."""

    def __init__(self, policy: Policy, review_gate: ReviewGate, emit: Emit) -> None:
        self.policy = policy
        self._gate = review_gate
        self._emit = emit

    async def authorize(
        self,
        action: Action,
        *,
        actor: str,
        flower_id: str,
        correlation_id: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> Authorization:
        decision = self.policy.evaluate(action)

        if not decision.allowed:
            await self._emit(
                types.ACTION_DENIED,
                {
                    "action": action.describe(),
                    "policy": self.policy.name,
                    "reason": decision.reason,
                },
                risk_level=RiskLevel.LOW,
            )
            return Authorization(False, decision.reason)

        if not decision.requires_review:
            return Authorization(True, decision.reason)

        await self._emit(
            types.REVIEW_REQUESTED,
            {"action": action.describe(), "policy": self.policy.name, "reason": decision.reason},
            risk_level=RiskLevel.MEDIUM,
            requires_review=True,
        )
        review = await self._gate.review(
            ReviewRequest(
                action=action,
                actor=actor,
                flower_id=flower_id,
                correlation_id=correlation_id,
                reason=decision.reason,
                arguments=dict(arguments or {}),
            )
        )
        await self._emit(
            types.REVIEW_RESOLVED,
            {
                "action": action.describe(),
                "approved": review.approved,
                "reviewer": review.reviewer,
                "comment": review.comment,
            },
            risk_level=RiskLevel.NONE if review.approved else RiskLevel.LOW,
        )
        if not review.approved:
            return Authorization(False, f"review rejected by {review.reviewer}: {review.comment}")
        return Authorization(True, f"approved by {review.reviewer}", reviewed=True)
