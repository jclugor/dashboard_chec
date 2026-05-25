from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
import time
from typing import Any


@dataclass(frozen=True)
class CacheEntry:
    value: Any
    expires_at: float


class TTLMemoryCache:
    """Small in-memory TTL cache for safe shared computations.

    Keep this for non-user-specific results only. In multi-worker deployments each
    worker process has its own cache, so total memory usage scales with worker count.
    """

    def __init__(self, max_entries: int = 64):
        self._max_entries = max_entries
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> Any | None:
        now = time.time()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at < now:
                self._entries.pop(key, None)
                return None
            self._entries.move_to_end(key)
            return entry.value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        expires_at = time.time() + max(ttl_seconds, 0)
        with self._lock:
            self._entries[key] = CacheEntry(value=value, expires_at=expires_at)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)


CACHE = TTLMemoryCache(max_entries=96)



def build_cache_key(*parts: str) -> str:
    return "|".join(part.strip() for part in parts)
