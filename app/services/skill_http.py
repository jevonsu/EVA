"""Proxy-free HTTP for skills talking to LAN services (NocoDB, qB, NAS APIs).

Do not use the system HTTP_PROXY / 设定→集成 http.proxy — those are for
public websites. LAN 502s after a few days are usually proxy or Host-spoofing.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# Empty proxy so urllib never inherits HTTP_PROXY / HTTPS_PROXY.
_NO_PROXY = urllib.request.ProxyHandler({})
_CTX = ssl.create_default_context()
_OPENER = urllib.request.build_opener(_NO_PROXY, urllib.request.HTTPSHandler(context=_CTX))


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
