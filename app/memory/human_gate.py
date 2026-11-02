"""Human gate for memory / knowledge certification.

Agent/tools may create staging, draft, or green-leaf (active + TTL).
Gold/certified (permanent active facts) requires human approve.
UI blank-slate creates land in staging when HUMAN_EDIT_CERTIFIED_ONLY=true.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.memory.control_plane import CONTROL_KINDS, is_control_kind, normalize_kind
from app.storage.lifecycle import (
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_CONFLICTED,
    STATUS_STAGING,
    normalize_status,
)

logger = logging.getLogger("app.memory.human_gate")

# Explicit gold aliases callers might pass
CERTIFIED_ALIASES = frozenset(
    {"gold", "certified", "金叶", "certified_active", "canonical"}
)

# Statuses that count as "pending human review" in the queue
QUEUE_MEMORY_STATUSES = frozenset(
    {STATUS_STAGING, STATUS_CONFLICTED, "review_required"}
)
QUEUE_KB_STATUSES = frozenset({STATUS_STAGING, "review_required"})
QUEUE_CONFLICT_STATUSES = frozenset({"review_required", "blocked", "logged"})

HARD_CONSTRAINT_KINDS = frozenset({"constraint", "rule"})

ACTOR_AGENT = "agent"
ACTOR_UI = "ui"
ACTOR_REVIEW = "review"
ACTOR_SYSTEM = "system"


def human_edit_certified_only() -> bool:
    try:
        from app.config import get_settings

        return bool(getattr(get_settings(), "human_edit_certified_only", True))
    except Exception:
        return True


def is_certified_request(status: str | None) -> bool:
    s = str(status or "").strip().lower()
    return s in CERTIFIED_ALIASES


def is_hard_constraint_kind(kind: str | None) -> bool:
    return normalize_kind(kind) in HARD_CONSTRAINT_KINDS


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def audit_path() -> Path:
    try:
        from app.config import get_settings

        root = get_settings().data_dir
    except Exception:
        root = Path("data")
    p = Path(root) / "audit"
    p.mkdir(parents=True, exist_ok=True)
    return p / "human_gate.jsonl"


def append_audit(
    action: str,
    *,
    actor: str = ACTOR_UI,
    item_type: str = "",
    item_id: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    row = {
        "at": _now_iso(),
        "action": action,
        "actor": actor,
        "item_type": item_type,
        "item_id": item_id,
        "detail": detail or {},
    }
    try:
        path = audit_path()
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        logger.exception("audit append failed: %s", action)


def gate_agent_memory_write(
    *,
    kind: str | None,
    status: str | None,
    valid_to: str | None = None,
    ttl_days: float | int | None = None,
    explicit_status: bool = False,
) -> dict[str, Any]:
    """Demote illegal gold/certified invents for Agent writes.

    Allowed without human:
      - staging / draft kinds
      - control kinds (preference/constraint/…) as active
      - green-leaf: active + valid_to/ttl (temporary)
    Not allowed:
      - status gold/certified
      - permanent active fact/note (no TTL) → force staging
    """
    notes: list[str] = []
    k = normalize_kind(kind)
    st_raw = str(status or "").strip().lower()
    has_ttl = bool(
        (valid_to and str(valid_to).strip())
        or (ttl_days is not None and float(ttl_days or 0) > 0)
    )

    if is_certified_request(st_raw):
        notes.append("agent_demote_gold_to_staging")
        return {
            "status": STATUS_STAGING,
            "kind": k,
            "notes": notes,
            "demoted": True,
            "reason": "agent_cannot_invent_gold",
        }

    st = normalize_status(st_raw) if st_raw else ""

    # Control plane standing prefs/constraints still OK
    if is_control_kind(k) or k in CONTROL_KINDS:
        if not st or st == STATUS_ACTIVE:
            return {
                "status": STATUS_ACTIVE,
                "kind": k,
                "notes": notes,
                "demoted": False,
                "reason": "control_ok",
            }

    # Explicit staging / review
    if st in (STATUS_STAGING, "review_required", STATUS_CONFLICTED):
        return {
            "status": st if st != STATUS_CONFLICTED else STATUS_STAGING,
            "kind": k,
            "notes": notes,
            "demoted": False,
            "reason": "staging_ok",
        }

    # Green-leaf: active with TTL
    if (st == STATUS_ACTIVE or not st) and has_ttl:
        notes.append("green_leaf_ttl")
        return {
            "status": STATUS_ACTIVE,
            "kind": k,
            "notes": notes,
            "demoted": False,
            "reason": "green_leaf",
        }

    # Permanent active fact/note without path → staging
    if st == STATUS_ACTIVE or (not st and not is_control_kind(k)):
        if not is_control_kind(k):
            notes.append("agent_force_staging_no_ttl")
            return {
                "status": STATUS_STAGING,
                "kind": k,
                "notes": notes,
                "demoted": True,
                "reason": "no_gold_without_approve",
            }

    return {
        "status": st or STATUS_STAGING,
        "kind": k,
        "notes": notes,
        "demoted": False,
        "reason": "default",
    }


def gate_ui_create(
    *,
    kind: str | None = None,
    status: str | None = None,
    collection: str | None = None,
) -> dict[str, Any]:
    """UI blank-slate create: force staging when certified-only flag is on."""
    if not human_edit_certified_only():
        st = normalize_status(status) if status else STATUS_ACTIVE
        return {"status": st, "forced_staging": False, "notes": []}

    notes = ["ui_create_forced_staging"]
    coll = str(collection or "").strip().lower()
    if coll and coll not in ("staging", "temp", "draft", "candidate", "daily"):
        notes.append("ui_collection_kept_but_status_staging")
    return {
        "status": STATUS_STAGING,
        "forced_staging": True,
        "notes": notes,
        "hint": "新建进入暂存；请在「评审」中批准后才会成为正式条目。",
    }


def gate_status_change(
    *,
    old_status: str | None,
    new_status: str | None,
    actor: str,
    kind: str | None = None,
) -> dict[str, Any]:
    """Block staging/conflicted → active/gold unless actor=review."""
    old_s = normalize_status(old_status)
    new_raw = str(new_status or "").strip().lower()
    if is_certified_request(new_raw):
        new_s = STATUS_ACTIVE
        certified = True
    else:
        new_s = normalize_status(new_raw) if new_raw else old_s
        certified = False

    if actor == ACTOR_REVIEW:
        return {"ok": True, "status": new_s, "blocked": False}

    # Downgrade always OK
    if new_s in (
        STATUS_STAGING,
        STATUS_ARCHIVED,
        STATUS_CONFLICTED,
        "review_required",
        "expired",
        "superseded",
    ):
        return {"ok": True, "status": new_s, "blocked": False}

    # Promote to active/gold
    if new_s == STATUS_ACTIVE and old_s in (
        STATUS_STAGING,
        STATUS_CONFLICTED,
        "review_required",
    ):
        if human_edit_certified_only() and actor != ACTOR_REVIEW:
            return {
                "ok": False,
                "blocked": True,
                "status": old_s,
                "error": "promote_requires_review",
                "message": "暂存/待审 → 正式 只能通过评审批准，不能直接改 status。",
            }

    if certified and actor != ACTOR_REVIEW and human_edit_certified_only():
        return {
            "ok": False,
            "blocked": True,
            "status": old_s,
            "error": "gold_requires_review",
            "message": "金叶/认证状态只能经评审批准写入。",
        }

    # Hard constraint content edits are allowed for human UI but audited by caller
    _ = kind
    return {"ok": True, "status": new_s, "blocked": False}


def gate_kb_agent_create(
    *,
    status: str | None,
    collection: str | None = None,
    valid_to: str | None = None,
    ttl_days: float | int | None = None,
) -> dict[str, Any]:
    """Agent kb create: staging/draft/green-leaf OK; permanent active → staging."""
    st_raw = str(status or "").strip().lower()
    coll = str(collection or "").strip().lower()
    has_ttl = bool(
        (valid_to and str(valid_to).strip())
        or (ttl_days is not None and float(ttl_days or 0) > 0)
    )
    notes: list[str] = []

    if is_certified_request(st_raw) or coll in ("gold", "certified", "canonical"):
        notes.append("agent_kb_demote_gold")
        return {"status": STATUS_STAGING, "notes": notes, "demoted": True}

    st = normalize_status(st_raw) if st_raw else STATUS_ACTIVE
    if coll in ("staging", "temp", "draft", "candidate"):
        return {"status": STATUS_STAGING, "notes": notes, "demoted": False}
    if st == STATUS_STAGING:
        return {"status": STATUS_STAGING, "notes": notes, "demoted": False}
    if st == STATUS_ACTIVE and has_ttl:
        notes.append("kb_green_leaf")
        return {"status": STATUS_ACTIVE, "notes": notes, "demoted": False}
    if st == STATUS_ACTIVE and not has_ttl:
        notes.append("agent_kb_force_staging")
        return {"status": STATUS_STAGING, "notes": notes, "demoted": True}
    return {"status": st, "notes": notes, "demoted": False}
