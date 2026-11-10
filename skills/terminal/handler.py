"""System skill: controlled local terminal (not a raw shell)."""

from __future__ import annotations

import asyncio
import json
import logging
import re

logger = logging.getLogger(__name__)

DESC = (
    "受控终端：在 workspace（或 Eva 目录）执行本机命令。"
    "action=run 一次性同步执行（超时/停止对话会结束整棵进程树；服务器、tail -f、watch 等常驻命令会被拒绝）；"
    "bg 用于会结束的后台任务（pip/npm install/clone），立即返回 job_id，poll 查进度；kill 结束任务同样先告知、用户下一轮同意后带 confirm_token；"
    "service 仅在用户明确要求常驻服务（web 服务器、dev server、端口服务）时使用：受保护，"
    "停止对话、超时、删除会话、重启 EVA 都不会结束它；services 列出服务/看日志（service_id+tail）；"
    "stop_service 结束服务——先不带令牌调用拿到告知（作用、端口、影响）告诉用户并等待，用户下一轮明确同意后再带 confirm_token 调用；绝不自行决定停服务。"
    "结束其它（非 EVA 创建的）进程用 process_control 工具，同样先告知再确认；终端里禁止 taskkill/kill。"
    "pip/python 自动改到 Eva 的 .venv。禁止格式化磁盘、关机、注册表删除等高风险命令。"
    "普通文件用 workspace；Word/Excel/PPT/PDF 用 document。不要用本工具当文件编辑器。"
)

_START_INTENT = re.compile(
    r"启动|开启|跑起|起一个|起个|开个|部署|常驻|一直(?:跑|运行|开着)|后台运行|服务|"
    r"server|serve|确认|同意|好的|yes|start|deploy",
    re.I,
)
_STOP_INTENT = re.compile(
    r"停止|停掉|停了|关掉|关闭|关了|结束|终止|杀掉|干掉|下线|stop|kill|shut\s*down|terminate",
    re.I,
)


def _turn_message() -> str | None:
    try:
        from app.tools.protection import get_turn_user_message

        return get_turn_user_message()
    except Exception:
        return None


def _session_id() -> str | None:
    try:
        from app.tools.protection import get_turn_session_id

        return get_turn_session_id()
    except Exception:
        return None


def _action_blocked(act: str) -> bool:
    try:
        from app.tools.protection import is_action_blocked

        return is_action_blocked("terminal", act)
    except Exception:
        return False


async def handle(
    action: str = "run",
    command: str = "",
    cwd: str = "",
    root: str = "workspace",
    timeout_sec: float | None = None,
    job_id: str = "",
    tail: int = 80,
    name: str = "",
    port: int | None = None,
    service_id: str = "",
    confirm: bool = False,
    confirm_token: str = "",
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
        if act in ("service", "stop_service") and _action_blocked(act):
            result = {
                "ok": False,
                "error": f"terminal action={act} 在当前路径（定时任务/工作流/Webhook）被禁用；只能在用户对话里由用户明确要求。",
            }
        elif act == "pwd":
            result = pwd()
        elif act == "poll":
            result = await poll(job_id, tail=tail)
        elif act == "kill":
            # Model-initiated kill of an EVA bg job: inform + user consent too
            # (automatic cleanup of EVA's own runs is unaffected).
            from app.services import process_control as pc

            st = await poll(job_id, tail=5)
            if not st.get("ok"):
                result = st
            elif st.get("status") != "running" or not st.get("pid"):
                result = {"ok": False, "error": "任务已结束", **{k: st.get(k) for k in ("id", "status", "exit_code")}}
            elif not (confirm_token or "").strip():
                q = await asyncio.to_thread(pc.query, pid=int(st["pid"]))
                result = {
                    "ok": False,
                    "need_confirm": True,
                    "job": {k: st.get(k) for k in ("id", "command", "pid")},
                    **{k: q.get(k) for k in ("tell_user", "confirm_token", "form", "token_expires_in_sec", "process", "error") if k in q},
                    "next_step": "把 tell_user 告诉用户并结束本轮；用户下一轮明确同意后再 action=kill 带 job_id 和 confirm_token。",
                }
            else:
                result = await asyncio.to_thread(pc.kill, int(st["pid"]), confirm_token, "tree")
                if result.get("killed"):
                    from app.services.terminal_exec import mark_job_killed

                    mark_job_killed(job_id)
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
        elif act == "service":
            msg = _turn_message()
            if not (command or "").strip():
                result = {"ok": False, "error": "service 需要 command"}
            elif msg is not None and not _START_INTENT.search(msg) and not confirm:
                result = {
                    "ok": False,
                    "need_confirm": True,
                    "error": "用户本轮没有明确要求启动常驻服务。请先向用户说明命令/端口并征得同意。",
                }
            elif msg is None and not confirm:
                result = {
                    "ok": False,
                    "need_confirm": True,
                    "error": "启动受保护服务需要用户明确要求；用户同意后再以 confirm=true 调用。",
                }
            else:
                from app.services.service_manager import start_service_sync_safe

                result = await asyncio.to_thread(
                    start_service_sync_safe,
                    command,
                    name=name,
                    cwd=cwd or None,
                    root=root,
                    port=int(port) if port else None,
                    session_id=_session_id(),
                    created_by="user_request" if msg else "model_confirmed",
                )
        elif act == "services":
            from app.services.service_manager import list_services

            result = await asyncio.to_thread(
                list_services,
                key=(service_id or name or "").strip(),
                tail=int(tail or 0) if (service_id or name) else 0,
            )
        elif act == "stop_service":
            # Same inform-then-confirm flow as process_control (unified UX):
            # 1st call → notice + confirm_token + card; later turn with user
            # consent → kill tree via process_control (registry updated).
            key = (service_id or name or "").strip()
            if not key:
                result = {"ok": False, "error": "stop_service 需要 service_id（或 name）"}
            else:
                from app.services import process_control as pc
                from app.services.service_manager import list_services

                found = await asyncio.to_thread(list_services, key=key)
                svc = found.get("service") if found.get("ok") else None
                if not svc:
                    result = found
                elif svc.get("status") != "running":
                    result = {"ok": True, "already": svc.get("status"), "service": svc}
                elif not (confirm_token or "").strip():
                    q = await asyncio.to_thread(pc.query, pid=int(svc["pid"]))
                    result = {
                        "ok": False,
                        "need_confirm": True,
                        "service": {k: svc.get(k) for k in ("id", "name", "command", "ports", "pid")},
                        **{k: q.get(k) for k in ("tell_user", "confirm_token", "form", "token_expires_in_sec", "process") if k in q},
                        "next_step": (
                            "把 tell_user 告诉用户并结束本轮；用户下一轮明确同意后，"
                            "再调用 action=stop_service，带 service_id 和 confirm_token。"
                        ),
                    }
                else:
                    result = await asyncio.to_thread(
                        pc.kill, int(svc["pid"]), confirm_token, "tree"
                    )
        else:
            result = {"ok": False, "error": f"未知 action：{act}"}
    except ValueError as exc:
        result = {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("terminal failed")
        result = {"ok": False, "error": str(exc)}
    return json.dumps(result, ensure_ascii=False, default=str)


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
                    "enum": ["run", "bg", "poll", "kill", "pwd", "service", "services", "stop_service"],
                    "description": (
                        "run=一次性同步执行（不可用于服务器/常驻命令）；bg=会结束的后台任务；poll/kill 要 job_id；"
                        "pwd=允许的目录；service=用户明确要求的常驻服务（受保护）；services=列出服务或看某服务日志；"
                        "stop_service=停止服务（先告知、用户下一轮同意后带 confirm_token）"
                    ),
                },
                "command": {
                    "type": "string",
                    "description": "命令行，如 python -m pip install openpyxl、python script.py、python -m http.server 8765",
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
                "job_id": {"type": "string", "description": "poll / kill 用（kill 需先告知、用户同意后带 confirm_token）"},
                "tail": {"type": "integer", "description": "poll/services 时返回末尾行数，默认 80"},
                "name": {"type": "string", "description": "service：服务名（便于用户称呼）；services/stop_service 也可按名字找"},
                "port": {"type": "integer", "description": "service：服务端口（启动前检查占用）；不填会尝试从命令里识别"},
                "service_id": {"type": "string", "description": "services / stop_service 用的服务 id"},
                "confirm": {
                    "type": "boolean",
                    "description": "service：拿不到用户原话时，用户明确同意启动后才传 true。",
                },
                "confirm_token": {
                    "type": "string",
                    "description": "stop_service 第二步：第一步返回的 confirm_token（用户下一轮明确同意后才传）。",
                },
            },
        },
        source="skill",
        metadata={"timeout_sec": 320, "group": "dev", "tag": "终端"},
    )
