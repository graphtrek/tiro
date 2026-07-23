"""Template rendering utilities for vision UI."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

_ISO_DT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
# invoice-core stores/serializes timestamps as naive UTC (datetime.utcnow()) — convert
# to local wall-clock time here so templates never have to think about it.
_LOCAL_TZ = ZoneInfo("Europe/Budapest")


def _parse_leaf(v):
    if isinstance(v, str) and _ISO_DT.match(v):
        try:
            dt = datetime.fromisoformat(v)
        except ValueError:
            return v
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_LOCAL_TZ)
    return v


def dict_to_ns(obj):
    """Recursively convert dicts → SimpleNamespace so templates can use dot-notation.
    ISO datetime strings are parsed back to datetime objects."""
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: dict_to_ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [dict_to_ns(i) for i in obj]
    return _parse_leaf(obj)
