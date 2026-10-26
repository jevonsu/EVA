"""User-level Windows auto-start (Startup folder shortcut)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SHORTCUT_NAME = "Eva.lnk"
CREATE_NO_WINDOW = 0x08000000


def startup_dir() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def shortcut_path() -> Path:
    return startup_dir() / SHORTCUT_NAME


def is_enabled() -> bool:
    return shortcut_path().is_file()


def _project_root() -> Path:
    from app.config import PROJECT_ROOT

    return Path(PROJECT_ROOT)


def launch_command() -> tuple[str, str, str]:
    """Return (target_exe, arguments, working_directory)."""
    cwd = str(_project_root())
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve()), "--gui --autostart", cwd
    run_py = _project_root() / "run.py"
    venv_w = _project_root() / ".venv" / "Scripts" / "pythonw.exe"
    venv = _project_root() / ".venv" / "Scripts" / "python.exe"
    if venv_w.is_file():
        target = str(venv_w)
    elif venv.is_file():
        target = str(venv)
    else:
        target = sys.executable
        w = Path(sys.executable).with_name("pythonw.exe")
        if w.is_file():
            target = str(w)
    return target, f'"{run_py}" --gui --autostart', cwd


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def enable() -> Path:
    if sys.platform != "win32":
        raise RuntimeError("开机启动仅支持 Windows")
    dest = shortcut_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    target, args, cwd = launch_command()
    ico = _project_root() / "app" / "static" / "logo.ico"
    lines = [
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({_ps_quote(str(dest))})",
        f"$s.TargetPath={_ps_quote(target)}",
        f"$s.Arguments={_ps_quote(args)}",
        f"$s.WorkingDirectory={_ps_quote(cwd)}",
        "$s.WindowStyle=7",
        "$s.Description='Eva'",
    ]
    if ico.is_file():
        lines.append(f"$s.IconLocation={_ps_quote(str(ico) + ',0')}")
    lines.append("$s.Save()")
    script = ";".join(lines)
    kwargs: dict = {
        "args": [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        "check": False,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    proc = subprocess.run(**kwargs)
    if proc.returncode != 0 or not dest.is_file():
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise RuntimeError(err[:240])
    return dest


def disable() -> None:
    path = shortcut_path()
    if path.is_file():
        path.unlink()
