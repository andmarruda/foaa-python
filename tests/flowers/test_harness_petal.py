"""HarnessPetal and CommandPetal: subagents whose execution belongs to someone else."""

from __future__ import annotations

from foaa import (
    Assignment,
    CommandPetal,
    HarnessAction,
    HarnessPetal,
    InMemoryEventBus,
    Policy,
    RiskLevel,
    RunContext,
    TaskStatus,
    event_types,
)
from foaa.testing import FakeCommandRunner, FakeHarness, command_result, outcome


def _ctx() -> RunContext:
    return RunContext(flower_id="eng", correlation_id="goal-1", bus=InMemoryEventBus())


# -- HarnessPetal ------------------------------------------------------------------------------


async def test_harness_result_becomes_a_petal_result_with_evidence() -> None:
    harness = FakeHarness(outcome("done", confidence=0.9, evidence=[("tests added", "repo")]))
    petal = HarnessPetal("coder", harness, description="writes code")

    result = await petal.run(Assignment("coder", "implement X", id="a1"), _ctx())

    assert result.status is TaskStatus.COMPLETED
    assert result.conclusion == "done"
    assert result.confidence == 0.9
    assert result.evidence[0].claim == "tests added"
    assert result.task_id == "a1"


async def test_harness_receives_the_policy_translated_into_permissions() -> None:
    harness = FakeHarness(outcome("ok"))
    policy = Policy.for_petal(
        "coder", tools={"git/*"}, review_tools={"git/push"}, restricted={"*/delete_*"}
    )
    petal = HarnessPetal("coder", harness, policy=policy)

    await petal.run(Assignment("coder", "do it"), _ctx(), objective="ship feature")

    task = harness.tasks[0]
    assert task.objective == "ship feature"
    assert set(task.permissions.tools) == {"git/*"}
    assert set(task.permissions.review_tools) == {"git/push"}
    assert set(task.permissions.restricted) == {"*/delete_*"}
    assert task.permissions.max_tool_calls == policy.max_tool_calls


async def test_upstream_results_and_feedback_reach_the_harness() -> None:
    harness = FakeHarness(outcome("first"), outcome("second"))
    writer = HarnessPetal("writer", harness)
    ctx = _ctx()
    upstream = await writer.run(Assignment("writer", "draft"), ctx)

    reviewer_harness = FakeHarness(outcome("reviewed"))
    reviewer = HarnessPetal("reviewer", reviewer_harness)
    await reviewer.run(
        Assignment("reviewer", "review", feedback="be stricter"), ctx, upstream=[upstream]
    )

    task = reviewer_harness.tasks[0]
    assert task.feedback == "be stricter"
    assert task.upstream[0].petal == "writer"
    assert task.upstream[0].conclusion == "first"


async def test_a_crashing_harness_is_reported_not_raised() -> None:
    petal = HarnessPetal("coder", FakeHarness(RuntimeError("sandbox died")))
    ctx = _ctx()

    result = await petal.run(Assignment("coder", "x"), ctx)

    assert result.status is TaskStatus.FAILED
    assert "sandbox died" in result.conclusion
    assert ctx.bus.events(event_types.TASK_FAILED)  # type: ignore[attr-defined]


async def test_actions_outside_policy_are_audited_and_raise_risk() -> None:
    """The harness ran the tools itself, so FOAA audits after the fact and never hides it."""
    harness = FakeHarness(outcome("ok", actions=["git/commit", "github/delete_repo"]))
    petal = HarnessPetal("coder", harness, policy=Policy.for_petal("coder", tools={"git/*"}))
    ctx = _ctx()

    result = await petal.run(Assignment("coder", "x"), ctx)

    assert result.risk_level is RiskLevel.HIGH
    denied = ctx.bus.events(event_types.ACTION_DENIED)  # type: ignore[attr-defined]
    assert [e.payload["action"] for e in denied] == ["tool:github/delete_repo"]
    assert denied[0].payload["audit"] == "post_hoc"
    assert result.actions == ("git/commit", "github/delete_repo")


async def test_review_tools_used_without_a_gardener_are_flagged() -> None:
    harness = FakeHarness(outcome("ok", actions=[HarnessAction("git/push", reviewed=False)]))
    policy = Policy.for_petal("coder", review_tools={"git/push"})
    result = await HarnessPetal("coder", harness, policy=policy).run(
        Assignment("coder", "x"), _ctx()
    )
    assert result.risk_level is RiskLevel.HIGH


async def test_reviewed_actions_and_read_only_tools_pass_the_audit() -> None:
    harness = FakeHarness(
        outcome(
            "ok",
            actions=[
                HarnessAction("git/push", reviewed=True),
                HarnessAction("repo/read_file", read_only=True),
            ],
        )
    )
    policy = Policy.for_petal(
        "coder", tools={"repo/*"}, review_tools={"git/push"}, read_only_tools_only=True
    )
    result = await HarnessPetal("coder", harness, policy=policy).run(
        Assignment("coder", "x"), _ctx()
    )
    assert result.risk_level is RiskLevel.NONE


async def test_tool_budget_overrun_is_a_risk() -> None:
    harness = FakeHarness(outcome("ok", actions=["repo/read"] * 3))
    policy = Policy.for_petal("coder", tools={"repo/*"}, max_tool_calls=2)
    result = await HarnessPetal("coder", harness, policy=policy).run(
        Assignment("coder", "x"), _ctx()
    )
    assert any("budget" in r.description for r in result.risks)


# -- CommandPetal ------------------------------------------------------------------------------


def _allow(*commands: str) -> Policy:
    return Policy.for_petal("tests", tools={f"command/{c}" for c in commands})


async def test_command_exit_zero_is_objective_evidence() -> None:
    runner = FakeCommandRunner(command_result(0, "5 passed"))
    petal = CommandPetal("tests", runner, ["pytest", "-q"], policy=_allow("pytest"))

    result = await petal.run(Assignment("tests", "verify"), _ctx())

    assert result.succeeded
    assert result.confidence == 1.0
    assert "exited 0" in result.evidence[0].claim
    assert runner.calls == [("pytest", "-q")]


async def test_command_failure_carries_its_output_for_the_center() -> None:
    runner = FakeCommandRunner(command_result(1, "FAILED test_x - assert 1 == 2"))
    petal = CommandPetal("tests", runner, ["pytest"], policy=_allow("pytest"))

    result = await petal.run(Assignment("tests", "verify"), _ctx())

    assert result.status is TaskStatus.FAILED
    assert "assert 1 == 2" in result.conclusion


async def test_commands_are_denied_by_default() -> None:
    runner = FakeCommandRunner(command_result(0))
    ctx = _ctx()

    result = await CommandPetal("tests", runner, ["rm", "-rf", "/"]).run(
        Assignment("tests", "x"), ctx
    )

    assert result.status is TaskStatus.FAILED
    assert runner.calls == []  # never executed
    assert ctx.bus.events(event_types.ACTION_DENIED)  # type: ignore[attr-defined]


async def test_subprocess_runner_runs_a_real_command() -> None:
    import sys

    from foaa import SubprocessRunner

    done = await SubprocessRunner().run([sys.executable, "-c", "print('hi')"])
    assert done.exit_code == 0
    assert "hi" in done.output
