"""Conformance kit for LLM adapters: "is my adapter right?" becomes a test that passes.

Run it against any :class:`~foaa.flowers.common.ModelPort` backed by a real model::

    from foaa.testing.conformance import assert_conformance

    async def test_my_adapter() -> None:
        await assert_conformance(MyAdapter(client, model="..."))

Or get a report without raising::

    report = await run_conformance(adapter)
    print(report.summary())

The checks call the real model (it costs a few small requests). They exercise exactly what
FOAA's harness relies on: plain answers, system prompts, tool calls with parsed arguments,
returning tool results (including errors) with the same id, and replaying the assistant turn.

Model answers are not perfectly deterministic. The prompts are written so that any capable
tool-calling model passes; a failure is a strong signal that the *adapter* mistranslates,
but read its ``detail`` before blaming the code.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from foaa.flowers.common import (
    Message,
    ModelPort,
    ModelRequest,
    ModelResponse,
    StopReason,
    ToolSpec,
)

WEATHER_TOOL = ToolSpec(
    # Same shape FOAA produces for MCP tools: "<connection>__<tool>".
    name="weather__get_current",
    description="Get the current weather for a city.",
    input_schema={
        "type": "object",
        "properties": {"city": {"type": "string", "description": "City name"}},
        "required": ["city"],
    },
    read_only=True,
)

TOOL_PROMPT = "What is the weather in Lisbon right now? Use the weather tool; do not guess."


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    required: bool = True


@dataclass
class ConformanceReport:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results if r.required)

    @property
    def failures(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed]

    def summary(self) -> str:
        lines = []
        for r in self.results:
            mark = "PASS" if r.passed else ("FAIL" if r.required else "WARN")
            lines.append(f"[{mark}] {r.name}" + (f": {r.detail}" if r.detail else ""))
        return "\n".join(lines)

    def raise_for_failures(self) -> None:
        failed = [r for r in self.failures if r.required]
        if failed:
            raise AssertionError("adapter is not conformant:\n" + self.summary())


Check = Callable[[ModelPort, dict[str, Any]], Awaitable[CheckResult]]


def _request(*messages: Message, tools: tuple[ToolSpec, ...] = ()) -> ModelRequest:
    return ModelRequest(messages=tuple(messages), tools=tools, metadata={"foaa.check": "true"})


def _shape_problems(response: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(response, ModelResponse):
        return [f"complete() returned {type(response).__name__}, expected ModelResponse"]
    if not isinstance(response.content, str):
        problems.append("content must be a str")
    if not isinstance(response.tool_calls, tuple):
        problems.append("tool_calls must be a tuple")
    if not isinstance(response.usage, Mapping):
        problems.append("usage must be a mapping")
    return problems


async def check_text_reply(model: ModelPort, state: dict[str, Any]) -> CheckResult:
    response = await model.complete(_request(Message.user("Reply with exactly one word: ready")))
    problems = _shape_problems(response)
    if problems:
        return CheckResult("text reply", False, "; ".join(problems))
    if not response.content.strip():
        return CheckResult("text reply", False, "empty content for a plain question")
    if response.tool_calls:
        return CheckResult("text reply", False, "tool calls returned although no tools were sent")
    state["text_response"] = response
    return CheckResult("text reply", True)


async def check_system_prompt(model: ModelPort, state: dict[str, Any]) -> CheckResult:
    response = await model.complete(
        _request(
            Message.system("Whatever the user says, answer with exactly the word PINEAPPLE."),
            Message.user("Tell me about the ocean."),
        )
    )
    ok = "pineapple" in response.content.lower()
    return CheckResult(
        "system prompt is honored",
        ok,
        "" if ok else f"system instruction ignored; got {response.content[:80]!r}",
    )


async def check_tool_call(model: ModelPort, state: dict[str, Any]) -> CheckResult:
    response = await model.complete(_request(Message.user(TOOL_PROMPT), tools=(WEATHER_TOOL,)))
    if not response.tool_calls:
        return CheckResult("tool call", False, f"no tool call; content={response.content[:80]!r}")
    call = response.tool_calls[0]
    problems = []
    if call.name != WEATHER_TOOL.name:
        problems.append(f"tool name changed: {call.name!r} != {WEATHER_TOOL.name!r}")
    if not call.id:
        problems.append("tool call has no id")
    if not isinstance(call.arguments, Mapping):
        problems.append("arguments must be a parsed mapping, not a JSON string")
    elif "lisbon" not in str(call.arguments.get("city", "")).lower():
        problems.append(f"unexpected arguments {dict(call.arguments)!r}")
    if response.stop_reason not in (None, StopReason.TOOL_USE):
        problems.append(f"stop_reason should be 'tool_use', got {response.stop_reason!r}")
    if problems:
        return CheckResult("tool call", False, "; ".join(problems))
    state["tool_response"] = response
    return CheckResult("tool call", True)


async def _round_trip(
    model: ModelPort, state: dict[str, Any], result: str, is_error: bool
) -> ModelResponse | str:
    first: ModelResponse | None = state.get("tool_response")
    if first is None:
        return "skipped: the tool call check did not pass"
    call = first.tool_calls[0]
    return await model.complete(
        _request(
            Message.user(TOOL_PROMPT),
            Message.assistant(
                first.content, first.tool_calls, provider_content=first.provider_content
            ),
            Message.tool(call.id, result, is_error=is_error),
            tools=(WEATHER_TOOL,),
        )
    )


async def check_tool_result_round_trip(model: ModelPort, state: dict[str, Any]) -> CheckResult:
    name = "tool result round trip (same id, assistant turn replayed)"
    response = await _round_trip(model, state, "Sunny, 25 degrees Celsius in Lisbon.", False)
    if isinstance(response, str):
        return CheckResult(name, False, response)
    text = response.content.lower()
    ok = "25" in text or "sunny" in text
    return CheckResult(name, ok, "" if ok else f"result not used; got {response.content[:80]!r}")


async def check_tool_error_round_trip(model: ModelPort, state: dict[str, Any]) -> CheckResult:
    name = "failed tool result is accepted"
    response = await _round_trip(model, state, "error: weather service unavailable", True)
    if isinstance(response, str):
        return CheckResult(name, False, response)
    return CheckResult(name, True)


async def check_usage(model: ModelPort, state: dict[str, Any]) -> CheckResult:
    response: ModelResponse | None = state.get("text_response")
    if response is None:
        return CheckResult("token usage reported", False, "no response to inspect", required=False)
    ok = {"input_tokens", "output_tokens"} <= set(response.usage)
    detail = "" if ok else f"usage keys: {sorted(response.usage)}"
    return CheckResult("token usage reported", ok, detail, required=False)


async def check_stop_reason(model: ModelPort, state: dict[str, Any]) -> CheckResult:
    response: ModelResponse | None = state.get("text_response")
    ok = response is not None and response.stop_reason == StopReason.END
    detail = "" if ok else f"stop_reason={getattr(response, 'stop_reason', None)!r}, expected 'end'"
    return CheckResult("stop reason normalized", ok, detail, required=False)


ALL_CHECKS: tuple[Check, ...] = (
    check_text_reply,
    check_system_prompt,
    check_tool_call,
    check_tool_result_round_trip,
    check_tool_error_round_trip,
    check_usage,
    check_stop_reason,
)


async def run_conformance(
    model: ModelPort, checks: tuple[Check, ...] = ALL_CHECKS
) -> ConformanceReport:
    """Run every check; an exception inside one check fails that check only."""
    report = ConformanceReport()
    state: dict[str, Any] = {}
    for check in checks:
        try:
            report.results.append(await check(model, state))
        except Exception as error:
            name = check.__name__.removeprefix("check_").replace("_", " ")
            report.results.append(CheckResult(name, False, f"{type(error).__name__}: {error}"))
    return report


async def assert_conformance(model: ModelPort) -> ConformanceReport:
    """Run the kit and raise ``AssertionError`` listing every required check that failed."""
    report = await run_conformance(model)
    report.raise_for_failures()
    return report
