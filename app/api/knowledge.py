"""Knowledge base (wiki) REST API."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
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


@router.get("/export")
async def export_kb(
    collection: str | None = None,
    ids: str = "",
    include_archived: bool = Query(True),
) -> Response:
    """Download a portable .evakb zip (manifest + catalog + pages)."""
    from app.knowledge.pack import build_export_zip, export_content_disposition
    from app.memory.human_gate import ACTOR_UI, append_audit

    store = get_knowledge_store()
    await store.ensure_seed()
    page_ids = [x.strip() for x in (ids or "").split(",") if x.strip()] or None
    coll = (collection or "").strip() or None
    try:
        blob, fname, manifest = await build_export_zip(
            store,
            collection=coll,
            page_ids=page_ids,
            include_archived=include_archived,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    append_audit(
        "kb_export",
        actor=ACTOR_UI,
        item_type="kb",
        item_id="",
        detail={
            "page_count": manifest.get("page_count"),
            "collection": coll,
            "ids": page_ids,
        },
    )
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition": export_content_disposition(fname)},
    )


@router.post("/import")
async def import_kb(
    file: UploadFile = File(...),
    conflict: str = Query(
        "skip",
        description="skip | overwrite | keep_both",
    ),
) -> dict[str, Any]:
    """Import .evakb/.zip pack, or a plain .md/.txt/.json knowledge file.

    Large packs: zip validation runs in a worker thread; DB writes stay async.
    """
    from app.knowledge import pack as kb_pack
    from app.memory.human_gate import ACTOR_UI, append_audit

    store = get_knowledge_store()
    await store.ensure_seed()
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "空文件")
    if len(raw) > kb_pack.MAX_ZIP_BYTES:
        raise HTTPException(
            400, f"文件过大（上限 {kb_pack.MAX_ZIP_BYTES // (1024 * 1024)}MB）"
        )
    fname = file.filename or "upload"
    conflict_l = (conflict or "skip").strip().lower()
    if conflict_l not in ("skip", "overwrite", "keep_both"):
        raise HTTPException(400, "conflict 仅支持 skip / overwrite / keep_both")

    # Pre-validate zip structure off the event loop (CPU/IO bound).
    if raw[:2] == b"PK" or fname.lower().endswith((".zip", ".evakb")):
        try:
            await asyncio.to_thread(kb_pack._read_zip_members, raw)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    try:
        result = await kb_pack.import_pack_bytes(
            store,
            raw,
            filename=fname,
            conflict=conflict_l,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    counts = result.get("counts") or {}
    append_audit(
        "kb_import",
        actor=ACTOR_UI,
        item_type="kb",
        item_id="",
        detail={
            "filename": fname,
            "conflict": conflict_l,
            "counts": counts,
            "failed": [
                {"id": x.get("id"), "reason": x.get("reason")}
                for x in (result.get("failed") or [])[:20]
            ],
        },
    )
    return result