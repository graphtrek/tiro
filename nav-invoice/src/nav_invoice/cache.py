"""Simple thread-safe TTL in-memory cache."""

import time
from threading import Lock
from typing import Any, Optional

_store: dict[str, tuple[Any, float]] = {}
_lock = Lock()


def get(key: str) -> Optional[Any]:
    with _lock:
        entry = _store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del _store[key]
            return None
        return value


def set(key: str, value: Any, ttl: int) -> None:  # noqa: A001
    with _lock:
        _store[key] = (value, time.monotonic() + ttl)


def clear() -> int:
    """Remove all entries; return the number cleared."""
    with _lock:
        count = len(_store)
        _store.clear()
        return count


def size() -> int:
    """Return the number of non-expired entries."""
    with _lock:
        now = time.monotonic()
        return sum(1 for _, (_, exp) in _store.items() if now <= exp)
