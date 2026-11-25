"""The conformance kit itself is tested with fake models: a correct one and broken ones."""

from __future__ import annotations

from foaa import ModelRequest, ModelResponse, StopReason, ToolCall
from foaa.testing.conformance import WEATHER_TOOL, run_conformance


class WellBehavedModel:
    """Answers the way a correct adapter over a capable model would."""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        usage = {"input_tokens": 10, "output_tokens": 2}
        last = request.messages[-1]
        if last.role == "tool":
            text = "It is sunny and 25C." if not last.is_error else "The service is down."
            return ModelResponse(text, usage=usage, stop_reason=StopReason.END)
        if request.tools:
            call = ToolCall("call_1", WEATHER_TOOL.name, {"city": "Lisbon"})
            return ModelResponse(
                "", (call,), usage, StopReason.TOOL_USE, provider_content=["native-block"]
            )
        if any(m.role == "system" and "PINEAPPLE" in m.content for m in request.messages):
            return ModelResponse("PINEAPPLE", usage=usage, stop_reason=StopReason.END)
        return ModelResponse("ready", usage=usage, stop_reason=StopReason.END)


async def test_a_correct_adapter_passes_every_check() -> None:
    model = WellBehavedModel()
    report = await run_conformance(model)
    assert report.passed, report.summary()
    assert not report.failures

    # the round trip replays the assistant turn with its native content and the same id
    round_trip = next(r for r in model.requests if r.messages[-1].role == "tool")
    assert round_trip.messages[1].provider_content == ["native-block"]
    assert round_trip.messages[2].tool_call_id == "call_1"


class ArgumentsAsString(WellBehavedModel):
    """A classic adapter bug: forwarding the provider's JSON string instead of parsing it."""

    async def complete(self, request: ModelRequest) -> ModelResponse:
        response = await super().complete(request)
        if response.tool_calls:
            call = response.tool_calls[0]
            broken = ToolCall(call.id, call.name, '{"city": "Lisbon"}')  # type: ignore[arg-type]
            return ModelResponse("", (broken,), response.usage, StopReason.TOOL_USE)
        return response


async def test_unparsed_arguments_are_caught() -> None:
    report = await run_conformance(ArgumentsAsString())
    assert not report.passed
    failed = {r.name: r.detail for r in report.failures}
    assert "parsed mapping" in failed["tool call"]


class RenamesTools(WellBehavedModel):
    async def complete(self, request: ModelRequest) -> ModelResponse:
        response = await super().complete(request)
        if response.tool_calls:
            call = response.tool_calls[0]
            renamed = ToolCall(call.id, "get_current", call.arguments)
            return ModelResponse("", (renamed,), response.usage, StopReason.TOOL_USE)
        return response


async def test_renamed_tools_are_caught() -> None:
    report = await run_conformance(RenamesTools())
    assert "tool name changed" in next(r.detail for r in report.failures if r.name == "tool call")


class NoUsage(WellBehavedModel):
    async def complete(self, request: ModelRequest) -> ModelResponse:
        response = await super().complete(request)
        return ModelResponse(response.content, response.tool_calls, {}, response.stop_reason)


async def test_missing_usage_is_only_a_warning() -> None:
    report = await run_conformance(NoUsage())
    assert report.passed
    assert [r.name for r in report.failures] == ["token usage reported"]
    assert "[WARN] token usage reported" in report.summary()


async def test_an_exception_fails_only_its_check() -> None:
    class Explodes:
        async def complete(self, request: ModelRequest) -> ModelResponse:
            raise ConnectionError("no network")

    report = await run_conformance(Explodes())
    assert not report.passed
    assert all(
        "ConnectionError" in r.detail
        or "skipped" in r.detail
        or "no response" in r.detail
        or "stop_reason" in r.detail
        for r in report.failures
    )
