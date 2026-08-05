"""Short-term conversation / session store (JSON files)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from app.config import get_settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SessionStore:
    def __init__(self, root: Path | None = None) -> None:
        settings = get_settings()
        self.root = root or (settings.data_dir / "sessions")
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_history = settings.max_history_messages

    def _path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.json"

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
            "evolution": {
                "version": 0,
                "text": "",
                "entries": [],
                "updated_at": None,
                "message_count_at_update": 0,
            },
        }
        await self._write(session_id, data)
        return data

    async def get(self, session_id: str) -> dict[str, Any] | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            return json.loads(await f.read())

    async def list_sessions(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            async with aiofiles.open(path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
            items.append(
                {
                    "session_id": data["session_id"],
                    "created_at": data["created_at"],
                    "updated_at": data["updated_at"],
                    "message_count": len(data.get("messages", [])),
                    "title": data.get("title"),
                }
            )
        return items

    async def append_messages(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        title: str | None = None,
        max_history: int | None = None,
    ) -> dict[str, Any]:
        data = await self.get(session_id)
        if data is None:
            raise KeyError(f"Session not found: {session_id}")
        data["messages"].extend(messages)
        # Keep a rolling window of history (hard cap)
        cap = int(max_history if max_history is not None else self.max_history)
        cap = max(4, cap)
        if len(data["messages"]) > cap * 2:
            data["messages"] = data["messages"][-cap:]
        data["updated_at"] = _now().isoformat()
        if title and not data.get("title"):
            data["title"] = title[:80]
        if "evolution" not in data or not isinstance(data.get("evolution"), dict):
            data["evolution"] = {
                "version": 0,
                "text": "",
                "entries": [],
                "updated_at": None,
                "message_count_at_update": 0,
            }
        await self._write(session_id, data)
        return data

    async def get_messages(self, session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
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
            return {
                "version": 0,
                "text": "",
                "entries": [],
                "updated_at": None,
                "message_count_at_update": 0,
            }
        evo = data.get("evolution")
        return evo if isinstance(evo, dict) else {
            "version": 0,
            "text": "",
            "entries": [],
            "updated_at": None,
            "message_count_at_update": 0,
        }

    async def set_evolution(
        self,
        session_id: str,
        evolution: dict[str, Any],
        *,
        trim_to: int | None = None,
    ) -> dict[str, Any]:
        """Persist evolution digest; optionally keep only the last *trim_to* messages."""
        data = await self.get(session_id)
        if data is None:
            raise KeyError(f"Session not found: {session_id}")
        evo = dict(evolution or {})
        if trim_to is not None:
            n = max(4, int(trim_to))
            msgs = list(data.get("messages") or [])
            if len(msgs) > n:
                data["messages"] = msgs[-n:]
        # Count after trim — next trigger is relative to stored length
        evo["message_count_at_update"] = len(data.get("messages") or [])
        data["evolution"] = evo
        data["updated_at"] = _now().isoformat()
        await self._write(session_id, data)
        return data

    async def update_title(self, session_id: str, title: str) -> dict[str, Any] | None:
        """Update session title. Returns None if session not found."""
        data = await self.get(session_id)
        if data is None:
            return None
        data["title"] = title[:80]
        data["updated_at"] = _now().isoformat()
        await self._write(session_id, data)
        return data

    async def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False

    async def _write(self, session_id: str, data: dict[str, Any]) -> None:
        path = self._path(session_id)
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=2))


_store: SessionStore | None = None


def get_session_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore()
    return _store
