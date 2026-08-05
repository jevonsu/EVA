"""ASGI auth gate — redirect unauthenticated users; protect APIs."""

from __future__ import annotations

import logging
from urllib.parse import quote

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.routes import COOKIE_ADMIN, COOKIE_USER
from app.auth.store import get_auth_store
from app.config import get_settings

logger = logging.getLogger("app.auth.gate")

# Paths that never require a user card session
_PUBLIC_PREFIXES = (
    "/login",
    "/admin",
    "/api/auth/",
    "/static/auth/",
    "/favicon.ico",
    "/health",
    "/ok.html",
    "/m",
    "/m.html",
    # External inbound webhooks (tokenized by slug/secret themselves)
    "/api/webhook/",
    "/webhook/",
)

# Static app assets still need auth when gate enabled (prevent free use of UI assets alone is weak;
# but API is what matters). Allow static after auth OR for login/admin pages only via /static/auth.
_PUBLIC_EXACT = frozenset(
    {
        "/login",
        "/login.html",
        "/admin",
        "/admin.html",
        "/admin/login",
        "/health",
        "/ok.html",
        "/m",
        "/m.html",
        "/favicon.ico",
    }
)


def _parse_cookies(scope: Scope) -> dict[str, str]:
    raw = b""
    for k, v in scope.get("headers") or []:
        if k == b"cookie":
            raw = v
            break
    out: dict[str, str] = {}
    if not raw:
        return out
    for part in raw.decode("latin-1", "replace").split(";"):
        part = part.strip()
        if "=" in part:
            name, val = part.split("=", 1)
            out[name.strip()] = val.strip()
    return out


def _is_public(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    for p in _PUBLIC_PREFIXES:
        if path == p.rstrip("/") or path.startswith(p):
            return True
    return False


def _is_admin_path(path: str) -> bool:
    if path in ("/admin", "/admin.html") or path.startswith("/admin/"):
        return True
    if path.startswith("/api/auth/admin/"):
        return True
    return False


async def _send_redirect(send: Send, location: str, status: int = 302) -> None:
    body = b""
    headers = [
        (b"location", location.encode("ascii", "ignore")),
        (b"content-type", b"text/html; charset=utf-8"),
        (b"cache-control", b"no-store"),
        (b"content-length", b"0"),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _send_json(send: Send, status: int, msg: str) -> None:
    import json

    body = json.dumps({"detail": msg}, ensure_ascii=False).encode("utf-8")
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"cache-control", b"no-store"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"x-content-type-options", b"nosniff"),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class AuthGateASGI:
    """Outer gate: card session for app; admin session for /admin."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        if not getattr(settings, "auth_enabled", True):
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or "/"
        method = (scope.get("method") or "GET").upper()

        # Always allow CORS preflight
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        if _is_public(path):
            # Admin HTML shell is public; admin APIs (except login) still checked below
            if path.startswith("/api/auth/admin/") and path not in (
                "/api/auth/admin/login",
                "/api/auth/admin/logout",
            ):
                cookies = _parse_cookies(scope)
                adm = get_auth_store().resolve_admin_session(cookies.get(COOKIE_ADMIN))
                if not adm:
                    await _send_json(send, 401, "管理员未登录")
                    return
            await self.app(scope, receive, send)
            return

        cookies = _parse_cookies(scope)

        # Admin-only paths that are not under public API list
        if _is_admin_path(path):
            adm = get_auth_store().resolve_admin_session(cookies.get(COOKIE_ADMIN))
            if not adm:
                if path.startswith("/api/"):
                    await _send_json(send, 401, "管理员未登录")
                else:
                    await _send_redirect(send, "/admin")
                return
            await self.app(scope, receive, send)
            return

        # User card session for everything else (/, /api/chat, /static/* except /static/auth)
        sess = get_auth_store().resolve_session(cookies.get(COOKIE_USER))
        if not sess:
            if path.startswith("/api/"):
                await _send_json(send, 401, "未登录或会话已过期，请使用卡密登录")
            else:
                nxt = quote(path)
                await _send_redirect(send, f"/login?next={nxt}")
            return

        # Attach security headers on the way out
        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    (b"cache-control", b"no-store"),
                ]
                # avoid duplicates
                existing = {h[0].lower() for h in headers}
                for k, v in extra:
                    if k not in existing:
                        headers.append((k, v))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
