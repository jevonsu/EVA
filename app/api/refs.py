"""Phase 3 REST: knowledge refs / anchors / conflict logs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.knowledge.refs import get_ref_store

router = APIRouter(prefix="/api/refs", tags=["refs"])


class LinkBody(BaseModel):
    from_type: str = Field(..., description="memory|kb|skill|reference")
    from_id: str
    to_type: str
    to_id: str
    edge_type: str = "references"
    reason: str | None = None
    ttl_days: float | None = None
    valid_to: str | None = None
    created_by: str | None = None
    weight: float = 1.0


class UnlinkBody(BaseModel):
    ref_id: str | None = None
    from_type: str | None = None
    from_id: str | None = None
    to_type: str | None = None
    to_id: str | None = None
    edge_type: str | None = None
    soft: bool = True


class AnchorBody(BaseModel):
    reference_type: str = Field(
        ..., description="user_explicit|authority|precedent|evidence|hierarchy"
    )
    resolution: str
    scope: str | None = None
    condition: str | None = None
    confidence: float = 0.9
    source: str | None = None
    created_from: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    ttl_days: float | None = None


@router.get("")
async def list_refs(
    node_type: str | None = None,
    node_id: str | None = None,
    direction: str = Query("both", pattern="^(out|in|both)$"),
    edge_type: str | None = None,
    include_expired: bool = False,
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    store = get_ref_store()
    rows = await store.list_refs(
        node_type=node_type,
        node_id=node_id,
        direction=direction,
        edge_type=edge_type,
        include_expired=include_expired,
        limit=limit,
    )
    return {"ok": True, "count": len(rows), "refs": rows}


@router.post("/link")
async def link_ref(body: LinkBody) -> dict[str, Any]:
    store = get_ref_store()
    try:
        edge = await store.link(
            from_type=body.from_type,
            from_id=body.from_id,
            to_type=body.to_type,
            to_id=body.to_id,
            edge_type=body.edge_type,
            reason=body.reason,
            ttl_days=body.ttl_days,
            valid_to=body.valid_to,
            created_by=body.created_by or "api",
            weight=body.weight,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "ref": edge}


@router.post("/unlink")
async def unlink_ref(body: UnlinkBody) -> dict[str, Any]:
    store = get_ref_store()
    try:
        result = await store.unlink(
            ref_id=body.ref_id,
            from_type=body.from_type,
            from_id=body.from_id,
            to_type=body.to_type,
            to_id=body.to_id,
            edge_type=body.edge_type,
            soft=body.soft,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return result


@router.get("/anchors")
async def list_anchors(
    scope: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    store = get_ref_store()
    rows = await store.list_anchors(
        scope=scope,
        subject_type=subject_type,
        subject_id=subject_id,
        limit=limit,
    )
    return {"ok": True, "count": len(rows), "anchors": rows}


@router.post("/anchors")
async def create_anchor(body: AnchorBody) -> dict[str, Any]:
    store = get_ref_store()
    try:
        row = await store.add_anchor(
            reference_type=body.reference_type,
            resolution=body.resolution,
            scope=body.scope,
            condition=body.condition,
            confidence=body.confidence,
            source=body.source,
            created_from=body.created_from,
            subject_type=body.subject_type,
            subject_id=body.subject_id,
            ttl_days=body.ttl_days,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "anchor": row}


@router.get("/conflicts")
async def list_conflicts(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    store = get_ref_store()
    rows = await store.list_conflicts(limit=limit)
    return {"ok": True, "count": len(rows), "conflicts": rows}


@router.get("/skill-graph")
async def skill_graph(
    skill_id: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    """Skill → knowledge ref graph (from_type=skill)."""
    from app.knowledge.skill_refs import list_skill_kb_graph

    return await list_skill_kb_graph(skill_id=skill_id, limit=limit)


@router.post("/skill-sync")
async def skill_sync(skill_id: str | None = None) -> dict[str, Any]:
    """Sync declared knowledge_refs from skill package(s) into DB."""
    from app.knowledge.skill_refs import (
        sync_all_skill_knowledge_refs,
        sync_skill_knowledge_refs,
    )

    if skill_id and skill_id.strip():
        return await sync_skill_knowledge_refs(skill_id.strip())
    return await sync_all_skill_knowledge_refs()


@router.get("/tree")
async def overview_tree(
    limit_skills: int = Query(100, ge=1, le=300),
    limit_memories: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """Lightweight read-only tree: skills → kb; control memories → refs."""
    from app.knowledge.skill_refs import build_overview_tree

    return await build_overview_tree(
        limit_skills=limit_skills, limit_memories=limit_memories
    )

