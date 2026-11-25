"""Event contracts: the envelope and the catalog of event types."""

from foaa.edd.events import types
from foaa.edd.events.envelope import ENVELOPE_SCHEMA_VERSION, EventEnvelope

__all__ = ["ENVELOPE_SCHEMA_VERSION", "EventEnvelope", "types"]
