"""Session management endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.memory.session import get_session_store
from app.models.schemas import SessionInfo

class SessionUpdate(BaseModel):
    title: str | None = None


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionInfo])
async def list_sessions() -> list[SessionInfo]:
    store = get_session_store()
    rows = await store.list_sessions()
    return [
        SessionInfo(
            session_id=r["session_id"],
            created_at=datetime.fromisoformat(r["created_at"]),
            updated_at=datetime.fromisoformat(r["updated_at"]),
            message_count=r["message_count"],
            title=r.get("title"),
        )
        for r in rows
    ]


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


@router.delete("/{session_id}")
async def delete_session(session_id: str) -> dict:
    store = get_session_store()
    ok = await store.delete(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True, "session_id": session_id}
