"""HarnessPetal: a subagent whose execution belongs to an external harness (ADR 0006).

FOAA does not run the agent loop here. Claude Code, the Agent SDK, Codex, LangGraph, or a
script you wrote does. FOAA contributes what a harness lacks: the role, the governance
boundary, the evidence contract, and the trace.

Governance happens at two moments, because FOAA cannot intercept a harness' own tool calls:

1. **Before**: the petal's :class:`Policy` is translated into :class:`HarnessPermissions`
   that the harness adapter must apply (its allowlist, sandbox, approval mode...).
2. **After**: every action the harness reports is audited against the same policy. A
   violation is published as ``governance.action.denied`` with ``audit = "post_hoc"`` and
   becomes a HIGH risk on the result, so the center escalates instead of trusting it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from foaa.common import RiskLevel
from foaa.edd.events import types
from foaa.flowers.common import (
    Assignment,
    Evidence,
    PetalResult,
    Risk,
    RunContext,
    TaskStatus,
)
from foaa.governance import Policy
from foaa.governance.policy import Action, ActionKind

# -- the contract between FOAA and a harness adapter -------------------------------------------


@dataclass(frozen=True, slots=True)
class HarnessPermissions:
    """A petal's policy, in the terms a harness adapter can enforce."""

    tools: tuple[str, ...] = ()
    review_tools: tuple[str, ...] = ()
    restricted: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    rag_sources: tuple[str, ...] = ()
    read_only_tools_only: bool = False
    max_steps: int = 8
    max_tool_calls: int = 16

    @classmethod
    def from_policy(cls, policy: Policy) -> HarnessPermissions:
        return cls(
            tools=tuple(sorted(policy.tools)),
            review_tools=tuple(sorted(policy.review_tools)),
            restricted=tuple(sorted(policy.restricted)),
            skills=tuple(sorted(policy.skills)),
            rag_sources=tuple(sorted(policy.rag_sources)),
            read_only_tools_only=policy.read_only_tools_only,
            max_steps=policy.max_steps,
            max_tool_calls=policy.max_tool_calls,
        )


@dataclass(frozen=True, slots=True)
class UpstreamResult:
    petal: str
    status: str
    conclusion: str


@dataclass(frozen=True, slots=True)
class HarnessTask:
    """Everything a harness needs to do one assignment, and nothing about FOAA internals."""

    petal: str
    assignment_id: str
    instruction: str
    permissions: HarnessPermissions
    objective: str | None = None
    feedback: str | None = None
    upstream: tuple[UpstreamResult, ...] = ()
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class HarnessAction:
    """A capability the harness reports having used. ``target`` is ``"<connection>/<tool>"``."""

    target: str
    read_only: bool = False
    reviewed: bool = False  # a human approved it inside the harness


@dataclass(frozen=True, slots=True)
class HarnessOutcome:
    """What a harness adapter returns. Mirrors the petal evidence contract."""

    conclusion: str
    succeeded: bool = True
    evidence: tuple[Evidence, ...] = ()
    risks: tuple[Risk, ...] = ()
    uncertainty: str | None = None
    confidence: float | None = None
    actions: tuple[HarnessAction, ...] = ()
    sources: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class HarnessPort(Protocol):
    """One method to implement to bring any agent runtime into a flower."""

    async def execute(self, task: HarnessTask) -> HarnessOutcome: ...


# -- the petal ---------------------------------------------------------------------------------


class HarnessPetal:
    """A petal that delegates execution to a :class:`HarnessPort` and governs the outcome."""

    role = "petal"

    def __init__(
        self,
        name: str,
        harness: HarnessPort,
        *,
        description: str = "",
        policy: Policy | None = None,
    ) -> None:
        if not name.strip():
            raise ValueError("a petal needs a name")
        self.name = name
        self.description = description
        self.harness = harness
        self.policy = policy or Policy.for_petal(f"{name}-default")

    def __repr__(self) -> str:
        return f"HarnessPetal(name={self.name!r}, harness={type(self.harness).__name__})"

    def set_policy(self, policy: Policy) -> HarnessPetal:
        self.policy = policy
        return self

    async def run(
        self,
        assignment: Assignment,
        ctx: RunContext,
        *,
        objective: str | None = None,
        upstream: Sequence[PetalResult] = (),
    ) -> PetalResult:
        await self._emit(
            ctx,
            types.TASK_STARTED,
            {"task_id": assignment.id, "petal": self.name, "instruction": assignment.instruction},
        )
        task = HarnessTask(
            petal=self.name,
            assignment_id=assignment.id,
            instruction=assignment.instruction,
            permissions=HarnessPermissions.from_policy(self.policy),
            objective=objective,
            feedback=assignment.feedback,
            upstream=tuple(UpstreamResult(r.petal, r.status.value, r.conclusion) for r in upstream),
            correlation_id=ctx.correlation_id,
        )
        try:
            done = await self.harness.execute(task)
        except Exception as error:
            reason = f"harness failed: {type(error).__name__}: {error}"
            result = PetalResult(
                task_id=assignment.id,
                petal=self.name,
                status=TaskStatus.FAILED,
                conclusion=reason,
                risks=(Risk(reason, RiskLevel.MEDIUM),),
                uncertainty=reason,
            )
            return await self._finish(ctx, result)

        audit_risks = await self._audit(ctx, done.actions)
        result = PetalResult(
            task_id=assignment.id,
            petal=self.name,
            status=TaskStatus.COMPLETED if done.succeeded else TaskStatus.FAILED,
            conclusion=done.conclusion,
            evidence=done.evidence,
            context_sources=done.sources,
            risks=done.risks + audit_risks,
            uncertainty=done.uncertainty,
            confidence=done.confidence,
            actions=tuple(a.target for a in done.actions),
        )
        return await self._finish(ctx, result)

    async def _audit(self, ctx: RunContext, actions: Sequence[HarnessAction]) -> tuple[Risk, ...]:
        risks: list[Risk] = []
        for used in actions:
            action = Action(ActionKind.TOOL, used.target, read_only=used.read_only)
            decision = self.policy.evaluate(action)
            if decision.allowed and not (decision.requires_review and not used.reviewed):
                continue
            reason = (
                decision.reason
                if not decision.allowed
                else f"{action.describe()} required a gardener review that did not happen"
            )
            await self._emit(
                ctx,
                types.ACTION_DENIED,
                {"action": action.describe(), "reason": reason, "audit": "post_hoc"},
                risk_level=RiskLevel.HIGH,
                requires_review=True,
            )
            risks.append(Risk(f"harness acted outside policy: {reason}", RiskLevel.HIGH))
        if len(actions) > self.policy.max_tool_calls:
            risks.append(
                Risk(
                    f"tool budget exceeded: {len(actions)} calls > {self.policy.max_tool_calls}",
                    RiskLevel.MEDIUM,
                )
            )
        return tuple(risks)

    async def _finish(self, ctx: RunContext, result: PetalResult) -> PetalResult:
        await self._emit(
            ctx,
            types.TASK_COMPLETED if result.succeeded else types.TASK_FAILED,
            {
                "task_id": result.task_id,
                "petal": result.petal,
                "status": result.status.value,
                "confidence": result.confidence,
                "evidence_count": len(result.evidence),
                "risk_count": len(result.risks),
                "actions": list(result.actions),
                "executor": "harness",
            },
            risk_level=result.risk_level,
            requires_review=result.risk_level.weight >= RiskLevel.HIGH.weight,
        )
        return result

    async def _emit(
        self,
        ctx: RunContext,
        event_type: str,
        payload: dict[str, object],
        *,
        risk_level: RiskLevel = RiskLevel.NONE,
        requires_review: bool = False,
    ) -> None:
        await ctx.emit(
            event_type,
            payload,
            attributes={"agent.role": self.role, "agent.name": self.name},
            risk_level=risk_level,
            requires_review=requires_review,
        )
