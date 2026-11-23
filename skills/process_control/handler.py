"""System skill: inspect and (after user consent) terminate local processes."""

from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger(__name__)

DESC = (
    "查询/结束本机进程。结束任何进程都必须两步：① action=query（按 pid、name 进程名或 port 端口）"
    "取得告知内容，用中文把进程作用、命令行、端口、子进程、是否 EVA 创建、结束后的影响原样告诉用户，"
    "并结束本轮等待用户回答（会附确认卡片）；② 用户点卡片「同意」或回复「同意/取消」时，"
    "系统会直接按卡片执行或取消并告诉用户，你不要再次询问、也不要重复 query。"
    "只有用户在之后另行明确同意时，才调用 action=kill，带 pid、confirm_token 和 scope（process=只结束该进程，tree=连同子进程树）。"
    "绝不能自行假设用户同意，同一轮不能查完就结束；用户说不同意/取消就不要结束。"
    "一次只结束一个明确的 PID，不支持按名称批量结束；按名/端口查到多个时列出全部让用户挑 PID。"
    "系统关键进程、EVA 自身、Grok Bot 客户端一律不能结束。"
    "也用于回答「某端口被谁占用」「这个进程是干什么的」。不要在终端里用 taskkill/kill。"
)


async def handle(
    action: str = "query",
    pid: int | None = None,
    name: str = "",
    port: int | None = None,
    confirm_token: str = "",
    scope: str = "process",
) -> str:
    act = (action or "query").strip().lower()
    try:
        from app.tools.protection import is_action_blocked

        if act == "kill" and is_action_blocked("process_control", "kill"):
            return json.dumps(
                {"ok": False, "error": "结束进程在当前路径（定时任务/工作流/Webhook）被禁用，只能在用户亲自对话里确认。"},
                ensure_ascii=False,
            )
        from app.services import process_control as pc

        if act == "query":
            res = await asyncio.to_thread(
                pc.query,
                pid=int(pid) if pid else None,
                name=(name or "").strip(),
                port=int(port) if port else None,
            )
        elif act == "kill":
            if not pid or not (confirm_token or "").strip():
                res = {
                    "ok": False,
                    "error": "kill 需要 pid 和 confirm_token。请先 action=query pid=<PID> 告知用户，等用户下一轮同意。",
                }
            else:
                res = await asyncio.to_thread(
                    pc.kill, int(pid), confirm_token, (scope or "process").strip().lower()
                )
        else:
            res = {"ok": False, "error": f"未知 action：{act}（只有 query / kill）"}
    except Exception as exc:
        logger.exception("process_control failed")
        res = {"ok": False, "error": str(exc)}
    return json.dumps(res, ensure_ascii=False, default=str)


def register(registry):
    registry.register(
        "process_control",
        DESC,
        handle,
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["query", "kill"],
                    "description": "query=查询并生成告知+确认令牌；kill=用户下一轮明确同意后才可调用",
                },
                "pid": {"type": "integer", "description": "进程 PID（kill 必填；query 三选一）"},
                "name": {"type": "string", "description": "query：按进程名查，如 python、node.exe（可能多个）"},
                "port": {"type": "integer", "description": "query：按监听端口查，如 8080"},
                "confirm_token": {"type": "string", "description": "kill：query 返回的 confirm_token（5 分钟内、一次性）"},
                "scope": {
                    "type": "string",
                    "enum": ["process", "tree"],
                    "description": "kill：process=只结束该进程（默认）；tree=连同全部子进程。按用户选择传",
                },
            },
            "required": ["action"],
        },
        source="skill",
        metadata={"timeout_sec": 60, "group": "dev", "tag": "进程"},
    )
