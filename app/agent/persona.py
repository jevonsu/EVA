"""User-editable persona vs system-fixed operational rules.

Editable expression:
  1. Identity + persona (one UI block):
     - always: name, role, language, language_style, background
     - opt-in roleplay (roleplay_enabled): relationship / personality /
       speech_patterns / example_dialogue / ooc_rules + intensity
     - runtime knobs: max_tool_rounds, max_history_messages, evolution_*
  2. decision_tree — 隐性决策树
  3. language_calibrator — 动态语言校准器
  4. sop — 标准化作业流程
  5. hard_boundaries — 硬性边界（通用红线）
  6. greeting — 通用开机语

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
    "decision_tree",
    "language_calibrator",
    "sop",
    "hard_boundaries",
    "greeting",
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
    "decision_tree",
    "language_calibrator",
    "sop",
    "hard_boundaries",
    "greeting",
)

# Primary free-text layers of the agent form (assistant workflow)
LAYER_TEXT_FIELDS = (
    "decision_tree",
    "language_calibrator",
    "sop",
    "hard_boundaries",
    "greeting",
)

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
        {"id": "commercial", "label": "商业化", "line": "商业化：卖点与转化优先，不只描述画面。"},
        {"id": "executable", "label": "可执行", "line": "可执行：输出可直接复制到 AI 工具。"},
        {"id": "viral", "label": "爆款思维", "line": "爆款思维：优先点击率、传播性、主体突出。"},
        {"id": "platform_fit", "label": "平台适配", "line": "平台适配：按目标平台调整语气与结构。"},
        {"id": "info_tiers", "label": "信息分级", "line": "信息分级：可确认 / 推测 / 需补充，禁止编造。"},
        {"id": "stage_order", "label": "不跳阶段", "line": "按阶段执行，只生成用户需要的内容类型。"},
    ],
    "platforms": [
        {"id": "xhs", "label": "小红书", "line": "小红书：生活方式 + 情绪价值 + 真实种草。"},
        {"id": "taobao", "label": "淘宝/天猫", "line": "淘宝/天猫：卖点突出 + 信任背书 + 转化。"},
        {"id": "douyin", "label": "抖音/视频号", "line": "抖音/视频号：前三秒钩子 + 节奏 + 互动。"},
        {"id": "zhihu", "label": "知乎", "line": "知乎：专业深度 + 客观测评。"},
        {"id": "tvc", "label": "TVC/品牌", "line": "TVC/品牌广告：情绪曲线 + 镜头语言 + 记忆点。"},
        {
            "id": "kb_ref",
            "label": "细则见知识库",
            "line": "平台专章与模板全文见知识库 collection=commercial。",
        },
    ],
    "workflow": [
        {
            "id": "s1",
            "label": "阶段1 识别",
            "line": "阶段1 产品识别：输出可确认/推测/需补充。",
        },
        {
            "id": "s15",
            "label": "阶段1.5 咨询",
            "line": "阶段1.5 主动咨询：目标不明时最多约3问；「随便」用默认策略并标注。",
        },
        {
            "id": "s2",
            "label": "阶段2 策略",
            "line": "阶段2 策略：平台/人群/传播方向/视觉调性。",
        },
        {
            "id": "s3",
            "label": "阶段3 按需生成",
            "line": "阶段3 生成：仅按用户需要的类型输出。",
        },
        {
            "id": "video_ab",
            "label": "视频 A′→B",
            "line": "视频默认：先首帧改图 A′，再视频 B（用户明确跳过除外）。",
        },
        {
            "id": "wf_pipeline",
            "label": "工作流·内容流水线",
            "line": "编排可用工作流 commercial_content_pipeline。",
        },
        {
            "id": "wf_video",
            "label": "工作流·视频路径",
            "line": "视频路径可用工作流 commercial_video_a_prime_then_b。",
        },
    ],
    "output_modes": [
        {"id": "mode_a", "label": "图片 Prompt", "line": "模式 A：商品/场景图 Prompt（中英）。"},
        {"id": "mode_ap", "label": "首帧改图 A′", "line": "模式 A′：视频母版首帧改图（锁外观）。"},
        {"id": "mode_b", "label": "视频 B", "line": "模式 B：CRITICAL 锁定参考图 + 旁白/字幕模板。"},
        {"id": "mode_c", "label": "小红书", "line": "模式 C：小红书种草笔记。"},
        {"id": "mode_d", "label": "淘宝素材", "line": "模式 D：淘宝/天猫电商素材。"},
        {"id": "mode_e", "label": "抖音脚本", "line": "模式 E：抖音/视频号脚本。"},
        {"id": "mode_tvc", "label": "TVC", "line": "TVC：10/15/30 秒方案（知识库手册）。"},
        {
            "id": "tools_media",
            "label": "生图/识图工具",
            "line": "真·生图视频用 grok_media；识图用 analyze_image_auto；模板全文用 kb。",
        },
    ],
    "notes": [
        {
            "id": "def_xhs",
            "label": "默认小红书",
            "line": "默认平台：小红书。",
        },
        {
            "id": "def_mom",
            "label": "默认宝妈/女性",
            "line": "默认人群：宝妈/女性。",
        },
        {
            "id": "def_img_copy",
            "label": "默认图片+文案",
            "line": "默认内容：图片+文案。",
        },
        {
            "id": "def_studio",
            "label": "默认棚拍首帧",
            "line": "首帧背景默认：浅色棚拍 + 柔光 + 产品居中。",
        },
        {
            "id": "def_mark",
            "label": "标注默认策略",
            "line": "使用默认时须标注：⚠️ 基于默认策略，建议补充后优化。",
        },
        {
            "id": "mem_vs_kb",
            "label": "记忆≠知识库",
            "line": "短偏好 → memory；长手册/SOP → kb。",
        },
    ],
    "constraints": [
        {
            "id": "no_invent",
            "label": "不编造",
            "line": "信息不足时区分可确认/推测/需补充，不编造细节。",
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
        {
            "id": "default_on_skip",
            "label": "拒答用默认",
            "line": "用户拒绝补充关键信息时用默认策略并标注。",
        },
    ],
}

# Default chip selection for commercial-content agents
DEFAULT_BOUNDARY_SEL: dict[str, list[str]] = {
    "principles_sel": [
        "commercial",
        "executable",
        "viral",
        "platform_fit",
        "info_tiers",
        "stage_order",
    ],
    "platforms_sel": ["xhs", "taobao", "douyin", "zhihu", "tvc", "kb_ref"],
    "workflow_sel": ["s1", "s15", "s2", "s3", "video_ab", "wf_pipeline", "wf_video"],
    "output_modes_sel": [
        "mode_a",
        "mode_ap",
        "mode_b",
        "mode_c",
        "mode_d",
        "mode_e",
        "mode_tvc",
        "tools_media",
    ],
    "notes_sel": [
        "def_xhs",
        "def_mom",
        "def_img_copy",
        "def_studio",
        "def_mark",
        "mem_vs_kb",
    ],
    "constraints_sel": ["no_invent", "refuse_bad", "length_limit", "default_on_skip"],
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
        "AI商业内容专家",
        "产品视觉分析师",
        "爆款策略总监",
        "AI提示词工程师",
        "淘宝天猫视觉策划",
        "小红书种草博主",
        "抖音短视频导演",
        "TVC广告导演",
        "AI商业摄影师",
        "产品视觉营销顾问",
        "知乎深度种草答主",
        "专属助手",
        "文案策划",
        "技术顾问",
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
        "商业化",
        "可执行",
        "爆款思维",
        "种草",
        "转化导向",
        "专业测评",
        "简洁",
        "口语",
        "正式",
        "热情",
        "冷静",
    ],
}

# Placeholder / empty-state hints for free-text boundaries (short; long docs → KB)
BOUNDARY_PLACEHOLDERS: dict[str, str] = {
    "principles": "商业化 · 可执行 · 爆款 · 平台适配 · 信息三级（可确认/推测/需补充）",
    "platforms": "小红书、淘宝/天猫、抖音、视频号、知乎、TVC…（专章在知识库）",
    "workflow": "1识别→1.5咨询→2策略→3按需生成；视频先A′再B。工作流 commercial_content_pipeline",
    "output_modes": "图/改图/视频/小红书/淘宝/抖音/TVC…模板用 kb，勿在此贴全文",
}

# Recommended short summaries for the Agent form (not full SOP)
_DEFAULT_BOUNDARIES: dict[str, str] = {
    "principles": (
        "商业化：卖点与转化优先。\n"
        "可执行：输出可直接复制到 AI 工具。\n"
        "爆款思维：点击率/传播/主体突出。\n"
        "平台适配：按目标平台调整。\n"
        "信息分级：可确认 / 推测 / 需补充，禁止编造。"
    ),
    "platforms": (
        "小红书、淘宝/天猫、抖音/视频号、知乎、TVC/品牌广告。\n"
        "细则见知识库 commercial（模式 C/D/E、TVC 手册等）。"
    ),
    "workflow": (
        "阶段1 产品识别 → 1.5 主动咨询（最多约3问）→ 2 策略 → 3 仅生成用户需要的类型。\n"
        "视频默认：先首帧改图 A′，再视频 B（用户明确跳过除外）。\n"
        "编排：工作流 commercial_content_pipeline / commercial_video_a_prime_then_b。"
    ),
    "output_modes": (
        "图片 Prompt · 首帧改图 A′ · 视频 CRITICAL 模板 B · 小红书 · 淘宝素材 · 抖音脚本 · TVC。\n"
        "强制模板全文在知识库 commercial-modes；生图/视频用 grok_media，识图用 analyze_image_auto。"
    ),
}

# Short defaults for notes / constraints (form 「填入推荐摘要」)
RECOMMENDED_NOTES = (
    "用户说「随便/默认/你决定」时：\n"
    "平台小红书 · 人群宝妈/女性 · 内容图片+文案；\n"
    "首帧背景默认浅色棚拍+柔光+居中。\n"
    "须标注：⚠️ 基于默认策略，建议补充后优化。\n"
    "短偏好 → memory；长手册 → kb。"
)
RECOMMENDED_CONSTRAINTS = (
    "信息不足时区分可确认/推测/需补充，不编造。\n"
    "拒绝补充时用默认策略并标注。\n"
    "不当/虚假/误导内容拒绝并说明。\n"
    "有字数限制的区块严格遵守。"
)

SYSTEM_FIXED_RULES_SUMMARY = """\
【系统固定 · 不可改】
工具路由（workspace/http/memory/…）· 记忆匹配与强制记住 · 媒体约定
意图预路由/硬拦截 · 受保护 skill · 凭证与路径安全
人设/能力边界仅影响表达与业务交付；与系统规则冲突时以系统为准。
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

    # --- Six-layer free text ---
    # Only auto-seed from *legacy boundary keys* when layer key never existed.
    missing_layers = {k for k in LAYER_TEXT_FIELDS if k not in out or out.get(k) is None}
    for key in LAYER_TEXT_FIELDS:
        if key in missing_layers:
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

    # Migrate old commercial boundary blobs → layers only on first upgrade
    if "decision_tree" in missing_layers and not out["decision_tree"]:
        chunks: list[str] = []
        p = resolve_boundary_field(out, "principles")
        if p:
            chunks.append(p)
        d = _strip(out.get("duties"))
        if d:
            chunks.append(d)
        if chunks:
            out["decision_tree"] = "\n\n".join(chunks)

    if "sop" in missing_layers and not out["sop"]:
        w = resolve_boundary_field(out, "workflow")
        modes = resolve_boundary_field(out, "output_modes")
        bits = [x for x in (w, modes) if x]
        if bits:
            out["sop"] = "\n\n".join(bits)

    if "hard_boundaries" in missing_layers and not out["hard_boundaries"]:
        c = resolve_boundary_field(out, "constraints")
        if c:
            out["hard_boundaries"] = c
        elif _strip(out.get("constraints")):
            out["hard_boundaries"] = _strip(out.get("constraints"))

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


def build_persona_prompt(agent_cfg: dict[str, Any] | None) -> str:
    cfg = migrate_legacy_system_prompt(dict(agent_cfg or {}))
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

    decision_tree = _strip(cfg.get("decision_tree"))
    if decision_tree:
        parts.append(
            "【隐性决策树】（内部判断路径，勿向用户完整复述决策树本身）\n"
            f"{_compact_multiline(decision_tree)}"
        )

    calibrator = _strip(cfg.get("language_calibrator"))
    if calibrator:
        parts.append(
            f"【动态语言校准器】\n{_compact_multiline(calibrator)}"
        )

    sop = _strip(cfg.get("sop"))
    if sop:
        # Deep RP: still inject SOP but mark as internal work method
        if roleplay_on and intensity == "deep":
            parts.append(
                "【标准化作业流程 · SOP】（内部办事顺序；对外仍用角色口吻呈现结果）\n"
                f"{_compact_multiline(sop)}"
            )
        else:
            parts.append(f"【标准化作业流程 · SOP】\n{_compact_multiline(sop)}")

    hard = _strip(cfg.get("hard_boundaries"))
    if hard:
        parts.append(f"【硬性边界 · 通用红线】\n{_compact_multiline(hard)}")

    greeting = _strip(cfg.get("greeting"))
    if greeting:
        parts.append(
            "【通用开机语】新对话开场可参考以下语气与内容（勿机械每次全文复读，"
            "除非用户明确要求重说）：\n"
            f"{_compact_multiline(greeting)}"
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
            "冲突时以系统规则与硬性边界为准；用户明确要求出戏时可短暂 OOC。"
        )
    else:
        parts.append(
            "【优先级】系统工具/记忆/安全规则固定注入且优先于人设；"
            "先正确调工具，再按角色与决策/SOP/边界向用户交付。"
            "冲突时以系统规则与硬性边界为准。"
            "（角色扮演开关关闭：不注入扮演专用字段。）"
        )
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
        "decision_tree": _strip(cfg.get("decision_tree")),
        "language_calibrator": _strip(cfg.get("language_calibrator")),
        "sop": _strip(cfg.get("sop")),
        "hard_boundaries": _strip(cfg.get("hard_boundaries")),
        "greeting": _strip(cfg.get("greeting")),
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
