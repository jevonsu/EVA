"""Controlled local process runner for the terminal system skill.

Sync `run` blocks the chat turn (no tokens while waiting).
`bg` returns a job id immediately; poll/kill manage it.
Cwd is locked to workspace or the Eva project (for .venv pip).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.services.terminal_exec")

CREATE_NO_WINDOW = 0x08000000
MAX_CAPTURE = 12_000
MAX_LOG_BYTES = 2 * 1024 * 1024
SYNC_TIMEOUT_DEFAULT = 90
SYNC_TIMEOUT_MAX = 300

_DENY = (
    re.compile(r"\bformat\s+[a-z]:", re.I),
    re.compile(r"\bdiskpart\b", re.I),
    re.compile(r"\bbcdedit\b", re.I),
    re.compile(r"\bshutdown\b", re.I),
    re.compile(r"\brestart-computer\b", re.I),
    re.compile(r"\bstop-computer\b", re.I),
    re.compile(r"\breg\s+delete\b", re.I),
    re.compile(r"\brm\s+-rf\s+/", re.I),
    re.compile(r"\bdel\s+/[sfq]+\s+[c-z]:\\", re.I),
    re.compile(r"remove-item\s+.*-recurse.*[c-z]:\\", re.I),
    re.compile(r"\binvoke-expression\b|\biex\s*\(", re.I),
    re.compile(r"downloadstring\s*\(|frombase64string", re.I),
    re.compile(r"start-process\s+.*-verb\s+runas", re.I),
    re.compile(r"\bnet\s+(user|localgroup)\b", re.I),
    re.compile(r"\bschtasks\s+/create\b", re.I),
    re.compile(r"powershell\s+(-e|-enc|-encodedcommand)\b", re.I),
    re.compile(r"cmd\s+/c\s+.*&\s*rd\s+/s", re.I),
)

_AUTO_BG = re.compile(
    r"\b(pip|pip3|npm|pnpm|yarn)\b.*\b(install|ci|add)\b|\bgit\s+clone\b|\bnpm\s+i\b",
    re.I,
)

_jobs: dict[str, dict[str, Any]] = {}
_lock = asyncio.Lock()


def _roots() -> tuple[Path, Path]:
    from app.config import PROJECT_ROOT

    eva = Path(PROJECT_ROOT).resolve()
    try:
        from app.services.workspace_bind import resolved_root

        ws = resolved_root()
    except Exception:
        ws = eva / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return eva, ws


def _venv_python(eva: Path) -> Path | None:
    if os.name == "nt":
        p = eva / ".venv" / "Scripts" / "python.exe"
    else:
        p = eva / ".venv" / "bin" / "python"
    return p if p.is_file() else None


def _jobs_dir(eva: Path) -> Path:
    d = eva / "data" / "terminal_jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def resolve_cwd(cwd: str | None, *, root: str = "workspace") -> Path:
    from app.tools.safety import normalize_workspace_relpath

    eva, ws = _roots()
    base = ws if (root or "workspace").strip().lower() != "eva" else eva
    raw = (cwd or "").strip().replace("\\", "/")
    if not raw or raw in (".", "./"):
        target = base
    else:
        p = Path(raw)
        if p.is_absolute():
            target = p
        elif base == ws:
            rel = normalize_workspace_relpath(raw)
            target = ws if rel in (".", "") else (ws / rel)
        else:
            target = base / p
    target = target.resolve()
    if not (_under(target, ws) or _under(target, eva)):
        raise ValueError(f"工作目录不允许：{target}（只能在 workspace 或 Eva 目录内）")
    target.mkdir(parents=True, exist_ok=True)
    return target


def split_command(command: str) -> list[str]:
    line = (command or "").strip()
    if not line:
        raise ValueError("command 为空")
    # posix=True so python -c "print(1)" keeps the script as one argv.
    # We exec the list (not cmd.exe), so POSIX quoting is the right split.
    try:
        parts = shlex.split(line, posix=True)
    except ValueError:
        try:
            parts = shlex.split(line, posix=False)
        except ValueError:
            parts = line.split()
    if not parts:
        raise ValueError("无法解析 command")
    return parts


def deny_reason(command: str) -> str | None:
    for rx in _DENY:
        if rx.search(command or ""):
            return f"拒绝执行（高风险）：匹配 {rx.pattern}"
    return None


def rewrite_argv(argv: list[str], eva: Path) -> list[str]:
    if not argv:
        return argv
    py = _venv_python(eva)
    head = Path(argv[0]).name.lower()
    if py and head in {"pip", "pip3", "pip.exe"}:
        return [str(py), "-m", "pip", *argv[1:]]
    if py and head in {"python", "python3", "py", "python.exe"}:
        # keep absolute interpreter the user named; otherwise Eva venv
        if Path(argv[0]).is_absolute() and Path(argv[0]).is_file():
            return argv
        return [str(py), *argv[1:]]
    return argv


def _clip(text: str, limit: int = MAX_CAPTURE) -> str:
    if len(text) <= limit:
        return text
    return text[: limit // 2] + "\n…(截断)…\n" + text[-(limit // 2) :]


def _dump_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job.get("id"),
        "status": job.get("status"),
        "command": job.get("command"),
        "cwd": job.get("cwd"),
        "pid": job.get("pid"),
        "exit_code": job.get("exit_code"),
        "started_at": job.get("started_at"),
        "ended_at": job.get("ended_at"),
        "log_path": job.get("log_path"),
    }


async def _pump(proc: asyncio.subprocess.Process, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with log_path.open("ab") as fh:
        assert proc.stdout is not None
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            if size < MAX_LOG_BYTES:
                take = chunk[: max(0, MAX_LOG_BYTES - size)]
                fh.write(take)
                size += len(take)
                fh.flush()
        code = await proc.wait()
    return int(code if code is not None else -1)


async def run_sync(
    command: str,
    *,
    cwd: str | None = None,
    root: str = "workspace",
    timeout_sec: float | None = None,
) -> dict[str, Any]:
    denied = deny_reason(command)
    if denied:
        return {"ok": False, "error": denied}
    eva, _ws = _roots()
    work = resolve_cwd(cwd, root=root)
    argv = rewrite_argv(split_command(command), eva)
    timeout = SYNC_TIMEOUT_DEFAULT if timeout_sec is None else float(timeout_sec)
    timeout = max(5.0, min(timeout, SYNC_TIMEOUT_MAX))
    jid = uuid.uuid4().hex[:10]
    log_path = _jobs_dir(eva) / f"{jid}.log"
    kw: dict[str, Any] = {
        "cwd": str(work),
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.STDOUT,
    }
    if os.name == "nt":
        kw["creationflags"] = CREATE_NO_WINDOW
    started = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(*argv, **kw)
    except FileNotFoundError:
        return {
            "ok": False,
            "error": f"找不到命令：{argv[0]}。请确认已安装并在 PATH 中。",
            "argv": argv,
        }
    try:
        code = await asyncio.wait_for(_pump(proc, log_path), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
        return {
            "ok": False,
            "error": f"超时 {int(timeout)}s，进程已结束。长任务请用 action=bg。",
            "id": jid,
            "argv": argv,
            "cwd": str(work),
            "output": _clip(text),
            "log_path": str(log_path),
        }
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    return {
        "ok": code == 0,
        "id": jid,
        "exit_code": code,
        "argv": argv,
        "cwd": str(work),
        "elapsed_sec": round(time.time() - started, 2),
        "output": _clip(text),
        "log_path": str(log_path),
        "hint": None if code == 0 else "失败时看 output / log_path；装依赖请用 Eva 的 python -m pip。",
    }


async def start_bg(
    command: str,
    *,
    cwd: str | None = None,
    root: str = "workspace",
) -> dict[str, Any]:
    denied = deny_reason(command)
    if denied:
        return {"ok": False, "error": denied}
    eva, _ws = _roots()
    work = resolve_cwd(cwd, root=root)
    argv = rewrite_argv(split_command(command), eva)
    jid = uuid.uuid4().hex[:10]
    log_path = _jobs_dir(eva) / f"{jid}.log"
    job = {
        "id": jid,
        "status": "running",
        "command": command,
        "argv": argv,
        "cwd": str(work),
        "pid": None,
        "exit_code": None,
        "started_at": time.time(),
        "ended_at": None,
        "log_path": str(log_path),
        "proc": None,
    }
    kw: dict[str, Any] = {
        "cwd": str(work),
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.STDOUT,
    }
    if os.name == "nt":
        kw["creationflags"] = CREATE_NO_WINDOW
    try:
        proc = await asyncio.create_subprocess_exec(*argv, **kw)
    except FileNotFoundError:
        return {
            "ok": False,
            "error": f"找不到命令：{argv[0]}。请确认已安装并在 PATH 中。",
            "argv": argv,
        }
    job["pid"] = proc.pid
    job["proc"] = proc
    async with _lock:
        _jobs[jid] = job

    async def _wait() -> None:
        try:
            code = await _pump(proc, log_path)
            job["exit_code"] = code
            job["status"] = "ok" if code == 0 else "failed"
        except Exception:
            logger.exception("bg job %s crashed", jid)
            job["status"] = "failed"
            job["exit_code"] = -1
        finally:
            job["ended_at"] = time.time()
            job["proc"] = None
            meta = _jobs_dir(eva) / f"{jid}.json"
            try:
                meta.write_text(
                    json.dumps(_dump_job(job), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError:
                pass

    asyncio.create_task(_wait(), name=f"terminal-{jid}")
    return {
        "ok": True,
        "background": True,
        "id": jid,
        "pid": proc.pid,
        "argv": argv,
        "cwd": str(work),
        "log_path": str(log_path),
        "hint": "对话已返回，不占用等待 token。用 action=poll job_id=该 id 查看进度。",
    }


def should_autostart_bg(command: str, action: str) -> bool:
    if (action or "run").strip().lower() != "run":
        return False
    return bool(_AUTO_BG.search(command or ""))


async def poll(job_id: str, *, tail: int = 80) -> dict[str, Any]:
    jid = (job_id or "").strip()
    job = _jobs.get(jid)
    eva, _ = _roots()
    if not job:
        meta = _jobs_dir(eva) / f"{jid}.json"
        if meta.is_file():
            try:
                job = json.loads(meta.read_text(encoding="utf-8"))
            except Exception:
                job = None
    if not job:
        return {"ok": False, "error": f"没有这个任务：{jid}"}
    log_path = Path(str(job.get("log_path") or _jobs_dir(eva) / f"{jid}.log"))
    text = ""
    if log_path.is_file():
        raw = log_path.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines()
        n = max(10, min(int(tail or 80), 400))
        text = "\n".join(lines[-n:])
    out = _dump_job(job)
    out["ok"] = True
    out["tail"] = _clip(text, 8000)
    return out


def _kill_pid(pid: int) -> None:
    if pid <= 0:
        raise ValueError("pid 无效")
    if os.name == "nt":
        import subprocess

        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
        return
    os.kill(pid, 15)


async def kill(job_id: str) -> dict[str, Any]:
    jid = (job_id or "").strip()
    job = _jobs.get(jid)
    eva, _ = _roots()
    if not job:
        meta = _jobs_dir(eva) / f"{jid}.json"
        if meta.is_file():
            try:
                job = json.loads(meta.read_text(encoding="utf-8"))
            except Exception:
                job = None
    if not job:
        return {"ok": False, "error": f"没有这个任务：{jid}"}
    proc = job.get("proc") if jid in _jobs else None
    try:
        if proc is not None:
            proc.kill()
        else:
            pid = int(job.get("pid") or 0)
            if not pid:
                return {"ok": False, "error": "任务已结束", **_dump_job(job)}
            _kill_pid(pid)
    except Exception as exc:
        return {"ok": False, "error": str(exc), **_dump_job(job)}
    job["status"] = "killed"
    job["ended_at"] = time.time()
    live = _jobs.get(jid)
    if live is not None:
        live["status"] = "killed"
        live["ended_at"] = job["ended_at"]
        live["proc"] = None
    try:
        meta = _jobs_dir(eva) / f"{jid}.json"
        meta.write_text(
            json.dumps(_dump_job(job), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
    return {"ok": True, **_dump_job(job)}


def pwd() -> dict[str, Any]:
    eva, ws = _roots()
    py = _venv_python(eva)
    return {
        "ok": True,
        "eva": str(eva),
        "workspace": str(ws),
        "venv_python": str(py) if py else None,
        "hint": "默认 cwd=workspace；装库用 python -m pip（会改写到 Eva .venv）。长任务用 action=bg。",
    }
