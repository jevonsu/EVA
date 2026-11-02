"""Phase 4: skill-declared knowledge_refs sync + lightweight overview tree.

Skills may declare refs in:
  - skills/<id>/manifest.json  key ``knowledge_refs`` (or agentos_meta.knowledge_refs)
  - skills/<id>/knowledge_refs.json  (array or {"refs": [...]})

Each entry becomes an eva_knowledge_refs edge with from_type=skill, from_id=<skill_id>.

Human-gate: sync is **refs only**. It never creates kb pages, never flips page
status to active/gold/certified, and never bypasses the review queue. Declared
targets stay as references until a human approves the underlying memory/kb.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.knowledge.refs import (
    EDGE_REFERENCES,
    NODE_KB,
    NODE_MEMORY,
    NODE_SKILL,
    get_ref_store,
    normalize_edge_type,
    normalize_node_type,
)
from app.storage.util import run_db

logger = logging.getLogger("app.knowledge.skill_refs")

CREATED_BY = "skill_declared"
META_DECLARED = "declared"
META_SOURCE = "source"


def _skills_root() -> Path:
    from app.services.skills import skills_root

    return skills_root()


def _normalize_ref_entry(raw: Any) -> dict[str, Any] | None:
    """Normalize one declared ref into {to_type, to_id, edge_type, reason?}."""
    if raw is None:
        return None
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        if ":" in s:
            left, right = s.split(":", 1)
            left = left.strip().lower()
            right = right.strip()
            if left in ("kb", "memory", "skill", "reference") and right:
                return {
                    "to_type": left if left != "kb" else NODE_KB,
                    "to_id": right,
                    "edge_type": EDGE_REFERENCES,
                }
            # bare "kb:page" already handled; treat whole as kb id
        return {"to_type": NODE_KB, "to_id": s, "edge_type": EDGE_REFERENCES}
    if not isinstance(raw, dict):
        return None
    # shorthand: {"kb": "page-id"} / {"memory": "..."}
    for key in ("kb", "memory", "skill", "reference"):
        if key in raw and raw.get(key) and "to_id" not in raw and "to_type" not in raw:
            return {
                "to_type": NODE_KB if key == "kb" else key,
                "to_id": str(raw[key]).strip(),
                "edge_type": normalize_edge_type(raw.get("edge_type") or EDGE_REFERENCES),
                "reason": (str(raw["reason"]).strip() if raw.get("reason") else None),
            }
    to_type = raw.get("to_type") or raw.get("type") or NODE_KB
    to_id = raw.get("to_id") or raw.get("id") or raw.get("target") or ""
    to_id = str(to_id).strip()
    if not to_id:
        return None
    return {
        "to_type": normalize_node_type(str(to_type)),
        "to_id": to_id,
        "edge_type": normalize_edge_type(raw.get("edge_type") or EDGE_REFERENCES),
        "reason": (str(raw["reason"]).strip() if raw.get("reason") else None),
    }


def _coerce_refs_list(data: Any) -> list[Any]:
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("refs", "knowledge_refs", "items", "edges"):
            if isinstance(data.get(key), list):
                return data[key]
        # single object
        if data.get("to_id") or data.get("kb") or data.get("id"):
            return [data]
    return []


def read_skill_declared_refs(skill_dir: Path | str, *, skill_id: str | None = None) -> dict[str, Any]:
    """Read declared refs from manifest and/or knowledge_refs.json sidecar."""
    root = Path(skill_dir)
    sid = (skill_id or root.name or "").strip()
    declared: list[dict[str, Any]] = []
    sources: list[str] = []
    errors: list[str] = []

    man_path = root / "manifest.json"
    if man_path.is_file():
        try:
            man = json.loads(man_path.read_text(encoding="utf-8"))
            blob = man.get("knowledge_refs")
            if blob is None and isinstance(man.get("agentos_meta"), dict):
                blob = man["agentos_meta"].get("knowledge_refs")
            for item in _coerce_refs_list(blob):
                norm = _normalize_ref_entry(item)
                if norm:
                    norm["_source"] = "manifest"
                    declared.append(norm)
            if blob is not None:
                sources.append("manifest")
        except Exception as exc:
            errors.append(f"manifest: {exc}")

    side = root / "knowledge_refs.json"
    if side.is_file():
        try:
            data = json.loads(side.read_text(encoding="utf-8"))
            for item in _coerce_refs_list(data):
                norm = _normalize_ref_entry(item)
                if norm:
                    norm["_source"] = "sidecar"
                    declared.append(norm)
            sources.append("sidecar")
        except Exception as exc:
            errors.append(f"sidecar: {exc}")

    # Dedupe by (to_type, to_id, edge_type); prefer sidecar over manifest
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    for d in declared:
        key = (d["to_type"], d["to_id"], d["edge_type"])
        prev = seen.get(key)
        if prev and prev.get("_source") == "sidecar" and d.get("_source") != "sidecar":
            continue
        seen[key] = d
    unique = list(seen.values())
    return {
        "skill_id": sid,
        "path": str(root.resolve()) if root.exists() else str(root),
        "sources": sources,
        "declared": [
            {
                "to_type": x["to_type"],
                "to_id": x["to_id"],
                "edge_type": x["edge_type"],
                "reason": x.get("reason"),
                "source": x.get("_source"),
            }
            for x in unique
        ],
        "errors": errors,
    }


def sync_skill_knowledge_refs_sync(
    skill_id: str,
    *,
    skill_dir: Path | str | None = None,
    prune_missing: bool = True,
) -> dict[str, Any]:
    """Create/update edges for declared refs; optionally soft-expire removed declarations.

    Does not mint or certify knowledge pages (refs only / no gold).
    """
    sid = (skill_id or "").strip()
    if not sid:
        return {"ok": False, "error": "empty skill_id"}
    root = Path(skill_dir) if skill_dir else (_skills_root() / sid)
    if not root.is_dir():
        return {"ok": False, "skill_id": sid, "error": f"skill dir missing: {root}"}

    info = read_skill_declared_refs(root, skill_id=sid)
    store = get_ref_store()
    linked: list[dict[str, Any]] = []
    wanted: set[tuple[str, str, str]] = set()

    for d in info["declared"]:
        key = (d["to_type"], d["to_id"], d["edge_type"])
        wanted.add(key)
        try:
            edge = store.link_sync(
                from_type=NODE_SKILL,
                from_id=sid,
                to_type=d["to_type"],
                to_id=d["to_id"],
                edge_type=d["edge_type"],
                reason=d.get("reason") or f"skill:{sid} declared",
                created_by=CREATED_BY,
                meta={
                    META_DECLARED: True,
                    META_SOURCE: d.get("source") or "manifest",
                    "skill_id": sid,
                },
                dedupe=True,
            )
            linked.append(edge)
        except Exception as exc:
            logger.warning("sync skill ref %s -> %s failed: %s", sid, key, exc)
            info.setdefault("link_errors", []).append({"ref": d, "error": str(exc)})

    pruned: list[str] = []
    if prune_missing:
        existing = store.list_refs_sync(
            node_type=NODE_SKILL,
            node_id=sid,
            direction="out",
            include_expired=False,
            limit=500,
        )
        for e in existing:
            meta = e.get("meta") or {}
            if not meta.get(META_DECLARED) and e.get("created_by") != CREATED_BY:
                continue
            key = (e["to_type"], e["to_id"], e["edge_type"])
            if key not in wanted:
                try:
                    store.unlink_sync(ref_id=e["id"], soft=True)
                    pruned.append(e["id"])
                except Exception as exc:
                    logger.warning("prune skill ref %s failed: %s", e.get("id"), exc)

    return {
        "ok": True,
        "skill_id": sid,
        "sources": info["sources"],
        "declared_count": len(info["declared"]),
        "linked_count": len(linked),
        "pruned_count": len(pruned),
        "declared": info["declared"],
        "linked": linked,
        "pruned": pruned,
        "errors": info.get("errors") or [],
        "link_errors": info.get("link_errors") or [],
    }


async def sync_skill_knowledge_refs(skill_id: str, **kwargs: Any) -> dict[str, Any]:
    return await run_db(lambda: sync_skill_knowledge_refs_sync(skill_id, **kwargs))


def sync_all_skill_knowledge_refs_sync(*, prune_missing: bool = True) -> dict[str, Any]:
    root = _skills_root()
    results: list[dict[str, Any]] = []
    if not root.is_dir():
        return {"ok": True, "skills": 0, "results": [], "note": "no skills root"}
    for path in sorted(root.iterdir()):
        if not path.is_dir() or path.name.startswith((".", "_")):
            continue
        # Only sync packages that declare something or already have declared edges
        info = read_skill_declared_refs(path, skill_id=path.name)
        if not info["declared"] and not info["errors"]:
            # still prune if old declared edges linger
            store = get_ref_store()
            existing = store.list_refs_sync(
                node_type=NODE_SKILL,
                node_id=path.name,
                direction="out",
                include_expired=False,
                limit=20,
            )
            has_declared = any(
                (e.get("meta") or {}).get(META_DECLARED) or e.get("created_by") == CREATED_BY
                for e in existing
            )
            if not has_declared:
                continue
        results.append(
            sync_skill_knowledge_refs_sync(
                path.name, skill_dir=path, prune_missing=prune_missing
            )
        )
    return {
        "ok": True,
        "skills": len(results),
        "linked_total": sum(int(r.get("linked_count") or 0) for r in results),
        "pruned_total": sum(int(r.get("pruned_count") or 0) for r in results),
        "results": results,
    }


async def sync_all_skill_knowledge_refs(**kwargs: Any) -> dict[str, Any]:
    return await run_db(lambda: sync_all_skill_knowledge_refs_sync(**kwargs))


def list_skill_kb_graph_sync(*, skill_id: str | None = None, limit: int = 200) -> dict[str, Any]:
    """Skill → kb (and other) edge graph for tools / API."""
    store = get_ref_store()
    sid = (skill_id or "").strip() or None
    if sid:
        edges = store.list_refs_sync(
            node_type=NODE_SKILL,
            node_id=sid,
            direction="out",
            include_expired=False,
            limit=limit,
        )
        skills_scanned = [sid]
    else:
        edges = [
            e
            for e in store.list_refs_sync(include_expired=False, limit=max(limit, 500))
            if e.get("from_type") == NODE_SKILL
        ][:limit]
        skills_scanned = sorted({e["from_id"] for e in edges})

    # Enrich with declarations from disk
    by_skill: dict[str, dict[str, Any]] = {}
    root = _skills_root()
    ids = skills_scanned if sid else (
        [p.name for p in sorted(root.iterdir()) if p.is_dir() and not p.name.startswith((".", "_"))]
        if root.is_dir()
        else skills_scanned
    )
    for s in ids:
        path = root / s
        decl = read_skill_declared_refs(path, skill_id=s) if path.is_dir() else {
            "skill_id": s,
            "declared": [],
            "sources": [],
            "errors": ["missing dir"],
        }
        skill_edges = [e for e in edges if e["from_id"] == s]
        by_skill[s] = {
            "id": s,
            "declared": decl.get("declared") or [],
            "sources": decl.get("sources") or [],
            "edges": skill_edges,
            "kb_targets": sorted(
                {
                    e["to_id"]
                    for e in skill_edges
                    if e.get("to_type") == NODE_KB
                }
            ),
        }

    return {
        "ok": True,
        "skill_id": sid,
        "count_edges": len(edges),
        "count_skills": len(by_skill),
        "skills": list(by_skill.values()),
        "edges": edges,
    }


async def list_skill_kb_graph(**kwargs: Any) -> dict[str, Any]:
    return await run_db(lambda: list_skill_kb_graph_sync(**kwargs))


def build_overview_tree_sync(*, limit_skills: int = 100, limit_memories: int = 50) -> dict[str, Any]:
    """Read-only tree: skills → kb refs; control memories → refs."""
    from app.memory.control_plane import CONTROL_KINDS
    from app.memory.store import get_memory_store
    from app.services.skills import scan_skills

    store = get_ref_store()
    graph = list_skill_kb_graph_sync(limit=500)
    skills_info = {s["id"]: s for s in scan_skills()}
    skill_nodes = []
    for item in (graph.get("skills") or []):
        sid = item["id"]
        meta = skills_info.get(sid) or {}
        declared = item.get("declared") or []
        edges = item.get("edges") or []
        if not declared and not edges:
            continue
        skill_nodes.append(
            {
                "type": "skill",
                "id": sid,
                "name": meta.get("name") or sid,
                "enabled": meta.get("enabled", True),
                "declared": declared,
                "children": [
                    {
                        "type": e.get("to_type") or "kb",
                        "id": e.get("to_id"),
                        "edge_type": e.get("edge_type"),
                        "status": e.get("status"),
                        "ref_id": e.get("id"),
                        "reason": e.get("reason"),
                    }
                    for e in edges
                ],
            }
        )
        if len(skill_nodes) >= limit_skills:
            break

    # Skills that only have declarations on disk (not yet synced / empty edges)
    for s in scan_skills():
        sid = s["id"]
        if any(n["id"] == sid for n in skill_nodes):
            continue
        path = Path(s.get("path") or "")
        decl = read_skill_declared_refs(path, skill_id=sid) if path.is_dir() else {"declared": []}
        if not decl.get("declared"):
            continue
        skill_nodes.append(
            {
                "type": "skill",
                "id": sid,
                "name": s.get("name") or sid,
                "enabled": s.get("enabled", True),
                "declared": decl.get("declared") or [],
                "children": [
                    {
                        "type": d["to_type"],
                        "id": d["to_id"],
                        "edge_type": d["edge_type"],
                        "status": "declared_only",
                        "reason": d.get("reason"),
                    }
                    for d in (decl.get("declared") or [])
                ],
            }
        )

    # Control-plane memories (dicts from SQL loader)
    mem_store = get_memory_store()
    try:
        memories = mem_store._load_all_sync(include_archived=False)
    except Exception as exc:
        logger.warning("overview: load memories failed: %s", exc)
        memories = []

    control_nodes = []
    for m in memories or []:
        kind = str(m.get("kind") or "").lower()
        if kind not in CONTROL_KINDS:
            continue
        mid = m.get("id")
        refs = store.list_refs_sync(
            node_type=NODE_MEMORY,
            node_id=str(mid),
            direction="out",
            include_expired=False,
            limit=50,
        )
        content = str(m.get("content") or "")
        control_nodes.append(
            {
                "type": "memory",
                "id": mid,
                "kind": kind,
                "status": m.get("status"),
                "summary": content[:120],
                "children": [
                    {
                        "type": r.get("to_type"),
                        "id": r.get("to_id"),
                        "edge_type": r.get("edge_type"),
                        "status": r.get("status"),
                        "ref_id": r.get("id"),
                    }
                    for r in refs
                ],
            }
        )
        if len(control_nodes) >= limit_memories:
            break

    return {
        "ok": True,
        "tree": {
            "skills": skill_nodes,
            "control_memories": control_nodes,
        },
        "summary": {
            "skills": len(skill_nodes),
            "skill_edges": sum(len(n.get("children") or []) for n in skill_nodes),
            "control_memories": len(control_nodes),
            "control_edges": sum(len(n.get("children") or []) for n in control_nodes),
        },
    }


async def build_overview_tree(**kwargs: Any) -> dict[str, Any]:
    return await run_db(lambda: build_overview_tree_sync(**kwargs))
