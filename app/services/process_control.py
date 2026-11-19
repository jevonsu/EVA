"""Model-initiated process termination with "inform first, then confirm".

Flow (enforced in code, not just in the prompt):
  1. query(pid | name | port)  → full notice per process (what it is, what
     killing it breaks). For an exact single pid a one-shot confirm_token is
     issued, bound to pid + create_time + cmdline fingerprint + session +
     the turn it was issued in. Valid 5 minutes, usable once.
  2. kill(pid, confirm_token, scope) → only in a LATER turn whose user words
     clearly agree (同意/可以/确认…, no negation). Identity re-checked; if the
     tree grew since the notice, refused (re-inform). terminate → wait → kill.

EVA's own automatic cleanup (one-shot run timeout / chat stop / bg jobs) does
not go through here — that stays automatic by design.
Hard-deny: OS-critical processes, EVA itself + its ancestors, Grok Bot client.
Every attempt is appended to data/process_kill_audit.jsonl (secrets masked).
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.services.process_control")

TOKEN_TTL = 300.0
CREATE_NO_WINDOW = 0x08000000
_tokens: dict[str, dict[str, Any]] = {}
_tok_lock = threading.RLock()
_tok_loaded = False


def _tokens_path() -> Path:
    from app.config import PROJECT_ROOT

    d = Path(PROJECT_ROOT).resolve() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "process_kill_tokens.json"


def _ensure_tokens_loaded() -> None:
    """Load unexpired tokens persisted by a previous EVA run (restart within TTL).
    Identity (pid + create_time + cmdline fingerprint) is still re-checked at kill time."""
    global _tok_loaded
    with _tok_lock:
        if _tok_loaded:
            return
        _tok_loaded = True
        try:
            path = _tokens_path()
            if not path.exists():
                return
            raw = json.loads(path.read_text(encoding="utf-8") or "{}")
            now = time.time()
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if isinstance(v, dict) and float(v.get("expires") or 0) > now and k not in _tokens:
                        _tokens[k] = v
        except Exception:
            logger.exception("load kill tokens failed")


def _save_tokens() -> None:
    with _tok_lock:
        try:
            now = time.time()
            live = {k: v for k, v in _tokens.items() if float(v.get("expires") or 0) > now}
            path = _tokens_path()
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(live, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except Exception:
            logger.exception("save kill tokens failed")


def _pop_token(key: str) -> None:
    with _tok_lock:
        if _tokens.pop((key or "").strip(), None) is not None:
            _save_tokens()

# ---------------------------------------------------------------- deny lists
_WIN_CRITICAL = {
    "system", "system idle process", "idle", "registry", "smss", "csrss", "wininit",
    "winlogon", "services", "lsass", "lsaiso", "svchost", "dwm", "fontdrvhost",
    "msmpeng", "nissrv", "securityhealthservice", "memory compression", "secure system",
    "wudfhost", "sgrmbroker", "mpdefendercoreservice",
}
_POSIX_CRITICAL = {
    "init", "systemd", "sshd", "dockerd", "containerd", "kthreadd", "launchd",
    "dbus-daemon", "journald", "systemd-journald", "systemd-logind", "udevd", "systemd-udevd",
    "tini", "docker-init", "runc",
}
_CRITICAL_PREFIX = ("containerd-shim", "systemd-")
_GROK_CLIENT = ("grok bot",)
_WARN = {
    "explorer": "Windows 桌面外壳：任务栏、开始菜单、文件夹窗口会消失；可在任务管理器「运行新任务」输入 explorer.exe 恢复。",
    "taskmgr": "任务管理器窗口会关闭。",
    "spoolsv": "打印后台服务：正在进行的打印任务会中断。",
    "audiodg": "Windows 音频引擎：声音会暂时中断。",
    "ctfmon": "输入法框架：输入法可能暂时无法切换/输入。",
    "sihost": "Shell 基础设施：通知、操作中心等可能异常。",
    "runtimebroker": "系统权限代理：部分应用权限功能可能异常（通常会自动重启）。",
    "searchhost": "Windows 搜索界面（会自动重启）。",
    "startmenuexperiencehost": "开始菜单（会自动重启）。",
    "shellexperiencehost": "系统托盘/通知等界面（会自动重启）。",
    "textinputhost": "触摸键盘/输入面板。",
}
_KNOWN = {
    "python": "Python 解释器（运行 Python 脚本/服务）",
    "pythonw": "Python 解释器（无窗口，常用于后台/GUI 程序，EVA 启动器也用它）",
    "node": "Node.js 运行时（运行 JS 脚本/前端开发服务器/后端服务）",
    "java": "Java 虚拟机",
    "javaw": "Java 虚拟机（无窗口）",
    "chrome": "Google Chrome 浏览器",
    "msedge": "Microsoft Edge 浏览器",
    "firefox": "Firefox 浏览器",
    "code": "Visual Studio Code 编辑器",
    "cmd": "Windows 命令提示符",
    "powershell": "Windows PowerShell",
    "pwsh": "PowerShell 7",
    "conhost": "控制台窗口宿主（为命令行程序提供窗口）",
    "bash": "Bash shell",
    "sh": "POSIX shell",
    "nginx": "Nginx Web 服务器/反向代理",
    "docker": "Docker 客户端",
    "wechat": "微信",
    "weixin": "微信",
    "qq": "QQ",
    "dingtalk": "钉钉",
    "wxwork": "企业微信",
    "notepad": "记事本",
}
_CMD_HINTS = (
    (re.compile(r"-m\s+http\.server\b"), "Python 内置 HTTP 文件服务（把目录作为网页共享）"),
    (re.compile(r"\buvicorn\b|\bgunicorn\b|\bhypercorn\b"), "Python Web 服务（ASGI/WSGI）"),
    (re.compile(r"\bflask\b"), "Flask Web 服务"),
    (re.compile(r"\bmanage\.py\s+runserver\b"), "Django 开发服务器"),
    (re.compile(r"\bvite\b|\bnext\s+dev\b|\bwebpack\b|npm-cli\.js.*\b(?:dev|start|serve)\b"), "前端开发服务器"),
    (re.compile(r"\bstreamlit\b"), "Streamlit 应用"),
    (re.compile(r"\bjupyter\b"), "Jupyter 笔记本服务"),
    (re.compile(r"run\.py\b.*--gui|run\.py\b.*--cli"), "EVA 启动器/服务"),
    (re.compile(r"\bpip\b.*\binstall\b"), "正在安装 Python 包"),
    (re.compile(r"\bgit\b"), "Git 操作"),
)
_SECRET_ARG = re.compile(
    r"(?i)((?:--?|/)(?:password|passwd|pwd|token|api[-_]?key|secret|key|auth|access[-_]?key)[=\s:]+)(\"[^\"]*\"|'[^']*'|\S+)"
)
_SECRET_KV = re.compile(r"(?i)\b([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD)[A-Z0-9_]*=)(\S+)")
_SECRET_LONG = re.compile(r"\b(?:sk|xai|ghp|gho|github_pat|nc_pat)[-_][A-Za-z0-9_\-]{12,}\b")

CONSENT = re.compile(
    r"同意|可以|确认|杀吧|杀掉吧|杀了吧|结束吧|关掉吧|干掉|没问题|就这样|好的|好吧|行吧|是的|对的|"
    r"\byes\b|\bok\b|\bokay\b|\bconfirm\b|\bgo ahead\b",
    re.I,
)
# 「不」只在构成否定词时才算否定（「不错」「没问题，不客气」不算）；
# 「别/勿/否」同理只认常见否定搭配，避免误伤「同意结束」之类的确认文字。
NEGATION = re.compile(
    r"不要|不用|不同意|不行|不可以|不能|不必|不需要|不想|不准|不许|不杀|不结束|不关|不停|不好|"
    r"先不|还是不|暂时不|不了|别|勿|否决|拒绝|取消|算了|等等|先等|暂停|停一下|"
    r"\bno\b|\bnot\b|\bdon'?t\b|\bcancel\b|\bstop\b",
    re.I,
)


def _psutil():
    import psutil  # type: ignore

    return psutil


def mask_secrets(text: str) -> str:
    s = _SECRET_ARG.sub(lambda m: m.group(1) + "***", text or "")
    s = _SECRET_KV.sub(lambda m: m.group(1) + "***", s)
    return _SECRET_LONG.sub("***", s)


def user_consents(message: str | None) -> bool:
    msg = (message or "").strip()
    if not msg:
        return False
    if NEGATION.search(msg):
        return False
    return bool(CONSENT.search(msg))


def _base(name: str) -> str:
    n = (name or "").strip().lower()
    return n[:-4] if n.endswith(".exe") else n


# ------------------------------------------------------------ win file info
def _win_file_info(path: str) -> dict[str, str]:
    if os.name != "nt" or not path:
        return {}
    try:
        import ctypes
        from ctypes import wintypes

        ver = ctypes.WinDLL("version")
        size = ver.GetFileVersionInfoSizeW(path, None)
        if not size:
            return {}
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(path, 0, size, buf):
            return {}
        ptr = ctypes.c_void_p()
        ln = wintypes.UINT()
        langs = []
        if ver.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(ln)) and ln.value:
            arr = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint16 * (ln.value // 2))).contents
            langs = [(arr[i], arr[i + 1]) for i in range(0, len(arr) - 1, 2)]
        langs += [(0x0409, 0x04B0), (0x0804, 0x04B0), (0x0409, 0x04E4)]
        out: dict[str, str] = {}
        for key in ("FileDescription", "CompanyName", "ProductName"):
            for lang, cp in langs:
                q = f"\\StringFileInfo\\{lang:04x}{cp:04x}\\{key}"
                if ver.VerQueryValueW(buf, q, ctypes.byref(ptr), ctypes.byref(ln)) and ln.value:
                    val = ctypes.wstring_at(ptr.value, ln.value).rstrip("\x00").strip()
                    if val:
                        out[key] = val
                        break
        return out
    except Exception:
        return {}


# ------------------------------------------------------------- EVA origin
def _eva_origin(pid: int) -> dict[str, Any] | None:
    try:
        from app.services.service_manager import service_for_pid

        r = service_for_pid(pid)
        if r and r.get("_relation") == "root":
            return {"kind": "service", "id": r.get("id"), "name": r.get("name"),
                    "label": f"EVA 登记的受保护服务「{r.get('name')}」（id={r.get('id')}）"}
        if r:
            return {"kind": "service_child", "id": r.get("id"), "name": r.get("name"),
                    "label": f"EVA 登记服务「{r.get('name')}」（id={r.get('id')}）的子进程"}
    except Exception:
        pass
    try:
        from app.services import terminal_exec as te

        if pid in te._active_runs:
            return {"kind": "run", "label": "EVA 正在执行的一次性命令（run）"}
        for jid, job in te._jobs.items():
            if int(job.get("pid") or 0) == pid and job.get("status") == "running":
                return {"kind": "bg", "id": jid, "label": f"EVA 后台任务 bg（job_id={jid}）"}
    except Exception:
        pass
    return None


def _protected_self() -> dict[int, str]:
    """EVA's own process and every ancestor (launcher, pythonw, EVA.exe, shell)."""
    out = {os.getpid(): "EVA 自身进程"}
    try:
        for p in _psutil().Process(os.getpid()).parents():
            try:
                if _base(p.name()) in _WARN:  # desktop shell (explorer) does not own EVA's lifetime
                    continue
            except Exception:
                pass
            out[p.pid] = "EVA 的上级进程（启动器/宿主）"
    except Exception:
        pass
    return out


def hard_deny_reason(info: dict[str, Any]) -> str | None:
    pid = int(info.get("pid") or 0)
    name = _base(info.get("name") or "")
    exe = (info.get("exe") or "").lower()
    if pid in (0, 4) or (os.name != "nt" and pid == 1):
        return "系统核心进程（PID 0/4/1），结束会导致系统崩溃或容器退出。"
    selfmap = _protected_self()
    if pid in selfmap:
        return f"{selfmap[pid]}，结束会让 EVA 自己停止。请用 EVA 启动器关闭。"
    if any(g in name for g in _GROK_CLIENT) or "\\programs\\grok bot\\" in exe:
        return "Grok Bot 桌面客户端，不允许由 EVA 结束。"
    if os.name == "nt":
        if name in _WIN_CRITICAL:
            return f"Windows 关键系统进程（{info.get('name')}），结束会蓝屏、注销或失去安全防护。"
    else:
        if name in _POSIX_CRITICAL or name.startswith(_CRITICAL_PREFIX):
            return f"系统关键进程（{info.get('name')}），结束会影响整个系统/容器。"
        if int(info.get("ppid") or 0) == 2:
            return "内核线程，不能结束。"
    return None


# ------------------------------------------------------------ describe
def _fmt_time(ts: float | None) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def describe(pid: int, *, cpu_interval: float | None = 0.3) -> dict[str, Any]:
    """Full notice for one pid (never raises; AccessDenied fields → None)."""
    ps = _psutil()
    from app.services.proc_tree import cmdline_fingerprint, listening_ports

    try:
        p = ps.Process(int(pid))
    except ps.NoSuchProcess:
        return {"ok": False, "pid": pid, "error": f"没有 PID {pid} 这个进程（可能已退出）。"}
    except Exception as exc:
        return {"ok": False, "pid": pid, "error": str(exc)}

    def g(fn, default=None):
        try:
            return fn()
        except ps.AccessDenied:
            return default
        except Exception:
            return default

    with p.oneshot():
        name = g(p.name, "") or ""
        exe = g(p.exe, "") or ""
        cmd = g(p.cmdline, []) or []
        ppid = g(p.ppid, 0) or 0
        ct = g(p.create_time, None)
        user = g(p.username, None)
        mem = g(lambda: p.memory_info().rss, None)
        status = g(p.status, None)
    cpu = g(lambda: p.cpu_percent(interval=cpu_interval), None)
    kids = []
    try:
        for c in p.children(recursive=True):
            try:
                kids.append({"pid": c.pid, "name": c.name()})
            except Exception:
                kids.append({"pid": c.pid, "name": "?"})
    except Exception:
        pass
    parent = None
    try:
        if ppid:
            parent = {"pid": ppid, "name": ps.Process(ppid).name()}
    except Exception:
        parent = {"pid": ppid, "name": "(已退出)"}
    ports = listening_ports(pid)
    info: dict[str, Any] = {
        "ok": True,
        "pid": pid,
        "name": name,
        "exe": exe,
        "cmdline": mask_secrets(" ".join(cmd)),
        "parent": parent,
        "ppid": ppid,
        "started": _fmt_time(ct),
        "create_time": ct,
        "user": user,
        "status": status,
        "cpu_percent": cpu,
        "memory_mb": round(mem / 1048576, 1) if mem else None,
        "listening_ports": ports,
        "children": kids,
        "children_count": len(kids),
        "fp": cmdline_fingerprint(cmd),
    }
    if user is None or not cmd:
        info["access_note"] = "部分信息无权读取（可能属于其他用户或管理员），结束它很可能也会因权限不足失败。"
    origin = _eva_origin(pid)
    info["eva_origin"] = origin["label"] if origin else "否（不是 EVA 创建的）"
    info["_origin"] = origin
    info["purpose"] = _purpose(info)
    deny = hard_deny_reason(info)
    info["hard_denied"] = bool(deny)
    if deny:
        info["deny_reason"] = deny
    info["impact"] = _impact(info)
    return info


def _purpose(info: dict[str, Any]) -> str:
    bits: list[str] = []
    origin = info.get("_origin")
    if origin:
        bits.append(origin["label"] + "（来自 EVA 登记，确定）")
    meta = _win_file_info(info.get("exe") or "")
    if meta.get("FileDescription") or meta.get("CompanyName"):
        desc = meta.get("FileDescription") or meta.get("ProductName") or ""
        comp = meta.get("CompanyName") or ""
        bits.append(f"{desc}{('（' + comp + '）') if comp else ''}（来自程序文件信息）")
    base = _base(info.get("name") or "")
    if base in _KNOWN:
        bits.append(_KNOWN[base] + "（推断：按程序名）")
    cmd = info.get("cmdline") or ""
    for rx, label in _CMD_HINTS:
        if rx.search(cmd):
            bits.append(label + "（推断：按命令行）")
            break
    if info.get("listening_ports"):
        bits.append(f"它（含子进程）正在监听端口 {', '.join(map(str, info['listening_ports']))}（实测）")
    if not bits:
        bits.append("无法确定具体作用（推断不出），请按可执行路径和命令行判断")
    return "；".join(dict.fromkeys(bits))


def _impact(info: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if info.get("hard_denied"):
        return ["不允许结束：" + str(info.get("deny_reason"))]
    base = _base(info.get("name") or "")
    if base in _WARN:
        out.append("⚠ 重要进程：" + _WARN[base])
    exe = (info.get("exe") or "").lower()
    if os.name == "nt" and exe.startswith(("c:\\windows\\system32", "c:\\windows\\syswow64")) and base not in _WARN:
        out.append("⚠ 这是 Windows 系统目录下的组件，结束可能影响系统功能。")
    if info.get("listening_ports"):
        out.append(f"端口 {', '.join(map(str, info['listening_ports']))}（含子进程）上的服务会断开，正在连接它的客户端会掉线。")
    n = info.get("children_count") or 0
    kid_names = {_base(k.get("name") or "") for k in info.get("children") or []}
    if os.name == "nt" and n and base in ("python", "pythonw") and base in kid_names and "\\scripts\\" in exe:
        out.append("⚠ 这是 venv 的 python 启动器，真正运行脚本的是它的子进程 python：只结束该进程，脚本通常还会继续运行，建议选「连同子进程树」。")
    if n:
        out.append(f"它有 {n} 个子进程：选「只结束该进程」时子进程可能变成孤儿继续运行；选「连同子进程树」会一起结束这 {n} 个。")
    origin = info.get("_origin") or {}
    if origin.get("kind") == "service":
        out.append("这是 EVA 登记的受保护服务，结束后登记表会标记为已停止，不会自动重启。")
    elif origin.get("kind") == "service_child":
        out.append(f"它属于 EVA 登记服务「{origin.get('name')}」，结束后该服务大概率不再可用；要整体停止请结束服务主进程（连同子进程树）。")
    out.append("程序里未保存的数据可能丢失；正在进行的读写/下载会中断。")
    return out


def _public(info: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in info.items() if not k.startswith("_") and k not in ("fp",)}


# ------------------------------------------------------------- query
def _turn() -> tuple[str | None, str | None, str | None]:
    try:
        from app.tools.protection import get_turn_id, get_turn_session_id, get_turn_user_message

        return get_turn_id(), get_turn_session_id(), get_turn_user_message()
    except Exception:
        return None, None, None


def _issue_token(info: dict[str, Any]) -> str:
    turn_id, sid, _ = _turn()
    tok = secrets.token_urlsafe(9)
    _ensure_tokens_loaded()
    with _tok_lock:
        now = time.time()
        for k in [k for k, v in _tokens.items() if v["expires"] < now]:
            _tokens.pop(k, None)
        _tokens[tok] = {
            "pid": info["pid"],
            "create_time": info.get("create_time"),
            "fp": info.get("fp"),
            "name": info.get("name"),
            "session_id": sid,
            "turn_id": turn_id,
            "children": sorted(c["pid"] for c in info.get("children") or []),
            "issued": now,
            "expires": now + TOKEN_TTL,
        }
        _save_tokens()
    return tok


def _find_pids(name: str = "", port: int | None = None) -> list[int]:
    ps = _psutil()
    pids: set[int] = set()
    if port:
        try:
            for c in ps.net_connections(kind="inet"):
                if c.laddr and int(c.laddr.port) == int(port) and c.pid and (c.status == "LISTEN" or not c.raddr):
                    pids.add(int(c.pid))
        except Exception:
            # some OSes need privileges for the global table; fall back per process
            for p in ps.process_iter(["pid"]):
                try:
                    fn = getattr(p, "net_connections", None) or p.connections
                    if any(c.laddr and int(c.laddr.port) == int(port) for c in fn(kind="inet")):
                        pids.add(p.pid)
                except Exception:
                    continue
    if name:
        key = _base(name)
        for p in ps.process_iter(["pid", "name"]):
            try:
                if _base(p.info.get("name") or "") == key or key in _base(p.info.get("name") or ""):
                    pids.add(p.info["pid"])
            except Exception:
                continue
    return sorted(pids)


def query(pid: int | None = None, name: str = "", port: int | None = None) -> dict[str, Any]:
    if pid:
        info = describe(int(pid))
        if not info.get("ok"):
            return info
        out = {"ok": True, "process": _public(info)}
        if info.get("hard_denied"):
            out["can_kill"] = False
            out["tell_user"] = f"PID {pid} 不允许结束：{info['deny_reason']}"
            return out
        tok = _issue_token(info)
        out["can_kill"] = True
        out["confirm_token"] = tok
        out["token_expires_in_sec"] = int(TOKEN_TTL)
        out["form"] = confirm_form(info)
        out["tell_user"] = notice_text(info)
        out["next_step"] = (
            "把 tell_user 原样告诉用户（已附确认卡片），然后结束本轮等用户回答。"
            "不要在本轮调用 kill，也不要假设用户同意。用户在卡片上点「同意」或回复「同意/取消」后，"
            "系统会直接执行或取消并把结果告诉用户，你不需要也不要再次询问。"
            "只有用户在之后另行明确同意时，才调用 action=kill，带 pid、confirm_token、scope。"
        )
        return out
    if not name and not port:
        return {"ok": False, "error": "请提供 pid、name（进程名）或 port（端口）之一。"}
    pids = _find_pids(name=name, port=port)
    if not pids:
        return {"ok": True, "matches": [], "tell_user": "没有找到匹配的进程。"}
    rows = []
    for p in pids[:30]:
        d = describe(p, cpu_interval=None)
        if d.get("ok"):
            rows.append({k: d.get(k) for k in (
                "pid", "name", "exe", "cmdline", "started", "user", "memory_mb",
                "listening_ports", "children_count", "eva_origin", "purpose", "hard_denied", "deny_reason")})
    return {
        "ok": True,
        "matches": rows,
        "count": len(pids),
        "next_step": (
            "列出全部匹配给用户，请用户指定要结束的那一个 PID；"
            "然后用 action=query pid=<该PID> 生成告知和确认。不支持按名称批量结束。"
        ),
    }


def notice_text(info: dict[str, Any]) -> str:
    kids = info.get("children") or []
    kid_s = "、".join(f"{c['pid']}({c['name']})" for c in kids[:20]) + ("…" if len(kids) > 20 else "")
    lines = [
        f"准备结束进程 PID {info['pid']}「{info.get('name')}」，请确认：",
        f"- 作用：{info.get('purpose')}",
        f"- 程序路径：{info.get('exe') or '（无权读取）'}",
        f"- 命令行：{info.get('cmdline') or '（无权读取）'}",
        f"- 父进程：{(info.get('parent') or {}).get('name', '')}（PID {info.get('ppid')}）",
        f"- 启动时间：{info.get('started')}　用户：{info.get('user') or '（无权读取）'}",
        f"- CPU：{info.get('cpu_percent')}%　内存：{info.get('memory_mb')} MB",
        f"- 监听端口（含子进程）：{', '.join(map(str, info.get('listening_ports') or [])) or '无'}",
        f"- 子进程：{len(kids)} 个" + (f"（{kid_s}）" if kids else ""),
        f"- 是否 EVA 创建：{info.get('eva_origin')}",
        "- 结束后的影响：",
    ]
    lines += [f"  · {x}" for x in info.get("impact") or []]
    if info.get("access_note"):
        lines.append("- 注意：" + info["access_note"])
    lines.append("两种方式：只结束该进程 / 连同子进程树一起结束。先温和结束，几秒不退再强制结束。")
    lines.append("同意请回复「同意」（可注明只结束该进程或连同子进程树），不同意请回复「取消」。5 分钟内有效。")
    return "\n".join(lines)


def confirm_form(info: dict[str, Any]) -> dict[str, Any]:
    pid = info["pid"]
    opts = [
        {"value": "process", "label": f"同意结束 PID {pid}（只结束该进程）"},
    ]
    if info.get("children_count"):
        opts.append({"value": "tree", "label": f"同意结束 PID {pid}（连同 {info['children_count']} 个子进程）"})
    opts.append({"value": "cancel", "label": "取消，不要结束"})
    return {
        "kind": "ask",
        "purpose": "kill_confirm",
        "kill_pid": pid,
        "title": f"结束进程 {info.get('name')}（PID {pid}）？",
        "prompt": notice_text(info)[:1200],
        "submit_label": "提交",
        "fields": [
            {"id": "choice", "type": "single", "label": "你的决定", "required": True, "options": opts},
        ],
        "cancellable": True,
    }


def tree_only_form(form: dict[str, Any], what: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """Terminal job / EVA service stop always ends the whole tree: one agree option."""
    pid = form.get("kill_pid")
    form["kill_ctx"] = dict(ctx, scope="tree")
    for f in form.get("fields") or []:
        if isinstance(f, dict) and f.get("id") == "choice":
            f["options"] = [
                {"value": "tree", "label": f"同意停止{what}（PID {pid}，连同子进程）"},
                {"value": "cancel", "label": "取消，不要停止"},
            ]
    return form


# ------------------------------------------------------------- kill
def audit_path() -> Path:
    from app.config import PROJECT_ROOT

    d = Path(PROJECT_ROOT).resolve() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "process_kill_audit.jsonl"


def _audit(entry: dict[str, Any]) -> None:
    try:
        path = audit_path()
        entry = dict(entry)
        entry["time"] = datetime.now().astimezone().isoformat(timespec="seconds")
        for k in ("cmdline", "consent"):
            if entry.get(k):
                entry[k] = mask_secrets(str(entry[k]))[:500]
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        logger.exception("kill audit write failed")


def _scope_from_message(msg: str, requested: str) -> str:
    m = msg or ""
    if "只结束该进程" in m or "只杀该进程" in m or "只结束这个" in m:
        return "process"
    if "子进程" in m or "进程树" in m or "整棵" in m:
        return "tree"
    return "tree" if requested == "tree" else "process"


def _wait_gone(procs: list, timeout: float) -> tuple[list, list]:
    """Like psutil.wait_procs but never reaps EVA's own children (asyncio owns those on POSIX)."""
    import psutil as ps

    deadline = time.time() + timeout
    while True:
        gone, alive = [], []
        for p in procs:
            try:
                (alive if p.is_running() and p.status() != ps.STATUS_ZOMBIE else gone).append(p)
            except ps.NoSuchProcess:
                gone.append(p)
            except Exception:
                alive.append(p)
        if not alive or time.time() >= deadline:
            return gone, alive
        time.sleep(0.2)


def _terminate(pids: list[int]) -> dict[str, Any]:
    """Gentle first (Windows: taskkill without /F → WM_CLOSE; POSIX: SIGTERM),
    wait up to 5s, then force. Reports which pids exited."""
    ps = _psutil()
    procs = []
    errors: dict[int, str] = {}
    for pid in pids:
        try:
            procs.append(ps.Process(pid))
        except ps.NoSuchProcess:
            pass
        except Exception as exc:
            errors[pid] = str(exc)
    soft_sent = 0
    for p in procs:
        try:
            if os.name == "nt":
                # no /F: asks GUI windows to close (WM_CLOSE). Console/windowless
                # processes refuse ("can only be terminated forcefully").
                r = subprocess.run(["taskkill", "/PID", str(p.pid)], capture_output=True,
                                   creationflags=CREATE_NO_WINDOW, timeout=10, check=False)
                if r.returncode == 0:
                    soft_sent += 1
            else:
                p.terminate()
                soft_sent += 1
        except ps.AccessDenied:
            errors[p.pid] = "权限不足（属于其他用户或需要管理员），EVA 不会提权"
        except Exception as exc:
            errors[p.pid] = str(exc)
    gone, alive = _wait_gone(procs, 5 if soft_sent else 0.5)
    forced = []
    for p in alive:
        try:
            p.kill()
            forced.append(p.pid)
        except ps.NoSuchProcess:
            pass
        except ps.AccessDenied:
            errors[p.pid] = "权限不足（属于其他用户或需要管理员），EVA 不会提权"
        except Exception as exc:
            errors[p.pid] = str(exc)
    gone2, alive2 = _wait_gone(alive, 3)
    still = [p.pid for p in alive2 if p.is_running() and p.status() != getattr(ps, "STATUS_ZOMBIE", "zombie")]
    exited = sorted(set(pids) - set(still))
    return {"exited": exited, "still_running": still, "forced": forced,
            "graceful": sorted(p.pid for p in gone), "errors": {str(k): v for k, v in errors.items()}}


def kill(pid: int, confirm_token: str, scope: str = "process") -> dict[str, Any]:
    turn_id, sid, msg = _turn()
    pid = int(pid or 0)
    base_audit = {"pid": pid, "session_id": sid, "consent": (msg or "")[:200], "scope_requested": scope}
    _ensure_tokens_loaded()
    with _tok_lock:
        tok = _tokens.get((confirm_token or "").strip())
    def refuse(err: str, *, drop: bool = False, **extra) -> dict[str, Any]:
        if drop:
            _pop_token(confirm_token)
        _audit({**base_audit, "result": "refused", "reason": err})
        return {"ok": False, "killed": False, "error": err, **extra}

    if not tok:
        return refuse("确认令牌无效、已用过或已过期。请重新 action=query 告知用户并等待同意。", need_requery=True)
    if tok["expires"] < time.time():
        return refuse("确认令牌已过期（5 分钟）。请重新查询并告知用户。", drop=True, need_requery=True)
    if tok["pid"] != pid:
        return refuse("令牌不是给这个 PID 的。每次确认只对应一个明确的 PID。", need_requery=True)
    if tok.get("session_id") and sid and tok["session_id"] != sid:
        return refuse("令牌属于另一个会话。", drop=True)
    if turn_id is None or tok.get("turn_id") == turn_id:
        return refuse(
            "同一轮里不能查完就结束：必须先把告知发给用户，等用户下一轮明确同意。",
            need_user_consent=True,
        )
    if msg is None or not user_consents(msg):
        return refuse(
            "用户本轮没有明确同意（或包含否定/取消）。不要假设同意；如用户拒绝，就不要结束。",
            need_user_consent=True,
        )
    eff_scope = _scope_from_message(msg, scope)
    return _execute_kill(pid, (confirm_token or "").strip(), tok, eff_scope, base_audit, refuse)


def _execute_kill(pid: int, key: str, tok: dict[str, Any], eff_scope: str,
                  base_audit: dict[str, Any], refuse) -> dict[str, Any]:
    """Shared by model kill() and the server-side form-consent path.
    Re-checks identity, hard-deny and tree growth, then terminates."""
    info = describe(pid)
    from app.services.proc_tree import matches

    if not info.get("ok") or not matches(pid, create_time=tok.get("create_time"), fp=tok.get("fp")):
        return refuse("进程已退出，或 PID 已被别的程序复用（身份核对未通过），未结束任何进程。", drop=True)
    if info.get("hard_denied"):
        return refuse(info["deny_reason"], drop=True)
    kids_now = sorted(c["pid"] for c in info.get("children") or [])
    if eff_scope == "tree" and set(kids_now) - set(tok.get("children") or []):
        return refuse(
            "子进程比告知时多了，影响范围变化，需要重新告知用户。",
            drop=True, need_requery=True, children_now=kids_now,
        )
    # consume token atomically (a double submit must not kill twice)
    with _tok_lock:
        claimed = _tokens.pop(key, None) is not None
        if claimed:
            _save_tokens()
    if not claimed:
        return refuse("这次确认已经执行过或已被取消，没有重复结束。", already_used=True)
    targets = [pid]
    if eff_scope == "tree":
        prot = _protected_self()
        targets = [k for k in kids_now if k not in prot] + [pid]
    result = _terminate(targets)
    origin = info.get("_origin") or {}
    if origin.get("kind") == "service" and pid in result["exited"]:
        try:
            from app.services.service_manager import mark_stopped

            mark_stopped(origin.get("id"), by="kill_process")
        except Exception:
            logger.exception("service registry update failed")
    ok = pid in result["exited"]
    _audit({**base_audit, "name": info.get("name"), "cmdline": info.get("cmdline"),
            "scope": eff_scope, "targets": targets, "result": "killed" if ok else "failed",
            "detail": result, "eva_origin": origin.get("kind")})
    out = {
        "ok": ok,
        "killed": ok,
        "pid": pid,
        "name": info.get("name"),
        "scope": eff_scope,
        "targets": targets,
        **result,
    }
    if not ok:
        out["error"] = "进程没有退出" + ("：" + "；".join(result["errors"].values()) if result["errors"] else "")
    if origin.get("kind") == "service":
        out["note"] = "这是 EVA 登记服务，登记表已标记为 stopped。"
    return out


def revoke_session_tokens(session_id: str | None, pid: int | None = None) -> int:
    """Revoke a session's tokens (all, or only those for one pid)."""
    _ensure_tokens_loaded()
    with _tok_lock:
        ks = [
            k for k, v in _tokens.items()
            if v.get("session_id") == session_id and (pid is None or int(v.get("pid") or 0) == int(pid))
        ]
        for k in ks:
            _tokens.pop(k, None)
        if ks:
            _save_tokens()
    return len(ks)


def find_session_token(session_id: str | None, pid: int) -> tuple[str | None, dict[str, Any] | None]:
    """Newest token (expired ones included, so callers can say "expired")
    issued in this session for this pid. Never returned to the user/model."""
    if not session_id:
        return None, None
    _ensure_tokens_loaded()
    with _tok_lock:
        rows = [
            (k, v) for k, v in _tokens.items()
            if v.get("session_id") == session_id and int(v.get("pid") or 0) == int(pid)
        ]
    if not rows:
        return None, None
    rows.sort(key=lambda kv: float(kv[1].get("issued") or kv[1].get("expires") or 0))
    return rows[-1]


def kill_by_form_consent(
    session_id: str | None,
    pid: int,
    choice: str,
    *,
    force_scope: str | None = None,
    consent_text: str = "",
) -> dict[str, Any]:
    """Server-side execution after the user submitted the kill_confirm card
    (or replied 同意 to it). The submission itself is the explicit consent, so
    the model never needs the token and cannot loop re-asking. All identity /
    expiry / session / hard-deny / tree-growth checks still apply."""
    pid = int(pid or 0)
    ch = (choice or "").strip().lower()
    base_audit = {
        "pid": pid, "session_id": session_id, "path": "form_consent",
        "consent": f"form:{ch} {consent_text or ''}"[:200], "scope_requested": force_scope or ch,
    }
    key, tok = find_session_token(session_id, pid)

    def refuse(err: str, *, drop: bool = False, **extra) -> dict[str, Any]:
        if drop and key:
            _pop_token(key)
        _audit({**base_audit, "result": "refused", "reason": err})
        return {"ok": False, "killed": False, "pid": pid, "error": err, **extra}

    if ch not in ("process", "tree"):
        return refuse("没有选择结束方式。", bad_choice=True)
    if not session_id or not pid:
        return refuse("缺少会话或 PID，未结束任何进程。")
    if not tok:
        return refuse(
            "这张确认卡已经失效（已执行过、已取消，或已超过 5 分钟），没有结束任何进程。",
            expired=True, need_requery=True,
        )
    if float(tok.get("expires") or 0) < time.time():
        return refuse("确认已超过 5 分钟有效期，没有结束任何进程。", drop=True, expired=True, need_requery=True)
    if tok.get("session_id") != session_id:
        return refuse("令牌属于另一个会话。", drop=True)
    eff_scope = force_scope if force_scope in ("process", "tree") else ch
    return _execute_kill(pid, key or "", tok, eff_scope, base_audit, refuse)
