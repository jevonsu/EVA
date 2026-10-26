"""One-shot migrate legacy JSON files under data/ into SQL tables."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.engine import Connection

from app.storage.schema import (
    kb_catalog,
    kb_pages,
    kv_meta,
    memories,
    sessions,
    tasks,
    workflow_runs,
)

logger = logging.getLogger("app.storage.migrate")


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8") or json.dumps(default))
    except (OSError, json.JSONDecodeError):
        logger.exception("migrate: bad json %s", path)
        return default


def _has_meta(conn: Connection, key: str) -> bool:
    row = conn.execute(select(kv_meta.c.value).where(kv_meta.c.key == key)).first()
    return bool(row and row[0])


def _set_meta(conn: Connection, key: str, value: str) -> None:
    existing = conn.execute(select(kv_meta.c.key).where(kv_meta.c.key == key)).first()
    if existing:
        conn.execute(kv_meta.update().where(kv_meta.c.key == key).values(value=value))
    else:
        conn.execute(insert(kv_meta).values(key=key, value=value))


def migrate_from_json(conn: Connection, data_dir: Path) -> dict[str, int]:
    """Import JSON stores if not already marked migrated for this DB."""
    counts = {
        "sessions": 0,
        "memories": 0,
        "kb_pages": 0,
        "tasks": 0,
        "workflow_runs": 0,
    }
    if _has_meta(conn, "json_migrated_v1"):
        return counts

    # sessions
    sess_dir = data_dir / "sessions"
    if sess_dir.is_dir():
        for path in sess_dir.glob("*.json"):
            data = _read_json(path, None)
            if not isinstance(data, dict) or not data.get("session_id"):
                continue
            sid = str(data["session_id"])
            exists = conn.execute(select(sessions.c.id).where(sessions.c.id == sid)).first()
            if exists:
                continue
            msgs = data.get("messages") or []
            conn.execute(
                insert(sessions).values(
                    id=sid,
                    title=data.get("title"),
                    created_at=str(data.get("created_at") or ""),
                    updated_at=str(data.get("updated_at") or ""),
                    message_count=len(msgs) if isinstance(msgs, list) else 0,
                    payload_json=json.dumps(data, ensure_ascii=False, default=str),
                )
            )
            counts["sessions"] += 1

    # memories
    mem_path = data_dir / "memory" / "long_term.json"
    items = _read_json(mem_path, [])
    if isinstance(items, list):
        for row in items:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            mid = str(row["id"])
            if conn.execute(select(memories.c.id).where(memories.c.id == mid)).first():
                continue
            conn.execute(
                insert(memories).values(
                    id=mid,
                    content=str(row.get("content") or ""),
                    kind=str(row.get("kind") or "note"),
                    tags_json=json.dumps(row.get("tags") or [], ensure_ascii=False),
                    session_id=row.get("session_id"),
                    created_at=str(row.get("created_at") or ""),
                )
            )
            counts["memories"] += 1

    # kb pages
    pages_dir = data_dir / "kb" / "pages"
    if pages_dir.is_dir():
        for path in pages_dir.glob("*.json"):
            page = _read_json(path, None)
            if not isinstance(page, dict) or not page.get("id"):
                continue
            pid = str(page["id"])
            if conn.execute(select(kb_pages.c.id).where(kb_pages.c.id == pid)).first():
                continue
            content = str(page.get("content") or "")
            conn.execute(
                insert(kb_pages).values(
                    id=pid,
                    title=str(page.get("title") or ""),
                    slug=str(page.get("slug") or ""),
                    collection=str(page.get("collection") or "default"),
                    tags_json=json.dumps(page.get("tags") or [], ensure_ascii=False),
                    content=content,
                    version=int(page.get("version") or 1),
                    pinned=bool(page.get("pinned")),
                    archived=bool(page.get("archived")),
                    versions_json=json.dumps(
                        page.get("versions") or [], ensure_ascii=False, default=str
                    ),
                    created_at=str(page.get("created_at") or ""),
                    updated_at=str(page.get("updated_at") or ""),
                    preview=content[:160],
                )
            )
            counts["kb_pages"] += 1

    cat_path = data_dir / "kb" / "catalog.json"
    cat = _read_json(cat_path, {})
    if isinstance(cat, dict):
        existing = conn.execute(select(kb_catalog.c.id).where(kb_catalog.c.id == 1)).first()
        if not existing:
            conn.execute(
                insert(kb_catalog).values(
                    id=1,
                    collections_json=json.dumps(
                        cat.get("collections") or [], ensure_ascii=False
                    ),
                    hidden_json=json.dumps(cat.get("hidden") or [], ensure_ascii=False),
                )
            )

    # tasks
    task_path = data_dir / "tasks" / "tasks.json"
    trows = _read_json(task_path, [])
    if isinstance(trows, list):
        for row in trows:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            tid = str(row["id"])
            if conn.execute(select(tasks.c.id).where(tasks.c.id == tid)).first():
                continue
            conn.execute(
                insert(tasks).values(
                    id=tid,
                    name=str(row.get("name") or ""),
                    enabled=bool(row.get("enabled", True)),
                    status=str(row.get("status") or "pending"),
                    created_at=str(row.get("created_at") or ""),
                    payload_json=json.dumps(row, ensure_ascii=False, default=str),
                )
            )
            counts["tasks"] += 1

    # workflow runs
    runs_dir = data_dir / "workflows" / "runs"
    if runs_dir.is_dir():
        for path in runs_dir.glob("*.json"):
            run = _read_json(path, None)
            if not isinstance(run, dict) or not run.get("id"):
                continue
            rid = str(run["id"])
            if conn.execute(
                select(workflow_runs.c.id).where(workflow_runs.c.id == rid)
            ).first():
                continue
            conn.execute(
                insert(workflow_runs).values(
                    id=rid,
                    workflow_id=str(run.get("workflow_id") or ""),
                    status=str(run.get("status") or "pending"),
                    created_at=str(run.get("created_at") or ""),
                    updated_at=str(run.get("updated_at") or ""),
                    finished_at=run.get("finished_at"),
                    payload_json=json.dumps(run, ensure_ascii=False, default=str),
                )
            )
            counts["workflow_runs"] += 1

    _set_meta(conn, "json_migrated_v1", "1")
    logger.info("JSON → SQL migration done: %s", counts)
    return counts
