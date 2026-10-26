"""Look up installed tools by name or capability group (no hardcoded skill ids)."""

from __future__ import annotations

from typing import Any


def tool_registered(name: str) -> bool:
    n = (name or "").strip()
    if not n:
        return False
    try:
        from app.tools.registry import get_tool_registry

        return bool(get_tool_registry().get(n))
    except Exception:
        return False


def tools_in_group(group: str) -> list[str]:
    g = (group or "").strip().lower()
    if not g:
        return []
    try:
        from app.tools.registry import get_tool_registry
        from app.tools.tool_meta import meta_for

        out: list[str] = []
        for spec in get_tool_registry().list_tools():
            mg = str((meta_for(spec.name) or {}).get("group") or "").lower()
            if mg == g:
                out.append(spec.name)
        return out
    except Exception:
        return []


def has_group(group: str) -> bool:
    return bool(tools_in_group(group))


def first_in_group(group: str) -> str:
    names = tools_in_group(group)
    return names[0] if names else ""


def tool_group(name: str) -> str:
    try:
        from app.tools.tool_meta import meta_for

        return str((meta_for(name) or {}).get("group") or "").strip().lower()
    except Exception:
        return ""
