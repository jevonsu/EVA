"""Eva ASGI gate — requires a local encrypted session (not cookies)."""

from __future__ import annotations

from urllib.parse import quote

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.login_prefs import load_login_prefs, save_login_prefs
from app.auth.remote import control_configured, normalize_control_url
from app.auth.routes import resolve_auth
from app.config import get_settings

# Static UI assets (JS/CSS/icons/vendor) must be public:
# they contain no secrets, and putting them behind the auth gate forces a remote
# session check + Cache-Control: no-store on every file — that alone makes page
# load multi-second on cold cache.
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


def is_local_hub_request(scope: Scope) -> bool:
    """Same-machine AgentHub may reuse Eva without re-entering the card."""
    client = ""
    peer = scope.get("client")
    if peer:
        client = str(peer[0] or "")
    if not is_loopback_host(client):
        return False
    for k, v in scope.get("headers") or []:
        if k == b"user-agent" and v.lower().startswith(b"agenthub"):
            return True
        if k == b"x-agenthub":
            return True
    return False


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
        if not getattr(settings, "auth_enabled", True):
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or "/"
        method = (scope.get("method") or "GET").upper()
        if method == "OPTIONS" or _is_public(path):
            await self.app(scope, receive, send)
            return

        # Block admin / card-issuing plane on Eva (merchant admin only)
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
            try:
                prefs_url = str((load_login_prefs() or {}).get("control_url") or "")
            except Exception:
                prefs_url = ""
            if path == "/api" or path.startswith("/api/"):
                msg = "未登录或会话已过期，请使用卡密登录"
                if not control_configured(prefs_url or None):
                    msg = "请先登录并填写可访问的鉴权网关地址（公司内网 / 外出公网）"
                await _send_json(send, 401, msg)
            else:
                await _send_redirect(send, f"/login?next={quote(path)}")
            return

        # Failover to another gateway: remember it in this install's prefs (not cookies).
        effective_ctrl = normalize_control_url(
            str(
                (info or {}).get("_effective_control_url")
                or (info or {}).get("_control_url")
                or ""
            )
        )
        if effective_ctrl:
            try:
                prefs = load_login_prefs()
                if normalize_control_url(prefs.get("control_url")) != effective_ctrl:
                    save_login_prefs(control_url=effective_ctrl, has_saved=True)
            except Exception:
                pass

        # Security headers for HTML/API only. Do NOT force no-store on every
        # response type here — static is public and sets its own cache policy.
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
