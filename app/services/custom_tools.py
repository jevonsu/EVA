"""Register custom HTTP tools from config."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config_store import get_config_store
from app.tools.registry import ToolRegistry, get_tool_registry

logger = logging.getLogger(__name__)


def _make_http_handler(spec: dict[str, Any]):
    method = (spec.get("method") or "GET").upper()
    url_template = spec.get("url") or ""
    headers = dict(spec.get("headers") or {})
    timeout = float(spec.get("timeout") or 20)
    body_template = spec.get("body")  # optional JSON string or object

    async def handler(**kwargs: Any) -> str:
        url = url_template
        # simple {param} substitution
        for k, v in kwargs.items():
            url = url.replace("{" + k + "}", str(v))

        # leftover kwargs as query for GET, json body for others
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                if method == "GET":
                    # append unused kwargs as query if not substituted
                    unused = {
                        k: v
                        for k, v in kwargs.items()
                        if "{" + k + "}" not in url_template
                    }
                    if unused and "?" not in url:
                        url = f"{url}?{urlencode({k: str(v) for k, v in unused.items()})}"
                    resp = await client.request(method, url, headers=headers)
                else:
                    body = body_template
                    if isinstance(body, str) and body.strip():
                        try:
                            body = json.loads(body)
                        except json.JSONDecodeError:
                            pass
                    if body is None:
                        body = kwargs
                    elif isinstance(body, dict):
                        # fill {placeholders} in string values
                        filled = {}
                        for bk, bv in body.items():
                            if isinstance(bv, str):
                                for k, v in kwargs.items():
                                    bv = bv.replace("{" + k + "}", str(v))
                            filled[bk] = bv
                        body = {**filled, **{k: v for k, v in kwargs.items() if k not in filled}}
                    resp = await client.request(method, url, headers=headers, json=body)

                text = resp.text[:8000]
                return json.dumps(
                    {
                        "status": resp.status_code,
                        "url": str(resp.url),
                        "body": text,
                        "truncated": len(resp.text) > 8000,
                    },
                    ensure_ascii=False,
                )
        except Exception as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    return handler


def register_custom_tools(registry: ToolRegistry | None = None) -> int:
    registry = registry or get_tool_registry()
    store = get_config_store()

    # drop previous custom tools
    for t in list(registry.list_tools()):
        if t.source == "custom":
            registry.unregister(t.name)

    count = 0
    for spec in store.custom_tools():
        if not spec.get("enabled", True):
            continue
        name = spec.get("name")
        if not name:
            continue
        # sanitize name
        safe = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
        tool_type = (spec.get("type") or "http").lower()
        if tool_type != "http":
            logger.warning("Unsupported custom tool type: %s", tool_type)
            continue

        params = spec.get("parameters") or {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional query/input"},
            },
        }
        handler = _make_http_handler(spec)
        registry.register(
            safe,
            spec.get("description") or f"Custom HTTP tool: {safe}",
            handler,
            params,
            source="custom",
            metadata={"id": spec.get("id"), "url": spec.get("url")},
        )
        count += 1
    return count
