"""Editable capability groups for skills and tools.

Seeded from the historical 12 UI buckets. Users and Eva can add / rename /
reassign. ``other`` is always present and cannot be deleted.
Persisted at data/tools/capability_groups.json.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_GROUPS: list[dict[str, str]] = [
    {"id": "vision", "label": "识图分析", "icon": "picture"},
    {"id": "media", "label": "生图 / 视频", "icon": "video"},
    {"id": "memory", "label": "记忆 / 偏好", "icon": "brain"},
    {"id": "content", "label": "内容营销", "icon": "comment"},
    {"id": "workspace", "label": "工作区文件", "icon": "folder-open"},
    {"id": "network", "label": "网络请求", "icon": "network-tree"},
    {"id": "office", "label": "办公文档", "icon": "doc-detail"},
    {"id": "schedule", "label": "任务 / 提醒", "icon": "alarm-clock"},
    {"id": "news", "label": "资讯", "icon": "newspaper-folding"},
    {"id": "infra", "label": "基础设施", "icon": "server"},
    {"id": "dev", "label": "开发 / 运维", "icon": "code"},
    {"id": "other", "label": "其它", "icon": "all-application"},
]

DEFAULT_IDS = frozenset(g["id"] for g in DEFAULT_GROUPS)
PROTECTED_IDS = frozenset({"other"})
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

_lock = threading.RLock()
_cache: list[dict[str, Any]] | None = None
_mtime: float | None = None


def _groups_path() -> Path:
    try:
        from app.config import get_settings

        return get_settings().paths().capability_groups
    except Exception:
        from app.config import PROJECT_ROOT

        return PROJECT_ROOT / "data" / "tools" / "capability_groups.json"


def _normalize_entry(raw: Any, *, builtin_hint: bool | None = None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    gid = str(raw.get("id") or "").strip().lower()
    if not gid or not _ID_RE.match(gid):
        return None
    label = str(raw.get("label") or gid).strip()[:40] or gid
    icon = str(raw.get("icon") or "all-application").strip() or "all-application"
    if builtin_hint is None:
        builtin = bool(raw.get("builtin")) if "builtin" in raw else gid in DEFAULT_IDS
    else:
        builtin = bool(builtin_hint)
    return {"id": gid, "label": label, "icon": icon, "builtin": builtin}


def _seed() -> list[dict[str, Any]]:
    return [
        {
            "id": g["id"],
            "label": g["label"],
            "icon": g["icon"],
            "builtin": True,
        }
        for g in DEFAULT_GROUPS
    ]


def _sort_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rest = [g for g in groups if g.get("id") != "other"]
    other = [g for g in groups if g.get("id") == "other"]
    if not other:
        other = [
            {
                "id": "other",
                "label": "其它",
                "icon": "all-application",
                "builtin": True,
            }
        ]
    return rest + other[:1]


def _save(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    global _cache, _mtime
    ordered = _sort_groups(groups)
    path = _groups_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"groups": ordered}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    _cache = ordered
    _mtime = mtime
    return ordered


def list_groups(*, force: bool = False) -> list[dict[str, Any]]:
    """Return the live group list (seeded on first use)."""
    global _cache, _mtime
    with _lock:
        path = _groups_path()
        mtime: float | None = None
        try:
            if path.exists():
                mtime = path.stat().st_mtime
        except OSError:
            mtime = None
        if not force and _cache is not None and _mtime == mtime:
            return list(_cache)

        groups: list[dict[str, Any]] = []
        seen: set[str] = set()
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8") or "{}")
                rows = raw.get("groups") if isinstance(raw, dict) else raw
                if isinstance(rows, list):
                    for row in rows:
                        entry = _normalize_entry(row)
                        if entry and entry["id"] not in seen:
                            groups.append(entry)
                            seen.add(entry["id"])
            except Exception:
                logger.exception("failed to load capability groups from %s", path)

        if not groups:
            groups = _seed()
            return _save(groups)

        for seed in _seed():
            if seed["id"] not in seen and seed["id"] == "other":
                groups.append(seed)
                seen.add(seed["id"])
        if "other" not in seen:
            groups.append(
                {
                    "id": "other",
                    "label": "其它",
                    "icon": "all-application",
                    "builtin": True,
                }
            )
        ordered = _sort_groups(groups)
        _cache = ordered
        _mtime = mtime
        return list(ordered)


def invalidate_groups_cache() -> None:
    global _cache, _mtime
    with _lock:
        _cache = None
        _mtime = None


def _invalidate_catalog() -> None:
    try:
        from app.api.config import invalidate_tools_catalog_cache

        invalidate_tools_catalog_cache()
    except Exception:
        pass


def valid_ids() -> set[str]:
    return {str(g["id"]) for g in list_groups()}


def match_group(value: str | None) -> dict[str, Any] | None:
    """Match by id (case-insensitive) or label (strip, then casefold)."""
    raw = (value or "").strip()
    if not raw:
        return None
    groups = list_groups()
    low = raw.lower()
    for g in groups:
        if str(g.get("id") or "").lower() == low:
            return dict(g)
    folded = raw.casefold()
    for g in groups:
        if str(g.get("label") or "").strip().casefold() == folded:
            return dict(g)
    return None


def _unique_id(label: str, existing: set[str]) -> str:
    ascii_part = re.sub(r"[^a-z0-9]+", "_", (label or "").strip().lower()).strip("_")
    if ascii_part and ascii_part[0].isalpha() and len(ascii_part) >= 2:
        candidate = ascii_part[:32]
        if candidate not in existing:
            return candidate
        i = 2
        while f"{candidate}_{i}" in existing:
            i += 1
        return f"{candidate}_{i}"[:40]
    digest = hashlib.sha1((label or "").strip().encode("utf-8")).hexdigest()[:8]
    base = f"g_{digest}"
    if base not in existing:
        return base
    i = 2
    while f"{base}_{i}" in existing:
        i += 1
    return f"{base}_{i}"


def add_group(label: str, icon: str = "") -> dict[str, Any]:
    label_n = (label or "").strip()
    if not label_n:
        raise ValueError("分组名称不能为空")
    with _lock:
        groups = list_groups(force=True)
        found = match_group(label_n)
        if found:
            return found
        gid = _unique_id(label_n, {g["id"] for g in groups})
        icon_n = (icon or "").strip() or "all-application"
        entry = {
            "id": gid,
            "label": label_n[:40],
            "icon": icon_n,
            "builtin": False,
        }
        groups.append(entry)
        _save(groups)
        _invalidate_catalog()
        return dict(entry)


def ensure_group(value: str) -> dict[str, Any]:
    """Return an existing group or create one from a new label."""
    found = match_group(value)
    if found:
        return found
    raw = (value or "").strip()
    if not raw:
        other = match_group("other")
        return other or {"id": "other", "label": "其它", "icon": "all-application", "builtin": True}
    return add_group(raw)


def rename_group(gid: str, label: str, icon: str | None = None) -> dict[str, Any]:
    label_n = (label or "").strip()
    if not label_n:
        raise ValueError("分组名称不能为空")
    with _lock:
        groups = list_groups(force=True)
        target = None
        for g in groups:
            if g["id"] == gid:
                target = g
                break
        if not target:
            raise ValueError("分组不存在")
        for g in groups:
            if g["id"] != gid and str(g.get("label") or "").strip().casefold() == label_n.casefold():
                raise ValueError(f"已有同名分组「{g['label']}」")
        target["label"] = label_n[:40]
        if icon is not None and str(icon).strip():
            target["icon"] = str(icon).strip()
        _save(groups)
        _invalidate_catalog()
        return dict(target)


def _iter_skill_manifests() -> list[Path]:
    paths: list[Path] = []
    try:
        from app.services.skill_lifecycle import draft_skills_root, skills_root

        for root in (skills_root(), draft_skills_root()):
            if not root.exists():
                continue
            for p in root.iterdir():
                man = p / "manifest.json"
                if p.is_dir() and man.is_file():
                    paths.append(man)
    except Exception:
        logger.exception("scan skill manifests for group migrate failed")
    return paths


def _write_manifest_group(skill_id: str, group_id: str) -> bool:
    """Patch live then draft manifest agentos_meta.group. Returns True if any wrote."""
    wrote = False
    try:
        from app.services.skill_lifecycle import draft_skill_dir, live_skill_dir

        roots = [live_skill_dir(skill_id), draft_skill_dir(skill_id)]
    except Exception:
        return False
    for root in roots:
        path = root / "manifest.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
            if not isinstance(data, dict):
                continue
            am = data.get("agentos_meta")
            if not isinstance(am, dict):
                am = {}
                data["agentos_meta"] = am
            am["group"] = group_id
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            wrote = True
        except Exception:
            logger.exception("failed to patch group on %s", path)
    return wrote


def migrate_item_groups(src: str, dest: str) -> int:
    """Move tools/skills from group src to dest. Returns how many meta rows moved."""
    src_id = (src or "").strip()
    dest_id = (dest or "other").strip() or "other"
    if not src_id or src_id == dest_id:
        return 0
    moved = 0
    try:
        from app.tools.tool_meta import load_dynamic_meta, upsert_dynamic_meta

        data = load_dynamic_meta(force=True)
        for name, entry in list(data.items()):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("group") or "") != src_id:
                continue
            upsert_dynamic_meta(
                name,
                role=str(entry.get("role") or "primary"),
                tag=str(entry.get("tag") or name),
                group=dest_id,
                scene_keywords=list(entry.get("scene_keywords") or []),
                description_hint=str(entry.get("description_hint") or ""),
                version=str(entry.get("version") or ""),
            )
            moved += 1
    except Exception:
        logger.exception("migrate dynamic tool meta groups failed")
    for man in _iter_skill_manifests():
        try:
            data = json.loads(man.read_text(encoding="utf-8") or "{}")
            if not isinstance(data, dict):
                continue
            am = data.get("agentos_meta")
            if not isinstance(am, dict):
                continue
            if str(am.get("group") or "") != src_id:
                continue
            am["group"] = dest_id
            man.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception:
            logger.exception("migrate skill manifest group failed: %s", man)
    return moved


def delete_group(gid: str, *, migrate: str = "other") -> dict[str, Any]:
    key = (gid or "").strip().lower()
    if not key:
        raise ValueError("分组 id 不能为空")
    if key in PROTECTED_IDS:
        raise ValueError("「其它」不能删除")
    with _lock:
        groups = list_groups(force=True)
        target = next((g for g in groups if g["id"] == key), None)
        if not target:
            raise ValueError("分组不存在")
        dest = match_group(migrate) or match_group("other")
        dest_id = str((dest or {}).get("id") or "other")
        if dest_id == key:
            dest_id = "other"
        moved = migrate_item_groups(key, dest_id)
        groups = [g for g in groups if g["id"] != key]
        _save(groups)
        _invalidate_catalog()
        return {
            "ok": True,
            "deleted": key,
            "migrated_to": dest_id,
            "moved": moved,
        }


def set_item_group(name: str, group: str) -> dict[str, Any]:
    """Assign a skill/tool to a group (creates the group if the label is new)."""
    safe = (name or "").strip()
    if not safe:
        raise ValueError("name required")
    raw = (group or "").strip()
    g = ensure_group(raw) if raw else match_group("other")
    if not g:
        g = {
            "id": "other",
            "label": "其它",
            "icon": "all-application",
            "builtin": True,
        }
    gid = str(g["id"])
    from app.tools.tool_meta import TOOL_META, load_dynamic_meta, upsert_dynamic_meta

    existing = load_dynamic_meta().get(safe) or {}
    static = TOOL_META.get(safe) or {}
    upsert_dynamic_meta(
        safe,
        role=str(existing.get("role") or static.get("role") or "primary"),
        tag=str(existing.get("tag") or static.get("tag") or safe),
        group=gid,
        scene_keywords=list(existing.get("scene_keywords") or []),
        description_hint=str(existing.get("description_hint") or ""),
        version=str(existing.get("version") or ""),
    )
    patched = _write_manifest_group(safe, gid)
    _invalidate_catalog()
    return {
        "ok": True,
        "name": safe,
        "group": gid,
        "label": g.get("label") or gid,
        "manifest_updated": patched,
    }


def public_groups() -> list[dict[str, Any]]:
    return [
        {
            "id": g["id"],
            "label": g["label"],
            "icon": g.get("icon") or "all-application",
            "builtin": bool(g.get("builtin")),
        }
        for g in list_groups()
    ]
