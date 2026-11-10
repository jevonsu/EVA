"""Controlled local process runner for the terminal system skill.

Process classes (see also app/services/service_manager.py):
  ① one-shot `run`  — EVA-internal. Hard timeout; on timeout / chat stop /
     EVA shutdown the WHOLE process tree is killed. stdin=DEVNULL.
  ② `service`       — user-requested long-running server. Lives in
     service_manager, detached from EVA, never killed except explicit stop.
  ③ `bg` job        — finite background work (pip/npm/clone). Survives chat
     stop; `kill` kills its tree (after pid identity check).
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
    # 绕过变体：编码/缩写参数、间接执行、路径与扩展名变体
    re.compile(r"\b(?:powershell|pwsh)(?:\.exe)?[\"']?\s+(?:.*\s)?[-/]e(?:c|n\w*)?(?:\s|$)", re.I),
    re.compile(r"\b(?:invoke-command|icm)\b.*-scriptblock|\[scriptblock\]::create", re.I),
    re.compile(r"\b(?:certutil)\b.*-(?:decode|urlcache)", re.I),
    re.compile(r"\b(?:mshta|regsvr32|rundll32|wscript|cscript|bitsadmin)(?:\.exe)?\b", re.I),
    re.compile(r"\b(?:format|diskpart|bcdedit|shutdown|vssadmin|wbadmin|cipher)(?:\.exe|\.com)?\b.*(?:/w|delete|[a-z]:|/s|/r|/p|shadows)", re.I),
    re.compile(r"\breg(?:\.exe)?\s+(?:delete|add\s+hk(?:lm|ey_local_machine))", re.I),
    re.compile(r"\b(?:rm|rmdir|rd|del|erase|remove-item|ri)\b.*(?:-rf?|/s|-recurse).*(?:^|\s|[\"'])(?:[c-z]:[\\/]?(?:\s|[\"']|$)|%systemroot%|\$env:windir|/\s*$|~\s*$)", re.I),
    re.compile(r"\b(?:set-mppreference|add-mppreference)\b|\bnetsh\s+advfirewall\b", re.I),
    re.compile(r"\bpython[\d.]*(?:\.exe)?\s+-c\s+.*(?:base64|b64decode|exec\s*\(|os\.system|subprocess)", re.I),
    re.compile(r"\|\s*(?:iex|invoke-expression|sh|bash|cmd(?:\.exe)?|powershell|pwsh)\b", re.I),
    re.compile(r"\b(?:curl|wget|iwr|invoke-webrequest|irm|invoke-restmethod)\b.*\|", re.I),
    # POSIX shell 模式额外规则
    re.compile(r"\bmkfs(?:\.\w+)?\b|\bdd\b.*\bof=/dev/|>\s*/dev/(?:sd|nvme|hd|vd|mmcblk)", re.I),
    re.compile(r":\s*\(\s*\)\s*\{.*:\s*\|\s*:", re.I),
    re.compile(r"\b(?:reboot|halt|poweroff|init\s+[06])\b", re.I),
    re.compile(r"\bbase64\b.*(?:-d|--decode).*\|", re.I),
    re.compile(r"\beval\b|\bsource\s+/dev/|\b(?:sh|bash|zsh|dash)\s+-c\b|<\(\s*(?:curl|wget)", re.I),
    re.compile(r"\bchmod\s+(?:-R\s+)?[0-7]*777\s+/(?:\s|$)|\bchown\s+-R\b.*\s/(?:\s|$)", re.I),
    re.compile(r"\b(?:rm|rmdir)\b.*\s(?:/|/\*|~|\$HOME|/(?:etc|usr|bin|lib|boot|var|app)\b\S*)\s*(?:$|[;&|])", re.I),
    re.compile(r"\bsudo\b|\bnsenter\b|\bdocker\b.*\b(?:run|exec)\b", re.I),
)

# Killing processes from a shell bypasses the inform-and-confirm flow.
# Best effort: obfuscated variants (aliases built at runtime, scripts on disk
# that kill, other languages' APIs) cannot all be caught by regex.
_KILL_CMD = re.compile(
    r"\b(?:taskkill|tskill|pkill|killall|xkill|fuser\s+-k)(?:\.exe)?\b"
    r"|\bstop-process\b|\bspps\b|\.kill\(\)|\.terminate\(\)"
    r"|(?:^|[;&|(`]\s*|\bsudo\s+|\bxargs\s+)kill(?:\s|$)"
    r"|\bkill\s+-(?:\d+|[A-Z]+|s\s+\w+)\b"
    r"|\bwmic\b.*\bprocess\b.*\b(?:delete|terminate|call\s+terminate)\b"
    r"|\b(?:Get-Process|gps|ps)\b.*\|\s*(?:Stop-Process|spps|kill)\b"
    r"|\bGet-CimInstance\b.*Win32_Process.*\b(?:Terminate|Invoke-CimMethod)\b"
    r"|\bos\.kill\b|\bos\.killpg\b|\bpsutil\b.*\b(?:kill|terminate)\b|\bprocess\.kill\b"
    r"|\bsignal\.SIG(?:KILL|TERM)\b",
    re.I,
)

_AUTO_BG = re.compile(
    r"\b(pip|pip3|npm|pnpm|yarn)\b.*\b(install|ci|add)\b|\bgit\s+clone\b|\bnpm\s+i\b",
    re.I,
)

# Long-running / never-ending commands: refuse in `run` (would block the chat
# until timeout, then get killed). Suggest action=service instead.
_SERVICE_LIKE = re.compile(
    r"\buvicorn\s+[\w.]+:\w+|-m\s+uvicorn\b|\b(?:gunicorn|hypercorn|daphne|waitress-serve)\s+\S"
    r"|\bflask\s+run\b|\bdjango-admin\s+runserver\b|\bmanage\.py\s+runserver\b"
    r"|-m\s+http\.server\b|\bSimpleHTTPServer\b"
    r"|\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:dev|start|serve|preview)\b"
    r"|\bvite(?:\s*$|\s+(?:dev|serve|preview)\b|\s+--)|\bnext\s+(?:dev|start)\b|\bnuxt\s+dev\b"
    r"|\bwebpack-dev-server\b|\bng\s+serve\b|\bserve\s+-[sl]\b"
    r"|\bstreamlit\s+run\b|\bjupyter\s+(?:lab|notebook)\b|\bphp\s+-S\b|\bcaddy\s+run\b"
    r"|\bnode(?:\.exe)?\s+\S*(?:server|app)\.(?:c?js|mjs|ts)\b",
    re.I,
)
_WATCH_LIKE = re.compile(
    r"\btail\s+-[a-z]*f|\bGet-Content\b.*-Wait\b|\bwatch\s|--watch\b|\bping\s+-t\b"
    r"|\bnodemon\b|\bpause\b|\bRead-Host\b",
    re.I,
)


def service_like_reason(command: str) -> str | None:
    """Why `command` looks long-running (server / watcher), else None."""
    line = command or ""
    if _AUTO_BG.search(line):
        return None  # pip/npm install, git clone: finite
    if _SERVICE_LIKE.search(line):
        return "server"
    if _WATCH_LIKE.search(line):
        return "watch"
    return None


_jobs: dict[str, dict[str, Any]] = {}
_lock = asyncio.Lock()
# ① live one-shot runs: pid -> {"create_time", "descendants": set[(pid, ct)]}
_active_runs: dict[int, dict[str, Any]] = {}


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
    if _KILL_CMD.search(command or ""):
        return (
            "拒绝在终端里直接结束进程（taskkill/Stop-Process/kill/pkill 等）。"
            "请改用 process_control 工具：先 action=query 告知用户进程作用与影响，"
            "用户下一轮明确同意后再 action=kill。"
        )
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


POSIX_SHELL = os.name != "nt"


def _posix_shell() -> str:
    for c in ("/bin/bash", "/bin/sh"):
        if os.path.isfile(c):
            return c
    return "/bin/sh"


def build_argv(command: str, eva: Path) -> tuple[list[str], dict[str, str] | None]:
    """Windows：保持原逻辑（拆 argv 直接 exec）。
    Linux/Docker：交给 sh -c，支持 | && 重定向 变量；pip/python 通过 PATH 优先 Eva .venv。"""
    if not POSIX_SHELL:
        return rewrite_argv(split_command(command), eva), None
    line = (command or "").strip()
    if not line:
        raise ValueError("command 为空")
    env = dict(os.environ)
    py = _venv_python(eva)
    if py:
        env["PATH"] = str(py.parent) + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = str(py.parent.parent)
    env.setdefault("LANG", "C.UTF-8")
    return [_posix_shell(), "-c", line], env


def _clip(text: str, limit: int = MAX_CAPTURE) -> str:
    if len(text) <= limit:
        return text
    return text[: limit // 2] + "\n…(截断)…\n" + text[-(limit // 2) :]


def _dump_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job.get("id"),
        "kind": job.get("kind") or "bg",
        "create_time": job.get("create_time"),
        "fp": job.get("fp"),
        "status": job.get("status"),
        "command": job.get("command"),
        "cwd": job.get("cwd"),
        "pid": job.get("pid"),
        "exit_code": job.get("exit_code"),
        "started_at": job.get("started_at"),
        "ended_at": job.get("ended_at"),
        "log_path": job.get("log_path"),
    }


async def _pump_stream(proc: asyncio.subprocess.Process, log_path: Path) -> None:
    """Copy stdout to log until EOF (does not wait for process exit)."""
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


async def _pump(proc: asyncio.subprocess.Process, log_path: Path) -> int:
    await _pump_stream(proc, log_path)
    code = await proc.wait()
    return int(code if code is not None else -1)


def _spawn_kwargs(work: Path, env: dict[str, str] | None) -> dict[str, Any]:
    kw: dict[str, Any] = {
        "cwd": str(work),
        "stdin": asyncio.subprocess.DEVNULL,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.STDOUT,
    }
    if os.name == "nt":
        kw["creationflags"] = CREATE_NO_WINDOW
    else:
        kw["start_new_session"] = True
    if env is not None:
        kw["env"] = env
    return kw


async def _watch_descendants(pid: int, bag: set[tuple[int, float]]) -> None:
    """Remember every descendant we see, so we can still kill grandchildren
    after their parent exited (Windows has no process groups)."""
    from app.services.proc_tree import descendants

    n = 0
    while True:
        try:
            for pair in await asyncio.to_thread(descendants, pid):
                bag.add(pair)
        except Exception:
            pass
        n += 1
        await asyncio.sleep(0.25 if n < 20 else 1.0)


def _cleanup_run(pid: int, create_time: float | None, bag: set[tuple[int, float]]) -> dict[str, Any]:
    from app.services.proc_tree import kill_tree

    try:
        from app.services.service_manager import protected_pids

        prot = protected_pids()
    except Exception:
        prot = set()
    pairs = set(bag)
    if os.name == "nt":
        from app.services.proc_tree import orphans_of

        pairs.update(orphans_of(pid, create_time))
    extra = [p for p in pairs if p[0] not in prot]
    # force_group: POSIX one-shot runs own their session (pgid == pid); sweep it
    # even if the leader already exited (re-parented grandchildren).
    return kill_tree(pid, create_time=create_time, extra=extra, force_group=True)


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
    why = service_like_reason(command)
    if why:
        return {
            "ok": False,
            "error": (
                "这条命令看起来会一直运行（%s），不能用 action=run（会占住对话直到超时并被结束）。"
                % ("服务/端口进程" if why == "server" else "监视/等待输入")
            ),
            "hint": (
                "用户明确要常驻服务时改用 action=service（受保护，停止对话/重启 EVA 都不会结束）；"
                "有限时长的后台任务用 action=bg；只想看一眼输出请去掉 -f/--watch 等常驻参数。"
            ),
            "suggest_action": "service" if why == "server" else "bg",
        }
    eva, _ws = _roots()
    work = resolve_cwd(cwd, root=root)
    argv, env = build_argv(command, eva)
    timeout = SYNC_TIMEOUT_DEFAULT if timeout_sec is None else float(timeout_sec)
    timeout = max(5.0, min(timeout, SYNC_TIMEOUT_MAX))
    jid = uuid.uuid4().hex[:10]
    log_path = _jobs_dir(eva) / f"{jid}.log"
    kw = _spawn_kwargs(work, env)
    started = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(*argv, **kw)
    except FileNotFoundError:
        return {
            "ok": False,
            "error": f"找不到命令：{argv[0]}。请确认已安装并在 PATH 中。",
            "argv": argv,
        }
    from app.services.proc_tree import WinJob, identity

    job_obj = WinJob()  # Windows: whole-tree containment for this one-shot run
    in_job = job_obj.assign(proc.pid)
    ident = identity(proc.pid)
    ct = ident["create_time"] if ident else None
    bag: set[tuple[int, float]] = set()
    _active_runs[proc.pid] = {"create_time": ct, "descendants": bag, "command": command, "job": job_obj}
    pump = asyncio.create_task(_pump_stream(proc, log_path), name=f"terminal-pump-{jid}")
    watcher = asyncio.create_task(_watch_descendants(proc.pid, bag), name=f"terminal-watch-{jid}")
    status = "ok"
    code: int | None = None
    try:
        # Note: asyncio's proc.wait() also waits for the stdout pipe to close,
        # so a background grandchild holding the pipe would block it. Watch
        # returncode (set as soon as the direct child exits) instead.
        deadline = time.monotonic() + timeout
        while proc.returncode is None and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        if proc.returncode is None:
            status = "timeout"
        else:
            code = proc.returncode
            # Parent exited; a background grandchild may still hold the pipe.
            try:
                await asyncio.wait_for(asyncio.shield(pump), timeout=3.0)
            except asyncio.TimeoutError:
                status = "leftover"
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    finally:
        watcher.cancel()
        report: dict[str, Any] = {}
        alive_root = proc.returncode is None
        if in_job:
            # one-shot semantics: whatever the command left behind ends with it
            job_obj.terminate()
        if alive_root or status != "ok" or bag:
            # ① cleanup: kill the whole tree (root if alive + every descendant seen)
            report = await asyncio.to_thread(_cleanup_run, proc.pid, ct, bag) if status != "cancelled" else _cleanup_run(proc.pid, ct, bag)
        try:
            await asyncio.wait_for(asyncio.shield(pump), timeout=2.0)
        except BaseException:
            pump.cancel()
        _active_runs.pop(proc.pid, None)
        job_obj.close()
        if status == "cancelled":
            logger.info("terminal run %s cancelled; process tree cleaned %s", jid, report)
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    if status == "timeout":
        return {
            "ok": False,
            "error": f"超时 {int(timeout)}s，整个进程树已结束。长任务请用 action=bg；常驻服务请用 action=service。",
            "id": jid,
            "argv": argv,
            "cwd": str(work),
            "output": _clip(text),
            "log_path": str(log_path),
        }
    if code is None:
        code = proc.returncode if proc.returncode is not None else -1
    out = {
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
    if status == "leftover" or bag:
        out["note"] = "命令遗留的子进程已随本次 run 一并结束（run 是一次性执行）。需要常驻请用 action=service。"
    return out


def shutdown_cleanup() -> int:
    """EVA shutdown: kill class-① one-shot runs still alive. Never touches
    registered services (class ②)."""
    n = 0
    for pid, info in list(_active_runs.items()):
        try:
            job = info.get("job")
            if job is not None:
                job.terminate()
                job.close()
            _cleanup_run(pid, info.get("create_time"), set(info.get("descendants") or ()))
            n += 1
        except Exception:
            logger.exception("shutdown cleanup failed pid=%s", pid)
        _active_runs.pop(pid, None)
    return n


async def start_bg(
    command: str,
    *,
    cwd: str | None = None,
    root: str = "workspace",
) -> dict[str, Any]:
    denied = deny_reason(command)
    if denied:
        return {"ok": False, "error": denied}
    if service_like_reason(command) == "server":
        return {
            "ok": False,
            "error": "这是常驻服务类命令。action=bg 只用于会结束的后台任务（pip/npm install/clone 等）。",
            "hint": "用户明确要常驻服务时改用 action=service（受保护，不随对话/EVA 结束）。",
            "suggest_action": "service",
        }
    eva, _ws = _roots()
    work = resolve_cwd(cwd, root=root)
    argv, env = build_argv(command, eva)
    jid = uuid.uuid4().hex[:10]
    log_path = _jobs_dir(eva) / f"{jid}.log"
    job = {
        "kind": "bg",
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
    kw = _spawn_kwargs(work, env)
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
    try:
        from app.services.proc_tree import identity

        _ident = identity(proc.pid)
        if _ident:
            job["create_time"] = _ident["create_time"]
    except Exception:
        pass
    async with _lock:
        _jobs[jid] = job

    async def _wait() -> None:
        try:
            code = await _pump(proc, log_path)
            job["exit_code"] = code
            if job.get("status") != "killed":
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

    try:
        (_jobs_dir(eva) / f"{jid}.json").write_text(
            json.dumps(_dump_job(job), ensure_ascii=False, indent=2), encoding="utf-8"
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


def _kill_pid(pid: int, *, create_time: float | None = None, started_near: float | None = None, fp: str | None = None) -> dict[str, Any]:
    """Kill a pid tree only after proving it is still our process."""
    from app.services.proc_tree import kill_tree, matches

    if pid <= 0:
        raise ValueError("pid 无效")
    if not matches(pid, create_time=create_time, fp=fp, started_near=started_near):
        raise ValueError("进程已不存在，或 pid 已被系统复用为别的程序（身份核对未通过），未执行结束。")
    try:
        from app.services.service_manager import protected_pids

        if pid in protected_pids():
            raise ValueError("该进程属于受保护服务，请用 action=stop_service 并由用户明确确认。")
    except ImportError:
        pass
    return kill_tree(pid, create_time=None if create_time is None else create_time)


def _kill_tree(proc: Any) -> None:
    """Kill a live asyncio/Popen child and all its descendants."""
    from app.services.proc_tree import kill_tree

    try:
        kill_tree(int(proc.pid))
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


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
            _kill_tree(proc)
        else:
            pid = int(job.get("pid") or 0)
            if not pid or job.get("status") not in (None, "running"):
                return {"ok": False, "error": "任务已结束", **_dump_job(job)}
            _kill_pid(
                pid,
                create_time=job.get("create_time"),
                started_near=job.get("started_at"),
                fp=job.get("fp"),
            )
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


def mark_job_killed(job_id: str) -> None:
    """Bookkeeping after a confirmed kill done by process_control."""
    jid = (job_id or "").strip()
    eva, _ = _roots()
    job = _jobs.get(jid)
    if job is None:
        meta = _jobs_dir(eva) / f"{jid}.json"
        try:
            job = json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() else None
        except Exception:
            job = None
    if not job:
        return
    job["status"] = "killed"
    job["ended_at"] = time.time()
    try:
        (_jobs_dir(eva) / f"{jid}.json").write_text(
            json.dumps(_dump_job(job), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def pwd() -> dict[str, Any]:
    eva, ws = _roots()
    py = _venv_python(eva)
    return {
        "ok": True,
        "eva": str(eva),
        "workspace": str(ws),
        "venv_python": str(py) if py else None,
        "hint": "默认 cwd=workspace；装库用 python -m pip（会改写到 Eva .venv）。长任务用 action=bg；常驻服务用 action=service。",
    }
