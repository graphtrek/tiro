"""Template rendering utilities for vision UI."""

from __future__ import annotations

import re
from datetime import datetime
from types import SimpleNamespace

_ISO_DT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _parse_leaf(v):
    if isinstance(v, str) and _ISO_DT.match(v):
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            pass
    return v


def dict_to_ns(obj):
    """Recursively convert dicts → SimpleNamespace so templates can use dot-notation.
    ISO datetime strings are parsed back to datetime objects."""
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: dict_to_ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [dict_to_ns(i) for i in obj]
    return _parse_leaf(obj)
