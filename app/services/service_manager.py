"""Protected long-running services (process class ②).

A service is started ONLY when the user explicitly asks for a resident
server (terminal action=service). It is fully detached from EVA:
  - output goes straight to a log file (no pipe EVA has to drain),
  - stdin = DEVNULL,
  - Windows: CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW |
    CREATE_BREAKAWAY_FROM_JOB (retry without breakaway → in_job=True),
  - POSIX: start_new_session (setsid).
So stopping a chat, a run timeout, deleting a session, or restarting EVA
never ends it. Only stop_service (explicit user request) kills it, after a
pid identity check (create_time + cmdline fingerprint) to avoid pid reuse.

Registry: data/services.json. On EVA start, reconcile() re-adopts running
services (status only — it never kills anything).

Docker note: inside a container EVA is PID 1; restarting EVA restarts the
container and every service in it is gone. Records then show "exited".
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.services.service_manager")

MAX_SERVICES = 5
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

_reg_lock = threading.RLock()

# Env vars a spawned service must not inherit (EVA secrets / config).
_SECRET_ENV = re.compile(
    r"(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD_|CREDENTIAL|COOKIE|SESSION|PRIVATE|AUTH)",
    re.I,
)
_SECRET_PREFIX = (
    "EVA_", "XAI_", "OPENAI_", "ANTHROPIC_", "DEEPSEEK_", "GEMINI_", "GOOGLE_API",
    "OPENROUTER_", "AZURE_OPENAI", "DASHSCOPE_", "MOONSHOT_", "ZHIPU_", "GH_", "GITHUB_",
    "HF_", "HUGGINGFACE", "AWS_", "DATABASE_URL", "WEBHOOK_", "SMTP_",
)
_ENV_KEEP = {"PATH", "PATHEXT", "SYSTEMROOT", "COMSPEC", "TEMP", "TMP", "USERPROFILE", "HOME",
             "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "WINDIR", "LANG", "LC_ALL", "TZ",
             "VIRTUAL_ENV", "PYTHONIOENCODING", "PYTHONUTF8", "USERNAME", "USER", "COMPUTERNAME",
             "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "PROGRAMFILES", "PROGRAMFILES(X86)",
             "COMMONPROGRAMFILES", "SYSTEMDRIVE", "HOMEDRIVE", "HOMEPATH", "OS", "SHELL", "TERM"}


def _data_dir() -> Path:
    from app.config import PROJECT_ROOT

    d = Path(PROJECT_ROOT).resolve() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def registry_path() -> Path:
    return _data_dir() / "services.json"


def _logs_dir() -> Path:
    d = _data_dir() / "services"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load() -> list[dict[str, Any]]:
    p = registry_path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("services.json unreadable; keeping a copy")
        try:
            shutil.copy2(p, p.with_suffix(".json.bad"))
        except Exception:
            pass
        return []
    rows = data.get("services") if isinstance(data, dict) else data
    return [r for r in (rows or []) if isinstance(r, dict)]


def _save(rows: list[dict[str, Any]]) -> None:
    p = registry_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"version": 1, "services": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, p)


def _now() -> float:
    return time.time()


def clean_env(base: dict[str, str] | None = None) -> dict[str, str]:
    src = dict(base if base is not None else os.environ)
    out: dict[str, str] = {}
    for k, v in src.items():
        ku = k.upper()
        if ku in _ENV_KEEP:
            out[k] = v
            continue
        if ku.startswith(_SECRET_PREFIX) or _SECRET_ENV.search(ku):
            continue
        out[k] = v
    out.setdefault("PYTHONUNBUFFERED", "1")
    out.setdefault("PYTHONIOENCODING", "utf-8")
    return out


_PORT_RX = (
    re.compile(r"(?:--port|-p|--listen)[=\s]+(\d{2,5})\b"),
    re.compile(r"http\.server\s+(\d{2,5})\b"),
    re.compile(r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0)?:(\d{2,5})\b"),
)


def guess_port(command: str) -> int | None:
    for rx in _PORT_RX:
        m = rx.search(command or "")
        if m:
            try:
                n = int(m.group(1))
                if 1 <= n <= 65535:
                    return n
            except ValueError:
                pass
    return None


def _status_of(rec: dict[str, Any]) -> str:
    """Live status by pid identity. Never kills anything."""
    from app.services.proc_tree import matches

    if rec.get("status") in ("stopped",):
        return "stopped"
    pid = int(rec.get("pid") or 0)
    if pid and matches(pid, create_time=rec.get("create_time"), fp=rec.get("fp") or None):
        return "running"
    if rec.get("status") == "running":
        return "exited"
    return str(rec.get("status") or "exited")


def protected_pids() -> set[int]:
    """pids (root + live descendants) of registered running services.
    Every cleanup path must skip these."""
    from app.services.proc_tree import descendants

    out: set[int] = set()
    with _reg_lock:
        rows = _load()
    for r in rows:
        if r.get("status") != "running":
            continue
        pid = int(r.get("pid") or 0)
        if not pid:
            continue
        out.add(pid)
        for d, _ in descendants(pid):
            out.add(d)
    return out


def reconcile() -> dict[str, Any]:
    """Called at EVA start: re-adopt services by pid identity. Status only."""
    changed = 0
    with _reg_lock:
        rows = _load()
        for r in rows:
            if r.get("status") != "running":
                continue
            st = _status_of(r)
            if st != "running":
                r["status"] = st
                r["ended_at"] = r.get("ended_at") or _now()
                changed += 1
            else:
                r["adopted_at"] = _now()
        if rows:
            _save(rows)
    running = [r.get("id") for r in rows if r.get("status") == "running"]
    if rows:
        logger.info("services reconcile: running=%s marked_exited=%d", running, changed)
    return {"running": running, "marked_exited": changed}


def _public(rec: dict[str, Any], *, tail: int = 0) -> dict[str, Any]:
    from app.services.proc_tree import listening_ports

    out = {k: rec.get(k) for k in (
        "id", "name", "command", "cwd", "root", "pid", "status", "ports", "log_path",
        "session_id", "created_by", "autostart", "in_job", "started_at", "ended_at",
        "last_exit", "create_time",
    )}
    if rec.get("status") == "running" and rec.get("pid"):
        out["listening"] = listening_ports(int(rec["pid"]))
    if tail:
        out["tail"] = read_log(rec, tail=tail)
    return out


def read_log(rec: dict[str, Any], *, tail: int = 80) -> str:
    p = Path(str(rec.get("log_path") or ""))
    if not p.is_file():
        return ""
    try:
        with p.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 64 * 1024))
            raw = fh.read().decode("utf-8", "replace")
    except OSError:
        return ""
    lines = raw.splitlines()
    n = max(5, min(int(tail or 80), 400))
    return "\n".join(lines[-n:])


def _find(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    k = (key or "").strip()
    if not k:
        return None
    for r in rows:
        if r.get("id") == k:
            return r
    hits = [r for r in rows if (r.get("name") or "") == k and r.get("status") == "running"]
    if len(hits) == 1:
        return hits[0]
    hits = [r for r in rows if (r.get("name") or "") == k]
    return hits[-1] if hits else None


def list_services(*, include_ended: bool = True, tail: int = 0, key: str = "") -> dict[str, Any]:
    with _reg_lock:
        rows = _load()
        dirty = False
        for r in rows:
            if r.get("status") == "running":
                st = _status_of(r)
                if st != "running":
                    r["status"] = st
                    r["ended_at"] = r.get("ended_at") or _now()
                    dirty = True
        if dirty:
            _save(rows)
    if key:
        r = _find(rows, key)
        if not r:
            return {"ok": False, "error": f"没有这个服务：{key}"}
        return {"ok": True, "service": _public(r, tail=tail or 80)}
    shown = [r for r in rows if include_ended or r.get("status") == "running"]
    return {
        "ok": True,
        "max_services": MAX_SERVICES,
        "running": sum(1 for r in rows if r.get("status") == "running"),
        "services": [_public(r, tail=tail) for r in shown[-30:]],
    }


def _win_resolve(argv: list[str], env: dict[str, str]) -> list[str]:
    head = argv[0]
    if os.path.isabs(head) or os.sep in head or "/" in head:
        return argv
    found = shutil.which(head, path=env.get("PATH") or env.get("Path"))
    return [found, *argv[1:]] if found else argv


def _spawn(argv: list[str], *, cwd: str, env: dict[str, str], log_fh) -> tuple[subprocess.Popen, bool]:
    kw: dict[str, Any] = {
        "cwd": cwd,
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": log_fh,
        "stderr": subprocess.STDOUT,
        "close_fds": True,
    }
    if os.name == "nt":
        base = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        try:
            return subprocess.Popen(argv, creationflags=base | CREATE_BREAKAWAY_FROM_JOB, **kw), False
        except OSError as exc:
            # ERROR_ACCESS_DENIED: EVA runs inside a Job that forbids breakaway
            if getattr(exc, "winerror", None) != 5:
                raise
            logger.warning("service breakaway denied (EVA in a Job); spawning inside job")
            return subprocess.Popen(argv, creationflags=base, **kw), True
    kw["start_new_session"] = True
    return subprocess.Popen(argv, **kw), False


def _reaper(proc: subprocess.Popen, sid: str) -> None:
    """Reap our own child (avoid zombies on POSIX) and record exit code.
    If EVA exits first the service keeps running; reconcile() handles it."""
    try:
        code = proc.wait()
    except Exception:
        return
    with _reg_lock:
        rows = _load()
        for r in rows:
            if r.get("id") == sid and r.get("status") == "running" and int(r.get("pid") or 0) == proc.pid:
                r["status"] = "exited"
                r["last_exit"] = code
                r["ended_at"] = _now()
                _save(rows)
                break


def start_service(
    command: str,
    *,
    name: str = "",
    cwd: str | None = None,
    root: str = "workspace",
    port: int | None = None,
    session_id: str | None = None,
    created_by: str = "model",
    autostart: str = "none",
) -> dict[str, Any]:
    from app.services.proc_tree import identity, port_in_use
    from app.services.terminal_exec import (
        _roots,
        build_argv,
        deny_reason,
        resolve_cwd,
    )

    denied = deny_reason(command)
    if denied:
        return {"ok": False, "error": denied}
    eva, _ws = _roots()
    work = resolve_cwd(cwd, root=root)
    with _reg_lock:
        rows = _load()
        for r in rows:
            if r.get("status") == "running" and _status_of(r) != "running":
                r["status"] = "exited"
                r["ended_at"] = r.get("ended_at") or _now()
        running = [r for r in rows if r.get("status") == "running"]
        if len(running) >= MAX_SERVICES:
            _save(rows)
            return {
                "ok": False,
                "error": f"受保护服务已达上限 {MAX_SERVICES} 个。请先让用户决定停掉哪个（action=stop_service）。",
                "running": [{"id": r.get("id"), "name": r.get("name"), "ports": r.get("ports")} for r in running],
            }
        nm = (name or "").strip()[:40]
        if nm and any((r.get("name") or "") == nm for r in running):
            return {"ok": False, "error": f"已有同名服务在运行：{nm}"}
        p = int(port) if port else guess_port(command)
        if p:
            if port_in_use(p):
                return {
                    "ok": False,
                    "error": f"端口 {p} 已被占用，未启动。请换端口，或先确认占用它的程序。",
                    "port": p,
                }
        argv, env = build_argv(command, eva)
        env = clean_env(env if env is not None else None)
        if os.name == "nt":
            py = eva / ".venv" / "Scripts"
            if py.is_dir():
                env["PATH"] = str(py) + os.pathsep + env.get("PATH", env.get("Path", ""))
            argv = _win_resolve(argv, env)
        sid = uuid.uuid4().hex[:8]
        log_path = _logs_dir() / f"{sid}.log"
        try:
            with log_path.open("ab") as fh:
                fh.write(f"# EVA service {sid} started {time.strftime('%Y-%m-%d %H:%M:%S')}\n# cmd: {command}\n".encode("utf-8"))
                fh.flush()
                proc, in_job = _spawn(argv, cwd=str(work), env=env, log_fh=fh)
        except FileNotFoundError:
            return {"ok": False, "error": f"找不到命令：{argv[0]}", "argv": argv}
        except OSError as exc:
            return {"ok": False, "error": f"启动失败：{exc}", "argv": argv}
        ident = identity(proc.pid) or {}
        # fp is captured after the exec settles (see below); right after fork
        # POSIX may still report the parent's cmdline.
        ident = {"create_time": ident.get("create_time"), "fp": None}
        rec = {
            "id": sid,
            "name": nm or (Path(argv[0]).stem if argv else sid),
            "command": command,
            "argv": argv,
            "cwd": str(work),
            "root": root,
            "pid": proc.pid,
            "create_time": ident.get("create_time"),
            "fp": ident.get("fp"),
            "ports": [p] if p else [],
            "log_path": str(log_path),
            "session_id": session_id,
            "created_by": created_by,
            "autostart": autostart if autostart in ("none", "eva", "boot") else "none",
            "status": "running",
            "in_job": bool(in_job),
            "started_at": _now(),
            "ended_at": None,
            "last_exit": None,
        }
        rows.append(rec)
        _save(rows)
    threading.Thread(target=_reaper, args=(proc, sid), name=f"svc-reap-{sid}", daemon=True).start()
    # Give it a moment: report immediate crashes instead of a false "ok".
    time.sleep(1.5)
    later = identity(proc.pid)
    if later and proc.poll() is None:
        with _reg_lock:
            rows = _load()
            for r in rows:
                if r.get("id") == sid:
                    r["fp"] = later.get("fp")
                    if r.get("create_time") is None:
                        r["create_time"] = later.get("create_time")
            _save(rows)
    out = list_services(key=sid, tail=30)
    svc = out.get("service") or {}
    if svc.get("status") != "running":
        return {"ok": False, "error": "服务启动后立即退出，请看日志。", "service": svc}
    return {
        "ok": True,
        "service": svc,
        "note": (
            "已作为受保护服务运行：停止对话、run 超时、删除会话、重启 EVA 都不会结束它。"
            "只有用户明确要求时才可 action=stop_service。"
            + ("（注意：EVA 运行在不允许脱离的 Job 中，关闭 EVA 的宿主可能连带结束此服务。）" if in_job else "")
        ),
    }


def start_service_sync_safe(*args, **kwargs) -> dict[str, Any]:
    try:
        return start_service(*args, **kwargs)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("start_service failed")
        return {"ok": False, "error": str(exc)}


def stop_service(key: str) -> dict[str, Any]:
    """Kill a registered service tree — only after pid identity check."""
    from app.services.proc_tree import kill_tree, matches

    with _reg_lock:
        rows = _load()
        rec = _find(rows, key)
        if not rec:
            return {"ok": False, "error": f"没有这个服务：{key}"}
        if rec.get("status") != "running":
            return {"ok": True, "already": rec.get("status"), "service": _public(rec)}
        pid = int(rec.get("pid") or 0)
        if not matches(pid, create_time=rec.get("create_time"), fp=rec.get("fp") or None):
            rec["status"] = "exited"
            rec["ended_at"] = _now()
            _save(rows)
            return {
                "ok": True,
                "already": "exited",
                "note": "进程已不在（或 pid 已被别的程序复用），未结束任何进程，只更新了状态。",
                "service": _public(rec),
            }
        report = kill_tree(pid, create_time=rec.get("create_time"))
        rec["status"] = "stopped"
        rec["ended_at"] = _now()
        _save(rows)
    return {"ok": True, "stopped": rec.get("id"), "report": report, "service": _public(rec)}


def mark_stopped(key: str | None, *, by: str = "") -> bool:
    """Registry bookkeeping after a confirmed kill (process_control)."""
    if not key:
        return False
    with _reg_lock:
        rows = _load()
        rec = _find(rows, key)
        if not rec:
            return False
        rec["status"] = "stopped"
        rec["ended_at"] = _now()
        if by:
            rec["stopped_by"] = by
        _save(rows)
    return True


def service_for_pid(pid: int) -> dict[str, Any] | None:
    """Registered running service whose root is pid, or that pid descends from."""
    from app.services.proc_tree import descendants

    with _reg_lock:
        rows = [r for r in _load() if r.get("status") == "running"]
    for r in rows:
        root = int(r.get("pid") or 0)
        if not root:
            continue
        if root == pid:
            return {**r, "_relation": "root"}
        if any(d == pid for d, _ in descendants(root)):
            return {**r, "_relation": "child"}
    return None
