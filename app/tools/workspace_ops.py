"""Builtin workspace multi-action tool (project/workspace only)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_OFFICE_BIN_EXT = {".docx", ".xlsx", ".xlsm", ".pptx", ".pdf"}

from app.tools.registry import ToolRegistry
from app.tools.safety import (
    get_workspace_root,
    normalize_workspace_relpath,
    resolve_workspace_path,
    workspace_relpath,
)


def _source_meta() -> dict[str, str]:
    try:
        from app.services.workspace_bind import binding_public

        pub = binding_public()
        if pub.get("shared"):
            return {
                "file_source": "hub",
                "file_source_label": "Hub 公司工作区（所有员工共用）",
            }
    except Exception:
        pass
    return {
        "file_source": "eva_local",
        "file_source_label": "本机 Eva 独立工作区（未接到 Hub）",
    }


def register_workspace_tools(registry: ToolRegistry) -> None:
    def _root() -> Path:
        return get_workspace_root()

    def _ws_err(msg: str, **extra: Any) -> str:
        extra.setdefault("workspace_root", str(_root()))
        extra.update(_source_meta())
        return json.dumps({"ok": False, "error": msg, **extra}, ensure_ascii=False)

    def _resolve(path: str | None) -> tuple[Path | None, str]:
        rel = normalize_workspace_relpath(path)
        target = resolve_workspace_path(rel)
        return target, rel

    def _office_bin_hint(rel: str) -> str | None:
        ext = Path(rel or "").suffix.lower()
        if ext in _OFFICE_BIN_EXT:
            return (
                f"{rel} 是办公文档，请用 document 的 action=read|write|edit|delete，"
                "不要用 workspace 当文本读写（会乱码）。"
                "重命名/移动仍可用 workspace rename。"
            )
        return None

    async def list_workspace(path: str = ".") -> str:
        try:
            from app.services.workspace_bind import uses_hub_http
            from app.services.hub_ws_client import tool_list

            if uses_hub_http():
                return tool_list(path)
        except Exception as exc:
            logger.debug("Hub workspace list failed, using local: %s", exc)
        target, rel = _resolve(path)
        if target is None:
            return _ws_err("Path outside workspace is not allowed", path=path)
        if not target.exists():
            return _ws_err(f"Not found: {rel}", path=rel, workspace_root=str(_root()))
        if target.is_file():
            return json.dumps(
                {
                    "ok": True,
                    "type": "file",
                    "path": rel,
                    "size": target.stat().st_size,
                    "workspace_root": str(_root()),
                    **_source_meta(),
                },
                ensure_ascii=False,
            )
        entries = []
        for child in sorted(target.iterdir())[:200]:
            entries.append(
                {
                    "name": child.name,
                    "type": "dir" if child.is_dir() else "file",
                    "size": child.stat().st_size if child.is_file() else None,
                }
            )
        return json.dumps(
            {
                "ok": True,
                "path": rel,
                "entries": entries,
                "workspace_root": str(_root()),
                "hint": "path 相对工作区，不要再加 workspace/ 前缀",
                **_source_meta(),
            },
            ensure_ascii=False,
        )

    async def read_workspace_file(path: str, max_chars: int = 8000) -> str:
        rel0 = normalize_workspace_relpath(path)
        hint = _office_bin_hint(rel0)
        if hint:
            return _ws_err(hint, path=rel0, use_tool="document")
        try:
            from app.services.workspace_bind import uses_hub_http
            from app.services.hub_ws_client import tool_read

            if uses_hub_http():
                return tool_read(path, max_chars=max_chars)
        except Exception as exc:
            logger.debug("Hub workspace read failed, using local: %s", exc)
        target, rel = _resolve(path)
        if target is None:
            return _ws_err("Path outside workspace is not allowed", path=path)
        if not target.is_file():
            return _ws_err(f"Not a file: {rel}", path=rel)
        text = target.read_text(encoding="utf-8", errors="replace")
        truncated = len(text) > max_chars
        return json.dumps(
            {
                "ok": True,
                "path": rel,
                "content": text[:max_chars],
                "truncated": truncated,
                "total_chars": len(text),
                **_source_meta(),
            },
            ensure_ascii=False,
        )

    async def write_workspace_file(path: str, content: str) -> str:
        rel0 = normalize_workspace_relpath(path)
        hint = _office_bin_hint(rel0)
        if hint:
            return _ws_err(hint, path=rel0, use_tool="document")
        try:
            from app.services.workspace_bind import uses_hub_http
            from app.services.hub_ws_client import tool_write

            if uses_hub_http():
                return tool_write(path, content)
        except Exception as exc:
            logger.debug("Hub workspace write failed, using local: %s", exc)
        target, rel = _resolve(path)
        if target is None:
            return _ws_err("Path outside workspace is not allowed", path=path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return json.dumps(
            {
                "ok": True,
                "path": rel,
                "bytes": len(content.encode("utf-8")),
                "workspace_root": str(_root()),
                **_source_meta(),
            },
            ensure_ascii=False,
        )

    async def delete_workspace_file(path: str) -> str:
        target, rel = _resolve(path)
        if target is None:
            return _ws_err("Path outside workspace is not allowed", path=path)
        if not target.exists():
            return _ws_err("Not found: " + rel, path=rel)
        if target.is_dir():
            return _ws_err("Path is a directory, not a file", path=rel)
        sz = target.stat().st_size
        target.unlink()
        return json.dumps({"ok": True, "deleted": rel, "bytes": sz}, ensure_ascii=False)

    async def find_files(pattern: str = "*", path: str = ".") -> str:
        import fnmatch

        base, rel = _resolve(path)
        if base is None:
            return _ws_err("Path outside workspace is not allowed", path=path)
        if not base.exists():
            return _ws_err(f"Not found: {rel}", path=rel)
        pat = (pattern or "*").strip() or "*"
        matches: list[str] = []
        if base.is_file():
            if fnmatch.fnmatch(base.name, pat):
                matches.append(workspace_relpath(base))
        else:
            for p in base.rglob("*"):
                if p.is_file() and fnmatch.fnmatch(p.name, pat):
                    matches.append(workspace_relpath(p))
                if len(matches) >= 500:
                    break
        return json.dumps(
            {
                "ok": True,
                "pattern": pat,
                "base": rel,
                "count": len(matches),
                "files": matches,
                "workspace_root": str(_root()),
            },
            ensure_ascii=False,
        )

    async def file_rename(source: str, dest: str) -> str:
        import shutil

        src, srel = _resolve(source)
        dst, drel = _resolve(dest)
        if src is None:
            return _ws_err("源路径越界", path=source)
        if dst is None:
            return _ws_err("目标路径越界", path=dest)
        if not src.exists():
            return _ws_err(f"源不存在: {srel}", path=srel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return json.dumps({"ok": True, "source": srel, "dest": drel}, ensure_ascii=False)

    async def workspace_tool(
        action: str,
        path: str = ".",
        content: str = "",
        max_chars: int = 8000,
        pattern: str = "*",
        source: str = "",
        dest: str = "",
    ) -> str:
        act = str(action if action is not None else "").strip().lower()
        if act in ("list", "ls", "dir"):
            return await list_workspace(path=path)
        if act in ("read", "cat", "get"):
            return await read_workspace_file(path=path, max_chars=max_chars)
        if act in ("write", "put", "save"):
            if not path or path in (".",):
                return _ws_err("write 需要具体文件 path")
            return await write_workspace_file(path=path, content=content)
        if act in ("delete", "rm", "remove", "unlink"):
            return await delete_workspace_file(path=path)
        if act in ("find", "search", "glob"):
            return await find_files(pattern=pattern or "*", path=path or ".")
        if act in ("rename", "move", "mv"):
            if not source or not dest:
                return _ws_err("rename 需要 source 与 dest")
            return await file_rename(source=source, dest=dest)
        if act in ("info", "root", "where"):
            return json.dumps(
                {
                    "ok": True,
                    "workspace_root": str(_root()),
                    "hint": (
                        "所有 path 均相对于此目录，例如 uploads/a.jpg 或 notes.md；"
                        "不要写 workspace/uploads/a.jpg（会自动去掉多余前缀）。"
                    ),
                },
                ensure_ascii=False,
            )
        return _ws_err(
            f"Unknown action: {action}. Use list|read|write|delete|find|rename|info"
        )

    registry.register(
        "workspace",
        "【工作区】目录与普通文件：list|read|write|delete|find|rename|info。"
        "txt/代码/图片/任意文件名用本工具；Word/Excel/PPT/PDF 用 document（读文本会乱码）。"
        "Markdown 短笔记可用本工具；要按标题/查找替换也可用 document。"
        "path 相对工作区，如 notes.md、uploads/a.jpg，不要加 workspace/ 前缀。",
        workspace_tool,
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list",
                        "read",
                        "write",
                        "delete",
                        "find",
                        "rename",
                        "info",
                    ],
                    "description": "list=列目录; read=读文件; write=写文件; delete=删文件; find=glob; rename=重命名; info=根路径",
                },
                "path": {
                    "type": "string",
                    "description": "相对 workspace 的路径",
                    "default": ".",
                },
                "content": {"type": "string", "description": "write 时文件内容"},
                "max_chars": {
                    "type": "integer",
                    "description": "read 最大字符数",
                    "default": 8000,
                },
                "pattern": {
                    "type": "string",
                    "description": "find 的文件名 glob",
                    "default": "*",
                },
                "source": {"type": "string", "description": "rename 源路径"},
                "dest": {"type": "string", "description": "rename 目标路径"},
            },
            "required": ["action"],
        },
        source="builtin",
    )
