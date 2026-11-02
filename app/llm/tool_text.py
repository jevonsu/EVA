"""Recover OpenAI-style tool_calls from models that emit DSML (DeepSeek V4) as text.

Some gateways / local templates leave DeepSeek DSML markup in ``message.content``
instead of (or in addition to) structured ``tool_calls``. EVA's agent loop only
understands OpenAI function calls — parse DSML into that shape and strip the
raw markup so users never see it.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Canonical token is fullwidth pipes: ｜DSML｜ (U+FF5C). Also accept ASCII |,
# doubled pipes, and optional whitespace (copy/paste / tokenizer quirks).
_PIPE = r"[|｜]{1,2}"
_DSML = rf"{_PIPE}\s*DSML\s*{_PIPE}"
_BLOCK_NAMES = r"(?:tool_calls|toolcalls|tool_call|tools|calls|tool)"

_BLOCK_RE = re.compile(
    rf"<{_DSML}\s*{_BLOCK_NAMES}\s*>.*?</{_DSML}\s*{_BLOCK_NAMES}\s*>",
    re.DOTALL | re.IGNORECASE,
)
_INVOKE_RE = re.compile(
    rf"<{_DSML}\s*invoke\s+name\s*=\s*[\"']([^\"']+)[\"']\s*>"
    rf"(.*?)"
    rf"</{_DSML}\s*invoke\s*>",
    re.DOTALL | re.IGNORECASE,
)
_PARAM_RE = re.compile(
    rf"<{_DSML}\s*parameter\s+name\s*=\s*[\"']([^\"']+)[\"']"
    rf"(?:\s+string\s*=\s*[\"']([^\"']*)[\"'])?\s*>"
    rf"(.*?)"
    rf"</{_DSML}\s*parameter\s*>",
    re.DOTALL | re.IGNORECASE,
)
# Orphan / truncated markup leftovers (never show to user)
_ORPHAN_TAG_RE = re.compile(
    rf"</?{_DSML}\s*(?:{_BLOCK_NAMES}|invoke|parameter)[^>]*>",
    re.IGNORECASE,
)
_HAS_DSML_RE = re.compile(rf"{_PIPE}\s*DSML\s*{_PIPE}", re.IGNORECASE)


def looks_like_dsml(text: str | None) -> bool:
    if not text:
        return False
    return bool(_HAS_DSML_RE.search(text))


def _coerce_param(raw: str, is_string: str | None) -> Any:
    value = raw if raw is not None else ""
    # string="true" → keep literal; missing / false → try JSON
    if (is_string or "").strip().lower() == "true":
        return value
    text = value.strip()
    if not text:
        return value
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError, TypeError):
        return value


def _invokes_to_tool_calls(invokes: list[re.Match[str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, m in enumerate(invokes):
        name = (m.group(1) or "").strip()
        body = m.group(2) or ""
        if not name:
            continue
        args: dict[str, Any] = {}
        for pm in _PARAM_RE.finditer(body):
            key = (pm.group(1) or "").strip()
            if not key:
                continue
            args[key] = _coerce_param(pm.group(3) or "", pm.group(2))
        out.append(
            {
                "id": f"dsml_{uuid.uuid4().hex[:12]}_{i}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
        )
    return out


def extract_dsml_tool_calls(text: str | None) -> tuple[str, list[dict[str, Any]]]:
    """Parse DSML tool markup from assistant text.

    Returns ``(cleaned_text, tool_calls)`` where ``tool_calls`` is OpenAI-shaped.
    Always strips DSML (and orphan tags) from the returned text, even when no
    complete invoke was parsed — so raw markup never reaches the UI.
    """
    raw = text if isinstance(text, str) else ("" if text is None else str(text))
    if not raw or not looks_like_dsml(raw):
        return raw, []

    tool_calls: list[dict[str, Any]] = []
    cleaned = raw

    # Prefer whole tool_calls blocks; fall back to bare invoke tags.
    blocks = list(_BLOCK_RE.finditer(cleaned))
    if blocks:
        for bm in blocks:
            tool_calls.extend(
                _invokes_to_tool_calls(list(_INVOKE_RE.finditer(bm.group(0))))
            )
        cleaned = _BLOCK_RE.sub("", cleaned)
    else:
        invokes = list(_INVOKE_RE.finditer(cleaned))
        if invokes:
            tool_calls.extend(_invokes_to_tool_calls(invokes))
            cleaned = _INVOKE_RE.sub("", cleaned)

    cleaned = _ORPHAN_TAG_RE.sub("", cleaned)
    cleaned = re.sub(rf"{_PIPE}\s*DSML\s*{_PIPE}", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    if tool_calls:
        logger.info(
            "Recovered %s tool call(s) from DSML text: %s",
            len(tool_calls),
            ", ".join(
                (tc.get("function") or {}).get("name") or "?" for tc in tool_calls
            ),
        )
    elif looks_like_dsml(raw):
        logger.warning(
            "Stripped DSML markup from assistant text but parsed 0 tool calls"
        )

    return cleaned, tool_calls


def merge_dsml_into_completion(result: dict[str, Any] | None) -> dict[str, Any]:
    """Mutate/return a chat completion dict: strip DSML content, attach tool_calls."""
    if not isinstance(result, dict):
        return result or {}
    content = result.get("content")
    if not isinstance(content, str) or not looks_like_dsml(content):
        return result
    cleaned, parsed = extract_dsml_tool_calls(content)
    result["content"] = cleaned or None
    if not parsed:
        return result
    existing = result.get("tool_calls")
    if isinstance(existing, list) and existing:
        seen: set[tuple[str, str]] = set()
        for tc in existing:
            fn = tc.get("function") if isinstance(tc, dict) else None
            if isinstance(fn, dict):
                seen.add((str(fn.get("name") or ""), str(fn.get("arguments") or "")))
        for tc in parsed:
            fn = tc.get("function") or {}
            key = (str(fn.get("name") or ""), str(fn.get("arguments") or ""))
            if key not in seen:
                existing.append(tc)
                seen.add(key)
        result["tool_calls"] = existing
    else:
        result["tool_calls"] = parsed
    if not result.get("finish_reason") or result.get("finish_reason") == "stop":
        result["finish_reason"] = "tool_calls"
    return result
