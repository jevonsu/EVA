"""HTTP server lifecycle: start / stop uvicorn, optional CLI wait loop."""

from __future__ import annotations

import json
import logging
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("app.desktop")

LOOPBACK = "127.0.0.1"
LogFn = Callable[[str], None]


def _lan_ipv4s() -> list[str]:
    """Best-effort LAN IPv4 list for the startup banner."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.2)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        if ip and not ip.startswith("127.") and ip not in found:
            found.append(ip)
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found


def public_urls(bind_host: str, port: int) -> list[str]:
    host = (bind_host or "").strip() or "0.0.0.0"
    if host in ("0.0.0.0", "::", "*"):
        return [f"http://{ip}:{port}" for ip in _lan_ipv4s()]
    if host not in (LOOPBACK, "localhost", "::1"):
        return [f"http://{host}:{port}"]
    return []


def health_url(port: int) -> str:
    return f"http://{LOOPBACK}:{int(port)}/health"


def local_url(port: int) -> str:
    return f"http://{LOOPBACK}:{int(port)}/"


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((LOOPBACK, int(port))) == 0


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, int(port)))
            return True
        except OSError:
            return False


def next_free_port(start: int) -> int:
    p = max(1, int(start))
    while p <= 65535:
        if not port_busy(p):
            return p
        p += 1
    return int(start)


def is_healthy(url: str) -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(url, method="GET")
        with opener.open(req, timeout=1.0) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except Exception:
        return False


def wait_healthy(url: str, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_healthy(url):
            return True
        time.sleep(0.15)
    return False


def launch_path() -> Path:
    from app.config import PROJECT_ROOT

    p = Path(PROJECT_ROOT) / "data" / "launch.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_launch_prefs() -> dict:
    path = launch_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_launch_prefs(**fields: object) -> None:
    path = launch_path()
    body = load_launch_prefs()
    for k, v in fields.items():
        if v is None:
            continue
        body[k] = v
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_launch_port() -> int | None:
    try:
        port = int(load_launch_prefs().get("port") or 0)
    except (TypeError, ValueError):
        return None
    if 1 <= port <= 65535:
        return port
    return None


def save_launch_port(port: int) -> None:
    save_launch_prefs(port=int(port))


class EvaServer:
    """Start / stop the ASGI server on a background thread."""

    def __init__(self, log: LogFn | None = None) -> None:
        self._log = log or (lambda msg: print(msg))
        self._server: Any = None
        self._thread: threading.Thread | None = None
        self.host = "0.0.0.0"
        self.port = 8080
        self.debug = False

    def log(self, msg: str) -> None:
        self._log(msg)
        logger.info("%s", msg)

    @property
    def running(self) -> bool:
        t = self._thread
        return bool(t is not None and t.is_alive())

    def start(
        self,
        *,
        host: str,
        port: int,
        debug: bool = False,
        log_to_console: bool = True,
    ) -> None:
        if self.running:
            raise RuntimeError("服务已在运行")
        host = (host or "0.0.0.0").strip() or "0.0.0.0"
        port = int(port)
        if not (1 <= port <= 65535):
            raise ValueError(f"端口须为 1–65535，当前 {port}")
        health = health_url(port)
        if is_healthy(health):
            raise RuntimeError(f"端口 {port} 上已有 Eva（{health}）。请换一个端口。")
        bind_check = "0.0.0.0" if host in ("0.0.0.0", "::") else host
        if not port_free(bind_check, port) and not port_free(LOOPBACK, port):
            raise RuntimeError(f"端口 {port} 已被占用，请换一个再启动。")

        from app.config import configure_logging, get_settings
        from app.main import app as asgi_app
        import uvicorn

        get_settings.cache_clear()
        settings = get_settings()
        settings.ensure_dirs()
        debug = bool(debug or getattr(settings, "debug", False))
        configure_logging(debug)

        self.host = host
        self.port = port
        self.debug = debug

        config_kw: dict[str, Any] = {
            "host": host,
            "port": port,
            "log_level": "debug" if debug else "info",
            "reload": False,
            "access_log": bool(debug),
            "use_colors": False,
        }
        if not log_to_console:
            config_kw["log_config"] = None

        config = uvicorn.Config(asgi_app, **config_kw)
        server = uvicorn.Server(config)
        self._server = server

        def _run() -> None:
            try:
                server.run()
            except Exception:
                logger.exception("Uvicorn thread crashed")
            finally:
                self._server = None

        thread = threading.Thread(target=_run, name="eva-uvicorn", daemon=True)
        self._thread = thread
        self.log(f"Starting Eva on {host}:{port} …")
        thread.start()

    def wait_ready(self, timeout: float = 45.0) -> bool:
        return wait_healthy(health_url(self.port), timeout=timeout)

    def stop(self, timeout: float = 8.0) -> None:
        server = self._server
        thread = self._thread
        if server is not None:
            logger.info("Shutting down backend")
            server.should_exit = True
        if thread is not None and thread.is_alive():
            thread.join(timeout=min(max(timeout, 0.5), 4.0))
        if thread is not None and thread.is_alive() and server is not None:
            try:
                server.force_exit = True
            except Exception:
                pass
            thread.join(timeout=timeout)
        self._server = None
        self._thread = None

    def banner_lines(self) -> list[str]:
        base = local_url(self.port).rstrip("/")
        lines = ["", f"  本机     {base}/"]
        for u in public_urls(self.host, self.port):
            lines.append(f"  局域网   {u}/")
        lines.append(f"  登录     {base}/login")
        lan = public_urls(self.host, self.port)
        if lan:
            lines.append("  访问     局域网用上面 IP 地址，协议必须是 http://（不要 https）")
            if sys.platform == "win32" and self.host in ("0.0.0.0", "::", "*"):
                lines.append("  防火墙   若 IP 打不开：Windows 防火墙放行该端口入站（TCP）")
        elif self.host in (LOOPBACK, "localhost", "::1"):
            lines.append("  注意     当前 HOST=127.0.0.1，只能本机打开；局域网请改 .env 为 HOST=0.0.0.0")
        try:
            from app.config import get_settings

            settings = get_settings()
            auth_on = bool(getattr(settings, "auth_enabled", True))
            if auth_on:
                card_remote = bool(getattr(settings, "auth_card_remote", False))
                has_gateway = bool(
                    (getattr(settings, "auth_control_url", "") or "").strip()
                    and (getattr(settings, "auth_control_key", "") or "").strip()
                )
                if card_remote and has_gateway:
                    lines.append(
                        "  鉴权     远程卡密模式已开启；已登录则直接进入"
                    )
                else:
                    lines.append(
                        "  鉴权     本机账号密码登录；已登录则直接进入（首次可打开 /login 建管理员）"
                    )
            if self.debug:
                lines.append("  Debug    开（详细日志 / 访问记录）")
        except Exception:
            pass
        lines.append("")
        return lines


def run_app(
    *,
    open_browser: bool = True,
    port: int | None = None,
) -> None:
    """CLI: start HTTP server and block until Ctrl+C."""
    from app.config import configure_logging, get_settings

    settings = get_settings()
    settings.ensure_dirs()
    debug = bool(getattr(settings, "debug", False))
    configure_logging(debug)

    if port is not None:
        preferred = int(port)
    else:
        preferred = int(settings.port or 8080)
    bind_host = (settings.host or "0.0.0.0").strip() or "0.0.0.0"

    server = EvaServer()
    try:
        server.start(host=bind_host, port=preferred, debug=debug, log_to_console=True)
    except Exception as exc:
        logger.exception("Failed to start backend")
        raise SystemExit(f"Backend failed to import/start: {exc}") from exc
    if not server.wait_ready(timeout=45.0):
        server.stop()
        raise SystemExit(f"Backend failed to start ({LOOPBACK}:{preferred}).")

    for line in server.banner_lines():
        server.log(line)
    server.log("  停止     Ctrl+C")
    server.log("")

    if open_browser:
        try:
            webbrowser.open(local_url(server.port))
        except Exception:
            logger.exception("webbrowser.open failed")

    try:
        while server.running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        server.log("\nStopping…")
    finally:
        server.stop()
        time.sleep(0.3)
