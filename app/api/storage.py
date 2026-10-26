"""Storage backend API — local SQLite or remote SQL databases."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.storage.bootstrap import ensure_storage, reset_storage
from app.storage.engine import test_connection
from app.storage.settings import (
    SUPPORTED_BACKENDS,
    StorageSettings,
    get_storage_settings,
    update_storage_settings,
)

router = APIRouter(prefix="/api/storage", tags=["storage"])


class StorageBody(BaseModel):
    backend: Literal["sqlite", "postgresql", "mysql", "mariadb", "mssql"] = "sqlite"
    host: str = "127.0.0.1"
    port: int = Field(0, ge=0, le=65535)
    database: str = "eva"
    username: str = ""
    password: str = ""
    ssl: bool = False
    sqlite_path: str = "eva.db"


@router.get("")
async def get_storage() -> dict[str, Any]:
    cfg = get_storage_settings(force=True)
    return {"ok": True, "storage": cfg.public_dict()}


@router.post("/test")
async def storage_test(body: StorageBody) -> dict[str, Any]:
    cur = get_storage_settings(force=True)
    pwd = body.password
    if not pwd or pwd == "********":
        pwd = cur.password
    cfg = StorageSettings(
        backend=body.backend,
        host=body.host,
        port=body.port,
        database=body.database,
        username=body.username,
        password=pwd,
        ssl=body.ssl,
        sqlite_path=body.sqlite_path or "eva.db",
        migrated_from_json=cur.migrated_from_json,
    )
    if cfg.backend != "sqlite" and not (cfg.host or "").strip():
        raise HTTPException(400, "请填写数据库主机地址")
    if cfg.backend != "sqlite" and not (cfg.username or "").strip():
        # allow empty user for some local installs, but warn in message via test
        pass
    return test_connection(cfg)


@router.put("")
async def put_storage(body: StorageBody) -> dict[str, Any]:
    """Save backend settings, reconnect, migrate schema, optional JSON import."""
    try:
        cfg = update_storage_settings(body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    # reset singleton stores so they use new engine
    try:
        from app.memory.session import reset_session_store
        from app.memory.store import reset_memory_store

        reset_session_store()
        reset_memory_store()
    except Exception:
        pass
    try:
        from app.knowledge.store import get_knowledge_store

        # knowledge store is stateless SQL; force new instance if cached
        import app.knowledge.store as ks

        ks._store = None  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        import app.workflow.store as ws

        ws._store = None  # type: ignore[attr-defined]
    except Exception:
        pass

    reset_storage()
    try:
        summary = ensure_storage(force_reconnect=True, fallback_sqlite=False)
    except Exception as e:
        raise HTTPException(
            500,
            f"无法连接或初始化数据库：{e}",
        ) from e

    return {
        "ok": True,
        "storage": cfg.public_dict(),
        "summary": summary,
        "message": "存储配置已保存并完成初始化",
    }


@router.get("/backends")
async def list_backends() -> dict[str, Any]:
    return {
        "ok": True,
        "backends": [
            {
                "id": "sqlite",
                "name": "本地 SQLite",
                "needs_host": False,
                "default_port": 0,
                "hint": "零配置，数据在 data/eva.db",
            },
            {
                "id": "postgresql",
                "name": "PostgreSQL",
                "needs_host": True,
                "default_port": 5432,
            },
            {
                "id": "mysql",
                "name": "MySQL",
                "needs_host": True,
                "default_port": 3306,
            },
            {
                "id": "mariadb",
                "name": "MariaDB",
                "needs_host": True,
                "default_port": 3306,
            },
            {
                "id": "mssql",
                "name": "SQL Server",
                "needs_host": True,
                "default_port": 1433,
                "hint": "需安装 ODBC Driver 18 for SQL Server",
            },
        ],
        "supported": list(SUPPORTED_BACKENDS),
    }
