"""Call Agent Hub workspace HTTP when this Eva cannot mount the shared folder."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _base() -> str:
    from app.services.workspace_bind import hub_url

    return hub_url().rstrip("/")


def _timeout() -> httpx.Timeout:
    return httpx.Timeout(20.0, connect=5.0)


def hub_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.services.workspace_bind import mark_hub_reachable, mark_hub_unreachable

    url = _base() + path
    try:
        with httpx.Client(timeout=_timeout(), follow_redirects=True) as client:
            r = client.get(url, params=params or {})
            r.raise_for_status()
            mark_hub_reachable()
            return r.json() if r.content else {"ok": True}
    except Exception:
        mark_hub_unreachable()
        raise


def hub_send(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.services.workspace_bind import mark_hub_reachable, mark_hub_unreachable

    url = _base() + path
    try:
        with httpx.Client(timeout=_timeout(), follow_redirects=True) as client:
            r = client.request(method.upper(), url, json=body or {})
            r.raise_for_status()
            mark_hub_reachable()
            return r.json() if r.content else {"ok": True}
    except Exception:
        mark_hub_unreachable()
        raise


def list_as_eva(rel: str = "", *, limit: int = 400) -> dict[str, Any]:
    data = hub_get("/api/workspace/list", {"path": rel or ""})
    items = data.get("items") or []
    entries = []
    for it in items[: max(1, min(int(limit), 500))]:
        if not isinstance(it, dict):
            continue
        is_dir = bool(it.get("is_dir") or it.get("kind") == "dir")
        path = str(it.get("path") or "").replace("\\", "/").strip("/")
        name = str(it.get("name") or "").strip()
        if not name:
            name = path.rsplit("/", 1)[-1] if path else ""
        if not name or name.startswith("."):
            continue
        row = {
            "name": name,
            "path": path or name,
            "type": "dir" if is_dir else "file",
        }
        if not is_dir:
            row["size"] = it.get("size")
        if it.get("mtime") is not None:
            try:
                mt = float(it["mtime"])
                if mt > 1e12:
                    mt = mt / 1000.0
                row["mtime"] = int(mt)
            except (TypeError, ValueError):
                pass
        entries.append(row)
    path = str(data.get("path") or rel or "")
    parent = data.get("parent")
    if path in ("", "."):
        parent = None
        display = "."
        path_display = "工作区根目录（Hub 共享）"
    else:
        display = path
        path_display = path
        if parent is None:
            parent = ""
    return {
        "ok": True,
        "path": display,
        "path_display": path_display,
        "parent": parent,
        "entries": entries,
        "count": len(entries),
        "shared": True,
        "via": "hub_http",
        "file_source": "hub",
        "file_source_label": "Hub 公司工作区（与 Hub 同一份）",
    }


def tool_list(rel: str) -> str:
    data = list_as_eva(rel)
    return json.dumps(
        {
            "ok": True,
            "path": data.get("path") or rel,
            "entries": data.get("entries") or [],
            "workspace_root": "hub:" + _base(),
            "hint": "path 相对 Hub 公司工作区（全员共用），不要再加 workspace/ 前缀",
            "file_source": "hub",
            "file_source_label": "Hub 公司工作区（所有员工共用）",
        },
        ensure_ascii=False,
    )


def tool_read(rel: str, max_chars: int = 8000) -> str:
    data = hub_get("/api/workspace/read", {"path": rel})
    content = str(data.get("content") or "")
    if len(content) > max_chars:
        content = content[:max_chars] + "\n…(truncated)"
    return json.dumps(
        {
            "ok": True,
            "path": data.get("path") or rel,
            "content": content,
            "via": "hub_http",
            "file_source": "hub",
            "file_source_label": "Hub 公司工作区（所有员工共用）",
        },
        ensure_ascii=False,
    )


def tool_write(rel: str, content: str) -> str:
    data = hub_send("PUT", "/api/workspace/write", {"path": rel, "content": content})
    return json.dumps({"ok": True, "path": rel, "via": "hub_http", **(data or {})}, ensure_ascii=False)
