"""Session management endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.memory.session import get_session_store
from app.models.schemas import SessionInfo

class SessionCreate(BaseModel):
    title: str | None = Field(None, max_length=120)


class SessionUpdate(BaseModel):
    title: str | None = None


class SessionRewind(BaseModel):
    keep: int = Field(ge=0, description="Keep the first N messages, drop the rest")


class SessionMessageDelete(BaseModel):
    id: str | None = None
    index: int | None = Field(default=None, ge=0)


class SessionRestore(BaseModel):
    session: dict[str, Any]


class SessionMessageRestore(BaseModel):
    message: dict[str, Any]
    index: int | None = Field(default=None, ge=0)


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _session_info(r: dict[str, Any]) -> SessionInfo:
    return SessionInfo(
        session_id=r["session_id"],
        created_at=datetime.fromisoformat(str(r["created_at"])),
        updated_at=datetime.fromisoformat(str(r["updated_at"])),
        message_count=r["message_count"],
        title=r.get("title"),
    )


@router.get("", response_model=list[SessionInfo])
async def list_sessions(q: str = "") -> list[SessionInfo]:
    store = get_session_store()
    needle = (q or "").strip()
    rows = await store.search_sessions(needle) if needle else await store.list_sessions()
    return [_session_info(r) for r in rows]


@router.post("/restore")
async def restore_session(body: SessionRestore) -> dict:
    store = get_session_store()
    try:
        data = await store.restore(body.session or {})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "session_id": data.get("session_id")}


@router.post("")
async def create_session(body: SessionCreate) -> dict:
    """Create an empty session with an explicit title (Hub mirrors conv title)."""
    title = (body.title or "").strip()[:80] or None
    data = await get_session_store().create(title=title)
    return {"ok": True, **data}


@router.get("/{session_id}/evolution")
async def get_session_evolution(session_id: str) -> dict:
    """Current session evolution digest for 人设 → 演化人格."""
    from app.agent.evolution import evolution_public_view

    store = get_session_store()
    data = await store.get(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    return evolution_public_view(
        data.get("evolution"),
        session_id=session_id,
        session_title=str(data.get("title") or ""),
        message_count=len(data.get("messages") or []),
    )


@router.get("/{session_id}")
async def get_session(session_id: str) -> dict:
    store = get_session_store()
    data = await store.get(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    return data


@router.patch("/{session_id}")
async def update_session(session_id: str, body: SessionUpdate) -> dict:
    store = get_session_store()
    data: dict | None = None
    if body.title is not None:
        data = await store.update_title(session_id, body.title)
    else:
        data = await store.get(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    return data


@router.post("/{session_id}/rewind")
async def rewind_session(session_id: str, body: SessionRewind) -> dict:
    store = get_session_store()
    if not await store.get(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    data = await store.rewind_messages(session_id, body.keep)
    return {
        "ok": True,
        "session_id": session_id,
        "kept": len(data.get("messages") or []),
    }


@router.post("/{session_id}/messages/delete")
async def delete_session_message(session_id: str, body: SessionMessageDelete) -> dict:
    store = get_session_store()
    if not await store.get(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    result = await store.delete_message(session_id, body.id, body.index)
    if result is None:
        raise HTTPException(status_code=404, detail="Message not found")
    data = result.get("data") or {}
    return {
        "ok": True,
        "session_id": session_id,
        "message_count": len(data.get("messages") or []),
        "removed": result.get("removed"),
        "index": result.get("index"),
    }


@router.post("/{session_id}/messages/restore")
async def restore_session_message(session_id: str, body: SessionMessageRestore) -> dict:
    store = get_session_store()
    data = await store.insert_message(session_id, body.message or {}, body.index)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "ok": True,
        "session_id": session_id,
        "message_count": len(data.get("messages") or []),
    }


@router.delete("/{session_id}/messages/{message_id}")
async def delete_session_message_by_id(session_id: str, message_id: str) -> dict:
    store = get_session_store()
    result = await store.delete_message(session_id, message_id, None)
    if result is None:
        raise HTTPException(status_code=404, detail="Message not found")
    data = result.get("data") or {}
    return {
        "ok": True,
        "session_id": session_id,
        "message_id": message_id,
        "message_count": len(data.get("messages") or []),
        "removed": result.get("removed"),
        "index": result.get("index"),
    }


@router.delete("/{session_id}")
async def delete_session(session_id: str) -> dict:
    store = get_session_store()
    ok = await store.delete(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True, "session_id": session_id}
