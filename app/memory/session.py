"""Conversation / session store backed by SQL (local SQLite or remote DB)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, insert, or_, select, update

from app.config import get_settings
from app.storage.engine import db_connect
from app.storage.schema import sessions as sessions_t
from app.storage.util import dumps, loads, run_db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def suggest_session_title(message: str, *, limit: int = 18) -> str:
    """Short sidebar title from the user's first real sentence, not a form dump."""
    t = (message or "").strip()
    if not t:
        return "对话"
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"【表单回复】\s*", "", t)
    t = re.sub(r"（已上传文件）", "", t)
    t = t.split("\n", 1)[0].strip()
    if t.count("、") >= 2 or t.count("，") >= 2:
        t = re.split(r"[、，]", t, maxsplit=1)[0].strip()
    t = re.split(r"[。！？!?]", t, maxsplit=1)[0].strip()
    t = re.sub(r"\s+", " ", t).strip(" ·-—")
    if not t:
        return "对话"
    if len(t) > limit:
        t = re.sub(r"[，、,.；;：:\-—…\s]+$", "", t[:limit]) + "…"
    return t[:80]


def _empty_evolution() -> dict[str, Any]:
    return {
        "version": 0,
        "text": "",
        "entries": [],
        "updated_at": None,
        "message_count_at_update": 0,
    }


class SessionStore:
    def __init__(self) -> None:
        settings = get_settings()
        self.max_history = settings.max_history_messages

    @staticmethod
    def _ensure_message_ids(messages: list[Any]) -> bool:
        changed = False
        if not isinstance(messages, list):
            return False
        for m in messages:
            if not isinstance(m, dict):
                continue
            if not str(m.get("id") or "").strip():
                m["id"] = uuid.uuid4().hex[:12]
                changed = True
        return changed

    def _row_to_data(self, row: Any) -> dict[str, Any]:
        data = loads(row.payload_json, {})
        if not isinstance(data, dict):
            data = {}
        data.setdefault("session_id", row.id)
        data.setdefault("title", row.title)
        data.setdefault("created_at", row.created_at)
        data.setdefault("updated_at", row.updated_at)
        data.setdefault("messages", [])
        data.setdefault("metadata", {})
        if "evolution" not in data or not isinstance(data.get("evolution"), dict):
            data["evolution"] = _empty_evolution()
        return data

    def _upsert_sync(self, data: dict[str, Any]) -> None:
        sid = str(data["session_id"])
        msgs = data.get("messages") or []
        mc = len(msgs) if isinstance(msgs, list) else 0
        payload = dumps(data)
        with db_connect() as conn:
            exists = conn.execute(
                select(sessions_t.c.id).where(sessions_t.c.id == sid)
            ).first()
            vals = dict(
                title=data.get("title"),
                created_at=str(data.get("created_at") or ""),
                updated_at=str(data.get("updated_at") or ""),
                message_count=mc,
                payload_json=payload,
            )
            if exists:
                conn.execute(
                    update(sessions_t).where(sessions_t.c.id == sid).values(**vals)
                )
            else:
                conn.execute(insert(sessions_t).values(id=sid, **vals))

    def _get_sync(self, session_id: str) -> dict[str, Any] | None:
        with db_connect() as conn:
            row = conn.execute(
                select(sessions_t).where(sessions_t.c.id == session_id)
            ).first()
            if not row:
                return None
            data = self._row_to_data(row)
            msgs = data.get("messages") or []
            if self._ensure_message_ids(msgs):
                data["messages"] = msgs
            return data

    def _list_sync(self) -> list[dict[str, Any]]:
        with db_connect() as conn:
            rows = conn.execute(
                select(
                    sessions_t.c.id,
                    sessions_t.c.title,
                    sessions_t.c.created_at,
                    sessions_t.c.updated_at,
                    sessions_t.c.message_count,
                ).order_by(sessions_t.c.updated_at.desc())
            ).all()
        return [
            {
                "session_id": r.id,
                "title": r.title,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
                "message_count": int(r.message_count or 0),
            }
            for r in rows
        ]

    @staticmethod
    def _like_escape(q: str) -> str:
        return (
            (q or "")
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )

    def _search_sync(self, q: str) -> list[dict[str, Any]]:
        needle = (q or "").strip()
        if not needle:
            return self._list_sync()
        like = f"%{self._like_escape(needle)}%"
        with db_connect() as conn:
            rows = conn.execute(
                select(
                    sessions_t.c.id,
                    sessions_t.c.title,
                    sessions_t.c.created_at,
                    sessions_t.c.updated_at,
                    sessions_t.c.message_count,
                )
                .where(
                    or_(
                        sessions_t.c.title.like(like, escape="\\"),
                        sessions_t.c.payload_json.like(like, escape="\\"),
                    )
                )
                .order_by(sessions_t.c.updated_at.desc())
            ).all()
        return [
            {
                "session_id": r.id,
                "title": r.title,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
                "message_count": int(r.message_count or 0),
            }
            for r in rows
        ]

    def _delete_sync(self, session_id: str) -> bool:
        with db_connect() as conn:
            res = conn.execute(delete(sessions_t).where(sessions_t.c.id == session_id))
            return bool(res.rowcount)

    def _restore_sync(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(data or {})
        sid = str(payload.get("session_id") or "").strip()
        if not sid:
            raise ValueError("缺少 session_id")
        payload["session_id"] = sid
        msgs = payload.get("messages") or []
        if not isinstance(msgs, list):
            msgs = []
            payload["messages"] = msgs
        self._ensure_message_ids(msgs)
        payload.setdefault("title", None)
        payload.setdefault("created_at", _now().isoformat())
        payload.setdefault("updated_at", _now().isoformat())
        payload.setdefault("metadata", {})
        if "evolution" not in payload or not isinstance(payload.get("evolution"), dict):
            payload["evolution"] = _empty_evolution()
        self._upsert_sync(payload)
        return payload

    async def create(self, title: str | None = None) -> dict[str, Any]:
        session_id = uuid.uuid4().hex
        now = _now().isoformat()
        data = {
            "session_id": session_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "messages": [],
            "metadata": {},
            "evolution": _empty_evolution(),
        }
        await run_db(lambda: self._upsert_sync(data))
        return data

    async def get(self, session_id: str) -> dict[str, Any] | None:
        return await run_db(lambda: self._get_sync(session_id))

    async def list_sessions(self) -> list[dict[str, Any]]:
        return await run_db(self._list_sync)

    async def search_sessions(self, q: str) -> list[dict[str, Any]]:
        needle = (q or "").strip()
        if not needle:
            return await self.list_sessions()
        return await run_db(lambda: self._search_sync(needle))

    async def restore(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await run_db(lambda: self._restore_sync(payload))

    async def append_messages(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        title: str | None = None,
        max_history: int | None = None,
    ) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            data = self._get_sync(session_id)
            if data is None:
                raise KeyError(f"Session not found: {session_id}")
            for m in messages:
                if isinstance(m, dict) and not str(m.get("id") or "").strip():
                    m["id"] = uuid.uuid4().hex[:12]
            data["messages"].extend(messages)
            self._ensure_message_ids(data["messages"])
            cap = int(max_history if max_history is not None else self.max_history)
            cap = max(4, cap)
            if len(data["messages"]) > cap * 2:
                data["messages"] = data["messages"][-cap:]
            data["updated_at"] = _now().isoformat()
            if title and not data.get("title"):
                data["title"] = title[:80]
            if "evolution" not in data or not isinstance(data.get("evolution"), dict):
                data["evolution"] = _empty_evolution()
            self._upsert_sync(data)
            return data

        return await run_db(_do)

    async def get_messages(
        self, session_id: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        data = await self.get(session_id)
        if not data:
            return []
        msgs = data.get("messages", [])
        if limit:
            return msgs[-limit:]
        return msgs

    async def get_evolution(self, session_id: str) -> dict[str, Any]:
        data = await self.get(session_id)
        if not data:
            return _empty_evolution()
        evo = data.get("evolution")
        return evo if isinstance(evo, dict) else _empty_evolution()

    async def set_evolution(
        self,
        session_id: str,
        evolution: dict[str, Any],
        *,
        trim_to: int | None = None,
    ) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            data = self._get_sync(session_id)
            if data is None:
                raise KeyError(f"Session not found: {session_id}")
            evo = dict(evolution or {})
            if trim_to is not None:
                n = max(4, int(trim_to))
                msgs = list(data.get("messages") or [])
                if len(msgs) > n:
                    data["messages"] = msgs[-n:]
            evo["message_count_at_update"] = len(data.get("messages") or [])
            data["evolution"] = evo
            data["updated_at"] = _now().isoformat()
            self._upsert_sync(data)
            return data

        return await run_db(_do)

    async def rewind_messages(self, session_id: str, keep: int) -> dict[str, Any]:
        """Keep the first *keep* messages; drop the rest."""

        def _do() -> dict[str, Any]:
            data = self._get_sync(session_id)
            if data is None:
                raise KeyError(f"Session not found: {session_id}")
            msgs = list(data.get("messages") or [])
            k = max(0, min(int(keep), len(msgs)))
            data["messages"] = msgs[:k]
            data["updated_at"] = _now().isoformat()
            self._upsert_sync(data)
            return data

        return await run_db(_do)

    async def delete_message(
        self,
        session_id: str,
        message_id: str | None = None,
        index: int | None = None,
    ) -> dict[str, Any] | None:
        mid = str(message_id or "").strip()

        def _do() -> dict[str, Any] | None:
            data = self._get_sync(session_id)
            if data is None:
                return None
            msgs = list(data.get("messages") or [])
            self._ensure_message_ids(msgs)
            drop: int | None = None
            if mid:
                for i, m in enumerate(msgs):
                    if isinstance(m, dict) and str(m.get("id") or "") == mid:
                        drop = i
                        break
            if drop is None and index is not None:
                chat_idxs = [
                    i
                    for i, m in enumerate(msgs)
                    if isinstance(m, dict)
                    and str(m.get("role") or "") in ("user", "assistant")
                ]
                idx = int(index)
                if 0 <= idx < len(chat_idxs):
                    drop = chat_idxs[idx]
            if drop is None:
                return None
            removed = msgs.pop(drop)
            data["messages"] = msgs
            data["updated_at"] = _now().isoformat()
            self._upsert_sync(data)
            return {"data": data, "removed": removed, "index": drop}

        return await run_db(_do)

    async def insert_message(
        self,
        session_id: str,
        message: dict[str, Any],
        index: int | None = None,
    ) -> dict[str, Any] | None:
        def _do() -> dict[str, Any] | None:
            data = self._get_sync(session_id)
            if data is None:
                return None
            msgs = list(data.get("messages") or [])
            self._ensure_message_ids(msgs)
            row = dict(message or {})
            if not str(row.get("id") or "").strip():
                row["id"] = uuid.uuid4().hex[:12]
            at = len(msgs) if index is None else int(index)
            at = max(0, min(at, len(msgs)))
            msgs.insert(at, row)
            data["messages"] = msgs
            data["updated_at"] = _now().isoformat()
            self._upsert_sync(data)
            return data

        return await run_db(_do)

    async def update_title(self, session_id: str, title: str) -> dict[str, Any] | None:
        def _do() -> dict[str, Any] | None:
            data = self._get_sync(session_id)
            if data is None:
                return None
            data["title"] = title[:80]
            data["updated_at"] = _now().isoformat()
            self._upsert_sync(data)
            return data

        return await run_db(_do)

    async def update_metadata(
        self,
        session_id: str,
        metadata: dict[str, Any],
        *,
        merge: bool = True,
    ) -> dict[str, Any] | None:
        def _do() -> dict[str, Any] | None:
            data = self._get_sync(session_id)
            if data is None:
                return None
            if merge:
                base = (
                    data.get("metadata")
                    if isinstance(data.get("metadata"), dict)
                    else {}
                )
                merged = dict(base)
                merged.update(metadata or {})
                data["metadata"] = merged
            else:
                data["metadata"] = dict(metadata or {})
            data["updated_at"] = _now().isoformat()
            self._upsert_sync(data)
            return data

        return await run_db(_do)

    async def delete(self, session_id: str) -> bool:
        return await run_db(lambda: self._delete_sync(session_id))


_store: SessionStore | None = None


def get_session_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore()
    return _store


def reset_session_store() -> None:
    global _store
    _store = None
