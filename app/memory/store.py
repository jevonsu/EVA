"""Long-term memory store with match-based ranking (never full dump)."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from app.config import get_settings
from app.models.schemas import MemoryItem


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tokenize(text: str) -> set[str]:
    tokens: set[str] = set()
    for t in re.split(r"[\s,.;:!?/\\|_+\-*=()\[\]{}\"'`]+", text.lower()):
        if len(t) >= 2 or (t and "\u4e00" <= t <= "\u9fff"):
            tokens.add(t)
    chn_chars = re.findall(r"[一-鿿]", text)
    if not chn_chars:
        return tokens
    tokens.update(chn_chars)
    for i in range(len(chn_chars) - 1):
        tokens.add(chn_chars[i] + chn_chars[i + 1])
    for seg in re.findall(r"[一-鿿]{3,}", text):
        tokens.add(seg)
    return tokens


# Tags that force a memory into the "always apply" pin set (still capped)
_PIN_TAGS = frozenset({"always", "pin", "全局", "始终", "永久规则", "standing"})

# Below this score a row is treated as non-match (filters weak CJK char noise)
_MIN_MATCH_SCORE = 2.0


class MemoryStore:
    def __init__(self, path: Path | None = None) -> None:
        settings = get_settings()
        self.path = path or (settings.data_dir / "memory" / "long_term.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    async def _load(self) -> list[dict[str, Any]]:
        async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
            raw = await f.read()
        return json.loads(raw or "[]")

    async def _save(self, items: list[dict[str, Any]]) -> None:
        async with aiofiles.open(self.path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(items, ensure_ascii=False, indent=2))

    def _to_item(self, d: dict[str, Any], score: float | None = None) -> MemoryItem:
        return MemoryItem(
            id=d["id"],
            content=d["content"],
            kind=d.get("kind", "note"),
            tags=d.get("tags", []),
            session_id=d.get("session_id"),
            created_at=datetime.fromisoformat(d["created_at"]),
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
        items = await self._load()
        row = {
            "id": uuid.uuid4().hex,
            "content": content,
            "kind": kind,
            "tags": tags or [],
            "session_id": session_id,
            "created_at": _now().isoformat(),
        }
        items.append(row)
        await self._save(items)
        return self._to_item(row)

    async def list_all(self, limit: int = 100) -> list[MemoryItem]:
        items = await self._load()
        return [self._to_item(i) for i in items[-limit:][::-1]]

    def _score_item(self, item: dict[str, Any], q_tokens: set[str], query: str) -> float:
        """Relevance score for match injection. 0 = no match."""
        content = str(item.get("content") or "")
        tags = [str(t) for t in (item.get("tags") or [])]
        kind = str(item.get("kind") or "note").lower()
        blob = f"{content} {' '.join(tags)} {kind}"
        tokens = _tokenize(blob)
        if not tokens and not content:
            return 0.0

        score = 0.0
        # token overlap (bigrams/words more valuable than single CJK char)
        for t in q_tokens & tokens:
            if len(t) >= 2:
                score += 2.0
            else:
                score += 0.35

        q_low = (query or "").lower().strip()
        c_low = content.lower()
        if q_low and q_low in c_low:
            score += 4.0
        # tag exact-ish hits
        for tag in tags:
            tl = tag.lower()
            if tl and (tl in q_low or any(tl in qt or qt in tl for qt in q_tokens if len(qt) >= 2)):
                score += 3.0

        # kind soft boost when query hints at that domain
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

        # mild recency (0–1)
        try:
            created = datetime.fromisoformat(item.get("created_at", ""))
            age_days = max(0.0, (_now() - created).total_seconds() / 86400.0)
            score += max(0.0, 1.0 - min(age_days, 90.0) / 90.0) * 0.5
        except Exception:
            pass

        return score

    async def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
        items = await self._load()
        q = (query or "").strip()
        if not items:
            return []
        if not q:
            # no query → newest only (still capped), not full dump
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
        items = await self._load()
        for row in items:
            if row["id"] == item_id:
                if content is not None:
                    row["content"] = content
                if kind is not None:
                    row["kind"] = kind
                if tags is not None:
                    row["tags"] = tags
                if clear_session:
                    row["session_id"] = None
                elif session_id is not None:
                    row["session_id"] = session_id
                await self._save(items)
                return self._to_item(row)
        return None

    async def delete(self, memory_id: str) -> bool:
        items = await self._load()
        new_items = [i for i in items if i["id"] != memory_id]
        if len(new_items) == len(items):
            return False
        await self._save(new_items)
        return True

    def _is_pin_row(self, row: dict[str, Any]) -> bool:
        """Only explicit pins are always-considered (still score-capped)."""
        kind = (row.get("kind") or "").lower()
        tags = {str(t).lower() for t in (row.get("tags") or [])}
        if kind == "rule":
            return True
        if tags & _PIN_TAGS:
            return True
        return False

    async def context_snippet(
        self,
        query: str,
        limit: int = 5,
        *,
        max_chars: int = 1800,
        max_pin: int = 3,
    ) -> str:
        """Build matched memory context for one turn.

        Design goals
        ------------
        - **Match, not full dump**: only relevant rows enter the prompt.
        - **Bounded tokens**: hard cap on item count and total characters.
        - **Optional pins**: only kind=rule or tags always/pin/全局 — few items,
          not every preference (preferences grow and would blow the budget).

        Preference/template rows still surface when they **match** the query.
        """
        items = await self._load()
        if not items:
            return ""

        q = (query or "").strip()
        q_tokens = _tokenize(q) if q else set()

        # 1) Explicit pins (rule / always-tag) — newest first, hard capped
        pins: list[tuple[float, dict[str, Any]]] = []
        for row in items:
            if not self._is_pin_row(row):
                continue
            # If there is a query, still prefer pins that match a bit; pure pins get base score
            s = self._score_item(row, q_tokens, q) if q_tokens else 1.0
            if not q_tokens:
                s = 1.0
            pins.append((max(s, 0.5), row))
        pins.sort(key=lambda x: x[0], reverse=True)
        pins = pins[:max_pin]

        # 2) Matched hits (all kinds) via scoring
        hits = await self.search(q, limit=max(limit, 1)) if q else []
        pin_ids = {p[1].get("id") for p in pins}

        # 3) Assemble under char budget
        lines: list[str] = [
            "Long-term memory (matched only — not the full store):",
        ]
        used = 0
        count = 0
        budget = max(400, int(max_chars))

        def _add(prefix: str, kind: str, content: str, score: float | None = None) -> bool:
            nonlocal used, count
            if count >= limit + max_pin:
                return False
            body = (content or "").strip()
            if len(body) > 280:
                body = body[:280] + "…"
            score_s = f" score={score:.1f}" if score is not None else ""
            line = f"- [{kind}]{score_s} {body}"
            # +1 for newline
            if used + len(line) + 1 > budget and count > 0:
                return False
            lines.append(line)
            used += len(line) + 1
            count += 1
            return True

        if pins:
            lines.append("Standing rules (pinned tags/kind=rule):")
            for s, row in pins:
                if not _add(
                    "pin",
                    str(row.get("kind") or "rule"),
                    str(row.get("content") or ""),
                    s,
                ):
                    break

        extras = [h for h in hits if h.id not in pin_ids]
        if extras:
            if pins:
                lines.append("Relevant matches:")
            for h in extras:
                if not _add("hit", h.kind, h.content, h.score):
                    break

        # No pins and no matches → inject nothing (avoid dumping recent noise)
        if count == 0:
            return ""

        return "\n".join(lines)


_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store
