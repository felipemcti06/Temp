"""Cache TM1 com TTL — memória L1 + SQLite L2 (compartilhado entre workers)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_TTL = 180
_DEFAULT_TTL = min(int(os.getenv("TM1_CACHE_TTL_SECONDS", "180")), _MAX_TTL)
_DB_PATH = os.getenv("TM1_CACHE_DB_PATH", "/tmp/tm1_cache.db")

_store: dict[str, tuple[float, dict[str, Any]]] = {}
_stats = {"hits": 0, "misses": 0, "sets": 0}
_lock = threading.Lock()


def cache_ttl_seconds() -> int:
    configured = int(os.getenv("TM1_CACHE_TTL_SECONDS", str(_DEFAULT_TTL)))
    return min(max(configured, 0), _MAX_TTL)


def cache_enabled() -> bool:
    return cache_ttl_seconds() > 0


def sqlite_enabled() -> bool:
    return os.getenv("TM1_CACHE_SQLITE", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def normalize_query_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Chave canônica estável — não depende do texto livre do prompt."""
    normalized = {
        "connection_id": payload.get("connection_id"),
        "cube_name": payload.get("cube_name"),
        "metric": (payload.get("metric") or "").strip().lower() or None,
        "year": str(payload.get("year") or ""),
        "version": payload.get("version") or "REAL",
        "account": payload.get("account"),
        "measure": payload.get("measure"),
        "group_by": payload.get("group_by"),
    }
    return {k: v for k, v in normalized.items() if v is not None}


def cache_key(namespace: str, payload: dict[str, Any]) -> str:
    canonical = normalize_query_payload(payload)
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"{namespace}:{digest}"


def _cache_key(namespace: str, payload: dict[str, Any]) -> str:
    return cache_key(namespace, payload)


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tm1_cache (
            key TEXT PRIMARY KEY,
            expires_at REAL NOT NULL,
            value TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _sqlite_get(key: str) -> tuple[float, dict[str, Any]] | None:
    if not sqlite_enabled():
        return None

    try:
        Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            conn = sqlite3.connect(_DB_PATH, timeout=5)
            try:
                _init_db(conn)
                row = conn.execute(
                    "SELECT expires_at, value FROM tm1_cache WHERE key = ?",
                    (key,),
                ).fetchone()
            finally:
                conn.close()
    except sqlite3.Error as exc:
        logger.warning("TM1 cache SQLite read failed: %s", exc)
        return None

    if not row:
        return None

    expires_at, raw = row
    if expires_at <= time.time():
        _sqlite_delete(key)
        return None

    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        _sqlite_delete(key)
        return None

    if not isinstance(value, dict):
        return None
    return expires_at, value


def _sqlite_set(key: str, expires_at: float, value: dict[str, Any]) -> None:
    if not sqlite_enabled():
        return

    try:
        Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            conn = sqlite3.connect(_DB_PATH, timeout=5)
            try:
                _init_db(conn)
                conn.execute(
                    """
                    INSERT INTO tm1_cache (key, expires_at, value)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        expires_at = excluded.expires_at,
                        value = excluded.value
                    """,
                    (key, expires_at, json.dumps(value, ensure_ascii=False, default=str)),
                )
                conn.commit()
            finally:
                conn.close()
    except sqlite3.Error as exc:
        logger.warning("TM1 cache SQLite write failed: %s", exc)


def _sqlite_delete(key: str) -> None:
    if not sqlite_enabled():
        return

    try:
        with _lock:
            conn = sqlite3.connect(_DB_PATH, timeout=5)
            try:
                _init_db(conn)
                conn.execute("DELETE FROM tm1_cache WHERE key = ?", (key,))
                conn.commit()
            finally:
                conn.close()
    except sqlite3.Error:
        pass


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
    if entry:
        expires_at, value = entry
        if expires_at > time.time():
            _stats["hits"] += 1
            cached = dict(value)
            cached["_cached"] = True
            logger.info("TM1 cache HIT (memory) key=%s", key)
            return cached
        _store.pop(key, None)

    sqlite_entry = _sqlite_get(key)
    if sqlite_entry:
        expires_at, value = sqlite_entry
        _store[key] = (expires_at, value)
        _stats["hits"] += 1
        cached = dict(value)
        cached["_cached"] = True
        logger.info("TM1 cache HIT (sqlite) key=%s", key)
        return cached

    _stats["misses"] += 1
    logger.info("TM1 cache MISS key=%s", key)
    return None


def set_cached(namespace: str, payload: dict[str, Any], value: dict[str, Any]) -> None:
    if not cache_enabled():
        return

    ttl = cache_ttl_seconds()
    key = _cache_key(namespace, payload)
    stored = {k: v for k, v in value.items() if not str(k).startswith("_")}
    expires_at = time.time() + ttl
    _store[key] = (expires_at, stored)
    _sqlite_set(key, expires_at, stored)
    _stats["sets"] += 1
    logger.info("TM1 cache SET key=%s ttl=%ss", key, ttl)


def cache_stats() -> dict[str, Any]:
    _cleanup()
    now = time.time()
    entries = []
    for key, (expires_at, _) in _store.items():
        entries.append(
            {
                "key": key,
                "expires_in_seconds": max(0, int(expires_at - now)),
                "layer": "memory",
            }
        )

    sqlite_entries = 0
    if sqlite_enabled():
        try:
            with _lock:
                conn = sqlite3.connect(_DB_PATH, timeout=5)
                try:
                    _init_db(conn)
                    sqlite_entries = conn.execute(
                        "SELECT COUNT(*) FROM tm1_cache WHERE expires_at > ?",
                        (now,),
                    ).fetchone()[0]
                finally:
                    conn.close()
        except sqlite3.Error:
            sqlite_entries = 0

    return {
        "enabled": cache_enabled(),
        "sqlite": sqlite_enabled(),
        "db_path": _DB_PATH if sqlite_enabled() else None,
        "ttl_seconds": cache_ttl_seconds(),
        "entries": max(len(_store), sqlite_entries),
        "memory_entries": len(_store),
        "sqlite_entries": sqlite_entries,
        "hits": _stats["hits"],
        "misses": _stats["misses"],
        "sets": _stats["sets"],
        "hit_rate": round(
            _stats["hits"] / max(_stats["hits"] + _stats["misses"], 1),
            3,
        ),
        "items": entries[:20],
    }
