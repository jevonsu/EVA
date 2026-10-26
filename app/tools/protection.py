"""LLM mutability policy for tools / skills.

Policy
------
1. **Builtin tools** (registered with source=builtin) are always read-only:
   LLM cannot create_tool / update / delete them.

2. **Reserved names** cannot be used for new skills (even if not currently registered),
   so LLM cannot re-introduce removed workspace aliases or shadow builtins.

3. **Protected skills** (shipped platform packages under skills/) cannot be
   updated or deleted by create_tool / delete_tool. They can still be *read*
   via read_skill for inspection.

4. **All other skills** are fully mutable: LLM may create, update=true, and delete.

Currently protected skills are limited to *tool-system / runtime* packages.
Workspace FS is a builtin (``workspace``), not a skill package.
Domain skills (user-created packs) are intentionally mutable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Names that must never be claimed by a skill (builtins + retired aliases).
RESERVED_TOOL_NAMES: frozenset[str] = frozenset({
    # Core builtins
    "workspace",
    "memory",
    "get_current_time",
    "calculator",
    "system_info",
    "create_tool",
    "capability_groups",
    "delete_tool",
    "read_skill",
    "list_skills",
    "validate_skill",
    "promote_skill",
    "kb",
    "workflow",
    "scheduled_task",
    "integrations",
    "llms",
    "terminal",
    "document",
    "reload_runtime",
    "list_api_models",
    "server_health_check",
    "shell",
    # Retired workspace aliases (merged into workspace)
    "list_workspace",
    "read_workspace_file",
    "write_workspace_file",
    "delete_workspace_file",
    "find_files",
    "file_rename",
    "list_workspace_files",
    "delete_file",
    "explore_paths",
    "search_workspace_deep",
    "find_workspace",
    "save_markdown_doc",
    "read_chinese_path",
    # Retired HTTP aliases
    "http_get",
    "demo_http_echo",
    "fetch_url_content",
})

# Skill package ids under skills/ that LLM must not update or delete.
# (tool-system / runtime only — domain skills stay mutable.)
PROTECTED_SKILLS: frozenset[str] = frozenset({
    "reload_runtime",
    "list_api_models",
    "server_health_check",
    "terminal",
    "document",
})


def normalize_tool_name(name: str | None) -> str:
    return (name or "").strip().lower().replace(" ", "_")


def is_reserved_name(name: str | None) -> bool:
    return normalize_tool_name(name) in RESERVED_TOOL_NAMES


def is_protected_skill(name: str | None) -> bool:
    return normalize_tool_name(name) in PROTECTED_SKILLS


def is_builtin_tool(name: str | None) -> bool:
    """True if currently registered as source=builtin."""
    try:
        from app.tools.registry import get_tool_registry

        n = normalize_tool_name(name)
        if not n:
            return False
        spec = get_tool_registry().get(n)
        return bool(spec and spec.source == "builtin")
    except Exception:
        return False


def protection_reason(name: str | None) -> str | None:
    """If *name* must not be created/updated/deleted by LLM, return a short reason."""
    n = normalize_tool_name(name)
    if not n:
        return "empty name"
    if is_builtin_tool(n) or n in RESERVED_TOOL_NAMES:
        return (
            f"[{n}] 属于系统保留/builtin（含 workspace 与工具管理），"
            "LLM 不能创建、覆盖或删除"
        )
    if is_protected_skill(n):
        return (
            f"[{n}] 属于受保护的系统 skill（工具/运行时相关），"
            "LLM 不能 update 或 delete；可用 read_skill 查看"
        )
    return None


def can_llm_create(name: str | None) -> tuple[bool, str]:
    """Whether create_tool may create a *new* skill with this name."""
    n = normalize_tool_name(name)
    if not n:
        return False, "Invalid empty name"
    if is_reserved_name(n) or is_builtin_tool(n):
        return False, protection_reason(n) or "reserved"
    if is_protected_skill(n):
        # Creating a brand-new folder with a protected id should also be blocked
        # if the package is missing (prevents spoofing); if it exists, use update rules.
        return False, protection_reason(n) or "protected skill"
    return True, ""


def can_llm_update(name: str | None) -> tuple[bool, str]:
    """Whether create_tool(update=true) may overwrite this skill."""
    n = normalize_tool_name(name)
    if not n:
        return False, "Invalid empty name"
    if is_reserved_name(n) or is_builtin_tool(n):
        return False, protection_reason(n) or "reserved/builtin"
    if is_protected_skill(n):
        return False, protection_reason(n) or "protected skill"
    return True, ""


def can_llm_delete(name: str | None) -> tuple[bool, str]:
    """Whether delete_tool may remove this skill package."""
    return can_llm_update(name)


def protection_summary() -> dict[str, Any]:
    """For system_info / docs."""
    return {
        "policy": (
            "builtin + reserved names + protected skills 只读；"
            "其余 skills/ 下 skill 可由 LLM create / update / delete"
        ),
        "reserved_names": sorted(RESERVED_TOOL_NAMES),
        "protected_skills": sorted(PROTECTED_SKILLS),
        "mutable_hint": (
            "已安装的业务 skill 均可 create_tool(update=true) 或 delete_tool"
        ),
    }


def skill_package_exists(name: str) -> bool:
    from app.services.skills import skills_root

    n = normalize_tool_name(name)
    return bool(n) and (skills_root() / n).is_dir()
