"""How a center thinks: planning (before delegation) and reinference (after evidence).

Both are ports with interchangeable implementations, so the way a center reasons can evolve
(a smarter planner, a cheaper evaluator, a deterministic pipeline) without changing
:class:`~foaa.flowers.anther.Anther` itself.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from foaa.common import ModelOutputError, RiskLevel, highest_risk, new_id
from foaa.flowers.common import Assignment, Objective, PetalResult, Risk
from foaa.flowers.common.parsing import as_float_01, as_list, as_str, extract_json_object
from foaa.flowers.root import RetrievedDocument
from foaa.flowers.runtime import render_context

# -- data the strategies work with --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PetalProfile:
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class PlanningInput:
    objective: Objective
    petals: tuple[PetalProfile, ...]
    context: tuple[RetrievedDocument, ...] = ()


@dataclass(frozen=True, slots=True)
class ReinferenceInput:
    objective: Objective
    assignments: tuple[Assignment, ...]
    latest: tuple[PetalResult, ...]
    results: tuple[PetalResult, ...]
    round: int
    max_rounds: int
    petals: tuple[PetalProfile, ...] = ()


class VerdictStatus(StrEnum):
    COMPLETE = "complete"
    REFINE = "refine"
    ESCALATE = "escalate"


@dataclass(frozen=True, slots=True)
class Verdict:
    """The center's judgement after reasoning again over the petals' evidence."""

    status: VerdictStatus
    summary: str
    refinements: tuple[Assignment, ...] = ()
    risks: tuple[Risk, ...] = ()
    confidence: float | None = None
    reason: str | None = None


class CenterMind(Protocol):
    """What a strategy may use from the center: its governed conversation with the model.

    The center's own prompt, skills, RAG, and read-only tools are applied by the harness.
    """

    async def think(self, instructions: str, content: str) -> str: ...


class PlanningStrategy(Protocol):
    async def plan(self, data: PlanningInput, mind: CenterMind) -> Sequence[Assignment]: ...


class ReinferenceStrategy(Protocol):
    async def evaluate(self, data: ReinferenceInput, mind: CenterMind) -> Verdict: ...


# -- model-driven defaults ----------------------------------------------------------------------

PLANNING_INSTRUCTIONS = """\
# Your role: the center of this flower

You coordinate a team of specialist petals. You do not do their work. Turn the objective
into assignments, one per petal contribution, each with a clear, self-contained instruction.
Use only the petals listed. Use "depends_on" when one assignment needs another's result.

Answer with a single JSON object:

{
  "assignments": [
    {"id": "a1", "petal": "<petal name>", "instruction": "...", "depends_on": []}
  ]
}"""

REINFERENCE_INSTRUCTIONS = """\
# Your role: reason again as the center of this flower

The petals returned their results. Do not just concatenate them. Check whether they answer
the objective, whether they agree, whether one invalidates another, what risk and
uncertainty remain, and whether more work is needed.

Choose one status:
- "complete": the results answer the objective safely; write the final summary.
- "refine": specific petals must redo or extend their work; list refinements with feedback.
- "escalate": the flower cannot decide safely on its own; explain why.

Answer with a single JSON object:

{
  "status": "complete|refine|escalate",
  "summary": "the decision that leaves the flower",
  "confidence": 0.0,
  "risks": [{"description": "...", "level": "none|low|medium|high|critical"}],
  "reason": "why this status",
  "refinements": [{"petal": "<petal name>", "instruction": "...", "feedback": "..."}]
}"""


def _describe_petals(petals: Sequence[PetalProfile]) -> str:
    return "\n".join(f"- {p.name}: {p.description or 'no description'}" for p in petals)


class ModelPlanning:
    """Default planner: the center's model decomposes the objective into assignments."""

    async def plan(self, data: PlanningInput, mind: CenterMind) -> Sequence[Assignment]:
        content = "\n\n".join(
            part
            for part in (
                f"# Objective\n\n{data.objective.description}",
                _constraints(data.objective),
                f"# Petals in this flower\n\n{_describe_petals(data.petals)}",
                render_context(data.context),
            )
            if part
        )
        answer = await mind.think(PLANNING_INSTRUCTIONS, content)
        items = as_list(extract_json_object(answer).get("assignments"))
        if not items:
            raise ModelOutputError("the planning answer has no assignments")

        local_to_global: dict[str, Assignment] = {}
        drafts: list[tuple[str, dict[str, object]]] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            local_id = as_str(item.get("id")) or f"a{index + 1}"
            drafts.append((local_id, item))
            local_to_global[local_id] = Assignment(
                petal=as_str(item.get("petal")), instruction=as_str(item.get("instruction"))
            )

        assignments = []
        for local_id, item in drafts:
            base = local_to_global[local_id]
            depends = tuple(
                local_to_global[dep].id
                for dep in as_list(item.get("depends_on"))
                if isinstance(dep, str) and dep in local_to_global
            )
            assignments.append(
                Assignment(base.petal, base.instruction, depends_on=depends, id=base.id)
            )
        return assignments


class ModelReinference:
    """Default evaluator: the center's model reasons again over the evidence."""

    async def evaluate(self, data: ReinferenceInput, mind: CenterMind) -> Verdict:
        results = [
            {
                "task_id": r.task_id,
                "petal": r.petal,
                "status": r.status.value,
                "conclusion": r.conclusion,
                "evidence": [{"claim": e.claim, "source": e.source} for e in r.evidence],
                "risks": [{"description": k.description, "level": k.level.value} for k in r.risks],
                "uncertainty": r.uncertainty,
                "confidence": r.confidence,
            }
            for r in data.results
        ]
        content = "\n\n".join(
            part
            for part in (
                f"# Objective\n\n{data.objective.description}",
                _constraints(data.objective),
                f"# Petals in this flower\n\n{_describe_petals(data.petals)}",
                f"# Round\n\n{data.round} of at most {data.max_rounds}",
                "# Petal results\n\n```json\n" + json.dumps(results, indent=2) + "\n```",
            )
            if part
        )
        answer = await mind.think(REINFERENCE_INSTRUCTIONS, content)
        payload = extract_json_object(answer)

        try:
            status = VerdictStatus(as_str(payload.get("status")).lower())
        except ValueError as error:
            raise ModelOutputError(
                f"unknown reinference status {payload.get('status')!r}"
            ) from error

        refinements = tuple(
            Assignment(
                petal=as_str(item.get("petal")),
                instruction=as_str(item.get("instruction")),
                feedback=as_str(item.get("feedback")) or None,
            )
            for item in as_list(payload.get("refinements"))
            if isinstance(item, dict)
        )
        risks = tuple(
            Risk(as_str(item.get("description")), RiskLevel.parse(item.get("level")))
            for item in as_list(payload.get("risks"))
            if isinstance(item, dict) and as_str(item.get("description"))
        )
        return Verdict(
            status=status,
            summary=as_str(payload.get("summary")),
            refinements=refinements,
            risks=risks,
            confidence=as_float_01(payload.get("confidence")),
            reason=as_str(payload.get("reason")) or None,
        )


def _constraints(objective: Objective) -> str:
    if not objective.constraints:
        return ""
    return "# Constraints\n\n" + "\n".join(f"- {c}" for c in objective.constraints)


# -- deterministic alternatives ------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    """One step of a :class:`StaticPlanning` pipeline. ``{objective}`` is substituted."""

    petal: str
    instruction: str = "{objective}"
    after: tuple[str, ...] = ()  # names of earlier steps' petals this step depends on


class StaticPlanning:
    """A fixed pipeline, no model needed to plan. Good for predictable, repeatable flows."""

    def __init__(self, steps: Sequence[Step]) -> None:
        self.steps = tuple(steps)

    async def plan(self, data: PlanningInput, mind: CenterMind) -> Sequence[Assignment]:
        by_petal: dict[str, Assignment] = {}
        assignments = []
        for step in self.steps:
            depends = tuple(by_petal[name].id for name in step.after if name in by_petal)
            assignment = Assignment(
                petal=step.petal,
                instruction=step.instruction.format(objective=data.objective.description),
                depends_on=depends,
            )
            by_petal[step.petal] = assignment
            assignments.append(assignment)
        return assignments


@dataclass(frozen=True)
class ThresholdReinference:
    """Rule-based reinference: explicit, cheap, and predictable.

    * failed petals are retried with feedback while rounds remain, then escalated;
    * any risk at or above ``escalate_at`` escalates;
    * confidence below ``min_confidence`` escalates;
    * otherwise the flower completes with ``summarize(results)``.
    """

    escalate_at: RiskLevel = RiskLevel.HIGH
    min_confidence: float = 0.0
    summarize: Callable[[Sequence[PetalResult]], str] = field(
        default=lambda results: "\n".join(f"[{r.petal}] {r.conclusion}" for r in results)
    )

    async def evaluate(self, data: ReinferenceInput, mind: CenterMind) -> Verdict:
        failed = [r for r in data.latest if not r.succeeded]
        if failed:
            if data.round < data.max_rounds:
                by_task = {a.id: a for a in data.assignments}
                # Retries keep the original dependency order: a dependency that is retried too
                # points at its retry; one that already succeeded stays a satisfied result.
                new_ids = {r.task_id: new_id("task") for r in failed}
                retries = tuple(
                    Assignment(
                        id=new_ids[r.task_id],
                        petal=r.petal,
                        instruction=by_task[r.task_id].instruction
                        if r.task_id in by_task
                        else data.objective.description,
                        depends_on=tuple(
                            new_ids.get(dep, dep)
                            for dep in (
                                by_task[r.task_id].depends_on if r.task_id in by_task else ()
                            )
                        ),
                        feedback=f"Your previous attempt failed: {r.conclusion}",
                    )
                    for r in failed
                )
                return Verdict(VerdictStatus.REFINE, "retrying failed petals", refinements=retries)
            return Verdict(
                VerdictStatus.ESCALATE,
                "petals kept failing",
                reason=", ".join(f"{r.petal}: {r.conclusion}" for r in failed),
            )

        # Failed attempts were retried (or escalated above), so successful results are current.
        # Only each petal's latest result counts: superseded attempts are history, not evidence.
        latest_by_petal = {r.petal: r for r in data.results}
        current = [r for r in latest_by_petal.values() if r.succeeded]
        risk = highest_risk(r.risk_level for r in current)
        if risk.weight >= self.escalate_at.weight:
            return Verdict(
                VerdictStatus.ESCALATE,
                self.summarize(current),
                reason=f"risk {risk.value} reached the escalation threshold",
            )
        confidences = [r.confidence for r in current if r.confidence is not None]
        confidence = min(confidences) if confidences else None
        if self.min_confidence > 0 and (confidence is None or confidence < self.min_confidence):
            return Verdict(
                VerdictStatus.ESCALATE,
                self.summarize(current),
                confidence=confidence,
                reason=f"confidence {confidence} is below {self.min_confidence}",
            )
        return Verdict(VerdictStatus.COMPLETE, self.summarize(current), confidence=confidence)


@dataclass(frozen=True)
class RepairLoopReinference:
    """Verify-and-repair: a failing verifier sends its evidence back to the petal that can fix it.

    ``repairs`` maps a verifier petal (tests, lint, type check...) to its fixer petal (the
    coder). When a mapped verifier fails and rounds remain, the center plans a new round:
    the fixer gets the verifier's output as feedback, and every verifier of that fixer runs
    again on the fixed work. When rounds run out, the flower escalates to the gardener.

    Anything else (no failures, or failures nobody can repair) is decided by ``fallback``.
    This is the loop at the heart of an agentic software factory, kept deterministic.
    """

    repairs: Mapping[str, str]
    fallback: ReinferenceStrategy = field(default_factory=ThresholdReinference)

    async def evaluate(self, data: ReinferenceInput, mind: CenterMind) -> Verdict:
        repairable = [r for r in data.latest if not r.succeeded and r.petal in self.repairs]
        if not repairable:
            return await self.fallback.evaluate(data, mind)
        if data.round >= data.max_rounds:
            return Verdict(
                VerdictStatus.ESCALATE,
                "verification still failing",
                reason="; ".join(f"{r.petal}: {r.conclusion}" for r in repairable),
            )

        by_petal = {a.petal: a for a in data.assignments}
        refinements: list[Assignment] = []
        for fixer in dict.fromkeys(self.repairs[r.petal] for r in repairable):
            failures = [r for r in repairable if self.repairs[r.petal] == fixer]
            previous = by_petal.get(fixer)
            fix = Assignment(
                petal=fixer,
                instruction=previous.instruction if previous else data.objective.description,
                feedback="Verification failed. Fix the work so these pass:\n"
                + "\n".join(f"- [{r.petal}] {r.conclusion}" for r in failures),
            )
            refinements.append(fix)
            for verifier, owner in self.repairs.items():
                if owner != fixer:
                    continue
                earlier = by_petal.get(verifier)
                refinements.append(
                    Assignment(
                        petal=verifier,
                        instruction=earlier.instruction if earlier else "Verify the fix",
                        depends_on=(fix.id,),
                    )
                )
        names = ", ".join(r.petal for r in repairable)
        return Verdict(
            VerdictStatus.REFINE,
            f"repairing after failed verification: {names}",
            refinements=tuple(refinements),
        )
