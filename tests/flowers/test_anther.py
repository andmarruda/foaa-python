from __future__ import annotations

import json

from foaa import (
    Anther,
    DecisionStatus,
    InMemoryEventBus,
    InMemoryRetriever,
    ModelRequest,
    ModelResponse,
    Objective,
    Petal,
    RiskLevel,
    StaticPlanning,
    Step,
    ThresholdReinference,
)
from foaa.edd.events import types
from foaa.testing import ScriptedModel, json_reply


def petal_answer(conclusion: str, confidence: float = 0.9, risk: str = "low") -> ModelResponse:
    return json_reply(
        {
            "conclusion": conclusion,
            "evidence": [{"claim": conclusion, "source": "test"}],
            "risks": [{"description": "test risk", "level": risk}],
            "uncertainty": "none",
            "confidence": confidence,
        }
    )


def product_flower(center_model: ScriptedModel, bus: InMemoryEventBus) -> Anther:
    return Anther(
        "product",
        center_model,
        prompt="You lead the product team.",
        bus=bus,
        petals=[
            Petal(
                "research",
                ScriptedModel(default=petal_answer("customers want discounts")),
                description="customer research",
            ),
            Petal(
                "ux",
                ScriptedModel(default=petal_answer("one-click upgrade")),
                description="user experience",
            ),
            Petal(
                "writer",
                ScriptedModel(default=petal_answer("Pay yearly, save more")),
                description="copywriting",
            ),
        ],
    )


PLAN = {
    "assignments": [
        {"id": "a1", "petal": "research", "instruction": "Study demand", "depends_on": []},
        {"id": "a2", "petal": "ux", "instruction": "Sketch upgrade", "depends_on": []},
        {"id": "a3", "petal": "writer", "instruction": "Write copy", "depends_on": ["a1", "a2"]},
    ]
}


async def test_center_plans_delegates_reasons_again_and_decides() -> None:
    bus = InMemoryEventBus()
    center_model = ScriptedModel(
        [
            json_reply(PLAN),
            json_reply({"status": "complete", "summary": "Launch yearly plan", "confidence": 0.85}),
        ]
    )
    center = product_flower(center_model, bus)

    decision = await center.handle(Objective("Launch yearly subscription plans"))

    assert decision.status is DecisionStatus.COMPLETED
    assert decision.summary == "Launch yearly plan"
    assert {r.petal for r in decision.results} == {"research", "ux", "writer"}
    assert decision.rounds == 1

    # the writer depended on research and ux, so it saw their results
    writer_model = center.petals["writer"].model
    assert isinstance(writer_model, ScriptedModel)
    writer_prompt = writer_model.requests[0].messages[1].content
    assert "customers want discounts" in writer_prompt and "one-click upgrade" in writer_prompt

    # reinference saw the evidence, not a concatenation
    reinference_request = center_model.requests[1].messages[1].content
    assert '"evidence"' in reinference_request

    # the whole story is observable under one correlation id
    event_types = [e.event_type for e in bus.events(correlation_id=decision.objective_id)]
    assert event_types[0] == types.OBJECTIVE_RECEIVED
    assert event_types[-1] == types.DECISION_PUBLISHED
    assert event_types.count(types.TASK_COMPLETED) == 3
    assert types.REINFERENCE_COMPLETED in event_types
    assert {e.flower_id for e in bus.history} == {"product"}


async def test_center_refines_with_feedback_before_deciding() -> None:
    bus = InMemoryEventBus()
    center_model = ScriptedModel(
        [
            json_reply(PLAN),
            json_reply(
                {
                    "status": "refine",
                    "summary": "",
                    "reason": "copy promises cancellation not covered",
                    "refinements": [
                        {
                            "petal": "writer",
                            "instruction": "Rewrite copy",
                            "feedback": "Do not promise refunds",
                        }
                    ],
                }
            ),
            json_reply({"status": "complete", "summary": "Launch", "confidence": 0.9}),
        ]
    )
    center = product_flower(center_model, bus)

    decision = await center.handle("Launch yearly subscription plans")

    assert decision.status is DecisionStatus.COMPLETED
    assert decision.rounds == 2
    writer_model = center.petals["writer"].model
    assert isinstance(writer_model, ScriptedModel)
    assert "Do not promise refunds" in writer_model.requests[-1].messages[1].content


async def test_center_escalates_after_max_rounds() -> None:
    refine = json_reply(
        {
            "status": "refine",
            "summary": "",
            "refinements": [{"petal": "ux", "instruction": "again"}],
        }
    )
    center_model = ScriptedModel([json_reply(PLAN)], default=refine)
    center = product_flower(center_model, InMemoryEventBus())
    center.max_rounds = 2

    decision = await center.handle("Launch")

    assert decision.status is DecisionStatus.ESCALATED
    assert decision.requires_review
    assert "2 rounds" in (decision.escalation_reason or "")


async def test_invalid_plan_escalates_instead_of_crashing() -> None:
    bus = InMemoryEventBus()
    center_model = ScriptedModel(
        [json_reply({"assignments": [{"petal": "ghost", "instruction": "boo"}]})]
    )
    center = product_flower(center_model, bus)

    decision = await center.handle("Launch")

    assert decision.status is DecisionStatus.ESCALATED
    assert "unknown petal" in (decision.escalation_reason or "")
    assert bus.events(types.PLAN_REJECTED)


async def test_center_uses_its_own_rag_while_planning() -> None:
    center_model = ScriptedModel(
        [
            json_reply(PLAN),
            json_reply({"status": "complete", "summary": "ok", "confidence": 0.9}),
        ]
    )
    center = product_flower(center_model, InMemoryEventBus())
    center.add_rag(InMemoryRetriever("soil", ["last launch: international tax broke billing"]))

    await center.handle("Launch yearly plans with international tax")

    planning_prompt = center_model.requests[0].messages[1].content
    assert "international tax broke billing" in planning_prompt


async def test_deterministic_pipeline_without_a_center_model_call() -> None:
    def never(_: ModelRequest) -> str:
        raise AssertionError("the center model must not be called")

    center = Anther(
        "content",
        ScriptedModel(default=never),
        petals=[
            Petal("research", ScriptedModel(default=petal_answer("facts"))),
            Petal("writer", ScriptedModel(default=petal_answer("article"))),
        ],
        planning=StaticPlanning(
            [Step("research"), Step("writer", "Write about: {objective}", after=("research",))]
        ),
        reinference=ThresholdReinference(),
    )

    decision = await center.handle("yearly plans")

    assert decision.status is DecisionStatus.COMPLETED
    assert "[writer] article" in decision.summary


async def test_threshold_reinference_escalates_high_risk() -> None:
    center = Anther(
        "security",
        ScriptedModel(),
        petals=[
            Petal("reviewer", ScriptedModel(default=petal_answer("sql injection", risk="high")))
        ],
        planning=StaticPlanning([Step("reviewer")]),
        reinference=ThresholdReinference(escalate_at=RiskLevel.HIGH),
    )
    decision = await center.handle("review billing")
    assert decision.status is DecisionStatus.ESCALATED
    assert decision.risk_level is RiskLevel.HIGH


async def test_failed_petal_is_retried_then_dependents_are_blocked() -> None:
    def fail(_: ModelRequest) -> str:
        raise TimeoutError("provider down")

    bus = InMemoryEventBus()
    center = Anther(
        "content",
        ScriptedModel(),
        bus=bus,
        petals=[
            Petal("research", ScriptedModel(default=fail)),
            Petal("writer", ScriptedModel(default=petal_answer("article"))),
        ],
        planning=StaticPlanning([Step("research"), Step("writer", after=("research",))]),
        reinference=ThresholdReinference(),
        max_rounds=2,
    )

    decision = await center.handle("yearly plans")

    assert decision.status is DecisionStatus.ESCALATED
    writer_results = [r for r in decision.results if r.petal == "writer"]
    assert writer_results and "blocked by failed dependency" in writer_results[0].conclusion
    started = [e for e in bus.events(types.TASK_STARTED) if e.payload["petal"] == "research"]
    assert len(started) == 2  # first attempt + one retry


def test_plan_json_is_what_the_center_is_asked_for() -> None:
    from foaa.flowers.anther.strategies import PLANNING_INSTRUCTIONS

    sample = PLANNING_INSTRUCTIONS[PLANNING_INSTRUCTIONS.index("{") :]
    assert json.loads(sample.replace("<petal name>", "x"))["assignments"]
