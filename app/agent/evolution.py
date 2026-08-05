"""Per-session evolving context (running summary / scratchpad).

When a conversation grows past a configurable message threshold, older turns
are compressed into a structured evolution digest that is re-injected each turn.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Defaults (overridable via config.agent.*)
DEFAULT_EVOLUTION_ENABLED = True
DEFAULT_EVOLUTION_TRIGGER = 24  # messages since last evolve (or total if never)
DEFAULT_EVOLUTION_KEEP = 16  # raw messages kept after compress
DEFAULT_EVOLUTION_MAX_ENTRIES = 12  # bullet entries in digest
DEFAULT_EVOLUTION_MAX_CHARS = 2200


def evolution_settings(agent_cfg: dict[str, Any] | None) -> dict[str, Any]:
    cfg = agent_cfg or {}
    enabled = cfg.get("evolution_enabled")
    if enabled is None:
        enabled = DEFAULT_EVOLUTION_ENABLED
    try:
        trigger = int(cfg.get("evolution_trigger_messages") or DEFAULT_EVOLUTION_TRIGGER)
    except (TypeError, ValueError):
        trigger = DEFAULT_EVOLUTION_TRIGGER
    try:
        keep = int(cfg.get("evolution_keep_messages") or DEFAULT_EVOLUTION_KEEP)
    except (TypeError, ValueError):
        keep = DEFAULT_EVOLUTION_KEEP
    try:
        max_entries = int(cfg.get("evolution_max_entries") or DEFAULT_EVOLUTION_MAX_ENTRIES)
    except (TypeError, ValueError):
        max_entries = DEFAULT_EVOLUTION_MAX_ENTRIES
    try:
        max_chars = int(cfg.get("evolution_max_chars") or DEFAULT_EVOLUTION_MAX_CHARS)
    except (TypeError, ValueError):
        max_chars = DEFAULT_EVOLUTION_MAX_CHARS

    trigger = max(6, min(trigger, 200))
    keep = max(4, min(keep, 80))
    max_entries = max(4, min(max_entries, 40))
    max_chars = max(400, min(max_chars, 8000))
    # keep must be < trigger or evolution never reduces pressure
    if keep >= trigger:
        keep = max(4, trigger // 2)

    return {
        "enabled": bool(enabled),
        "trigger_messages": trigger,
        "keep_messages": keep,
        "max_entries": max_entries,
        "max_chars": max_chars,
    }


def empty_evolution() -> dict[str, Any]:
    return {
        "version": 0,
        "text": "",
        "entries": [],
        "updated_at": None,
        "message_count_at_update": 0,
        "messages_since_update": 0,
    }


def normalize_evolution(raw: Any) -> dict[str, Any]:
    base = empty_evolution()
    if not isinstance(raw, dict):
        return base
    base["version"] = int(raw.get("version") or 0)
    base["text"] = str(raw.get("text") or "")
    ents = raw.get("entries")
    if isinstance(ents, list):
        clean: list[dict[str, str]] = []
        for e in ents:
            if isinstance(e, dict) and str(e.get("content") or "").strip():
                clean.append(
                    {
                        "kind": str(e.get("kind") or "fact")[:32],
                        "content": str(e.get("content") or "").strip()[:500],
                    }
                )
            elif isinstance(e, str) and e.strip():
                clean.append({"kind": "fact", "content": e.strip()[:500]})
        base["entries"] = clean
    base["updated_at"] = raw.get("updated_at")
    try:
        base["message_count_at_update"] = int(raw.get("message_count_at_update") or 0)
    except (TypeError, ValueError):
        base["message_count_at_update"] = 0
    return base


def render_evolution_block(evo: dict[str, Any] | None, *, max_chars: int = 2200) -> str:
    """System-prompt block for the current evolution digest."""
    evo = normalize_evolution(evo)
    entries = evo.get("entries") or []
    text = (evo.get("text") or "").strip()
    if not entries and not text:
        return ""

    lines = [
        "SESSION EVOLUTION (running summary of this conversation — authoritative for prior decisions):",
        "Treat the items below as established context. Prefer them over vague recall of early turns.",
        "If the user corrects something here, obey the correction.",
        "",
    ]
    if entries:
        for i, e in enumerate(entries, 1):
            kind = (e.get("kind") or "fact").strip()
            content = (e.get("content") or "").strip()
            lines.append(f"{i}. [{kind}] {content}")
    elif text:
        lines.append(text)

    block = "\n".join(lines).strip()
    if len(block) > max_chars:
        block = block[: max_chars - 1] + "…"
    return block


def should_evolve(
    *,
    message_count: int,
    evolution: dict[str, Any] | None,
    settings: dict[str, Any],
) -> bool:
    if not settings.get("enabled"):
        return False
    if message_count < 4:
        return False
    evo = normalize_evolution(evolution)
    at = int(evo.get("message_count_at_update") or 0)
    # messages accumulated since last evolve
    since = max(0, message_count - at)
    trigger = int(settings.get("trigger_messages") or DEFAULT_EVOLUTION_TRIGGER)
    # First evolve when total hits trigger; later when since >= trigger
    if at <= 0:
        return message_count >= trigger
    return since >= trigger


def _compact_messages_for_prompt(messages: list[dict[str, Any]], *, max_chars: int = 6000) -> str:
    parts: list[str] = []
    total = 0
    for m in messages:
        role = m.get("role") or "?"
        if role == "system":
            continue
        content = str(m.get("content") or "").strip()
        if not content and m.get("metadata"):
            meta = m.get("metadata") or {}
            content = f"(tools: {meta.get('tools_used') or '…'})"
        if not content:
            continue
        # drop huge blobs
        if len(content) > 800:
            content = content[:800] + "…"
        line = f"{role}: {content}"
        if total + len(line) > max_chars:
            parts.append("…(earlier messages truncated for compression)…")
            break
        parts.append(line)
        total += len(line) + 1
    return "\n".join(parts)


async def evolve_session_context(
    *,
    llm: Any,
    previous: dict[str, Any] | None,
    messages_to_compress: list[dict[str, Any]],
    latest_user: str = "",
    latest_assistant: str = "",
    settings: dict[str, Any] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Call LLM to merge prior evolution + older turns into a fresh digest."""
    settings = settings or evolution_settings({})
    max_entries = int(settings.get("max_entries") or DEFAULT_EVOLUTION_MAX_ENTRIES)
    max_chars = int(settings.get("max_chars") or DEFAULT_EVOLUTION_MAX_CHARS)
    prev = normalize_evolution(previous)

    transcript = _compact_messages_for_prompt(messages_to_compress, max_chars=max_chars * 2)
    prev_block = render_evolution_block(prev, max_chars=max_chars) or "(none yet)"

    system = (
        "You maintain a RUNNING SESSION EVOLUTION digest for an AI agent.\n"
        "Compress prior context into durable, high-signal bullets so later turns stay coherent "
        "after old messages are dropped.\n"
        "Rules:\n"
        f"- Output STRICT JSON only: {{\"entries\":[{{\"kind\":\"...\",\"content\":\"...\"}}],\"text\":\"optional prose\"}}\n"
        f"- At most {max_entries} entries; each content ≤ 200 Chinese chars or 120 English words.\n"
        "- kind ∈ goal|decision|fact|constraint|stage|open|artifact|preference\n"
        "- Keep: user goals, confirmed decisions, product facts (可确认/推测/待补), platform/audience, "
        "current stage in multi-step flows, file paths/artifacts, open questions.\n"
        "- Drop: chit-chat, failed tool noise, full prompts longer than one line (summarize instead).\n"
        "- Merge/update old evolution; correct superseded decisions.\n"
        "- Language: match the conversation (usually Chinese).\n"
        "- No markdown fences."
    )
    user = (
        f"PREVIOUS EVOLUTION:\n{prev_block}\n\n"
        f"MESSAGES TO COMPRESS:\n{transcript or '(none)'}\n\n"
        f"LATEST USER:\n{(latest_user or '')[:600]}\n\n"
        f"LATEST ASSISTANT (summary ok):\n{(latest_assistant or '')[:600]}\n\n"
        f"Return JSON with ≤{max_entries} entries."
    )

    try:
        result = await llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            tools=None,
            model=model,
            temperature=0.2,
        )
        raw = (result.get("content") or "").strip()
        data = _parse_json_object(raw)
    except Exception:
        logger.exception("Session evolution LLM failed; using heuristic fallback")
        data = _heuristic_evolution(prev, messages_to_compress, latest_user, latest_assistant)

    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        entries = _heuristic_evolution(
            prev, messages_to_compress, latest_user, latest_assistant
        ).get("entries") or []

    clean_entries: list[dict[str, str]] = []
    for e in entries[:max_entries]:
        if not isinstance(e, dict):
            continue
        content = str(e.get("content") or "").strip()
        if not content:
            continue
        kind = str(e.get("kind") or "fact").strip().lower()[:32]
        if kind not in (
            "goal",
            "decision",
            "fact",
            "constraint",
            "stage",
            "open",
            "artifact",
            "preference",
        ):
            kind = "fact"
        clean_entries.append({"kind": kind, "content": content[:400]})

    text = ""
    if isinstance(data, dict) and data.get("text"):
        text = str(data.get("text") or "").strip()[: max_chars // 2]
    if not text and clean_entries:
        text = "；".join(f"{e['kind']}:{e['content']}" for e in clean_entries)[:max_chars]

    return {
        "version": int(prev.get("version") or 0) + 1,
        "text": text,
        "entries": clean_entries,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "message_count_at_update": 0,  # filled by caller
    }


def _parse_json_object(raw: str) -> dict[str, Any]:
    s = (raw or "").strip()
    if not s:
        return {}
    # strip ```json fences if any
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", s)
        if not m:
            return {}
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            return {}


def _heuristic_evolution(
    prev: dict[str, Any],
    messages: list[dict[str, Any]],
    latest_user: str,
    latest_assistant: str,
) -> dict[str, Any]:
    """Fallback without LLM: keep prior entries + last user intent."""
    entries = list(prev.get("entries") or [])
    if latest_user.strip():
        entries.append(
            {
                "kind": "goal",
                "content": f"最近用户意图：{latest_user.strip()[:180]}",
            }
        )
    # pull path-like tokens from recent assistant
    paths = re.findall(
        r"(?:uploads|images|videos|temp|workspace)[/\w.\-]+",
        latest_assistant or "",
        flags=re.I,
    )
    for p in paths[:3]:
        entries.append({"kind": "artifact", "content": f"相关路径：{p}"})
    # dedupe by content
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for e in reversed(entries):
        c = (e.get("content") if isinstance(e, dict) else str(e)) or ""
        c = str(c).strip()
        if not c or c in seen:
            continue
        seen.add(c)
        if isinstance(e, dict):
            out.append(
                {
                    "kind": str(e.get("kind") or "fact")[:32],
                    "content": c[:400],
                }
            )
        else:
            out.append({"kind": "fact", "content": c[:400]})
        if len(out) >= 12:
            break
    out.reverse()
    return {"entries": out, "text": ""}
