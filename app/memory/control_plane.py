"""Memory / knowledge control plane (Phase 2).

Control plane = short standing prefs / constraints / goals / strategies.
Staging = evidence / inferred / candidate notes with TTL (default 7d).
Data plane = knowledge base pages (long factual bodies).
"""

from __future__ import annotations

import re
from typing import Any

# Standing / constitution-like kinds (short control metadata)
CONTROL_KINDS = frozenset(
    {
        "preference",
        "constraint",
        "goal",
        "strategy",
        "habit",
        "rule",
    }
)

# Evidence / provisional — land in status=staging with TTL
STAGING_KINDS = frozenset(
    {
        "staging",
        "temp",
        "draft",
        "evidence",
        "scratch",
        "inferred",
        "observation",
        "candidate",
        "hypothesis",
    }
)

# Aliases → canonical kind
_KIND_ALIASES = {
    "pref": "preference",
    "prefs": "preference",
    "prefer": "preference",
    "limit": "constraint",
    "constraints": "constraint",
    "forbid": "constraint",
    "ban": "constraint",
    "objective": "goal",
    "goals": "goal",
    "plan": "strategy",
    "policy": "strategy",
    "policies": "strategy",
    "rules": "rule",
    "always": "rule",
    "tmp": "temp",
    "temporary": "temp",
    "guess": "inferred",
    "infer": "inferred",
    "obs": "observation",
}

STANDING_TAG = "standing"
CONTROL_TAGS = frozenset({"standing", "pin", "always", "全局", "始终", "永久规则"})

# TTL defaults for staging (days); within the 3–14 day design band
STAGING_TTL_DEFAULT_DAYS = 7.0
STAGING_TTL_MIN_DAYS = 3.0
STAGING_TTL_MAX_DAYS = 14.0

CONTROL_CONFIDENCE = 0.9
STAGING_CONFIDENCE = 0.55
FACT_CONFIDENCE = 0.8

# Long bodies belong in kb; memory keeps a short pointer
LONG_BODY_CHARS = 200
POINTER_HEAD_CHARS = 120

_WS_RE = re.compile(r"\s+")


def normalize_kind(kind: str | None) -> str:
    k = (kind or "note").strip().lower() or "note"
    return _KIND_ALIASES.get(k, k)


def is_control_kind(kind: str | None) -> bool:
    return normalize_kind(kind) in CONTROL_KINDS


def is_staging_kind(kind: str | None) -> bool:
    return normalize_kind(kind) in STAGING_KINDS


def clamp_staging_ttl_days(days: float | int | None) -> float:
    if days is None:
        return STAGING_TTL_DEFAULT_DAYS
    try:
        d = float(days)
    except (TypeError, ValueError):
        return STAGING_TTL_DEFAULT_DAYS
    if d <= 0:
        return STAGING_TTL_DEFAULT_DAYS
    if d < STAGING_TTL_MIN_DAYS:
        return STAGING_TTL_MIN_DAYS
    if d > STAGING_TTL_MAX_DAYS:
        return STAGING_TTL_MAX_DAYS
    return d


def control_key(kind: str, content: str, tags: list[str] | None = None) -> str:
    """Stable key for supersede matching (same preference/constraint topic)."""
    k = normalize_kind(kind)
    tags = tags or []
    # Prefer an explicit key= / topic= tag
    for t in tags:
        s = str(t or "").strip()
        low = s.lower()
        if low.startswith("key=") or low.startswith("topic="):
            return f"{k}|{low.split('=', 1)[1].strip()}"
    text = (content or "").strip()
    first = text.split("\n", 1)[0].strip()
    first = _WS_RE.sub(" ", first).lower()
    # Drop common prefixes so rewrites still match
    for prefix in (
        "用户偏好：",
        "偏好：",
        "约束：",
        "规则：",
        "目标：",
        "策略：",
        "preference:",
        "constraint:",
        "rule:",
        "goal:",
        "strategy:",
    ):
        if first.startswith(prefix.lower()) or first.startswith(prefix):
            first = first[len(prefix) :].strip()
            break
    if len(first) > 80:
        first = first[:80]
    return f"{k}|{first}"


def short_summary(content: str, *, max_chars: int = POINTER_HEAD_CHARS) -> str:
    t = _WS_RE.sub(" ", (content or "").strip())
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1].rstrip() + "…"


def should_prefer_kb(kind: str | None, content: str) -> bool:
    """Long factual / evidence bodies → kb data plane; memory holds ref/summary."""
    k = normalize_kind(kind)
    if k in CONTROL_KINDS:
        # control stays in memory even if a bit long; inject truncates anyway
        return False
    text = (content or "").strip()
    if len(text) >= LONG_BODY_CHARS:
        return True
    if k in ("fact", "note", "evidence", "observation", "candidate") and text.count("\n") >= 4:
        return True
    return False


def classify_memory_write(
    *,
    kind: str | None = None,
    tags: list[str] | None = None,
    content: str = "",
    status: str | None = None,
    ttl_days: float | int | None = None,
    valid_to: str | None = None,
    confidence: float | None = None,
    explicit_status: bool = False,
) -> dict[str, Any]:
    """Decide plane, status, tags, TTL, confidence for a remember write.

    Returns dict with keys:
      kind, tags, status, ttl_days, confidence, plane, prefer_kb, notes
    """
    from app.storage.lifecycle import (
        STATUS_ACTIVE,
        STATUS_STAGING,
        normalize_status,
    )

    k = normalize_kind(kind)
    tag_list = [str(t).strip() for t in (tags or []) if str(t).strip()]
    tag_lower = {t.lower() for t in tag_list}
    notes: list[str] = []

    # Explicit status wins when caller set it
    st_in = (str(status).strip().lower() if status else "") or ""
    if explicit_status and st_in:
        st = normalize_status(st_in)
    elif st_in == STATUS_STAGING or is_staging_kind(k) or ("staging" in tag_lower):
        st = STATUS_STAGING
    elif is_control_kind(k) or (tag_lower & {t.lower() for t in CONTROL_TAGS}):
        st = STATUS_ACTIVE
    else:
        st = normalize_status(st_in) if st_in else STATUS_ACTIVE

    plane = "staging" if st == STATUS_STAGING or is_staging_kind(k) else (
        "control" if is_control_kind(k) or (tag_lower & {t.lower() for t in CONTROL_TAGS}) else "fact"
    )

    # Standing tags for control plane
    if plane == "control":
        if STANDING_TAG not in tag_lower and "pin" not in tag_lower and "always" not in tag_lower:
            tag_list.append(STANDING_TAG)
            tag_lower.add(STANDING_TAG)
            notes.append("auto_tag_standing")

    # TTL for staging
    out_ttl: float | None = None
    has_valid = bool(valid_to and str(valid_to).strip())
    if plane == "staging" or st == STATUS_STAGING:
        st = STATUS_STAGING
        if not has_valid:
            if ttl_days is not None and float(ttl_days or 0) > 0:
                out_ttl = clamp_staging_ttl_days(ttl_days)
            else:
                out_ttl = STAGING_TTL_DEFAULT_DAYS
                notes.append("default_staging_ttl_7d")
        elif ttl_days is not None and float(ttl_days or 0) > 0:
            out_ttl = clamp_staging_ttl_days(ttl_days)
    elif ttl_days is not None and float(ttl_days or 0) > 0:
        out_ttl = float(ttl_days)

    # Confidence defaults by plane
    if confidence is not None:
        conf = float(confidence)
    elif plane == "control":
        conf = CONTROL_CONFIDENCE
    elif plane == "staging":
        conf = STAGING_CONFIDENCE
    else:
        conf = FACT_CONFIDENCE

    prefer_kb = should_prefer_kb(k, content)
    if prefer_kb:
        notes.append("prefer_kb_for_long_body")

    return {
        "kind": k,
        "tags": tag_list,
        "status": st,
        "ttl_days": out_ttl,
        "confidence": conf,
        "plane": plane,
        "prefer_kb": prefer_kb,
        "notes": notes,
        "control_key": control_key(k, content, tag_list) if plane == "control" else None,
    }


def find_supersede_id(
    rows: list[dict[str, Any]],
    *,
    kind: str,
    content: str,
    tags: list[str] | None = None,
) -> str | None:
    """Find an active control memory with the same control_key to supersede."""
    from app.storage.lifecycle import STATUS_ACTIVE, is_visible_row

    key = control_key(kind, content, tags)
    if not key or key.endswith("|"):
        return None
    for row in rows:
        if not is_visible_row(row, include_archived=False):
            continue
        if str(row.get("status") or STATUS_ACTIVE) != STATUS_ACTIVE:
            continue
        if not is_control_kind(row.get("kind")):
            continue
        rk = control_key(
            str(row.get("kind") or ""),
            str(row.get("content") or ""),
            list(row.get("tags") or []),
        )
        if rk == key:
            rid = str(row.get("id") or "").strip()
            if rid:
                return rid
    return None
