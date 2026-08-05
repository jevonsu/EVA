"""Serve / upload workspace files safely for UI media preview."""

from __future__ import annotations

import mimetypes
import re
import time
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.tools.safety import get_workspace_root, resolve_workspace_path

router = APIRouter(prefix="/api/workspace", tags=["workspace"])
UPLOAD_ROOT = "uploads"

# 单文件上限（字节）
MAX_UPLOAD_BYTES = 40 * 1024 * 1024
MAX_FILES_PER_REQUEST = 12
MAX_TEXT_EDIT_BYTES = 2 * 1024 * 1024

_TEXT_EDIT_EXT = frozenset(
    {
        ".txt",
        ".md",
        ".markdown",
        ".json",
        ".jsonl",
        ".csv",
        ".tsv",
        ".py",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".jsx",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".less",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".log",
        ".xml",
        ".svg",
        ".env",
        ".sh",
        ".bat",
        ".ps1",
        ".sql",
        ".r",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".vue",
        ".svelte",
        ".php",
        ".rb",
        ".pl",
        ".lua",
        ".gitignore",
        ".dockerignore",
        ".editorconfig",
        ".rhai",
    }
)

_BLOCKED_EXT = frozenset(
    {
        ".exe",
        ".bat",
        ".cmd",
        ".com",
        ".msi",
        ".scr",
        ".ps1",
        ".vbs",
        ".js",
        ".jse",
        ".wsf",
        ".wsh",
        ".dll",
        ".sys",
        ".sh",
        ".bash",
        ".zsh",
        ".jar",
        ".apk",
        ".dmg",
        ".app",
    }
)

# Prefer explicit types for common media (Windows mimetypes can be incomplete)
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
    ".ogg": "video/ogg",
    ".ogv": "video/ogg",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _workspace_root() -> Path:
    return get_workspace_root()


def _normalize_rel_path(raw: str) -> str:
    """Strip common prefixes / URL encoding so UI paths map into workspace."""
    from app.tools.safety import normalize_workspace_relpath

    p = unquote((raw or "").strip())
    parts = [seg for seg in p.replace("\\", "/").split("/") if seg not in ("", ".")]
    if any(seg == ".." for seg in parts):
        return ""
    norm = normalize_workspace_relpath(p)
    return "" if norm == "." else norm


def _media_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _EXTRA_TYPES:
        return _EXTRA_TYPES[ext]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


@router.get("/browse")
async def browse_workspace(
    path: str = "",
    dirs_only: bool = False,
    limit: int = 300,
) -> dict:
    """List workspace entries for UI path pickers (relative to workspace/).

    - ``path`` empty or ``.`` = workspace root
    - ``parent`` is ``null`` at root; ``""`` means parent is root; otherwise relative path
    """
    raw = (path or "").strip()
    if not raw or raw in (".", "./"):
        rel = ""
    else:
        rel = _normalize_rel_path(raw)

    root = _workspace_root()
    target = root if not rel else resolve_workspace_path(root, rel)
    if target is None:
        raise HTTPException(status_code=403, detail="Path outside workspace is not allowed")
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {rel or '.'}")
    if target.is_file():
        raise HTTPException(status_code=400, detail="Path is a file; pass a directory")

    if not rel:
        parent: str | None = None
        display = "."
        path_display = "工作区根目录"
    else:
        parent_s = str(Path(rel).parent).replace("\\", "/")
        parent = "" if parent_s in (".", "") else parent_s
        display = rel
        path_display = rel

    entries: list[dict] = []
    try:
        children = sorted(
            target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    lim = max(1, min(int(limit or 300), 500))
    for child in children:
        if child.name.startswith("."):
            continue
        is_dir = child.is_dir()
        if dirs_only and not is_dir:
            continue
        child_rel = str(child.relative_to(root)).replace("\\", "/")
        item: dict = {
            "name": child.name,
            "path": child_rel,
            "type": "dir" if is_dir else "file",
        }
        if not is_dir:
            try:
                item["size"] = child.stat().st_size
            except OSError:
                item["size"] = None
        entries.append(item)
        if len(entries) >= lim:
            break

    return {
        "ok": True,
        "path": display,
        "path_display": path_display,
        "parent": parent,
        "entries": entries,
        "dirs_only": bool(dirs_only),
        "count": len(entries),
    }


@router.get("/uploads")
async def list_uploads(
    limit: int = 200,
    days: int = 0,
) -> dict:
    """List files under workspace/uploads for reuse in chat (no re-upload).

    Sorted by mtime descending. ``days``>0 only returns folders from last N day names
    (YYYYMMDD) plus any non-dated files.
    """
    root = _workspace_root()
    up = root / UPLOAD_ROOT
    if not up.exists() or not up.is_dir():
        return {
            "ok": True,
            "root": UPLOAD_ROOT,
            "count": 0,
            "files": [],
            "days": [],
        }

    lim = max(1, min(int(limit or 200), 500))
    day_filter: set[str] | None = None
    if days and int(days) > 0:
        import datetime as _dt

        day_filter = set()
        today = _dt.date.today()
        for i in range(int(days)):
            day_filter.add((today - _dt.timedelta(days=i)).strftime("%Y%m%d"))

    files: list[dict] = []
    day_dirs: set[str] = set()
    try:
        for path in up.rglob("*"):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            try:
                rel = str(path.relative_to(root)).replace("\\", "/")
            except ValueError:
                continue
            # uploads/YYYYMMDD/...
            parts = rel.split("/")
            day_key = parts[1] if len(parts) >= 3 and parts[0] == UPLOAD_ROOT else ""
            if day_key and len(day_key) == 8 and day_key.isdigit():
                day_dirs.add(day_key)
                if day_filter is not None and day_key not in day_filter:
                    continue
            try:
                st = path.stat()
                size = st.st_size
                mtime = st.st_mtime
            except OSError:
                size = 0
                mtime = 0
            mt = _media_type(path)
            kind = (
                "image"
                if mt.startswith("image/")
                else "video"
                if mt.startswith("video/")
                else "audio"
                if mt.startswith("audio/")
                else "file"
            )
            files.append(
                {
                    "path": rel,
                    "name": path.name,
                    "size": size,
                    "mtime": mtime,
                    "media_type": mt,
                    "kind": kind,
                    "preview_url": f"/api/workspace/media/{rel}",
                    "day": day_key or "",
                }
            )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    files.sort(key=lambda x: float(x.get("mtime") or 0), reverse=True)
    files = files[:lim]
    return {
        "ok": True,
        "root": UPLOAD_ROOT,
        "count": len(files),
        "files": files,
        "days": sorted(day_dirs, reverse=True),
    }


@router.get("/media/{file_path:path}")
async def get_workspace_media(file_path: str) -> FileResponse:
    """
    Stream a file from ./workspace for chat bubble preview.
    Path traversal outside workspace is rejected.
    """
    rel = _normalize_rel_path(file_path)
    if not rel or rel in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid path")

    root = _workspace_root()
    target = resolve_workspace_path(root, rel)
    if target is None:
        raise HTTPException(status_code=403, detail="Path outside workspace is not allowed")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {rel}")

    return FileResponse(
        path=str(target),
        media_type=_media_type(target),
        filename=target.name,
        content_disposition_type="inline",
    )


@router.get("/download")
async def download_workspace_file(path: str) -> FileResponse:
    """Download a workspace file as attachment (forces save dialog)."""
    rel, target = _resolve_rel(path, must_exist=True, expect="file")
    return FileResponse(
        path=str(target),
        media_type=_media_type(target),
        filename=target.name,
        content_disposition_type="attachment",
    )


def _safe_filename(name: str) -> str:
    base = Path(name or "file").name
    base = base.replace("\\", "/").split("/")[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base)
    base = re.sub(r"[^\w\u4e00-\u9fff.\- ()（）\[\]【】]+", "_", base, flags=re.UNICODE)
    base = base.strip(" .")
    if not base or base in (".", ".."):
        base = f"file_{int(time.time())}"
    if len(base) > 120:
        stem = Path(base).stem[:80]
        suf = Path(base).suffix[:20]
        base = stem + suf
    return base


def _unique_path(dir_path: Path, filename: str) -> Path:
    candidate = dir_path / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suf = Path(filename).suffix
    for i in range(1, 200):
        c = dir_path / f"{stem}_{i}{suf}"
        if not c.exists():
            return c
    return dir_path / f"{stem}_{int(time.time())}{suf}"


@router.post("/upload")
async def upload_workspace_files(
    files: list[UploadFile] = File(..., description="One or more files"),
    dest: str = Form(
        default="",
        description="目标目录（相对 workspace/）",
    ),
    mode: str = Form(
        default="chat",
        description="chat=默认 uploads/日期；panel=写入 dest 指定目录（空=工作区根）",
    ),
) -> dict:
    """
    上传文件到 workspace。
    - mode=chat（默认）：workspace/uploads/YYYYMMDD/（对话附件）
    - mode=panel：写入 dest 当前目录；dest 空则为 workspace 根
    返回 saved 列表：path（相对 workspace）、name、size、media_type、preview_url。
    """
    if not files:
        raise HTTPException(status_code=400, detail="未选择文件")
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多上传 {MAX_FILES_PER_REQUEST} 个文件",
        )

    root = _workspace_root()
    mode_n = (mode or "chat").strip().lower()
    dest_rel = _normalize_rel_path(dest or "")

    if mode_n != "panel":
        # 对话附件：固定 uploads/日期
        day = time.strftime("%Y%m%d")
        dest_dir = root / UPLOAD_ROOT / day
        upload_dir_label = f"{UPLOAD_ROOT}/{day}"
    elif not dest_rel:
        dest_dir = root
        upload_dir_label = "."
    else:
        target = resolve_workspace_path(root, dest_rel)
        if target is None:
            raise HTTPException(status_code=403, detail="目标路径不在 workspace 内")
        if target.exists() and not target.is_dir():
            raise HTTPException(status_code=400, detail="目标路径不是目录")
        dest_dir = target
        upload_dir_label = dest_rel
    dest_dir.mkdir(parents=True, exist_ok=True)

    saved: list[dict] = []
    errors: list[dict] = []

    for uf in files:
        original = uf.filename or "file"
        safe_name = _safe_filename(original)
        ext = Path(safe_name).suffix.lower()
        if ext in _BLOCKED_EXT:
            errors.append({"name": original, "error": f"不允许的文件类型: {ext}"})
            continue

        out_path = _unique_path(dest_dir, safe_name)
        size = 0
        try:
            with out_path.open("wb") as f:
                while True:
                    chunk = await uf.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        try:
                            out_path.unlink(missing_ok=True)
                        except OSError:
                            pass
                        errors.append(
                            {
                                "name": original,
                                "error": f"超过大小限制 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
                            }
                        )
                        size = -1
                        break
                    f.write(chunk)
        except Exception as exc:
            try:
                out_path.unlink(missing_ok=True)
            except OSError:
                pass
            errors.append({"name": original, "error": str(exc)})
            continue
        finally:
            await uf.close()

        if size < 0:
            continue
        if size == 0:
            try:
                out_path.unlink(missing_ok=True)
            except OSError:
                pass
            errors.append({"name": original, "error": "空文件"})
            continue

        rel = str(out_path.relative_to(root)).replace("\\", "/")
        mt = _media_type(out_path)
        saved.append(
            {
                "path": rel,
                "name": out_path.name,
                "original_name": original,
                "size": size,
                "media_type": mt,
                "preview_url": f"/api/workspace/media/{rel}",
                "kind": (
                    "image"
                    if mt.startswith("image/")
                    else "video"
                    if mt.startswith("video/")
                    else "audio"
                    if mt.startswith("audio/")
                    else "file"
                ),
            }
        )

    if not saved and errors:
        raise HTTPException(
            status_code=400,
            detail={"message": "上传失败", "errors": errors},
        )

    return {
        "ok": True,
        "count": len(saved),
        "saved": saved,
        "errors": errors,
        "upload_dir": upload_dir_label,
    }


def _is_text_editable(path: Path) -> bool:
    name = path.name.lower()
    if name in (".gitignore", ".dockerignore", ".editorconfig", ".env"):
        return True
    ext = path.suffix.lower()
    if ext in _TEXT_EDIT_EXT:
        return True
    # no suffix small files often text
    if not ext and path.is_file():
        try:
            return path.stat().st_size <= 256 * 1024
        except OSError:
            return False
    return False


def _resolve_rel(rel_raw: str, *, must_exist: bool = False, expect: str | None = None) -> tuple[str, Path]:
    """Return (normalized rel, absolute path) inside workspace."""
    rel = _normalize_rel_path(rel_raw)
    if not rel or rel in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid path")
    root = _workspace_root()
    target = resolve_workspace_path(root, rel)
    if target is None:
        raise HTTPException(status_code=403, detail="Path outside workspace is not allowed")
    if must_exist and not target.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {rel}")
    if expect == "file" and target.exists() and not target.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")
    if expect == "dir" and target.exists() and not target.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")
    return rel, target


class WorkspaceWriteBody(BaseModel):
    path: str = Field(..., min_length=1, description="Relative path under workspace/")
    content: str = Field(default="", description="UTF-8 text content")
    create_parents: bool = Field(default=True, description="Create parent dirs if missing")


class WorkspaceMkdirBody(BaseModel):
    path: str = Field(..., min_length=1)
    create_parents: bool = True


class WorkspaceRenameBody(BaseModel):
    path: str = Field(..., min_length=1)
    new_path: str = Field(..., min_length=1)


@router.get("/file")
async def read_workspace_file(path: str) -> dict:
    """Read a text file from workspace for the settings editor."""
    rel, target = _resolve_rel(path, must_exist=True, expect="file")
    try:
        size = target.stat().st_size
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if size > MAX_TEXT_EDIT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大（>{MAX_TEXT_EDIT_BYTES // (1024 * 1024)}MB），请用工具或本地编辑器",
        )
    editable = _is_text_editable(target)
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    # reject likely binary
    if b"\x00" in raw[:8192]:
        raise HTTPException(status_code=415, detail="二进制文件不可在线编辑")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="无法按 UTF-8 解码") from exc
    return {
        "ok": True,
        "path": rel,
        "name": target.name,
        "size": size,
        "editable": editable,
        "content": text,
        "media_type": _media_type(target),
    }


@router.put("/file")
async def write_workspace_file(body: WorkspaceWriteBody) -> dict:
    """Create or overwrite a text file under workspace/."""
    rel, target = _resolve_rel(body.path, must_exist=False)
    if target.exists() and target.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory")
    content = body.content if body.content is not None else ""
    data = content.encode("utf-8")
    if len(data) > MAX_TEXT_EDIT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"内容超过 {MAX_TEXT_EDIT_BYTES // (1024 * 1024)}MB 限制",
        )
    # block dangerous extensions for new writes still allowed for text edit set
    ext = target.suffix.lower()
    if ext in _BLOCKED_EXT and ext not in (".js", ".ps1", ".sh", ".bat"):
        # keep blocked list for true binaries; allow common text scripts in editor
        raise HTTPException(status_code=400, detail=f"不允许的文件类型: {ext}")
    try:
        if body.create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        elif not target.parent.exists():
            raise HTTPException(status_code=400, detail="父目录不存在")
        target.write_bytes(data)
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "ok": True,
        "path": rel,
        "name": target.name,
        "size": len(data),
        "media_type": _media_type(target),
    }


@router.delete("/entry")
async def delete_workspace_entry(path: str, recursive: bool = False) -> dict:
    """Delete a file or directory under workspace/.

    Directories require ``recursive=true`` when non-empty.
    """
    rel, target = _resolve_rel(path, must_exist=True)
    root = _workspace_root()
    if target.resolve() == root.resolve():
        raise HTTPException(status_code=400, detail="不能删除工作区根目录")
    try:
        if target.is_file() or target.is_symlink():
            target.unlink()
            kind = "file"
        elif target.is_dir():
            kind = "dir"
            if recursive:
                import shutil

                shutil.rmtree(target)
            else:
                try:
                    target.rmdir()
                except OSError as exc:
                    raise HTTPException(
                        status_code=400,
                        detail="目录非空，请勾选递归删除或先清空内容",
                    ) from exc
        else:
            raise HTTPException(status_code=400, detail="无法删除该类型条目")
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "path": rel, "type": kind, "deleted": True}


@router.post("/mkdir")
async def mkdir_workspace(body: WorkspaceMkdirBody) -> dict:
    """Create a directory under workspace/."""
    rel, target = _resolve_rel(body.path, must_exist=False)
    if target.exists():
        if target.is_dir():
            return {"ok": True, "path": rel, "existed": True}
        raise HTTPException(status_code=400, detail="同名文件已存在")
    try:
        target.mkdir(parents=bool(body.create_parents), exist_ok=False)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail="父目录不存在") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "path": rel, "existed": False}


@router.post("/rename")
async def rename_workspace_entry(body: WorkspaceRenameBody) -> dict:
    """Rename or move a file/directory within workspace/."""
    src_rel, src = _resolve_rel(body.path, must_exist=True)
    dst_rel, dst = _resolve_rel(body.new_path, must_exist=False)
    root = _workspace_root()
    if src.resolve() == root.resolve():
        raise HTTPException(status_code=400, detail="不能重命名工作区根目录")
    if dst.exists():
        raise HTTPException(status_code=400, detail=f"目标已存在: {dst_rel}")
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "ok": True,
        "from": src_rel,
        "to": dst_rel,
        "type": "dir" if dst.is_dir() else "file",
    }
