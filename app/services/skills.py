"""Skill package loader.

Skill layout:
  skills/<skill_id>/
    manifest.json
    SKILL.md (optional)
    handler.py (optional — defines tools via register(registry))

manifest.json example:
{
  "id": "demo",
  "name": "Demo Skill",
  "description": "...",
  "version": "0.1.0",
  "tools": [
    {
      "name": "demo_echo",
      "description": "Echo text",
      "type": "http",
      "method": "GET",
      "url": "https://httpbin.org/get",
      "parameters": {"type":"object","properties":{"query":{"type":"string"}}}
    }
  ]
}
"""

from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path
from typing import Any

from app.config_store import get_config_store
from app.services.custom_tools import _make_http_handler
from app.tools.registry import ToolRegistry, get_tool_registry

logger = logging.getLogger(__name__)


def skills_root() -> Path:
    return Path(__file__).resolve().parents[2] / "skills"


def scan_skills() -> list[dict[str, Any]]:
    root = skills_root()
    root.mkdir(parents=True, exist_ok=True)
    disabled = get_config_store().disabled_skills()
    results: list[dict[str, Any]] = []

    for path in sorted(root.iterdir() if root.exists() else []):
        if not path.is_dir() or path.name.startswith((".", "_")):
            continue
        manifest_path = path / "manifest.json"
        skill_id = path.name
        info: dict[str, Any] = {
            "id": skill_id,
            "name": skill_id,
            "description": "",
            "version": "",
            "path": str(path),
            "enabled": skill_id not in disabled,
            "has_handler": (path / "handler.py").exists(),
            "has_skill_md": (path / "SKILL.md").exists(),
            "tool_count": 0,
            "tools": [],
        }
        if manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                info["id"] = data.get("id") or skill_id
                info["name"] = data.get("name") or skill_id
                info["description"] = data.get("description") or ""
                info["version"] = data.get("version") or ""
                tools = data.get("tools") or []
                info["tools"] = tools
                info["tool_count"] = len(tools)
                info["enabled"] = info["id"] not in disabled and skill_id not in disabled
                if isinstance(data.get("agentos_meta"), dict):
                    info["metadata"] = dict(data["agentos_meta"])
            except Exception as exc:
                info["description"] = f"Invalid manifest: {exc}"
        elif (path / "SKILL.md").exists():
            text = (path / "SKILL.md").read_text(encoding="utf-8", errors="replace")
            info["description"] = text.strip().splitlines()[0][:200] if text.strip() else ""
        # Merge dynamic create_tool meta (P0–P2) when present
        try:
            from app.tools.tool_meta import display_name_for, meta_for

            sid = info.get("id") or skill_id
            dyn = meta_for(sid)
            if dyn:
                base_md = dict(info.get("metadata") or {})
                base_md.update(dyn)
                info["metadata"] = base_md
            label = display_name_for(sid)
            info["display_name"] = label
            # Prefer Chinese label over English Title Case from create_tool
            if label and label != sid.replace("_", " ").title():
                info["name"] = label
            # User prompt override for package description
            try:
                base_desc = (info.get("description") or "").strip()
                ovr = get_config_store().get_skill_prompt_override(sid)
                info["base_description"] = base_desc
                info["prompt_override"] = ovr or ""
                info["has_prompt_override"] = bool(ovr)
                if ovr:
                    info["description"] = ovr
            except Exception:
                info.setdefault("base_description", info.get("description") or "")
                info.setdefault("has_prompt_override", False)
        except Exception:
            info.setdefault("display_name", info.get("name") or skill_id)

        # Link skill → integrations.* config (for frontend 配置提示)
        try:
            from app.services.integrations_meta import skill_to_integration

            imap = skill_to_integration()
            sid = str(info.get("id") or skill_id)
            iid = imap.get(sid) or imap.get(skill_id)
            if iid:
                info["integration_id"] = iid
                try:
                    pub = get_config_store().get_integration_public(iid)
                    info["integration_status"] = (pub or {}).get("status") or "empty"
                    info["integration_name"] = (pub or {}).get("name") or iid
                except Exception:
                    info["integration_status"] = "unknown"
                    info["integration_name"] = iid
        except Exception:
            pass

        results.append(info)
    return results


def register_skills(
    registry: ToolRegistry | None = None,
    *,
    include_disabled: bool = False,
) -> int:
    """Load skill handlers into *registry*.

    Parameters
    ----------
    include_disabled:
        If True, register tools even when the skill package is in the disabled
        list (used for UI catalog so users can re-enable). Runtime rebuild keeps
        the default False so disabled skills stay out of LLM schemas.
    """
    registry = registry or get_tool_registry()
    disabled = set() if include_disabled else get_config_store().disabled_skills()

    # remove previous skill tools
    for t in list(registry.list_tools()):
        if t.source == "skill":
            registry.unregister(t.name)

    count = 0
    for skill in scan_skills():
        skill_id = skill["id"]
        folder = Path(skill["path"]).name
        if not include_disabled:
            if skill_id in disabled or folder in disabled or not skill.get("enabled", True):
                continue

        path = Path(skill["path"])
        # manifest-declared tools (http)
        for tool in skill.get("tools") or []:
            name = tool.get("name")
            if not name:
                continue
            ttype = (tool.get("type") or "http").lower()
            if ttype != "http":
                continue
            handler = _make_http_handler(tool)
            registry.register(
                name,
                tool.get("description") or f"[skill:{skill_id}] {name}",
                handler,
                tool.get("parameters"),
                source="skill",
                metadata={"skill_id": skill_id, **{k: tool.get(k) for k in ("url", "method")}},
            )
            count += 1

        # optional handler.py with register(registry) or TOOLS list
        handler_py = path / "handler.py"
        if handler_py.exists():
            try:
                mod_name = f"skills_{path.name}_handler"
                spec = importlib.util.spec_from_file_location(mod_name, handler_py)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    if hasattr(mod, "register") and callable(mod.register):
                        before = {t.name for t in registry.list_tools()}
                        mod.register(registry)
                        # Force source="skill" + skill_id on newly registered tools
                        for t in registry.list_tools():
                            if t.name not in before:
                                t.source = "skill"
                                md = dict(t.metadata or {})
                                md.setdefault("skill_id", skill_id)
                                t.metadata = md
                        count += len({t.name for t in registry.list_tools()} - before)
                    elif hasattr(mod, "TOOLS"):
                        for tool_def in getattr(mod, "TOOLS") or []:
                            # expected dict with name, description, handler, parameters
                            registry.register(
                                tool_def["name"],
                                tool_def.get("description", ""),
                                tool_def["handler"],
                                tool_def.get("parameters"),
                                source="skill",
                                metadata={"skill_id": skill_id},
                            )
                            count += 1
            except Exception as _skill_err:
                logger.exception(
                    "Failed loading skill handler: %s - %s", path, _skill_err
                )

    return count
