"""SQLAlchemy engine factory (sync; stores use asyncio.to_thread for async APIs)."""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.storage.schema import metadata
from app.storage.settings import StorageSettings, get_storage_settings

logger = logging.getLogger("app.storage.engine")

_lock = threading.RLock()
_engine: Engine | None = None
_engine_url: str | None = None


_REMOTE_CONNECT_TIMEOUT = 3


def _remote_connect_args(cfg: StorageSettings) -> dict[str, Any]:
    """Fail fast so a down Postgres/MySQL cannot stall Eva startup."""
    if cfg.backend == "postgresql":
        return {"connect_timeout": _REMOTE_CONNECT_TIMEOUT}
    if cfg.backend in ("mysql", "mariadb"):
        return {"connect_timeout": _REMOTE_CONNECT_TIMEOUT}
    if cfg.backend == "mssql":
        return {"timeout": _REMOTE_CONNECT_TIMEOUT}
    return {}


def build_engine(cfg: StorageSettings | None = None) -> Engine:
    cfg = cfg or get_storage_settings()
    url = cfg.sqlalchemy_url()
    kwargs: dict[str, Any] = {
        "pool_pre_ping": True,
        "future": True,
    }
    if cfg.backend == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False}
        # StaticPool not needed for single-process asyncio threads
    else:
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 10
        kwargs["pool_timeout"] = _REMOTE_CONNECT_TIMEOUT
        kwargs["connect_args"] = _remote_connect_args(cfg)
    eng = create_engine(url, **kwargs)
    return eng


def get_engine(*, force: bool = False) -> Engine:
    global _engine, _engine_url
    cfg = get_storage_settings(force=force)
    url = cfg.sqlalchemy_url()
    with _lock:
        if _engine is not None and not force and _engine_url == url:
            return _engine
        if _engine is not None:
            try:
                _engine.dispose()
            except Exception:
                pass
        _engine = build_engine(cfg)
        _engine_url = url
        return _engine


def dispose_engine() -> None:
    global _engine, _engine_url
    with _lock:
        if _engine is not None:
            try:
                _engine.dispose()
            except Exception:
                pass
        _engine = None
        _engine_url = None


def create_tables(engine: Engine | None = None) -> None:
    eng = engine or get_engine()
    metadata.create_all(eng)
    # sqlite WAL for better concurrent read
    if eng.dialect.name == "sqlite":
        with eng.begin() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA synchronous=NORMAL"))
    # Phase 1: add lifecycle columns on existing DBs (idempotent ALTER)
    try:
        from app.storage.lifecycle import migrate_lifecycle_schema

        with eng.begin() as conn:
            migrate_lifecycle_schema(conn)
    except Exception:
        logger.exception("Lifecycle schema migrate failed")
    # Phase 3: verify refs/anchors/conflict tables (create_all above creates them)
    try:
        from app.knowledge.refs import migrate_refs_schema

        with eng.begin() as conn:
            migrate_refs_schema(conn)
    except Exception:
        logger.exception("Refs schema migrate failed")


@contextmanager
def db_connect() -> Iterator[Any]:
    eng = get_engine()
    with eng.begin() as conn:
        yield conn


def test_connection(cfg: StorageSettings) -> dict[str, Any]:
    """Open a throwaway engine and run SELECT 1."""
    eng = None
    try:
        eng = build_engine(cfg)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {
            "ok": True,
            "backend": cfg.backend,
            "dialect": eng.dialect.name,
            "message": "连接成功",
        }
    except Exception as e:
        logger.warning("storage test failed: %s", e)
        return {
            "ok": False,
            "backend": cfg.backend,
            "error": str(e)[:400],
            "message": "连接失败",
        }
    finally:
        if eng is not None:
            try:
                eng.dispose()
            except Exception:
                pass
