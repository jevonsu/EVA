"""Long-term memory endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.memory.human_gate import (
    ACTOR_UI,
    append_audit,
    is_hard_constraint_kind,
)
from app.memory.store import get_memory_store
from app.models.schemas import MemoryCreate, MemoryItem, MemoryUpdate

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("", response_model=list[MemoryItem])
async def list_memory(
    limit: int = Query(50, ge=1, le=500),
    include_archived: bool = False,
) -> list[MemoryItem]:
    return await get_memory_store().list_all(
        limit=limit, include_archived=include_archived
    )


@router.get("/search", response_model=list[MemoryItem])
async def search_memory(
    q: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=50),
    include_archived: bool = False,
) -> list[MemoryItem]:
    return await get_memory_store().search(
        q, limit=limit, include_archived=include_archived
    )


@router.post("", response_model=MemoryItem)
async def create_memory(body: MemoryCreate) -> MemoryItem:
    """UI create: forced staging when HUMAN_EDIT_CERTIFIED_ONLY (store gate)."""
    try:
        item = await get_memory_store().add(
            content=body.content,
            kind=body.kind,
            tags=body.tags,
            session_id=body.session_id,
            confidence=body.confidence,
            valid_to=body.valid_to,
            ttl_days=body.ttl_days,
            supersedes_id=body.supersedes_id,
            source="ui",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    append_audit(
        "ui_create_memory",
        actor=ACTOR_UI,
        item_type="memory",
        item_id=item.id,
        detail={"status": item.status, "kind": item.kind},
    )
    return item


@router.put("/{memory_id}", response_model=MemoryItem)
async def update_memory(memory_id: str, body: MemoryUpdate) -> MemoryItem:
    """Edit content / kind / tags of an existing memory."""
    try:
        item = await get_memory_store().update(
            memory_id,
            content=body.content,
            kind=body.kind,
            tags=body.tags,
            session_id=body.session_id,
            status=body.status,
            confidence=body.confidence,
            valid_to=body.valid_to,
            ttl_days=body.ttl_days,
            source="ui",
            via_review=False,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not item:
        raise HTTPException(status_code=404, detail="Memory not found")
    if is_hard_constraint_kind(item.kind) or (
        body.kind is not None and is_hard_constraint_kind(body.kind)
    ):
        append_audit(
            "ui_edit_hard_constraint",
            actor=ACTOR_UI,
            item_type="memory",
            item_id=memory_id,
            detail={
                "kind": item.kind,
                "status": item.status,
                "content_changed": body.content is not None,
            },
        )
    else:
        append_audit(
            "ui_edit_memory",
            actor=ACTOR_UI,
            item_type="memory",
            item_id=memory_id,
            detail={"kind": item.kind, "status": item.status},
        )
    return item


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str) -> dict:
    ok = await get_memory_store().delete(memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found")
    append_audit(
        "ui_delete_memory",
        actor=ACTOR_UI,
        item_type="memory",
        item_id=memory_id,
        detail={},
    )
    return {"ok": True, "id": memory_id}
