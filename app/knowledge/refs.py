"""Phase 3: knowledge reference edges, reference anchors, light conflict arbitration.

Edges link memory / kb / skill nodes. Reference anchors resolve conflicts
(user_explicit > authority > precedent > evidence > hierarchy). L0 auto,
L1 lookup refs, L2 log review_required (review queue UI in settings).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, insert, select, text, update

from app.storage.engine import db_connect
from app.storage.lifecycle import (
    compute_valid_to,
    is_expired_by_valid_to,
    normalize_status,
    parse_iso,
)
from app.storage.schema import conflict_logs as conflict_logs_t
from app.storage.schema import knowledge_refs as knowledge_refs_t
from app.storage.schema import reference_anchors as reference_anchors_t
from app.storage.util import dumps, loads, run_db

logger = logging.getLogger("app.knowledge.refs")

EDGE_REFERENCES = "references"
EDGE_CONTROLS = "controls"
EDGE_SUPERSEDES = "supersedes"
EDGE_CONTRADICTS = "contradicts"
VALID_EDGE_TYPES = frozenset(
    {EDGE_REFERENCES, EDGE_CONTROLS, EDGE_SUPERSEDES, EDGE_CONTRADICTS}
)

NODE_MEMORY = "memory"
NODE_KB = "kb"
NODE_SKILL = "skill"
NODE_REFERENCE = "reference"
VALID_NODE_TYPES = frozenset({NODE_MEMORY, NODE_KB, NODE_SKILL, NODE_REFERENCE})

REF_STATUS_ACTIVE = "active"
REF_STATUS_DORMANT = "dormant"
REF_STATUS_EXPIRED = "expired"
VALID_REF_STATUSES = frozenset(
    {REF_STATUS_ACTIVE, REF_STATUS_DORMANT, REF_STATUS_EXPIRED}
)

# Reference type priority (lower index = higher priority)
REF_TYPE_ORDER = (
    "user_explicit",
    "authority",
    "precedent",
    "evidence",
    "hierarchy",
)
REF_TYPE_RANK = {name: i for i, name in enumerate(REF_TYPE_ORDER)}

# Edge dormancy / expiry (days without use)
DORMANT_AFTER_DAYS = 30
EXPIRE_AFTER_DAYS = 180
DEFAULT_EDGE_TTL_DAYS = 180

# Soft contradiction cues (light heuristic)
_NEG_CUES = (
    "禁止",
    "不要",
    "不可",
    "不许",
    "不得",
    "绝不",
    "严禁",
    "must not",
    "do not",
    "don't",
    "never",
    "forbid",
    "禁止使用",
)
_POS_CUES = (
    "必须",
    "一定要",
    "总是",
    "始终",
    "always",
    "must ",
    "require",
    "强制",
)

HARD_CONSTRAINT_KINDS = frozenset({"constraint", "rule"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def normalize_edge_type(value: str | None) -> str:
    s = str(value or "").strip().lower()
    aliases = {
        "ref": EDGE_REFERENCES,
        "reference": EDGE_REFERENCES,
        "refs": EDGE_REFERENCES,
        "control": EDGE_CONTROLS,
        "ctrl": EDGE_CONTROLS,
        "supersede": EDGE_SUPERSEDES,
        "replace": EDGE_SUPERSEDES,
        "contradict": EDGE_CONTRADICTS,
        "conflict": EDGE_CONTRADICTS,
        "conflicts": EDGE_CONTRADICTS,
    }
    s = aliases.get(s, s)
    if s not in VALID_EDGE_TYPES:
        raise ValueError(
            f"edge_type must be one of {sorted(VALID_EDGE_TYPES)}, got {value!r}"
        )
    return s


def normalize_node_type(value: str | None) -> str:
    s = str(value or "").strip().lower()
    aliases = {
        "mem": NODE_MEMORY,
        "page": NODE_KB,
        "wiki": NODE_KB,
        "knowledge": NODE_KB,
        "kb_page": NODE_KB,
        "anchor": NODE_REFERENCE,
        "ref_anchor": NODE_REFERENCE,
    }
    s = aliases.get(s, s)
    if s not in VALID_NODE_TYPES:
        raise ValueError(
            f"node type must be one of {sorted(VALID_NODE_TYPES)}, got {value!r}"
        )
    return s


def normalize_ref_status(value: str | None) -> str:
    s = str(value or "").strip().lower() or REF_STATUS_ACTIVE
    if s not in VALID_REF_STATUSES:
        return REF_STATUS_ACTIVE
    return s


def normalize_reference_type(value: str | None) -> str:
    s = str(value or "").strip().lower()
    aliases = {
        "user": "user_explicit",
        "explicit": "user_explicit",
        "用户显式": "user_explicit",
        "权威": "authority",
        "规范": "authority",
        "先例": "precedent",
        "证据": "evidence",
        "层级": "hierarchy",
    }
    s = aliases.get(s, s)
    if s not in REF_TYPE_RANK:
        # allow unknown but rank last
        return s or "evidence"
    return s


def _edge_row_dict(row: Any) -> dict[str, Any]:
    meta = loads(getattr(row, "meta_json", None) or "{}", {})
    if not isinstance(meta, dict):
        meta = {}
    return {
        "id": row.id,
        "from_type": row.from_type,
        "from_id": row.from_id,
        "to_type": row.to_type,
        "to_id": row.to_id,
        "edge_type": row.edge_type,
        "status": normalize_ref_status(getattr(row, "status", None)),
        "valid_from": getattr(row, "valid_from", None),
        "valid_to": getattr(row, "valid_to", None),
        "use_count": int(getattr(row, "use_count", 0) or 0),
        "last_used_at": getattr(row, "last_used_at", None),
        "weight": float(getattr(row, "weight", 1.0) or 1.0),
        "reason": getattr(row, "reason", None),
        "created_by": getattr(row, "created_by", None),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "meta": meta,
    }


def _anchor_row_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "reference_type": normalize_reference_type(row.reference_type),
        "scope": getattr(row, "scope", None),
        "condition": getattr(row, "condition", None),
        "resolution": getattr(row, "resolution", "") or "",
        "confidence": float(getattr(row, "confidence", 0.8) or 0.8),
        "status": normalize_status(getattr(row, "status", None)),
        "valid_from": getattr(row, "valid_from", None),
        "valid_to": getattr(row, "valid_to", None),
        "source": getattr(row, "source", None),
        "created_from": getattr(row, "created_from", None),
        "subject_type": getattr(row, "subject_type", None),
        "subject_id": getattr(row, "subject_id", None),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def is_edge_visible(row: dict[str, Any], *, now: datetime | None = None) -> bool:
    now = now or _now()
    st = normalize_ref_status(row.get("status"))
    if st == REF_STATUS_EXPIRED:
        return False
    if is_expired_by_valid_to(row, now=now):
        return False
    return True


class KnowledgeRefStore:
    """CRUD for edges + anchors + light conflict helpers."""

    # ----- edges -----

    def link_sync(
        self,
        *,
        from_type: str,
        from_id: str,
        to_type: str,
        to_id: str,
        edge_type: str = EDGE_REFERENCES,
        status: str = REF_STATUS_ACTIVE,
        valid_to: str | None = None,
        ttl_days: float | int | None = None,
        reason: str | None = None,
        created_by: str | None = None,
        weight: float = 1.0,
        meta: dict[str, Any] | None = None,
        dedupe: bool = True,
    ) -> dict[str, Any]:
        ft = normalize_node_type(from_type)
        tt = normalize_node_type(to_type)
        fid = str(from_id or "").strip()
        tid = str(to_id or "").strip()
        if not fid or not tid:
            raise ValueError("from_id and to_id are required")
        et = normalize_edge_type(edge_type)
        now = _now_iso()
        vt = compute_valid_to(valid_to=valid_to, ttl_days=ttl_days)
        if vt is None and et in (EDGE_REFERENCES, EDGE_CONTROLS):
            # default soft TTL so edges do not grow forever
            vt = compute_valid_to(ttl_days=DEFAULT_EDGE_TTL_DAYS)

        with db_connect() as conn:
            if dedupe:
                existing = conn.execute(
                    select(knowledge_refs_t)
                    .where(knowledge_refs_t.c.from_type == ft)
                    .where(knowledge_refs_t.c.from_id == fid)
                    .where(knowledge_refs_t.c.to_type == tt)
                    .where(knowledge_refs_t.c.to_id == tid)
                    .where(knowledge_refs_t.c.edge_type == et)
                    # 含 expired：软过期边复活为 upsert，避免再次 sync 堆重复边
                    .order_by(knowledge_refs_t.c.updated_at.desc())
                ).all()
                existing = existing[0] if existing else None
                if existing is not None:
                    # 同端点同类型的多余旧边（历史重复）一并硬删
                    dup_ids = [
                        r.id
                        for r in conn.execute(
                            select(knowledge_refs_t.c.id)
                            .where(knowledge_refs_t.c.from_type == ft)
                            .where(knowledge_refs_t.c.from_id == fid)
                            .where(knowledge_refs_t.c.to_type == tt)
                            .where(knowledge_refs_t.c.to_id == tid)
                            .where(knowledge_refs_t.c.edge_type == et)
                            .where(knowledge_refs_t.c.id != existing.id)
                        ).all()
                    ]
                    if dup_ids:
                        conn.execute(
                            delete(knowledge_refs_t).where(
                                knowledge_refs_t.c.id.in_(dup_ids)
                            )
                        )
                    conn.execute(
                        update(knowledge_refs_t)
                        .where(knowledge_refs_t.c.id == existing.id)
                        .values(
                            status=normalize_ref_status(status),
                            valid_to=vt or existing.valid_to,
                            reason=reason if reason is not None else existing.reason,
                            weight=float(weight),
                            updated_at=now,
                            last_used_at=now,
                            use_count=int(existing.use_count or 0) + 1,
                            meta_json=dumps(meta)
                            if meta is not None
                            else (existing.meta_json or "{}"),
                        )
                    )
                    row = conn.execute(
                        select(knowledge_refs_t).where(
                            knowledge_refs_t.c.id == existing.id
                        )
                    ).first()
                    return _edge_row_dict(row)

            eid = uuid.uuid4().hex
            conn.execute(
                insert(knowledge_refs_t).values(
                    id=eid,
                    from_type=ft,
                    from_id=fid,
                    to_type=tt,
                    to_id=tid,
                    edge_type=et,
                    status=normalize_ref_status(status),
                    valid_from=now,
                    valid_to=vt,
                    use_count=0,
                    last_used_at=None,
                    weight=float(weight),
                    reason=reason,
                    created_by=created_by,
                    created_at=now,
                    updated_at=now,
                    meta_json=dumps(meta or {}),
                )
            )
            row = conn.execute(
                select(knowledge_refs_t).where(knowledge_refs_t.c.id == eid)
            ).first()
            return _edge_row_dict(row)

    async def link(self, **kwargs: Any) -> dict[str, Any]:
        return await run_db(lambda: self.link_sync(**kwargs))

    def unlink_sync(
        self,
        *,
        ref_id: str | None = None,
        from_type: str | None = None,
        from_id: str | None = None,
        to_type: str | None = None,
        to_id: str | None = None,
        edge_type: str | None = None,
        soft: bool = True,
    ) -> dict[str, Any]:
        """Unlink by id, or by endpoints. soft=True → status=expired."""
        with db_connect() as conn:
            rows_q = select(knowledge_refs_t)
            if ref_id:
                rows_q = rows_q.where(knowledge_refs_t.c.id == str(ref_id).strip())
            else:
                if not (from_id and to_id):
                    raise ValueError("ref_id or (from_id + to_id) required")
                ft = normalize_node_type(from_type or NODE_MEMORY)
                tt = normalize_node_type(to_type or NODE_KB)
                rows_q = (
                    rows_q.where(knowledge_refs_t.c.from_type == ft)
                    .where(knowledge_refs_t.c.from_id == str(from_id).strip())
                    .where(knowledge_refs_t.c.to_type == tt)
                    .where(knowledge_refs_t.c.to_id == str(to_id).strip())
                )
                if edge_type:
                    rows_q = rows_q.where(
                        knowledge_refs_t.c.edge_type
                        == normalize_edge_type(edge_type)
                    )
            found = conn.execute(rows_q).all()
            if not found:
                return {"ok": False, "removed": 0, "ids": []}
            ids = [r.id for r in found]
            now = _now_iso()
            if soft:
                for rid in ids:
                    conn.execute(
                        update(knowledge_refs_t)
                        .where(knowledge_refs_t.c.id == rid)
                        .values(status=REF_STATUS_EXPIRED, updated_at=now)
                    )
            else:
                for rid in ids:
                    conn.execute(
                        delete(knowledge_refs_t).where(knowledge_refs_t.c.id == rid)
                    )
            return {"ok": True, "removed": len(ids), "ids": ids, "soft": soft}

    async def unlink(self, **kwargs: Any) -> dict[str, Any]:
        return await run_db(lambda: self.unlink_sync(**kwargs))

    def list_refs_sync(
        self,
        *,
        node_type: str | None = None,
        node_id: str | None = None,
        direction: str = "both",  # out|in|both
        edge_type: str | None = None,
        include_expired: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with db_connect() as conn:
            rows = conn.execute(
                select(knowledge_refs_t).order_by(knowledge_refs_t.c.updated_at.desc())
            ).all()
        out: list[dict[str, Any]] = []
        nt = normalize_node_type(node_type) if node_type else None
        nid = str(node_id or "").strip() if node_id else ""
        et = normalize_edge_type(edge_type) if edge_type else None
        direction = (direction or "both").strip().lower()
        for r in rows:
            d = _edge_row_dict(r)
            if not include_expired and not is_edge_visible(d):
                continue
            if et and d["edge_type"] != et:
                continue
            if nt and nid:
                match_out = d["from_type"] == nt and d["from_id"] == nid
                match_in = d["to_type"] == nt and d["to_id"] == nid
                if direction == "out" and not match_out:
                    continue
                if direction == "in" and not match_in:
                    continue
                if direction == "both" and not (match_out or match_in):
                    continue
            out.append(d)
            if len(out) >= max(1, int(limit)):
                break
        return out

    async def list_refs(self, **kwargs: Any) -> list[dict[str, Any]]:
        return await run_db(lambda: self.list_refs_sync(**kwargs))

    def touch_sync(self, ref_id: str) -> None:
        now = _now_iso()
        with db_connect() as conn:
            row = conn.execute(
                select(knowledge_refs_t).where(knowledge_refs_t.c.id == ref_id)
            ).first()
            if not row:
                return
            conn.execute(
                update(knowledge_refs_t)
                .where(knowledge_refs_t.c.id == ref_id)
                .values(
                    use_count=int(row.use_count or 0) + 1,
                    last_used_at=now,
                    updated_at=now,
                    status=REF_STATUS_ACTIVE
                    if row.status == REF_STATUS_DORMANT
                    else row.status,
                )
            )

    async def touch(self, ref_id: str) -> None:
        await run_db(lambda: self.touch_sync(ref_id))

    # ----- anchors -----

    def add_anchor_sync(
        self,
        *,
        reference_type: str,
        resolution: str,
        scope: str | None = None,
        condition: str | None = None,
        confidence: float = 0.9,
        source: str | None = None,
        created_from: str | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
        valid_to: str | None = None,
        ttl_days: float | int | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        now = _now_iso()
        aid = uuid.uuid4().hex
        vt = compute_valid_to(valid_to=valid_to, ttl_days=ttl_days)
        with db_connect() as conn:
            conn.execute(
                insert(reference_anchors_t).values(
                    id=aid,
                    reference_type=normalize_reference_type(reference_type),
                    scope=(str(scope).strip() if scope else None) or None,
                    condition=condition,
                    resolution=resolution or "",
                    confidence=float(confidence),
                    status=normalize_status(status),
                    valid_from=now,
                    valid_to=vt,
                    source=source,
                    created_from=created_from,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            row = conn.execute(
                select(reference_anchors_t).where(reference_anchors_t.c.id == aid)
            ).first()
            return _anchor_row_dict(row)

    async def add_anchor(self, **kwargs: Any) -> dict[str, Any]:
        return await run_db(lambda: self.add_anchor_sync(**kwargs))

    def list_anchors_sync(
        self,
        *,
        scope: str | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
        include_expired: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with db_connect() as conn:
            rows = conn.execute(
                select(reference_anchors_t).order_by(
                    reference_anchors_t.c.created_at.desc()
                )
            ).all()
        out: list[dict[str, Any]] = []
        scope_l = (scope or "").strip().lower()
        for r in rows:
            d = _anchor_row_dict(r)
            if not include_expired:
                if d.get("status") not in ("active",):
                    continue
                if is_expired_by_valid_to(d):
                    continue
            if scope_l and (str(d.get("scope") or "").lower() != scope_l):
                # soft match: scope contained
                if scope_l not in str(d.get("scope") or "").lower() and scope_l not in (
                    str(d.get("condition") or "") + " " + str(d.get("resolution") or "")
                ).lower():
                    continue
            if subject_type and d.get("subject_type") and d["subject_type"] != subject_type:
                continue
            if subject_id and d.get("subject_id") and d["subject_id"] != subject_id:
                continue
            out.append(d)
            if len(out) >= max(1, int(limit)):
                break
        # sort by reference type priority then confidence
        out.sort(
            key=lambda a: (
                REF_TYPE_RANK.get(a.get("reference_type") or "", 99),
                -float(a.get("confidence") or 0),
            )
        )
        return out

    async def list_anchors(self, **kwargs: Any) -> list[dict[str, Any]]:
        return await run_db(lambda: self.list_anchors_sync(**kwargs))

    # ----- conflict log -----

    def log_conflict_sync(
        self,
        *,
        summary: str,
        level: str = "L2",
        status: str = "review_required",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cid = uuid.uuid4().hex
        now = _now_iso()
        with db_connect() as conn:
            conn.execute(
                insert(conflict_logs_t).values(
                    id=cid,
                    created_at=now,
                    level=str(level or "L2"),
                    status=str(status or "logged"),
                    summary=summary or "",
                    payload_json=dumps(payload or {}),
                )
            )
        logger.info("Conflict %s [%s]: %s", status, level, (summary or "")[:200])
        return {
            "id": cid,
            "created_at": now,
            "level": level,
            "status": status,
            "summary": summary,
            "payload": payload or {},
        }

    async def log_conflict(self, **kwargs: Any) -> dict[str, Any]:
        return await run_db(lambda: self.log_conflict_sync(**kwargs))

    def list_conflicts_sync(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with db_connect() as conn:
            rows = conn.execute(
                select(conflict_logs_t)
                .order_by(conflict_logs_t.c.created_at.desc())
                .limit(max(1, int(limit)))
            ).all()
        out = []
        for r in rows:
            out.append(
                {
                    "id": r.id,
                    "created_at": r.created_at,
                    "level": r.level,
                    "status": r.status,
                    "summary": r.summary,
                    "payload": loads(r.payload_json, {}),
                }
            )
        return out

    async def list_conflicts(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return await run_db(lambda: self.list_conflicts_sync(limit=limit))

    def update_conflict_status_sync(
        self,
        conflict_id: str,
        *,
        status: str,
        note: str = "",
    ) -> dict[str, Any] | None:
        cid = str(conflict_id or "").strip()
        if not cid:
            return None
        with db_connect() as conn:
            row = conn.execute(
                select(conflict_logs_t).where(conflict_logs_t.c.id == cid)
            ).first()
            if not row:
                return None
            payload = loads(row.payload_json, {})
            if not isinstance(payload, dict):
                payload = {}
            if note:
                hist = list(payload.get("resolution_notes") or [])
                hist.append({"note": note, "at": _now_iso(), "status": status})
                payload["resolution_notes"] = hist[-20:]
                payload["last_note"] = note
            conn.execute(
                update(conflict_logs_t)
                .where(conflict_logs_t.c.id == cid)
                .values(status=str(status or "logged"), payload_json=dumps(payload))
            )
        return {
            "id": row.id,
            "created_at": row.created_at,
            "level": row.level,
            "status": str(status or "logged"),
            "summary": row.summary,
            "payload": payload,
        }

    async def update_conflict_status(
        self,
        conflict_id: str,
        *,
        status: str,
        note: str = "",
    ) -> dict[str, Any] | None:
        return await run_db(
            lambda: self.update_conflict_status_sync(
                conflict_id, status=status, note=note
            )
        )


_store: KnowledgeRefStore | None = None


def get_ref_store() -> KnowledgeRefStore:
    global _store
    if _store is None:
        _store = KnowledgeRefStore()
    return _store


def reset_ref_store() -> None:
    global _store
    _store = None


# ----- heuristics & arbitration -----


def _normalize_text(s: str) -> str:
    t = re.sub(r"\s+", " ", (s or "").strip().lower())
    for prefix in (
        "用户偏好：",
        "偏好：",
        "约束：",
        "规则：",
        "禁止：",
        "preference:",
        "constraint:",
        "rule:",
    ):
        if t.startswith(prefix.lower()) or t.startswith(prefix):
            t = t[len(prefix) :].strip()
            break
    return t


def _core_topic(text: str) -> str:
    t = _normalize_text(text)
    for cue in _NEG_CUES + _POS_CUES:
        t = t.replace(cue.lower(), " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:60]


def looks_contradictory(a: str, b: str) -> bool:
    """Light heuristic: same topic core + opposing polarity cues."""
    ta, tb = _normalize_text(a), _normalize_text(b)
    if not ta or not tb:
        return False
    ca, cb = _core_topic(a), _core_topic(b)
    if len(ca) < 2 or len(cb) < 2:
        return False
    # topic overlap
    if ca != cb and ca not in cb and cb not in ca:
        # token overlap on CJK bigrams / words
        def toks(s: str) -> set[str]:
            out = set()
            for w in re.split(r"[\s,.;:!?]+", s):
                if len(w) >= 2:
                    out.add(w)
            ch = re.findall(r"[一-鿿]", s)
            for i in range(len(ch) - 1):
                out.add(ch[i] + ch[i + 1])
            return out

        oa, ob = toks(ca), toks(cb)
        if not oa or not ob:
            return False
        inter = oa & ob
        if len(inter) < 1 or len(inter) / max(1, min(len(oa), len(ob))) < 0.4:
            return False
    a_neg = any(c in ta for c in _NEG_CUES)
    b_neg = any(c in tb for c in _NEG_CUES)
    a_pos = any(c in ta for c in _POS_CUES)
    b_pos = any(c in tb for c in _POS_CUES)
    if (a_neg and b_pos) or (a_pos and b_neg) or (a_neg != b_neg and (a_neg or b_neg)):
        # if one has clear negation and other does not on same topic
        if a_neg != b_neg:
            return True
        if (a_neg and b_pos) or (a_pos and b_neg):
            return True
    return False


def arbitrate_l0(
    *,
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """L0 automatic: scope/status/time/explicit. Returns decision dict."""
    # status: ignore inactive existing
    est = str(existing.get("status") or "active").lower()
    if est in ("expired", "archived", "superseded"):
        return {
            "level": "L0",
            "decision": "incoming_wins",
            "reason": f"existing_status={est}",
        }
    # explicit supersedes
    if incoming.get("supersedes_id") and incoming.get("supersedes_id") == existing.get(
        "id"
    ):
        return {
            "level": "L0",
            "decision": "incoming_wins",
            "reason": "explicit_supersedes",
        }
    # time: newer soft prefs win if not hard constraint
    in_kind = str(incoming.get("kind") or "").lower()
    ex_kind = str(existing.get("kind") or "").lower()
    if ex_kind in HARD_CONSTRAINT_KINDS and in_kind not in HARD_CONSTRAINT_KINDS:
        return {
            "level": "L0",
            "decision": "keep_existing",
            "reason": "hard_constraint_protected",
        }
    if in_kind in HARD_CONSTRAINT_KINDS and ex_kind in HARD_CONSTRAINT_KINDS:
        # both hard — escalate unless same key supersede path already handled
        return {
            "level": "L0",
            "decision": "escalate",
            "reason": "two_hard_constraints",
        }
    # soft: newer wins
    return {
        "level": "L0",
        "decision": "incoming_wins",
        "reason": "newer_soft_preference",
    }


def arbitrate_l1(
    anchors: list[dict[str, Any]],
    *,
    topic: str = "",
) -> dict[str, Any]:
    """Pick best reference anchor. Empty → escalate."""
    if not anchors:
        return {
            "level": "L1",
            "decision": "escalate",
            "reason": "no_reference_anchor",
            "anchor": None,
        }
    # already sorted by priority in list_anchors_sync
    best = anchors[0]
    return {
        "level": "L1",
        "decision": "follow_reference",
        "reason": f"anchor_type={best.get('reference_type')}",
        "anchor": best,
    }


def detect_and_handle_write_conflict(
    *,
    existing_rows: list[dict[str, Any]],
    incoming_kind: str,
    incoming_content: str,
    incoming_id: str | None = None,
    incoming_tags: list[str] | None = None,
    supersedes_id: str | None = None,
    auto_link: bool = True,
) -> dict[str, Any]:
    """Run light conflict detection on memory write path.

    Returns {ok, blocked, conflicts[], actions[], notes[]}.
    Hard constraints are never silently overwritten without supersede/ref.
    """
    store = get_ref_store()
    notes: list[str] = []
    actions: list[str] = []
    conflicts: list[dict[str, Any]] = []
    blocked = False

    incoming = {
        "id": incoming_id,
        "kind": incoming_kind,
        "content": incoming_content,
        "tags": incoming_tags or [],
        "supersedes_id": supersedes_id,
        "status": "active",
    }

    for row in existing_rows:
        if str(row.get("id") or "") == (incoming_id or ""):
            continue
        if str(row.get("status") or "active") not in ("active", "conflicted"):
            continue
        if not looks_contradictory(str(row.get("content") or ""), incoming_content):
            continue

        conflict = {
            "existing_id": row.get("id"),
            "existing_kind": row.get("kind"),
            "existing_content": (str(row.get("content") or ""))[:160],
        }
        l0 = arbitrate_l0(existing=row, incoming=incoming)
        conflict["l0"] = l0

        if l0["decision"] == "incoming_wins":
            conflicts.append(conflict)
            notes.append("l0_incoming_wins")
            if auto_link and row.get("id") and incoming_id:
                try:
                    store.link_sync(
                        from_type=NODE_MEMORY,
                        from_id=str(incoming_id),
                        to_type=NODE_MEMORY,
                        to_id=str(row["id"]),
                        edge_type=EDGE_SUPERSEDES
                        if l0.get("reason") == "explicit_supersedes"
                        else EDGE_CONTRADICTS,
                        reason=f"L0:{l0.get('reason')}",
                        created_by="system:conflict",
                    )
                    actions.append("linked_edge")
                except Exception as exc:
                    notes.append(f"link_failed:{exc}")
            continue

        if l0["decision"] == "keep_existing":
            # Protect hard constraint — do not let soft overwrite
            blocked = True
            conflicts.append(conflict)
            store.log_conflict_sync(
                summary=(
                    f"Blocked write that contradicts hard constraint "
                    f"{row.get('id')}: {(incoming_content or '')[:120]}"
                ),
                level="L0",
                status="blocked",
                payload={
                    "existing": conflict,
                    "incoming_kind": incoming_kind,
                    "incoming_content": (incoming_content or "")[:400],
                    "l0": l0,
                },
            )
            actions.append("blocked_hard_constraint")
            notes.append("hard_constraint_protected")
            continue

        # escalate → L1
        topic = _core_topic(incoming_content)
        anchors = store.list_anchors_sync(scope=topic, limit=10)
        l1 = arbitrate_l1(anchors, topic=topic)
        conflict["l1"] = l1
        conflicts.append(conflict)

        if l1["decision"] == "follow_reference":
            anchor = l1.get("anchor") or {}
            notes.append(f"l1_follow:{anchor.get('reference_type')}")
            # Mark existing conflicted if resolution prefers incoming
            res = str(anchor.get("resolution") or "").lower()
            if auto_link and incoming_id and row.get("id"):
                try:
                    store.link_sync(
                        from_type=NODE_MEMORY,
                        from_id=str(incoming_id),
                        to_type=NODE_MEMORY,
                        to_id=str(row["id"]),
                        edge_type=EDGE_CONTRADICTS,
                        reason=f"L1:{anchor.get('id')}",
                        created_by="system:conflict",
                        meta={"anchor_id": anchor.get("id"), "resolution": res},
                    )
                    actions.append("linked_contradicts_l1")
                except Exception as exc:
                    notes.append(f"link_failed:{exc}")
            continue

        # L2: no reference → log review_required, mark conflicted edge
        store.log_conflict_sync(
            summary=(
                f"review_required: contradict {row.get('id')} vs new "
                f"{incoming_kind}: {(incoming_content or '')[:120]}"
            ),
            level="L2",
            status="review_required",
            payload={
                "existing": conflict,
                "incoming_kind": incoming_kind,
                "incoming_content": (incoming_content or "")[:400],
                "l0": l0,
                "l1": l1,
            },
        )
        actions.append("logged_review_required")
        notes.append("review_required")
        if auto_link and incoming_id and row.get("id"):
            try:
                store.link_sync(
                    from_type=NODE_MEMORY,
                    from_id=str(incoming_id),
                    to_type=NODE_MEMORY,
                    to_id=str(row["id"]),
                    edge_type=EDGE_CONTRADICTS,
                    reason="L2:review_required",
                    created_by="system:conflict",
                    status=REF_STATUS_ACTIVE,
                )
                # mark existing memory conflicted (soft signal)
                _mark_memory_conflicted_sync(str(row["id"]))
                actions.append("marked_conflicted")
            except Exception as exc:
                notes.append(f"link_failed:{exc}")

    return {
        "ok": not blocked,
        "blocked": blocked,
        "conflicts": conflicts,
        "actions": actions,
        "notes": notes,
    }


def _mark_memory_conflicted_sync(memory_id: str) -> None:
    from app.storage.schema import memories as memories_t

    with db_connect() as conn:
        conn.execute(
            update(memories_t)
            .where(memories_t.c.id == memory_id)
            .values(status="conflicted")
        )


def attach_kb_ref_for_memory(
    *,
    memory_id: str,
    kb_id: str,
    edge_type: str = EDGE_REFERENCES,
    reason: str | None = None,
    created_by: str | None = "system:remember",
) -> dict[str, Any]:
    return get_ref_store().link_sync(
        from_type=NODE_MEMORY,
        from_id=memory_id,
        to_type=NODE_KB,
        to_id=kb_id,
        edge_type=edge_type,
        reason=reason or "memory→kb",
        created_by=created_by,
    )


def attach_controls_edge(
    *,
    memory_id: str,
    target_type: str,
    target_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    return get_ref_store().link_sync(
        from_type=NODE_MEMORY,
        from_id=memory_id,
        to_type=target_type,
        to_id=target_id,
        edge_type=EDGE_CONTROLS,
        reason=reason or "control plane",
        created_by="system:control",
    )


def parse_ref_tags(tags: list[str] | None) -> list[dict[str, str]]:
    """Parse tags like kb_ref=ID, controls=kb:ID, ref=skill:name."""
    out: list[dict[str, str]] = []
    for t in tags or []:
        s = str(t or "").strip()
        low = s.lower()
        if low.startswith("kb_ref="):
            out.append(
                {
                    "to_type": NODE_KB,
                    "to_id": s.split("=", 1)[1].strip(),
                    "edge_type": EDGE_REFERENCES,
                }
            )
        elif low.startswith("controls="):
            rest = s.split("=", 1)[1].strip()
            if ":" in rest:
                typ, oid = rest.split(":", 1)
            else:
                typ, oid = NODE_KB, rest
            out.append(
                {
                    "to_type": typ.strip(),
                    "to_id": oid.strip(),
                    "edge_type": EDGE_CONTROLS,
                }
            )
        elif low.startswith("knowledge_ref=") or low.startswith("ref="):
            rest = s.split("=", 1)[1].strip()
            if ":" in rest:
                typ, oid = rest.split(":", 1)
            else:
                typ, oid = NODE_KB, rest
            out.append(
                {
                    "to_type": typ.strip(),
                    "to_id": oid.strip(),
                    "edge_type": EDGE_REFERENCES,
                }
            )
    return [x for x in out if x.get("to_id")]


def run_refs_cleanup_sync() -> dict[str, int]:
    """Hourly: dormant → expire; expire by valid_to; drop orphan edges."""
    now = _now()
    now_iso = now.isoformat()
    dormant_cut = (now - timedelta(days=DORMANT_AFTER_DAYS)).isoformat()
    expire_cut = (now - timedelta(days=EXPIRE_AFTER_DAYS)).isoformat()
    counts = {
        "refs_expired_ttl": 0,
        "refs_dormant": 0,
        "refs_expired_idle": 0,
        "refs_orphan_removed": 0,
        "anchors_expired": 0,
    }

    with db_connect() as conn:
        # TTL expire
        r1 = conn.execute(
            text(
                "UPDATE eva_knowledge_refs SET status = 'expired', updated_at = :now "
                "WHERE status IN ('active', 'dormant') "
                "AND valid_to IS NOT NULL AND TRIM(valid_to) != '' "
                "AND valid_to <= :now"
            ),
            {"now": now_iso},
        )
        counts["refs_expired_ttl"] = int(r1.rowcount or 0)

        # active → dormant if idle
        r2 = conn.execute(
            text(
                "UPDATE eva_knowledge_refs SET status = 'dormant', updated_at = :now "
                "WHERE status = 'active' AND ("
                "  (last_used_at IS NOT NULL AND last_used_at <= :cut) OR "
                "  ((last_used_at IS NULL OR TRIM(last_used_at) = '') AND created_at <= :cut)"
                ")"
            ),
            {"now": now_iso, "cut": dormant_cut},
        )
        counts["refs_dormant"] = int(r2.rowcount or 0)

        # dormant → expired if very idle
        r3 = conn.execute(
            text(
                "UPDATE eva_knowledge_refs SET status = 'expired', updated_at = :now "
                "WHERE status = 'dormant' AND ("
                "  (last_used_at IS NOT NULL AND last_used_at <= :cut) OR "
                "  ((last_used_at IS NULL OR TRIM(last_used_at) = '') AND created_at <= :cut)"
                ")"
            ),
            {"now": now_iso, "cut": expire_cut},
        )
        counts["refs_expired_idle"] = int(r3.rowcount or 0)

        # expire anchors by valid_to
        r4 = conn.execute(
            text(
                "UPDATE eva_reference_anchors SET status = 'expired', updated_at = :now "
                "WHERE status = 'active' AND valid_to IS NOT NULL AND TRIM(valid_to) != '' "
                "AND valid_to <= :now"
            ),
            {"now": now_iso},
        )
        counts["anchors_expired"] = int(r4.rowcount or 0)

        # Orphan cleanup: edges pointing at missing memory/kb (skills kept)
        mem_ids = {
            str(r[0])
            for r in conn.execute(text("SELECT id FROM eva_memories")).all()
        }
        kb_ids = {
            str(r[0])
            for r in conn.execute(text("SELECT id FROM eva_kb_pages")).all()
        }
        edges = conn.execute(
            select(knowledge_refs_t).where(
                knowledge_refs_t.c.status != REF_STATUS_EXPIRED
            )
        ).all()
        orphan_ids: list[str] = []
        for e in edges:
            orphan = False
            if e.from_type == NODE_MEMORY and e.from_id not in mem_ids:
                orphan = True
            if e.to_type == NODE_MEMORY and e.to_id not in mem_ids:
                orphan = True
            if e.from_type == NODE_KB and e.from_id not in kb_ids:
                orphan = True
            if e.to_type == NODE_KB and e.to_id not in kb_ids:
                orphan = True
            if orphan:
                orphan_ids.append(e.id)
        for oid in orphan_ids:
            conn.execute(
                update(knowledge_refs_t)
                .where(knowledge_refs_t.c.id == oid)
                .values(status=REF_STATUS_EXPIRED, updated_at=now_iso)
            )
        counts["refs_orphan_removed"] = len(orphan_ids)

    total = sum(counts.values())
    if total:
        logger.info("Refs cleanup: %s", counts)
    else:
        logger.debug("Refs cleanup: nothing to do")
    return counts


async def run_refs_cleanup() -> dict[str, int]:
    return await run_db(run_refs_cleanup_sync)


def migrate_refs_schema(conn) -> dict[str, Any]:
    """Ensure Phase-3 tables exist (create_all usually enough). Idempotent."""
    # Tables are in metadata; create_all handles them. This is a no-op hook
    # that verifies presence for logging.
    present: dict[str, bool] = {}
    for table in (
        "eva_knowledge_refs",
        "eva_reference_anchors",
        "eva_conflict_logs",
    ):
        try:
            dialect = conn.engine.dialect.name
            if dialect == "sqlite":
                row = conn.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=:t"
                    ),
                    {"t": table},
                ).first()
                present[table] = bool(row)
            else:
                conn.execute(text(f"SELECT 1 FROM {table} WHERE 1=0"))
                present[table] = True
        except Exception:
            present[table] = False
    missing = [t for t, ok in present.items() if not ok]
    if missing:
        logger.warning("Phase3 tables missing after create_all: %s", missing)
    return {"present": present, "ok": not missing}
