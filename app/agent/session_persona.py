"""Per-session persona: inherit the public agent or use an independent snapshot.

Runtime knobs (tool rounds, history caps, evolution thresholds) and
system/tool/safety rules stay on the public agent and are never part of a
session role snapshot.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.agent.persona import (
    compact_agent_config,
    migrate_legacy_system_prompt,
    persona_public_view,
)

# Identity + roleplay only. Excludes max_tool_rounds / evolution_* / etc.
SESSION_PERSONA_KEYS = (
    "name",
    "avatar",
    "role",
    "language",
    "language_style",
    "background",
    "roleplay_enabled",
    "roleplay_intensity",
    "roleplay_background",
    "relationship",
    "personality",
    "speech_patterns",
    "example_dialogue",
    "ooc_rules",
    "persona_options",
)

PERSONA_TEXT_MAX = 8000
PERSONA_MODES = ("inherit", "override")

ROLE_CHANGE_HINT = (
    "更换本对话人设后，本会话已有的历史消息和演化要点仍可能影响回复；"
    "不会自动删除历史。若要干净地开始新角色，建议开一个新对话。"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip(v: Any) -> str:
    return str(v or "").strip()


def snapshot_persona_fields(agent_cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Compact identity/roleplay fields only, with length caps."""
    cfg = compact_agent_config(migrate_legacy_system_prompt(dict(agent_cfg or {})))
    out: dict[str, Any] = {}
    for key in SESSION_PERSONA_KEYS:
        if key not in cfg:
            continue
        val = cfg[key]
        if isinstance(val, str) and key != "avatar":
            out[key] = val[:PERSONA_TEXT_MAX]
        else:
            out[key] = deepcopy(val)
    return out


def apply_persona_fields(base: dict[str, Any], snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Overlay session persona fields onto a public agent copy (runtime knobs kept)."""
    out = migrate_legacy_system_prompt(dict(base or {}))
    snap = snapshot_persona_fields(snapshot or {})
    for key in SESSION_PERSONA_KEYS:
        if key in snap:
            out[key] = snap[key]
    return compact_agent_config(out)


def _blank_snapshot(agent: dict[str, Any] | None) -> bool:
    if not isinstance(agent, dict) or not agent:
        return True
    for key in SESSION_PERSONA_KEYS:
        if key not in agent:
            continue
        val = agent[key]
        if key == "roleplay_enabled":
            continue
        if key == "roleplay_intensity":
            continue
        if isinstance(val, str):
            if val.strip():
                return False
            continue
        if isinstance(val, list) and any(str(x).strip() for x in val):
            return False
        if isinstance(val, dict) and any(
            (isinstance(v, list) and any(str(x).strip() for x in v))
            or (isinstance(v, str) and v.strip())
            for v in val.values()
        ):
            return False
        if val not in (None, "", [], {}, False):
            if key == "persona_options":
                continue
            if isinstance(val, bool):
                continue
            return False
    return True


def normalize_persona_meta(raw: Any) -> dict[str, Any]:
    """Normalize session.metadata.persona. Missing/blank → inherit."""
    if not isinstance(raw, dict):
        return {"mode": "inherit", "agent": {}, "updated_at": None, "previous_mode": None}
    mode = _strip(raw.get("mode")).lower()
    agent = raw.get("agent") if isinstance(raw.get("agent"), dict) else {}
    if mode not in PERSONA_MODES:
        # Legacy: a non-empty agent dict without mode is treated as override
        mode = "override" if not _blank_snapshot(agent) else "inherit"
    if mode == "override" and _blank_snapshot(agent):
        mode = "inherit"
        agent = {}
    if mode == "inherit":
        agent = {}
    else:
        agent = snapshot_persona_fields(agent)
    prev = _strip(raw.get("previous_mode")).lower() or None
    if prev not in PERSONA_MODES:
        prev = None
    return {
        "mode": mode,
        "agent": agent,
        "updated_at": raw.get("updated_at"),
        "previous_mode": prev,
        "switched_at": raw.get("switched_at"),
    }


def is_inherit(meta: dict[str, Any] | None) -> bool:
    return normalize_persona_meta(meta).get("mode") != "override"


def persona_meta_from_session(session: dict[str, Any] | None) -> dict[str, Any]:
    md = (session or {}).get("metadata") if isinstance(session, dict) else {}
    if not isinstance(md, dict):
        md = {}
    return normalize_persona_meta(md.get("persona"))


def resolve_session_agent(
    public_agent: dict[str, Any] | None,
    session: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Freeze-ready resolve: effective agent + public view metadata.

    Inherit (default, missing, empty, cleared) uses the latest public persona.
    Override uses the session snapshot for identity/roleplay only.
    """
    public = compact_agent_config(migrate_legacy_system_prompt(dict(public_agent or {})))
    meta = persona_meta_from_session(session)
    if meta["mode"] == "override":
        effective = apply_persona_fields(public, meta.get("agent"))
        source = "session"
        source_label = "本对话独立人设"
    else:
        effective = deepcopy(public)
        source = "public"
        source_label = "跟随公共人设"
    info = {
        "mode": meta["mode"],
        "source": source,
        "source_label": source_label,
        "updated_at": meta.get("updated_at"),
        "previous_mode": meta.get("previous_mode"),
        "switched_at": meta.get("switched_at"),
        "role_change_hint": ROLE_CHANGE_HINT,
        "show_role_change_hint": bool(
            (meta.get("switched_at") or meta.get("previous_mode"))
            and ((session or {}).get("messages") or (session or {}).get("message_count"))
        ),
    }
    return effective, info


def build_persona_record(
    *,
    mode: str,
    agent_fields: dict[str, Any] | None,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prev = normalize_persona_meta(previous)
    mode_n = _strip(mode).lower()
    if mode_n not in PERSONA_MODES:
        raise ValueError("mode 只能是 inherit 或 override")
    rec = {
        "mode": mode_n,
        "agent": {},
        "updated_at": _now_iso(),
        "previous_mode": prev.get("mode"),
        "switched_at": prev.get("switched_at"),
    }
    if mode_n == "override":
        snap = snapshot_persona_fields(agent_fields or {})
        if _blank_snapshot(snap):
            rec["mode"] = "inherit"
            rec["agent"] = {}
        else:
            rec["agent"] = snap
    if rec["mode"] != prev.get("mode"):
        rec["switched_at"] = rec["updated_at"]
    return rec


def persona_api_view(
    *,
    session: dict[str, Any] | None,
    public_agent: dict[str, Any] | None,
) -> dict[str, Any]:
    from app.agent.persona import build_persona_prompt

    effective, info = resolve_session_agent(public_agent, session)
    meta = persona_meta_from_session(session)
    form_agent = meta["agent"] if meta["mode"] == "override" else public_agent
    return {
        "ok": True,
        "session_id": (session or {}).get("session_id") or "",
        "session_title": (session or {}).get("title") or "",
        "mode": info["mode"],
        "source": info["source"],
        "source_label": info["source_label"],
        "updated_at": info.get("updated_at"),
        "agent": persona_public_view(form_agent),
        "public_agent": persona_public_view(public_agent),
        "effective_preview": build_persona_prompt(effective),
        "role_change_hint": ROLE_CHANGE_HINT,
        "show_role_change_hint": info.get("show_role_change_hint"),
    }
