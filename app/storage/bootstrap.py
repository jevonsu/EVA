"""Initialize storage engine, schema, and optional JSON migration."""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.config import get_settings
from app.storage.engine import create_tables, db_connect, dispose_engine, get_engine
from app.storage.migrate_json import migrate_from_json
from app.storage.settings import (
    StorageSettings,
    get_storage_settings,
    save_storage_settings,
)

logger = logging.getLogger("app.storage.bootstrap")

_ready = False
_lock = threading.Lock()


def _unconfigured_remote(cfg: StorageSettings) -> bool:
    return cfg.backend != "sqlite" and not (cfg.username or "").strip() and not (cfg.password or "")


def _use_sqlite_fallback(cfg: StorageSettings, reason: str) -> StorageSettings:
    logger.warning(
        "Storage backend=%s (%s:%s/%s) unusable (%s); using local sqlite",
        cfg.backend,
        cfg.host,
        cfg.dialect_default_port(),
        cfg.database,
        reason,
    )
    fallback = StorageSettings(
        sqlite_path=cfg.sqlite_path or "eva.db",
        migrated_from_json=bool(cfg.migrated_from_json),
    )
    save_storage_settings(fallback)
    dispose_engine()
    return get_storage_settings(force=True)


def _open_storage(cfg: StorageSettings, *, force: bool) -> tuple[StorageSettings, dict[str, int]]:
    logger.info("Storage connecting backend=%s", _safe_url(cfg))
    eng = get_engine(force=force)
    create_tables(eng)
    with db_connect() as conn:
        counts = migrate_from_json(conn, get_settings().data_dir)
    return cfg, counts


def ensure_storage(
    *,
    force_reconnect: bool = False,
    fallback_sqlite: bool = True,
) -> dict[str, Any]:
    """Create tables and migrate JSON once. Safe to call repeatedly."""
    global _ready
    with _lock:
        if force_reconnect:
            dispose_engine()
            get_storage_settings(force=True)
            _ready = False
        cfg = get_storage_settings()
        if fallback_sqlite and _unconfigured_remote(cfg):
            cfg = _use_sqlite_fallback(cfg, "no username/password")
        try:
            cfg, counts = _open_storage(cfg, force=force_reconnect)
        except Exception as exc:
            if cfg.backend == "sqlite" or not fallback_sqlite:
                raise
            cfg = _use_sqlite_fallback(cfg, str(exc)[:240])
            cfg, counts = _open_storage(cfg, force=True)
        if counts and any(counts.values()) and not cfg.migrated_from_json:
            cfg.migrated_from_json = True
            save_storage_settings(cfg)
        _ready = True
        summary = {
            "ok": True,
            "backend": cfg.backend,
            "url_safe": _safe_url(cfg),
            "migrated": counts,
        }
        logger.info("Storage ready: backend=%s migrated=%s", cfg.backend, counts)
        return summary


def reset_storage() -> None:
    global _ready
    with _lock:
        dispose_engine()
        get_storage_settings(force=True)
        _ready = False


def storage_ready() -> bool:
    return _ready


def _safe_url(cfg) -> str:
    if cfg.backend == "sqlite":
        return f"sqlite:///{cfg.sqlite_path}"
    return f"{cfg.backend}://{cfg.host}:{cfg.dialect_default_port()}/{cfg.database}"
