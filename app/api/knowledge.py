"""Knowledge base (wiki) REST API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.knowledge.store import get_knowledge_store

router = APIRouter(prefix="/api/kb", tags=["knowledge"])


class PageCreate(BaseModel):
    title: str = Field(..., min_length=1)
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    collection: str = "default"
    pinned: bool = False
    confidence: float | None = None
    valid_to: str | None = None
    ttl_days: float | None = None
    supersedes_id: str | None = None


class PageUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    collection: str | None = None
    pinned: bool | None = None
    archived: bool | None = None
    changelog: str = ""
    status: str | None = None
    confidence: float | None = None
    valid_to: str | None = None
    ttl_days: float | None = None


class PageAppend(BaseModel):
    text: str = Field(..., min_length=1)
    heading: str = ""
    changelog: str = ""


@router.get("/collections")
async def list_collections() -> dict[str, Any]:
    """Collection catalog for the editor dropdown (+ page counts)."""
    store = get_knowledge_store()
    await store.ensure_seed()
    return await store.collections_public()


class CollectionBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)


@router.post("/collections")
async def add_collection(body: CollectionBody) -> dict[str, Any]:
    store = get_knowledge_store()
    try:
        return await store.add_collection(body.name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.delete("/collections/{name}")
async def remove_collection(name: str) -> dict[str, Any]:
    store = get_knowledge_store()
    try:
        return await store.remove_collection_option(name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/pages")
async def list_pages(
    collection: str | None = None,
    include_archived: bool = False,
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    store = get_knowledge_store()
    await store.ensure_seed()
    return await store.list_pages(
        collection=collection, include_archived=include_archived, limit=limit
    )


@router.get("/search")
async def search_pages(
    q: str = Query(..., min_length=1),
    collection: str | None = None,
    limit: int = Query(10, ge=1, le=50),
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    store = get_knowledge_store()
    return await store.search(
        q,
        collection=collection,
        limit=limit,
        include_archived=include_archived,
    )


@router.get("/pages/{page_id}")
async def get_page(page_id: str) -> dict[str, Any]:
    store = get_knowledge_store()
    page = await store.get(page_id)
    if not page:
        page = await store.get_by_title_or_slug(page_id)
    if not page:
        raise HTTPException(404, "Page not found")
    return page


@router.post("/pages")
async def create_page(body: PageCreate) -> dict[str, Any]:
    from app.memory.human_gate import ACTOR_UI, append_audit

    store = get_knowledge_store()
    try:
        page = await store.create(
            title=body.title,
            content=body.content,
            tags=body.tags,
            collection=body.collection,
            pinned=body.pinned,
            confidence=body.confidence,
            valid_to=body.valid_to,
            ttl_days=body.ttl_days,
            supersedes_id=body.supersedes_id,
            source="ui",
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    append_audit(
        "ui_create_kb",
        actor=ACTOR_UI,
        item_type="kb",
        item_id=str(page.get("id") or ""),
        detail={"status": page.get("status"), "collection": page.get("collection")},
    )
    return page


@router.patch("/pages/{page_id}")
async def update_page(page_id: str, body: PageUpdate) -> dict[str, Any]:
    from app.memory.human_gate import ACTOR_UI, append_audit

    store = get_knowledge_store()
    try:
        page = await store.update(
            page_id,
            title=body.title,
            content=body.content,
            tags=body.tags,
            collection=body.collection,
            pinned=body.pinned,
            archived=body.archived,
            changelog=body.changelog,
            status=body.status,
            confidence=body.confidence,
            valid_to=body.valid_to,
            ttl_days=body.ttl_days,
            source="ui",
            via_review=False,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not page:
        raise HTTPException(404, "Page not found")
    append_audit(
        "ui_edit_kb",
        actor=ACTOR_UI,
        item_type="kb",
        item_id=page_id,
        detail={"status": page.get("status"), "changelog": body.changelog},
    )
    return page


@router.post("/pages/{page_id}/append")
async def append_page(page_id: str, body: PageAppend) -> dict[str, Any]:
    store = get_knowledge_store()
    try:
        page = await store.append(
            page_id, body.text, heading=body.heading, changelog=body.changelog
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not page:
        raise HTTPException(404, "Page not found")
    return page


@router.delete("/pages/{page_id}")
async def delete_page(page_id: str) -> dict[str, Any]:
    store = get_knowledge_store()
    ok = await store.delete(page_id)
    if not ok:
        raise HTTPException(404, "Page not found")
    return {"ok": True, "id": page_id}
