import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple


class TTLCache:
    """Thread-safe in-memory cache with per-entry TTL."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._store: Dict[Any, Tuple[datetime, Any]] = {}
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()

    def get(self, key: Any) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            expires_at, value = entry
            if datetime.now() > expires_at:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return value

    def set(self, key: Any, value: Any) -> None:
        with self._lock:
            self._store[key] = (datetime.now() + self._ttl, value)

    def clear(self) -> int:
        """Clear all entries; returns the number of entries removed."""
        with self._lock:
            count = len(self._store)
            self._store.clear()
            return count

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "entries": len(self._store),
                "hits": self._hits,
                "misses": self._misses,
            }
