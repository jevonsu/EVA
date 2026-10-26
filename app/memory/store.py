"""Long-term memory store (SQL) with match-based ranking."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, insert, select, update

from app.models.schemas import MemoryItem
from app.storage.engine import db_connect
from app.storage.schema import memories as memories_t
from app.storage.util import loads, run_db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tokenize(text: str) -> set[str]:
    """Score tokens: no single CJK chars (those make long notes match every query)."""
    tokens: set[str] = set()
    for t in re.split(r"[\s,.;:!?/\\|_+\-*=()\[\]{}\"'`]+", (text or "").lower()):
        if len(t) >= 2:
            tokens.add(t)
    chn_chars = re.findall(r"[一-鿿]", text or "")
    if not chn_chars:
        return tokens
    for i in range(len(chn_chars) - 1):
        tokens.add(chn_chars[i] + chn_chars[i + 1])
    for seg in re.findall(r"[一-鿿]{3,}", text or ""):
        tokens.add(seg)
    return tokens


_PIN_TAGS = frozenset({"always", "pin", "全局", "始终", "永久规则", "standing"})
_MIN_MATCH_SCORE = 2.0
_LONG_MEM_CHARS = 200
_MATCH_BODY_CHARS = 280
_LONG_POINTER_HEAD = 120


def is_pin_row(row: dict[str, Any]) -> bool:
    """Explicit pin tags only — kind=rule is not a standing pin."""
    tags = {str(t).lower() for t in (row.get("tags") or [])}
    return bool(tags & _PIN_TAGS)


_SOURCE_RE = re.compile(
    r"\b(def register\s*\(|async def handle\s*\(|registry\.register\s*\(|"
    r"from app\.tools|handler\.py|```(?:python|py|js)\b)",
    re.I,
)
_BROKEN_RE = re.compile(
    r"^(错误|失败|error\s*:|traceback|exception\b)|【长文截断",
    re.I,
)


def looks_like_source(content: str) -> bool:
    t = (content or "").strip()
    if not t:
        return False
    if _SOURCE_RE.search(t):
        return True
    head = t[:400]
    if t.count("\n") >= 8 and (
        ("from app" in head or "registry.register" in head)
        or ("import " in head and ("def " in t or "async def " in t or "class " in t))
    ):
        return True
    return False


def looks_broken_note(content: str) -> bool:
    t = (content or "").strip()
    if not t:
        return True
    if _BROKEN_RE.search(t) and len(t) < 240:
        return True
    if t in ("…", "...", "null", "undefined"):
        return True
    return False


def looks_long_procedure(content: str) -> bool:
    t = (content or "").strip()
    if looks_like_source(t):
        return True
    if len(t) > _LONG_MEM_CHARS:
        return True
    marks = len(re.findall(r"[①②③④⑤⑥⑦⑧⑨⑩]|[1-9][\.、．)]\s*\S", t))
    return marks >= 3


def format_memory_body(content: str) -> str:
    """Never inject a truncated SOP or source dump as if it were the full rule."""
    t = (content or "").strip()
    if looks_broken_note(t):
        return ""
    if looks_like_source(t):
        return "【已跳过：记忆里像源码/工具结果，对话中不要粘贴执行】"
    if looks_long_procedure(t):
        head = t[:_LONG_POINTER_HEAD].split("\n", 1)[0].strip()
        if len(t) > _LONG_POINTER_HEAD:
            head = head[:_LONG_POINTER_HEAD] + "…"
        return f"{head} 【长文截断：流程/标准以知识库为准，勿按本条执行】"
    if len(t) > _MATCH_BODY_CHARS:
        return t[:_MATCH_BODY_CHARS] + "…"
    return t


def _overlap_terms(row: dict[str, Any], terms: list[str] | set[str] | None) -> bool:
    if not terms:
        return False
    content = str(row.get("content") or "")
    tags = [str(t) for t in (row.get("tags") or [])]
    blob = f"{content} {' '.join(tags)}".lower()
    for term in terms:
        tl = str(term or "").strip().lower()
        if len(tl) < 4:
            continue
        if tl in blob:
            return True
        for tag in tags:
            tg = tag.lower()
            if len(tg) >= 4 and (tg in tl or tl in tg):
                return True
    return False


def render_memory_context(
    items: list[dict[str, Any]],
    query: str,
    *,
    suppress_terms: list[str] | None = None,
    limit: int = 5,
    max_chars: int = 1800,
    max_pin: int = 6,
) -> str:
    """Build the system-prompt memory block from already-loaded rows.

    Standing pins are explicit-tag only and ordered stably (created_at, id) so
    editing an unrelated note cannot reshuffle the constitution.
    Long notes overlapping the knowledge base are dropped.
    """
    if not items:
        return ""
    q = (query or "").strip()
    q_tokens = _tokenize(q) if q else set()
    suppress = list(suppress_terms or [])

    pin_rows = [row for row in items if is_pin_row(row)]
    pin_rows.sort(
        key=lambda r: (str(r.get("created_at") or ""), str(r.get("id") or ""))
    )
    standing: list[dict[str, Any]] = []
    long_pins = 0
    pin_cap = max(0, int(max_pin))
    for row in pin_rows:
        long = looks_long_procedure(str(row.get("content") or ""))
        if long and _overlap_terms(row, suppress):
            continue
        if long:
            if long_pins >= pin_cap:
                continue
            long_pins += 1
        standing.append(row)

    hits: list[tuple[float, dict[str, Any]]] = []
    if q:
        for row in items:
            s = _score_memory_item(row, q_tokens, q)
            if s >= _MIN_MATCH_SCORE:
                hits.append((s, row))
        hits.sort(key=lambda x: x[0], reverse=True)

    pin_ids = {r.get("id") for r in standing}
    extras: list[tuple[float, dict[str, Any]]] = []
    for s, row in hits:
        if row.get("id") in pin_ids:
            continue
        if looks_long_procedure(str(row.get("content") or "")) and _overlap_terms(
            row, suppress
        ):
            continue
        extras.append((s, row))
        if len(extras) >= max(1, int(limit)):
            break

    lines: list[str] = [
        "Long-term memory (matched / pinned short prefs — not the full store):",
    ]
    used = 0
    count = 0
    budget = max(400, int(max_chars))

    def _add(kind: str, content: str, score: float | None = None) -> bool:
        nonlocal used, count
        body = format_memory_body(content)
        if not body or looks_broken_note(body):
            return True
        score_s = f" score={score:.1f}" if score is not None else ""
        line = f"- [{kind}]{score_s} {body}"
        if used + len(line) + 1 > budget and count > 0:
            return False
        lines.append(line)
        used += len(line) + 1
        count += 1
        return True

    if standing:
        lines.append("Standing prefs (explicit pin tags only; procedures live in kb):")
        for row in standing:
            if not _add(
                str(row.get("kind") or "rule"),
                str(row.get("content") or ""),
            ):
                break

    if extras:
        if standing:
            lines.append("Relevant matches:")
        for s, row in extras:
            if not _add(
                str(row.get("kind") or "note"),
                str(row.get("content") or ""),
                s,
            ):
                break

    if count == 0:
        return ""
    return "\n".join(lines)


def _score_memory_item(item: dict[str, Any], q_tokens: set[str], query: str) -> float:
    content = str(item.get("content") or "")
    tags = [str(t) for t in (item.get("tags") or [])]
    kind = str(item.get("kind") or "note").lower()
    blob = f"{content} {' '.join(tags)} {kind}"
    tokens = _tokenize(blob)
    if not tokens and not content:
        return 0.0

    score = 0.0
    for t in q_tokens & tokens:
        score += 2.0 if len(t) >= 2 else 0.0

    q_low = (query or "").lower().strip()
    c_low = content.lower()
    if q_low and q_low in c_low:
        score += 4.0
    for tag in tags:
        tl = tag.lower()
        if tl and (tl in q_low or any(tl in qt or qt in tl for qt in q_tokens if len(qt) >= 2)):
            score += 3.0

    kind_hints = {
        "preference": ("偏好", "喜欢", "习惯", "preference", "prefer", "风格"),
        "template": ("模板", "template", "格式", "大纲"),
        "habit": ("习惯", "总是", "每次", "habit"),
        "rule": ("规则", "必须", "禁止", "rule"),
        "fact": ("事实", "是", "fact"),
    }
    for k, hints in kind_hints.items():
        if kind == k and any(h in q_low for h in hints):
            score += 1.5

    try:
        created = datetime.fromisoformat(item.get("created_at", ""))
        age_days = max(0.0, (_now() - created).total_seconds() / 86400.0)
        score += max(0.0, 1.0 - min(age_days, 90.0) / 90.0) * 0.5
    except Exception:
        pass
    return score


class MemoryStore:
    def _row_dict(self, row: Any) -> dict[str, Any]:
        tags = loads(row.tags_json, [])
        if not isinstance(tags, list):
            tags = []
        return {
            "id": row.id,
            "content": row.content,
            "kind": row.kind or "note",
            "tags": tags,
            "session_id": row.session_id,
            "created_at": row.created_at,
        }

    def _load_all_sync(self) -> list[dict[str, Any]]:
        with db_connect() as conn:
            rows = conn.execute(
                select(memories_t).order_by(memories_t.c.created_at.asc())
            ).all()
        return [self._row_dict(r) for r in rows]

    def _to_item(self, d: dict[str, Any], score: float | None = None) -> MemoryItem:
        created = d.get("created_at") or _now().isoformat()
        try:
            created_at = datetime.fromisoformat(str(created))
        except Exception:
            created_at = _now()
        return MemoryItem(
            id=d["id"],
            content=d["content"],
            kind=d.get("kind", "note"),
            tags=d.get("tags", []),
            session_id=d.get("session_id"),
            created_at=created_at,
            score=score,
        )

    async def add(
        self,
        content: str,
        *,
        kind: str = "note",
        tags: list[str] | None = None,
        session_id: str | None = None,
    ) -> MemoryItem:
        row = {
            "id": uuid.uuid4().hex,
            "content": content,
            "kind": kind,
            "tags": tags or [],
            "session_id": session_id,
            "created_at": _now().isoformat(),
        }

        def _do() -> None:
            with db_connect() as conn:
                conn.execute(
                    insert(memories_t).values(
                        id=row["id"],
                        content=row["content"],
                        kind=row["kind"],
                        tags_json=json.dumps(row["tags"], ensure_ascii=False),
                        session_id=row["session_id"],
                        created_at=row["created_at"],
                    )
                )

        await run_db(_do)
        return self._to_item(row)

    async def list_all(self, limit: int = 100) -> list[MemoryItem]:
        items = await run_db(self._load_all_sync)
        return [self._to_item(i) for i in items[-limit:][::-1]]

    def _score_item(self, item: dict[str, Any], q_tokens: set[str], query: str) -> float:
        return _score_memory_item(item, q_tokens, query)

    async def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
        items = await run_db(self._load_all_sync)
        q = (query or "").strip()
        if not items:
            return []
        if not q:
            return [self._to_item(i) for i in items[-limit:][::-1]]

        q_tokens = _tokenize(q)
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in items:
            s = self._score_item(item, q_tokens, q)
            if s >= _MIN_MATCH_SCORE:
                scored.append((s, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [self._to_item(item, score=s) for s, item in scored[:limit]]

    async def update(
        self,
        item_id: str,
        *,
        content: str | None = None,
        kind: str | None = None,
        tags: list[str] | None = None,
        session_id: str | None = None,
        clear_session: bool = False,
    ) -> MemoryItem | None:
        def _do() -> dict[str, Any] | None:
            with db_connect() as conn:
                row = conn.execute(
                    select(memories_t).where(memories_t.c.id == item_id)
                ).first()
                if not row:
                    return None
                d = self._row_dict(row)
                if content is not None:
                    d["content"] = content
                if kind is not None:
                    d["kind"] = kind
                if tags is not None:
                    d["tags"] = tags
                if clear_session:
                    d["session_id"] = None
                elif session_id is not None:
                    d["session_id"] = session_id
                conn.execute(
                    update(memories_t)
                    .where(memories_t.c.id == item_id)
                    .values(
                        content=d["content"],
                        kind=d["kind"],
                        tags_json=json.dumps(d["tags"], ensure_ascii=False),
                        session_id=d["session_id"],
                    )
                )
                return d

        d = await run_db(_do)
        return self._to_item(d) if d else None

    async def delete(self, memory_id: str) -> bool:
        def _do() -> bool:
            with db_connect() as conn:
                res = conn.execute(
                    delete(memories_t).where(memories_t.c.id == memory_id)
                )
                return bool(res.rowcount)

        return await run_db(_do)

    def _is_pin_row(self, row: dict[str, Any]) -> bool:
        return is_pin_row(row)

    async def context_snippet(
        self,
        query: str,
        limit: int = 5,
        *,
        max_chars: int = 1800,
        max_pin: int = 6,
        suppress_terms: list[str] | None = None,
    ) -> str:
        items = await run_db(self._load_all_sync)
        return render_memory_context(
            items,
            query,
            suppress_terms=suppress_terms,
            limit=limit,
            max_chars=max_chars,
            max_pin=max_pin,
        )


_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


def reset_memory_store() -> None:
    global _store
    _store = None
