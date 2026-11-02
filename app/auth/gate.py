"""Eva ASGI gate — requires a local password session."""

from __future__ import annotations

from urllib.parse import quote

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.routes import resolve_auth
from app.config import get_settings

_PUBLIC_PREFIXES = (
    "/login",
    "/api/auth/",
    "/static/",
    "/favicon.ico",
    "/health",
    "/ok.html",
    "/m",
    "/m.html",
    "/api/webhook/",
    "/webhook/",
)

_PUBLIC_EXACT = frozenset(
    {
        "/login",
        "/login.html",
        "/health",
        "/api",
        "/ok.html",
        "/m",
        "/m.html",
        "/favicon.ico",
    }
)


def is_loopback_host(host: str) -> bool:
    h = (host or "").strip().strip("[]").split("%", 1)[0].lower()
    return h in ("127.0.0.1", "::1", "localhost")


def _client_host(scope: Scope) -> str:
    peer = scope.get("client")
    if peer:
        return str(peer[0] or "")
    return ""


def _is_public(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    for p in _PUBLIC_PREFIXES:
        if path == p.rstrip("/") or path.startswith(p):
            return True
    return False


async def _send_redirect(send: Send, location: str, status: int = 302) -> None:
    headers = [
        (b"location", location.encode("ascii", "ignore")),
        (b"content-type", b"text/html; charset=utf-8"),
        (b"cache-control", b"no-store"),
        (b"content-length", b"0"),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": b""})


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
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        path = scope.get("path") or "/"
        method = (scope.get("method") or "GET").upper()
        client = _client_host(scope)

        # F08: AUTH_ENABLED=false only allowed from loopback
        if not getattr(settings, "auth_enabled", True):
            if not is_loopback_host(client):
                if path == "/api" or path.startswith("/api/"):
                    await _send_json(
                        send,
                        403,
                        "AUTH_ENABLED=false 仅允许本机访问；请从 127.0.0.1 连接或开启鉴权",
                    )
                else:
                    await _send_json(
                        send,
                        403,
                        "AUTH_ENABLED=false 仅允许本机访问",
                    )
                return
            await self.app(scope, receive, send)
            return

        if method == "OPTIONS" or _is_public(path):
            await self.app(scope, receive, send)
            return

        if path.startswith("/admin") or path.startswith("/api/auth/admin") or path.startswith(
            "/api/cards"
        ):
            if path == "/api" or path.startswith("/api/"):
                await _send_json(send, 404, "not found")
            else:
                await _send_redirect(send, "/login")
            return

        from starlette.requests import Request as StarletteRequest

        req = StarletteRequest(scope, receive)
        info = await resolve_auth(req)
        if not info:
            if path == "/api" or path.startswith("/api/"):
                await _send_json(send, 401, "未登录或会话已过期，请使用账号密码登录")
            else:
                await _send_redirect(send, f"/login?next={quote(path)}")
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                existing = {h[0].lower() for h in headers}
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                ]
                if b"cache-control" not in existing:
                    extra.append((b"cache-control", b"no-store"))
                for k, v in extra:
                    if k not in existing:
                        headers.append((k, v))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
