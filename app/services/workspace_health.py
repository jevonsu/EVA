"""Detect and flatten nested ``workspace/`` copies inside the real workspace."""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SKIP_NAMES = {".eva_trash", ".git", "__pycache__"}
_DEFAULT_BUCKETS = {"docs", "images", "skills", "uploads", "videos"}


def _root() -> Path:
    from app.tools.safety import get_workspace_root

    return get_workspace_root().resolve()


def _file_fingerprint(path: Path) -> tuple[int, bytes]:
    size = path.stat().st_size
    h = hashlib.sha256()
    with path.open("rb") as fh:
        h.update(fh.read(65536))
    return size, h.digest()


def _same_file(a: Path, b: Path) -> bool:
    if not a.is_file() or not b.is_file():
        return False
    try:
        return _file_fingerprint(a) == _file_fingerprint(b)
    except OSError:
        return False


def _child_names(path: Path) -> set[str]:
    names: set[str] = set()
    try:
        for child in path.iterdir():
            if child.name.startswith(".") or child.name in _SKIP_NAMES:
                continue
            names.add(child.name.lower())
    except OSError:
        pass
    return names


def _looks_duplicate(nested: Path, root: Path) -> bool:
    kids = _child_names(nested)
    if not kids:
        return True
    if "workspace" in kids:
        return True
    siblings = _child_names(root) - {"workspace"}
    overlap = kids & (siblings | _DEFAULT_BUCKETS)
    return bool(overlap) or kids <= (siblings | _DEFAULT_BUCKETS | _SKIP_NAMES)


def inspect_nested_workspaces(root: Path | None = None) -> dict[str, Any]:
    """Find ``workspace/`` folders sitting inside the real workspace root."""
    base = (root or _root()).resolve()
    items: list[dict[str, Any]] = []
    try:
        children = list(base.iterdir())
    except OSError:
        children = []
    for child in children:
        if not child.is_dir() or child.name.lower() != "workspace":
            continue
        try:
            if child.resolve() == base:
                continue
        except OSError:
            continue
        names = sorted(_child_names(child))
        dup = _looks_duplicate(child, base)
        items.append(
            {
                "path": "workspace",
                "name": child.name,
                "duplicate": dup,
                "children": names[:24],
            }
        )
    return {
        "ok": True,
        "count": len(items),
        "duplicate": any(it.get("duplicate") for it in items),
        "items": items,
    }


def _unique_dest(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    parent = dest.parent
    for i in range(1, 80):
        cand = parent / f"{stem}__from_workspace{'' if i == 1 else i}{suffix}"
        if not cand.exists():
            return cand
    return parent / f"{stem}__from_workspace_{id(dest)}{suffix}"


def _merge_tree(src: Path, dest_dir: Path, *, rel: str, moved: list, skipped: list) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        children = list(src.iterdir())
    except OSError as exc:
        logger.warning("cannot list nested workspace %s: %s", src, exc)
        return
    for child in children:
        if child.name in _SKIP_NAMES:
            continue
        name = child.name
        target = dest_dir / name
        child_rel = f"{rel}/{name}" if rel else name
        if child.is_dir() and name.lower() == "workspace":
            # Nested copy-of-a-copy: dump into dest, do not recreate dest/workspace.
            _merge_tree(child, dest_dir, rel=child_rel, moved=moved, skipped=skipped)
            if _dir_is_empty(child):
                shutil.rmtree(child, ignore_errors=True)
            continue
        if child.is_dir():
            if target.exists() and target.is_dir():
                _merge_tree(child, target, rel=child_rel, moved=moved, skipped=skipped)
                continue
            if target.exists():
                target = _unique_dest(target)
            shutil.move(str(child), str(target))
            moved.append(child_rel)
            continue
        if target.exists() and target.is_file() and _same_file(child, target):
            try:
                child.unlink()
            except OSError:
                pass
            skipped.append(child_rel)
            continue
        if target.exists():
            target = _unique_dest(target)
        shutil.move(str(child), str(target))
        moved.append(child_rel)


def _dir_is_empty(path: Path) -> bool:
    try:
        for child in path.iterdir():
            if child.name in _SKIP_NAMES:
                continue
            if child.is_dir() and _dir_is_empty(child):
                continue
            return False
        return True
    except OSError:
        return False


def flatten_nested_workspaces(root: Path | None = None) -> dict[str, Any]:
    """Move nested workspace/* up into the real root. Identical files are dropped."""
    base = (root or _root()).resolve()
    moved: list[str] = []
    skipped: list[str] = []
    removed: list[str] = []
    for _ in range(6):
        report = inspect_nested_workspaces(base)
        if not report.get("count"):
            break
        progressed = False
        for item in report.get("items") or []:
            nested = base / str(item.get("name") or "workspace")
            if not nested.is_dir():
                continue
            before = len(moved) + len(skipped) + len(removed)
            _merge_tree(
                nested,
                base,
                rel=str(item.get("name") or "workspace"),
                moved=moved,
                skipped=skipped,
            )
            if _dir_is_empty(nested):
                try:
                    shutil.rmtree(nested, ignore_errors=True)
                    removed.append(str(item.get("name") or "workspace"))
                except OSError as exc:
                    logger.warning("could not remove nested workspace: %s", exc)
            if len(moved) + len(skipped) + len(removed) > before:
                progressed = True
        if not progressed:
            break
    return {
        "ok": True,
        "moved": moved,
        "skipped": skipped,
        "removed": removed,
        "remaining": inspect_nested_workspaces(base),
    }
