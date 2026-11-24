"""Global evolution digest + shared tag catalog (not long-term memory)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.agent.evolution_entries import (
    MAX_TAGS_PER_ENTRY,
    TAG_NAME_MAX,
    delete_manual_entry,
    normalize_digest,
    normalize_tag_name,
    now_iso,
    new_id,
    public_entry,
    query_entries,
    unbind_tag,
    upsert_manual_entry,
)
from app.config_store import get_config_store
from app.memory.session import get_session_store

CATALOG_SECTION = "evolution_catalog"


def empty_catalog() -> dict[str, Any]:
    return {
        "tags": [],
        "global": normalize_digest({}),
    }


def _load() -> dict[str, Any]:
    store = get_config_store()
    raw = store.get_raw().get(CATALOG_SECTION)
    if not isinstance(raw, dict):
        return empty_catalog()
    tags = []
    seen = set()
    for item in raw.get("tags") or []:
        if not isinstance(item, dict):
            continue
        tid = str(item.get("id") or "").strip() or new_id()
        try:
            name = normalize_tag_name(item.get("name"))
        except ValueError:
            continue
        key = name.lower()
        if tid in seen:
            tid = new_id()
        seen.add(tid)
        tags.append(
            {
                "id": tid,
                "name": name,
                "created_at": item.get("created_at") or now_iso(),
                "updated_at": item.get("updated_at") or item.get("created_at") or now_iso(),
            }
        )
    return {"tags": tags, "global": normalize_digest(raw.get("global"))}


def _save(catalog: dict[str, Any]) -> dict[str, Any]:
    store = get_config_store()
    payload = {
        "tags": list(catalog.get("tags") or []),
        "global": normalize_digest(catalog.get("global")),
    }
    store.update_section(CATALOG_SECTION, payload)
    return payload


def tag_map(catalog: dict[str, Any] | None = None) -> dict[str, str]:
    cat = catalog or _load()
    return {str(t["id"]): str(t["name"]) for t in cat.get("tags") or []}


def list_tags() -> list[dict[str, Any]]:
    return deepcopy(_load()["tags"])


def create_tag(name: str) -> dict[str, Any]:
    cat = _load()
    n = normalize_tag_name(name)
    for t in cat["tags"]:
        if t["name"].lower() == n.lower():
            raise ValueError("标签已存在")
    row = {"id": new_id(), "name": n, "created_at": now_iso(), "updated_at": now_iso()}
    cat["tags"].append(row)
    _save(cat)
    return row


def rename_tag(tag_id: str, name: str) -> dict[str, Any]:
    cat = _load()
    tid = str(tag_id or "").strip()
    n = normalize_tag_name(name)
    target = None
    for t in cat["tags"]:
        if t["id"] == tid:
            target = t
        elif t["name"].lower() == n.lower() and t["id"] != tid:
            raise ValueError("标签已存在")
    if target is None:
        raise KeyError("标签不存在")
    target["name"] = n
    target["updated_at"] = now_iso()
    _save(cat)
    # Entries keep tag ids; rename is catalog-only.
    return dict(target)


async def tag_usage(tag_id: str) -> dict[str, int]:
    tid = str(tag_id or "").strip()
    cat = _load()
    global_count = sum(1 for e in cat["global"].get("entries") or [] if tid in (e.get("tags") or []))
    session_count = 0
    store = get_session_store()
    rows = await store.list_sessions()
    for row in rows:
        data = await store.get(row["session_id"])
        if not data:
            continue
        evo = normalize_digest(data.get("evolution"))
        session_count += sum(1 for e in evo.get("entries") or [] if tid in (e.get("tags") or []))
    return {
        "global_count": global_count,
        "session_count": session_count,
        "total": global_count + session_count,
    }


async def delete_tag(tag_id: str) -> dict[str, Any]:
    """Remove the tag from the catalog and unbind it from entries. Entries stay."""
    tid = str(tag_id or "").strip()
    cat = _load()
    target = next((t for t in cat["tags"] if t["id"] == tid), None)
    if target is None:
        raise KeyError("标签不存在")
    usage = await tag_usage(tid)
    cat["global"], g_changed = unbind_tag(cat["global"], tid)
    cat["tags"] = [t for t in cat["tags"] if t["id"] != tid]
    _save(cat)
    store = get_session_store()
    s_changed = 0
    for row in await store.list_sessions():
        data = await store.get(row["session_id"])
        if not data:
            continue
        evo, n = unbind_tag(data.get("evolution"), tid)
        if n:
            await store.set_evolution(row["session_id"], evo)
            s_changed += n
    return {
        "ok": True,
        "deleted": target,
        "unbound": {"global": g_changed, "session": s_changed, **usage},
        "entries_preserved": True,
    }


def get_global_digest() -> dict[str, Any]:
    return _load()["global"]


def save_global_digest(digest: dict[str, Any]) -> dict[str, Any]:
    cat = _load()
    cat["global"] = normalize_digest(digest)
    _save(cat)
    return cat["global"]


async def collect_entries(
    *,
    scope: str = "session",
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    names = tag_map()
    scope_n = (scope or "session").strip().lower()
    rows: list[dict[str, Any]] = []
    if scope_n in ("global", "all"):
        for e in get_global_digest().get("entries") or []:
            rows.append(public_entry(e, scope="global", tag_names=names))
    if scope_n in ("session", "all"):
        if not session_id and scope_n == "session":
            return rows
        if session_id:
            data = await get_session_store().get(session_id)
            evo = normalize_digest((data or {}).get("evolution") if data else {})
            for e in evo.get("entries") or []:
                rows.append(public_entry(e, scope="session", tag_names=names))
    return rows


async def query_evolution_entries(
    *,
    scope: str = "session",
    session_id: str | None = None,
    q: str = "",
    kind: str = "",
    tag: str = "",
    source: str = "",
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    scope_n = (scope or "session").strip().lower()
    if scope_n not in ("session", "global", "all"):
        raise ValueError("scope 只能是 session、global 或 all")
    if scope_n in ("session", "all") and scope_n == "session" and not (session_id or "").strip():
        return {
            "ok": True,
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": int(page_size or 10),
            "pages": 1,
            "empty": True,
            "need_session": True,
        }
    # tag filter may be id or name
    tag_n = (tag or "").strip()
    if tag_n:
        for t in list_tags():
            if t["name"] == tag_n or t["id"] == tag_n:
                tag_n = t["id"]
                break
    rows = await collect_entries(scope=scope_n, session_id=session_id)
    result = query_entries(
        rows,
        q=q,
        kind=kind,
        tag=tag_n,
        source=source,
        page=page,
        page_size=page_size,
    )
    result["scope"] = scope_n
    result["session_id"] = session_id or ""
    result["tags"] = list_tags()
    return result


async def save_entry(
    *,
    scope: str,
    session_id: str | None,
    payload: dict[str, Any],
    entry_id: str | None = None,
) -> dict[str, Any]:
    scope_n = (scope or "session").strip().lower()
    if scope_n not in ("session", "global"):
        raise ValueError("scope 只能是 session 或 global")
    if scope_n == "session":
        sid = (session_id or "").strip()
        if not sid:
            raise ValueError("请先打开一个会话")
        store = get_session_store()
        data = await store.get(sid)
        if not data:
            raise KeyError("Session not found")
        evo, saved = upsert_manual_entry(data.get("evolution"), payload, entry_id=entry_id)
        await store.set_evolution(sid, evo)
        return public_entry(saved, scope="session", tag_names=tag_map())
    evo, saved = upsert_manual_entry(get_global_digest(), payload, entry_id=entry_id)
    save_global_digest(evo)
    return public_entry(saved, scope="global", tag_names=tag_map())


async def remove_entry(*, scope: str, session_id: str | None, entry_id: str) -> dict[str, Any]:
    scope_n = (scope or "session").strip().lower()
    if scope_n not in ("session", "global"):
        raise ValueError("scope 只能是 session 或 global")
    if scope_n == "session":
        sid = (session_id or "").strip()
        if not sid:
            raise ValueError("请先打开一个会话")
        store = get_session_store()
        data = await store.get(sid)
        if not data:
            raise KeyError("Session not found")
        evo = delete_manual_entry(data.get("evolution"), entry_id)
        await store.set_evolution(sid, evo)
        return {"ok": True, "id": entry_id, "scope": "session"}
    evo = delete_manual_entry(get_global_digest(), entry_id)
    save_global_digest(evo)
    return {"ok": True, "id": entry_id, "scope": "global"}
