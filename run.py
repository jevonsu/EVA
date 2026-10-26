"""Eva entrypoint: ``python run.py``.

Windows default is a control window (start / stop / port / logs).
Use ``--cli`` for the old blocking terminal. Frozen ``EVA.exe`` has no console.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _runtime_root() -> Path:
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


_ROOT = _runtime_root()
os.chdir(_ROOT)


def _venv_python() -> Path | None:
    if sys.platform == "win32":
        p = _ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        p = _ROOT / ".venv" / "bin" / "python"
    return p if p.is_file() else None


def _same_python(a: str | Path, b: str | Path) -> bool:
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(
            os.path.realpath(b)
        )
    except OSError:
        return False


def _pythonw_for(exe: Path) -> Path | None:
    if sys.platform != "win32":
        return None
    name = exe.name.lower()
    if name == "pythonw.exe":
        return exe
    if name in ("python.exe", "python3.exe"):
        w = exe.with_name("pythonw.exe")
        return w if w.is_file() else None
    return None


def _handoff_venv(argv: list[str], *, gui: bool) -> None:
    """Re-enter with .venv interpreter. GUI uses pythonw so no extra console."""
    if _is_frozen():
        return
    if os.environ.get("EVA_LAUNCHER") == "1":
        return
    vpy = _venv_python()
    target: Path | None = None
    if gui and sys.platform == "win32":
        if vpy is not None:
            target = _pythonw_for(vpy) or vpy
        else:
            target = _pythonw_for(Path(sys.executable))
        if target is None:
            return
        me = Path(sys.executable)
        try:
            me_dir = os.path.normcase(os.path.realpath(me.parent))
            tgt_dir = os.path.normcase(os.path.realpath(Path(target).parent))
        except OSError:
            me_dir = tgt_dir = ""
        # Already the intended GUI interpreter (double-click run.bat / pythonw).
        if me.name.lower() == "pythonw.exe" and (
            _same_python(me, target) or (me_dir and me_dir == tgt_dir)
        ):
            return
        if _same_python(me, target):
            return
        env = os.environ.copy()
        env["EVA_LAUNCHER"] = "1"
        kwargs: dict = {
            "env": env,
            "cwd": str(_ROOT),
            "close_fds": True,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            # Break away from the Explorer / py.exe console so the GUI survives
            # after the parent console window closes.
            flags = 0
            flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
            flags |= int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
            kwargs["creationflags"] = flags
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            kwargs["startupinfo"] = si
        subprocess.Popen([str(target), str(Path(__file__).resolve()), *argv], **kwargs)
        raise SystemExit(0)

    if vpy is None or _same_python(sys.executable, vpy):
        return
    cmd = [str(vpy), str(Path(__file__).resolve()), *argv]
    raise SystemExit(subprocess.call(cmd))


def _seed_frozen_sidecars() -> None:
    """Copy bundled skills / .env next to the exe on first portable launch."""
    if not _is_frozen():
        return
    meipass = getattr(sys, "_MEIPASS", None)
    bundle = Path(meipass) if meipass else None
    if bundle and bundle.is_dir():
        src_skills = bundle / "skills"
        dest_skills = _ROOT / "skills"
        if src_skills.is_dir() and not dest_skills.is_dir():
            shutil.copytree(src_skills, dest_skills, ignore=shutil.ignore_patterns("__pycache__"))
        src_env = bundle / ".env"
        dest_env = _ROOT / ".env"
        if src_env.is_file() and not dest_env.is_file():
            shutil.copy2(src_env, dest_env)
    for d in ("docs", "images", "skills", "uploads", "videos"):
        (_ROOT / "workspace" / d).mkdir(parents=True, exist_ok=True)


def _fatal(msg: str, *, gui: bool) -> None:
    text = (msg or "").strip() or "Eva 启动失败"
    if gui and sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, text, "Eva", 0x10)
        except Exception:
            print(text, file=sys.stderr)
    else:
        print("")
        print(text)
        print("")
    raise SystemExit(1)


def _check_deps(*, gui: bool) -> None:
    missing: list[str] = []
    for name, pkg in (
        ("uvicorn", "uvicorn"),
        ("fastapi", "fastapi"),
        ("dotenv", "python-dotenv"),
    ):
        try:
            __import__(name)
        except ImportError:
            missing.append(pkg)
    if not missing:
        return
    if _is_frozen():
        _fatal(
            "[X] 便携包缺少运行库: "
            + ", ".join(missing)
            + "\n请使用 OPC\\员工 目录中的完整 _internal 文件夹，不要只复制 EVA.exe。",
            gui=gui,
        )
    _fatal(
        "[X] Missing packages: "
        + ", ".join(missing)
        + "\n    python -m venv .venv\n"
        "    .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt\n"
        "    .\\.venv\\Scripts\\python.exe run.py",
        gui=gui,
    )


def _read_env_port(default: int = 8080) -> int:
    raw = (os.environ.get("PORT") or "").strip()
    if raw.isdigit() and 1 <= int(raw) <= 65535:
        return int(raw)
    env = _ROOT / ".env"
    if env.is_file():
        try:
            for line in env.read_text(encoding="utf-8-sig").splitlines():
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                if k.strip() == "PORT" and v.strip().isdigit():
                    n = int(v.strip())
                    if 1 <= n <= 65535:
                        return n
        except OSError:
            pass
    return default


def _resolve_listen_port(*, cli_port: int | None, interactive: bool) -> int:
    """Remember the first chosen port for this project copy."""
    from app.desktop import load_launch_port, next_free_port, port_busy, save_launch_port

    if cli_port is not None:
        if not (1 <= cli_port <= 65535):
            print(f"[X] Invalid --port {cli_port} (need 1-65535)")
            raise SystemExit(2)
        if port_busy(cli_port):
            print(f"[X] 端口 {cli_port} 已被占用")
            raise SystemExit(2)
        save_launch_port(cli_port)
        return cli_port

    saved = load_launch_port()
    if saved is not None:
        if not port_busy(saved):
            if interactive:
                print(f"  使用上次端口 {saved}")
                print("  改端口：在启动窗口修改，或 python run.py --port 8181")
            return saved
        alt = next_free_port(saved + 1)
        if interactive:
            print(f"  已记住端口 {saved} 被占用，本次改用 {alt}")
        return alt

    suggested = next_free_port(_read_env_port())
    if interactive:
        port = _ask_port(suggested)
    else:
        port = suggested
    save_launch_port(port)
    return port


def _ask_port(suggested: int) -> int:
    from app.desktop import next_free_port, port_busy

    print("")
    print("  本目录是一份独立 Eva。请输入端口，避免和另一份冲突。")
    print("  例如：第一份 8080，复制出来的第二份 8081。")
    print("")
    while True:
        try:
            raw = input(f"  请输入端口 [{suggested}]: ").strip()
        except EOFError:
            raw = ""
        if not raw:
            port = suggested
        elif raw.isdigit() and 1 <= int(raw) <= 65535:
            port = int(raw)
        else:
            print("  端口须为 1–65535 的数字")
            continue
        if port_busy(port):
            alt = next_free_port(port + 1)
            print(f"  {port} 已被占用，自动改用 {alt}")
            return alt
        return port


def _want_gui(args: argparse.Namespace) -> bool:
    if args.cli:
        return False
    if args.gui:
        return True
    if _is_frozen():
        return True
    # Windows default is the control window (double-click run.py / run.bat).
    return sys.platform == "win32"


def _ensure_cli_console() -> None:
    if sys.platform != "win32":
        return
    if sys.stdout is not None:
        try:
            if sys.stdout.isatty():
                return
        except Exception:
            pass
    try:
        import ctypes

        ctypes.windll.kernel32.AllocConsole()
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")  # noqa: SIM115
        sys.stderr = sys.stdout
        sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")  # noqa: SIM115
    except Exception:
        pass


def _bind_host(cli_host: str | None) -> str:
    if cli_host:
        host = cli_host.strip()
        if not host:
            print("[X] Invalid --host")
            raise SystemExit(2)
        os.environ["HOST"] = host
        return host
    raw = (os.environ.get("HOST") or "").strip()
    if raw:
        return raw
    env = _ROOT / ".env"
    if env.is_file():
        try:
            for line in env.read_text(encoding="utf-8-sig").splitlines():
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                if k.strip() == "HOST" and v.strip():
                    return v.strip()
        except OSError:
            pass
    return "0.0.0.0"


def main() -> None:
    parser = argparse.ArgumentParser(description="Eva — local web server.")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        metavar="N",
        help="HTTP port. Example: --port 8081",
    )
    parser.add_argument(
        "--host",
        default=None,
        metavar="ADDR",
        help="Bind address. 0.0.0.0 = LAN. Default from .env HOST.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the system browser after the server is ready.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Verbose logs (same as DEBUG=true in .env).",
    )
    parser.add_argument(
        "--ask-port",
        action="store_true",
        help="CLI only: ask for the listen port again and remember it.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Force the Windows control window.",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Blocking terminal (no control window). Use for scripts.",
    )
    parser.add_argument(
        "--no-autostart",
        action="store_true",
        help="Open the control window without starting the server.",
    )
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="GUI: start the server as soon as the control window opens.",
    )
    args = parser.parse_args()
    _seed_frozen_sidecars()

    if args.debug:
        os.environ["DEBUG"] = "true"

    gui = _want_gui(args)
    if gui:
        argv = list(sys.argv[1:])
        if "--gui" not in argv:
            argv = ["--gui", *argv]
        _handoff_venv(argv, gui=True)
        from app.desktop import load_launch_port, next_free_port, save_launch_port

        if args.port is not None:
            if not (1 <= args.port <= 65535):
                _fatal(f"[X] Invalid --port {args.port} (need 1-65535)", gui=True)
            save_launch_port(args.port)
            port = args.port
        else:
            port = load_launch_port() or next_free_port(_read_env_port())
        os.environ["PORT"] = str(port)
        host = _bind_host(args.host)
        _check_deps(gui=True)
        try:
            from app.launcher import run_launcher
        except Exception as exc:
            _fatal(f"无法打开启动窗口（需要 tkinter）：{exc}", gui=True)
        if args.no_autostart:
            auto_start = False
        elif args.autostart:
            auto_start = True
        else:
            auto_start = None
        try:
            run_launcher(
                port=port,
                host=host,
                open_browser=False,
                debug=bool(args.debug),
                auto_start=auto_start,
            )
        except Exception as exc:
            _fatal(f"启动窗口异常：{exc}", gui=True)
        return

    _ensure_cli_console()
    if args.ask_port and args.port is None and sys.stdin is not None and sys.stdin.isatty():
        from app.desktop import save_launch_port

        suggested = None
        try:
            from app.desktop import load_launch_port, next_free_port

            suggested = load_launch_port() or next_free_port(_read_env_port())
        except Exception:
            suggested = _read_env_port()
        port = _ask_port(int(suggested))
        save_launch_port(port)
    else:
        port = _resolve_listen_port(
            cli_port=args.port,
            interactive=bool(sys.stdin is not None and sys.stdin.isatty()),
        )

    os.environ["PORT"] = str(port)
    host = _bind_host(args.host)
    handoff = ["--cli", "--port", str(port)]
    if args.host:
        handoff.extend(["--host", host])
    if args.no_browser:
        handoff.append("--no-browser")
    if args.debug:
        handoff.append("--debug")
    _handoff_venv(handoff, gui=False)

    print(f"  使用端口 {port}")
    print("")

    _check_deps(gui=False)

    from app.desktop import run_app

    run_app(open_browser=not args.no_browser, port=port)


def _crash_log(exc: BaseException) -> None:
    try:
        import traceback

        log_dir = _ROOT / "data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "launcher.log"
        log_path.write_text(
            traceback.format_exc(),
            encoding="utf-8",
            errors="replace",
        )
        _fatal(f"{type(exc).__name__}: {exc}\n详见 {log_path}", gui=True)
    except Exception:
        try:
            _fatal(str(exc), gui=True)
        except Exception:
            raise SystemExit(1) from exc


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
        raise SystemExit(0) from None
    except SystemExit:
        raise
    except Exception as exc:
        _crash_log(exc)
