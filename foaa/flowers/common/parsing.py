"""Tolerant extraction of the JSON contracts that models are asked to follow."""

from __future__ import annotations

import json
import re
from typing import Any

from foaa.common import ModelOutputError

_FENCED = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def extract_json_object(text: str) -> dict[str, Any]:
    """Return the first JSON object found in a model answer.

    Accepts a fenced ```json block, a bare object, or an object surrounded by prose.
    Raises :class:`ModelOutputError` when nothing usable is found.
    """
    candidates = [match.group(1) for match in _FENCED.finditer(text)]
    candidates.append(text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ModelOutputError("the model answer does not contain a JSON object")


def as_str(value: Any, default: str = "") -> str:
    return value.strip() if isinstance(value, str) else default


def as_float_01(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if 0.0 <= number <= 1.0 else None


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
