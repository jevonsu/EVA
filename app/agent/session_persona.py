"""Per-session persona: inherit the public agent or use an independent identity snapshot.

Independent (override) persona is assistant identity and communication
preference only — not roleplay. Runtime knobs (tool rounds, history caps,
evolution thresholds) and system/tool/safety rules stay on the public agent.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.agent.identity_prefs import (
    IDENTITY_COMM_KEYS,
    IDENTITY_OPTIONAL_KEYS,
    LANGUAGE_INHERIT_PUBLIC,
    PERSONA_TEXT_MAX,
    ROLEPLAY_FIELD_KEYS,
    has_legacy_roleplay_payload,
    identity_field_choices,
    normalize_answer_detail,
    normalize_identity_language,
    normalize_speech_style,
    normalize_terminology,
    validate_identity_payload,
)
from app.agent.persona import (
    compact_agent_config,
    migrate_legacy_system_prompt,
    persona_public_view,
)

# Historical snapshots may still contain roleplay keys; new writes do not.
SESSION_PERSONA_KEYS = IDENTITY_COMM_KEYS + IDENTITY_OPTIONAL_KEYS + ROLEPLAY_FIELD_KEYS + (
    "role",
    "language_style",
    "persona_options",
)

PERSONA_MODES = ("inherit", "override")

ROLE_CHANGE_HINT = (
    "更换本对话人设后，本会话已有的历史消息和演化要点仍可能影响回复；"
    "不会自动删除历史。若要干净地开始新角色，建议开一个新对话。"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip(v: Any) -> str:
    return str(v or "").strip()


def _is_follow_public(val: Any) -> bool:
    return normalize_identity_language(val, allow_inherit=True) == LANGUAGE_INHERIT_PUBLIC or _strip(val) == LANGUAGE_INHERIT_PUBLIC


def snapshot_identity_fields(agent_cfg: dict[str, Any] | None, *, allow_inherit: bool = True) -> dict[str, Any]:
    """Persist only identity / communication fields for an independent persona."""
    src = dict(agent_cfg or {})
    try:
        validated = validate_identity_payload(src, allow_inherit=allow_inherit)
    except ValueError:
        # Lenient read path: normalize without rejecting legacy/unknown language
        validated = {}
        if "name" in src:
            validated["name"] = _strip(src.get("name"))[:80]
        if "background" in src:
            validated["background"] = _strip(src.get("background"))[:PERSONA_TEXT_MAX]
        if "language" in src:
            validated["language"] = normalize_identity_language(src.get("language"), allow_inherit=allow_inherit)
        if "speech_style" in src:
            validated["speech_style"] = normalize_speech_style(src.get("speech_style"), allow_inherit=allow_inherit)
        if "speech_style_custom" in src:
            validated["speech_style_custom"] = _strip(src.get("speech_style_custom"))[:PERSONA_TEXT_MAX]
        if "answer_detail" in src:
            validated["answer_detail"] = normalize_answer_detail(src.get("answer_detail"), allow_inherit=allow_inherit)
        if "terminology" in src:
            validated["terminology"] = normalize_terminology(src.get("terminology"), allow_inherit=allow_inherit)
    out: dict[str, Any] = {}
    for key in IDENTITY_COMM_KEYS:
        if key in validated:
            out[key] = validated[key]
        elif key in src:
            # include empty strings so a cleared background is a snapshot
            val = src[key]
            if isinstance(val, str):
                out[key] = val.strip()[:PERSONA_TEXT_MAX] if key != "name" else val.strip()[:80]
            else:
                out[key] = val
    avatar = src.get("avatar")
    if avatar:
        out["avatar"] = avatar
    return out


def snapshot_persona_fields(agent_cfg: dict[str, Any] | None) -> dict[str, Any]:
    """New snapshots are identity-only. Kept name for existing callers."""
    return snapshot_identity_fields(agent_cfg, allow_inherit=True)


def _strip_roleplay(agent: dict[str, Any]) -> dict[str, Any]:
    out = dict(agent or {})
    out["roleplay_enabled"] = False
    # Keep stored RP text on the public object so inherit/other sessions
    # are unaffected; injection is gated by roleplay_enabled.
    return out


def apply_persona_fields(base: dict[str, Any], snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Overlay independent identity onto a public agent copy; force roleplay off."""
    out = _strip_roleplay(migrate_legacy_system_prompt(dict(base or {})))
    snap = snapshot_identity_fields(snapshot or {}, allow_inherit=True)
    public_lang = normalize_identity_language(out.get("language"), allow_inherit=False)
    public_style = normalize_speech_style(out.get("speech_style"), allow_inherit=False)
    public_detail = normalize_answer_detail(out.get("answer_detail"), allow_inherit=False)
    public_term = normalize_terminology(out.get("terminology"), allow_inherit=False)

    if "name" in snap:
        name = _strip(snap.get("name"))
        if name:
            out["name"] = name
        # empty name → keep public name
    if "background" in snap:
        out["background"] = snap.get("background") or ""

    lang = snap.get("language") if "language" in snap else LANGUAGE_INHERIT_PUBLIC
    if _is_follow_public(lang) or not _strip(lang):
        out["language"] = public_lang or out.get("language") or ""
    else:
        out["language"] = normalize_identity_language(lang, allow_inherit=False) or _strip(lang)

    style = snap.get("speech_style") if "speech_style" in snap else LANGUAGE_INHERIT_PUBLIC
    if _is_follow_public(style) or not _strip(style):
        out["speech_style"] = public_style
        if "speech_style_custom" not in snap:
            pass  # keep public custom
        else:
            out["speech_style_custom"] = _strip(snap.get("speech_style_custom"))
    else:
        out["speech_style"] = normalize_speech_style(style, allow_inherit=False)
        if "speech_style_custom" in snap:
            out["speech_style_custom"] = _strip(snap.get("speech_style_custom"))
        elif out.get("speech_style") != "custom":
            # don't leak public custom notes into a different chosen style unless provided
            if out.get("speech_style") != public_style:
                out["speech_style_custom"] = _strip(snap.get("speech_style_custom"))

    detail = snap.get("answer_detail") if "answer_detail" in snap else LANGUAGE_INHERIT_PUBLIC
    if _is_follow_public(detail) or not _strip(detail):
        out["answer_detail"] = public_detail
    else:
        out["answer_detail"] = normalize_answer_detail(detail, allow_inherit=False)

    term = snap.get("terminology") if "terminology" in snap else LANGUAGE_INHERIT_PUBLIC
    if _is_follow_public(term) or not _strip(term):
        out["terminology"] = public_term
    else:
        out["terminology"] = normalize_terminology(term, allow_inherit=False)

    if "avatar" in snap and snap.get("avatar"):
        out["avatar"] = snap.get("avatar")

    out["roleplay_enabled"] = False
    return compact_agent_config(out)


def _has_identity_value(agent: dict[str, Any] | None) -> bool:
    if not isinstance(agent, dict) or not agent:
        return False
    if _strip(agent.get("name")) or _strip(agent.get("background")) or _strip(agent.get("speech_style_custom")):
        return True
    for key, norm in (
        ("language", lambda v: normalize_identity_language(v, allow_inherit=True)),
        ("speech_style", lambda v: normalize_speech_style(v, allow_inherit=True)),
        ("answer_detail", lambda v: normalize_answer_detail(v, allow_inherit=True)),
        ("terminology", lambda v: normalize_terminology(v, allow_inherit=True)),
    ):
        if key not in agent:
            continue
        val = norm(agent.get(key))
        if val:
            return True
    return False


def _blank_snapshot(agent: dict[str, Any] | None) -> bool:
    """True when there is no identity content and no follow-public sentinels and no legacy RP."""
    if _has_identity_value(agent):
        return False
    if has_legacy_roleplay_payload(agent):
        return False
    return True


def normalize_persona_meta(raw: Any) -> dict[str, Any]:
    """Normalize session.metadata.persona. Missing/blank → inherit.

    Explicit override with only legacy roleplay fields stays override so the
    session does not silently start inheriting public roleplay; those RP
    fields are not executed. Follow-public sentinels also keep override.
    """
    if not isinstance(raw, dict):
        return {"mode": "inherit", "agent": {}, "updated_at": None, "previous_mode": None}
    mode = _strip(raw.get("mode")).lower()
    agent = raw.get("agent") if isinstance(raw.get("agent"), dict) else {}
    if mode not in PERSONA_MODES:
        mode = "override" if not _blank_snapshot(agent) else "inherit"
    if mode == "override" and _blank_snapshot(agent):
        mode = "inherit"
        agent = {}
    if mode == "inherit":
        agent = {}
    else:
        # Identity view for the form; do not drop stored RP from disk here.
        agent = snapshot_identity_fields(agent, allow_inherit=True)
    prev = _strip(raw.get("previous_mode")).lower() or None
    if prev not in PERSONA_MODES:
        prev = None
    return {
        "mode": mode,
        "agent": agent,
        "updated_at": raw.get("updated_at"),
        "previous_mode": prev,
        "switched_at": raw.get("switched_at"),
        "legacy_roleplay_ignored": bool(
            mode == "override" and has_legacy_roleplay_payload(raw.get("agent") if isinstance(raw.get("agent"), dict) else {})
        ),
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

    Inherit (default, missing, empty, cleared) uses the latest public persona,
    including public roleplay if enabled. Override uses an identity snapshot
    only and never executes session or public roleplay fields.
    Does not mutate the public agent object.
    """
    public = compact_agent_config(migrate_legacy_system_prompt(dict(public_agent or {})))
    meta = persona_meta_from_session(session)
    stored_agent = {}
    md = (session or {}).get("metadata") if isinstance(session, dict) else {}
    if isinstance(md, dict) and isinstance((md.get("persona") or {}).get("agent"), dict):
        stored_agent = md["persona"]["agent"]
    if meta["mode"] == "override":
        effective = apply_persona_fields(public, stored_agent or meta.get("agent"))
        source = "session"
        source_label = "本对话独立人设（身份与沟通偏好，不含角色扮演）"
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
        "legacy_roleplay_ignored": bool(meta.get("legacy_roleplay_ignored")),
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
    strict: bool = False,
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
        if strict:
            snap = validate_identity_payload(agent_fields or {}, allow_inherit=True)
            # validate_identity_payload only returns provided keys; keep empties
            snap = snapshot_identity_fields({**(agent_fields or {}), **snap}, allow_inherit=True)
        else:
            snap = snapshot_identity_fields(agent_fields or {}, allow_inherit=True)
        if _blank_snapshot(snap) and not has_legacy_roleplay_payload(agent_fields):
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
    form_agent = meta["agent"] if meta["mode"] == "override" else {}
    public_view = persona_public_view(public_agent)
    return {
        "ok": True,
        "session_id": (session or {}).get("session_id") or "",
        "session_title": (session or {}).get("title") or "",
        "mode": info["mode"],
        "source": info["source"],
        "source_label": info["source_label"],
        "updated_at": info.get("updated_at"),
        "agent": form_agent,
        "public_agent": public_view,
        "effective_preview": build_persona_prompt(effective),
        "role_change_hint": ROLE_CHANGE_HINT,
        "show_role_change_hint": info.get("show_role_change_hint"),
        "legacy_roleplay_ignored": info.get("legacy_roleplay_ignored"),
        "identity_choices": identity_field_choices(for_session=True),
        "mode_copy": identity_field_choices(for_session=True).get("copy"),
    }
