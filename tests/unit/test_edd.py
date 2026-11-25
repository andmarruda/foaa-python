from __future__ import annotations

from foaa import EventEnvelope, InMemoryEventBus


def event(event_type: str = "petal.task.completed") -> EventEnvelope:
    return EventEnvelope(event_type=event_type, flower_id="f", correlation_id="goal")


async def test_bus_delivers_by_pattern_and_records_history() -> None:
    bus = InMemoryEventBus()
    seen: list[str] = []

    async def listener(e: EventEnvelope) -> None:
        seen.append(e.event_type)

    bus.subscribe("petal.*", listener)
    await bus.publish(event("petal.task.completed"))
    await bus.publish(event("center.plan.created"))

    assert seen == ["petal.task.completed"]
    assert [e.event_type for e in bus.history] == ["petal.task.completed", "center.plan.created"]


async def test_bus_is_idempotent_per_event_id() -> None:
    bus = InMemoryEventBus()
    calls = 0

    async def listener(_: EventEnvelope) -> None:
        nonlocal calls
        calls += 1

    bus.subscribe("*", listener)
    same = event()
    await bus.publish(same)
    await bus.publish(same)
    assert calls == 1


async def test_failing_listener_does_not_break_the_publisher() -> None:
    bus = InMemoryEventBus()

    async def broken(_: EventEnvelope) -> None:
        raise RuntimeError("boom")

    bus.subscribe("*", broken)
    await bus.publish(event())
    assert len(bus.failures) == 1


def test_caused_event_keeps_the_goal_and_links_the_cause() -> None:
    first = event("flower.objective.received")
    second = first.caused("center.plan.created")
    assert second.correlation_id == first.correlation_id
    assert second.causation_id == first.event_id
    assert second.event_id != first.event_id
