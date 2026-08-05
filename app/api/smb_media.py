"""SMB/NAS media proxy for chat bubble preview.

Reuses connection defaults from skills/nas/handler.py without modifying that file.
Streams images/videos into the browser via HTTP so <img>/<video> can load them.
"""

from __future__ import annotations

import importlib.util
import io
import logging
import mimetypes
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

MAX_PREVIEW_BYTES = 80 * 1024 * 1024

_EXTRA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
    ".mkv": "video/x-matroska",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}


@lru_cache(maxsize=1)
def _load_nas_handler() -> Any:
    """Load skills/nas/handler.py for DEFAULT_* and _get_conn (no edits to that file)."""
    handler_py = Path(__file__).resolve().parents[2] / "skills" / "nas" / "handler.py"
    if not handler_py.is_file():
        raise RuntimeError(f"NAS skill not found: {handler_py}")
    spec = importlib.util.spec_from_file_location("skills_nas_handler_media", handler_py)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load NAS handler module")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _media_type(name: str) -> str:
    ext = Path(name or "").suffix.lower()
    if ext in _EXTRA_TYPES:
        return _EXTRA_TYPES[ext]
    guessed, _ = mimetypes.guess_type(name or "")
    return guessed or "application/octet-stream"


def _normalize_smb_path(raw: str) -> str:
    """Normalize share-relative path (no host/share prefix, no ..)."""
    # unquote only %XX — do NOT turn + into space (critical for folders like 18+)
    p = unquote((raw or "").strip())
    # common mistakes: + already became space in querystring
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    p = p.lstrip("/")
    parts = [seg for seg in p.split("/") if seg not in ("", ".")]
    if any(seg == ".." for seg in parts):
        return ""
    return "/".join(parts)


def _safe_share(name: str) -> str:
    s = unquote((name or "").strip()).replace("\\", "/").strip("/")
    if not s or "/" in s or ".." in s or re.search(r"[\x00-\x1f]", s):
        return ""
    return s


def _path_variants(rel: str) -> list[str]:
    """Generate pysmb path candidates (NAS path styles vary)."""
    rel = (rel or "").replace("\\", "/").strip("/")
    if not rel:
        return []
    parts = rel.split("/")
    # Fix "18 /SONE" if + was turned into space before "digit"
    fixed_parts = []
    for seg in parts:
        # "18 " alone is unlikely; keep as-is unless pattern 18 + next
        fixed_parts.append(seg)
    rel_fixed = "/".join(fixed_parts)

    cands: list[str] = []
    for r in {rel, rel_fixed}:
        if not r:
            continue
        cands.append(r)
        cands.append(r.replace("/", "\\"))
        cands.append("/" + r)
        cands.append("\\" + r.replace("/", "\\"))
        cands.append("/" + r.replace("/", "\\"))
    # de-dupe preserve order
    out: list[str] = []
    seen: set[str] = set()
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _resolve_share_name(conn: Any, share: str) -> str:
    """Case-insensitive share match (Video vs video)."""
    want = (share or "").strip()
    if not want:
        return ""
    try:
        shares = conn.listShares()
        names = [s.name for s in shares if getattr(s, "name", None)]
    except Exception:
        return want
    for n in names:
        if n == want:
            return n
    for n in names:
        if n.lower() == want.lower():
            return n
    return want


def _retrieve(conn: Any, share: str, rel: str) -> tuple[bytes, str]:
    """Try path variants; return (data, used_path)."""
    last_err: Exception | None = None
    for cand in _path_variants(rel):
        buf = io.BytesIO()
        try:
            _attrs, size = conn.retrieveFile(share, cand, buf)
            if size is not None and int(size) > MAX_PREVIEW_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large for preview (>{MAX_PREVIEW_BYTES // (1024 * 1024)}MB)",
                )
            data = buf.getvalue()
            if len(data) > MAX_PREVIEW_BYTES:
                raise HTTPException(status_code=413, detail="File too large for preview")
            if data:
                return data, cand
        except HTTPException:
            raise
        except Exception as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    raise FileNotFoundError(rel)


def _search_filename(conn: Any, share: str, filename: str, max_depth: int = 5) -> str | None:
    """Find share-relative path ending with filename (best-effort)."""
    target = (filename or "").lower()
    if not target:
        return None
    found: list[str] = []

    def walk(path: str, depth: int) -> None:
        if depth > max_depth or found:
            return
        try:
            items = conn.listPath(share, path)
        except Exception:
            return
        for it in items:
            name = it.filename
            if name in (".", ".."):
                continue
            if path in ("/", ""):
                child = "/" + name
                rel = name
            else:
                # keep same separator style as path
                if "\\" in path:
                    child = path.rstrip("\\") + "\\" + name
                    rel = child.lstrip("\\").replace("\\", "/")
                else:
                    child = path.rstrip("/") + "/" + name
                    rel = child.lstrip("/")
            if name.lower() == target and not it.isDirectory:
                found.append(rel.replace("\\", "/"))
                return
            if it.isDirectory:
                walk(child, depth + 1)

    walk("/", 0)
    return found[0] if found else None


def _serve_smb(share: str, path: str, host: str | None = None) -> Response:
    share_name = _safe_share(share)
    # Restore + if querystring turned "18+" into "18 "
    raw_path = path or ""
    raw_path = raw_path.replace("18 /", "18+/").replace("18 \\", "18+\\")
    rel = _normalize_smb_path(raw_path)
    if not share_name or not rel:
        raise HTTPException(status_code=400, detail="Invalid share or path")

    try:
        nas = _load_nas_handler()
    except Exception as e:
        logger.exception("Load NAS handler failed")
        raise HTTPException(status_code=500, detail=f"NAS skill unavailable: {e}") from e

    # Prefer live config (DEFAULT_* may be empty until _defaults runs)
    try:
        refresh = getattr(nas, "_defaults", None)
        if callable(refresh):
            refresh()
    except Exception:
        pass
    default_host = (
        getattr(nas, "DEFAULT_HOST", None)
        or ""
    ).strip()
    use_host = (host or "").strip() or default_host
    if use_host != default_host:
        raise HTTPException(
            status_code=403,
            detail=f"Host not allowed for preview (only {default_host})",
        )

    conn = None
    try:
        get_conn = getattr(nas, "_get_conn")
        conn = get_conn(host=use_host)
        share_name = _resolve_share_name(conn, share_name)

        try:
            data, used = _retrieve(conn, share_name, rel)
        except HTTPException:
            raise
        except Exception as first_err:
            # Fallback: search by filename within share (helps SONE-616.jpg without folder)
            fname = Path(rel).name
            logger.info(
                "SMB direct open failed share=%s path=%s err=%s; try search %s",
                share_name,
                rel,
                first_err,
                fname,
            )
            found = _search_filename(conn, share_name, fname)
            if not found:
                raise FileNotFoundError(
                    f"{share_name}/{rel} (also searched for {fname})"
                ) from first_err
            data, used = _retrieve(conn, share_name, found)

        filename = Path(rel).name
        media_type = _media_type(filename)
        return Response(
            content=data,
            media_type=media_type,
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                "Cache-Control": "private, max-age=120",
                "X-Content-Type-Options": "nosniff",
                "X-SMB-Path": used.replace("\\", "/"),
            },
        )
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"SMB file not found: {e}") from e
    except Exception as e:
        msg = str(e)
        logger.warning("SMB media failed share=%s path=%s: %s", share_name, rel, msg)
        lower = msg.lower()
        if (
            "not found" in lower
            or "object_name" in lower
            or "0xc0000034" in lower
            or "unable to open" in lower
            or "0xc000000f" in lower
            or "0xc000003a" in lower
        ):
            raise HTTPException(
                status_code=404, detail=f"SMB file not found: {share_name}/{rel}"
            ) from e
        if "connect" in lower or "timed out" in lower:
            raise HTTPException(status_code=502, detail=f"SMB connection failed: {msg}") from e
        raise HTTPException(status_code=500, detail=f"SMB read failed: {msg}") from e
    finally:
        if conn is not None:
            try:
                getattr(nas, "_close_conn")(conn)
            except Exception:
                pass


@router.get("/smb-media")
async def get_smb_media_query(
    share: str = Query(..., description="SMB share name, e.g. Video"),
    path: str = Query(..., description="Path inside share, e.g. 18+/SONE-616/SONE-616.jpg"),
    host: str | None = Query(None, description="Optional host (default nas skill host)"),
) -> Response:
    """
    Query form (note: encode '+' as %2B):
      /api/workspace/smb-media?share=Video&path=18%2B/SONE-616/SONE-616.jpg
    Prefer path form below when possible.
    """
    return _serve_smb(share, path, host)


@router.get("/smb-media/{share}/{file_path:path}")
async def get_smb_media_path(
    share: str,
    file_path: str,
    host: str | None = Query(None),
) -> Response:
    """
    Path form (preferred; avoids '+' querystring pitfalls):
      /api/workspace/smb-media/Video/18+/SONE-616/SONE-616.jpg
    """
    return _serve_smb(share, file_path, host)
