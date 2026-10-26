"""System skill: controlled local terminal (not a raw shell)."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

DESC = (
    "受控终端：在 workspace（或 Eva 目录）执行本机命令。"
    "action=run 同步等待（装库/克隆请用 bg，避免占对话）；"
    "bg 立即返回 job_id；poll/kill 查进度或结束。"
    "pip/python 自动改到 Eva 的 .venv。禁止格式化磁盘、关机、注册表删除等高风险命令。"
    "普通文件用 workspace；Word/Excel/PPT/PDF 用 document。不要用本工具当文件编辑器。"
)


async def handle(
    action: str = "run",
    command: str = "",
    cwd: str = "",
    root: str = "workspace",
    timeout_sec: float | None = None,
    job_id: str = "",
    tail: int = 80,
) -> str:
    from app.services.terminal_exec import (
        kill,
        poll,
        pwd,
        run_sync,
        should_autostart_bg,
        start_bg,
    )

    act = (action or "run").strip().lower()
    try:
        if act == "pwd":
            result = pwd()
        elif act == "poll":
            result = await poll(job_id, tail=tail)
        elif act == "kill":
            result = await kill(job_id)
        elif act == "bg":
            result = await start_bg(command, cwd=cwd or None, root=root)
        elif act == "run":
            if should_autostart_bg(command, "run"):
                result = await start_bg(command, cwd=cwd or None, root=root)
                result["note"] = "检测到安装/克隆类命令，已改为后台执行，以免占住对话和 token。"
            else:
                result = await run_sync(
                    command,
                    cwd=cwd or None,
                    root=root,
                    timeout_sec=timeout_sec,
                )
        else:
            result = {"ok": False, "error": f"未知 action：{act}"}
    except ValueError as exc:
        result = {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("terminal failed")
        result = {"ok": False, "error": str(exc)}
    return json.dumps(result, ensure_ascii=False)


def register(registry):
    registry.register(
        "terminal",
        DESC,
        handle,
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["run", "bg", "poll", "kill", "pwd"],
                    "description": "run=同步等结束；bg=后台；poll/kill 要 job_id；pwd=允许的目录",
                },
                "command": {
                    "type": "string",
                    "description": "命令行，如 python -m pip install openpyxl 或 python script.py",
                },
                "cwd": {
                    "type": "string",
                    "description": "相对 workspace（或 root=eva 时相对 Eva 根）的子目录，默认 .",
                },
                "root": {
                    "type": "string",
                    "enum": ["workspace", "eva"],
                    "description": "workspace=工作区（默认）；eva=项目根（装 .venv 包时用）",
                },
                "timeout_sec": {
                    "type": "number",
                    "description": "仅 run：秒，默认 90，最大 300。更长用 bg。",
                },
                "job_id": {"type": "string", "description": "poll / kill 用"},
                "tail": {"type": "integer", "description": "poll 时返回末尾行数，默认 80"},
            },
        },
        source="skill",
        metadata={"timeout_sec": 320, "group": "dev", "tag": "终端"},
    )
