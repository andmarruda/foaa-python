from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from typing import Self

from foaa.common import FoaaError, RiskLevel
from foaa.edd import EventBus, InMemoryEventBus
from foaa.edd.events import types
from foaa.flowers.anther.plan import execution_waves, validate_plan
from foaa.flowers.anther.strategies import (
    ModelPlanning,
    ModelReinference,
    PetalProfile,
    PlanningInput,
    PlanningStrategy,
    ReinferenceInput,
    ReinferenceStrategy,
    Verdict,
    VerdictStatus,
)
from foaa.flowers.branches import McpConnection
from foaa.flowers.common import (
    Assignment,
    DecisionStatus,
    FlowerDecision,
    ModelPort,
    Objective,
    PetalResult,
    Risk,
    RunContext,
    Skill,
    TaskStatus,
)
from foaa.flowers.petals import Petal
from foaa.flowers.root import Retriever
from foaa.flowers.runtime import AgentHarness, CapabilityKit, Configurable
from foaa.governance import DenyAllReviewGate, Policy, ReviewGate

CENTER_CONTRACT = """\
# Output

Follow the answer format requested in the message exactly."""


class _HarnessMind:
    """Binds the center's governed harness to the strategies' :class:`CenterMind` port."""

    def __init__(self, harness: AgentHarness) -> None:
        self._harness = harness

    async def think(self, instructions: str, content: str) -> str:
        system = await self._harness.system_prompt(f"{instructions}\n\n{CENTER_CONTRACT}")
        conversation = await self._harness.converse(system, content)
        if conversation.exhausted:
            raise FoaaError("the center exhausted its step budget while thinking")
        if conversation.refused:
            raise FoaaError("the model provider declined the center's request (refusal)")
        return conversation.text


class Anther(Configurable):
    """The flower center: the agent that calls its subagents (petals) and coordinates them.

    It receives the same capability kit as a petal (prompt, skills, MCP connections, RAG
    sources, policy), by constructor parameter or setter. What makes it a center:

    1. **Plan**: turns an objective into assignments for its petals (:class:`PlanningStrategy`).
    2. **Delegate**: runs assignments in dependency order, in parallel where possible.
    3. **Reason again** over the evidence (:class:`ReinferenceStrategy`): complete, refine,
       or escalate. It never just concatenates petal outputs (Constitution, Principle I).
    4. **Decide**: publishes one :class:`FlowerDecision` with its risks and confidence.

    Without an explicit policy, the center may use the skills and RAG handed to it and only
    read-only MCP tools: it coordinates instead of doing the petals' work.
    """

    role = "center"

    def __init__(
        self,
        name: str,
        model: ModelPort | None = None,
        *,
        petals: Iterable[Petal] = (),
        prompt: str = "",
        skills: Iterable[Skill] = (),
        mcp: Iterable[McpConnection] = (),
        rag: Iterable[Retriever] = (),
        policy: Policy | None = None,
        planning: PlanningStrategy | None = None,
        reinference: ReinferenceStrategy | None = None,
        bus: EventBus | None = None,
        review_gate: ReviewGate | None = None,
        max_rounds: int = 3,
        flower_id: str | None = None,
    ) -> None:
        if not name.strip():
            raise ValueError("a center needs a name")
        if max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")
        self.name = name
        self.flower_id = flower_id or name
        self.model = model
        self.kit = CapabilityKit(
            prompt=prompt,
            skills=list(skills),
            mcp=list(mcp),
            rag=list(rag),
            policy=policy or Policy.for_center(f"{name}-default"),
        )
        self.planning: PlanningStrategy = planning or ModelPlanning()
        self.reinference: ReinferenceStrategy = reinference or ModelReinference()
        self.bus: EventBus = bus or InMemoryEventBus()
        self.review_gate: ReviewGate = review_gate or DenyAllReviewGate()
        self.max_rounds = max_rounds
        self._petals: dict[str, Petal] = {}
        for petal in petals:
            self.add_petal(petal)

    def __repr__(self) -> str:
        return f"Anther(name={self.name!r}, petals={list(self._petals)!r})"

    # -- configuration -----------------------------------------------------------------------

    def add_petal(self, petal: Petal) -> Self:
        if petal.name in self._petals:
            raise ValueError(f"petal {petal.name!r} already belongs to {self.name!r}")
        self._petals[petal.name] = petal
        return self

    def set_petals(self, petals: Iterable[Petal]) -> Self:
        self._petals = {}
        for petal in petals:
            self.add_petal(petal)
        return self

    def remove_petal(self, name: str) -> Self:
        self._petals.pop(name, None)
        return self

    @property
    def petals(self) -> Mapping[str, Petal]:
        return dict(self._petals)

    def set_planning(self, planning: PlanningStrategy) -> Self:
        self.planning = planning
        return self

    def set_reinference(self, reinference: ReinferenceStrategy) -> Self:
        self.reinference = reinference
        return self

    def set_bus(self, bus: EventBus) -> Self:
        self.bus = bus
        return self

    def set_review_gate(self, review_gate: ReviewGate) -> Self:
        self.review_gate = review_gate
        return self

    # -- the center at work ------------------------------------------------------------------

    async def handle(self, objective: Objective | str) -> FlowerDecision:
        """Turn an objective into one governed decision. Always returns a decision."""
        if isinstance(objective, str):
            objective = Objective(objective)
        if not self._petals:
            raise FoaaError(f"center {self.name!r} has no petals to coordinate")

        ctx = RunContext(
            flower_id=self.flower_id,
            correlation_id=objective.trace_id,
            bus=self.bus,
            review_gate=self.review_gate,
            causation_id=objective.causation_id,
        )
        received = await ctx.emit(
            types.OBJECTIVE_RECEIVED,
            {"objective_id": objective.id, "description": objective.description},
            attributes={"agent.role": self.role, "agent.name": self.name},
        )
        ctx = ctx.with_cause(received.event_id)
        harness = AgentHarness(
            name=self.name, role=self.role, model=self._require_model(), kit=self.kit, ctx=ctx
        )
        mind = _HarnessMind(harness)
        profiles = tuple(PetalProfile(p.name, p.description) for p in self._petals.values())

        # 1. plan ----------------------------------------------------------------------------
        try:
            context = tuple(await harness.retrieve(objective.description))
            drafted = await self.planning.plan(PlanningInput(objective, profiles, context), mind)
            plan = validate_plan(drafted, self._petals)
        except Exception as error:
            reason = f"planning failed: {type(error).__name__}: {error}"
            await harness.emit(types.PLAN_REJECTED, {"reason": reason}, risk_level=RiskLevel.MEDIUM)
            return await self._publish(harness, objective, _escalation(reason), [], rounds=0)

        await harness.emit(types.PLAN_CREATED, {"assignments": _describe(plan)})

        # 2-3. delegate and reason again, round by round -------------------------------------
        results: dict[str, PetalResult] = {}
        verdict: Verdict
        rounds = 0
        while True:
            rounds += 1
            latest = await self._execute(plan, results, objective, ctx)
            results.update({r.task_id: r for r in latest})
            try:
                verdict = await self.reinference.evaluate(
                    ReinferenceInput(
                        objective=objective,
                        assignments=tuple(plan),
                        latest=tuple(latest),
                        results=tuple(results.values()),
                        round=rounds,
                        max_rounds=self.max_rounds,
                        petals=profiles,
                    ),
                    mind,
                )
            except Exception as error:
                verdict = _escalation(f"reinference failed: {type(error).__name__}: {error}")

            await harness.emit(
                types.REINFERENCE_COMPLETED,
                {
                    "round": rounds,
                    "status": verdict.status.value,
                    "reason": verdict.reason,
                    "refinements": len(verdict.refinements),
                },
            )
            if verdict.status is not VerdictStatus.REFINE:
                break
            if rounds >= self.max_rounds:
                verdict = _escalation(f"still refining after {rounds} rounds", base=verdict)
                break
            try:
                plan = validate_plan(verdict.refinements, self._petals, known_results=results)
            except Exception as error:
                verdict = _escalation(f"invalid refinements: {error}", base=verdict)
                break
            await harness.emit(
                types.PLAN_CREATED, {"round": rounds + 1, "assignments": _describe(plan)}
            )

        # 4. decide ---------------------------------------------------------------------------
        return await self._publish(harness, objective, verdict, list(results.values()), rounds)

    async def _execute(
        self,
        plan: Sequence[Assignment],
        previous: Mapping[str, PetalResult],
        objective: Objective,
        ctx: RunContext,
    ) -> list[PetalResult]:
        results: dict[str, PetalResult] = dict(previous)
        produced: list[PetalResult] = []
        for wave in execution_waves(plan, satisfied=previous):
            outcomes = await asyncio.gather(
                *(self._run_one(a, results, objective, ctx) for a in wave)
            )
            for outcome in outcomes:
                results[outcome.task_id] = outcome
                produced.append(outcome)
        return produced

    async def _run_one(
        self,
        assignment: Assignment,
        results: Mapping[str, PetalResult],
        objective: Objective,
        ctx: RunContext,
    ) -> PetalResult:
        upstream = [results[dep] for dep in assignment.depends_on if dep in results]
        blocked = [r for r in upstream if not r.succeeded]
        if blocked:
            reason = "blocked by failed dependency: " + ", ".join(r.task_id for r in blocked)
            return PetalResult(
                task_id=assignment.id,
                petal=assignment.petal,
                status=TaskStatus.FAILED,
                conclusion=reason,
                risks=(Risk(reason, RiskLevel.MEDIUM),),
                uncertainty=reason,
            )
        petal = self._petals[assignment.petal]
        return await petal.run(assignment, ctx, objective=objective.description, upstream=upstream)

    async def _publish(
        self,
        harness: AgentHarness,
        objective: Objective,
        verdict: Verdict,
        results: list[PetalResult],
        rounds: int,
    ) -> FlowerDecision:
        completed = verdict.status is VerdictStatus.COMPLETE
        decision = FlowerDecision(
            objective_id=objective.id,
            flower_id=self.flower_id,
            status=DecisionStatus.COMPLETED if completed else DecisionStatus.ESCALATED,
            summary=verdict.summary,
            results=tuple(results),
            risks=verdict.risks,
            confidence=verdict.confidence,
            rounds=rounds,
            escalation_reason=None if completed else (verdict.reason or "escalated by center"),
        )
        await harness.emit(
            types.DECISION_PUBLISHED,
            {
                "objective_id": decision.objective_id,
                "status": decision.status.value,
                "summary": decision.summary,
                "confidence": decision.confidence,
                "rounds": decision.rounds,
                "escalation_reason": decision.escalation_reason,
                "result_count": len(decision.results),
            },
            risk_level=decision.risk_level,
            requires_review=decision.requires_review,
        )
        return decision


def _describe(plan: Sequence[Assignment]) -> list[dict[str, object]]:
    return [
        {
            "id": a.id,
            "petal": a.petal,
            "depends_on": list(a.depends_on),
            "refinement": bool(a.feedback),
        }
        for a in plan
    ]


def _escalation(reason: str, base: Verdict | None = None) -> Verdict:
    return Verdict(
        status=VerdictStatus.ESCALATE,
        summary=base.summary if base else "",
        risks=base.risks if base else (),
        confidence=base.confidence if base else None,
        reason=reason,
    )
