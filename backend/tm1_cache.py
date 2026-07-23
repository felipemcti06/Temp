"""Cache em memória para consultas TM1 (TTL máximo 3 minutos)."""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

_MAX_TTL = 180
_DEFAULT_TTL = min(int(os.getenv("TM1_CACHE_TTL_SECONDS", "180")), _MAX_TTL)

_store: dict[str, tuple[float, dict[str, Any]]] = {}


def cache_ttl_seconds() -> int:
    configured = int(os.getenv("TM1_CACHE_TTL_SECONDS", str(_DEFAULT_TTL)))
    return min(max(configured, 0), _MAX_TTL)


def cache_enabled() -> bool:
    return cache_ttl_seconds() > 0


def _cache_key(namespace: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"{namespace}:{digest}"


def _cleanup(now: float | None = None) -> None:
    ts = now if now is not None else time.time()
    expired = [key for key, (expires_at, _) in _store.items() if expires_at <= ts]
    for key in expired:
        _store.pop(key, None)


def get_cached(namespace: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if not cache_enabled():
        return None

    _cleanup()
    key = _cache_key(namespace, payload)
    entry = _store.get(key)
    if not entry:
        return None

    expires_at, value = entry
    if expires_at <= time.time():
        _store.pop(key, None)
        return None

    cached = dict(value)
    cached["_cached"] = True
    return cached


def set_cached(namespace: str, payload: dict[str, Any], value: dict[str, Any]) -> None:
    if not cache_enabled():
        return

    ttl = cache_ttl_seconds()
    key = _cache_key(namespace, payload)
    stored = {k: v for k, v in value.items() if not str(k).startswith("_")}
    _store[key] = (time.time() + ttl, stored)
