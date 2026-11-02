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
from app.storage.lifecycle import (
    NEW_WRITE_CONFIDENCE,
    STATUS_ACTIVE,
    STATUS_STAGING,
    clamp_confidence,
    compute_valid_to,
    is_visible_row,
    normalize_status,
)
from app.memory.control_plane import (
    CONTROL_KINDS,
    STAGING_KINDS as CP_STAGING_KINDS,
    classify_memory_write,
    find_supersede_id,
    is_control_kind,
    is_staging_kind,
    short_summary,
    should_prefer_kb,
)


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
    """Standing prefs: explicit pin tags, or Phase-2 control kinds.

    Staging / evidence never counts as standing (even if mistagged).
    """
    status = str(row.get("status") or "").strip().lower()
    if status == STATUS_STAGING or status in (
        "expired",
        "archived",
        "superseded",
        "conflicted",
        "review_required",
    ):
        return False
    kind = str(row.get("kind") or "").strip().lower()
    if kind in CP_STAGING_KINDS or is_staging_kind(kind):
        return False
    tags = {str(t).lower() for t in (row.get("tags") or [])}
    if tags & _PIN_TAGS:
        return True
    # Control-plane kinds are standing constitution (Phase 2)
    return kind in CONTROL_KINDS or is_control_kind(kind)


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

    # Never inject staging into standing or match blocks
    items = [
        row
        for row in items
        if str(row.get("status") or "").lower() != STATUS_STAGING
        and str(row.get("kind") or "").lower() not in CP_STAGING_KINDS
    ]
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
        status = normalize_status(getattr(row, "status", None))
        try:
            confidence = float(getattr(row, "confidence", None) or 1.0)
        except (TypeError, ValueError):
            confidence = 1.0
        return {
            "id": row.id,
            "content": row.content,
            "kind": row.kind or "note",
            "tags": tags,
            "session_id": row.session_id,
            "created_at": row.created_at,
            "status": status,
            "valid_from": getattr(row, "valid_from", None),
            "valid_to": getattr(row, "valid_to", None),
            "confidence": confidence,
            "supersedes_id": getattr(row, "supersedes_id", None),
        }

    def _load_all_sync(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        with db_connect() as conn:
            rows = conn.execute(
                select(memories_t).order_by(memories_t.c.created_at.asc())
            ).all()
        out = [self._row_dict(r) for r in rows]
        if include_archived:
            return out
        return [r for r in out if is_visible_row(r, include_archived=False)]

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
            status=normalize_status(d.get("status")),
            valid_from=d.get("valid_from"),
            valid_to=d.get("valid_to"),
            confidence=float(d.get("confidence") if d.get("confidence") is not None else 1.0),
            supersedes_id=d.get("supersedes_id"),
        )

    async def add(
        self,
        content: str,
        *,
        kind: str = "note",
        tags: list[str] | None = None,
        session_id: str | None = None,
        confidence: float | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        ttl_days: float | int | None = None,
        ttl_hours: float | int | None = None,
        supersedes_id: str | None = None,
        status: str = STATUS_ACTIVE,
        explicit_status: bool = False,
        auto_supersede: bool = True,
        apply_control_plane: bool = True,
        source: str = "agent",
        via_review: bool = False,
    ) -> MemoryItem:
        text_in = content or ""
        tag_in = list(tags or [])
        st_in = status
        ttl_in = ttl_days
        conf_in = confidence
        kind_in = kind
        meta: dict[str, Any] = {}
        if apply_control_plane:
            meta = classify_memory_write(
                kind=kind_in,
                tags=tag_in,
                content=text_in,
                status=st_in,
                ttl_days=ttl_in,
                valid_to=valid_to,
                confidence=conf_in,
                explicit_status=explicit_status,
            )
            kind_in = meta["kind"]
            tag_in = list(meta["tags"])
            st_in = meta["status"]
            if meta.get("ttl_days") is not None and not (
                valid_to and str(valid_to).strip()
            ):
                ttl_in = meta["ttl_days"]
            if confidence is None:
                conf_in = meta["confidence"]
            # Long factual bodies: keep a short summary pointer in memory
            if meta.get("prefer_kb") and len(text_in.strip()) > 120:
                summary = short_summary(text_in)
                text_in = (
                    f"{summary} 【长文宜入知识库；本条为控制/索引摘要】"
                )
                if "needs_kb" not in {t.lower() for t in tag_in}:
                    tag_in.append("needs_kb")

        # Human gate: agent cannot invent gold; UI blank creates → staging
        src = str(source or "agent").strip().lower()
        if via_review or src == "review":
            pass
        else:
            try:
                from app.memory.human_gate import (
                    gate_agent_memory_write,
                    gate_ui_create,
                )

                if src == "ui":
                    g = gate_ui_create(kind=kind_in, status=st_in)
                    st_in = g["status"]
                else:
                    g = gate_agent_memory_write(
                        kind=kind_in,
                        status=st_in,
                        valid_to=valid_to,
                        ttl_days=ttl_in,
                        explicit_status=explicit_status,
                    )
                    st_in = g["status"]
            except Exception:
                pass

        # Auto-supersede same-key control preference when not specified
        sid = (str(supersedes_id).strip() if supersedes_id else None) or None
        if (
            auto_supersede
            and not sid
            and apply_control_plane
            and meta.get("plane") == "control"
        ):
            try:
                existing = self._load_all_sync(include_archived=False)
                sid = find_supersede_id(
                    existing, kind=kind_in, content=content or "", tags=tag_in
                )
            except Exception:
                sid = None

        vt = compute_valid_to(valid_to=valid_to, ttl_days=ttl_in, ttl_hours=ttl_hours)
        # Staging without expiry: force default TTL via classify (already set ttl_in)
        if normalize_status(st_in) == STATUS_STAGING and not vt and ttl_in:
            vt = compute_valid_to(ttl_days=ttl_in)
        vf = (str(valid_from).strip() if valid_from else None) or None
        row = {
            "id": uuid.uuid4().hex,
            "content": text_in,
            "kind": kind_in,
            "tags": tag_in,
            "session_id": session_id,
            "created_at": _now().isoformat(),
            "status": normalize_status(st_in),
            "valid_from": vf,
            "valid_to": vt,
            "confidence": clamp_confidence(
                conf_in if conf_in is not None else NEW_WRITE_CONFIDENCE
            ),
            "supersedes_id": sid,
        }

        # Phase 3: refuse soft writes that contradict active hard constraints
        try:
            from app.knowledge.refs import detect_and_handle_write_conflict

            existing_all = self._load_all_sync(include_archived=False)
            pre = detect_and_handle_write_conflict(
                existing_rows=existing_all,
                incoming_kind=row["kind"],
                incoming_content=content or row["content"],
                incoming_id=None,
                incoming_tags=row["tags"],
                supersedes_id=row.get("supersedes_id"),
                auto_link=False,
            )
            if pre.get("blocked"):
                raise ValueError(
                    "blocked_hard_constraint: 新内容与现有硬约束冲突，"
                    "请显式 supersedes_id 或先写入参照锚点后再改。"
                    f" details={pre.get('notes')}"
                )
        except ValueError:
            raise
        except Exception:
            pass

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
                        status=row["status"],
                        valid_from=row["valid_from"],
                        valid_to=row["valid_to"],
                        confidence=row["confidence"],
                        supersedes_id=row["supersedes_id"],
                    )
                )
                # Optional: mark superseded predecessor
                sid = row["supersedes_id"]
                if sid:
                    conn.execute(
                        update(memories_t)
                        .where(memories_t.c.id == sid)
                        .values(status="superseded")
                    )

        await run_db(_do)

        # Phase 3: attach knowledge_refs / controls; post-write conflict edges
        try:
            from app.knowledge.refs import (
                EDGE_CONTROLS,
                EDGE_REFERENCES,
                attach_controls_edge,
                attach_kb_ref_for_memory,
                detect_and_handle_write_conflict,
                get_ref_store,
                parse_ref_tags,
            )
            from app.memory.control_plane import is_control_kind as _is_ctrl

            store_refs = get_ref_store()
            for spec in parse_ref_tags(row.get("tags") or []):
                try:
                    et = spec.get("edge_type") or EDGE_REFERENCES
                    if et == EDGE_CONTROLS:
                        attach_controls_edge(
                            memory_id=row["id"],
                            target_type=spec["to_type"],
                            target_id=spec["to_id"],
                        )
                    elif spec.get("to_type") == "kb":
                        attach_kb_ref_for_memory(
                            memory_id=row["id"],
                            kb_id=spec["to_id"],
                            edge_type=et,
                        )
                    else:
                        store_refs.link_sync(
                            from_type="memory",
                            from_id=row["id"],
                            to_type=spec["to_type"],
                            to_id=spec["to_id"],
                            edge_type=et,
                            created_by="system:remember",
                        )
                except Exception:
                    pass

            # Control memories that reference kb also get a controls edge
            if _is_ctrl(row.get("kind")):
                for spec in parse_ref_tags(row.get("tags") or []):
                    if (
                        spec.get("edge_type") == EDGE_REFERENCES
                        and spec.get("to_type") == "kb"
                    ):
                        try:
                            attach_controls_edge(
                                memory_id=row["id"],
                                target_type="kb",
                                target_id=spec["to_id"],
                                reason="control→kb",
                            )
                        except Exception:
                            pass

            existing_all = self._load_all_sync(include_archived=False)
            detect_and_handle_write_conflict(
                existing_rows=existing_all,
                incoming_kind=row["kind"],
                incoming_content=content or row["content"],
                incoming_id=row["id"],
                incoming_tags=row["tags"],
                supersedes_id=row.get("supersedes_id"),
                auto_link=True,
            )
        except Exception:
            pass

        return self._to_item(row)

    async def list_all(
        self, limit: int = 100, *, include_archived: bool = False
    ) -> list[MemoryItem]:
        items = await run_db(
            lambda: self._load_all_sync(include_archived=include_archived)
        )
        return [self._to_item(i) for i in items[-limit:][::-1]]

    def _score_item(self, item: dict[str, Any], q_tokens: set[str], query: str) -> float:
        return _score_memory_item(item, q_tokens, query)

    async def search(
        self, query: str, limit: int = 5, *, include_archived: bool = False
    ) -> list[MemoryItem]:
        items = await run_db(
            lambda: self._load_all_sync(include_archived=include_archived)
        )
        q = (query or "").strip()
        if not items:
            return []
        if not q:
            return [self._to_item(i) for i in items[-limit:][::-1]]

        q_tokens = _tokenize(q)
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in items:
            s = self._score_item(item, q_tokens, q)
            # mild confidence boost
            try:
                s += max(0.0, float(item.get("confidence") or 0.0) - 0.5) * 0.5
            except (TypeError, ValueError):
                pass
            if s >= _MIN_MATCH_SCORE:
                scored.append((s, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        hits = scored[:limit]
        # Phase 3: lightly touch outbound refs for recalled memories
        try:
            from app.knowledge.refs import get_ref_store

            rs = get_ref_store()
            for _, item in hits[:8]:
                mid = str(item.get("id") or "")
                if not mid:
                    continue
                for edge in rs.list_refs_sync(
                    node_type="memory", node_id=mid, direction="out", limit=5
                ):
                    try:
                        rs.touch_sync(edge["id"])
                    except Exception:
                        pass
        except Exception:
            pass
        return [self._to_item(item, score=s) for s, item in hits]

    async def update(
        self,
        item_id: str,
        *,
        content: str | None = None,
        kind: str | None = None,
        tags: list[str] | None = None,
        session_id: str | None = None,
        clear_session: bool = False,
        status: str | None = None,
        confidence: float | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        ttl_days: float | int | None = None,
        ttl_hours: float | int | None = None,
        supersedes_id: str | None = None,
        via_review: bool = False,
        source: str = "ui",
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
                if status is not None:
                    from app.memory.human_gate import (
                        ACTOR_REVIEW,
                        ACTOR_UI,
                        gate_status_change,
                    )

                    actor = ACTOR_REVIEW if via_review else ACTOR_UI
                    if str(source or "").lower() == "agent":
                        actor = "agent"
                    chk = gate_status_change(
                        old_status=d.get("status"),
                        new_status=status,
                        actor=actor,
                        kind=d.get("kind"),
                    )
                    if chk.get("blocked"):
                        raise ValueError(chk.get("message") or chk.get("error") or "blocked")
                    d["status"] = normalize_status(chk.get("status") or status)
                if confidence is not None:
                    d["confidence"] = clamp_confidence(confidence)
                if valid_from is not None:
                    d["valid_from"] = str(valid_from).strip() or None
                if (
                    valid_to is not None
                    or ttl_days is not None
                    or ttl_hours is not None
                ):
                    d["valid_to"] = compute_valid_to(
                        valid_to=valid_to if valid_to is not None else d.get("valid_to"),
                        ttl_days=ttl_days,
                        ttl_hours=ttl_hours,
                    ) if (ttl_days is not None or ttl_hours is not None) else (
                        str(valid_to).strip() or None if valid_to is not None else d.get("valid_to")
                    )
                if supersedes_id is not None:
                    d["supersedes_id"] = str(supersedes_id).strip() or None
                conn.execute(
                    update(memories_t)
                    .where(memories_t.c.id == item_id)
                    .values(
                        content=d["content"],
                        kind=d["kind"],
                        tags_json=json.dumps(d["tags"], ensure_ascii=False),
                        session_id=d["session_id"],
                        status=d["status"],
                        valid_from=d.get("valid_from"),
                        valid_to=d.get("valid_to"),
                        confidence=d.get("confidence", 1.0),
                        supersedes_id=d.get("supersedes_id"),
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
        items = await run_db(lambda: self._load_all_sync(include_archived=False))
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
