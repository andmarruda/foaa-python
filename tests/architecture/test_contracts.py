"""Fitness functions for the event and result contracts (Constitution, Principle V)."""

from __future__ import annotations

import dataclasses

import pytest

from foaa import EventEnvelope, FlowerDecision, PetalResult, RiskLevel
from foaa.edd.events import types

REQUIRED_ENVELOPE_FIELDS = {
    "event_id",
    "event_type",
    "event_version",
    "occurred_at",
    "flower_id",
    "correlation_id",
    "causation_id",
    "risk_level",
    "requires_review",
}


def test_envelope_carries_every_required_field() -> None:
    fields = {f.name for f in dataclasses.fields(EventEnvelope)}
    assert fields >= REQUIRED_ENVELOPE_FIELDS


@pytest.mark.parametrize("event_type", sorted(types.ALL_EVENT_TYPES))
def test_event_types_are_meaningful_dotted_names(event_type: str) -> None:
    domain, *rest = event_type.split(".")
    assert domain in {"flower", "center", "petal", "root", "branch", "governance"}
    assert len(rest) >= 2, f"{event_type} should read as <domain>.<subject>.<outcome>"


def test_every_contract_is_versioned() -> None:
    for contract in (EventEnvelope, PetalResult, FlowerDecision):
        assert "schema_version" in {f.name for f in dataclasses.fields(contract)}


def test_envelope_rejects_signals_without_origin() -> None:
    with pytest.raises(ValueError):
        EventEnvelope(event_type="petal.task.completed", flower_id="", correlation_id="g")
    with pytest.raises(ValueError):
        EventEnvelope(event_type="petal.task.completed", flower_id="f", correlation_id="")
    with pytest.raises(ValueError):
        EventEnvelope(event_type="nodots", flower_id="f", correlation_id="g")
    with pytest.raises(ValueError):
        EventEnvelope(event_type="a.b.c", flower_id="f", correlation_id="g", event_version=0)


def test_envelope_serializes_to_plain_data() -> None:
    event = EventEnvelope(
        event_type="petal.task.completed",
        flower_id="f",
        correlation_id="g",
        payload={"x": 1},
        risk_level=RiskLevel.HIGH,
    )
    data = event.to_dict()
    assert data["risk_level"] == "high"
    assert data["payload"] == {"x": 1}
    assert isinstance(data["occurred_at"], str)
