"""Runtime project config — persisted to data/config.json, supports hot reload."""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

MASK = "********"


def parse_scene_keywords(raw: Any, *, limit: int = 24) -> list[str]:
    """Split a comma/顿号/newline string or list into unique keyword phrases."""
    items: list[str] = []
    if raw is None:
        return []
    if isinstance(raw, str):
        blob = (
            raw.replace("，", ",")
            .replace("、", ",")
            .replace(";", ",")
            .replace("；", ",")
            .replace("\n", ",")
        )
        items = [x.strip() for x in blob.split(",") if x.strip()]
    elif isinstance(raw, (list, tuple, set)):
        items = [str(x).strip() for x in raw if str(x).strip()]
    else:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for s in items:
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s[:40])
        if len(out) >= limit:
            break
    return out


def normalize_prompt_override(raw: Any) -> dict[str, Any] | None:
    """Legacy string → {description}; empty / junk → None.

    Stored shape::
        {"description": str, "how_to_call": str, "scene_keywords": [str, ...]}
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        return {"description": text, "how_to_call": "", "scene_keywords": []}
    if not isinstance(raw, dict):
        return None
    desc = str(raw.get("description") or "").strip()
    how = str(raw.get("how_to_call") or raw.get("trigger") or "").strip()[:200]
    kws = parse_scene_keywords(raw.get("scene_keywords") or raw.get("keywords"))
    if not desc and not how and not kws:
        return None
    return {"description": desc, "how_to_call": how, "scene_keywords": kws}


def prompt_meta_active(meta: dict[str, Any] | None) -> bool:
    if not meta:
        return False
    return bool(
        str(meta.get("description") or "").strip()
        or str(meta.get("how_to_call") or "").strip()
        or (meta.get("scene_keywords") or [])
    )


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _mask_key(key: str | None) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return MASK
    return key[:3] + MASK + key[-4:]


def _is_masked(value: str | None) -> bool:
    return not value or MASK in value


def _merge_host_passwords(
    prev_hosts: Any, incoming_hosts: Any
) -> dict[str, Any]:
    """Keep previous per-host SSH passwords when the form left them blank."""
    prev = prev_hosts if isinstance(prev_hosts, dict) else {}
    incoming = incoming_hosts if isinstance(incoming_hosts, dict) else {}
    merged: dict[str, Any] = {}
    for hn, hc in incoming.items():
        name = str(hn)
        row = dict(hc) if isinstance(hc, dict) else {"host": str(hc)}
        old = prev.get(name) if isinstance(prev.get(name), dict) else {}
        incoming_pw = str(row.get("password") or "").strip()
        if not incoming_pw or _is_masked(incoming_pw):
            if str(old.get("password") or "").strip():
                row["password"] = old.get("password")
            else:
                row.pop("password", None)
        merged[name] = row
    return merged


def _normalize_item_rows(blob: Any) -> dict[str, Any]:
    """Content-table rows as name → dict."""
    out: dict[str, Any] = {}
    if isinstance(blob, dict):
        seq = blob.items()
        for i, (k, v) in enumerate(seq, 1):
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


def _merge_item_rows(prev_items: Any, incoming_items: Any) -> dict[str, Any]:
    """Keep previous secret columns when the form left them blank."""
    from app.services.integrations_meta import is_secret_key

    prev = _normalize_item_rows(prev_items)
    incoming = _normalize_item_rows(incoming_items)
    merged: dict[str, Any] = {}
    for name, row in incoming.items():
        old = prev.get(name) if isinstance(prev.get(name), dict) else {}
        out = dict(row)
        secret_keys = {str(k) for k in old if is_secret_key(str(k))} | {
            str(k) for k in out if is_secret_key(str(k))
        }
        for k in secret_keys:
            v = out.get(k)
            s = "" if v is None else str(v)
            if not s.strip() or _is_masked(s):
                if str(old.get(k) or "").strip():
                    out[k] = old.get(k)
                else:
                    out.pop(k, None)
        merged[name] = out
    return merged


def blank_agent_config() -> dict[str, Any]:
    """Empty agent persona skeleton (no stock commercial copy)."""
    s = get_settings()
    return {
        "name": "",
        "role": [],
        "language": "",
        "language_style": [],
        "background": "",
        "roleplay_enabled": False,
        "roleplay_intensity": "medium",
        "relationship": "",
        "personality": "",
        "speech_patterns": "",
        "example_dialogue": "",
        "ooc_rules": "",
        "persona_options": {},
        # Runtime knobs only — not persona marketing text
        "max_tool_rounds": s.max_tool_rounds,
        "max_history_messages": s.max_history_messages,
        "evolution_enabled": True,
        "evolution_trigger_messages": 24,
        "evolution_keep_messages": 16,
        "evolution_max_entries": 12,
        "evolution_max_chars": 2200,
    }


def default_llms() -> list[dict[str, Any]]:
    """Publishable DeepSeek row. API Key stays empty until the user fills it."""
    return [
        {
            "id": "deepseek",
            "name": "Deepseek",
            "provider": "openai",
            "base_url": "https://api.deepseek.com",
            "api_key": "",
            "model": "deepseek-flash",
            "enabled": True,
            "is_default": True,
            "is_deputy": False,
            "use_proxy": False,
        }
    ]


def default_config() -> dict[str, Any]:
    """Fresh config when data/config.json is missing.

    Blank persona / MCP / integrations. Ships one DeepSeek template with
    an empty API Key; chat works after 设定 → LLM fills the key.
    """
    return {
        "version": 1,
        "agent": blank_agent_config(),
        "llms": default_llms(),
        "tools": {
            "disabled": [],
            "custom": [],
        },
        "skills": {
            "disabled": [],
        },
        "prompt_overrides": {
            "tools": {},
            "skills": {},
        },
        "mcp_servers": [],
        # Empty map; integration catalog still lists builtins in UI
        "integrations": {},
        "workspace": {
            "mode": "local",
            "root": "",
            "hub_url": "",
        },
    }


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        settings = get_settings()
        self.path = path or settings.paths().config_json
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                self._data = default_config()
                self._write_unlocked()
            else:
                raw = self.path.read_text(encoding="utf-8")
                self._data = json.loads(raw or "{}")
                self._data = self._merge_defaults(self._data)
            return deepcopy(self._data)

    def _merge_defaults(self, data: dict[str, Any]) -> dict[str, Any]:
        """Fill only missing structural sections; never re-seed persona marketing text.

        Agent: blank skeleton + user keys (empty strings stay empty).
        LLMs: honor disk list as-is, including empty [].
        """
        base = default_config()
        out = deepcopy(base)
        if not isinstance(data, dict):
            return out

        for k, v in data.items():
            if k == "agent" and isinstance(v, dict):
                # Start from blank agent, not stock persona; then apply disk values
                agent = blank_agent_config()
                agent.update(v)
                out["agent"] = agent
            elif k == "tools" and isinstance(v, dict):
                tools = dict(out.get("tools") or {"disabled": [], "custom": []})
                tools.update(v)
                out["tools"] = tools
            elif k == "skills" and isinstance(v, dict):
                skills = dict(out.get("skills") or {"disabled": []})
                skills.update(v)
                out["skills"] = skills
            elif k in ("llms", "mcp_servers") and isinstance(v, list):
                out[k] = v  # allow empty list = user cleared all
            elif k == "integrations" and isinstance(v, dict):
                base_int = out.setdefault("integrations", {})
                if not isinstance(base_int, dict):
                    base_int = {}
                    out["integrations"] = base_int
                for sk, sv in v.items():
                    if isinstance(sv, dict) and isinstance(base_int.get(sk), dict):
                        merged = dict(base_int[sk])
                        merged.update(sv)
                        base_int[sk] = merged
                    else:
                        base_int[sk] = sv
            elif k == "prompt_overrides" and isinstance(v, dict):
                base_po = out.setdefault(
                    "prompt_overrides", {"tools": {}, "skills": {}}
                )
                if not isinstance(base_po, dict):
                    base_po = {"tools": {}, "skills": {}}
                    out["prompt_overrides"] = base_po
                for sec in ("tools", "skills"):
                    incoming = v.get(sec)
                    if not isinstance(incoming, dict):
                        continue
                    cleaned: dict[str, Any] = {}
                    for kk, vv in incoming.items():
                        norm = normalize_prompt_override(vv)
                        if norm:
                            cleaned[str(kk)] = norm
                    base_po[sec] = cleaned
            elif k == "workspace" and isinstance(v, dict):
                base_ws = out.setdefault(
                    "workspace", {"mode": "local", "root": "", "hub_url": ""}
                )
                if isinstance(base_ws, dict):
                    base_ws.update({str(sk): sv for sk, sv in v.items()})
            elif k in ("skills_catalog", "tools_catalog"):
                continue
            else:
                out[k] = v

        # Do NOT re-seed llms when empty — empty means "user cleared / fresh install"
        if out.get("llms") is None:
            out["llms"] = []
        if out.get("mcp_servers") is None:
            out["mcp_servers"] = []
        if out["llms"] and not any(x.get("is_default") for x in out["llms"]):
            out["llms"][0]["is_default"] = True
        if not isinstance(out.get("agent"), dict):
            out["agent"] = blank_agent_config()
        return out

    def _write_unlocked(self) -> None:
        # Do not persist runtime catalogs (they are rebuilt via scan/registry)
        data = deepcopy(self._data)
        data.pop("skills_catalog", None)
        data.pop("tools_catalog", None)
        # api_key_set is computed in get_public(); never store it
        for llm in data.get("llms") or []:
            if isinstance(llm, dict):
                llm.pop("api_key_set", None)
        for llm in self._data.get("llms") or []:
            if isinstance(llm, dict):
                llm.pop("api_key_set", None)
        # Drop obsolete agent keys if any slipped in without migrate
        if isinstance(data.get("agent"), dict):
            from app.agent.persona import compact_agent_config, migrate_legacy_system_prompt

            data["agent"] = compact_agent_config(
                migrate_legacy_system_prompt(data["agent"])
            )
            self._data["agent"] = deepcopy(data["agent"])
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def save(self) -> None:
        with self._lock:
            self._write_unlocked()

    def get_raw(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._data)

    def get_public(self) -> dict[str, Any]:
        """Return config with API keys / integration passwords masked for frontend."""
        data = self.get_raw()
        llms = data.get("llms")
        if not isinstance(llms, list):
            llms = []
            data["llms"] = llms
        for llm in llms:
            if not isinstance(llm, dict):
                continue
            llm["api_key_set"] = bool(llm.get("api_key"))
            llm["api_key"] = _mask_key(llm.get("api_key") or "")
        tools_sec = data.get("tools")
        if not isinstance(tools_sec, dict):
            tools_sec = {}
            data["tools"] = tools_sec
        custom_list = tools_sec.get("custom") or []
        if not isinstance(custom_list, list):
            custom_list = []
            tools_sec["custom"] = custom_list
        for custom in custom_list:
            if not isinstance(custom, dict):
                continue
            headers = custom.get("headers") or {}
            masked_headers = {}
            for hk, hv in headers.items():
                if re.search(r"(key|token|secret|auth)", hk, re.I):
                    masked_headers[hk] = _mask_key(str(hv))
                else:
                    masked_headers[hk] = hv
            custom["headers"] = masked_headers
        integ = data.get("integrations")
        if isinstance(integ, dict):
            from app.services.integrations_meta import public_row

            pub_map: dict[str, Any] = {}
            for sid, sec in integ.items():
                if not isinstance(sec, dict):
                    continue
                row = public_row(str(sid), sec)
                merged = dict(row.get("config") or {})
                for sk, sv in (row.get("secrets") or {}).items():
                    merged[sk] = sv
                pub_map[str(sid)] = merged
            data["integrations"] = pub_map
        data.pop("skills_catalog", None)
        data.pop("tools_catalog", None)
        return data

    def replace(self, data: dict[str, Any]) -> dict[str, Any]:
        """Full replace while preserving unmasked secrets when client sends masks."""
        with self._lock:
            current = deepcopy(self._data)
            incoming = self._merge_defaults(data)

            # preserve API keys if masked
            cur_llms = {x["id"]: x for x in current.get("llms", []) if "id" in x}
            for llm in incoming.get("llms", []):
                if _is_masked(llm.get("api_key")):
                    old = cur_llms.get(llm.get("id", ""))
                    if old:
                        llm["api_key"] = old.get("api_key", "")
                    else:
                        llm["api_key"] = ""

            # preserve sensitive custom headers if masked
            cur_custom = {
                x["id"]: x
                for x in current.get("tools", {}).get("custom", [])
                if x.get("id")
            }
            for custom in incoming.get("tools", {}).get("custom", []):
                old = cur_custom.get(custom.get("id", ""))
                if not old:
                    continue
                old_headers = old.get("headers") or {}
                new_headers = custom.get("headers") or {}
                for hk, hv in list(new_headers.items()):
                    if _is_masked(str(hv)) and hk in old_headers:
                        new_headers[hk] = old_headers[hk]
                custom["headers"] = new_headers

            incoming_integ = incoming.get("integrations")
            cur_integ = (
                current.get("integrations")
                if isinstance(current.get("integrations"), dict)
                else {}
            )
            if isinstance(incoming_integ, dict):
                from app.services.integrations_meta import is_secret_key

                merged_integ: dict[str, Any] = {}
                for iid, sec in incoming_integ.items():
                    if not isinstance(sec, dict):
                        continue
                    old = (
                        cur_integ.get(iid)
                        if isinstance(cur_integ.get(iid), dict)
                        else {}
                    )
                    row = dict(sec)
                    for hk, hv in list(row.items()):
                        if not is_secret_key(str(hk)):
                            continue
                        s = "" if hv is None else str(hv)
                        if (not s.strip() or _is_masked(s)) and old.get(hk):
                            row[hk] = old[hk]
                    if isinstance(row.get("hosts"), dict) or isinstance(
                        old.get("hosts"), dict
                    ):
                        row["hosts"] = _merge_host_passwords(
                            old.get("hosts"), row.get("hosts")
                        )
                    merged_integ[str(iid)] = row
                incoming["integrations"] = merged_integ

            self._data = incoming
            self._write_unlocked()
            return deepcopy(self._data)

    def update_section(self, section: str, value: Any) -> dict[str, Any]:
        with self._lock:
            if section == "agent" and isinstance(value, dict):
                # Agent is replaced (not deep-merged forever) so obsolete keys
                # can be dropped after migrate/compact.
                from app.agent.persona import compact_agent_config, migrate_legacy_system_prompt

                current = dict(self._data.get("agent") or {})
                current.update(value)
                self._data["agent"] = compact_agent_config(
                    migrate_legacy_system_prompt(current)
                )
            elif section == "tools" and isinstance(value, dict):
                self._data.setdefault("tools", {}).update(value)
            elif section == "skills" and isinstance(value, dict):
                self._data.setdefault("skills", {}).update(value)
            elif section == "llms" and isinstance(value, list):
                # merge keys
                cur = {x["id"]: x for x in self._data.get("llms", [])}
                for llm in value:
                    if _is_masked(llm.get("api_key")):
                        old = cur.get(llm.get("id", ""))
                        llm["api_key"] = (old or {}).get("api_key", "")
                self._data["llms"] = value
            elif section == "mcp_servers" and isinstance(value, list):
                self._data["mcp_servers"] = value
            else:
                self._data[section] = value
            self._write_unlocked()
            return deepcopy(self._data)

    # --- integrations (skill connection configs) ---

    def get_integrations_raw(self) -> dict[str, Any]:
        with self._lock:
            integ = self._data.get("integrations")
            return deepcopy(integ) if isinstance(integ, dict) else {}

    def list_integrations_public(self) -> list[dict[str, Any]]:
        from app.services.integrations_meta import (
            INTEGRATION_CATALOG,
            catalog_list,
            public_row,
        )

        raw = self.get_integrations_raw()
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        # catalog first
        for meta in catalog_list():
            iid = meta["id"]
            seen.add(iid)
            out.append(public_row(iid, raw.get(iid) if isinstance(raw.get(iid), dict) else {}))
        # custom extras on disk
        for iid, sec in raw.items():
            if iid in seen or not isinstance(sec, dict):
                continue
            out.append(public_row(str(iid), sec))
        return out

    def get_integration_public(self, integration_id: str) -> dict[str, Any] | None:
        from app.services.integrations_meta import get_schema, public_row

        iid = (integration_id or "").strip()
        if not iid:
            return None
        raw = self.get_integrations_raw()
        if iid not in raw and not get_schema(iid):
            return None
        return public_row(iid, raw.get(iid) if isinstance(raw.get(iid), dict) else {})

    def upsert_integration(
        self, integration_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        """Create or update integration; empty/masked secrets keep previous values."""
        from app.services.integrations_meta import (
            defaults_for,
            get_schema,
            is_secret_key,
            public_row,
        )

        iid = (integration_id or "").strip()
        if not iid or not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]{0,39}$", iid):
            raise ValueError("invalid integration id")

        with self._lock:
            integ = self._data.setdefault("integrations", {})
            if not isinstance(integ, dict):
                integ = {}
                self._data["integrations"] = integ
            cur = dict(integ.get(iid) or defaults_for(iid) or {})
            schema = get_schema(iid, cur)
            allowed_keys: set[str] | None = None
            incoming = dict(fields or {})
            incoming_schema = incoming.get("_schema")
            incoming_layout = (
                str(incoming_schema.get("layout") or "").strip()
                if isinstance(incoming_schema, dict)
                else ""
            )
            if isinstance(incoming_schema, dict) and (
                isinstance(incoming_schema.get("fields"), list)
                or incoming_layout in ("single", "content")
            ):
                if schema and schema.get("builtin"):
                    incoming.pop("_schema", None)
                    incoming_schema = None
                else:
                    schema = dict(incoming_schema)
                    if not isinstance(schema.get("fields"), list):
                        schema["fields"] = []
            if schema:
                allowed_keys = {str(f.get("key") or "") for f in (schema.get("fields") or [])}
                allowed_keys.update({"_schema", "_label", "_description", "_skills", "items"})
                allowed_keys.discard("")
                if any(
                    str(f.get("type") or "") == "items_table"
                    or str(f.get("key") or "") == "items"
                    for f in (schema.get("fields") or [])
                    if isinstance(f, dict)
                ):
                    allowed_keys.add("items")
            # Normalize hosts_json / hosts for multi-host tables
            if "hosts" in incoming and "hosts_json" not in incoming:
                hv = incoming.get("hosts")
                if isinstance(hv, (dict, list)):
                    import json as _json

                    incoming["hosts_json"] = _json.dumps(hv, ensure_ascii=False)
            for k, v in list(incoming.items()):
                if allowed_keys is not None and k not in allowed_keys:
                    # still accept nested hosts when catalog only lists hosts_json
                    if not (k == "hosts" and "hosts_json" in (allowed_keys or set())):
                        continue
                if is_secret_key(k):
                    s = "" if v is None else str(v)
                    if not s.strip() or _is_masked(s):
                        # keep existing
                        continue
                    cur[k] = s
                else:
                    if k == "port":
                        try:
                            cur[k] = int(v)
                        except (TypeError, ValueError):
                            cur[k] = cur.get("port") or 80
                    elif k == "hosts_json":
                        import json as _json

                        if isinstance(v, (dict, list)):
                            blob = v.get("hosts") if isinstance(v, dict) and isinstance(v.get("hosts"), dict) else v
                            if isinstance(blob, dict):
                                merged = _merge_host_passwords(cur.get("hosts"), blob)
                                cur["hosts"] = merged
                                cur["hosts_json"] = _json.dumps(merged, ensure_ascii=False)
                            else:
                                cur["hosts_json"] = _json.dumps(v, ensure_ascii=False)
                        else:
                            s = "" if v is None else str(v)
                            cur["hosts_json"] = s
                            try:
                                parsed = _json.loads(s) if s.strip() else {}
                                if isinstance(parsed, dict):
                                    parsed_hosts = (
                                        parsed["hosts"]
                                        if isinstance(parsed.get("hosts"), dict)
                                        else parsed
                                    )
                                    cur["hosts"] = _merge_host_passwords(
                                        cur.get("hosts"), parsed_hosts
                                    )
                            except Exception:
                                pass
                    elif k == "hosts" and isinstance(v, dict):
                        import json as _json

                        merged = _merge_host_passwords(cur.get("hosts"), v)
                        cur["hosts"] = merged
                        cur["hosts_json"] = _json.dumps(merged, ensure_ascii=False)
                    elif k == "items" and isinstance(v, (dict, list)):
                        cur["items"] = _merge_item_rows(cur.get("items"), v)
                    elif isinstance(v, (dict, list)):
                        cur[k] = v
                    else:
                        cur[k] = "" if v is None else v
            # ensure default keys exist for builtin
            for dk, dv in (defaults_for(iid) or {}).items():
                cur.setdefault(dk, dv)
            if isinstance(schema, dict) and schema.get("layout") == "single":
                cur.pop("items", None)
            integ[iid] = cur
            self._write_unlocked()
            return public_row(iid, cur)

    def delete_integration(self, integration_id: str) -> bool:
        """Clear builtin to defaults, or remove custom entry entirely."""
        from app.services.integrations_meta import defaults_for, get_schema

        iid = (integration_id or "").strip()
        if not iid:
            return False
        with self._lock:
            integ = self._data.get("integrations")
            if not isinstance(integ, dict) or iid not in integ:
                # still allow reset builtin even if missing
                if not get_schema(iid):
                    return False
            if get_schema(iid):
                integ = self._data.setdefault("integrations", {})
                integ[iid] = dict(defaults_for(iid) or {})
            else:
                integ = self._data.get("integrations") or {}
                if iid in integ:
                    del integ[iid]
            self._write_unlocked()
            return True

    # --- helpers used by runtime ---

    def get_agent(self) -> dict[str, Any]:
        from app.agent.persona import migrate_legacy_system_prompt

        raw = deepcopy(self.get_raw().get("agent") or {})
        return migrate_legacy_system_prompt(raw)

    def get_default_llm(self) -> dict[str, Any] | None:
        llms = self.get_raw().get("llms") or []
        enabled = [x for x in llms if x.get("enabled", True)]
        for x in enabled:
            if x.get("is_default"):
                return deepcopy(x)
        return deepcopy(enabled[0]) if enabled else None

    def get_deputy_llm(self) -> dict[str, Any] | None:
        """Enabled deputy row, never the same as the default primary."""
        llms = self.get_raw().get("llms") or []
        enabled = [x for x in llms if x.get("enabled", True)]
        default = None
        for x in enabled:
            if x.get("is_default"):
                default = x
                break
        if default is None and enabled:
            default = enabled[0]
        default_id = str((default or {}).get("id") or "")
        for x in enabled:
            if x.get("is_deputy") and str(x.get("id") or "") != default_id:
                return deepcopy(x)
        return None

    def get_llm(self, llm_id: str) -> dict[str, Any] | None:
        for x in self.get_raw().get("llms") or []:
            if x.get("id") == llm_id:
                return deepcopy(x)
        return None

    def list_llms(self) -> list[dict[str, Any]]:
        return deepcopy(self.get_raw().get("llms") or [])

    def upsert_llm(self, llm: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            llms = self._data.setdefault("llms", [])
            llm = dict(llm)
            if not llm.get("id"):
                llm["id"] = _new_id()
            found = False
            for i, row in enumerate(llms):
                if row.get("id") == llm["id"]:
                    if _is_masked(llm.get("api_key")):
                        llm["api_key"] = row.get("api_key", "")
                    llms[i] = {**row, **llm}
                    llm = llms[i]
                    found = True
                    break
            if not found:
                if _is_masked(llm.get("api_key")):
                    llm["api_key"] = ""
                llms.append(llm)
            if llm.get("is_default"):
                llm["is_deputy"] = False
                for row in llms:
                    row["is_default"] = row.get("id") == llm["id"]
                    if row.get("is_default"):
                        row["is_deputy"] = False
            elif llm.get("is_deputy"):
                llm["is_default"] = False
                for row in llms:
                    row["is_deputy"] = row.get("id") == llm["id"]
                    if row.get("is_deputy"):
                        row["is_default"] = False
                if not any(x.get("is_default") for x in llms):
                    for row in llms:
                        if row.get("id") != llm["id"] and row.get("enabled", True):
                            row["is_default"] = True
                            break
            self._write_unlocked()
            return deepcopy(llm)

    def delete_llm(self, llm_id: str) -> bool:
        with self._lock:
            llms = self._data.get("llms") or []
            new = [x for x in llms if x.get("id") != llm_id]
            if len(new) == len(llms):
                return False
            if new and not any(x.get("is_default") for x in new):
                new[0]["is_default"] = True
                new[0]["is_deputy"] = False
            self._data["llms"] = new
            self._write_unlocked()
            return True

    def set_default_llm(self, llm_id: str) -> bool:
        with self._lock:
            found = False
            for row in self._data.get("llms") or []:
                if row.get("id") == llm_id:
                    row["is_default"] = True
                    row["is_deputy"] = False
                    row["enabled"] = True
                    found = True
                else:
                    row["is_default"] = False
            if found:
                self._write_unlocked()
            return found

    def set_deputy_llm(self, llm_id: str) -> bool:
        with self._lock:
            found = False
            rows = self._data.get("llms") or []
            for row in rows:
                if row.get("id") == llm_id:
                    row["is_deputy"] = True
                    row["is_default"] = False
                    row["enabled"] = True
                    found = True
                else:
                    row["is_deputy"] = False
            if found and not any(x.get("is_default") for x in rows):
                for row in rows:
                    if row.get("id") != llm_id and row.get("enabled", True):
                        row["is_default"] = True
                        break
            if found:
                self._write_unlocked()
            return found

    def disabled_tools(self) -> set[str]:
        tools = self.get_raw().get("tools")
        if not isinstance(tools, dict):
            return set()
        raw = tools.get("disabled") or []
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple, set)):
            return set()
        return {str(x) for x in raw if str(x).strip()}

    def prompt_overrides(self) -> dict[str, dict[str, dict[str, Any]]]:
        raw = self.get_raw().get("prompt_overrides") or {}
        tools = raw.get("tools") if isinstance(raw.get("tools"), dict) else {}
        skills = raw.get("skills") if isinstance(raw.get("skills"), dict) else {}
        out_tools: dict[str, dict[str, Any]] = {}
        out_skills: dict[str, dict[str, Any]] = {}
        for k, v in tools.items():
            norm = normalize_prompt_override(v)
            if norm:
                out_tools[str(k)] = norm
        for k, v in skills.items():
            norm = normalize_prompt_override(v)
            if norm:
                out_skills[str(k)] = norm
        return {"tools": out_tools, "skills": out_skills}

    def _lookup_prompt_meta(
        self, section: str, key: str
    ) -> dict[str, Any] | None:
        n = (key or "").strip()
        if not n:
            return None
        bucket = self.prompt_overrides().get(section) or {}
        if n in bucket:
            return dict(bucket[n])
        n_l = n.lower()
        for k, v in bucket.items():
            if str(k).lower() == n_l:
                return dict(v)
        return None

    def get_tool_prompt_meta(self, name: str) -> dict[str, Any] | None:
        return self._lookup_prompt_meta("tools", name)

    def get_skill_prompt_meta(self, skill_id: str) -> dict[str, Any] | None:
        return self._lookup_prompt_meta("skills", skill_id)

    def get_tool_prompt_override(self, name: str) -> str | None:
        """LLM-facing description override only (legacy string getter)."""
        meta = self.get_tool_prompt_meta(name)
        if not meta:
            return None
        text = str(meta.get("description") or "").strip()
        return text or None

    def get_skill_prompt_override(self, skill_id: str) -> str | None:
        meta = self.get_skill_prompt_meta(skill_id)
        if not meta:
            return None
        text = str(meta.get("description") or "").strip()
        return text or None

    def _set_prompt_meta(
        self,
        section: str,
        key: str,
        *,
        description: str | None = None,
        how_to_call: str | None = None,
        scene_keywords: Any = None,
        clear: bool = False,
    ) -> dict[str, Any] | None:
        n = (key or "").strip()
        if not n:
            return None
        with self._lock:
            po = self._data.setdefault("prompt_overrides", {"tools": {}, "skills": {}})
            if not isinstance(po, dict):
                po = {"tools": {}, "skills": {}}
                self._data["prompt_overrides"] = po
            bucket = po.setdefault(section, {})
            if not isinstance(bucket, dict):
                bucket = {}
                po[section] = bucket
            # drop case variants so the saved key is the canonical one
            n_l = n.lower()
            for k in list(bucket.keys()):
                if str(k).lower() == n_l:
                    bucket.pop(k, None)
            if clear:
                self._write_unlocked()
                return None
            entry = normalize_prompt_override(
                {
                    "description": description or "",
                    "how_to_call": how_to_call or "",
                    "scene_keywords": scene_keywords or [],
                }
            )
            if entry:
                bucket[n] = entry
            self._write_unlocked()
            return dict(entry) if entry else None

    def set_tool_prompt_meta(
        self,
        name: str,
        *,
        description: str | None = None,
        how_to_call: str | None = None,
        scene_keywords: Any = None,
        clear: bool = False,
    ) -> dict[str, Any] | None:
        return self._set_prompt_meta(
            "tools",
            name,
            description=description,
            how_to_call=how_to_call,
            scene_keywords=scene_keywords,
            clear=clear,
        )

    def set_skill_prompt_meta(
        self,
        skill_id: str,
        *,
        description: str | None = None,
        how_to_call: str | None = None,
        scene_keywords: Any = None,
        clear: bool = False,
    ) -> dict[str, Any] | None:
        return self._set_prompt_meta(
            "skills",
            skill_id,
            description=description,
            how_to_call=how_to_call,
            scene_keywords=scene_keywords,
            clear=clear,
        )

    def set_tool_prompt_override(self, name: str, description: str | None) -> None:
        """Legacy: set/clear description only. Empty description clears the whole override."""
        text = (description or "").strip()
        if not text:
            self.set_tool_prompt_meta(name, clear=True)
            return
        cur = self.get_tool_prompt_meta(name) or {}
        self.set_tool_prompt_meta(
            name,
            description=text,
            how_to_call=cur.get("how_to_call") or "",
            scene_keywords=cur.get("scene_keywords") or [],
        )

    def set_skill_prompt_override(self, skill_id: str, description: str | None) -> None:
        text = (description or "").strip()
        if not text:
            self.set_skill_prompt_meta(skill_id, clear=True)
            return
        cur = self.get_skill_prompt_meta(skill_id) or {}
        self.set_skill_prompt_meta(
            skill_id,
            description=text,
            how_to_call=cur.get("how_to_call") or "",
            scene_keywords=cur.get("scene_keywords") or [],
        )

    def custom_tools(self) -> list[dict[str, Any]]:
        return deepcopy(self.get_raw().get("tools", {}).get("custom") or [])

    def set_tool_disabled(self, name: str, disabled: bool) -> None:
        with self._lock:
            disabled_list = list(
                self._data.setdefault("tools", {}).setdefault("disabled", [])
            )
            nm = (name or "").strip()
            disabled_list = [
                x for x in disabled_list if str(x).lower() != nm.lower()
            ]
            if disabled and nm:
                disabled_list.append(nm)
            self._data["tools"]["disabled"] = disabled_list
            self._write_unlocked()

    def upsert_custom_tool(self, tool: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            tools = self._data.setdefault("tools", {}).setdefault("custom", [])
            tool = dict(tool)
            if not tool.get("id"):
                tool["id"] = _new_id()
            # preserve masked headers
            for i, row in enumerate(tools):
                if row.get("id") == tool["id"]:
                    old_headers = row.get("headers") or {}
                    new_headers = tool.get("headers") or {}
                    for hk, hv in list(new_headers.items()):
                        if _is_masked(str(hv)) and hk in old_headers:
                            new_headers[hk] = old_headers[hk]
                    tool["headers"] = new_headers
                    tools[i] = {**row, **tool}
                    tool = tools[i]
                    self._write_unlocked()
                    return deepcopy(tool)
            tools.append(tool)
            self._write_unlocked()
            return deepcopy(tool)

    def delete_custom_tool(self, tool_id: str) -> bool:
        with self._lock:
            tools = self._data.get("tools", {}).get("custom") or []
            new = [x for x in tools if x.get("id") != tool_id]
            if len(new) == len(tools):
                return False
            self._data.setdefault("tools", {})["custom"] = new
            self._write_unlocked()
            return True

    def disabled_skills(self) -> set[str]:
        skills = self.get_raw().get("skills")
        if not isinstance(skills, dict):
            return set()
        raw = skills.get("disabled") or []
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple, set)):
            return set()
        return {str(x) for x in raw if str(x).strip()}

    def set_skill_disabled(self, skill_id: str, disabled: bool) -> None:
        with self._lock:
            disabled_list = list(
                self._data.setdefault("skills", {}).setdefault("disabled", [])
            )
            sid = (skill_id or "").strip()
            # Normalize: remove both exact and case-insensitive duplicates
            disabled_list = [
                x for x in disabled_list if str(x).lower() != sid.lower()
            ]
            if disabled and sid:
                disabled_list.append(sid)
            self._data["skills"]["disabled"] = disabled_list
            self._write_unlocked()

    def list_mcp(self) -> list[dict[str, Any]]:
        return deepcopy(self.get_raw().get("mcp_servers") or [])

    def upsert_mcp(self, server: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            servers = self._data.setdefault("mcp_servers", [])
            server = dict(server)
            if not server.get("id"):
                server["id"] = _new_id()
            for i, row in enumerate(servers):
                if row.get("id") == server["id"]:
                    servers[i] = {**row, **server}
                    server = servers[i]
                    self._write_unlocked()
                    return deepcopy(server)
            servers.append(server)
            self._write_unlocked()
            return deepcopy(server)

    def delete_mcp(self, server_id: str) -> bool:
        with self._lock:
            servers = self._data.get("mcp_servers") or []
            new = [x for x in servers if x.get("id") != server_id]
            if len(new) == len(servers):
                return False
            self._data["mcp_servers"] = new
            self._write_unlocked()
            return True


_store: ConfigStore | None = None


def get_config_store() -> ConfigStore:
    global _store
    if _store is None:
        _store = ConfigStore()
    return _store


def reset_config_store() -> None:
    global _store
    _store = None
