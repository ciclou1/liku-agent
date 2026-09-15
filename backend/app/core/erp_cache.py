"""Small Redis-backed cache for read-only ERP analysis responses."""

from __future__ import annotations

import json
import logging
from time import monotonic
from typing import Any

import redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class ErpAnalysisCache:
    def __init__(self) -> None:
        settings = get_settings()
        self.ttl = settings.erp_analysis_cache_ttl_seconds
        self.client = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=0.3,
            socket_timeout=0.3,
            decode_responses=True,
        )
        self.local: dict[str, tuple[float, dict[str, Any]]] = {}
        self.redis_disabled = False   # Redis 不可达时置 True，后续直接走进程内存，避免每次超时

    def _redis_get(self, key: str) -> dict[str, Any] | None:
        if self.redis_disabled:
            return None
        try:
            raw = self.client.get(key)
            if raw:
                return json.loads(raw)
        except Exception:  # noqa: BLE001 - cache must never break ERP reads
            logger.warning("redis cache unreachable, falling back to in-memory cache")
            self.redis_disabled = True
        return None

    def _redis_set(self, key: str, value: dict[str, Any]) -> None:
        if self.redis_disabled:
            return
        try:
            self.client.setex(key, self.ttl, json.dumps(value, ensure_ascii=False, default=str))
        except Exception:  # noqa: BLE001 - retain local fallback
            logger.warning("redis cache unreachable, falling back to in-memory cache")
            self.redis_disabled = True

    def get(self, key: str) -> dict[str, Any] | None:
        cached = self._redis_get(key)
        if cached is not None:
            return cached
        entry = self.local.get(key)
        if entry and entry[0] > monotonic():
            return entry[1]
        self.local.pop(key, None)
        return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._redis_set(key, value)
        self.local[key] = (monotonic() + self.ttl, value)

    def clear(self) -> None:
        self.local.clear()


erp_analysis_cache = ErpAnalysisCache()
