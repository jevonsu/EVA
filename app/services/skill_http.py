"""Proxy-free HTTP for skills talking to LAN services (NocoDB, qB, NAS APIs).

Inside ``async def handle`` ALWAYS use ``await arequest(...)`` (runs in a worker
thread). The sync ``request(...)`` blocks EVA's single event loop — every
session, SSE stream and the stop button freeze until it returns.

Do not use the system HTTP_PROXY / 设定→集成 http.proxy — those are for
public websites. LAN 502s after a few days are usually proxy or Host-spoofing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# Empty proxy so urllib never inherits HTTP_PROXY / HTTPS_PROXY.
_NO_PROXY = urllib.request.ProxyHandler({})
_CTX = ssl.create_default_context()
_OPENER = urllib.request.build_opener(_NO_PROXY, urllib.request.HTTPSHandler(context=_CTX))

logger = logging.getLogger("app.services.skill_http")
_warned: set[str] = set()
_warn_lock = threading.Lock()


def _warn_if_on_loop(url: str) -> None:
    """Log once per host when sync request() runs on the event-loop thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return  # worker thread / sync context: fine
    try:
        host = urllib.parse.urlparse(url).netloc or url[:60]
    except Exception:
        host = "?"
    with _warn_lock:
        if host in _warned:
            return
        _warned.add(host)
    logger.warning(
        "skill_http.request(%s) called on the event loop thread: this blocks all "
        "sessions until it returns. Use `await skill_http.arequest(...)` or "
        "`await asyncio.to_thread(request, ...)` in async handlers.",
        host,
    )


def gateway_hint(status: int | None, body: Any = None) -> str | None:
    if status in (502, 503, 504) or status == -1:
        return (
            "这是网关/反代/连不上上游（常见 502），不是表结构或 action 写错。"
            "请核对设定→集成的 base_url 能否在浏览器打开；"
            "不要改 Host=localhost、不要改技能代码里的 IP。"
            "重启 Eva 后再试；只重启 NocoDB/qB 容器往往无效。"
        )
    return None


def origin_from_base(base_url: str) -> str:
    raw = (base_url or "").strip() or "http://127.0.0.1"
    p = urllib.parse.urlparse(raw if "://" in raw else "http://" + raw)
    scheme = p.scheme or "http"
    host = p.hostname or "127.0.0.1"
    port = p.port
    default = 443 if scheme == "https" else 80
    if port and port != default:
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: Any = None,
    form: dict[str, Any] | None = None,
    timeout: float = 30,
) -> tuple[int, Any, dict[str, str]]:
    """Return (status, parsed_body, response_headers). Body is dict/list/str."""
    _warn_if_on_loop(url)
    hdrs = {str(k): str(v) for k, v in (headers or {}).items() if v is not None}
    data: bytes | None = None
    if json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    elif form is not None:
        data = urllib.parse.urlencode(
            {k: v for k, v in form.items() if v is not None}
        ).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=(method or "GET").upper())
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read()
            text = raw.decode("utf-8", "replace")
            parsed: Any = text
            if text:
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = text
            rh = {k: v for k, v in resp.headers.items()}
            return int(resp.status), parsed, rh
    except urllib.error.HTTPError as e:
        raw = e.read() if e.fp else b""
        text = raw.decode("utf-8", "replace") if raw else ""
        parsed: Any = text
        if text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = text
        rh = {k: v for k, v in (e.headers.items() if e.headers else [])}
        return int(e.code), parsed, rh
    except Exception as e:
        return -1, {"error": str(e)}, {}


async def arequest(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: Any = None,
    form: dict[str, Any] | None = None,
    timeout: float = 30,
) -> tuple[int, Any, dict[str, str]]:
    """Non-blocking ``request``: same arguments/return, runs in a worker thread
    so the event loop (other chats, stop button) keeps going."""
    return await asyncio.to_thread(
        request,
        method,
        url,
        headers=headers,
        json_body=json_body,
        form=form,
        timeout=timeout,
    )
