"""Resolve credentials without hardcoding secrets in skill handlers.

Priority (high → low):
  1. Explicit function arguments (when a tool accepts them)
  2. Environment variables
  3. data/config.json → integrations.*
  4. Default LLM entry from config store / Settings
"""

from __future__ import annotations

import os
import re
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


def default_llm_credentials() -> dict[str, str]:
    """Return {base_url, api_key, model} for OpenAI-compatible APIs."""
    try:
        from app.config_store import get_config_store

        llm = get_config_store().get_default_llm()
        if llm:
            return {
                "base_url": str(llm.get("base_url") or "").strip().rstrip("/"),
                "api_key": str(llm.get("api_key") or "").strip(),
                "model": str(llm.get("model") or "").strip(),
            }
    except Exception:
        pass
    try:
        from app.config import get_settings

        s = get_settings()
        return {
            "base_url": (s.llm_base_url or "").strip().rstrip("/"),
            "api_key": (s.llm_api_key or "").strip(),
            "model": (s.llm_model or "").strip(),
        }
    except Exception:
        return {"base_url": "", "api_key": "", "model": ""}


def _llm_row_creds(llm: dict[str, Any]) -> dict[str, str]:
    return {
        "base_url": str(llm.get("base_url") or "").strip().rstrip("/"),
        "api_key": str(llm.get("api_key") or "").strip(),
        "model": str(llm.get("model") or "").strip(),
        "name": str(llm.get("name") or "").strip(),
        "id": str(llm.get("id") or "").strip(),
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


def vision_llm_credentials() -> dict[str, str]:
    """Credentials for product vision / image analysis.

    Priority:
      1. VISION_API_KEY / VISION_BASE_URL / VISION_MODEL env
      2. integrations.vision {base_url, api_key, model, llm_id}
      3. Enabled LLM whose model/name looks vision-capable (prefer GPT)
      4. Default LLM only if it looks vision-capable
    """
    env_key = _env("VISION_API_KEY", "VISION_KEY")
    env_url = _env("VISION_BASE_URL", "VISION_API_BASE")
    env_model = _env("VISION_MODEL")
    if env_key and env_url:
        return {
            "base_url": env_url.rstrip("/"),
            "api_key": env_key,
            "model": env_model or "gpt-4o",
            "source": "env",
        }

    sec = _integ("vision")
    if sec:
        llm_id = str(sec.get("llm_id") or "").strip()
        if llm_id:
            try:
                from app.config_store import get_config_store

                for row in get_config_store().get_raw().get("llms") or []:
                    if str(row.get("id")) == llm_id and row.get("enabled", True):
                        c = _llm_row_creds(row)
                        if c["api_key"] and c["base_url"]:
                            c["source"] = f"integrations.vision.llm_id:{llm_id}"
                            return c
            except Exception:
                pass
        base_url = str(sec.get("base_url") or "").strip().rstrip("/")
        api_key = str(sec.get("api_key") or "").strip()
        model = str(sec.get("model") or "").strip()
        if base_url and api_key:
            return {
                "base_url": base_url,
                "api_key": api_key,
                "model": model or "gpt-4o",
                "source": "integrations.vision",
            }

    # Scan configured LLMs
    try:
        from app.config_store import get_config_store

        rows = [
            r
            for r in (get_config_store().get_raw().get("llms") or [])
            if r.get("enabled", True)
            and str(r.get("api_key") or "").strip()
            and str(r.get("base_url") or "").strip()
        ]
        vision_rows = [
            r
            for r in rows
            if looks_like_vision_model(
                str(r.get("model") or ""),
                base_url=str(r.get("base_url") or ""),
                name=str(r.get("name") or ""),
            )
        ]
        # Prefer GPT / OpenAI-compatible vision names (over Gemini)
        def _score(r: dict[str, Any]) -> int:
            m = f"{r.get('model','')} {r.get('name','')}".lower()
            s = 0
            if "gpt-4o" in m or "gpt-5" in m or "gpt-4.1" in m or "gpt-4-turbo" in m:
                s += 40
            elif re.search(r"\bgpt\b", m) or m.strip().startswith("gpt"):
                s += 35
            if "vision" in m or "vl" in m or "luna" in m:
                s += 20
            if "gemini" in m:
                s += 10  # still vision-capable, but below GPT
            if r.get("is_default"):
                s += 5
            return s

        vision_rows.sort(key=_score, reverse=True)
        if vision_rows:
            c = _llm_row_creds(vision_rows[0])
            c["source"] = f"llm:{c.get('id') or c.get('name') or c.get('model')}"
            return c
    except Exception:
        pass

    # Default only if it can do vision
    d = default_llm_credentials()
    if d.get("api_key") and d.get("base_url") and looks_like_vision_model(
        d.get("model") or "", base_url=d.get("base_url") or ""
    ):
        d["source"] = "default_llm"
        return d

    return {
        "base_url": "",
        "api_key": "",
        "model": "",
        "source": "none",
        "hint": (
            "未找到支持识图的 LLM。当前默认模型可能不支持 image_url。"
            "请在设定中启用 Gemini/GPT-4o 等 Vision 模型，"
            "或设置环境变量 VISION_BASE_URL / VISION_API_KEY / VISION_MODEL，"
            "或在 integrations.vision 中配置。"
        ),
    }


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
    proxy = _env(
        "PROXY_URL",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        default=str(sec.get("proxy_url") or settings_proxy or ""),
    )
    fs = _env(
        "FLARESOLVERR_URL",
        default=str(
            sec.get("flaresolverr_url")
            or settings_fs
            or "http://127.0.0.1:8191/v1"
        ),
    )
    return {"proxy_url": proxy.strip(), "flaresolverr_url": fs.strip()}


def nas_config() -> dict[str, Any]:
    sec = _integ("nas")
    return {
        "host": _env("NAS_HOST", default=str(sec.get("host") or "")),
        "user": _env("NAS_USER", default=str(sec.get("user") or "")),
        "password": _env("NAS_PASSWORD", "NAS_PASS", default=str(sec.get("password") or "")),
        "port": int(_env("NAS_PORT", default=str(sec.get("port") or "445")) or 445),
    }


def nocodb_config() -> dict[str, str]:
    sec = _integ("nocodb")
    return {
        "base_url": _env("NOCODB_URL", "NOCODB_BASE_URL", default=str(sec.get("base_url") or "")).rstrip("/"),
        "email": _env("NOCODB_EMAIL", default=str(sec.get("email") or "")),
        "password": _env("NOCODB_PASSWORD", default=str(sec.get("password") or "")),
        "token": _env("NOCODB_TOKEN", default=str(sec.get("token") or "")),
    }


def qb_config() -> dict[str, str]:
    sec = _integ("qbittorrent")
    return {
        "base_url": _env("QB_URL", "QBITTORRENT_URL", default=str(sec.get("base_url") or "")).rstrip("/"),
        "user": _env("QB_USER", "QBITTORRENT_USER", default=str(sec.get("user") or "")),
        "password": _env(
            "QB_PASSWORD",
            "QB_PASS",
            "QBITTORRENT_PASSWORD",
            default=str(sec.get("password") or ""),
        ),
    }


def netops_config() -> dict[str, Any]:
    """NetOps hosts table from integrations.netops (fallback: skill-local JSON).

    Returns ``{"hosts": {name: {host,user,port,password,key_path,ports}, ...},
               "default_ssh_password": str, "source": str}``.
    """
    import json
    from pathlib import Path

    sec = _integ("netops")
    hosts: dict[str, Any] = {}
    source = "empty"

    raw_hosts = sec.get("hosts")
    if isinstance(raw_hosts, dict) and raw_hosts:
        hosts = {str(k): dict(v) if isinstance(v, dict) else {"host": str(v)} for k, v in raw_hosts.items()}
        source = "integrations.netops.hosts"
    else:
        hj = sec.get("hosts_json")
        if isinstance(hj, str) and hj.strip():
            try:
                parsed = json.loads(hj)
                if isinstance(parsed, dict):
                    if isinstance(parsed.get("hosts"), dict):
                        hosts = {
                            str(k): dict(v) if isinstance(v, dict) else {"host": str(v)}
                            for k, v in parsed["hosts"].items()
                        }
                    else:
                        hosts = {
                            str(k): dict(v) if isinstance(v, dict) else {"host": str(v)}
                            for k, v in parsed.items()
                            if isinstance(v, (dict, str))
                        }
                    source = "integrations.netops.hosts_json"
            except Exception:
                pass

    if not hosts:
        # Legacy fallback: skills/netops/netops_config.json
        try:
            from app.services.skills import skills_root

            path = skills_root() / "netops" / "netops_config.json"
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                h = data.get("hosts") if isinstance(data, dict) else None
                if isinstance(h, dict) and h:
                    hosts = {
                        str(k): dict(v) if isinstance(v, dict) else {"host": str(v)}
                        for k, v in h.items()
                    }
                    source = "skills/netops/netops_config.json"
        except Exception:
            pass

    default_pw = _env(
        "NETOPS_SSH_PASSWORD",
        "NETOPS_PASSWORD",
        default=str(sec.get("default_ssh_password") or sec.get("password") or ""),
    )
    # Fill empty per-host passwords with default
    if default_pw:
        for _name, conf in list(hosts.items()):
            if isinstance(conf, dict) and not str(conf.get("password") or "").strip():
                conf = dict(conf)
                conf["password"] = default_pw
                hosts[_name] = conf

    return {
        "hosts": hosts,
        "default_ssh_password": default_pw,
        "source": source,
    }


def missing_msg(service: str, keys: list[str]) -> str:
    env_hint = " / ".join(keys)
    return (
        f"{service} 未配置凭证。请在前端「设定 → 集成」填写，"
        f"或环境变量（{env_hint}）/ data/config.json → integrations；"
        f"勿把密钥写进 skill 代码。"
    )
