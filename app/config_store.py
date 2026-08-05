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
        "decision_tree": "",
        "language_calibrator": "",
        "sop": "",
        "hard_boundaries": "",
        "greeting": "",
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


def default_config() -> dict[str, Any]:
    """Fresh config when data/config.json is missing.

    Intentionally blank: no pre-filled persona, no placeholder LLM.
    Only inject LLMs / MCP from environment (.env) when explicitly set.
    """
    s = get_settings()
    llms: list[dict[str, Any]] = []
    # Env-provided keys only — never invent an empty "xAI Grok" row
    if (s.llm_api_key or "").strip():
        llms.append(
            {
                "id": "default",
                "name": s.llm_provider or "default",
                "provider": s.llm_provider or "openai",
                "base_url": s.llm_base_url or "",
                "api_key": s.llm_api_key or "",
                "model": s.llm_model or "",
                "enabled": True,
                "is_default": True,
            }
        )
    if (s.llm_fallback_api_key or "").strip() and (s.llm_fallback_base_url or "").strip():
        llms.append(
            {
                "id": "fallback",
                "name": "fallback",
                "provider": "custom",
                "base_url": s.llm_fallback_base_url,
                "api_key": s.llm_fallback_api_key,
                "model": s.llm_fallback_model or s.llm_model or "",
                "enabled": True,
                "is_default": not bool(llms),
            }
        )

    mcp: list[dict[str, Any]] = []
    for i, row in enumerate(s.parse_mcp_servers()):
        mcp.append(
            {
                "id": row.get("id") or f"mcp-{i}",
                "name": row.get("name") or f"mcp-{i}",
                "command": row.get("command", ""),
                "args": row.get("args") or [],
                "env": row.get("env") or {},
                "enabled": row.get("enabled", True),
            }
        )

    return {
        "version": 1,
        "agent": blank_agent_config(),
        "llms": llms,
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
        "mcp_servers": mcp,
        # Empty map; integration catalog still lists builtins in UI
        "integrations": {},
    }


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        settings = get_settings()
        self.path = path or (settings.data_dir / "config.json")
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
                for sec in ("tools", "skills"):
                    incoming = v.get(sec)
                    if isinstance(incoming, dict):
                        base_po[sec] = {
                            str(kk): str(vv)
                            for kk, vv in incoming.items()
                            if str(vv).strip()
                        }
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
        for llm in data.get("llms", []):
            llm["api_key_set"] = bool(llm.get("api_key"))
            llm["api_key"] = _mask_key(llm.get("api_key") or "")
        for custom in data.get("tools", {}).get("custom", []):
            headers = custom.get("headers") or {}
            masked_headers = {}
            for hk, hv in headers.items():
                if re.search(r"(key|token|secret|auth)", hk, re.I):
                    masked_headers[hk] = _mask_key(str(hv))
                else:
                    masked_headers[hk] = hv
            custom["headers"] = masked_headers
        # mask integration secrets
        integ = data.get("integrations")
        if isinstance(integ, dict):
            for _sec_name, sec in integ.items():
                if not isinstance(sec, dict):
                    continue
                for sk in list(sec.keys()):
                    if re.search(r"(password|token|secret|api_key|pass)", sk, re.I):
                        if sec.get(sk):
                            sec[sk + "_set"] = True
                            sec[sk] = _mask_key(str(sec.get(sk) or ""))
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
        schema = get_schema(iid)
        allowed_keys: set[str] | None = None
        if schema:
            allowed_keys = {f["key"] for f in (schema.get("fields") or [])}

        with self._lock:
            integ = self._data.setdefault("integrations", {})
            if not isinstance(integ, dict):
                integ = {}
                self._data["integrations"] = integ
            cur = dict(integ.get(iid) or defaults_for(iid) or {})
            incoming = dict(fields or {})
            # Normalize hosts_json / hosts for netops-style multi-host tables
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
                            cur[k] = cur.get("port") or 445
                    elif k == "hosts_json":
                        import json as _json

                        if isinstance(v, (dict, list)):
                            cur["hosts_json"] = _json.dumps(v, ensure_ascii=False)
                            if isinstance(v, dict):
                                cur["hosts"] = (
                                    v.get("hosts") if isinstance(v.get("hosts"), dict) else v
                                )
                        else:
                            s = "" if v is None else str(v)
                            cur["hosts_json"] = s
                            try:
                                parsed = _json.loads(s) if s.strip() else {}
                                if isinstance(parsed, dict):
                                    cur["hosts"] = (
                                        parsed["hosts"]
                                        if isinstance(parsed.get("hosts"), dict)
                                        else parsed
                                    )
                            except Exception:
                                pass
                    elif k == "hosts" and isinstance(v, dict):
                        import json as _json

                        cur["hosts"] = v
                        cur["hosts_json"] = _json.dumps(v, ensure_ascii=False)
                    elif isinstance(v, (dict, list)):
                        cur[k] = v
                    else:
                        cur[k] = "" if v is None else v
            # ensure default keys exist for builtin
            for dk, dv in (defaults_for(iid) or {}).items():
                cur.setdefault(dk, dv)
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
                for row in llms:
                    row["is_default"] = row.get("id") == llm["id"]
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
            self._data["llms"] = new
            self._write_unlocked()
            return True

    def set_default_llm(self, llm_id: str) -> bool:
        with self._lock:
            found = False
            for row in self._data.get("llms") or []:
                if row.get("id") == llm_id:
                    row["is_default"] = True
                    row["enabled"] = True
                    found = True
                else:
                    row["is_default"] = False
            if found:
                self._write_unlocked()
            return found

    def disabled_tools(self) -> set[str]:
        return set(self.get_raw().get("tools", {}).get("disabled") or [])

    def prompt_overrides(self) -> dict[str, dict[str, str]]:
        raw = self.get_raw().get("prompt_overrides") or {}
        tools = raw.get("tools") if isinstance(raw.get("tools"), dict) else {}
        skills = raw.get("skills") if isinstance(raw.get("skills"), dict) else {}
        return {
            "tools": {str(k): str(v) for k, v in tools.items() if str(v).strip()},
            "skills": {str(k): str(v) for k, v in skills.items() if str(v).strip()},
        }

    def get_tool_prompt_override(self, name: str) -> str | None:
        n = (name or "").strip()
        if not n:
            return None
        tools = self.prompt_overrides().get("tools") or {}
        text = (tools.get(n) or "").strip()
        return text or None

    def get_skill_prompt_override(self, skill_id: str) -> str | None:
        n = (skill_id or "").strip()
        if not n:
            return None
        skills = self.prompt_overrides().get("skills") or {}
        # case-insensitive id match
        if n in skills and str(skills[n]).strip():
            return str(skills[n]).strip()
        for k, v in skills.items():
            if str(k).lower() == n.lower() and str(v).strip():
                return str(v).strip()
        return None

    def set_tool_prompt_override(self, name: str, description: str | None) -> None:
        with self._lock:
            po = self._data.setdefault("prompt_overrides", {"tools": {}, "skills": {}})
            tools = po.setdefault("tools", {})
            n = (name or "").strip()
            text = (description or "").strip()
            if not n:
                return
            if text:
                tools[n] = text
            else:
                tools.pop(n, None)
            self._write_unlocked()

    def set_skill_prompt_override(self, skill_id: str, description: str | None) -> None:
        with self._lock:
            po = self._data.setdefault("prompt_overrides", {"tools": {}, "skills": {}})
            skills = po.setdefault("skills", {})
            n = (skill_id or "").strip()
            text = (description or "").strip()
            if not n:
                return
            # drop case variants
            for k in list(skills.keys()):
                if str(k).lower() == n.lower():
                    skills.pop(k, None)
            if text:
                skills[n] = text
            self._write_unlocked()

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
        return set(self.get_raw().get("skills", {}).get("disabled") or [])

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
