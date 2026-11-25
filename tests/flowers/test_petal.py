from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from foaa import (
    ApproveAllReviewGate,
    Assignment,
    FoaaError,
    InMemoryEventBus,
    InMemoryMcpConnection,
    InMemoryRetriever,
    ModelRequest,
    Petal,
    Policy,
    RiskLevel,
    RunContext,
    Skill,
    TaskStatus,
    ToolSpec,
)
from foaa.edd.events import types
from foaa.testing import ScriptedModel, json_reply, reply, tool_call

FINAL = {
    "conclusion": "Customers want a clear discount.",
    "evidence": [{"claim": "40% asked for discounts", "source": "survey:q3"}],
    "risks": [{"description": "small sample", "level": "Low"}],
    "uncertainty": "survey covers only US customers",
    "confidence": 0.8,
}


def ctx(**kwargs: Any) -> RunContext:
    return RunContext(
        flower_id="product", correlation_id="goal-1", bus=InMemoryEventBus(), **kwargs
    )


def github() -> InMemoryMcpConnection:
    async def get_file(args: Mapping[str, Any]) -> str:
        return f"contents of {args['path']}"

    async def push(args: Mapping[str, Any]) -> str:
        return "pushed"

    connection = InMemoryMcpConnection("github")
    connection.add_tool(ToolSpec("get_file", "Read a file", read_only=True), get_file)
    connection.add_tool(ToolSpec("push", "Push a commit"), push)
    return connection


async def test_petal_returns_a_structured_result_with_evidence() -> None:
    model = ScriptedModel([json_reply(FINAL)])
    petal = Petal("research", model, prompt="You are a market researcher.")
    run_ctx = ctx()

    result = await petal.run(Assignment("research", "What do customers expect?"), run_ctx)

    assert result.status is TaskStatus.COMPLETED
    assert result.conclusion == FINAL["conclusion"]
    assert result.evidence[0].source == "survey:q3"
    assert result.risks[0].level is RiskLevel.LOW
    assert result.confidence == 0.8
    assert [e.event_type for e in run_ctx.bus.events()] == [  # type: ignore[attr-defined]
        types.TASK_STARTED,
        types.TASK_COMPLETED,
    ]
    assert "You are a market researcher." in model.requests[0].messages[0].content


async def test_capabilities_can_be_given_by_setters() -> None:
    model = ScriptedModel([json_reply(FINAL)])
    skill = Skill.from_text("interviews", "Ask open questions.", "talking to customers")
    petal = (
        Petal("research")
        .set_model(model)
        .set_prompt("Researcher.")
        .add_skill(skill)
        .add_rag(InMemoryRetriever("survey", ["customers want discounts on yearly plans"]))
    )

    result = await petal.run(Assignment("research", "yearly plans discounts"), ctx())

    system = model.requests[0].messages[0].content
    user = model.requests[0].messages[1].content
    assert "## Skill: interviews" in system
    assert "customers want discounts" in user
    assert result.context_sources == ("survey:survey-0",)


async def test_skills_and_rag_outside_policy_are_withheld_and_reported() -> None:
    model = ScriptedModel([json_reply(FINAL)])
    petal = Petal(
        "research",
        model,
        skills=[Skill.from_text("secret-sauce", "never share this")],
        rag=[InMemoryRetriever("hr-records", ["salary data yearly"])],
        policy=Policy.for_petal("strict", skills=(), rag_sources=()),
    )
    run_ctx = ctx()

    await petal.run(Assignment("research", "yearly data"), run_ctx)

    request = model.requests[0]
    assert "secret-sauce" not in request.messages[0].content
    assert "salary" not in request.messages[1].content
    denied = run_ctx.bus.events(types.ACTION_DENIED)  # type: ignore[attr-defined]
    assert {e.payload["action"] for e in denied} == {"skill:secret-sauce", "rag:hr-records"}


async def test_only_allowed_tools_are_exposed_and_called() -> None:
    model = ScriptedModel(
        [
            reply("", tool_call("github__get_file", {"path": "billing.py"})),
            json_reply(FINAL),
        ]
    )
    petal = Petal(
        "engineer",
        model,
        mcp=[github()],
        policy=Policy.for_petal("eng", tools={"github/get_file"}),
    )
    run_ctx = ctx()

    result = await petal.run(Assignment("engineer", "read billing"), run_ctx)

    assert [t.name for t in model.requests[0].tools] == ["github__get_file"]
    tool_message = model.requests[1].messages[-1]
    assert tool_message.role == "tool" and tool_message.content == "contents of billing.py"
    assert result.actions == ("github/get_file",)
    called = run_ctx.bus.events(types.TOOL_CALLED)  # type: ignore[attr-defined]
    assert called[0].payload["argument_keys"] == ["path"]  # values are never published


async def test_a_denied_call_is_reported_to_the_model_not_executed() -> None:
    pushed: list[str] = []
    connection = github()

    async def spy(args: Mapping[str, Any]) -> str:
        pushed.append("yes")
        return "pushed"

    connection.add_tool(ToolSpec("push", "Push"), spy)
    model = ScriptedModel(
        [
            reply("", tool_call("github__push", {"ref": "main"})),
            json_reply(FINAL),
        ]
    )
    petal = Petal(
        "engineer", model, mcp=[connection], policy=Policy.for_petal("eng", tools={"github/*"})
    )
    petal.set_policy(Policy.for_petal("eng", tools={"github/get_file"}))  # tightened later

    await petal.run(Assignment("engineer", "push"), ctx())

    assert pushed == []
    assert model.requests[1].messages[-1].content.startswith("error: unknown tool")


async def test_tool_budget_is_enforced_at_call_time() -> None:
    model = ScriptedModel(
        [
            reply(
                "",
                tool_call("github__get_file", {"path": "a"}, "c1"),
                tool_call("github__get_file", {"path": "b"}, "c2"),
            ),
            json_reply(FINAL),
        ]
    )
    policy = Policy.for_petal("eng", tools={"github/get_file"}, max_tool_calls=1)
    run_ctx = ctx()

    result = await Petal("engineer", model, mcp=[github()], policy=policy).run(
        Assignment("engineer", "read two files"), run_ctx
    )

    outputs = [m.content for m in model.requests[1].messages if m.role == "tool"]
    assert outputs == ["contents of a", "denied: tool-call budget exhausted"]
    assert result.actions == ("github/get_file",)
    assert run_ctx.bus.events(types.ACTION_DENIED)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("gate", "executed"),
    [(None, False), (ApproveAllReviewGate(), True)],
)
async def test_review_tools_wait_for_the_gardener(gate: Any, executed: bool) -> None:
    calls: list[str] = []
    connection = InMemoryMcpConnection("deploy")

    async def production(_: Mapping[str, Any]) -> str:
        calls.append("deployed")
        return "ok"

    connection.add_tool(ToolSpec("production", "Deploy"), production)
    model = ScriptedModel([reply("", tool_call("deploy__production")), json_reply(FINAL)])
    petal = Petal(
        "ops", model, mcp=[connection], policy=Policy.for_petal("ops", review_tools={"deploy/*"})
    )
    run_ctx = ctx(**({"review_gate": gate} if gate else {}))

    await petal.run(Assignment("ops", "deploy"), run_ctx)

    assert (calls == ["deployed"]) is executed
    bus = run_ctx.bus
    assert bus.events(types.REVIEW_REQUESTED)  # type: ignore[attr-defined]
    resolved = bus.events(types.REVIEW_RESOLVED)  # type: ignore[attr-defined]
    assert resolved[0].payload["approved"] is executed


async def test_step_budget_exhaustion_fails_honestly() -> None:
    model = ScriptedModel(default=reply("", tool_call("github__get_file", {"path": "x"})))
    petal = Petal(
        "engineer",
        model,
        mcp=[github()],
        policy=Policy.for_petal("eng", tools={"github/get_file"}, max_steps=2),
    )
    run_ctx = ctx()

    result = await petal.run(Assignment("engineer", "loop forever"), run_ctx)

    assert result.status is TaskStatus.FAILED
    assert "step budget" in result.conclusion
    assert run_ctx.bus.events(types.TASK_FAILED)  # type: ignore[attr-defined]


async def test_unstructured_answers_are_kept_but_flagged() -> None:
    petal = Petal("writer", ScriptedModel(["Pay yearly, save more."]))
    result = await petal.run(Assignment("writer", "slogan"), ctx())
    assert result.succeeded
    assert result.conclusion == "Pay yearly, save more."
    assert result.confidence is None
    assert result.uncertainty and "unstructured" in result.uncertainty


async def test_model_errors_become_failed_results() -> None:
    def explode(_: ModelRequest) -> str:
        raise TimeoutError("provider down")

    result = await Petal("p", ScriptedModel([explode])).run(Assignment("p", "x"), ctx())
    assert result.status is TaskStatus.FAILED
    assert "provider down" in result.conclusion


async def test_a_petal_without_a_model_says_so() -> None:
    with pytest.raises(FoaaError, match="set_model"):
        await Petal("p").run(Assignment("p", "x"), ctx())
