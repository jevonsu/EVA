"""Copy CLI-produced images/videos into the Eva workspace so chat can preview them.

Grok Build writes files under ``~/.grok/sessions/<encoded-cwd>/<id>/images/1.jpg``
and mentions ``images/1.jpg`` in markdown. Eva's bubble loads
``/api/workspace/media/...``, so those session-relative paths 404 unless copied.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from urllib.parse import quote, unquote

logger = logging.getLogger(__name__)

_MEDIA_EXT = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".svg",
    ".mp4",
    ".webm",
    ".mov",
    ".m4v",
    ".ogv",
)
_MD_REF = re.compile(
    r"!\[[^\]]*\]\(\s*<?([^)\s>]+)>?|"
    r"(?<!!)\[(?:[^\]]*)\]\(\s*<?([^)\s>]+\.(?:png|jpe?g|gif|webp|bmp|svg|mp4|webm|mov|m4v|ogv))>?",
    re.I,
)
_BARE_REF = re.compile(
    r"(?<![\w./\\])(?<!\()(?<!\[)((?:[A-Za-z]:[\\/])?[^\s<>\"')\[\](!]+"
    r"\.(?:png|jpe?g|gif|webp|bmp|svg|mp4|webm|mov|m4v|ogv))",
    re.I,
)


def _is_media_name(name: str) -> bool:
    return Path(name).suffix.lower() in _MEDIA_EXT


def _workspace_root() -> Path:
    from app.tools.safety import get_workspace_root

    return get_workspace_root()


def _grok_session_dirs(cwd: str) -> list[Path]:
    home = Path.home() / ".grok" / "sessions"
    if not home.is_dir():
        return []
    try:
        resolved = str(Path(cwd).resolve())
    except OSError:
        resolved = cwd
    keys = []
    for raw in (resolved, cwd):
        if not raw:
            continue
        keys.append(quote(raw, safe=""))
        keys.append(quote(raw.replace("\\", "/"), safe=""))
    found: list[Path] = []
    seen: set[str] = set()
    for key in keys:
        root = home / key
        if not root.is_dir():
            # grok sometimes mixes percent-encoding case
            for child in home.iterdir() if home.is_dir() else []:
                if unquote(child.name).replace("/", "\\") == resolved.replace("/", "\\"):
                    root = child
                    break
            else:
                continue
        if str(root) in seen:
            continue
        seen.add(str(root))
        subs = [p for p in root.iterdir() if p.is_dir()]
        subs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        found.extend(subs)
    return found


def _extract_refs(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        s = (raw or "").strip().strip("<>").strip("'\"")
        s = s.replace("\\", "/")
        if s.lower().startswith("file:"):
            s = re.sub(r"^file:/*", "", s, flags=re.I)
            if re.match(r"^[A-Za-z]:/", s):
                pass
            elif s.startswith("/"):
                s = s
        if not s or s.startswith("http://") or s.startswith("https://"):
            return
        if s.startswith("data:"):
            return
        if not _is_media_name(s.split("?")[0]):
            return
        if s not in seen:
            seen.add(s)
            out.append(s)

    for m in _MD_REF.finditer(text or ""):
        add(m.group(1) or m.group(2) or "")
    for m in _BARE_REF.finditer(text or ""):
        add(m.group(1))
    return out


def _resolve_ref(ref: str, *, cwd: Path, sessions: list[Path]) -> Path | None:
    cleaned = ref.split("?")[0].split("#")[0].strip()
    candidates: list[Path] = []
    p = Path(cleaned)
    if p.is_file():
        return p.resolve()
    if p.is_absolute():
        return p if p.is_file() else None
    candidates.append(cwd / cleaned)
    candidates.append(cwd / Path(cleaned).name)
    for sd in sessions:
        candidates.append(sd / cleaned)
        name = Path(cleaned).name
        candidates.append(sd / "images" / name)
        candidates.append(sd / "videos" / name)
    for cand in candidates:
        try:
            if cand.is_file():
                return cand.resolve()
        except OSError:
            continue
    return None


def _unique_dest(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    base = Path(name).name or "media.bin"
    dest = folder / base
    if not dest.exists():
        return dest
    stem, suffix = Path(base).stem, Path(base).suffix
    i = 1
    while True:
        dest = folder / f"{stem}_{i}{suffix}"
        if not dest.exists():
            return dest
        i += 1


def import_cli_media(text: str, *, cwd: str = "") -> tuple[str, list[str]]:
    """Copy referenced CLI media into workspace/generated and rewrite markdown.

    Returns (new_text, workspace-relative paths).
    """
    raw = text or ""
    refs = _extract_refs(raw)
    if not refs:
        return raw, []

    try:
        ws = _workspace_root()
    except Exception:
        logger.exception("CLI media: workspace root unavailable")
        return raw, []
    work = Path(cwd).resolve() if (cwd or "").strip() else ws
    sessions = _grok_session_dirs(str(work))
    dest_dir = ws / "generated"

    rewritten = raw
    imported: list[str] = []
    copied_src: dict[str, str] = {}
    # longer refs first so images/1.jpg wins over 1.jpg
    ordered: list[str] = []
    for ref in sorted(refs, key=len, reverse=True):
        if any(prev.endswith("/" + ref) or prev.endswith("\\" + ref) for prev in ordered):
            continue
        ordered.append(ref)
    for ref in ordered:
        src = _resolve_ref(ref, cwd=work, sessions=sessions)
        if src is None:
            continue
        src_key = str(src)
        if src_key in copied_src:
            rewritten = _rewrite_ref(rewritten, ref, copied_src[src_key])
            continue
        try:
            rel = src.relative_to(ws.resolve()).as_posix()
            copied_src[src_key] = rel
            if rel not in imported:
                imported.append(rel)
            continue
        except ValueError:
            pass
        dest = _unique_dest(dest_dir, src.name)
        try:
            shutil.copy2(src, dest)
        except OSError:
            logger.exception("CLI media copy failed: %s", src)
            continue
        rel = dest.relative_to(ws.resolve()).as_posix()
        copied_src[src_key] = rel
        imported.append(rel)
        rewritten = _rewrite_ref(rewritten, ref, rel)
    return rewritten, imported


def _rewrite_ref(text: str, old: str, new: str) -> str:
    """Replace a media path inside markdown links, not as a raw substring."""
    if not old or old == new:
        return text
    out = text
    variants = [old]
    if "\\" in old:
        variants.append(old.replace("\\", "/"))
    elif "/" in old:
        variants.append(old.replace("/", "\\"))
    for var in variants:
        if not var or var == new:
            continue
        for left, right in (("](", ")"), ("](<", ">)")):
            needle = f"{left}{var}{right}"
            if needle in out:
                out = out.replace(needle, f"{left}{new}{right}")
    return out
