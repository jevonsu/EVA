"""Primary / deputy LLM: local daily chat, deputy when this turn needs skills.

Does not change ``is_default``. Interactive chat, webhooks, workflows and
scheduled tasks may pass allow_deputy=True so skill work can use the deputy.
"""

from __future__ import annotations

from typing import Any

# Built-in cores used in daily chat — not a reason to switch.
_DAILY_TOOLS = frozenset(
    {
        "memory",
        "kb",
        "workspace",
        "get_current_time",
        "ask_user",
        "workflow",
        "scheduled_task",
        "integrations",
        "llms",
        "list_skills",
    }
)

# Writing / editing a skill is hard work; listing or deleting is not.
_SKILL_AUTHOR_TOOLS = frozenset(
    {
        "create_tool",
        "read_skill",
        "validate_skill",
        "promote_skill",
    }
)

_CONFIRM_MARKERS = (
    "用副模型",
    "用大模型",
    "用云端",
    "用deepseek",
    "换副模型",
    "副模型做",
    "用副的",
    "改用副",
)

_DECLINE_MARKERS = (
    "不用副",
    "不要副",
    "别用副",
    "主模型继续",
    "继续用主",
    "用主模型",
    "用本地",
    "本地就行",
    "skip_deputy",
)


def get_deputy_row() -> dict[str, Any] | None:
    try:
        from app.config_store import get_config_store

        return get_config_store().get_deputy_llm()
    except Exception:
        return None


def deputy_label(row: dict[str, Any] | None) -> str:
    if not row:
        return "副模型"
    return str(row.get("name") or row.get("model") or "副模型").strip() or "副模型"


def last_ask_pending(history: list[dict[str, Any]] | None) -> str:
    for m in reversed(history or []):
        if m.get("role") != "assistant":
            continue
        meta = m.get("metadata") or {}
        if not isinstance(meta, dict):
            return ""
        if meta.get("ask_deputy"):
            return str(meta.get("pending_user") or "").strip()
        return ""
    return ""


def _fold(message: str) -> str:
    return "".join((message or "").strip().lower().split())


def is_deputy_confirm(message: str) -> bool:
    t = _fold(message)
    if not t or len(t) > 40:
        return False
    if any(x.replace(" ", "") in t for x in _DECLINE_MARKERS):
        return False
    return any(x.replace(" ", "") in t for x in _CONFIRM_MARKERS)


def is_deputy_decline(message: str) -> bool:
    t = _fold(message)
    if not t or len(t) > 40:
        return False
    return any(x.replace(" ", "") in t for x in _DECLINE_MARKERS)


def resolve_pending_task(
    message: str,
    history: list[dict[str, Any]] | None,
    *,
    use_deputy: bool = False,
    skip_deputy: bool = False,
) -> tuple[str, bool, bool]:
    """If the last assistant asked to use the deputy, map a short reply back to the task."""
    pending = last_ask_pending(history)
    if not pending:
        return (message or "").strip(), bool(use_deputy), bool(skip_deputy)
    if use_deputy or skip_deputy:
        return pending, bool(use_deputy), bool(skip_deputy)
    if is_deputy_confirm(message):
        return pending, True, False
    if is_deputy_decline(message):
        return pending, False, True
    return (message or "").strip(), False, False


def _tool_source(name: str, tools: Any = None) -> str:
    if not tools or not name:
        return ""
    try:
        spec = tools.get(name)
    except Exception:
        return ""
    return str(getattr(spec, "source", "") or "")


def is_skill_work_tool(name: str, tools: Any = None) -> bool:
    """True if calling this tool means the turn should use the deputy."""
    n = (name or "").strip()
    if not n or n in _DAILY_TOOLS:
        return False
    if n in _SKILL_AUTHOR_TOOLS:
        return True
    src = _tool_source(n, tools)
    if src == "skill":
        return True
    if src in ("builtin", "custom"):
        return False
    # Unknown intent names count as skill work.
    return True


def _always_include() -> set[str]:
    try:
        from app.tools.registry import ToolRegistry

        return set(ToolRegistry._ALWAYS_INCLUDE)
    except Exception:
        return {"memory", "kb", "workspace", "get_current_time", "ask_user"}


def should_use_deputy(
    message: str,
    intent_force: set[str] | None,
    *,
    tools: Any = None,
) -> bool:
    """True when this turn needs a business skill (or to write/edit one).

    Daily chat, time, memory, KB, workspace, and「你有什么技能」stay on the
    primary model. No user prompt — the caller auto-switches.
    """
    t = (message or "").strip()
    authoring = False
    try:
        from app.agent.ask_form import skill_authoring_mode

        authoring = skill_authoring_mode(t) in {"create", "update"}
    except Exception:
        authoring = False
    if authoring:
        return True
    names: set[str] = {str(x).strip() for x in (intent_force or set()) if str(x).strip()}
    always = _always_include()
    if tools is not None and hasattr(tools, "filter_tools"):
        try:
            for schema in tools.filter_tools(t, force_tools=names) or []:
                fn = (schema.get("function") or {}) if isinstance(schema, dict) else {}
                n = str(fn.get("name") or "").strip()
                if not n:
                    continue
                if n in always and n not in names:
                    continue
                names.add(n)
        except Exception:
            pass
    for n in names:
        if n in _SKILL_AUTHOR_TOOLS:
            continue
        if is_skill_work_tool(n, tools):
            return True
    return False


def should_ask_deputy(message: str, intent_force: set[str] | None) -> bool:
    """Deprecated: skill work now auto-switches. Kept so old tests/imports hold."""
    _ = (message, intent_force)
    return False


def deputy_ask_text(row: dict[str, Any] | None) -> str:
    name = deputy_label(row)
    return (
        f"这件事更适合用副模型（{name}）来做，主模型保持不变。\n"
        "要用副模型做**这一件**吗？不会改掉默认模型。"
    )


def is_hard_llm_failure(exc: BaseException) -> bool:
    t = str(exc or "").lower()
    if not t:
        return False
    if "exceed" in t and "context" in t:
        return True
    keys = (
        "status code 5",
        " 502",
        " 503",
        " 504",
        "502 ",
        "503 ",
        "504 ",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
        "connection refused",
        "connection reset",
        "connect error",
        "connecterror",
        "timed out",
        "timeout",
        "server disconnected",
        "remoteprotocolerror",
        "readerror",
    )
    return any(k in t for k in keys)
