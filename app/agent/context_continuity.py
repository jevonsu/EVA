"""Helpers for next-turn tool context, task state, and secret redaction.

Kept independent of Agent so unit tests can import this module without
booting the full chat loop. Tool transcripts are restored as a text
block (not role=tool messages) so DeepSeek-style OpenAI-compatible
APIs never see unmatched tool_call ids.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

TOOL_RESULT_STORE_CHARS = 2000
TOOL_RESULT_PROMPT_CHARS = 800
PREV_TOOLS_BLOCK_CHARS = 2500
PREV_TOOLS_BLOCK_CHARS_TIGHT = 1200
TASK_STATE_CHARS = 800
TASK_STATE_CHARS_TIGHT = 400

_SECRET_KEYS = frozenset(
    {
        "confirm_token",
        "token",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "password",
        "passwd",
        "secret",
        "authorization",
        "auth",
        "credential",
        "private_key",
    }
)

# JSON / text confirm tokens and common secret fields.
_RE_JSON_SECRET = re.compile(
    r'(?i)("(?:confirm_token|api[_-]?key|access[_-]?token|refresh[_-]?token|'
    r'password|passwd|secret|authorization|private_key)"\s*:\s*")([^"]*)(")'
)
_RE_KV_SECRET = re.compile(
    r"(?i)\b(confirm_token|api[_-]?key|access[_-]?token|password|passwd|secret)"
    r"(\s*[=:]\s*)(\S+)"
)
_FOLLOWUP_KEYS = (
    "继续",
    "再来",
    "再做",
    "再跑",
    "同样",
    "一样",
    "那个",
    "这个也",
    "还是",
    "搞一下",
    "弄一下",
    "改一下",
    "再处理",
    "同上",
    "刚才",
    "跟上次",
)


def redact_sensitive_tool_text(text: str) -> str:
    """Mask confirm tokens and common secrets in tool text (UI and storage)."""
    s = text if isinstance(text, str) else str(text or "")
    if not s:
        return ""
    try:
        from app.services.process_control import mask_secrets

        s = mask_secrets(s)
    except Exception:
        pass
    s = _RE_JSON_SECRET.sub(r"\1***\3", s)
    s = _RE_KV_SECRET.sub(r"\1\2***", s)
    return s


def _is_secret_key(key: str) -> bool:
    k = re.sub(r"[^a-z0-9]", "", (key or "").lower())
    if k in _SECRET_KEYS:
        return True
    return any(s in k for s in ("password", "secret", "apikey", "token"))


def redact_tool_args(args: Any, *, max_str: int = 80) -> dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    out: dict[str, Any] = {}
    for key, val in args.items():
        if _is_secret_key(str(key)):
            out[key] = "***"
            continue
        if isinstance(val, str):
            clipped = val if len(val) <= max_str else val[:max_str] + "…"
            out[key] = redact_sensitive_tool_text(clipped)
        else:
            out[key] = val
    return out


def clip_tool_result_for_storage(name: str, text: str, *, limit: int = TOOL_RESULT_STORE_CHARS) -> str:
    raw = redact_sensitive_tool_text(text or "")
    cap = max(200, int(limit or TOOL_RESULT_STORE_CHARS))
    if name in ("read_skill", "validate_skill") and "def register" in raw[:800]:
        # Keep a short pointer; full skill source does not belong in session metadata.
        return raw[: min(cap, 400)] + ("…" if len(raw) > min(cap, 400) else "")
    if len(raw) <= cap:
        return raw
    return raw[:cap] + f"\n…[truncated {len(raw) - cap} chars]"


def tool_calls_from_message(m: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(m, dict):
        return []
    meta = m.get("metadata") if isinstance(m.get("metadata"), dict) else {}
    raw = meta.get("tool_calls") or m.get("tool_calls") or []
    if not isinstance(raw, list):
        return []
    return [tc for tc in raw if isinstance(tc, dict)]


def _arg_hint(args: Any) -> str:
    if not isinstance(args, dict):
        return ""
    for key in ("path", "action", "query", "name", "id", "title", "pid"):
        val = args.get(key)
        if isinstance(val, str) and val.strip() and not _is_secret_key(key):
            return f"{key}={val.strip()[:60]}"
    return ""


def format_previous_tools_block(
    tool_calls: list[dict[str, Any]],
    *,
    max_chars: int = PREV_TOOLS_BLOCK_CHARS,
    per_result: int = TOOL_RESULT_PROMPT_CHARS,
) -> str:
    if not tool_calls:
        return ""
    lines = [
        "[Previous tool results — not shown to the user; use this to continue the task]"
    ]
    budget = max(200, int(max_chars or PREV_TOOLS_BLOCK_CHARS))
    used = len(lines[0]) + 1
    for i, tc in enumerate(tool_calls, 1):
        name = str(tc.get("name") or "?").strip() or "?"
        hint = _arg_hint(tc.get("arguments"))
        body = tc.get("result_llm") or tc.get("result") or ""
        body = redact_sensitive_tool_text(str(body))
        if len(body) > per_result:
            body = body[:per_result] + "…"
        line = f"{i}. {name}" + (f"({hint})" if hint else "()") + (f" → {body}" if body else "")
        if used + len(line) + 1 > budget and i > 1:
            lines.append("…[older tool results in this turn omitted]")
            break
        if used + len(line) + 1 > budget:
            line = line[: max(0, budget - used - 1)] + "…"
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines).strip()


def sanitize_message_for_llm(m: dict[str, Any], max_content: int = 0) -> dict[str, Any]:
    """Copy role/content only. Never emit metadata or reconstructed tool_calls."""
    content = m.get("content")
    if max_content and isinstance(content, str) and len(content) > max_content:
        content = content[:max_content] + "…"
    role = m.get("role") or "user"
    out: dict[str, Any] = {"role": role, "content": content}
    # Keep genuine in-turn OpenAI tool messages only (not session metadata).
    if role == "assistant" and isinstance(m.get("tool_calls"), list) and m.get("tool_calls"):
        # Session history does not store top-level tool_calls; this branch is
        # for already-built in-turn messages if they are re-sanitized.
        out["tool_calls"] = m["tool_calls"]
    if role == "tool":
        if m.get("tool_call_id"):
            out["tool_call_id"] = m["tool_call_id"]
        if m.get("name"):
            out["name"] = m["name"]
    return out


def history_messages_for_llm(
    history: list[dict[str, Any]],
    *,
    max_content: int = 0,
    recent_tool_turns: int = 2,
    tools_block_chars: int = 0,
) -> list[dict[str, Any]]:
    """Rebuild session history for the model with recent tool process restored.

    Uses a text appendix on the last *recent_tool_turns* assistant messages
    that have metadata.tool_calls, instead of role=tool messages, so the
    OpenAI-compatible payload stays valid without original tool_call ids.
    """
    if not history:
        return []
    tool_indexes: list[int] = []
    for i, m in enumerate(history):
        if m.get("role") == "assistant" and tool_calls_from_message(m):
            tool_indexes.append(i)
    restore = set(tool_indexes[-max(0, int(recent_tool_turns)) :])
    cap = int(tools_block_chars) if tools_block_chars else (
        PREV_TOOLS_BLOCK_CHARS_TIGHT if max_content and max_content <= 1200 else PREV_TOOLS_BLOCK_CHARS
    )
    out: list[dict[str, Any]] = []
    for i, m in enumerate(history):
        role = m.get("role")
        if role == "system":
            continue
        item = sanitize_message_for_llm(m, max_content=max_content)
        if i in restore:
            block = format_previous_tools_block(
                tool_calls_from_message(m),
                max_chars=cap,
            )
            if block:
                content = item.get("content")
                if content is None:
                    content = ""
                elif not isinstance(content, str):
                    content = str(content)
                item["content"] = (content + "\n\n" + block).strip()
        # Never pass a trailing assistant tool_calls without tool results.
        if item.get("role") != "tool":
            item.pop("tool_call_id", None)
        if item.get("role") != "assistant" or not item.get("tool_calls"):
            item.pop("tool_calls", None)
        # If we only have metadata-derived tools, do not set tool_calls.
        if i in restore:
            item.pop("tool_calls", None)
        out.append(item)
    return out


def format_message_for_compact(m: dict[str, Any], *, content_cap: int = 800) -> str:
    """One transcript line for session evolution, including tool summaries."""
    role = m.get("role") or "?"
    if role == "system":
        return ""
    content = str(m.get("content") or "").strip()
    if len(content) > content_cap:
        content = content[:content_cap] + "…"
    tools = tool_calls_from_message(m)
    if tools:
        bits: list[str] = []
        for tc in tools[:8]:
            name = str(tc.get("name") or "?").strip() or "?"
            hint = _arg_hint(tc.get("arguments"))
            body = redact_sensitive_tool_text(str(tc.get("result_llm") or tc.get("result") or ""))
            if len(body) > 220:
                body = body[:220] + "…"
            bits.append(name + (f"({hint})" if hint else "()") + (f"→{body}" if body else ""))
        tool_s = "tools: " + "; ".join(bits)
        content = (content + ("\n" if content else "") + tool_s).strip()
    elif not content:
        meta = m.get("metadata") if isinstance(m.get("metadata"), dict) else {}
        used = meta.get("tools_used")
        if used:
            content = f"(tools: {used})"
    if not content:
        return ""
    return f"{role}: {content}"


def compact_messages_newest_first(
    messages: list[dict[str, Any]],
    *,
    max_chars: int = 6000,
    content_cap: int = 800,
) -> str:
    """Compress a message range, preferring newer turns when the budget is tight."""
    parts: list[str] = []
    total = 0
    omitted = 0
    for m in reversed(list(messages or [])):
        line = format_message_for_compact(m, content_cap=content_cap)
        if not line:
            continue
        if total + len(line) + 1 > max_chars:
            if not parts:
                # Always keep a clipped copy of the newest turn.
                room = max(40, max_chars - total - 40)
                parts.append(line[:room] + "…")
            omitted += 1
            # Remaining items are older; stop so newer context is kept.
            break
        parts.append(line)
        total += len(line) + 1
    parts.reverse()
    if omitted:
        parts.insert(0, f"…({omitted} older messages omitted for compression)…")
    return "\n".join(parts)


def looks_like_followup(message: str) -> bool:
    t = (message or "").strip()
    if not t:
        return False
    if any(k in t for k in _FOLLOWUP_KEYS):
        return True
    compact = "".join(t.split())
    return len(compact) <= 6 and any(k in compact for k in ("好", "行", "嗯", "继续", "再", "那个"))


def _one_line(text: str, cap: int) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= cap:
        return t
    return t[: cap - 1].rstrip() + "…"


def _record_parts(rec: Any) -> tuple[str, dict[str, Any], str]:
    if isinstance(rec, dict):
        name = str(rec.get("name") or "")
        args = rec.get("arguments") if isinstance(rec.get("arguments"), dict) else {}
        result = str(rec.get("result") or "")
        return name, args, result
    name = str(getattr(rec, "name", "") or "")
    args = getattr(rec, "arguments", None)
    args = args if isinstance(args, dict) else {}
    result = str(getattr(rec, "result", "") or "")
    return name, args, result


def build_task_state(
    *,
    prev: dict[str, Any] | None = None,
    user_message: str = "",
    assistant: str = "",
    tool_records: list[Any] | None = None,
    paths: list[str] | None = None,
    is_followup: bool | None = None,
) -> dict[str, Any]:
    """Heuristic working-memory snapshot for this session (no extra LLM call)."""
    prev = prev if isinstance(prev, dict) else {}
    if is_followup is None:
        is_followup = looks_like_followup(user_message)
    goal = str(prev.get("goal") or "").strip()
    if not is_followup or not goal:
        goal = _one_line(user_message, 200)
    step = _one_line(assistant, 200) or str(prev.get("step") or "").strip()
    artifacts: list[str] = []
    seen: set[str] = set()
    harvested: list[str] = []
    for rec in tool_records or []:
        _n, args, result = _record_parts(rec)
        for key in ("path", "source", "dest", "filename", "script_path"):
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                harvested.append(val.strip().replace("\\", "/"))
        for m in re.findall(
            r"(?:uploads|images|videos|temp|workspace)[/\\][\w.\-]+",
            result or "",
            flags=re.I,
        ):
            harvested.append(m.replace("\\", "/"))
    for item in list(prev.get("artifacts") or []) + list(paths or []) + harvested:
        p = str(item or "").strip().replace("\\", "/")
        if not p or p in seen:
            continue
        seen.add(p)
        artifacts.append(p)
        if len(artifacts) >= 8:
            break
    conclusions: list[str] = []
    records = list(tool_records or [])
    if records:
        for rec in records[-6:]:
            name, args, result = _record_parts(rec)
            name = (name or "?").strip() or "?"
            hint = _arg_hint(redact_tool_args(args, max_str=40))
            body = redact_sensitive_tool_text(result)
            body = _one_line(body, 180)
            conclusions.append(name + (f"({hint})" if hint else "") + (f": {body}" if body else ""))
    else:
        for item in list(prev.get("tool_conclusions") or [])[:6]:
            s = str(item or "").strip()
            if s:
                conclusions.append(s[:240])
    return {
        "goal": goal,
        "step": step,
        "artifacts": artifacts,
        "tool_conclusions": conclusions,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def render_task_state_block(state: dict[str, Any] | None, *, max_chars: int = TASK_STATE_CHARS) -> str:
    if not isinstance(state, dict):
        return ""
    goal = str(state.get("goal") or "").strip()
    step = str(state.get("step") or "").strip()
    artifacts = [str(p).strip() for p in (state.get("artifacts") or []) if str(p).strip()]
    conclusions = [str(c).strip() for c in (state.get("tool_conclusions") or []) if str(c).strip()]
    if not (goal or step or artifacts or conclusions):
        return ""
    lines = [
        "TASK STATE (this conversation's working memory — valid for continuing the task; not an SOP):",
    ]
    if goal:
        lines.append(f"Goal: {goal}")
    if step:
        lines.append(f"Current step: {step}")
    if artifacts:
        lines.append("Artifacts: " + "; ".join(artifacts[:8]))
    if conclusions:
        lines.append("Latest tools:")
        for c in conclusions[:6]:
            lines.append(f"- {c}")
    block = "\n".join(lines).strip()
    cap = max(200, int(max_chars or TASK_STATE_CHARS))
    if len(block) > cap:
        block = block[: cap - 1] + "…"
    return block
