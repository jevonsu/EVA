"""Model routing: feature points -> LLM row id (config key ``model_routing``).

Schema (data/config.json)::

    "model_routing": {
        "default_llm": "",            # optional; empty = 设定→模型 的默认模型
        "rules": [
            {"id": "r1", "name": "识图走 GPT-4o", "enabled": true,
             "features": ["vision", "skill:foo"], "llm_id": "<llm id>"}
        ]
    }

Lookup: the caller passes the feature points active for this call, most specific
first. For each feature, the first enabled rule containing it wins. No match ->
``default_llm`` (if set) -> caller's fallback (global default client).

Legacy ``{"scenes": {...}, "skills": {...}}`` is migrated to rules on read.
Read live on every call; saving takes effect without restart.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# (id, 中文名, 分组, 说明) — every place EVA actually calls an LLM.
FEATURES: list[tuple[str, str, str, str]] = [
    ("chat.web", "网页/桌面对话", "对话", "设定页聊天窗口发起的 Agent 对话（含工具规划与回复）"),
    ("chat.stream", "纯流式对话", "对话", "/api/chat/stream 无工具流式接口"),
    ("chat.roleplay", "角色扮演对话", "对话", "开启角色扮演时的闲聊轮（命中技能/识图时让位）"),
    ("chat.webhook", "Webhook / 外部渠道", "对话", "外部消息渠道经 webhook 进入的对话"),
    ("chat.scheduler", "定时任务", "自动化", "任务调度器执行的 prompt"),
    ("chat.workflow", "工作流 Agent 步骤", "自动化", "工作流里的 agent 步骤"),
    ("vision", "识图（带图片的对话）", "多模态", "本轮消息带图片时的主模型"),
    ("skill", "技能轮（任意技能）", "技能", "本轮命中任意技能工具时"),
    ("tool_final", "工具轮次用尽后的收尾总结", "后台", "工具调用达到上限后强制生成文字回复"),
    ("evolution", "会话演化压缩", "后台", "长会话把旧消息压缩成演化摘要"),
    ("skill_handler", "技能脚本内调用默认模型", "技能", "技能代码通过 llm_credentials() 取默认模型时"),
]
FEATURE_KEYS = {k for k, *_ in FEATURES}
SKILL_PREFIX = "skill:"

# legacy scene -> features
_LEGACY_SCENE_MAP = {
    "chat": ["chat.web", "chat.stream"],
    "evolution": ["evolution"],
    "vision": ["vision"],
    "skill_default": ["skill"],
}


def _valid_feature(f: str) -> bool:
    return f in FEATURE_KEYS or (f.startswith(SKILL_PREFIX) and len(f) > len(SKILL_PREFIX))


def _norm_rule(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    feats: list[str] = []
    for f in raw.get("features") or []:
        ff = str(f or "").strip()
        if ff and _valid_feature(ff) and ff not in feats:
            feats.append(ff)
    llm_id = str(raw.get("llm_id") or "").strip()
    if not feats or not llm_id:
        return None
    return {
        "id": str(raw.get("id") or "").strip() or uuid.uuid4().hex[:8],
        "name": str(raw.get("name") or "").strip()[:60],
        "enabled": raw.get("enabled", True) is not False,
        "features": feats,
        "llm_id": llm_id,
    }


def _migrate_legacy(data: dict[str, Any]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    scenes = data.get("scenes") if isinstance(data.get("scenes"), dict) else {}
    by_llm: dict[str, list[str]] = {}
    for scene, feats in _LEGACY_SCENE_MAP.items():
        lid = str(scenes.get(scene) or "").strip()
        if lid:
            by_llm.setdefault(lid, []).extend(feats)
    skills = data.get("skills") if isinstance(data.get("skills"), dict) else {}
    for k, v in skills.items():
        kk, vv = str(k or "").strip(), str(v or "").strip()
        if kk and vv:
            by_llm.setdefault(vv, []).append(SKILL_PREFIX + kk)
    for i, (lid, feats) in enumerate(by_llm.items(), 1):
        r = _norm_rule({"id": f"legacy{i}", "name": f"迁移规则 {i}", "features": feats, "llm_id": lid})
        if r:
            rules.append(r)
    return rules


def normalize_routing(value: Any) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    if "rules" in data and isinstance(data.get("rules"), list):
        rules = [r for r in (_norm_rule(x) for x in data["rules"]) if r]
    else:
        rules = _migrate_legacy(data)
    seen: set[str] = set()
    for r in rules:
        while r["id"] in seen:
            r["id"] = uuid.uuid4().hex[:8]
        seen.add(r["id"])
    return {"default_llm": str(data.get("default_llm") or "").strip(), "rules": rules}


def get_routing() -> dict[str, Any]:
    try:
        from app.config_store import get_config_store

        return normalize_routing(get_config_store().get_raw().get("model_routing"))
    except Exception:
        return normalize_routing(None)


def _row_for_id(llm_id: str) -> dict[str, Any] | None:
    if not llm_id:
        return None
    try:
        from app.config_store import get_config_store

        row = get_config_store().get_llm(llm_id)
    except Exception:
        return None
    if not row or row.get("enabled", True) is False:
        return None
    return row


def match_rule(features: Iterable[str], routing: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """First enabled rule for the most specific feature that has one."""
    r = routing or get_routing()
    for f in features:
        if not f:
            continue
        for rule in r["rules"]:
            if rule["enabled"] and f in rule["features"] and _row_for_id(rule["llm_id"]):
                return rule
    return None


def routed_row(features: Iterable[str] | str, *, use_default: bool = True) -> dict[str, Any] | None:
    """LLM row routed for these features, else routing default_llm, else None."""
    feats = [features] if isinstance(features, str) else list(features)
    r = get_routing()
    rule = match_rule(feats, r)
    if rule:
        return _row_for_id(rule["llm_id"])
    if use_default:
        return _row_for_id(r.get("default_llm") or "")
    return None


def routed_client(
    features: Iterable[str] | str,
    *,
    fallback: Any = None,
    allow_cli: bool = True,
    use_default: bool = True,
):
    """Configured LLMClient for features, else ``fallback`` (default client)."""
    feats = [features] if isinstance(features, str) else list(features)
    row = routed_row(feats, use_default=use_default)
    if row is None:
        return fallback
    try:
        from app.llm.client import LLMClient

        cli = LLMClient.from_llm_config(row)
        if not allow_cli and getattr(cli, "is_cli", False):
            logger.info("Routed LLM %s for %s is CLI; skipped in tool loop", row.get("id"), feats)
            return fallback
        if cli.is_configured:
            logger.info("Model routing: %s -> %s", feats, row.get("id"))
            return cli
        logger.warning("Routed LLM %s for %s is incomplete; using default", row.get("id"), feats)
    except Exception:
        logger.exception("Failed to build routed LLM for %s", feats)
    return fallback