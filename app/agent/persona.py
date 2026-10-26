"""User-editable persona vs system-fixed operational rules.

Editable expression:
  1. Identity + persona (one UI block):
     - always: name, language, background
     - opt-in roleplay (roleplay_enabled): relationship / personality /
       speech_patterns / example_dialogue / ooc_rules + intensity
     - runtime knobs: max_tool_rounds, max_history_messages, evolution_*
  2. 演化人格 — session evolution digest (read-only in 人设)

SOP / decision_tree / language_calibrator / hard_boundaries belong in the
knowledge base (retrieved on demand), not in the per-turn persona.

Legacy commercial-boundary fields are read once during migrate then dropped
from the stored agent object (see compact_agent_config).

Not editable (code-injected each turn — logic unchanged):
  MEMORY / MEDIA / TOOL ROUTING / INTENT / protection / path safety
"""

from __future__ import annotations

from typing import Any

# Fields persisted under config.agent (and accepted by the form / PATCH)
ACTIVE_AGENT_KEYS = (
    "name",
    "role",
    "language",
    "language_style",
    "background",
    # Roleplay block (only injected when roleplay_enabled)
    "roleplay_enabled",
    "roleplay_intensity",
    "relationship",
    "personality",
    "speech_patterns",
    "example_dialogue",
    "ooc_rules",
    "persona_options",
    "max_tool_rounds",
    "max_history_messages",
    # Session evolution (running summary / auto compress)
    "evolution_enabled",
    "evolution_trigger_messages",
    "evolution_keep_messages",
    "evolution_max_entries",
    "evolution_max_chars",
)

PERSONA_FIELDS = (
    "role",
    "language",
    "language_style",
    "background",
    "relationship",
    "personality",
    "speech_patterns",
    "example_dialogue",
    "ooc_rules",
)

# Primary free-text layers of the agent form (assistant identity extras)
LAYER_TEXT_FIELDS: tuple[str, ...] = ()

# Roleplay free-text fields (injected only when roleplay_enabled)
ROLEPLAY_TEXT_FIELDS = (
    "relationship",
    "personality",
    "speech_patterns",
    "example_dialogue",
    "ooc_rules",
)

ROLEPLAY_INTENSITIES = ("light", "medium", "deep")

# Identity multi-select dropdown UI (legacy; form uses free-text 角色背景)
CHIP_KEYS = (
    "role",
    "language_style",
)

# Boundary multi-select (chips) → *_sel lists
BOUNDARY_SEL_KEYS = (
    "principles_sel",
    "platforms_sel",
    "workflow_sel",
    "output_modes_sel",
    "notes_sel",
    "constraints_sel",
)

# Free-text capability-boundary fields (default_* kept for legacy)
TEXT_BOUNDARY_FIELDS = (
    "principles",
    "platforms",
    "workflow",
    "output_modes",
)

# id → label + line used when composing system prompt from selections
BOUNDARY_CHOICES: dict[str, list[dict[str, str]]] = {
    "principles": [
        {"id": "accurate", "label": "准确", "line": "先核对事实，信息不足就说明缺口，不编造。"},
        {"id": "executable", "label": "可执行", "line": "输出可直接使用：步骤清楚、少套话。"},
        {"id": "concise", "label": "简洁", "line": "默认简短；用户要求展开时再写长。"},
        {"id": "ask_when_unclear", "label": "目标不明先问", "line": "目标不清时最多问 1～3 个关键问题再动手。"},
    ],
    "platforms": [
        {"id": "follow_user", "label": "跟随用户", "line": "按用户指定的渠道或格式写，不预设平台。"},
        {"id": "kb_ref", "label": "细则见知识库", "line": "若知识库有对应页面，按其标题与正文执行。"},
    ],
    "workflow": [
        {
            "id": "clarify",
            "label": "先确认再做",
            "line": "先确认目标与约束，再行动。",
        },
        {
            "id": "tools_first",
            "label": "先工具后结论",
            "line": "需要查资料或改文件时先调工具，再根据结果回答。",
        },
        {
            "id": "wf_optional",
            "label": "多步用工作流",
            "line": "重复多步流程用设定→工作流，或让助手创建 workflow。",
        },
    ],
    "output_modes": [
        {"id": "as_asked", "label": "按用户要求", "line": "格式、长度、语言以用户当轮要求为准。"},
        {
            "id": "tools_media",
            "label": "生图/识图随技能",
            "line": "生图/识图仅在已安装对应 skill 时使用。",
        },
    ],
    "notes": [
        {
            "id": "mem_vs_kb",
            "label": "记忆≠知识库",
            "line": "短偏好 → memory；长手册 → kb。",
        },
    ],
    "constraints": [
        {
            "id": "no_invent",
            "label": "不编造",
            "line": "信息不足时说明缺口，不编造细节。",
        },
        {
            "id": "refuse_bad",
            "label": "拒不当内容",
            "line": "不当/虚假/误导内容拒绝并说明。",
        },
        {
            "id": "length_limit",
            "label": "守字数",
            "line": "有字数限制的区块严格遵守。",
        },
    ],
}

# Blank delivery: no chip pre-selection
DEFAULT_BOUNDARY_SEL: dict[str, list[str]] = {
    "principles_sel": [],
    "platforms_sel": [],
    "workflow_sel": [],
    "output_modes_sel": [],
    "notes_sel": [],
    "constraints_sel": [],
}


def compose_boundary_text(kind: str, selected_ids: list[str] | None) -> str:
    """Join selected choice lines for a boundary kind."""
    choices = {c["id"]: c for c in BOUNDARY_CHOICES.get(kind, [])}
    lines: list[str] = []
    for sid in selected_ids or []:
        c = choices.get(str(sid).strip())
        if c and c.get("line"):
            lines.append(c["line"])
    return "\n".join(lines)


def resolve_boundary_field(cfg: dict[str, Any], field: str) -> str:
    """Prefer chip selection composition; fall back to free text.

    field: principles | platforms | workflow | output_modes | notes | constraints
    When chips are selected, long legacy free-text dumps are ignored (only short
    supplements ≤400 chars are appended).
    """
    sel_key = f"{field}_sel"
    selected = _as_list(cfg.get(sel_key))
    composed = compose_boundary_text(field, selected) if selected else ""
    custom = _strip(cfg.get(field))
    if composed:
        c = custom.strip()
        if c and c != composed.strip() and len(c) <= 400:
            return f"{composed}\n\n【补充】\n{c}"
        return composed
    return custom or ""

PERSONA_PRESETS: dict[str, list[str]] = {
    "role": [
        "通用助手",
        "专属助手",
        "文案策划",
        "技术顾问",
        "产品经理",
        "研究员",
    ],
    "language": [
        "跟随用户",
        "简体中文",
        "繁体中文",
        "粤语",
        "英文",
        "中英混合",
    ],
    "language_style": [
        "专业",
        "简洁",
        "口语",
        "正式",
        "热情",
        "冷静",
        "可执行",
    ],
}

# Placeholder / empty-state hints for free-text boundaries (short; long docs → KB)
BOUNDARY_PLACEHOLDERS: dict[str, str] = {
    "principles": "可在此写原则；或由对话中让助手写入设定",
    "platforms": "目标平台（可选）",
    "workflow": "多步流程请用设定→工作流，或让助手创建",
    "output_modes": "输出格式说明（可选）",
}

_DEFAULT_BOUNDARIES: dict[str, str] = {
    "principles": "",
    "platforms": "",
    "workflow": "",
    "output_modes": "",
}

RECOMMENDED_NOTES = ""
RECOMMENDED_CONSTRAINTS = (
    "信息不足时说明缺口，不编造。\n"
    "不当/虚假/误导内容拒绝并说明。\n"
    "有字数限制的区块严格遵守。"
)

SYSTEM_FIXED_RULES_SUMMARY = """\
【系统固定 · 不可改】
事实边界（信息不足说明缺口，不编造）· 工具路由 · 记忆匹配与强制记住 · 媒体约定
意图预路由/硬拦截 · 受保护 skill · 凭证与路径安全
人设只影响身份与语气；与系统规则冲突时以系统为准。
"""


def _strip(v: Any) -> str:
    return str(v or "").strip()


def _as_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on", "开启", "启用"):
        return True
    if s in ("0", "false", "no", "off", "关闭", "停用", ""):
        return False
    return default


def _normalize_intensity(v: Any) -> str:
    s = _strip(v).lower()
    if s in ("轻度", "light", "low", "weak"):
        return "light"
    if s in ("深度", "deep", "strong", "full", "immersive"):
        return "deep"
    if s in ("中度", "medium", "mid", "normal", "balanced"):
        return "medium"
    return "medium"


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        raw = v
    else:
        s = _strip(v)
        if not s:
            return []
        if "\n" in s:
            raw = s.splitlines()
        elif "、" in s or "," in s or "，" in s:
            raw = []
            for part in s.replace("，", ",").replace("、", ",").split(","):
                raw.append(part.strip())
        else:
            raw = [s]
    out: list[str] = []
    seen: set[str] = set()
    for x in raw:
        t = _strip(x)
        if not t:
            continue
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


def _as_single(v: Any) -> str:
    if isinstance(v, list):
        for x in v:
            t = _strip(x)
            if t:
                return t
        return ""
    return _strip(v)


def _as_text(v: Any) -> str:
    """Free-text capability field: list → lines; str kept (multiline ok)."""
    if v is None:
        return ""
    if isinstance(v, list):
        items = _as_list(v)
        # short tags → join with顿号; long descriptions → newlines
        if items and all(len(x) <= 24 for x in items):
            return "、".join(items)
        return "\n".join(items)
    return _strip(v)


def _field_text(v: Any) -> str:
    if isinstance(v, list):
        return "、".join(_as_list(v))
    return _strip(v)


def _is_stock_background(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if t.startswith("You are a capable backend AI agent"):
        return True
    if "有能力的 AI 助手" in t and len(t) < 80:
        return True
    return False


def _empty_persona_options() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key in CHIP_KEYS:
        out[key] = []
        out[f"{key}_hidden"] = []
    return out


def _shorten_field(text: str, max_chars: int = 220) -> str:
    """Keep the first beat of a persona field; used on task turns only."""
    t = _compact_multiline(text)
    if len(t) <= max_chars:
        return t
    cut = t[:max_chars]
    for sep in ("。", "！", "？", "\n", "；", ".", "!"):
        i = cut.rfind(sep)
        if i >= 40:
            return cut[: i + 1].strip()
    return cut.rstrip() + "…"


# Tools that mean "this turn is work, not roleplay". Time-only chat stays full persona.
_TASK_PERSONA_TOOLS = frozenset(
    {
        "workflow",
        "scheduled_task",
        "integrations",
        "llms",
        "create_tool",
        "read_skill",
        "list_skills",
        "validate_skill",
        "promote_skill",
        "delete_tool",
        "workspace",
        "server_health_check",
        "list_api_models",
        "reload_runtime",
        "terminal",
        "document",
        "kb",
    }
)

_TASK_PERSONA_MARKERS = (
    "工作流",
    "定时任务",
    "excel",
    "xlsx",
    "docx",
    "pptx",
    "pdf",
)


def use_compact_persona(
    message: str,
    *,
    intent_force: set[str] | None = None,
    image_only: bool = False,
    tools: Any = None,
) -> bool:
    """True when this turn is a tool/business task — inject a short persona."""
    if image_only:
        return False
    forced = {str(x).strip() for x in (intent_force or set()) if str(x).strip()}
    skip = {"get_current_time", "ask_user", "memory"}
    if tools is not None:
        for n in forced:
            if n in skip:
                continue
            spec = None
            try:
                spec = tools.get(n)
            except Exception:
                spec = None
            src = str(getattr(spec, "source", "") or "")
            if src == "skill":
                return True
    if forced & _TASK_PERSONA_TOOLS:
        return True
    t = (message or "").lower()
    if not t.strip():
        return False
    return any(k.lower() in t for k in _TASK_PERSONA_MARKERS)


def _compact_multiline(text: str) -> str:
    lines = [line.rstrip() for line in (text or "").splitlines()]
    out: list[str] = []
    blank = False
    for line in lines:
        if not line.strip():
            if not blank and out:
                out.append("")
            blank = True
            continue
        blank = False
        out.append(line)
    return "\n".join(out).strip()


def migrate_legacy_system_prompt(agent: dict[str, Any]) -> dict[str, Any]:
    """Normalize agent dict for runtime / persistence.

    Empty persona fields stay empty. Stock commercial defaults are **not**
    re-injected (deleting config.json must yield a blank agent, not a refilled
    template). Only true legacy ``system_prompt`` / old boundary keys are
    migrated when present.
    """
    out = dict(agent or {})
    legacy = _strip(out.get("system_prompt"))
    bg = _strip(out.get("background"))

    # One-shot: old system_prompt → background when background empty/stock
    if legacy and _is_stock_background(bg):
        out["background"] = legacy
        bg = _strip(out["background"])

    # Identity — keep empty if user cleared / fresh install
    out["role"] = _as_list(out.get("role"))

    lang = _as_single(out.get("language"))
    if lang and ("跟随" in lang or "用户使用的语言" in lang):
        lang = "跟随用户"
    out["language"] = lang  # may be ""

    out["language_style"] = _as_list(out.get("language_style"))
    out["name"] = _strip(out.get("name"))  # may be ""

    # Normalize legacy boundary fields in-memory only (for one-shot seed into layers)
    for sel_key in BOUNDARY_SEL_KEYS:
        if sel_key in out and out.get(sel_key) is not None:
            out[sel_key] = _as_list(out.get(sel_key))
    for key in TEXT_BOUNDARY_FIELDS:
        if key in out and out.get(key) is not None:
            out[key] = _as_text(out.get(key))
    for key in ("duties", "constraints", "notes"):
        if key in out and out.get(key) is not None:
            out[key] = _strip(out.get(key))

    if not bg and legacy:
        out["background"] = legacy
    else:
        out["background"] = bg  # empty stays empty — no stock filler

    for key in LAYER_TEXT_FIELDS:
        if key not in out or out.get(key) is None:
            out[key] = ""
        else:
            out[key] = _strip(out.get(key))

    # --- Roleplay block (opt-in; empty by default) ---
    out["roleplay_enabled"] = _as_bool(out.get("roleplay_enabled"), False)
    out["roleplay_intensity"] = _normalize_intensity(out.get("roleplay_intensity"))
    for key in ROLEPLAY_TEXT_FIELDS:
        if key not in out or out.get(key) is None:
            out[key] = ""
        else:
            out[key] = _strip(out.get(key))

    opts = out.get("persona_options")
    if not isinstance(opts, dict):
        out["persona_options"] = _empty_persona_options()
    else:
        cleaned = _empty_persona_options()
        for key in CHIP_KEYS:
            cleaned[key] = _as_list(opts.get(key))
            cleaned[f"{key}_hidden"] = _as_list(
                opts.get(f"{key}_hidden") or opts.get(f"hidden_{key}")
            )
        out["persona_options"] = cleaned

    # runtime knobs (technical defaults only)
    try:
        mtr = int(out.get("max_tool_rounds") if out.get("max_tool_rounds") is not None else 8)
    except (TypeError, ValueError):
        mtr = 8
    out["max_tool_rounds"] = max(1, min(64, mtr))
    try:
        raw_mhm = out.get("max_history_messages")
        if raw_mhm is None:
            raw_mhm = out.get("max_history")
        mhm = int(raw_mhm if raw_mhm is not None else 40)
    except (TypeError, ValueError):
        mhm = 40
    out["max_history_messages"] = max(4, min(200, mhm))

    # Evolution knobs — fill only when missing
    if "evolution_enabled" not in out or out.get("evolution_enabled") is None:
        out["evolution_enabled"] = True
    for ekey, edef in (
        ("evolution_trigger_messages", 24),
        ("evolution_keep_messages", 16),
        ("evolution_max_entries", 12),
        ("evolution_max_chars", 2200),
    ):
        if ekey not in out or out.get(ekey) is None:
            out[ekey] = edef

    return compact_agent_config(out)


def compact_agent_config(agent: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only active agent keys for persistence / runtime."""
    src = dict(agent or {})
    out: dict[str, Any] = {}
    for key in ACTIVE_AGENT_KEYS:
        if key in src:
            out[key] = src[key]
    # Always persist identity keys (empty string / [] = intentionally blank)
    out.setdefault("name", "")
    out.setdefault("role", [])
    out.setdefault("language", "")
    out.setdefault("language_style", [])
    out.setdefault("background", "")
    # ensure layer keys always present
    for key in LAYER_TEXT_FIELDS:
        out.setdefault(key, "")
    out.setdefault("roleplay_enabled", False)
    out.setdefault("roleplay_intensity", "medium")
    for key in ROLEPLAY_TEXT_FIELDS:
        out.setdefault(key, "")
    if "persona_options" not in out or not isinstance(out.get("persona_options"), dict):
        out["persona_options"] = _empty_persona_options()
    # Normalize list fields
    if not isinstance(out.get("role"), list):
        out["role"] = _as_list(out.get("role"))
    if not isinstance(out.get("language_style"), list):
        out["language_style"] = _as_list(out.get("language_style"))
    return out


def merged_persona_options(agent_cfg: dict[str, Any] | None) -> dict[str, list[str]]:
    """Presets + custom minus hidden — only for multi-select identity fields."""
    cfg = migrate_legacy_system_prompt(dict(agent_cfg or {}))
    custom = cfg.get("persona_options") or {}
    out: dict[str, list[str]] = {}
    for key in ("role", "language", "language_style"):
        presets = list(PERSONA_PRESETS.get(key) or [])
        if key == "language":
            out[key] = presets
            continue
        hidden = {
            _strip(x).lower()
            for x in _as_list(custom.get(f"{key}_hidden"))
            if _strip(x)
        }
        merged: list[str] = []
        seen: set[str] = set()
        for x in presets + _as_list(custom.get(key)):
            t = _strip(x)
            if not t:
                continue
            k = t.lower()
            if k in seen or k in hidden:
                continue
            seen.add(k)
            merged.append(t)
        out[key] = merged
    return out


def build_persona_prompt(
    agent_cfg: dict[str, Any] | None,
    *,
    compact: bool = False,
) -> str:
    cfg = migrate_legacy_system_prompt(dict(agent_cfg or {}))
    if compact:
        return _build_compact_persona(cfg)
    parts: list[str] = []
    roleplay_on = _as_bool(cfg.get("roleplay_enabled"), False)
    intensity = _normalize_intensity(cfg.get("roleplay_intensity"))

    name = _strip(cfg.get("name"))
    if name:
        parts.append(f"名字：{name}。")

    # Base identity: name / language / 角色背景(background).
    # 旧版 role / language_style 多选已从 UI 移除，不再注入。
    lang = _field_text(cfg.get("language"))
    if lang:
        if lang == "跟随用户":
            parts.append("【语言】跟随用户当前使用的语言。")
        else:
            parts.append(f"【语言】{lang}")

    # 角色背景：优先 background；兼容旧数据仅有 role 标签时拼一行
    bg = _strip(cfg.get("background"))
    if not bg:
        legacy_role = _field_text(cfg.get("role"))
        if legacy_role:
            bg = legacy_role
    if bg:
        parts.append(f"【角色背景】\n{_compact_multiline(bg)}")

    # Roleplay block — only when switch is on (fields may still be saved when off)
    if roleplay_on:
        intensity_line = {
            "light": (
                "【扮演模式 · 开启 · 轻度】带一点角色口吻即可，仍以清晰、可执行的助手交付为主；"
                "不必全程沉浸。"
            ),
            "medium": (
                "【扮演模式 · 开启 · 中度】角色语气与任务交付并重：用角色身份说话，"
                "但关键信息仍要清楚、可操作。"
            ),
            "deep": (
                "【扮演模式 · 开启 · 深度】优先保持角色身份、关系与语气，少用「作为AI助手」腔；"
                "需要工具时仍可调用，但对外回复尽量保持角色口吻。"
            ),
        }.get(intensity) or (
            "【扮演模式 · 开启】按下方人设沉浸回复。"
        )
        parts.append(intensity_line)

        relationship = _strip(cfg.get("relationship"))
        if relationship:
            parts.append(
                f"【与用户关系】\n{_compact_multiline(relationship)}"
            )

        personality = _strip(cfg.get("personality"))
        if personality:
            parts.append(f"【性格与情绪】\n{_compact_multiline(personality)}")

        speech = _strip(cfg.get("speech_patterns"))
        if speech:
            parts.append(
                f"【说话方式 · 口癖与称呼】\n{_compact_multiline(speech)}"
            )

        examples = _strip(cfg.get("example_dialogue"))
        if examples:
            parts.append(
                "【示例对话】（风格参考，勿机械复读）\n"
                f"{_compact_multiline(examples)}"
            )

        ooc = _strip(cfg.get("ooc_rules"))
        if ooc:
            parts.append(
                "【破戏 / OOC 规则】\n"
                f"{_compact_multiline(ooc)}"
            )
        else:
            parts.append(
                "【破戏 / OOC 规则】默认保持角色；用户明确要求出戏、说明设定或切换助手模式时，"
                "可用简短旁白/OOC 回应后再回到角色。"
            )

    if not parts:
        legacy = _strip(cfg.get("system_prompt"))
        if legacy:
            return legacy
        return "你是 AI 助手。用用户语言清晰回复；需要时使用系统工具。"

    if roleplay_on:
        parts.append(
            "【优先级】系统工具/记忆/安全规则固定注入且优先于一切人设；"
            "在不违反安全与工具正确性的前提下，保持角色身份与语气。"
            "作业流程以知识库检索结果为准，不要凭空编造制度。"
            "冲突时以系统规则为准（含事实边界）；用户明确要求出戏时可短暂 OOC。"
        )
    else:
        parts.append(
            "【优先级】系统工具/记忆/安全规则固定注入且优先于人设；"
            "先正确调工具，再按角色向用户交付。"
            "作业流程以知识库检索结果为准，不要凭空编造制度。"
            "（角色扮演开关关闭：不注入扮演专用字段。）"
        )
    return "\n".join(parts)


def _build_compact_persona(cfg: dict[str, Any]) -> str:
    """Task-turn persona: identity + short RP, no SOP / examples / greeting."""
    parts: list[str] = []
    name = _strip(cfg.get("name"))
    if name:
        parts.append(f"名字：{name}。")
    lang = _field_text(cfg.get("language"))
    if lang:
        if lang == "跟随用户":
            parts.append("【语言】跟随用户当前使用的语言。")
        else:
            parts.append(f"【语言】{lang}")
    bg = _strip(cfg.get("background"))
    if bg:
        parts.append(f"【角色背景】\n{_shorten_field(bg, 160)}")
    if _as_bool(cfg.get("roleplay_enabled"), False):
        parts.append(
            "【扮演模式 · 任务轮精简】保持角色口吻，但先把这件事做完；"
            "不要客服式 A/B 选择题，除非用户在选方案。"
        )
        relationship = _strip(cfg.get("relationship"))
        if relationship:
            parts.append(f"【与用户关系】\n{_shorten_field(relationship, 220)}")
        personality = _strip(cfg.get("personality"))
        if personality:
            parts.append(f"【性格与情绪】\n{_shorten_field(personality, 220)}")
    parts.append(
        "【优先级】系统工具/记忆/安全规则优先于人设；对外仍用角色身份说话。"
        "本轮不注入示例对白。作业细则以知识库为准。"
    )
    if not parts:
        return "你是 AI 助手。用用户语言清晰回复；需要时使用系统工具。"
    return "\n".join(parts)


def persona_public_view(agent_cfg: dict[str, Any] | None) -> dict[str, Any]:
    cfg = migrate_legacy_system_prompt(dict(agent_cfg or {}))
    return {
        # Do not substitute "Agent" / "跟随用户" — empty means user cleared or fresh
        "name": _strip(cfg.get("name")),
        "role": _as_list(cfg.get("role")),
        "language": _as_single(cfg.get("language")),
        "language_style": _as_list(cfg.get("language_style")),
        "background": _strip(cfg.get("background")),
        "roleplay_enabled": bool(cfg.get("roleplay_enabled")),
        "roleplay_intensity": _normalize_intensity(cfg.get("roleplay_intensity")),
        "relationship": _strip(cfg.get("relationship")),
        "personality": _strip(cfg.get("personality")),
        "speech_patterns": _strip(cfg.get("speech_patterns")),
        "example_dialogue": _strip(cfg.get("example_dialogue")),
        "ooc_rules": _strip(cfg.get("ooc_rules")),
        "persona_options": cfg.get("persona_options") or _empty_persona_options(),
        "persona_presets": {
            "role": PERSONA_PRESETS["role"],
            "language": PERSONA_PRESETS["language"],
            "language_style": PERSONA_PRESETS["language_style"],
        },
        "persona_options_merged": merged_persona_options(cfg),
        "chip_keys": list(CHIP_KEYS),
        "layer_fields": list(LAYER_TEXT_FIELDS),
        "roleplay_fields": list(ROLEPLAY_TEXT_FIELDS),
        "roleplay_intensities": list(ROLEPLAY_INTENSITIES),
        "max_tool_rounds": cfg.get("max_tool_rounds"),
        "max_history_messages": cfg.get("max_history_messages"),
        "evolution_enabled": cfg.get("evolution_enabled"),
        "evolution_trigger_messages": cfg.get("evolution_trigger_messages"),
        "evolution_keep_messages": cfg.get("evolution_keep_messages"),
        "evolution_max_entries": cfg.get("evolution_max_entries"),
        "evolution_max_chars": cfg.get("evolution_max_chars"),
        "persona_preview": build_persona_prompt(cfg),
        "system_fixed_rules_summary": SYSTEM_FIXED_RULES_SUMMARY,
    }
