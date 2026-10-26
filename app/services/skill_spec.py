"""Skill intake spec: refuse vague create/update/delete until the user confirmed."""

from __future__ import annotations

import json
import re
from typing import Any

_VAGUE = frozenset(
    {
        "好",
        "行",
        "可以",
        "嗯",
        "哦",
        "ok",
        "okay",
        "yes",
        "y",
        "好的",
        "好呀",
        "行吧",
        "随便",
        "你看着办",
        "你决定",
        "默认",
        "随意",
        "都行",
        "没问题",
        "继续",
        "上吧",
        "搞",
        "做吧",
        "创建",
        "创建吧",
        "建",
        "建吧",
    }
)


def _s(v: Any) -> str:
    return str(v or "").strip()


def parse_spec_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            data = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}
    inputs = data.get("inputs")
    if not isinstance(inputs, list):
        inputs = []
    clean_inputs: list[dict[str, Any]] = []
    for item in inputs[:16]:
        if isinstance(item, dict):
            name = _s(item.get("name") or item.get("key"))
            if not name:
                continue
            clean_inputs.append(
                {
                    "name": name,
                    "type": _s(item.get("type")) or "string",
                    "example": _s(item.get("example")),
                    "required": bool(item.get("required", True)),
                    "note": _s(item.get("note")),
                }
            )
        elif isinstance(item, str) and item.strip():
            clean_inputs.append(
                {
                    "name": item.strip(),
                    "type": "string",
                    "example": "",
                    "required": True,
                    "note": "",
                }
            )
    return {
        "purpose": _s(data.get("purpose") or data.get("goal")),
        "trigger": _s(data.get("trigger") or data.get("how_to_call")),
        "inputs": clean_inputs,
        "success": _s(data.get("success")),
        "failure": _s(data.get("failure")),
        "integration_id": _s(data.get("integration_id") or data.get("integration")),
        "llm_id": _s(data.get("llm_id") or data.get("llm")),
        "no_params": bool(data.get("no_params")),
    }


_SPEC_CONFIRM = frozenset(
    {
        "确认",
        "确认创建",
        "确认新建",
        "确认，创建",
        "确认,创建",
        "按这个创建",
        "就按这个",
        "按这个来",
        "可以创建",
        "开始创建",
        "就这样创建",
        "按规格创建",
        "按这个做",
        "就这个",
        "没问题，创建",
        "没问题创建",
        "开始做",
        "就按这个来",
    }
)

_SPEC_CARD_MARKERS = (
    "技能规格卡",
    "【技能规格】",
    "规格确认",
    "规格卡",
    "确认，创建",
    "请确认两点",
    "请确认",
    "回复 **「确认",
    "回复「确认",
    "spec_card",
    "action_required",
    "功能范围 OK",
)


def _compact_confirm(text: str) -> str:
    t = _s(text).lower()
    for ch in ("！", "!", "。", ".", " ", "　", "\n", "\t"):
        t = t.replace(ch, "")
    return t


def is_spec_confirmation(text: str) -> bool:
    """User accepted a shown spec card (not a vague 好/行/随便)."""
    compact = _compact_confirm(text)
    if not compact:
        return False
    if compact in _SPEC_CONFIRM:
        return True
    if re.fullmatch(r"确认[，,]?(创建|新建|开工)?(吧)?", compact):
        return True
    return False


def has_spec_card(text: str) -> bool:
    t = text or ""
    return any(m in t for m in _SPEC_CARD_MARKERS)


def is_vague_confirmation(text: str) -> bool:
    if is_spec_confirmation(text):
        return False
    t = _s(text).lower()
    if not t:
        return True
    compact = t.replace("！", "").replace("!", "").replace("。", "").replace(".", "")
    compact = compact.replace(" ", "").replace("　", "")
    if compact in _VAGUE:
        return True
    if len(t) < 10 and compact in _VAGUE:
        return True
    if len(t) <= 4 and compact in {"好的", "可以", "行吧", "嗯嗯"}:
        return True
    return False


def spec_gaps(
    spec: dict[str, Any],
    *,
    description: str = "",
    how_to_call: str = "",
    spec_confirmed: bool = False,
    user_confirmation: str = "",
    is_update: bool = False,
) -> list[str]:
    gaps: list[str] = []
    if not spec_confirmed:
        gaps.append("尚未把规格卡给用户确认（spec_confirmed 必须为 true）")
    if is_vague_confirmation(user_confirmation):
        gaps.append(
            "用户确认太模糊（「好/行/随便/你看着办」不够）。"
            "请用户明确：用途、怎么喊、必填参数、缺配置怎么办"
        )
    purpose = spec.get("purpose") or _s(description)
    if len(purpose) < 12:
        gaps.append("缺少用途说明 purpose（做什么 / 不做什么）")
    trigger = spec.get("trigger") or _s(how_to_call)
    if len(trigger) < 4:
        gaps.append("缺少触发说法 trigger / how_to_call（用户以后怎么喊它）")
    if not spec.get("no_params") and not spec.get("inputs"):
        gaps.append(
            "未声明输入：列出 inputs[{name,type,example,required}]，"
            "或 spec.no_params=true 表示无需参数"
        )
    if not spec.get("success"):
        gaps.append("缺少成功长什么样 success")
    if not spec.get("failure"):
        gaps.append("缺少失败怎么说 failure")
    return gaps


def spec_card(spec: dict[str, Any], *, name: str = "") -> str:
    inputs = spec.get("inputs") or []
    if spec.get("no_params"):
        input_lines = "  （无需参数）"
    elif inputs:
        bits = []
        for i in inputs:
            req = "必填" if i.get("required") else "选填"
            ex = f"，例：{i['example']}" if i.get("example") else ""
            bits.append(f"  - {i['name']}（{i.get('type') or 'string'}，{req}{ex}）")
        input_lines = "\n".join(bits)
    else:
        input_lines = "  （未填写）"
    integ = spec.get("integration_id") or "无"
    llm = spec.get("llm_id") or "默认 LLM（设定→LLM）"
    return (
        f"【技能规格】{name or '（未命名）'}\n"
        f"- 用途：{spec.get('purpose') or '（未填写）'}\n"
        f"- 怎么喊：{spec.get('trigger') or '（未填写）'}\n"
        f"- 输入：\n{input_lines}\n"
        f"- 成功：{spec.get('success') or '（未填写）'}\n"
        f"- 失败：{spec.get('failure') or '（未填写）'}\n"
        f"- 对话模型：{llm}（供应商 key 只写设定→LLM，用工具 llms）\n"
        f"- 业务连接：{integ}（单一 url/token，或多记录 items，写设定→集成）\n"
        "请逐项确认或改正。仅回复「好/行/随便」不会创建。"
        "\n禁止把 DeepSeek/OpenAI/xAI 的 api_key 写进集成或技能代码。"
    )


_SECRET_LITERAL = re.compile(
    r"(?i)((api[_-]?key|password|passwd|secret|token|authorization)\s*[:=]\s*['\"][^'\"]{4,}['\"])"
    r"|(sk-[A-Za-z0-9]{12,})"
    r"|(Bearer\s+[A-Za-z0-9\-._~+/]{8,})"
)
_CONN_HINT = re.compile(
    r"(?i)(api[_-]?key|password|passwd|secret|token|base_url|endpoint|"
    r"账号|密码|密钥|主机|host\b|授权)"
)


_HOST_SPOOF = re.compile(
    r"(?is)(skip_host\s*=\s*True"
    r"|FAKE_HOST"
    r"|putheader\(\s*['\"]Host['\"]"
    r"|['\"]Host['\"]\s*:\s*['\"]localhost['\"]"
    r"|Host\s*=\s*['\"]localhost['\"])",
)


def connection_hacks_in_text(text: str) -> list[str]:
    """Refuse LLM 'fixes' that spoof Host / treat 502 as a code bug."""
    blob = text or ""
    hits: list[str] = []
    if _HOST_SPOOF.search(blob):
        hits.append(
            "禁止伪造 Host/localhost（skip_host、FAKE_HOST、putheader Host）。"
            "局域网服务用 app.services.skill_http.request，"
            "base_url 只来自 integration_config()。"
            "502 是网关问题，不要靠改技能代码硬扛。"
        )
    return hits


def leaked_secrets_in_text(text: str, extra_values: list[str] | None = None) -> list[str]:
    hits: list[str] = []
    blob = text or ""
    if _SECRET_LITERAL.search(blob):
        hits.append("技能代码/描述里出现了明文 password / token / api_key / sk-…")
    for v in extra_values or []:
        s = str(v or "").strip()
        if len(s) >= 6 and s in blob:
            hits.append("技能文件里出现了应写入「设定→LLM」或「设定→集成」的密钥原文")
            break
    return hits


_LLM_HINT = re.compile(
    r"(?i)(\bllm\b|大模型|对话模型|chat.?complet|openai|deepseek|anthropic|"
    r"\bxai\b|\bgrok\b|openrouter|ollama|gemini|"
    r"设定.?llm|模型列表|api\.openai|api\.x\.ai|api\.deepseek)"
)
_LLM_URL_HINT = (
    "openai.com",
    "api.x.ai",
    "deepseek.com",
    "openrouter.ai",
    "anthropic.com",
    "googleapis.com/v1beta",
    "api.groq.com",
)
_LLM_PROVIDERS = frozenset(
    {
        "openai",
        "xai",
        "deepseek",
        "anthropic",
        "grok",
        "ollama",
        "gemini",
        "openrouter",
        "groq",
        "custom",
    }
)
_LLM_FIELD_KEYS = frozenset(
    {
        "base_url",
        "api_key",
        "api-key",
        "apikey",
        "model",
        "provider",
        "is_default",
        "use_proxy",
        "llm_id",
        "enabled",
    }
)
_HOST_FIELD_KEYS = frozenset(
    {
        "host",
        "hostname",
        "user",
        "username",
        "password",
        "port",
        "share",
        "smb",
        "ssh",
        "hosts",
        "hosts_json",
    }
)


def _spec_blob(spec: dict[str, Any], description: str, handler_code: str) -> str:
    return " ".join(
        [
            _s(spec.get("purpose")),
            _s(spec.get("failure")),
            _s(description),
            _s(handler_code)[:2000],
        ]
    )


def looks_like_llm_fields(fields: dict[str, Any] | None) -> bool:
    """True when the payload is a chat-model credential, not a host/API row."""
    if not isinstance(fields, dict) or not fields:
        return False
    keys = {str(k).lower() for k in fields}
    if keys & _HOST_FIELD_KEYS:
        return False
    if "model" in keys and (keys & {"api_key", "api-key", "apikey", "base_url"}):
        return True
    provider = _s(fields.get("provider")).lower()
    if provider in _LLM_PROVIDERS:
        return True
    url = _s(fields.get("base_url") or fields.get("url")).lower()
    if any(h in url for h in _LLM_URL_HINT):
        return True
    return False


def looks_like_needs_llm(
    spec: dict[str, Any], description: str = "", handler_code: str = ""
) -> bool:
    if _s(spec.get("llm_id")):
        return True
    blob = _spec_blob(spec, description, handler_code)
    return bool(_LLM_HINT.search(blob))


def looks_like_needs_integration(spec: dict[str, Any], description: str, handler_code: str) -> bool:
    if _s(spec.get("integration_id")):
        return True
    blob = _spec_blob(spec, description, handler_code)
    if not _CONN_HINT.search(blob):
        return False
    # Chat-model keys belong in 设定→LLM, not 集成
    if looks_like_needs_llm(spec, description, handler_code) and not (
        _HOST_HINT.search(blob)
    ):
        return False
    return True


_HOST_HINT = re.compile(
    r"(?i)(\bhost\b|主机|nas|smb|ssh|ftp|共享盘|账号|username|webhook|smtp)"
)


def fields_to_llm_payload(fields: dict[str, Any], *, llm_id: str = "") -> dict[str, Any]:
    """Map free-form user fields onto a 设定→LLM row."""
    src = {str(k).strip(): v for k, v in (fields or {}).items()}
    key = _s(src.get("api_key") or src.get("api-key") or src.get("apikey") or src.get("key"))
    payload: dict[str, Any] = {
        "id": _s(llm_id or src.get("id") or src.get("llm_id")) or None,
        "name": _s(src.get("name")) or _s(src.get("model")) or "LLM",
        "provider": (_s(src.get("provider")) or "custom").lower(),
        "base_url": _s(src.get("base_url") or src.get("url")).rstrip("/"),
        "api_key": key,
        "model": _s(src.get("model")),
        "enabled": bool(src.get("enabled", True)),
        "is_default": bool(src.get("is_default", False)),
        "use_proxy": bool(src.get("use_proxy", False)),
    }
    if not payload["id"]:
        payload.pop("id", None)
    return payload


def resolve_skill_integration_id(
    skill_id: str,
    spec: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    sid = _s(skill_id)
    spec = spec or {}
    metadata = metadata or {}
    for cand in (
        _s(spec.get("integration_id")),
        _s(metadata.get("integration_id")),
    ):
        if cand:
            return cand
    try:
        from app.services.integrations_meta import skill_to_integration

        mapped = skill_to_integration().get(sid)
        if mapped:
            return str(mapped)
    except Exception:
        pass
    try:
        from app.config_store import get_config_store

        raw = get_config_store().get_integrations_raw()
        if sid in raw:
            return sid
    except Exception:
        pass
    return ""


def skill_integration_view(skill_id: str, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """Masked integration summary for LLM + UI (never raw secrets)."""
    spec = spec or {}
    iid = resolve_skill_integration_id(skill_id, spec, spec)
    if not iid:
        meta_iid = _s((spec or {}).get("integration_id"))
        iid = meta_iid
    if not iid:
        return {
            "id": "",
            "linked": False,
            "status": "",
            "hint": "此技能未绑定集成。连接信息应写入设定→集成。",
        }
    try:
        from app.config_store import get_config_store

        pub = get_config_store().get_integration_public(iid)
    except Exception:
        pub = None
    if not pub:
        return {
            "id": iid,
            "linked": True,
            "status": "missing",
            "hint": f"集成 [{iid}] 还不存在。把 URL/账号/token（或多记录 items）放进 integration_fields_json，或到设定→集成新建。",
        }
    return {
        "id": iid,
        "linked": True,
        "name": pub.get("name") or iid,
        "status": pub.get("status") or "empty",
        "config": pub.get("config") or {},
        "secrets": pub.get("secrets") or {},
        "fields": [
            {
                "key": f.get("key"),
                "label": f.get("label") or f.get("key"),
                "secret": bool(f.get("secret")),
            }
            for f in (pub.get("fields") or [])
            if isinstance(f, dict) and f.get("key")
        ],
        "hint": (
            "用户可在设定→集成修改这些值；技能代码只能用 "
            f"integration_config({iid!r}) 读取，禁止把密钥写进 handler。"
        ),
    }


def usage_card(
    *,
    name: str,
    spec: dict[str, Any],
    ready: bool,
    stage: str,
    integration_id: str = "",
    integration_status: str = "",
) -> dict[str, Any]:
    trigger = spec.get("trigger") or f"请用工具 {name}"
    example: dict[str, Any] = {}
    for i in spec.get("inputs") or []:
        if i.get("required") or i.get("example"):
            example[i["name"]] = i.get("example") or f"<{i['name']}>"
    if stage != "live":
        tell = f"技能仍在草稿（{stage}），对话里还不能直接调用。需要先发布到 live。"
    elif not ready:
        tell = (
            f"技能已写入，但集成「{integration_id or '?'}」未就绪"
            f"（{integration_status or 'empty'}）。"
            "请先到设定 → 集成填写，填完再说一次即可调用。"
        )
    else:
        args = "、".join(
            f"{i['name']}" + ("（必填）" if i.get("required") else "")
            for i in (spec.get("inputs") or [])
        )
        extra = f" 需要：{args}。" if args else ""
        tell = f"已经可以用。下次直接说：「{trigger}」。{extra}".strip()
    return {
        "call_name": name,
        "how_to_call": trigger,
        "example_args": example,
        "ready": ready,
        "stage": stage,
        "tell_user": tell,
        "integration_id": integration_id or spec.get("integration_id") or "",
        "integration_status": integration_status,
    }


def integration_status(integration_id: str) -> tuple[str, str]:
    iid = _s(integration_id)
    if not iid:
        return "", ""
    try:
        from app.config_store import get_config_store
        from app.services.integrations_meta import OPTIONAL_INTEGRATIONS

        pub = get_config_store().get_integration_public(iid)
        if not pub:
            if iid in OPTIONAL_INTEGRATIONS:
                return iid, "ready"
            return iid, "missing"
        st = str(pub.get("status") or "empty")
        if iid in OPTIONAL_INTEGRATIONS and st in ("", "empty", "missing", "unknown"):
            return iid, "ready"
        return iid, st
    except Exception:
        return iid, "unknown"


def refuse_payload(
    *,
    name: str,
    spec: dict[str, Any],
    gaps: list[str],
    is_update: bool = False,
    is_delete: bool = False,
) -> dict[str, Any]:
    verb = "删除" if is_delete else ("更新" if is_update else "创建")
    return {
        "ok": False,
        "error": f"规格未确认，不能{verb}技能",
        "action_required": "confirm_spec",
        "gaps": gaps,
        "spec": spec,
        "spec_card": spec_card(spec, name=name),
        "hint": (
            "先把 spec_card 原文发给用户，等他们补全并明确确认后，"
            "再带 spec_confirmed=true、user_confirmation=用户原话、完整 spec_json 重试。"
        ),
    }
