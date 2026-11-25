"""Event consumers.

A listener is any async callable that receives an :class:`EventEnvelope`. Listeners MUST be
idempotent: transports may deliver the same event more than once (Constitution, Principle V).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeAlias

from foaa.edd.events import EventEnvelope

Listener: TypeAlias = Callable[[EventEnvelope], Awaitable[None]]

__all__ = ["Listener"]
