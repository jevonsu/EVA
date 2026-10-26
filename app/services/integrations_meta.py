"""Integration catalog: schemas for frontend forms + skill linkage."""

from __future__ import annotations

import json
import re
from typing import Any

# Field: key, label, type (text|password|number|url), optional, placeholder, secret
INTEGRATION_CATALOG: dict[str, dict[str, Any]] = {
    "http": {
        "id": "http",
        "name": "HTTP 网络",
        "description": "全局代理与 FlareSolverr。",
        "icon": "connection",
        "skills": [],
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
            "flaresolverr_url": "",
        },
    },
}

SECRET_KEY_RE = ("password", "token", "secret", "api_key", "pass")


def is_secret_key(key: str) -> bool:
    k = (key or "").lower().strip()
    if k in ("key", "api_key", "apikey", "access_key", "secret_key", "token", "password", "secret"):
        return True
    return any(s in k for s in SECRET_KEY_RE)


def catalog_list() -> list[dict[str, Any]]:
    return [dict(v) for v in INTEGRATION_CATALOG.values()]


_ROW_META_KEYS = frozenset({"_schema", "_label", "_description", "_skills"})

# Global HTTP proxy — skills may link it, but empty is OK (直连).
OPTIONAL_INTEGRATIONS = frozenset({"http"})


def stored_schema(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Schema stashed on a custom integration row (from skill import or builder)."""
    if not isinstance(raw, dict):
        return None
    sch = raw.get("_schema")
    if not isinstance(sch, dict):
        return None
    fields = sch.get("fields")
    layout = str(sch.get("layout") or "").strip()
    if not isinstance(fields, list) and layout not in ("single", "content"):
        return None
    out = dict(sch)
    if not isinstance(out.get("fields"), list):
        out["fields"] = []
    if raw.get("_label") and not out.get("name"):
        out["name"] = str(raw["_label"])
    if raw.get("_description") and not out.get("description"):
        out["description"] = str(raw["_description"])
    skills = raw.get("_skills")
    if isinstance(skills, list) and "skills" not in out:
        out["skills"] = [str(s) for s in skills if str(s).strip()]
    return out


def get_schema(
    integration_id: str, raw: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    iid = (integration_id or "").strip()
    cat = INTEGRATION_CATALOG.get(iid)
    if cat:
        return dict(cat)
    return stored_schema(raw)


DEFAULT_ITEM_COLUMNS: list[dict[str, str]] = [
    {"key": "name", "label": "名称", "type": "text"},
    {"key": "content", "label": "内容", "type": "text"},
    {"key": "note", "label": "备注", "type": "text"},
]

ITEM_COLUMNS_BY_ID: dict[str, list[dict[str, str]]] = {}

_RECORD_KEY_RE = re.compile(r"^(group|member|bot)\d*_", re.I)
_SIMPLE_FIELD_META: dict[str, tuple[str, str]] = {
    "url": ("地址", "url"),
    "base_url": ("服务地址", "url"),
    "rpc_url": ("RPC 地址", "url"),
    "host": ("主机", "text"),
    "port": ("端口", "number"),
    "user": ("用户名", "text"),
    "username": ("用户名", "text"),
    "email": ("邮箱", "text"),
    "password": ("密码", "password"),
    "token": ("Token", "password"),
    "api_key": ("API Key", "password"),
    "key": ("密钥", "password"),
    "rpc_secret": ("RPC 密钥", "password"),
}


def is_record_key(key: str) -> bool:
    """Keys that belong in a content table, not connection fields."""
    k = str(key or "").strip()
    if k in ("items", "groups", "members", "hosts", "hosts_json"):
        return True
    return bool(_RECORD_KEY_RE.match(k))


def items_table_field(iid: str = "") -> dict[str, Any]:
    cols = ITEM_COLUMNS_BY_ID.get(iid) or DEFAULT_ITEM_COLUMNS
    hint = "每行一条明细，技能用 items 读取。"
    return {
        "key": "items",
        "label": "明细",
        "type": "items_table",
        "columns": [dict(c) for c in cols],
        "hint": hint,
    }


def simple_field(key: str) -> dict[str, Any]:
    k = str(key or "").strip()
    label, typ = _SIMPLE_FIELD_META.get(k, (k, "password" if is_secret_key(k) else "text"))
    secret = is_secret_key(k) or typ == "password"
    return {
        "key": k,
        "label": label,
        "type": "password" if secret else typ,
        "secret": secret,
    }


def _merge_skill_ids(*groups: Any) -> list[str]:
    out: list[str] = []
    for src in groups:
        if isinstance(src, str):
            src = [src]
        if not isinstance(src, list):
            continue
        for s in src:
            x = str(s or "").strip()
            if x and x not in out:
                out.append(x)
    return out


def schema_looks_content(schema: dict[str, Any] | None, data: dict[str, Any] | None = None) -> bool:
    sch = schema if isinstance(schema, dict) else {}
    if str(sch.get("layout") or "") == "content":
        return True
    for f in sch.get("fields") or []:
        if not isinstance(f, dict):
            continue
        if str(f.get("type") or "") == "items_table" or str(f.get("key") or "") == "items":
            return True
        if is_record_key(str(f.get("key") or "")):
            return True
    blob = data if isinstance(data, dict) else {}
    items = blob.get("items")
    if isinstance(items, (dict, list)) and items:
        return True
    for k in blob:
        if is_record_key(str(k)):
            return True
    return False


def pack_custom_integration(
    iid: str,
    values: dict[str, Any] | None = None,
    *,
    name: str = "",
    description: str = "",
    skill_id: str = "",
    skills: list[str] | None = None,
    existing: dict[str, Any] | None = None,
    layout: str | None = None,
) -> dict[str, Any]:
    """Upsert payload for a custom integration: `_schema.layout` + optional `items`."""
    iid = (iid or "").strip()
    incoming = dict(values or {})
    if iid in INTEGRATION_CATALOG:
        incoming.pop("_schema", None)
        return incoming

    existing = existing if isinstance(existing, dict) else {}
    incoming_schema = incoming.pop("_schema", None)
    if not isinstance(incoming_schema, dict):
        incoming_schema = None
    prev_schema = stored_schema(existing) or {}
    if not prev_schema and isinstance(existing.get("_schema"), dict):
        prev_schema = dict(existing["_schema"])

    skill_list = _merge_skill_ids(
        skills,
        incoming.get("_skills"),
        existing.get("_skills"),
        (incoming_schema or {}).get("skills"),
        prev_schema.get("skills"),
        skill_id,
    )

    layout_n = str(
        layout
        or (incoming_schema or {}).get("layout")
        or prev_schema.get("layout")
        or ""
    ).strip()
    items = incoming.get("items", existing.get("items"))
    if layout_n not in ("single", "content"):
        probe = dict(existing)
        probe.update(incoming)
        layout_n = (
            "content"
            if schema_looks_content(incoming_schema or prev_schema, probe)
            else "single"
        )
        if isinstance(items, (dict, list)) and items:
            layout_n = "content"

    skip = set(_ROW_META_KEYS) | {
        "items",
        "hosts",
        "hosts_json",
        "_skill_id",
        "name",
        "description",
    }
    conn_keys: list[str] = []
    for k in list(incoming.keys()) + list(existing.keys()):
        ks = str(k)
        if ks in skip or ks.startswith("_") or is_record_key(ks):
            continue
        if ks not in conn_keys:
            conn_keys.append(ks)

    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    src_fields: list[Any] = []
    if incoming_schema and isinstance(incoming_schema.get("fields"), list) and incoming_schema["fields"]:
        src_fields = list(incoming_schema["fields"])
    elif isinstance(prev_schema.get("fields"), list):
        src_fields = list(prev_schema["fields"])
    for f in src_fields:
        if not isinstance(f, dict):
            continue
        k = str(f.get("key") or "").strip()
        if not k or k in seen or is_record_key(k):
            continue
        seen.add(k)
        fields.append(dict(f))
    for k in conn_keys:
        if k in seen:
            continue
        seen.add(k)
        fields.append(simple_field(k))
    if layout_n == "content" and not any(
        str(f.get("type") or "") == "items_table" or str(f.get("key") or "") == "items"
        for f in fields
    ):
        fields.append(items_table_field(iid))

    label = name or str(
        incoming.get("_label") or existing.get("_label") or prev_schema.get("name") or iid
    )
    desc = description or str(
        incoming.get("_description")
        or existing.get("_description")
        or prev_schema.get("description")
        or ""
    )
    payload: dict[str, Any] = {}
    for k, v in incoming.items():
        if k in ("_schema", "_skills", "_label", "_description", "_skill_id"):
            continue
        payload[k] = v
    payload["_label"] = label
    if desc:
        payload["_description"] = desc
    payload["_skills"] = skill_list
    req = [k for k in ("rpc_url", "base_url", "url", "host") if k in seen][:1]
    payload["_schema"] = {
        "id": iid,
        "name": label,
        "description": desc,
        "builtin": False,
        "layout": layout_n,
        "skills": skill_list,
        "fields": fields,
        "required_for_ready": req,
    }
    return payload


def unlink_skill_from_integrations(skill_id: str) -> list[str]:
    """Drop a skill id from custom integration `_skills`; keep the config row."""
    sid = (skill_id or "").strip()
    if not sid:
        return []
    try:
        from app.config_store import get_config_store

        store = get_config_store()
    except Exception:
        return []
    raw = store.get_integrations_raw()
    touched: list[str] = []
    for iid, sec in list(raw.items()):
        if not isinstance(sec, dict) or iid in INTEGRATION_CATALOG:
            continue
        skills = [str(s) for s in (sec.get("_skills") or []) if str(s).strip()]
        sch = sec.get("_schema") if isinstance(sec.get("_schema"), dict) else {}
        sch_skills = [str(s) for s in (sch.get("skills") or []) if str(s).strip()]
        if sid not in skills and sid not in sch_skills:
            continue
        payload: dict[str, Any] = {
            "_skills": [s for s in skills if s != sid],
        }
        if sch:
            sch2 = dict(sch)
            if isinstance(sch2.get("skills"), list):
                sch2["skills"] = [s for s in sch2["skills"] if str(s).strip() != sid]
            payload["_schema"] = sch2
        try:
            store.upsert_integration(str(iid), payload)
            touched.append(str(iid))
        except Exception:
            continue
    return touched


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
    try:
        from app.config_store import get_config_store

        raw = get_config_store().get_integrations_raw()
        for iid, sec in raw.items():
            if not isinstance(sec, dict):
                continue
            skills = sec.get("_skills")
            if not isinstance(skills, list):
                sch = sec.get("_schema") if isinstance(sec.get("_schema"), dict) else {}
                skills = sch.get("skills") or []
            for sid in skills:
                s = str(sid or "").strip()
                if s:
                    out.setdefault(s, str(iid))
    except Exception:
        pass
    return out


def public_row(
    integration_id: str,
    raw: dict[str, Any] | None,
    *,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mask secrets; add *_set and configured flag."""
    raw = raw if isinstance(raw, dict) else {}
    schema = schema or get_schema(integration_id, raw)
    if not schema:
        schema = {
            "id": integration_id,
            "name": str(raw.get("_label") or integration_id),
            "description": str(raw.get("_description") or "自定义集成"),
            "icon": "api",
            "skills": list(raw.get("_skills") or []),
            "builtin": False,
            "fields": [
                {
                    "key": k,
                    "label": k,
                    "type": "password" if is_secret_key(k) else "text",
                    "secret": is_secret_key(k),
                }
                for k in raw
                if k not in _ROW_META_KEYS and k not in ("hosts", "hosts_json", "items")
            ],
            "defaults": {},
        }
    data = dict(schema.get("defaults") or {})
    data.update({k: v for k, v in raw.items() if k not in _ROW_META_KEYS})

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

    def _normalize_items(blob: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if isinstance(blob, dict):
            for i, (k, v) in enumerate(blob.items(), 1):
                row = dict(v) if isinstance(v, dict) else {"content": str(v)}
                name = str(row.get("name") or k or "").strip() or f"item_{i}"
                row["name"] = name
                out[name] = row
            return out
        if isinstance(blob, list):
            for i, v in enumerate(blob, 1):
                row = dict(v) if isinstance(v, dict) else {"content": str(v)}
                name = str(row.get("name") or "").strip() or f"item_{i}"
                row["name"] = name
                out[name] = row
        return out

    def _scrub_items(items_obj: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, row in _normalize_items(items_obj).items():
            clean: dict[str, Any] = {}
            for ck, cv in row.items():
                if is_secret_key(str(ck)):
                    secrets_set[f"items.{name}.{ck}_set"] = bool(str(cv or "").strip())
                    clean[ck] = ""
                else:
                    clean[ck] = cv
            out[name] = clean
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
        if k in ("hosts", "hosts_json", "items"):
            continue  # handled below as tables
        if is_secret_key(k):
            has = bool(str(v or "").strip())
            secrets_set[f"{k}_set"] = has
            config[k] = ""  # never send raw secret to frontend list
            # editor will get empty + *_set via same flags
        else:
            config[k] = v

    # Always expose structured hosts for UI (any integration using hosts_table)
    scrubbed_hosts = _scrub_hosts(_hosts_from_data(data))
    if scrubbed_hosts or any(
        (f.get("type") == "hosts_table" or f.get("key") in ("hosts", "hosts_json"))
        for f in (schema.get("fields") or [])
        if isinstance(f, dict)
    ):
        config["hosts"] = scrubbed_hosts
        # keep hosts_json out of editor primary path (table UI only)

    schema_fields = [f for f in (schema.get("fields") or []) if isinstance(f, dict)]
    is_catalog = integration_id in INTEGRATION_CATALOG
    layout = str(schema.get("layout") or "").strip()
    if layout not in ("single", "content") and not is_catalog:
        layout = "content" if schema_looks_content(schema, data) else ""
    wants_items = any(
        str(f.get("type") or "") == "items_table" or str(f.get("key") or "") == "items"
        for f in schema_fields
    )
    if layout == "content" and not wants_items and not is_catalog:
        schema_fields = [
            f for f in schema_fields if not is_record_key(str(f.get("key") or ""))
        ]
        schema_fields.append(items_table_field(integration_id))
        wants_items = True
    raw_items = data.get("items")
    scrubbed_items = _scrub_items(raw_items)
    if scrubbed_items or wants_items:
        config["items"] = scrubbed_items

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
            # url-only row with no auth is still "partial"
            ready = any(secrets_set.get(f"{s}_set") for s in any_sec) or bool(
                str(config.get("base_url") or "").strip()
            )
            # mark partial separately
    has_any = False
    if scrubbed_hosts:
        has_any = True
    if scrubbed_items:
        has_any = True
    for k, v in data.items():
        if k in ("hosts", "hosts_json", "items"):
            continue
        if is_secret_key(k):
            if str(v or "").strip():
                has_any = True
        elif str(v or "").strip() and str(v) not in ("445", "{}", "null"):
            has_any = True

    status = "empty"
    if has_any:
        status = "ready" if ready else "partial"

    skill_ids: list[str] = []
    for s in list(schema.get("skills") or []) + list(raw.get("_skills") or []):
        sid = str(s or "").strip()
        if sid and sid not in skill_ids:
            skill_ids.append(sid)
    installed: list[str] = []
    missing: list[str] = []
    try:
        from app.services.skills import skills_root

        root = skills_root()
        for sid in skill_ids:
            if (root / sid).is_dir():
                installed.append(sid)
            else:
                missing.append(sid)
    except Exception:
        missing = list(skill_ids)

    name = str(schema.get("name") or raw.get("_label") or integration_id)
    desc = str(schema.get("description") or raw.get("_description") or "")
    return {
        "id": integration_id,
        "name": name,
        "description": desc,
        "icon": schema.get("icon") or "api",
        "skills": skill_ids,
        "skills_installed": installed,
        "skills_missing": missing,
        "builtin": bool(schema.get("builtin")),
        "catalog": is_catalog,
        "layout": layout or ("content" if wants_items else ""),
        "fields": schema_fields,
        "config": config,
        "secrets": secrets_set,
        "status": status,
        "configured": status in ("ready", "partial"),
        "needs_setup": status != "ready" and integration_id not in OPTIONAL_INTEGRATIONS,
    }


_MISSING_RX = (
    "未配置",
    "没有配置",
    "缺配置",
    "not configured",
    "missing credential",
    "设定→集成",
    "设定 → 集成",
    "设定->集成",
)


def missing_integration_from_result(
    tool_name: str, raw: str
) -> dict[str, Any] | None:
    """If a tool failed because credentials are empty, return a UI hint (no secrets)."""
    text = (raw or "").strip()
    if not text:
        return None
    payload: dict[str, Any] = {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            payload = parsed
    except Exception:
        payload = {}
    if payload.get("ok") is True:
        return None
    if payload.get("action_required") in ("confirm_spec", "confirm_delete"):
        return None
    blob = " ".join(
        [
            str(payload.get("error") or ""),
            str(payload.get("hint") or ""),
            text[:500],
        ]
    )
    if not any(k.lower() in blob.lower() for k in _MISSING_RX):
        return None
    _NOT_INTEG = {
        "create_tool",
        "delete_tool",
        "read_skill",
        "list_skills",
        "validate_skill",
        "promote_skill",
        "ask_user",
        "integrations",
        "llms",
        "memory",
        "kb",
        "workspace",
        "get_current_time",
    }
    iid = str(payload.get("integration_id") or "").strip()
    if iid.lower() in _NOT_INTEG:
        iid = ""
    if not iid:
        import re

        m = re.search(
            r"(?:integrations[./]|集成\s*[「\"']?)([a-z][a-z0-9_]{1,40})",
            blob,
            re.I,
        )
        if m and m.group(1).lower() not in _NOT_INTEG:
            iid = m.group(1).lower()
        elif str(tool_name or "").strip().lower() not in _NOT_INTEG:
            iid = str(tool_name or "").strip()
        else:
            return None
    label = iid or tool_name or "这项能力"
    schema = get_schema(iid)
    if schema and schema.get("name"):
        label = str(schema["name"])
    else:
        try:
            from app.config_store import get_config_store

            pub = get_config_store().get_integration_public(iid)
            if pub and pub.get("name"):
                label = str(pub["name"])
        except Exception:
            pass
    tell = (
        f"「{label}」还没配好。账号密码不会跟着技能包过来，"
        "请到设定 → 集成填写，填好后再说一次即可。"
    )
    return {
        "tool": str(tool_name or ""),
        "integration_id": iid,
        "label": label,
        "tell_user": tell,
        "error": str(payload.get("error") or blob)[:240],
    }
