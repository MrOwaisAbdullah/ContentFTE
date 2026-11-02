"""Bounded, expiring Idempotency-Key cache (ENG-14).

The first version was a plain module dict: no TTL despite the documented 24 hours, no size limit (a
client sending a fresh key per request grew it for the life of the process) and callers were handed the
cached object itself, so one response mutated by a later handler corrupted every replay.

Still per process - with several workers a retry that lands on another worker is not replayed. The
engine's writes are individually safe to repeat (`submit_article` upserts by keyword), so this cache is a
latency/duplicate-suppression convenience, not a correctness guarantee. A shared (database) store is
tracked as ENG-14 / OPS-02.
"""
from __future__ import annotations

import copy
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Optional

DEFAULT_TTL_SECONDS = 24 * 3600
DEFAULT_MAX_ENTRIES = 5000


class IdempotencyCache:
    def __init__(self, ttl: float = DEFAULT_TTL_SECONDS, max_entries: int = DEFAULT_MAX_ENTRIES,
                 clock: Callable[[], float] = time.monotonic, shared: bool = False):
        # `shared=True` also writes through to the database (lib/lease.py), so a retry that lands on another
        # worker is replayed too. The in-memory copy stays as the fast path and the fallback.
        self.shared = shared
        self.ttl = ttl
        self.max_entries = max(1, int(max_entries))
        self._clock = clock
        self._items: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[dict]:
        if self.shared:
            from lib import lease
            hit = lease.idem_get(key)
            if hit is not None:
                return hit
        with self._lock:
            hit = self._items.get(key)
            if hit is None:
                return None
            stored_at, value = hit
            if self._clock() - stored_at > self.ttl:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return copy.deepcopy(value)

    def set(self, key: str, value: dict) -> None:
        if self.shared:
            from lib import lease
            lease.idem_put(key, value)
        with self._lock:
            self._items[key] = (self._clock(), copy.deepcopy(value))
            self._items.move_to_end(key)
            self._evict_locked()

    def _evict_locked(self) -> None:
        now = self._clock()
        # oldest first: drop expired entries, then enforce the size cap
        while self._items:
            key, (stored_at, _) = next(iter(self._items.items()))
            if now - stored_at > self.ttl or len(self._items) > self.max_entries:
                del self._items[key]
            else:
                break

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None
