"""SMB media proxy for chat bubble preview.

Uses credentials from 设定 → 集成 rows that have a matching host (pysmb).
"""

from __future__ import annotations

import io
import logging
import mimetypes
import re
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


def _smb_credentials(host_override: str | None = None) -> dict[str, Any]:
    """Find SMB login from a user-created integration whose host matches."""
    from app.config_store import get_config_store

    want = (host_override or "").strip()
    raw = get_config_store().get_integrations_raw()
    rows: list[dict[str, Any]] = []
    for iid, sec in (raw or {}).items():
        if iid == "http" or not isinstance(sec, dict):
            continue
        host = str(sec.get("host") or "").strip()
        if not host:
            continue
        rows.append({"id": iid, "host": host, **sec})

    chosen: dict[str, Any] | None = None
    if want:
        for row in rows:
            if str(row.get("host") or "").strip().lower() == want.lower():
                chosen = row
                break
        if not chosen:
            raise RuntimeError(
                f"未在设定→集成中找到主机 {want} 的连接（请添加含 host 的自定义集成）"
            )
    elif len(rows) == 1:
        chosen = rows[0]
    else:
        raise RuntimeError(
            "SMB 预览需要完整 smb://主机/共享/路径，并在设定→集成中填写该主机账号"
        )

    host = want or str(chosen.get("host") or "").strip()
    try:
        port = int(chosen.get("port") or 445)
    except (TypeError, ValueError):
        port = 445
    return {
        "host": host,
        "user": str(chosen.get("user") or ""),
        "password": str(chosen.get("password") or ""),
        "port": port,
    }


def _smb_connect(host_override: str | None = None) -> Any:
    """Open an SMB connection using a matching 设定 → 集成 row."""
    from smb.SMBConnection import SMBConnection

    cfg = _smb_credentials(host_override)
    host = str(cfg.get("host") or "").strip()
    if not host:
        raise RuntimeError("未配置 SMB 主机（设定 → 集成）")
    user = str(cfg.get("user") or "")
    password = str(cfg.get("password") or "")
    port = int(cfg.get("port") or 445)
    conn = SMBConnection(
        user,
        password,
        "eva-preview",
        (host[:15] or "smb"),
        use_ntlm_v2=True,
        is_direct_tcp=True,
    )
    if not conn.connect(host, port, timeout=8):
        raise RuntimeError(f"SMB 登录失败 {user}@{host}:{port}")
    return conn


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
    """Generate pysmb path candidates (share path styles vary)."""
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

    conn = None
    try:
        conn = _smb_connect(host)
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
                conn.close()
            except Exception:
                pass


@router.get("/smb-media")
async def get_smb_media_query(
    share: str = Query(..., description="SMB share name, e.g. Video"),
    path: str = Query(..., description="Path inside share, e.g. 18+/SONE-616/SONE-616.jpg"),
    host: str | None = Query(None, description="SMB host; must match a 设定→集成 row"),
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
