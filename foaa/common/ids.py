from __future__ import annotations

import uuid


def new_id(prefix: str) -> str:
    """Return a unique, human-readable identifier such as ``evt_3f2a...``."""
    return f"{prefix}_{uuid.uuid4().hex}"
