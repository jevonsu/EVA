"""Identity and communication preferences (not roleplay).

These fields are shared by the public basic-identity form and the
per-session independent persona. Option ids are new; legacy language
labels are accepted as aliases but are not presented as current choices.
"""

from __future__ import annotations

from typing import Any

LANGUAGE_INHERIT_PUBLIC = "inherit_public"
LANGUAGE_FOLLOW_USER = "follow_user"

IDENTITY_LANGUAGES = ("zh-Hans", "zh-Hant", "en", "ja", "follow_user")
SESSION_IDENTITY_LANGUAGES = (LANGUAGE_INHERIT_PUBLIC,) + IDENTITY_LANGUAGES

IDENTITY_LANGUAGE_LABELS: dict[str, str] = {
    LANGUAGE_INHERIT_PUBLIC: "跟随公共",
    LANGUAGE_FOLLOW_USER: "自动跟随用户",
    "zh-Hans": "简体中文",
    "zh-Hant": "繁体中文",
    "en": "English",
    "ja": "日本語",
}

# Legacy stored values and UI labels → canonical ids
_LANGUAGE_ALIASES: dict[str, str] = {
    "跟随公共": LANGUAGE_INHERIT_PUBLIC,
    "inherit": LANGUAGE_INHERIT_PUBLIC,
    "inherit_public": LANGUAGE_INHERIT_PUBLIC,
    "follow_public": LANGUAGE_INHERIT_PUBLIC,
    "follow-public": LANGUAGE_INHERIT_PUBLIC,
    "自动跟随用户": LANGUAGE_FOLLOW_USER,
    "跟随用户": LANGUAGE_FOLLOW_USER,
    "follow_user": LANGUAGE_FOLLOW_USER,
    "follow-user": LANGUAGE_FOLLOW_USER,
    "follow user": LANGUAGE_FOLLOW_USER,
    "简体中文": "zh-Hans",
    "簡體中文": "zh-Hans",
    "中文": "zh-Hans",
    "普通话": "zh-Hans",
    "普通話": "zh-Hans",
    "国语": "zh-Hans",
    "國語": "zh-Hans",
    "zh-cn": "zh-Hans",
    "zh_cn": "zh-Hans",
    "zh-hans": "zh-Hans",
    "zh-cn": "zh-Hans",
    "繁体中文": "zh-Hant",
    "繁體中文": "zh-Hant",
    "zh-tw": "zh-Hant",
    "zh_tw": "zh-Hant",
    "zh-hant": "zh-Hant",
    "english": "en",
    "英文": "en",
    "英语": "en",
    "英語": "en",
    "en-us": "en",
    "en-gb": "en",
    "en": "en",
    "日本語": "ja",
    "日语": "ja",
    "日語": "ja",
    "japanese": "ja",
    "ja-jp": "ja",
    "ja": "ja",
}

SPEECH_STYLES = ("natural", "concise", "gentle", "formal", "humorous", "detailed", "custom")
SESSION_SPEECH_STYLES = (LANGUAGE_INHERIT_PUBLIC,) + SPEECH_STYLES
SPEECH_STYLE_LABELS: dict[str, str] = {
    LANGUAGE_INHERIT_PUBLIC: "跟随公共",
    "natural": "自然口语（说人话）",
    "concise": "简洁直接",
    "gentle": "温和耐心",
    "formal": "正式专业",
    "humorous": "轻松幽默",
    "detailed": "详细讲解",
    "custom": "自定义",
}

ANSWER_DETAILS = ("brief", "balanced", "detailed")
SESSION_ANSWER_DETAILS = (LANGUAGE_INHERIT_PUBLIC,) + ANSWER_DETAILS
ANSWER_DETAIL_LABELS: dict[str, str] = {
    LANGUAGE_INHERIT_PUBLIC: "跟随公共",
    "brief": "简要",
    "balanced": "适中",
    "detailed": "详尽",
}

TERMINOLOGY_LEVELS = ("plain", "balanced", "technical")
SESSION_TERMINOLOGY = (LANGUAGE_INHERIT_PUBLIC,) + TERMINOLOGY_LEVELS
TERMINOLOGY_LABELS: dict[str, str] = {
    LANGUAGE_INHERIT_PUBLIC: "跟随公共",
    "plain": "少用术语，必要时先解释",
    "balanced": "适度使用术语",
    "technical": "可以使用专业术语",
}

IDENTITY_COMM_KEYS = (
    "name",
    "language",
    "background",
    "speech_style",
    "speech_style_custom",
    "answer_detail",
    "terminology",
)

# Avatar is identity chrome; not required in the independent form.
IDENTITY_OPTIONAL_KEYS = ("avatar",)

PERSONA_TEXT_MAX = 8000
PERSONA_NAME_MAX = 80

_SPEECH_STYLE_PROMPTS: dict[str, str] = {
    "natural": (
        "【讲话方式 · 自然口语（说人话）】用完整、自然的句子说话，像日常交谈那样把意思讲清楚；"
        "少用术语、套话和条目堆砌。不要写舞台动作、表情描写或括号里的表演提示；"
        "不要虚构现实世界中的身份、经历或关系。讲话方式只影响表达，"
        "不能绕过系统工具、记忆与安全规则。"
    ),
    "concise": (
        "【讲话方式 · 简洁直接】先给结论，再补必要说明，避免重复和客套。"
        "不要写舞台动作，不要虚构现实身份。不能绕过系统工具与安全规则。"
    ),
    "gentle": (
        "【讲话方式 · 温和耐心】语气友善、不催促；遇到复杂问题分步说明，允许用户慢慢想。"
        "不要写舞台动作，不要虚构现实身份。不能绕过系统工具与安全规则。"
    ),
    "formal": (
        "【讲话方式 · 正式专业】用书面、克制的专业表达，结构清楚，避免过于口语或玩笑。"
        "不要写舞台动作，不要虚构现实身份。不能绕过系统工具与安全规则。"
    ),
    "humorous": (
        "【讲话方式 · 轻松幽默】在保持准确的前提下可用轻松、适度的幽默；"
        "不要嘲讽用户，不要用玩笑代替事实或工具结果。"
        "不要写舞台动作，不要虚构现实身份。不能绕过系统工具与安全规则。"
    ),
    "detailed": (
        "【讲话方式 · 详细讲解】把步骤、原因和注意点讲清楚，必要时举简短例子；仍避免空话和重复。"
        "不要写舞台动作，不要虚构现实身份。不能绕过系统工具与安全规则。"
    ),
}

_ANSWER_DETAIL_PROMPTS: dict[str, str] = {
    "brief": "【回答详略】默认简要作答；用户要求展开时再写详细。",
    "balanced": "【回答详略】详略适中，按问题复杂度调整篇幅。",
    "detailed": "【回答详略】默认把要点讲完整，必要时分点说明；仍避免注水。",
}

_TERMINOLOGY_PROMPTS: dict[str, str] = {
    "plain": "【术语】少用专业术语；必须出现时先用白话解释。",
    "balanced": "【术语】可适度使用术语，并在可能造成误解时随手解释。",
    "technical": "【术语】可以使用专业术语，默认对方具有相关背景；若用户显得陌生再改为解释。",
}

_LANGUAGE_PROMPT: dict[str, str] = {
    LANGUAGE_FOLLOW_USER: "【语言】自动跟随用户当前使用的语言。",
    "zh-Hans": "【语言】使用简体中文回复。",
    "zh-Hant": "【语言】使用繁体中文回复。",
    "en": "【语言】Reply in English.",
    "ja": "【语言】日本語で返信してください。",
}

ROLEPLAY_FIELD_KEYS = (
    "roleplay_enabled",
    "roleplay_intensity",
    "roleplay_background",
    "relationship",
    "personality",
    "speech_patterns",
    "example_dialogue",
    "ooc_rules",
)


def _strip(v: Any) -> str:
    return str(v or "").strip()


def _is_inherit_token(v: str) -> bool:
    t = v.strip().lower().replace(" ", "_").replace("-", "_")
    return t in {"inherit_public", "inherit", "follow_public"} or v.strip() == "跟随公共"


def normalize_identity_language(value: Any, *, allow_inherit: bool = False) -> str:
    """Return a canonical language id, a preserved legacy label, or ''.

    Unknown non-empty values are returned as the original stripped text so
    previously saved options (e.g. 粤语) still render in the prompt.
    """
    raw = _strip(value)
    if not raw:
        return ""
    if _is_inherit_token(raw):
        return LANGUAGE_INHERIT_PUBLIC if allow_inherit else ""
    key = raw.lower()
    if raw in _LANGUAGE_ALIASES:
        cid = _LANGUAGE_ALIASES[raw]
    elif key in _LANGUAGE_ALIASES:
        cid = _LANGUAGE_ALIASES[key]
    else:
        cid = raw
    if cid == LANGUAGE_INHERIT_PUBLIC:
        return LANGUAGE_INHERIT_PUBLIC if allow_inherit else ""
    return cid


def parse_identity_language(value: Any, *, allow_inherit: bool = False) -> str:
    """Validate a language for API writes.

    Official ids are preferred. Legacy stored labels such as 粤语 are kept so
    existing public configs can still be saved, but they are not offered as
    new dropdown choices.
    """
    raw = _strip(value)
    if not raw:
        return ""
    if _is_inherit_token(raw):
        if allow_inherit:
            return LANGUAGE_INHERIT_PUBLIC
        raise ValueError("公共人设的语言不能选「跟随公共」")
    cid = normalize_identity_language(raw, allow_inherit=allow_inherit)
    allowed = SESSION_IDENTITY_LANGUAGES if allow_inherit else IDENTITY_LANGUAGES
    if cid in allowed:
        return cid
    if cid == LANGUAGE_INHERIT_PUBLIC:
        raise ValueError("公共人设的语言不能选「跟随公共」")
    # preserve leftover legacy labels (粤语 / 中英混合, etc.)
    return cid


def _enum_id(
    value: Any,
    *,
    aliases: dict[str, str],
    allowed: tuple[str, ...],
    allow_inherit: bool,
    field: str,
    labels: dict[str, str],
    strict: bool,
) -> str:
    raw = _strip(value)
    if not raw:
        return ""
    if _is_inherit_token(raw):
        if allow_inherit:
            return LANGUAGE_INHERIT_PUBLIC
        return ""
    key = raw.lower()
    cid = aliases.get(raw) or aliases.get(key) or (raw if raw in allowed else "")
    if not cid:
        # also accept labels
        for mid, lab in labels.items():
            if raw == lab or key == lab.lower():
                cid = mid
                break
    if cid == LANGUAGE_INHERIT_PUBLIC:
        return LANGUAGE_INHERIT_PUBLIC if allow_inherit else ""
    if cid in allowed and (allow_inherit or cid != LANGUAGE_INHERIT_PUBLIC):
        return cid
    if strict:
        opts = [labels[x] for x in allowed if x != LANGUAGE_INHERIT_PUBLIC or allow_inherit]
        raise ValueError(f"{field} 无效；可选：" + "、".join(opts))
    return ""


def normalize_speech_style(value: Any, *, allow_inherit: bool = False, strict: bool = False) -> str:
    aliases = {k: k for k in SESSION_SPEECH_STYLES}
    aliases.update({v: k for k, v in SPEECH_STYLE_LABELS.items()})
    aliases["说人话"] = "natural"
    aliases["人话"] = "natural"
    aliases["自然口语"] = "natural"
    aliases["自然口语（说人话）"] = "natural"
    return _enum_id(
        value,
        aliases=aliases,
        allowed=SESSION_SPEECH_STYLES if allow_inherit else SPEECH_STYLES,
        allow_inherit=allow_inherit,
        field="speech_style",
        labels=SPEECH_STYLE_LABELS,
        strict=strict,
    )


def normalize_answer_detail(value: Any, *, allow_inherit: bool = False, strict: bool = False) -> str:
    aliases = {k: k for k in SESSION_ANSWER_DETAILS}
    aliases.update({v: k for k, v in ANSWER_DETAIL_LABELS.items()})
    return _enum_id(
        value,
        aliases=aliases,
        allowed=SESSION_ANSWER_DETAILS if allow_inherit else ANSWER_DETAILS,
        allow_inherit=allow_inherit,
        field="answer_detail",
        labels=ANSWER_DETAIL_LABELS,
        strict=strict,
    )


def normalize_terminology(value: Any, *, allow_inherit: bool = False, strict: bool = False) -> str:
    aliases = {k: k for k in SESSION_TERMINOLOGY}
    aliases.update({v: k for k, v in TERMINOLOGY_LABELS.items()})
    return _enum_id(
        value,
        aliases=aliases,
        allowed=SESSION_TERMINOLOGY if allow_inherit else TERMINOLOGY_LEVELS,
        allow_inherit=allow_inherit,
        field="terminology",
        labels=TERMINOLOGY_LABELS,
        strict=strict,
    )


def language_prompt_line(value: Any) -> str:
    cid = normalize_identity_language(value, allow_inherit=False)
    if not cid:
        return ""
    if cid in _LANGUAGE_PROMPT:
        return _LANGUAGE_PROMPT[cid]
    # Legacy stored labels such as 粤语 / 中英混合
    if cid == LANGUAGE_INHERIT_PUBLIC:
        return ""
    return f"【语言】{cid}"


def communication_prompt_lines(cfg: dict[str, Any] | None, *, compact: bool = False) -> list[str]:
    """Prompt fragments for speech style / detail / terminology. Never roleplay."""
    cfg = cfg or {}
    parts: list[str] = []
    style = normalize_speech_style(cfg.get("speech_style"), allow_inherit=False)
    custom = _strip(cfg.get("speech_style_custom"))[:PERSONA_TEXT_MAX]
    if style == "custom":
        if custom:
            body = custom if not compact else custom[:220]
            parts.append(f"【讲话方式 · 自定义要求】\n{body}")
        # custom with empty text: no style line (validation should catch on save)
    elif style in _SPEECH_STYLE_PROMPTS:
        line = _SPEECH_STYLE_PROMPTS[style]
        if compact:
            # keep the heading + first clause
            parts.append(line.split("；")[0] + "。不能绕过系统工具与安全规则。")
        else:
            parts.append(line)
        if custom:
            body = custom if not compact else custom[:160]
            parts.append(f"【讲话方式 · 补充要求】\n{body}")
    elif custom:
        body = custom if not compact else custom[:160]
        parts.append(f"【讲话方式 · 补充要求】\n{body}")

    detail = normalize_answer_detail(cfg.get("answer_detail"), allow_inherit=False)
    if detail in _ANSWER_DETAIL_PROMPTS:
        parts.append(_ANSWER_DETAIL_PROMPTS[detail])
    term = normalize_terminology(cfg.get("terminology"), allow_inherit=False)
    if term in _TERMINOLOGY_PROMPTS:
        parts.append(_TERMINOLOGY_PROMPTS[term])
    return parts


def has_legacy_roleplay_payload(agent: dict[str, Any] | None) -> bool:
    if not isinstance(agent, dict):
        return False
    if bool(agent.get("roleplay_enabled")):
        return True
    for key in ROLEPLAY_FIELD_KEYS:
        if key == "roleplay_enabled" or key == "roleplay_intensity":
            continue
        val = agent.get(key)
        if isinstance(val, str) and val.strip():
            return True
        if isinstance(val, list) and any(str(x).strip() for x in val):
            return True
    return False


def identity_field_choices(*, for_session: bool = False) -> dict[str, Any]:
    def _opts(ids: tuple[str, ...], labels: dict[str, str]) -> list[dict[str, str]]:
        return [{"id": i, "label": labels[i]} for i in ids]

    langs = SESSION_IDENTITY_LANGUAGES if for_session else IDENTITY_LANGUAGES
    styles = SESSION_SPEECH_STYLES if for_session else SPEECH_STYLES
    details = SESSION_ANSWER_DETAILS if for_session else ANSWER_DETAILS
    terms = SESSION_TERMINOLOGY if for_session else TERMINOLOGY_LEVELS
    return {
        "language": _opts(langs, IDENTITY_LANGUAGE_LABELS),
        "speech_style": _opts(styles, SPEECH_STYLE_LABELS),
        "answer_detail": _opts(details, ANSWER_DETAIL_LABELS),
        "terminology": _opts(terms, TERMINOLOGY_LABELS),
        "follow_public_id": LANGUAGE_INHERIT_PUBLIC,
        "copy": {
            "inherit_mode": (
                "跟随公共人设：本会话完整使用当前公共人设（含公共角色扮演，若已启用）。"
                "每轮请求开始读取最新公共快照，不会改写公共配置。"
            ),
            "override_mode": (
                "独立人设：只配置本会话的助手身份与沟通偏好，不含角色扮演，也不会沿用公共角色扮演开关。"
                "某一栏选「跟随公共」时，仅该栏每轮跟公共身份走，不等于总体模式的「跟随公共人设」。"
            ),
            "language_follow_vs_mode": (
                "语言「跟随公共」只让回复语言跟公共；总体模式「跟随公共人设」才会使用完整公共人设（含扮演）。"
            ),
        },
    }


def validate_identity_payload(
    raw: dict[str, Any] | None,
    *,
    allow_inherit: bool,
) -> dict[str, Any]:
    """Normalize and validate identity fields for API writes."""
    src = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    if "name" in src:
        name = _strip(src.get("name"))[:PERSONA_NAME_MAX]
        out["name"] = name
    if "avatar" in src:
        out["avatar"] = src.get("avatar")
    if "language" in src:
        out["language"] = parse_identity_language(src.get("language"), allow_inherit=allow_inherit)
    if "background" in src:
        bg = _strip(src.get("background"))[:PERSONA_TEXT_MAX]
        out["background"] = bg
    if "speech_style" in src:
        out["speech_style"] = normalize_speech_style(
            src.get("speech_style"), allow_inherit=allow_inherit, strict=True
        )
    if "speech_style_custom" in src:
        out["speech_style_custom"] = _strip(src.get("speech_style_custom"))[:PERSONA_TEXT_MAX]
    if "answer_detail" in src:
        out["answer_detail"] = normalize_answer_detail(
            src.get("answer_detail"), allow_inherit=allow_inherit, strict=True
        )
    if "terminology" in src:
        out["terminology"] = normalize_terminology(
            src.get("terminology"), allow_inherit=allow_inherit, strict=True
        )
    style = out.get("speech_style") or normalize_speech_style(src.get("speech_style"), allow_inherit=allow_inherit)
    custom = out.get("speech_style_custom") if "speech_style_custom" in out else _strip(src.get("speech_style_custom"))
    if style == "custom" and not custom:
        raise ValueError("讲话方式选择「自定义」时，请填写自定义要求")
    return out
