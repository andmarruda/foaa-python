"""Simulated orchestrations, from the simplest flower to a mini software factory.

Every agent here is a mock: fake harnesses stand in for Claude Code, Codex, or any other
runtime, and a fake command runner stands in for pytest/lint. Nothing touches a network or
a model. Each level adds one capability on top of the previous one, the same way the
architecture is meant to grow (small steps).

Level 1  one petal, fixed plan
Level 2  a pipeline: upstream results flow downstream
Level 3  parallel waves really run concurrently
Level 4  a failed dependency blocks its dependents, then escalates
Level 5  governance: a harness acting outside policy forces escalation
Level 6  verify-and-repair loop: failing tests send feedback to the coder
Level 7  the repair loop gives up after max_rounds
Level 8  mini software factory: mixed harnesses, commands, read-only reviewer
Level 9  two flowers chained by events (the shape a bee will automate)
"""

from __future__ import annotations

import asyncio

from foaa import (
    Anther,
    CommandPetal,
    DecisionStatus,
    HarnessPetal,
    HarnessTask,
    InMemoryEventBus,
    Objective,
    Policy,
    RepairLoopReinference,
    RiskLevel,
    StaticPlanning,
    Step,
    ThresholdReinference,
    event_types,
)
from foaa.testing import FakeCommandRunner, FakeHarness, command_result, outcome


def _center(name: str, *petals: object, steps: list[Step], **kwargs: object) -> Anther:
    return Anther(
        name,
        petals=petals,  # type: ignore[arg-type]
        planning=StaticPlanning(steps),
        reinference=kwargs.pop("reinference", ThresholdReinference()),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


def _tests_policy() -> Policy:
    return Policy.for_petal("tests", tools={"command/pytest"})


# -- Level 1 -----------------------------------------------------------------------------------


async def test_level_1_single_petal_without_any_model() -> None:
    """A center with deterministic strategies needs no model at all."""
    harness = FakeHarness(outcome("hello world", confidence=0.8))
    bus = InMemoryEventBus()
    center = _center("hello", HarnessPetal("writer", harness), steps=[Step("writer")], bus=bus)

    decision = await center.handle("say hello")

    assert decision.status is DecisionStatus.COMPLETED
    assert "hello world" in decision.summary
    assert harness.tasks[0].instruction == "say hello"
    assert [e.event_type for e in bus.history] == [
        event_types.OBJECTIVE_RECEIVED,
        event_types.PLAN_CREATED,
        event_types.TASK_STARTED,
        event_types.TASK_COMPLETED,
        event_types.REINFERENCE_COMPLETED,
        event_types.DECISION_PUBLISHED,
    ]


# -- Level 2 -----------------------------------------------------------------------------------


async def test_level_2_pipeline_passes_upstream_results_downstream() -> None:
    spec = FakeHarness(outcome("spec: yearly plan with 2 months free"))
    code = FakeHarness(outcome("implemented yearly billing"))
    center = _center(
        "eng",
        HarnessPetal("spec", spec),
        HarnessPetal("coder", code),
        steps=[Step("spec", "Specify: {objective}"), Step("coder", "Implement", after=("spec",))],
    )

    decision = await center.handle("yearly plans")

    assert decision.status is DecisionStatus.COMPLETED
    assert spec.tasks[0].instruction == "Specify: yearly plans"
    assert code.tasks[0].upstream[0].conclusion.startswith("spec:")


# -- Level 3 -----------------------------------------------------------------------------------


async def test_level_3_independent_petals_run_in_parallel() -> None:
    """Both harnesses wait for each other: this only finishes if they run concurrently."""
    barrier = asyncio.Barrier(2)

    async def meet(task: HarnessTask) -> object:
        await asyncio.wait_for(barrier.wait(), timeout=1)
        return outcome(f"{task.petal} done")

    center = _center(
        "eng",
        HarnessPetal("backend", FakeHarness(meet)),
        HarnessPetal("frontend", FakeHarness(meet)),
        steps=[Step("backend"), Step("frontend")],
    )

    decision = await center.handle("build feature")

    assert decision.status is DecisionStatus.COMPLETED
    assert {r.petal for r in decision.results} == {"backend", "frontend"}


# -- Level 4 -----------------------------------------------------------------------------------


async def test_level_4_failed_dependency_blocks_dependents_then_escalates() -> None:
    coder = FakeHarness(RuntimeError("out of credits"), RuntimeError("out of credits"))
    reviewer = FakeHarness()  # must never be called
    center = _center(
        "eng",
        HarnessPetal("coder", coder),
        HarnessPetal("reviewer", reviewer),
        steps=[Step("coder"), Step("reviewer", "Review", after=("coder",))],
        max_rounds=2,
    )

    decision = await center.handle("feature")

    assert decision.status is DecisionStatus.ESCALATED
    assert decision.requires_review
    assert reviewer.tasks == []
    assert "out of credits" in (decision.escalation_reason or "")


# -- Level 5 -----------------------------------------------------------------------------------


async def test_level_5_harness_outside_policy_forces_escalation() -> None:
    rogue = FakeHarness(outcome("done", confidence=0.95, actions=["prod/drop_table"]))
    bus = InMemoryEventBus()
    center = _center(
        "eng",
        HarnessPetal("coder", rogue, policy=Policy.for_petal("coder", tools={"repo/*"})),
        steps=[Step("coder")],
        bus=bus,
    )

    decision = await center.handle("migrate")

    assert decision.status is DecisionStatus.ESCALATED
    assert decision.risk_level is RiskLevel.HIGH
    assert bus.events(event_types.ACTION_DENIED)


# -- Level 6 -----------------------------------------------------------------------------------


async def test_level_6_failing_tests_send_feedback_to_the_coder() -> None:
    coder = FakeHarness(outcome("v1"), outcome("v2 fixes the assertion"))
    runner = FakeCommandRunner(
        command_result(1, "FAILED test_price - expected 100"), command_result(0, "12 passed")
    )
    center = _center(
        "eng",
        HarnessPetal("coder", coder),
        CommandPetal("tests", runner, ["pytest"], policy=_tests_policy()),
        steps=[Step("coder"), Step("tests", "Verify", after=("coder",))],
        reinference=RepairLoopReinference({"tests": "coder"}),
    )

    decision = await center.handle("fix pricing")

    assert decision.status is DecisionStatus.COMPLETED
    assert decision.rounds == 2
    assert "expected 100" in (coder.tasks[1].feedback or "")
    assert len(runner.calls) == 2  # tests re-ran after the fix
    assert "v2 fixes" in decision.summary
    assert "v1" not in decision.summary  # superseded work is not part of the decision


# -- Level 7 -----------------------------------------------------------------------------------


async def test_level_7_repair_loop_gives_up_after_max_rounds() -> None:
    coder = FakeHarness(*(outcome(f"attempt {i}") for i in range(3)))
    runner = FakeCommandRunner(*(command_result(1, "still red") for _ in range(3)))
    center = _center(
        "eng",
        HarnessPetal("coder", coder),
        CommandPetal("tests", runner, ["pytest"], policy=_tests_policy()),
        steps=[Step("coder"), Step("tests", "Verify", after=("coder",))],
        reinference=RepairLoopReinference({"tests": "coder"}),
        max_rounds=3,
    )

    decision = await center.handle("impossible fix")

    assert decision.status is DecisionStatus.ESCALATED
    assert decision.rounds == 3
    assert len(coder.tasks) == 3


# -- Level 8 -----------------------------------------------------------------------------------


async def test_level_8_mini_software_factory_with_mixed_harnesses() -> None:
    """spec (vendor A) -> code (vendor B) -> tests + lint (commands) -> security review."""
    bus = InMemoryEventBus()
    vendor_a = FakeHarness(outcome("spec ready", confidence=0.9))
    vendor_b = FakeHarness(
        outcome("code v1", actions=["repo/write_file"]),
        outcome("code v2", actions=["repo/write_file"]),
    )
    security = FakeHarness(
        outcome("no secrets touched", confidence=0.85, actions=["repo/read_file"]),
        outcome("still clean", confidence=0.85, actions=["repo/read_file"]),
    )
    tests = FakeCommandRunner(command_result(1, "1 failed"), command_result(0, "40 passed"))
    lint = FakeCommandRunner(command_result(0, "clean"), command_result(0, "clean"))

    center = _center(
        "engineering",
        HarnessPetal("spec", vendor_a, description="writes the spec"),
        HarnessPetal(
            "coder",
            vendor_b,
            policy=Policy.for_petal("coder", tools={"repo/*"}, restricted={"repo/secrets*"}),
        ),
        CommandPetal("tests", tests, ["pytest"], policy=_tests_policy()),
        CommandPetal(
            "lint", lint, ["ruff", "check"], policy=Policy.for_petal("lint", tools={"command/ruff"})
        ),
        HarnessPetal(
            "security",
            security,
            policy=Policy.for_petal("security", tools={"repo/read_*"}),
        ),
        steps=[
            Step("spec", "Specify: {objective}"),
            Step("coder", "Implement the spec", after=("spec",)),
            Step("tests", "Run tests", after=("coder",)),
            Step("lint", "Run lint", after=("coder",)),
            Step("security", "Review the change", after=("coder",)),
        ],
        reinference=RepairLoopReinference({"tests": "coder", "lint": "coder"}),
        bus=bus,
    )

    decision = await center.handle(Objective("yearly subscriptions", id="goal-42"))

    assert decision.status is DecisionStatus.COMPLETED, decision.escalation_reason
    assert decision.rounds == 2
    assert len(vendor_a.tasks) == 1  # the spec was not redone
    assert len(vendor_b.tasks) == 2
    assert vendor_b.tasks[1].feedback and "1 failed" in vendor_b.tasks[1].feedback
    assert bus.events(event_types.ACTION_DENIED) == []
    assert {e.correlation_id for e in bus.history} == {"goal-42"}


# -- Level 9 -----------------------------------------------------------------------------------


async def test_level_9_two_flowers_chained_through_events() -> None:
    """Engineering's decision becomes Marketing's objective, traced end to end.

    Today a listener does the hand-off; a bee will own this routing later.
    """
    bus = InMemoryEventBus()
    engineering = _center(
        "engineering",
        HarnessPetal("coder", FakeHarness(outcome("yearly billing shipped"))),
        steps=[Step("coder")],
        bus=bus,
    )
    copywriter = FakeHarness(outcome("Pay yearly, get two months free"))
    marketing = _center(
        "marketing", HarnessPetal("copy", copywriter), steps=[Step("copy")], bus=bus
    )

    handoffs: list[asyncio.Task[object]] = []

    async def hand_off(event: object) -> None:
        from foaa import EventEnvelope

        assert isinstance(event, EventEnvelope)
        if event.flower_id != "engineering" or event.payload["status"] != "completed":
            return
        objective = Objective(
            f"Announce: {event.payload['summary']}",
            correlation_id=event.correlation_id,
            causation_id=event.event_id,
        )
        handoffs.append(asyncio.ensure_future(marketing.handle(objective)))

    bus.subscribe(event_types.DECISION_PUBLISHED, hand_off)

    await engineering.handle(Objective("yearly plans", id="goal-7"))
    marketing_decision = await handoffs[0]

    assert marketing_decision.status is DecisionStatus.COMPLETED  # type: ignore[attr-defined]
    assert "yearly billing shipped" in copywriter.tasks[0].instruction
    flowers = {e.flower_id for e in bus.history if e.correlation_id == "goal-7"}
    assert flowers == {"engineering", "marketing"}
