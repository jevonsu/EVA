"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from app import __version__
from app.api import chat, config as config_api, memory, sessions, system, tasks, tools, workspace
from app.api import knowledge as knowledge_api
from app.api import smb_media
from app.api import storage as storage_api
from app.api import webhook as webhook_api
from app.api import refs as refs_api
from app.api import review as review_api
from app.api import workflows as workflows_api
from app.auth.gate import AuthGateASGI
from app.auth.routes import router as auth_router
from app.config import RESOURCE_ROOT, configure_logging, get_settings
from app.config_store import get_config_store
from app.mcp.client import get_mcp_manager
from app.scheduler.manager import get_scheduler
from app.services.runtime import rebuild_runtime


def _resolve_static_dir() -> Path:
    candidates = (
        Path(__file__).resolve().parent / "static",
        Path(RESOURCE_ROOT) / "app" / "static",
        Path(RESOURCE_ROOT) / "static",
    )
    for p in candidates:
        if p.is_dir():
            return p
    return candidates[0]


STATIC_DIR = _resolve_static_dir()

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
# Quiet until desktop/lifespan applies DEBUG from .env
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# In-memory SPA shell — avoid re-reading disk on every navigation
_INDEX_HTML_CACHE: bytes | None = None
_INDEX_HTML_MTIME: float | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    configure_logging(bool(getattr(settings, "debug", False)))
    get_config_store()  # ensure data/config.json exists
    try:
        from app.auth.remote import invalidate_local_cache

        invalidate_local_cache()
    except Exception:
        logger.debug("auth cache reset skipped", exc_info=True)

    # Business data: local SQLite (default) or remote SQL — before stores load
    try:
        from app.storage.bootstrap import ensure_storage

        st = ensure_storage()
        logger.info(
            "Storage backend=%s migrated=%s",
            st.get("backend"),
            st.get("migrated"),
        )
    except Exception:
        logger.exception("Storage init failed — sessions/memory/kb may be unavailable")

    if getattr(settings, "auth_enabled", True):
        try:
            from app.auth.local_session import require_cryptography
            from app.auth.users import ensure_seed_admin_from_env, needs_setup

            require_cryptography()
            ensure_seed_admin_from_env()
            if needs_setup():
                logger.info(
                    "AUTH_ENABLED: no local users yet — open /login to create admin "
                    "or set EVA_ADMIN_USER / EVA_ADMIN_PASSWORD in .env"
                )
            else:
                logger.info("AUTH_ENABLED: local username/password login")
        except Exception:
            logger.exception("AUTH bootstrap failed")

    # Core runtime first (tools + LLM). MCP may spawn slow subprocesses —
    # connect in the background so the HTTP server becomes ready quickly.
    summary = await rebuild_runtime(reconnect_mcp=False)

    async def _mcp_bg() -> None:
        try:
            from app.tools.registry import get_tool_registry

            mcp = get_mcp_manager()
            await mcp.start(get_tool_registry())
            if mcp.connected_count:
                logger.info("MCP ready: %d server(s)", mcp.connected_count)
        except Exception:
            logger.exception("Background MCP connect failed")

    asyncio.create_task(_mcp_bg())

    try:
        from app.knowledge.store import get_knowledge_store
        from app.workflow.store import get_workflow_store

        await get_knowledge_store().ensure_seed()
        await get_workflow_store().ensure_seed()
    except Exception:
        logger.exception("KB/workflow seed failed")

    try:
        from app.knowledge.skill_refs import sync_all_skill_knowledge_refs

        refs_summary = await sync_all_skill_knowledge_refs()
        if refs_summary.get("skills"):
            logger.info(
                "Skill knowledge_refs synced: skills=%s linked=%s",
                refs_summary.get("skills"),
                refs_summary.get("linked_total"),
            )
    except Exception:
        logger.exception("Skill knowledge_refs sync failed (non-fatal)")

    scheduler = get_scheduler()
    await scheduler.start()

    # Warm SPA shell into memory so first request is instant
    try:
        _load_index_html()
    except OSError:
        pass

    logger.info(
        "Agent '%s' ready | provider=%s model=%s tools=%d mcp=%d (mcp may still connect)",
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
    """Read SPA shell as UTF-8 bytes (LF only, no BOM). Cached by mtime."""
    global _INDEX_HTML_CACHE, _INDEX_HTML_MTIME
    path = STATIC_DIR / "index.html"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    if (
        _INDEX_HTML_CACHE is not None
        and mtime is not None
        and _INDEX_HTML_MTIME == mtime
    ):
        return _INDEX_HTML_CACHE

    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    # Normalize newlines — a few WebViews mis-handle CR in the first line
    body = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    _INDEX_HTML_CACHE = body
    _INDEX_HTML_MTIME = mtime
    return body


# Minimal mobile probe page. If this still "downloads as document.txt", the
# problem is outside HTML content (proxy / client), not the SPA shell.
_MOBILE_OK_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Eva OK</title>
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
<p><a href="/index.html">Open Eva</a></p>
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
        # SPA shell may change with deploys; short cache is enough for back/forward
        (b"cache-control", b"private, max-age=30"),
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

        # Diagnose rare WebView issues without flooding logs on every refresh
        ua = b""
        for k, v in scope.get("headers") or []:
            if k == b"user-agent":
                ua = v
                break
        logger.debug(
            "UI hit path=%s method=%s ua=%s",
            path,
            method,
            ua[:120].decode("utf-8", "replace"),
        )

        if path in ("/ok.html", "/m", "/m.html"):
            body = _MOBILE_OK_HTML
        else:
            try:
                body = _load_index_html()
            except OSError:
                body = (
                    b"<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
                    b"<title>Eva</title></head><body><h1>UI missing</h1></body></html>"
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
                        (b"cache-control", b"private, max-age=30"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        await _send_html(send, body)


class CachedStaticFiles(StaticFiles):
    """Static assets with browser caching (JS/CSS rarely change between deploys)."""

    def file_response(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        resp = super().file_response(*args, **kwargs)
        resp.headers.setdefault(
            "Cache-Control",
            "public, max-age=86400, stale-while-revalidate=604800",
        )
        return resp


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
    origins = settings.cors_origin_list
    # Never combine allow_origins=["*"] with credentials (browser rejects / unsafe)
    allow_creds = origins != ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_creds,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router)
    app.include_router(system.router)
    app.include_router(chat.router)
    app.include_router(sessions.router)
    app.include_router(memory.router)
    app.include_router(knowledge_api.router)
    app.include_router(refs_api.router)
    app.include_router(review_api.router)
    app.include_router(workflows_api.router)
    app.include_router(tasks.router)
    app.include_router(tools.router)
    app.include_router(config_api.router)
    app.include_router(storage_api.router)
    app.include_router(workspace.router)
    app.include_router(webhook_api.mgmt_router)
    app.include_router(webhook_api.router)
    app.include_router(smb_media.router)

    def _auth_page(name: str) -> Response:
        path = STATIC_DIR / "auth" / name
        try:
            html = path.read_text(encoding="utf-8")
        except OSError:
            return HTMLResponse("<h1>Auth page missing</h1>", status_code=500)
        # Bust browser cache for login assets after deploys
        try:
            js_m = (STATIC_DIR / "auth" / "login.js").stat().st_mtime_ns
            css_m = (STATIC_DIR / "auth" / "auth.css").stat().st_mtime_ns
            ver = f"{int(js_m)}-{int(css_m)}"
        except OSError:
            ver = "1"
        html = html.replace('href="/static/auth/auth.css"', f'href="/static/auth/auth.css?v={ver}"')
        html = html.replace('src="/static/auth/login.js"', f'src="/static/auth/login.js?v={ver}"')
        return HTMLResponse(
            html,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
            },
        )

    @app.get("/login", include_in_schema=False)
    @app.get("/login.html", include_in_schema=False)
    async def login_page() -> Response:
        return _auth_page("login.html")

    # Card issuing is merchant-admin side only — no /admin on Eva

    # Static assets (JS/CSS). Must be after API routers.
    app.mount(
        "/static",
        CachedStaticFiles(directory=str(STATIC_DIR)),
        name="static",
    )

    # UI routes are handled by MobileHtmlASGI wrapper (not registered here),
    # so they never pick up FileResponse / Content-Disposition behavior.
    return app


def build_app() -> ASGIApp:
    """ASGI: Auth gate → mobile-safe HTML shell → FastAPI."""
    return AuthGateASGI(MobileHtmlASGI(create_app()))


# Used by uvicorn: app.main:app
app = build_app()


def run() -> None:
    settings = get_settings()
    debug = bool(settings.debug)
    configure_logging(debug)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="debug" if debug else "info",
        access_log=debug,
        reload=False,
        use_colors=False,
    )


if __name__ == "__main__":
    run()
