"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from app import __version__
from app.api import chat, config as config_api, memory, sessions, system, tasks, tools, workspace
from app.api import knowledge as knowledge_api
from app.api import smb_media
from app.api import webhook as webhook_api
from app.api import workflows as workflows_api
from app.config import get_settings
from app.config_store import get_config_store
from app.mcp.client import get_mcp_manager
from app.scheduler.manager import get_scheduler
from app.services.runtime import rebuild_runtime

STATIC_DIR = Path(__file__).resolve().parent / "static"

# SPA shell paths — served as pure HTML (never FileResponse / Content-Disposition)
_UI_PATHS = frozenset(
    {
        "/",
        "/index.html",
        "/index.htm",
        "/ui",
        "/chat",
        "/app",
        "/ok.html",
        "/m",
        "/m.html",
    }
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    encoding="utf-8",
)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    get_config_store()  # ensure data/config.json exists

    summary = await rebuild_runtime(reconnect_mcp=True)

    try:
        from app.knowledge.store import get_knowledge_store
        from app.workflow.store import get_workflow_store

        await get_knowledge_store().ensure_seed()
        await get_workflow_store().ensure_seed()
    except Exception:
        logger.exception("KB/workflow seed failed")

    scheduler = get_scheduler()
    await scheduler.start()

    logger.info(
        "Agent '%s' ready | provider=%s model=%s tools=%d mcp=%d",
        summary.get("agent") or settings.agent_name,
        (summary.get("llm") or {}).get("provider"),
        (summary.get("llm") or {}).get("model"),
        summary.get("tools"),
        summary.get("mcp_servers"),
    )
    yield

    await scheduler.shutdown()
    await get_mcp_manager().shutdown()
    logger.info("Agent shutdown complete")


def _load_index_html() -> bytes:
    """Read SPA shell as UTF-8 bytes (LF only, no BOM)."""
    raw = (STATIC_DIR / "index.html").read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    # Normalize newlines — a few WebViews mis-handle CR in the first line
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


# Minimal mobile probe page. If this still "downloads as document.txt", the
# problem is outside HTML content (proxy / client), not the SPA shell.
_MOBILE_OK_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AgentOS OK</title>
<style>
body{font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3;padding:24px;line-height:1.6}
a{color:#3fb950}
.box{max-width:420px;margin:40px auto;padding:20px;border:1px solid #30363d;border-radius:12px;background:#161b22}
</style>
</head>
<body>
<div class="box">
<h1>&#10003; Mobile HTML OK</h1>
<p>If you can read this page, the browser is rendering HTML (not downloading document.txt).</p>
<p><a href="/index.html">Open AgentOS</a></p>
<p style="color:#8b949e;font-size:13px">Tip: turn off phone VPN/proxy; use http:// not https://</p>
</div>
</body>
</html>
""".encode("utf-8")


async def _send_html(send: Send, body: bytes, status: int = 200) -> None:
    """Emit the smallest possible HTML response.

    No Content-Disposition, no Accept-Ranges, no extra sniff headers.
    Many Chinese mobile WebViews rename anonymous text downloads to document.txt
    when Content-Disposition or wrong Content-Type is present.
    """
    headers = [
        (b"content-type", b"text/html; charset=utf-8"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class MobileHtmlASGI:
    """Pure ASGI wrapper: UI paths never go through FileResponse / heavy middleware quirks."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or "/"
        method = (scope.get("method") or "GET").upper()
        if path not in _UI_PATHS or method not in ("GET", "HEAD"):
            await self.app(scope, receive, send)
            return

        # Log mobile probes for diagnosis
        ua = b""
        for k, v in scope.get("headers") or []:
            if k == b"user-agent":
                ua = v
                break
        logger.info("UI hit path=%s method=%s ua=%s", path, method, ua[:120].decode("utf-8", "replace"))

        if path in ("/ok.html", "/m", "/m.html"):
            body = _MOBILE_OK_HTML
        else:
            try:
                body = _load_index_html()
            except OSError:
                body = (
                    b"<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
                    b"<title>AgentOS</title></head><body><h1>UI missing</h1></body></html>"
                )
                await _send_html(send, body, status=500)
                return

        if method == "HEAD":
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"text/html; charset=utf-8"),
                        (b"content-length", str(len(body)).encode("ascii")),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        await _send_html(send, body)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.agent_name,
        version=__version__,
        description=(
            "Python backend AI Agent with multi-provider LLM, "
            "tool/skill system, memory, task scheduler, and MCP."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system.router)
    app.include_router(chat.router)
    app.include_router(sessions.router)
    app.include_router(memory.router)
    app.include_router(knowledge_api.router)
    app.include_router(workflows_api.router)
    app.include_router(tasks.router)
    app.include_router(tools.router)
    app.include_router(config_api.router)
    app.include_router(workspace.router)
    app.include_router(webhook_api.mgmt_router)
    app.include_router(webhook_api.router)
    app.include_router(smb_media.router)

    # Static assets (JS/CSS). Must be after API routers.
    app.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="static",
    )

    # UI routes are handled by MobileHtmlASGI wrapper (not registered here),
    # so they never pick up FileResponse / Content-Disposition behavior.
    return app


def build_app() -> ASGIApp:
    """ASGI app with mobile-safe HTML shell in front of FastAPI."""
    return MobileHtmlASGI(create_app())


# Used by uvicorn: app.main:app
app = build_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=bool(settings.debug),
    )


if __name__ == "__main__":
    run()
