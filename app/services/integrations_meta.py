"""Integration catalog: schemas for frontend forms + skill linkage."""

from __future__ import annotations

from typing import Any

# Field: key, label, type (text|password|number|url), optional, placeholder, secret
INTEGRATION_CATALOG: dict[str, dict[str, Any]] = {
    "http": {
        "id": "http",
        "name": "HTTP 网络",
        "description": "全局代理与 FlareSolverr，供 http / 网页抓取类技能使用。",
        "icon": "connection",
        "skills": ["http", "search_web", "search_ai_news"],
        "builtin": True,
        "fields": [
            {
                "key": "proxy_url",
                "label": "HTTP 代理",
                "type": "url",
                "secret": False,
                "placeholder": "http://127.0.0.1:7890",
                "hint": "可空。环境变量 PROXY_URL 优先级更高。",
            },
            {
                "key": "flaresolverr_url",
                "label": "FlareSolverr URL",
                "type": "url",
                "secret": False,
                "placeholder": "http://127.0.0.1:8191/v1",
            },
        ],
        "defaults": {
            "proxy_url": "",
            "flaresolverr_url": "http://127.0.0.1:8191/v1",
        },
    },
    "nas": {
        "id": "nas",
        "name": "NAS / SMB",
        "description": "局域网共享盘，供 nas 技能与媒体预览使用。",
        "icon": "hard-disk",
        "skills": ["nas"],
        "builtin": True,
        "fields": [
            {
                "key": "host",
                "label": "主机",
                "type": "text",
                "secret": False,
                "placeholder": "192.168.1.100",
            },
            {
                "key": "port",
                "label": "端口",
                "type": "number",
                "secret": False,
                "placeholder": "445",
            },
            {
                "key": "user",
                "label": "用户名",
                "type": "text",
                "secret": False,
                "placeholder": "admin",
            },
            {
                "key": "password",
                "label": "密码",
                "type": "password",
                "secret": True,
                "placeholder": "留空表示不修改已有密码",
            },
        ],
        "defaults": {"host": "", "user": "", "password": "", "port": 445},
        "required_for_ready": ["host", "user"],
    },
    "nocodb": {
        "id": "nocodb",
        "name": "NocoDB",
        "description": "表格/数据库 API，供 nocodb 技能增删改查。",
        "icon": "table",
        "skills": ["nocodb"],
        "builtin": True,
        "fields": [
            {
                "key": "base_url",
                "label": "Base URL",
                "type": "url",
                "secret": False,
                "placeholder": "http://192.168.1.100:8080",
            },
            {
                "key": "email",
                "label": "邮箱 / 账号",
                "type": "text",
                "secret": False,
                "placeholder": "admin@example.com",
            },
            {
                "key": "password",
                "label": "密码",
                "type": "password",
                "secret": True,
                "placeholder": "留空表示不修改",
            },
            {
                "key": "token",
                "label": "API Token",
                "type": "password",
                "secret": True,
                "placeholder": "可选；有 token 时优先于账号密码",
            },
        ],
        "defaults": {"base_url": "", "email": "", "password": "", "token": ""},
        "required_for_ready": ["base_url"],
        "ready_any_secret": ["password", "token"],
    },
    "qbittorrent": {
        "id": "qbittorrent",
        "name": "qBittorrent",
        "description": "下载客户端 WebUI，供 qb_manager 技能使用。",
        "icon": "download",
        "skills": ["qb_manager"],
        "builtin": True,
        "fields": [
            {
                "key": "base_url",
                "label": "Base URL",
                "type": "url",
                "secret": False,
                "placeholder": "http://192.168.1.100:8080",
            },
            {
                "key": "user",
                "label": "用户名",
                "type": "text",
                "secret": False,
                "placeholder": "admin",
            },
            {
                "key": "password",
                "label": "密码",
                "type": "password",
                "secret": True,
                "placeholder": "留空表示不修改",
            },
        ],
        "defaults": {"base_url": "", "user": "", "password": ""},
        "required_for_ready": ["base_url", "user"],
    },
    "netops": {
        "id": "netops",
        "name": "NetOps 主机表",
        "description": "网络运维主机/SSH：给每台机器起配置名（如 nas），供 netops 技能 ping/ssh/scp/status。"
        "密钥只存在集成里，勿写入 skill 或知识库。",
        "icon": "network-tree",
        "skills": ["netops"],
        "builtin": True,
        "fields": [
            {
                "key": "hosts",
                "label": "主机列表",
                "type": "hosts_table",
                "secret": False,
                "hint": "配置名用于 netops 参数 host=nas；检测端口用于 status 批量体检。",
            },
            {
                "key": "default_ssh_password",
                "label": "默认 SSH 密码",
                "type": "password",
                "secret": True,
                "placeholder": "留空不修改；单机未填密码时使用",
                "hint": "也可用环境变量 NETOPS_SSH_PASSWORD。",
            },
        ],
        "defaults": {"hosts": {}, "default_ssh_password": ""},
        "required_for_ready": [],
    },
}

SECRET_KEY_RE = ("password", "token", "secret", "api_key", "pass")


def is_secret_key(key: str) -> bool:
    k = (key or "").lower()
    return any(s in k for s in SECRET_KEY_RE)


def catalog_list() -> list[dict[str, Any]]:
    return [dict(v) for v in INTEGRATION_CATALOG.values()]


def get_schema(integration_id: str) -> dict[str, Any] | None:
    return INTEGRATION_CATALOG.get((integration_id or "").strip())


def defaults_for(integration_id: str) -> dict[str, Any]:
    schema = get_schema(integration_id)
    if schema:
        return dict(schema.get("defaults") or {})
    return {}


def skill_to_integration() -> dict[str, str]:
    """skill_id → integration_id (first match)."""
    out: dict[str, str] = {}
    for iid, meta in INTEGRATION_CATALOG.items():
        for sid in meta.get("skills") or []:
            out.setdefault(str(sid), iid)
    return out


def public_row(
    integration_id: str,
    raw: dict[str, Any] | None,
    *,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mask secrets; add *_set and configured flag."""
    schema = schema or get_schema(integration_id) or {
        "id": integration_id,
        "name": integration_id,
        "description": "自定义集成",
        "icon": "api",
        "skills": [],
        "builtin": False,
        "fields": [
            {"key": k, "label": k, "type": "password" if is_secret_key(k) else "text", "secret": is_secret_key(k)}
            for k in (raw or {})
        ],
        "defaults": {},
    }
    data = dict(schema.get("defaults") or {})
    if isinstance(raw, dict):
        data.update(raw)

    def _scrub_hosts(hosts_obj: Any) -> dict[str, Any]:
        """Strip nested SSH passwords; record per-host password_set flags."""
        out: dict[str, Any] = {}
        if not isinstance(hosts_obj, dict):
            return out
        for hn, hc in hosts_obj.items():
            name = str(hn)
            if not isinstance(hc, dict):
                out[name] = {"host": str(hc or "")}
                continue
            row = {
                "host": str(hc.get("host") or ""),
                "user": str(hc.get("user") or ""),
                "port": hc.get("port") if hc.get("port") is not None else 22,
                "key_path": str(hc.get("key_path") or ""),
                "ports": hc.get("ports") if isinstance(hc.get("ports"), list) else [],
                "password": "",
            }
            try:
                row["port"] = int(row["port"] or 22)
            except (TypeError, ValueError):
                row["port"] = 22
            has_pw = bool(str(hc.get("password") or "").strip())
            secrets_set[f"host_password_set.{name}"] = has_pw
            out[name] = row
        return out

    def _hosts_from_data(blob: dict[str, Any]) -> dict[str, Any]:
        h = blob.get("hosts")
        if isinstance(h, dict) and h:
            return h
        hj = blob.get("hosts_json")
        if isinstance(hj, str) and hj.strip():
            import json as _json

            try:
                parsed = _json.loads(hj)
                if isinstance(parsed, dict):
                    if isinstance(parsed.get("hosts"), dict):
                        return parsed["hosts"]
                    return parsed
            except Exception:
                pass
        return {}

    config: dict[str, Any] = {}
    secrets_set: dict[str, bool] = {}
    for k, v in data.items():
        if k in ("hosts", "hosts_json"):
            continue  # handled below as scrubbed hosts table
        if is_secret_key(k):
            has = bool(str(v or "").strip())
            secrets_set[f"{k}_set"] = has
            config[k] = ""  # never send raw secret to frontend list
            # editor will get empty + *_set via same flags
        else:
            config[k] = v

    # Always expose structured hosts for UI (netops + any integration using hosts_table)
    scrubbed_hosts = _scrub_hosts(_hosts_from_data(data))
    if scrubbed_hosts or any(
        (f.get("type") == "hosts_table" or f.get("key") in ("hosts", "hosts_json"))
        for f in (schema.get("fields") or [])
        if isinstance(f, dict)
    ):
        config["hosts"] = scrubbed_hosts
        # keep hosts_json out of editor primary path (table UI only)

    # configured / ready
    required = list(schema.get("required_for_ready") or [])
    ready = True
    if required:
        for rk in required:
            if not str(config.get(rk) or data.get(rk) or "").strip():
                # secret required fields
                if is_secret_key(rk):
                    if not secrets_set.get(f"{rk}_set"):
                        ready = False
                        break
                else:
                    ready = False
                    break
    any_sec = schema.get("ready_any_secret") or []
    if ready and any_sec:
        if not any(secrets_set.get(f"{s}_set") for s in any_sec):
            # nocodb: allow base_url only if token or password set — warn soft
            # if base_url set but no auth, still "partial"
            ready = any(secrets_set.get(f"{s}_set") for s in any_sec) or bool(
                str(config.get("base_url") or "").strip()
            )
            # mark partial separately
    has_any = False
    if scrubbed_hosts:
        has_any = True
    for k, v in data.items():
        if k in ("hosts", "hosts_json"):
            continue
        if is_secret_key(k):
            if str(v or "").strip():
                has_any = True
        elif str(v or "").strip() and str(v) not in ("445", "{}", "null"):
            has_any = True

    status = "empty"
    if has_any:
        status = "ready" if ready else "partial"

    return {
        "id": integration_id,
        "name": schema.get("name") or integration_id,
        "description": schema.get("description") or "",
        "icon": schema.get("icon") or "api",
        "skills": list(schema.get("skills") or []),
        "builtin": bool(schema.get("builtin")),
        "fields": list(schema.get("fields") or []),
        "config": config,
        "secrets": secrets_set,
        "status": status,
        "configured": status in ("ready", "partial"),
    }
