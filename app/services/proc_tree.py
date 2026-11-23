"""Process-tree helpers: identity check + kill whole tree.

Used by terminal one-shot runs (class ①), CLI model calls and protected
services (class ②, only on explicit stop). Never kill a pid without first
checking it is still the same process (create_time + cmdline fingerprint),
because Windows/Linux recycle pids.
"""

from __future__ import annotations

import hashlib
import logging
import os
import signal
import subprocess
from typing import Any, Iterable

logger = logging.getLogger("app.services.proc_tree")

CREATE_NO_WINDOW = 0x08000000
# create_time from psutil is float seconds; allow small skew between
# our own time.time() bookkeeping and the kernel's process start stamp.
_CT_TOLERANCE = 2.0


def _psutil():
    try:
        import psutil  # type: ignore

        return psutil
    except Exception:  # pragma: no cover - psutil is in requirements
        return None


def cmdline_fingerprint(parts: Iterable[str] | None) -> str:
    blob = "\x00".join(str(p) for p in (parts or []))
    return hashlib.sha256(blob.encode("utf-8", "replace")).hexdigest()[:16]


def identity(pid: int) -> dict[str, Any] | None:
    """Return {pid, create_time, cmdline, fp} for a live pid, else None."""
    ps = _psutil()
    if ps is None or not pid or pid <= 0:
        return None
    try:
        p = ps.Process(int(pid))
        ct = float(p.create_time())
        try:
            cmd = p.cmdline()
        except Exception:
            cmd = []
        return {"pid": int(pid), "create_time": ct, "cmdline": cmd, "fp": cmdline_fingerprint(cmd)}
    except Exception:
        return None


def matches(
    pid: int,
    *,
    create_time: float | None = None,
    fp: str | None = None,
    started_near: float | None = None,
) -> bool:
    """True only if pid is alive AND is the process we started.

    create_time: exact psutil create_time recorded at start (preferred).
    fp: cmdline fingerprint recorded at start (optional extra check).
    started_near: fallback for legacy records (time.time() at spawn).
    """
    ident = identity(pid)
    if not ident:
        return False
    if create_time is not None:
        if abs(ident["create_time"] - float(create_time)) > _CT_TOLERANCE:
            return False
    elif started_near is not None:
        if abs(ident["create_time"] - float(started_near)) > 10.0:
            return False
    else:
        return False  # no way to prove identity → refuse
    if fp and ident["fp"] and ident["fp"] != fp and ident["cmdline"]:
        # fp is recorded after the child has exec'd; an unreadable cmdline
        # (access denied) yields an empty list and is not treated as mismatch.
        return False
    return True


def descendants(pid: int) -> list[tuple[int, float]]:
    """[(pid, create_time)] of all live descendants (best effort)."""
    ps = _psutil()
    if ps is None:
        return []
    out: list[tuple[int, float]] = []
    try:
        for c in ps.Process(int(pid)).children(recursive=True):
            try:
                out.append((c.pid, float(c.create_time())))
            except Exception:
                pass
    except Exception:
        pass
    return out


def orphans_of(pid: int, root_create_time: float | None) -> list[tuple[int, float]]:
    """Windows keeps the dead parent's pid in ppid (no re-parenting), so after
    a one-shot parent exits we can still find what it spawned. Only processes
    created after the root are taken (guards against pid reuse)."""
    ps = _psutil()
    if ps is None or not pid:
        return []
    found: list[tuple[int, float]] = []
    frontier = {int(pid)}
    floor = float(root_create_time or 0) - 0.5
    try:
        procs = []
        for p in ps.process_iter(["pid", "ppid", "create_time"]):
            info = p.info
            procs.append((info.get("pid"), info.get("ppid"), float(info.get("create_time") or 0)))
    except Exception:
        return []
    seen: set[int] = set()
    while frontier:
        nxt: set[int] = set()
        for cpid, ppid, ct in procs:
            if ppid in frontier and cpid not in seen and cpid != pid and ct >= floor:
                seen.add(cpid)
                found.append((cpid, ct))
                nxt.add(cpid)
        frontier = nxt
    return found


def _kill_list(pairs: Iterable[tuple[int, float]]) -> int:
    ps = _psutil()
    if ps is None:
        return 0
    n = 0
    procs = []
    for pid, ct in pairs:
        try:
            p = ps.Process(int(pid))
            if abs(float(p.create_time()) - float(ct)) > _CT_TOLERANCE:
                continue
            procs.append(p)
        except Exception:
            continue
    for p in procs:
        try:
            p.kill()
            n += 1
        except Exception:
            pass
    # Don't reap our own direct children on POSIX: asyncio's child watcher /
    # subprocess.Popen own their exit status ("exit status already read").
    me = os.getpid()
    waitable = []
    for p in procs:
        try:
            if os.name == "nt" or p.ppid() != me:
                waitable.append(p)
        except Exception:
            pass
    try:
        ps.wait_procs(waitable, timeout=3)
    except Exception:
        pass
    return n


def kill_tree(
    pid: int,
    *,
    create_time: float | None = None,
    extra: Iterable[tuple[int, float]] | None = None,
    posix_group: bool = True,
    force_group: bool = False,
) -> dict[str, Any]:
    """Kill pid and all its descendants (+ `extra` previously seen descendants).

    If create_time is given, the root is only killed when it still matches.
    Returns a small report dict. Never raises.
    """
    report: dict[str, Any] = {"pid": pid, "killed": 0, "root_verified": None}
    ps = _psutil()
    pairs: list[tuple[int, float]] = list(extra or [])
    root_ok = False
    if pid and pid > 0:
        ident = identity(pid)
        if ident is not None:
            root_ok = create_time is None or abs(ident["create_time"] - float(create_time)) <= _CT_TOLERANCE
            report["root_verified"] = root_ok
            if root_ok:
                pairs = descendants(pid) + pairs
                pairs.append((pid, ident["create_time"]))
    if ps is not None:
        # de-dup, children first (root appended last)
        seen: set[int] = set()
        uniq: list[tuple[int, float]] = []
        for p in pairs:
            if p[0] in seen:
                continue
            seen.add(p[0])
            uniq.append(p)
        report["killed"] = _kill_list(uniq)
    elif root_ok or (create_time is None and pid):
        # psutil missing: OS-level tree kill
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=15,
                )
            else:
                os.killpg(pid, signal.SIGKILL)
            report["killed"] = -1
        except Exception as exc:
            report["error"] = str(exc)
    # POSIX: the one-shot/bg runner starts each command in its own session,
    # so pgid == pid; sweep the group too (catches re-parented grandchildren).
    if posix_group and os.name != "nt" and pid and pid > 0 and (root_ok or create_time is None or force_group):
        try:
            os.killpg(pid, signal.SIGKILL)
        except Exception:
            pass
    return report


def listening_ports(pid: int) -> list[int]:
    """Ports in LISTEN state owned by pid or its descendants (best effort)."""
    ps = _psutil()
    if ps is None:
        return []
    ports: set[int] = set()
    pids = [pid] + [p for p, _ in descendants(pid)]
    for one in pids:
        try:
            proc = ps.Process(one)
            fn = getattr(proc, "net_connections", None) or proc.connections
            for c in fn(kind="inet"):
                if getattr(c, "status", "") == "LISTEN" and c.laddr:
                    ports.add(int(c.laddr.port))
        except Exception:
            continue
    return sorted(ports)


def port_in_use(port: int) -> bool:
    import socket

    for host in ("127.0.0.1", "0.0.0.0"):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.settimeout(0.5)
            if host == "127.0.0.1":
                if s.connect_ex((host, int(port))) == 0:
                    return True
            else:
                s.bind((host, int(port)))
        except OSError:
            return True
        finally:
            try:
                s.close()
            except Exception:
                pass
    return False


class WinJob:
    """Windows Job Object for class-① one-shot processes.

    Every process the command spawns inherits the job (even if intermediate
    parents exit — e.g. venv python.exe launchers), so terminate() kills the
    whole tree reliably. KILL_ON_JOB_CLOSE also ends them if EVA itself dies.
    Protected services are spawned by EVA directly with
    CREATE_BREAKAWAY_FROM_JOB and are never assigned to these jobs.
    No-op on non-Windows or on any API failure (callers keep psutil fallback).
    """

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001

    def __init__(self) -> None:
        self.handle = None
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._k32 = k32
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            k32.CloseHandle.argtypes = [wintypes.HANDLE]

            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [(n, ctypes.c_ulonglong) for n in (
                    "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

            class BASIC(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD),
                ]

            class EXTENDED(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", BASIC),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            h = k32.CreateJobObjectW(None, None)
            if not h:
                return
            info = EXTENDED()
            info.BasicLimitInformation.LimitFlags = self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k32.SetInformationJobObject(
                h, self.JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
            ):
                k32.CloseHandle(h)
                return
            self.handle = h
        except Exception:
            logger.debug("WinJob unavailable", exc_info=True)
            self.handle = None

    def assign(self, pid: int) -> bool:
        if not self.handle:
            return False
        try:
            hp = self._k32.OpenProcess(self.PROCESS_SET_QUOTA | self.PROCESS_TERMINATE, False, int(pid))
            if not hp:
                return False
            try:
                return bool(self._k32.AssignProcessToJobObject(self.handle, hp))
            finally:
                self._k32.CloseHandle(hp)
        except Exception:
            return False

    def terminate(self) -> None:
        if self.handle:
            try:
                self._k32.TerminateJobObject(self.handle, 1)
            except Exception:
                pass

    def close(self) -> None:
        h, self.handle = self.handle, None
        if h:
            try:
                self._k32.CloseHandle(h)  # KILL_ON_JOB_CLOSE: anything left dies
            except Exception:
                pass
