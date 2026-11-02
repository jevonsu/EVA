"""Resolve credentials without hardcoding secrets in skill handlers.

Priority (high → low):
  1. Explicit function arguments (when a tool accepts them)
  2. Environment variables
  3. data/config.json → integrations.*
  4. Default LLM entry from config store / Settings
"""

from __future__ import annotations

import os
from typing import Any


def _env(*keys: str, default: str = "") -> str:
    for k in keys:
        v = (os.environ.get(k) or "").strip()
        if v:
            return v
    return default


def _integrations() -> dict[str, Any]:
    try:
        from app.config_store import get_config_store

        raw = get_config_store().get_raw()
        integ = raw.get("integrations")
        return dict(integ) if isinstance(integ, dict) else {}
    except Exception:
        return {}


def _integ(section: str) -> dict[str, Any]:
    sec = _integrations().get(section)
    return dict(sec) if isinstance(sec, dict) else {}


def integration_config(section: str) -> dict[str, Any]:
    """Read one integrations.* row (skill handlers should use this, not hardcode)."""
    return _integ((section or "").strip())


def default_llm_credentials() -> dict[str, str]:
    """Return {base_url, api_key, model} from UI-configured default LLM only."""
    return llm_credentials("")


def llm_credentials(llm_id: str = "") -> dict[str, str]:
    """Read one 设定→LLM row for skill handlers. Empty id = default model.

    Never use integrations for chat-model keys. 业务连接（单一字段或 items 明细）才走 integration_config.
    """
    try:
        from app.config_store import get_config_store

        store = get_config_store()
        wanted = (llm_id or "").strip()
        row = None
        if not wanted:
            try:
                from app.llm.routing import routed_row

                row = routed_row("skill_handler")
            except Exception:
                row = None
        if row is None:
            row = store.get_llm(wanted) if wanted else store.get_default_llm()
        if not row and wanted:
            # allow lookup by name
            for item in store.list_llms():
                if str(item.get("name") or "").strip() == wanted:
                    row = item
                    break
        if row:
            out = _llm_row_creds(row)
            out["source"] = "llm"
            return out
    except Exception:
        pass
    return {
        "base_url": "",
        "api_key": "",
        "model": "",
        "name": "",
        "id": "",
        "source": "llm",
        "error": "未配置 LLM。请在设定 → LLM 添加模型，或对工具 llms 执行 upsert。",
    }


def list_llms_public() -> list[dict[str, Any]]:
    """Masked catalog of 设定→LLM rows for the agent (no raw keys)."""
    try:
        from app.config_store import get_config_store
        from app.services.model_meta import enrich_llm_public

        out: list[dict[str, Any]] = []
        for row in get_config_store().list_llms():
            pub = {
                "id": str(row.get("id") or ""),
                "name": str(row.get("name") or ""),
                "provider": str(row.get("provider") or ""),
                "model": str(row.get("model") or ""),
                "base_url": str(row.get("base_url") or ""),
                "enabled": bool(row.get("enabled", True)),
                "is_default": bool(row.get("is_default")),
                "api_key_set": bool(str(row.get("api_key") or "").strip()),
                "use_proxy": bool(row.get("use_proxy")),
            }
            out.append(enrich_llm_public(pub))
        return out
    except Exception:
        return []


def _llm_row_creds(llm: dict[str, Any]) -> dict[str, str]:
    return {
        "base_url": str(llm.get("base_url") or "").strip().rstrip("/"),
        "api_key": str(llm.get("api_key") or "").strip(),
        "model": str(llm.get("model") or "").strip(),
        "name": str(llm.get("name") or "").strip(),
        "id": str(llm.get("id") or "").strip(),
        "use_proxy": "1" if llm.get("use_proxy") else "",
    }


def looks_like_vision_model(model: str, *, base_url: str = "", name: str = "") -> bool:
    """Heuristic: model likely accepts image_url multimodal chat."""
    blob = f"{model} {name} {base_url}".lower()
    # Known text-only / non-vision chat APIs
    if "deepseek" in blob and "vl" not in blob and "vision" not in blob:
        return False
    positive = (
        "gemini",
        "gpt-4o",
        "gpt-4.1",
        "gpt-5",
        "gpt-4-turbo",
        "gpt-4-vision",
        "vision",
        "vl-",
        "-vl",
        "qwen-vl",
        "qwen2-vl",
        "qwen2.5-vl",
        "claude-3",
        "claude-4",
        "claude-sonnet",
        "claude-opus",
        "grok-2-vision",
        "grok-vision",
        # xAI Grok family (chat multimodal; best-effort — API may reject if model is text-only)
        "grok-4",
        "grok-3",
        "grok-2",
        "flash-lite",  # common gemini flash lite aliases on gateways
        "luna",  # gateway multimodal aliases (best-effort)
    )
    return any(p in blob for p in positive)


def _vision_rank(row: dict[str, Any]) -> int:
    """How clearly this row can do image understanding. Not default-LLM order."""
    m = f"{row.get('model', '')} {row.get('name', '')}".lower()
    s = 0
    if any(k in m for k in ("vision", "-vl", "vl-", "qwen-vl", "qwen2-vl", "qwen2.5-vl")):
        s += 50
    if any(
        k in m
        for k in (
            "gpt-4o",
            "gpt-4.1",
            "gpt-5",
            "gpt-4-turbo",
            "gpt-4-vision",
            "gemini",
            "claude-3",
            "claude-4",
            "claude-sonnet",
            "claude-opus",
        )
    ):
        s += 40
    if "grok" in m:
        s += 25
    return s


def list_vision_llms() -> list[dict[str, str]]:
    """Enabled 设定→LLM rows that accept image_url.

    Sorted by how clearly they support vision, never by is_default / list order.
    """
    try:
        from app.config_store import get_config_store

        rows = get_config_store().list_llms()
    except Exception:
        return []
    out: list[dict[str, str]] = []
    for r in rows:
        if not r.get("enabled", True):
            continue
        c = _llm_row_creds(r)
        if not c["api_key"] or not c["base_url"]:
            continue
        if not looks_like_vision_model(
            c["model"], base_url=c["base_url"], name=c["name"]
        ):
            continue
        c["source"] = f"llm:{c.get('id') or c.get('name') or c.get('model')}"
        c["_rank"] = str(_vision_rank(r))
        out.append(c)
    out.sort(key=lambda x: (-int(x.get("_rank") or 0), (x.get("name") or "").lower()))
    for c in out:
        c.pop("_rank", None)
    return out


def resolve_vision_llms(wanted: str = "") -> list[dict[str, str]]:
    """Try-list for识图: explicit 设定→LLM pick first, then other vision models.

    ``wanted`` matches id / 显示名 / model 字符串. Never falls back to the
    default chat model just because it is default.
    """
    vision = list_vision_llms()
    pick = (wanted or "").strip()
    if not pick:
        return vision

    try:
        from app.config_store import get_config_store

        rows = [
            r
            for r in get_config_store().list_llms()
            if r.get("enabled", True)
        ]
    except Exception:
        rows = []

    picked: dict[str, Any] | None = None
    low = pick.lower()
    for r in rows:
        if str(r.get("id") or "") == pick:
            picked = r
            break
    if picked is None:
        for r in rows:
            name = str(r.get("name") or "").strip()
            model = str(r.get("model") or "").strip()
            if name.lower() == low or model.lower() == low:
                picked = r
                break
    if picked is None:
        for r in rows:
            blob = f"{r.get('id', '')} {r.get('name', '')} {r.get('model', '')}".lower()
            if low in blob:
                picked = r
                break

    if picked is None:
        return []

    cred = _llm_row_creds(picked)
    cred["source"] = f"llm:{cred.get('id') or cred.get('name')}"
    if not looks_like_vision_model(
        cred["model"], base_url=cred["base_url"], name=cred["name"]
    ):
        cred["error"] = (
            f"「{cred.get('name') or cred.get('model') or pick}」看起来不支持识图，"
            "请换设定→LLM 里的多模态模型。"
        )
        return [cred]

    rest = [c for c in vision if c.get("id") and c.get("id") != cred.get("id")]
    return [cred] + rest


def vision_llm_credentials() -> dict[str, str]:
    """Vision skill LLM: only the row picked in 设定→集成→Vision.

    Never auto-picks default chat model or ranks 设定→模型.
    """
    return resolve_vision_skill_llm()


def resolve_vision_skill_llm() -> dict[str, str]:
    """Credentials for the Vision skill from integrations.vision.llm_id."""
    cfg = integration_config("vision")
    wanted = str(cfg.get("llm_id") or cfg.get("llm") or "").strip()
    empty = {
        "base_url": "",
        "api_key": "",
        "model": "",
        "name": "",
        "id": "",
        "source": "integration:vision",
        "integration_id": "vision",
        "hint": "设定→集成→Vision 识图",
    }
    if not wanted:
        empty["error"] = (
            "未配置识图模型。请到设定→集成选择 Vision 要使用的 LLM，不会自动取默认模型。"
        )
        return empty
    cred = llm_credentials(wanted)
    out = dict(cred)
    out["source"] = "integration:vision"
    out["integration_id"] = "vision"
    if not (out.get("base_url") or "").strip() or not (out.get("api_key") or "").strip():
        out["error"] = (
            out.get("error")
            or f"找不到或未配好模型「{wanted}」。请在设定→模型补全，再到集成里重选。"
        )
    return out


def http_network_config() -> dict[str, str]:
    """Proxy + FlareSolverr endpoints for the http skill."""
    sec = _integ("http")
    try:
        from app.config import get_settings

        s = get_settings()
        settings_proxy = (s.proxy_url or "").strip()
        settings_fs = (s.flaresolverr_url or "").strip()
    except Exception:
        settings_proxy = ""
        settings_fs = ""
    # Explicit PROXY_URL only — never inherit system HTTP_PROXY / HTTPS_PROXY
    proxy = _env(
        "PROXY_URL",
        default=str(sec.get("proxy_url") or settings_proxy or ""),
    )
    fs = _env(
        "FLARESOLVERR_URL",
        default=str(sec.get("flaresolverr_url") or settings_fs or ""),
    )
    return {"proxy_url": proxy.strip(), "flaresolverr_url": fs.strip()}


def missing_msg(service: str, keys: list[str]) -> str:
    env_hint = " / ".join(keys)
    return (
        f"{service} 未配置凭证。请在前端「设定 → 集成」填写，"
        f"或环境变量（{env_hint}）/ data/config.json → integrations；"
        f"勿把密钥写进 skill 代码。"
    )
