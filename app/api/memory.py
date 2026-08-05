"""Long-term memory endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.memory.store import get_memory_store
from app.models.schemas import MemoryCreate, MemoryItem, MemoryUpdate

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("", response_model=list[MemoryItem])
async def list_memory(limit: int = Query(50, ge=1, le=500)) -> list[MemoryItem]:
    return await get_memory_store().list_all(limit=limit)


@router.get("/search", response_model=list[MemoryItem])
async def search_memory(
    q: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=50),
) -> list[MemoryItem]:
    return await get_memory_store().search(q, limit=limit)


@router.post("", response_model=MemoryItem)
async def create_memory(body: MemoryCreate) -> MemoryItem:
    return await get_memory_store().add(
        content=body.content,
        kind=body.kind,
        tags=body.tags,
        session_id=body.session_id,
    )


@router.put("/{memory_id}", response_model=MemoryItem)
async def update_memory(memory_id: str, body: MemoryUpdate) -> MemoryItem:
    """Edit content / kind / tags of an existing memory."""
    item = await get_memory_store().update(
        memory_id,
        content=body.content,
        kind=body.kind,
        tags=body.tags,
        session_id=body.session_id,
    )
    if not item:
        raise HTTPException(status_code=404, detail="Memory not found")
    return item


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str) -> dict:
    ok = await get_memory_store().delete(memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"ok": True, "id": memory_id}
