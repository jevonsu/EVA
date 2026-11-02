"""Human review queue: approve / reject / modify / downgrade pending items."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.memory.human_gate import (
    ACTOR_REVIEW,
    ACTOR_UI,
    HARD_CONSTRAINT_KINDS,
    QUEUE_CONFLICT_STATUSES,
    QUEUE_KB_STATUSES,
    QUEUE_MEMORY_STATUSES,
    append_audit,
    human_edit_certified_only,
    is_hard_constraint_kind,
)
from app.storage.lifecycle import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_STAGING,
    clamp_confidence,
    normalize_status,
)

router = APIRouter(prefix="/api/review", tags=["review"])


class ApproveBody(BaseModel):
    note: str = ""
    confidence: float | None = None
    clear_ttl: bool = True
    kind: str | None = None
    content: str | None = None
    title: str | None = None
    tags: list[str] | None = None
    collection: str | None = None


class RejectBody(BaseModel):
    note: str = ""
    archive: bool = True


class ModifyBody(BaseModel):
    content: str | None = None
    title: str | None = None
    kind: str | None = None
    tags: list[str] | None = None
    collection: str | None = None
    note: str = ""
    approve_after: bool = False
    confidence: float | None = None
    clear_ttl: bool = True


class DowngradeBody(BaseModel):
    note: str = ""
    ttl_days: float = 7.0


class ConflictResolveBody(BaseModel):
    resolution: str = Field(
        ..., description="approve_incoming|keep_existing|merge|dismiss"
    )
    note: str = ""
    promote_id: str | None = None
    promote_type: str | None = None  # memory|kb


@router.get("/flags")
async def review_flags() -> dict[str, Any]:
    return {
        "ok": True,
        "human_edit_certified_only": human_edit_certified_only(),
        "hint": "UI 新建默认进暂存；正式化请走本评审队列。",
    }


@router.get("/queue")
async def review_queue(
    limit: int = Query(80, ge=1, le=300),
) -> dict[str, Any]:
    """Pending staging / conflicted / review_required + open conflict logs."""
    from app.knowledge.refs import get_ref_store
    from app.knowledge.store import get_knowledge_store
    from app.memory.store import get_memory_store

    mem_store = get_memory_store()
    kb_store = get_knowledge_store()
    ref_store = get_ref_store()

    memories_all = await mem_store.list_all(limit=500, include_archived=True)
    pending_mem: list[dict[str, Any]] = []
    for m in memories_all:
        st = normalize_status(getattr(m, "status", None))
        if st not in QUEUE_MEMORY_STATUSES:
            continue
        pending_mem.append(
            {
                "item_type": "memory",
                "id": m.id,
                "status": st,
                "kind": m.kind,
                "content": m.content,
                "tags": m.tags,
                "confidence": m.confidence,
                "valid_to": m.valid_to,
                "created_at": m.created_at.isoformat()
                if hasattr(m.created_at, "isoformat")
                else str(m.created_at),
                "hard_constraint": is_hard_constraint_kind(m.kind),
            }
        )
        if len(pending_mem) >= limit:
            break

    # KB: load index with archived to catch staging
    kb_rows = await kb_store.list_pages(include_archived=True, limit=500)
    # list_pages filters by visible unless include_archived — staging hidden by default
    # so re-query raw index
    try:
        raw_idx = await kb_store._load_index()  # noqa: SLF001
    except Exception:
        raw_idx = kb_rows
    pending_kb: list[dict[str, Any]] = []
    for r in sorted(raw_idx, key=lambda x: x.get("updated_at") or "", reverse=True):
        st = normalize_status(r.get("status"), archived_flag=bool(r.get("archived")))
        if st not in QUEUE_KB_STATUSES:
            continue
        pending_kb.append(
            {
                "item_type": "kb",
                "id": r.get("id"),
                "status": st,
                "title": r.get("title"),
                "collection": r.get("collection"),
                "preview": r.get("preview") or "",
                "tags": r.get("tags") or [],
                "confidence": r.get("confidence"),
                "valid_to": r.get("valid_to"),
                "updated_at": r.get("updated_at"),
                "created_at": r.get("created_at"),
            }
        )
        if len(pending_kb) >= limit:
            break

    conflicts = await ref_store.list_conflicts(limit=limit)
    open_conflicts = [
        c
        for c in conflicts
        if str(c.get("status") or "").lower() in QUEUE_CONFLICT_STATUSES
        or str(c.get("status") or "").lower() == "review_required"
    ]

    return {
        "ok": True,
        "human_edit_certified_only": human_edit_certified_only(),
        "counts": {
            "memories": len(pending_mem),
            "kb": len(pending_kb),
            "conflicts": len(open_conflicts),
        },
        "memories": pending_mem[:limit],
        "kb": pending_kb[:limit],
        "conflicts": open_conflicts[:limit],
    }


async def _approve_memory(memory_id: str, body: ApproveBody) -> dict[str, Any]:
    from app.memory.store import get_memory_store
    from app.storage.util import run_db

    store = get_memory_store()

    def _find():
        rows = store._load_all_sync(include_archived=True)  # noqa: SLF001
        for r in rows:
            if r.get("id") == memory_id:
                return r
        return None

    raw = await run_db(_find)
    if not raw:
        raise HTTPException(404, "Memory not found")
    old_status = raw.get("status")
    content = body.content if body.content is not None else raw.get("content")
    kind = body.kind if body.kind is not None else raw.get("kind")
    tags = body.tags if body.tags is not None else raw.get("tags")
    conf = (
        clamp_confidence(body.confidence)
        if body.confidence is not None
        else 0.95
    )
    kwargs: dict[str, Any] = {
        "content": content,
        "kind": kind,
        "tags": tags,
        "status": STATUS_ACTIVE,
        "confidence": conf,
        "via_review": True,
    }
    if body.clear_ttl:
        kwargs["valid_to"] = ""
    item = await store.update(memory_id, **kwargs)
    if not item:
        raise HTTPException(404, "Memory not found")
    append_audit(
        "approve_memory",
        actor=ACTOR_REVIEW,
        item_type="memory",
        item_id=memory_id,
        detail={
            "from": old_status,
            "to": STATUS_ACTIVE,
            "note": body.note,
            "hard_constraint": is_hard_constraint_kind(kind),
        },
    )
    return {"ok": True, "item_type": "memory", "item": item.model_dump()}


async def _approve_kb(page_id: str, body: ApproveBody) -> dict[str, Any]:
    from app.knowledge.store import get_knowledge_store

    store = get_knowledge_store()
    page = await store.get(page_id)
    if not page:
        raise HTTPException(404, "KB page not found")
    old_status = page.get("status")
    conf = (
        clamp_confidence(body.confidence)
        if body.confidence is not None
        else 0.95
    )
    coll = body.collection
    if coll is None and str(page.get("collection") or "").lower() in (
        "staging",
        "temp",
        "draft",
        "candidate",
    ):
        coll = "default"
    updated = await store.update(
        page_id,
        title=body.title,
        content=body.content,
        tags=body.tags,
        collection=coll,
        status=STATUS_ACTIVE,
        confidence=conf,
        valid_to="" if body.clear_ttl else None,
        changelog=body.note or "review:approve",
        archived=False,
        via_review=True,
        source="review",
    )
    if not updated:
        raise HTTPException(404, "KB page not found")
    append_audit(
        "approve_kb",
        actor=ACTOR_REVIEW,
        item_type="kb",
        item_id=page_id,
        detail={"from": old_status, "to": STATUS_ACTIVE, "note": body.note},
    )
    return {"ok": True, "item_type": "kb", "item": updated}


@router.post("/memory/{memory_id}/approve")
async def approve_memory(memory_id: str, body: ApproveBody | None = None) -> dict[str, Any]:
    return await _approve_memory(memory_id, body or ApproveBody())


@router.post("/kb/{page_id}/approve")
async def approve_kb(page_id: str, body: ApproveBody | None = None) -> dict[str, Any]:
    return await _approve_kb(page_id, body or ApproveBody())


@router.post("/memory/{memory_id}/reject")
async def reject_memory(memory_id: str, body: RejectBody | None = None) -> dict[str, Any]:
    body = body or RejectBody()
    from app.memory.store import get_memory_store

    store = get_memory_store()
    if body.archive:
        item = await store.update(
            memory_id, status=STATUS_ARCHIVED, via_review=True, source="review"
        )
        if not item:
            raise HTTPException(404, "Memory not found")
        append_audit(
            "reject_memory",
            actor=ACTOR_REVIEW,
            item_type="memory",
            item_id=memory_id,
            detail={"note": body.note, "archive": True},
        )
        return {"ok": True, "item_type": "memory", "item": item.model_dump()}
    ok = await store.delete(memory_id)
    if not ok:
        raise HTTPException(404, "Memory not found")
    append_audit(
        "reject_memory_delete",
        actor=ACTOR_REVIEW,
        item_type="memory",
        item_id=memory_id,
        detail={"note": body.note},
    )
    return {"ok": True, "deleted": True, "id": memory_id}


@router.post("/kb/{page_id}/reject")
async def reject_kb(page_id: str, body: RejectBody | None = None) -> dict[str, Any]:
    body = body or RejectBody()
    from app.knowledge.store import get_knowledge_store

    store = get_knowledge_store()
    if body.archive:
        page = await store.update(
            page_id,
            status=STATUS_ARCHIVED,
            archived=True,
            changelog=body.note or "review:reject",
            via_review=True,
            source="review",
        )
        if not page:
            raise HTTPException(404, "KB page not found")
        append_audit(
            "reject_kb",
            actor=ACTOR_REVIEW,
            item_type="kb",
            item_id=page_id,
            detail={"note": body.note, "archive": True},
        )
        return {"ok": True, "item_type": "kb", "item": page}
    ok = await store.delete(page_id)
    if not ok:
        raise HTTPException(404, "KB page not found")
    append_audit(
        "reject_kb_delete",
        actor=ACTOR_REVIEW,
        item_type="kb",
        item_id=page_id,
        detail={"note": body.note},
    )
    return {"ok": True, "deleted": True, "id": page_id}


@router.post("/memory/{memory_id}/modify")
async def modify_memory(memory_id: str, body: ModifyBody) -> dict[str, Any]:
    from app.memory.store import get_memory_store

    store = get_memory_store()
    kwargs: dict[str, Any] = {}
    if body.content is not None:
        kwargs["content"] = body.content
    if body.kind is not None:
        kwargs["kind"] = body.kind
    if body.tags is not None:
        kwargs["tags"] = body.tags
    if body.confidence is not None:
        kwargs["confidence"] = clamp_confidence(body.confidence)
    item = await store.update(memory_id, **kwargs)
    if not item:
        raise HTTPException(404, "Memory not found")
    hard = is_hard_constraint_kind(item.kind)
    append_audit(
        "modify_memory",
        actor=ACTOR_UI,
        item_type="memory",
        item_id=memory_id,
        detail={"note": body.note, "hard_constraint": hard, "fields": list(kwargs)},
    )
    if body.approve_after:
        return await _approve_memory(
            memory_id,
            ApproveBody(
                note=body.note or "modify+approve",
                confidence=body.confidence,
                clear_ttl=body.clear_ttl,
                content=body.content,
                kind=body.kind,
                tags=body.tags,
            ),
        )
    return {"ok": True, "item_type": "memory", "item": item.model_dump()}


@router.post("/kb/{page_id}/modify")
async def modify_kb(page_id: str, body: ModifyBody) -> dict[str, Any]:
    from app.knowledge.store import get_knowledge_store

    store = get_knowledge_store()
    conf = (
        clamp_confidence(body.confidence)
        if body.confidence is not None
        else None
    )
    page = await store.update(
        page_id,
        title=body.title,
        content=body.content,
        tags=body.tags,
        collection=body.collection,
        confidence=conf,
        changelog=body.note or "review:modify",
    )
    if not page:
        raise HTTPException(404, "KB page not found")
    append_audit(
        "modify_kb",
        actor=ACTOR_UI,
        item_type="kb",
        item_id=page_id,
        detail={"note": body.note},
    )
    if body.approve_after:
        return await _approve_kb(
            page_id,
            ApproveBody(
                note=body.note or "modify+approve",
                confidence=body.confidence,
                clear_ttl=body.clear_ttl,
                title=body.title,
                content=body.content,
                tags=body.tags,
                collection=body.collection,
            ),
        )
    return {"ok": True, "item_type": "kb", "item": page}


@router.post("/memory/{memory_id}/downgrade")
async def downgrade_memory(
    memory_id: str, body: DowngradeBody | None = None
) -> dict[str, Any]:
    body = body or DowngradeBody()
    from app.memory.store import get_memory_store

    store = get_memory_store()
    item = await store.update(
        memory_id,
        status=STATUS_STAGING,
        ttl_days=body.ttl_days,
        via_review=True,
        source="review",
    )
    if not item:
        raise HTTPException(404, "Memory not found")
    append_audit(
        "downgrade_memory",
        actor=ACTOR_REVIEW,
        item_type="memory",
        item_id=memory_id,
        detail={"note": body.note, "ttl_days": body.ttl_days},
    )
    return {"ok": True, "item_type": "memory", "item": item.model_dump()}


@router.post("/kb/{page_id}/downgrade")
async def downgrade_kb(page_id: str, body: DowngradeBody | None = None) -> dict[str, Any]:
    body = body or DowngradeBody()
    from app.knowledge.store import get_knowledge_store

    store = get_knowledge_store()
    page = await store.update(
        page_id,
        status=STATUS_STAGING,
        collection="staging",
        ttl_days=body.ttl_days,
        changelog=body.note or "review:downgrade",
        via_review=True,
        source="review",
    )
    if not page:
        raise HTTPException(404, "KB page not found")
    append_audit(
        "downgrade_kb",
        actor=ACTOR_REVIEW,
        item_type="kb",
        item_id=page_id,
        detail={"note": body.note, "ttl_days": body.ttl_days},
    )
    return {"ok": True, "item_type": "kb", "item": page}


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_conflict(
    conflict_id: str, body: ConflictResolveBody
) -> dict[str, Any]:
    from app.knowledge.refs import get_ref_store

    store = get_ref_store()
    updated = await store.update_conflict_status(
        conflict_id,
        status=f"resolved:{body.resolution}",
        note=body.note,
    )
    if not updated:
        raise HTTPException(404, "Conflict not found")

    promoted = None
    if body.resolution == "approve_incoming" and body.promote_id:
        ptype = (body.promote_type or "memory").strip().lower()
        if ptype == "kb":
            promoted = await _approve_kb(
                body.promote_id, ApproveBody(note=body.note or "conflict resolve")
            )
        else:
            promoted = await _approve_memory(
                body.promote_id, ApproveBody(note=body.note or "conflict resolve")
            )

    append_audit(
        "resolve_conflict",
        actor=ACTOR_REVIEW,
        item_type="conflict",
        item_id=conflict_id,
        detail={"resolution": body.resolution, "note": body.note, "promoted": bool(promoted)},
    )
    return {"ok": True, "conflict": updated, "promoted": promoted}



_HISTORY_LABELS = {
    "approve_memory": "批准记忆", "approve_kb": "批准知识页",
    "reject_memory": "驳回记忆", "reject_memory_delete": "驳回并删除记忆",
    "reject_kb": "驳回知识页", "modify_memory": "修改记忆", "modify_kb": "修改知识页",
    "downgrade_memory": "降级记忆", "downgrade_kb": "降级知识页",
    "resolve_conflict": "处理冲突", "ui_delete_memory": "删除记忆",
}


@router.get("/history")
async def review_history(limit: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    """Recent human-gate actions (audit tail) with readable titles."""
    import json as _json

    from app.memory.human_gate import audit_path

    rows: list[dict[str, Any]] = []
    try:
        lines = audit_path().read_text(encoding="utf-8").splitlines()
    except Exception:
        lines = []
    for ln in reversed(lines):
        try:
            rows.append(_json.loads(ln))
        except Exception:
            continue
        if len(rows) >= limit:
            break
    titles: dict[str, str] = {}
    try:
        from app.knowledge.store import get_knowledge_store
        from app.memory.store import get_memory_store

        idx = await get_knowledge_store()._load_index()  # noqa: SLF001
        for p in idx:
            titles["kb:" + str(p.get("id"))] = str(p.get("title") or "")
        mems = await get_memory_store().list_all(limit=500, include_archived=True)
        for m in mems:
            titles["memory:" + str(m.id)] = str(m.content or "")[:80]
    except Exception:
        pass
    out = []
    for r in rows:
        key = f"{r.get('item_type')}:{r.get('item_id')}"
        out.append({
            **r,
            "label": _HISTORY_LABELS.get(str(r.get("action")), str(r.get("action"))),
            "title": titles.get(key) or "（已删除或未知条目）",
        })
    return {"ok": True, "items": out}
