"""Builtin workspace multi-action tool (project/workspace only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.tools.registry import ToolRegistry
from app.tools.safety import (
    get_workspace_root,
    normalize_workspace_relpath,
    resolve_workspace_path,
    workspace_relpath,
)


def register_workspace_tools(registry: ToolRegistry) -> None:
    workspace = get_workspace_root()

    def _ws_err(msg: str, **extra: Any) -> str:
        return json.dumps({"ok": False, "error": msg, **extra}, ensure_ascii=False)

    def _resolve(path: str | None) -> tuple[Path | None, str]:
        rel = normalize_workspace_relpath(path)
        target = resolve_workspace_path(rel)
        return target, rel

    async def list_workspace(path: str = ".") -> str:
        target, rel = _resolve(path)
        if target is None:
            return _ws_err("Path outside workspace is not allowed", path=path)
        if not target.exists():
            return _ws_err(f"Not found: {rel}", path=rel, workspace_root=str(workspace))
        if target.is_file():
            return json.dumps(
                {
                    "ok": True,
                    "type": "file",
                    "path": rel,
                    "size": target.stat().st_size,
                    "workspace_root": str(workspace),
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
                "workspace_root": str(workspace),
                "hint": "path 相对项目下 workspace/，不要再加 workspace/ 前缀",
            },
            ensure_ascii=False,
        )

    async def read_workspace_file(path: str, max_chars: int = 8000) -> str:
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
            },
            ensure_ascii=False,
        )

    async def write_workspace_file(path: str, content: str) -> str:
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
                "workspace_root": str(workspace),
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
                "workspace_root": str(workspace),
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
        act = (action or "").strip().lower()
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
                    "workspace_root": str(workspace),
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
        "【主推·工作区】统一本地文件操作（唯一入口，项目下 workspace/）。"
        "action: list|read|write|delete|find|rename|info。"
        "path 相对 workspace 根目录，例如 notes.md 或 uploads/a.jpg；"
        "禁止再加 workspace/ 前缀（会自动剥离，避免 workspace/workspace）。",
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
