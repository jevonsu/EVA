"""Evolution digest CRUD and tag catalog (session + public scopes)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agent.evolution import KIND_LABELS
from app.agent.evolution_entries import ENTRY_CONTENT_MAX, EVOLUTION_KINDS, PAGE_SIZE
from app.services import evolution_catalog as catalog

router = APIRouter(prefix="/api/evolution", tags=["evolution"])


class EntryBody(BaseModel):
    scope: str = Field(..., description="session | global")
    session_id: str | None = None
    kind: str | None = Field(default="fact")
    content: str = Field(..., min_length=1, max_length=ENTRY_CONTENT_MAX)
    tags: list[str] | None = None


class EntryPatch(BaseModel):
    scope: str = Field(..., description="session | global")
    session_id: str | None = None
    kind: str | None = None
    content: str | None = Field(default=None, max_length=ENTRY_CONTENT_MAX)
    tags: list[str] | None = None


class TagBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=32)


@router.get("/kinds")
async def list_kinds() -> dict:
    return {
        "ok": True,
        "kinds": [{"id": k, "label": v} for k, v in KIND_LABELS.items()],
        "page_size": PAGE_SIZE,
    }


@router.get("/entries")
async def list_entries(
    scope: str = "session",
    session_id: str = "",
    q: str = "",
    kind: str = "",
    tag: str = "",
    source: str = "",
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> dict:
    try:
        return await catalog.query_evolution_entries(
            scope=scope,
            session_id=session_id or None,
            q=q,
            kind=kind,
            tag=tag,
            source=source,
            page=page,
            page_size=page_size or PAGE_SIZE,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/entries")
async def create_entry(body: EntryBody) -> dict:
    if body.kind and body.kind not in EVOLUTION_KINDS:
        raise HTTPException(status_code=400, detail="不支持的条目类型")
    try:
        saved = await catalog.save_entry(
            scope=body.scope,
            session_id=body.session_id,
            payload={
                "kind": body.kind or "fact",
                "content": body.content,
                "tags": body.tags or [],
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found") from None
    return {"ok": True, "entry": saved}


@router.patch("/entries/{entry_id}")
async def patch_entry(entry_id: str, body: EntryPatch) -> dict:
    payload: dict[str, Any] = {}
    if body.kind is not None:
        if body.kind not in EVOLUTION_KINDS:
            raise HTTPException(status_code=400, detail="不支持的条目类型")
        payload["kind"] = body.kind
    if body.content is not None:
        payload["content"] = body.content
    if body.tags is not None:
        payload["tags"] = body.tags
    if not payload:
        raise HTTPException(status_code=400, detail="没有可改字段")
    try:
        saved = await catalog.save_entry(
            scope=body.scope,
            session_id=body.session_id,
            payload=payload,
            entry_id=entry_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except KeyError:
        raise HTTPException(status_code=404, detail="条目不存在") from None
    return {"ok": True, "entry": saved}


@router.delete("/entries/{entry_id}")
async def remove_entry(entry_id: str, scope: str, session_id: str = "") -> dict:
    try:
        return await catalog.remove_entry(scope=scope, session_id=session_id or None, entry_id=entry_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except KeyError:
        raise HTTPException(status_code=404, detail="条目不存在") from None


@router.get("/tags")
async def get_tags() -> dict:
    tags = catalog.list_tags()
    return {"ok": True, "tags": tags}


@router.post("/tags")
async def add_tag(body: TagBody) -> dict:
    try:
        row = catalog.create_tag(body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "tag": row}


@router.patch("/tags/{tag_id}")
async def edit_tag(tag_id: str, body: TagBody) -> dict:
    try:
        row = catalog.rename_tag(tag_id, body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except KeyError:
        raise HTTPException(status_code=404, detail="标签不存在") from None
    return {"ok": True, "tag": row}


@router.delete("/tags/{tag_id}")
async def drop_tag(tag_id: str) -> dict:
    try:
        return await catalog.delete_tag(tag_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="标签不存在") from None
