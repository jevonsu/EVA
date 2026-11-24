"""Evolution digest entries: schema, merge/retention, query, and tag helpers.

This is the session/global evolution digest — not the long-term memory store.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.agent.evolution import KIND_LABELS, empty_evolution

ENTRY_CONTENT_MAX = 800
TAG_NAME_MAX = 32
MAX_TAGS_PER_ENTRY = 8
PAGE_SIZE = 10
EVOLUTION_KINDS = tuple(KIND_LABELS.keys())
SOURCES = ("auto", "manual", "edited")
SCOPES = ("session", "global")

_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key\s*[:=]\s*\S+|access[_-]?token\s*[:=]\s*\S+|"
    r"secret\s*[:=]\s*\S+|password\s*[:=]\s*\S+|passwd\s*[:=]\s*\S+|"
    r"bearer\s+[A-Za-z0-9\-._~+/]+=*|"
    r"ghp_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+|"
    r"gho_[A-Za-z0-9]+|sk-[A-Za-z0-9\-]+|"
    r"sk-or-[A-Za-z0-9\-]+)"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def fingerprint(content: str) -> str:
    norm = re.sub(r"\s+", " ", (content or "").strip()).lower()
    if not norm:
        return ""
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def redact_text(text: str, *, max_len: int = 2000) -> str:
    s = _SECRET_RE.sub("[redacted]", text or "")
    s = s.replace("\x00", "")
    if max_len and len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def normalize_kind(kind: Any) -> str:
    k = str(kind or "fact").strip().lower()[:32]
    return k if k in EVOLUTION_KINDS else "fact"


def normalize_source(source: Any, *, protected: bool = False) -> str:
    s = str(source or "").strip().lower()
    if s in SOURCES:
        return s
    return "manual" if protected else "auto"


def normalize_tag_ids(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        tid = str(item or "").strip()[:64]
        if not tid or tid in seen:
            continue
        seen.add(tid)
        out.append(tid)
        if len(out) >= MAX_TAGS_PER_ENTRY:
            break
    return out


def normalize_entry(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, str):
        content = raw.strip()
        if not content:
            return None
        raw = {"kind": "fact", "content": content}
    if not isinstance(raw, dict):
        return None
    content = str(raw.get("content") or "").strip()[:ENTRY_CONTENT_MAX]
    if not content:
        return None
    source = normalize_source(raw.get("source"), protected=bool(raw.get("protected")))
    protected = bool(raw.get("protected")) or source in ("manual", "edited")
    eid = str(raw.get("id") or "").strip() or new_id()
    created = raw.get("created_at") or raw.get("updated_at") or now_iso()
    updated = raw.get("updated_at") or created
    return {
        "id": eid[:32],
        "kind": normalize_kind(raw.get("kind")),
        "content": content,
        "tags": normalize_tag_ids(raw.get("tags")),
        "source": source,
        "protected": protected,
        "created_at": created,
        "updated_at": updated,
        "fingerprint": fingerprint(content),
    }


def normalize_tombstones(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        eid = str(item.get("id") or "").strip()
        fp = str(item.get("fingerprint") or "").strip()
        key = eid or fp
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "id": eid,
                "fingerprint": fp,
                "deleted_at": str(item.get("deleted_at") or ""),
            }
        )
    return out[-200:]


def normalize_digest(raw: Any) -> dict[str, Any]:
    base = empty_evolution()
    if not isinstance(raw, dict):
        base["tombstones"] = []
        return base
    base["version"] = int(raw.get("version") or 0)
    base["text"] = str(raw.get("text") or "")
    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in raw.get("entries") or []:
        ent = normalize_entry(item)
        if not ent:
            continue
        if ent["id"] in seen_ids:
            ent["id"] = new_id()
        seen_ids.add(ent["id"])
        entries.append(ent)
    base["entries"] = entries
    base["updated_at"] = raw.get("updated_at")
    try:
        base["message_count_at_update"] = int(raw.get("message_count_at_update") or 0)
    except (TypeError, ValueError):
        base["message_count_at_update"] = 0
    base["tombstones"] = normalize_tombstones(raw.get("tombstones"))
    return base


def is_protected(entry: dict[str, Any]) -> bool:
    return bool(entry.get("protected")) or str(entry.get("source") or "") in (
        "manual",
        "edited",
    )


def merge_evolution(
    previous: dict[str, Any] | None,
    generated: dict[str, Any] | None,
    *,
    max_entries: int = 12,
) -> dict[str, Any]:
    """Keep manual/edited entries and tombstones; auto rows may be replaced.

    Auto-compression must not overwrite protected rows or resurrect deletions.
    """
    prev = normalize_digest(previous)
    gen = normalize_digest(generated)
    protected = [e for e in prev["entries"] if is_protected(e)]
    tombs = list(prev["tombstones"])
    tomb_ids = {t["id"] for t in tombs if t.get("id")}
    tomb_fps = {t["fingerprint"] for t in tombs if t.get("fingerprint")}
    prot_ids = {e["id"] for e in protected}
    prot_fps = {e.get("fingerprint") for e in protected if e.get("fingerprint")}

    auto_new: list[dict[str, Any]] = []
    for e in gen["entries"]:
        if e["id"] in tomb_ids or e.get("fingerprint") in tomb_fps:
            continue
        if e["id"] in prot_ids or e.get("fingerprint") in prot_fps:
            continue
        if is_protected(e) and e["id"] not in prot_ids:
            # generated payload should not invent protected rows
            e = dict(e)
            e["source"] = "auto"
            e["protected"] = False
        # fresh id if it collided with something already used
        if e["id"] in prot_ids:
            e = dict(e, id=new_id())
        e["source"] = "auto"
        e["protected"] = False
        auto_new.append(e)

    cap = max(1, int(max_entries or 12))
    if len(protected) >= cap:
        entries = protected
    else:
        room = cap - len(protected)
        entries = protected + auto_new[:room]

    text = str(gen.get("text") or prev.get("text") or "")
    if not text and entries:
        text = "；".join(f"{e['kind']}:{e['content']}" for e in entries)[:2000]

    return {
        "version": int(prev.get("version") or 0) + 1,
        "text": text,
        "entries": entries,
        "updated_at": now_iso(),
        "message_count_at_update": int(gen.get("message_count_at_update") or 0),
        "tombstones": tombs,
    }


def upsert_manual_entry(
    digest: dict[str, Any] | None,
    payload: dict[str, Any],
    *,
    entry_id: str | None = None,
) -> dict[str, Any]:
    evo = normalize_digest(digest)
    body = dict(payload or {})
    existing = None
    eid = (entry_id or str(body.get("id") or "")).strip()
    if eid:
        for item in evo["entries"]:
            if item["id"] == eid:
                existing = item
                break
        if existing is None:
            raise KeyError("entry not found")
    now = now_iso()
    if existing:
        merged = dict(existing)
        if "content" in body and body.get("content") is not None:
            merged["content"] = str(body.get("content") or "").strip()[:ENTRY_CONTENT_MAX]
        if "kind" in body and body.get("kind") is not None:
            merged["kind"] = normalize_kind(body.get("kind"))
        if "tags" in body:
            merged["tags"] = normalize_tag_ids(body.get("tags"))
        if not str(merged.get("content") or "").strip():
            raise ValueError("content 不能为空")
        merged["source"] = "edited" if existing.get("source") == "auto" else "manual"
        merged["protected"] = True
        merged["updated_at"] = now
        merged["fingerprint"] = fingerprint(merged["content"])
        evo["entries"] = [merged if e["id"] == existing["id"] else e for e in evo["entries"]]
        saved = merged
    else:
        body["source"] = "manual"
        body["protected"] = True
        body["id"] = new_id()
        body["created_at"] = now
        body["updated_at"] = now
        ent = normalize_entry(body)
        if not ent:
            raise ValueError("content 不能为空")
        ent["source"] = "manual"
        ent["protected"] = True
        evo["entries"].insert(0, ent)
        saved = ent
    evo["updated_at"] = now
    return evo, saved


def delete_manual_entry(digest: dict[str, Any] | None, entry_id: str) -> dict[str, Any]:
    evo = normalize_digest(digest)
    eid = str(entry_id or "").strip()
    if not eid:
        raise ValueError("missing entry id")
    found = None
    kept: list[dict[str, Any]] = []
    for item in evo["entries"]:
        if item["id"] == eid:
            found = item
        else:
            kept.append(item)
    if found is None:
        raise KeyError("entry not found")
    evo["entries"] = kept
    evo["tombstones"] = normalize_tombstones(
        list(evo.get("tombstones") or [])
        + [
            {
                "id": found["id"],
                "fingerprint": found.get("fingerprint") or fingerprint(found.get("content") or ""),
                "deleted_at": now_iso(),
            }
        ]
    )
    evo["updated_at"] = now_iso()
    return evo


def unbind_tag(digest: dict[str, Any] | None, tag_id: str) -> tuple[dict[str, Any], int]:
    evo = normalize_digest(digest)
    tid = str(tag_id or "").strip()
    changed = 0
    for item in evo["entries"]:
        tags = list(item.get("tags") or [])
        if tid in tags:
            item["tags"] = [t for t in tags if t != tid]
            changed += 1
    if changed:
        evo["updated_at"] = now_iso()
    return evo, changed


def query_entries(
    rows: list[dict[str, Any]],
    *,
    q: str = "",
    kind: str = "",
    tag: str = "",
    source: str = "",
    scope: str = "",
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> dict[str, Any]:
    needle = (q or "").strip().lower()
    kind_n = (kind or "").strip().lower()
    tag_n = (tag or "").strip()
    source_n = (source or "").strip().lower()
    scope_n = (scope or "").strip().lower()
    filtered: list[dict[str, Any]] = []
    for item in rows:
        if kind_n and str(item.get("kind") or "") != kind_n:
            continue
        if tag_n and tag_n not in (item.get("tags") or []):
            # also allow filter by tag name if provided on the row
            names = item.get("tag_names") or []
            if tag_n not in names and tag_n not in {str(t) for t in (item.get("tags") or [])}:
                continue
        if source_n and str(item.get("source") or "") != source_n:
            continue
        if scope_n and str(item.get("scope") or "") != scope_n:
            continue
        if needle:
            blob = " ".join(
                [
                    str(item.get("content") or ""),
                    str(item.get("kind") or ""),
                    str(item.get("kind_label") or ""),
                    " ".join(str(x) for x in (item.get("tag_names") or [])),
                    " ".join(str(x) for x in (item.get("tags") or [])),
                ]
            ).lower()
            if needle not in blob:
                continue
        filtered.append(item)
    filtered.sort(key=lambda e: str(e.get("updated_at") or ""), reverse=True)
    total = len(filtered)
    size = max(1, min(50, int(page_size or PAGE_SIZE)))
    pages = max(1, (total + size - 1) // size) if total else 1
    page_n = max(1, int(page or 1))
    if page_n > pages:
        page_n = pages
    start = (page_n - 1) * size
    items = filtered[start : start + size]
    return {
        "ok": True,
        "items": items,
        "total": total,
        "page": page_n,
        "page_size": size,
        "pages": pages,
        "empty": total == 0,
    }


def public_entry(entry: dict[str, Any], *, scope: str, tag_names: dict[str, str] | None = None) -> dict[str, Any]:
    names_map = tag_names or {}
    tags = list(entry.get("tags") or [])
    return {
        "id": entry.get("id"),
        "kind": entry.get("kind"),
        "kind_label": KIND_LABELS.get(str(entry.get("kind") or ""), str(entry.get("kind") or "")),
        "content": entry.get("content"),
        "tags": tags,
        "tag_names": [names_map.get(t, t) for t in tags],
        "source": entry.get("source") or "auto",
        "source_label": {
            "auto": "自动压缩",
            "manual": "手动添加",
            "edited": "手动修订",
        }.get(str(entry.get("source") or "auto"), str(entry.get("source") or "")),
        "protected": is_protected(entry),
        "scope": scope,
        "scope_label": "当前会话" if scope == "session" else "公共演化",
        "created_at": entry.get("created_at"),
        "updated_at": entry.get("updated_at"),
    }


def normalize_tag_name(name: Any) -> str:
    n = re.sub(r"\s+", " ", str(name or "").strip())
    if not n:
        raise ValueError("标签名不能为空")
    if len(n) > TAG_NAME_MAX:
        raise ValueError(f"标签名最多 {TAG_NAME_MAX} 字")
    return n
