import hashlib
import json
import time
from typing import Optional

from app.core.config import settings


class LLMResponseCache:
    def __init__(self, ttl_seconds: int = 3600, max_entries: int = 500):
        self._ttl = ttl_seconds
        self._max = max_entries
        self._cache: dict[str, tuple[float, str]] = {}

    def _make_key(self, text: str, mode: str) -> str:
        raw = f"{mode}||{text}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, text: str, mode: str) -> Optional[str]:
        key = self._make_key(text, mode)
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.monotonic() - ts > self._ttl:
            del self._cache[key]
            return None
        return value

    def set(self, text: str, mode: str, response: str):
        key = self._make_key(text, mode)
        self._cache[key] = (time.monotonic(), response)
        if len(self._cache) > self._max:
            self._evict()

    def invalidate(self, text: str, mode: str):
        key = self._make_key(text, mode)
        self._cache.pop(key, None)

    def _evict(self):
        cutoff = time.monotonic() - self._ttl
        stale = [k for k, (ts, _) in self._cache.items() if ts < cutoff]
        for k in stale:
            del self._cache[k]
        if len(self._cache) > self._max:
            sorted_items = sorted(self._cache.items(), key=lambda x: x[1][0])
            for k, _ in sorted_items[:len(self._cache) - self._max]:
                del self._cache[k]

    def clear(self):
        self._cache.clear()


llm_response_cache = LLMResponseCache()
