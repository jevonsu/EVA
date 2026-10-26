"""Shared HTTP helpers: proxy + FlareSolverr (no hardcoded secrets)."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.services.credentials import http_network_config

logger = logging.getLogger(__name__)


def proxy_mounts(use_proxy: bool) -> str | None:
    """Return a single proxy URL string for httpx, or None."""
    if not use_proxy:
        return None
    cfg = http_network_config()
    return cfg.get("proxy_url") or None


async def http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | bytes | None = None,
    max_chars: int = 5000,
    use_proxy: bool = False,
    use_flaresolverr: bool = False,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Perform HTTP request; return a JSON-serializable result dict."""
    if not url.startswith(("http://", "https://")):
        return {"ok": False, "error": "Only http(s) URLs are allowed"}

    method = (method or "GET").upper()
    net = http_network_config()

    if use_flaresolverr:
        fs_url = (net.get("flaresolverr_url") or "").strip()
        if not fs_url:
            return {"ok": False, "error": "未配置 FlareSolverr（设定 → 集成 → HTTP 网络）"}
        payload: dict[str, Any] = {
            "cmd": "request.get" if method == "GET" else "request.post",
            "url": url,
            "maxTimeout": 60000,
        }
        if headers:
            payload["headers"] = headers
        if use_proxy and net.get("proxy_url"):
            payload["proxy"] = {"url": net["proxy_url"]}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(90.0), trust_env=False
            ) as client:
                resp = await client.post(fs_url, json=payload)
                data = resp.json()
            if data.get("status") != "ok" and data.get("solution", {}).get("status", 0) not in (
                200,
                0,
            ):
                # Some FlareSolverr builds only set solution.status
                sol = data.get("solution") or {}
                if not sol:
                    return {"ok": False, "error": "FlareSolverr failed", "details": data}
            sol = data.get("solution") or {}
            content = str(sol.get("response") or "")
            return {
                "ok": True,
                "status_code": sol.get("status", 200),
                "content_preview": content[:max_chars],
                "content_length": len(content),
                "method": method,
                "url": url,
                "via": "flaresolverr",
            }
        except Exception as exc:
            logger.exception("FlareSolverr error")
            return {"ok": False, "error": f"FlareSolverr error: {exc}"}

    proxy = proxy_mounts(use_proxy)
    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(timeout),
        "follow_redirects": True,
        "trust_env": False,
    }
    # httpx 0.28+ uses `proxy=` single URL
    if proxy:
        client_kwargs["proxy"] = proxy

    last_err: Exception | None = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.request(
                    method,
                    url,
                    headers=headers or None,
                    content=body,
                )
                text = resp.text
                return {
                    "ok": True,
                    "status_code": resp.status_code,
                    "content_preview": text[:max_chars],
                    "content_length": len(text),
                    "method": method,
                    "url": str(resp.url),
                    "via": "proxy" if proxy else "direct",
                }
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_err = exc
            if attempt == 0:
                continue
    return {
        "ok": False,
        "error": f"Request failed: {last_err}",
        "url": url,
        "method": method,
    }


def dumps_result(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)
