"""Multi-endpoint inbound webhooks + management API.

Management (local UI, no token):
  GET    /api/webhooks
  POST   /api/webhooks
  GET    /api/webhooks/{id}
  PUT    /api/webhooks/{id}
  DELETE /api/webhooks/{id}
  POST   /api/webhooks/{id}/regenerate-token
  GET    /api/webhooks/{id}/token   (reveal once for copy)

Inbound:
  POST /api/webhook/chat              — match by token
  POST /api/webhook/{slug}/chat       — by slug + token
  GET  /api/webhook/health
  GET  /api/webhook/{slug}/health
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.agent.core import get_agent
from app.config import get_settings
from app.webhook.store import get_webhook_store, normalize_slug, public_endpoint

# Management + inbound share this module; two routers mounted from main
mgmt_router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
router = APIRouter(prefix="/api/webhook", tags=["webhook"])
logger = logging.getLogger("app.webhook")

_map_lock = threading.RLock()


def _truthy(v: Any, default: bool = True) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on", "y"):
        return True
    if s in ("0", "false", "no", "off", "n", ""):
        return False
    return default


def _extract_token(
    authorization: str | None,
    x_webhook_token: str | None,
    x_api_key: str | None,
) -> str:
    if x_webhook_token and x_webhook_token.strip():
        return x_webhook_token.strip()
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    auth = (authorization or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    if auth.lower().startswith("token "):
        return auth[6:].strip()
    return auth


def _env_fallback_token() -> str:
    return (os.environ.get("WEBHOOK_TOKEN") or "").strip()


def _resolve_endpoint(
    *,
    slug: str | None,
    authorization: str | None,
    x_webhook_token: str | None,
    x_api_key: str | None,
) -> dict[str, Any]:
    """Resolve inbound endpoint by slug and/or token."""
    store = get_webhook_store()
    got = _extract_token(authorization, x_webhook_token, x_api_key)
    env_tok = _env_fallback_token()

    ep: dict[str, Any] | None = None
    if slug:
        ep = store.get_by_slug_raw(slug)
        if not ep:
            raise HTTPException(status_code=404, detail=f"Webhook 通道不存在: {slug}")
        if not ep.get("enabled", True):
            raise HTTPException(status_code=403, detail="该 Webhook 通道已停用")
        expected = str(ep.get("token") or "").strip()
        if not expected and env_tok:
            expected = env_tok
        if not expected:
            raise HTTPException(status_code=503, detail="该通道未配置 token")
        if not got or got != expected:
            raise HTTPException(status_code=401, detail="Invalid webhook token")
        return ep

    # no slug: match token across all endpoints
    if got:
        ep = store.find_by_token(got)
        if ep:
            if not ep.get("enabled", True):
                raise HTTPException(status_code=403, detail="该 Webhook 通道已停用")
            return ep
        # env global fallback → first enabled or synthetic
        if env_tok and got == env_tok:
            for row in store.list_raw():
                if row.get("enabled", True):
                    return row
            return {
                "id": "env",
                "name": "WEBHOOK_TOKEN",
                "slug": "env",
                "enabled": True,
                "token": env_tok,
                "platform": "custom",
                "session_mode": "map",
                "session_id": "",
                "use_tools": True,
                "use_memory": True,
            }

    if not store.list_raw() and not env_tok:
        raise HTTPException(
            status_code=503,
            detail="尚未配置任何 Webhook 通道。请打开设定 → Webhook 新建通道。",
        )
    if not got:
        raise HTTPException(status_code=401, detail="缺少 X-Webhook-Token")
    raise HTTPException(status_code=401, detail="Invalid webhook token")


def _session_map_path() -> Path:
    return get_settings().data_dir / "webhook_sessions.json"


def _load_session_map() -> dict[str, str]:
    path = _session_map_path()
    with _map_lock:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items() if k and v}
        except (OSError, json.JSONDecodeError):
            logger.exception("Failed to load webhook session map")
        return {}


def _save_session_map(data: dict[str, str]) -> None:
    path = _session_map_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _map_lock:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _map_key(endpoint_id: str, source: str, external_id: str) -> str:
    eid = (endpoint_id or "x")[:32]
    src = re.sub(r"[^\w\-./:]+", "_", (source or "custom").strip())[:40] or "custom"
    ext = (external_id or "").strip()[:200]
    return f"{eid}:{src}:{ext}"


def _bind_external(
    endpoint_id: str, source: str, external_id: str | None, session_id: str
) -> None:
    if not external_id or not session_id:
        return
    key = _map_key(endpoint_id, source, external_id)
    with _map_lock:
        data = _load_session_map()
        if data.get(key) == session_id:
            return
        data[key] = session_id
        if len(data) > 5000:
            for k in list(data.keys())[: len(data) - 4000]:
                data.pop(k, None)
        _save_session_map(data)


def _resolve_session_for_endpoint(
    ep: dict[str, Any],
    *,
    payload_session_id: str | None,
    external_id: str | None,
    source: str,
) -> str | None:
    """Choose internal session according to endpoint session_mode."""
    # explicit override from payload always wins
    if payload_session_id:
        return payload_session_id

    mode = str(ep.get("session_mode") or "fixed").strip().lower()
    fixed = str(ep.get("session_id") or "").strip() or None
    ep_id = str(ep.get("id") or "")

    if mode == "new":
        return None  # agent creates new

    if mode == "fixed":
        return fixed

    # map mode: sticky by external_id, fallback to fixed session_id
    if external_id:
        key = _map_key(ep_id, source, external_id)
        mapped = _load_session_map().get(key)
        if mapped:
            return mapped
    return fixed


def _pick_message(payload: dict[str, Any]) -> str:
    for key in ("message", "text", "content", "query", "prompt", "msg"):
        v = payload.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            for nk in ("text", "content", "message"):
                nv = v.get(nk)
                if isinstance(nv, str) and nv.strip():
                    return nv.strip()
    event = payload.get("event")
    if isinstance(event, dict):
        msg = event.get("message") or event.get("text")
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                try:
                    inner = json.loads(content)
                    if isinstance(inner, dict) and isinstance(inner.get("text"), str):
                        return inner["text"].strip()
                except json.JSONDecodeError:
                    return content.strip()
            if isinstance(msg.get("text"), str) and msg["text"].strip():
                return msg["text"].strip()
        if isinstance(msg, str) and msg.strip():
            return msg.strip()
    return ""


def _pick_external_id(payload: dict[str, Any]) -> str:
    for key in (
        "external_id",
        "conversation_id",
        "chat_id",
        "thread_id",
        "channel_id",
        "open_id",
        "user_id",
    ):
        v = payload.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    event = payload.get("event")
    if isinstance(event, dict):
        msg = event.get("message") if isinstance(event.get("message"), dict) else {}
        chat = event.get("chat") if isinstance(event.get("chat"), dict) else {}
        for src in (msg, chat, event):
            if not isinstance(src, dict):
                continue
            for key in ("chat_id", "conversation_id", "message_id", "open_id", "user_id"):
                v = src.get(key)
                if v is not None and str(v).strip():
                    return str(v).strip()
    return ""


async def _parse_payload(request: Request) -> dict[str, Any]:
    content_type = (request.headers.get("content-type") or "").lower()
    payload: dict[str, Any] = {}
    try:
        if "application/json" in content_type or not content_type:
            body = await request.body()
            if body:
                data = json.loads(body.decode("utf-8"))
                if isinstance(data, dict):
                    payload = data
                elif isinstance(data, str):
                    payload = {"message": data}
        elif (
            "application/x-www-form-urlencoded" in content_type
            or "multipart/form-data" in content_type
        ):
            form = await request.form()
            payload = {k: form.get(k) for k in form.keys()}
        else:
            raw = (await request.body()).decode("utf-8", errors="replace").strip()
            if raw:
                try:
                    data = json.loads(raw)
                    payload = data if isinstance(data, dict) else {"message": str(data)}
                except json.JSONDecodeError:
                    payload = {"message": raw}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    return payload


async def _run_chat(
    ep: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    # Feishu / Lark URL verification
    if payload.get("type") == "url_verification" or payload.get("challenge"):
        challenge = payload.get("challenge")
        if challenge is not None:
            return {"challenge": challenge}

    message = _pick_message(payload)
    if not message:
        raise HTTPException(status_code=400, detail="缺少 message/text/content 字段")

    platform = str(ep.get("platform") or "custom").strip() or "custom"
    source = str(payload.get("source") or platform).strip() or platform
    payload_sid = str(payload.get("session_id") or "").strip() or None
    external_id = (
        str(payload.get("external_id") or "").strip()
        or str(payload.get("conversation_id") or "").strip()
        or str(payload.get("chat_id") or "").strip()
        or _pick_external_id(payload)
        or None
    )

    resolved = _resolve_session_for_endpoint(
        ep,
        payload_session_id=payload_sid,
        external_id=external_id,
        source=source,
    )

    use_tools = ep.get("use_tools", True)
    use_memory = ep.get("use_memory", True)
    if "use_tools" in payload and payload["use_tools"] is not None:
        use_tools = (
            _truthy(payload.get("use_tools"), bool(use_tools))
            if isinstance(payload.get("use_tools"), str)
            else bool(payload["use_tools"])
        )
    if "use_memory" in payload and payload["use_memory"] is not None:
        use_memory = (
            _truthy(payload.get("use_memory"), bool(use_memory))
            if isinstance(payload.get("use_memory"), str)
            else bool(payload["use_memory"])
        )

    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

    logger.info(
        "webhook chat ep=%s slug=%s mode=%s external=%s session=%s len=%d",
        ep.get("id"),
        ep.get("slug"),
        ep.get("session_mode"),
        (external_id or "")[:40],
        resolved or "(new)",
        len(message),
    )

    agent = get_agent()
    try:
        result = await agent.chat(
            message,
            session_id=resolved,
            use_tools=bool(use_tools),
            use_memory=bool(use_memory),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("webhook chat failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    mode = str(ep.get("session_mode") or "fixed")
    if mode == "map":
        _bind_external(str(ep.get("id") or ""), source, external_id, result.session_id)

    return {
        "ok": True,
        "webhook_id": ep.get("id"),
        "webhook_name": ep.get("name"),
        "slug": ep.get("slug"),
        "session_id": result.session_id,
        "reply": result.reply,
        "model": result.model,
        "source": source,
        "external_id": external_id,
        "session_mode": mode,
        "tool_calls": [
            {
                "id": t.id,
                "name": t.name,
                "arguments": t.arguments,
                "result": (t.result[:2000] if isinstance(t.result, str) else t.result),
            }
            for t in (result.tool_calls or [])
        ],
        "usage": result.usage,
        "metadata": meta or None,
    }


# ---------- Management API ----------


class WebhookUpsert(BaseModel):
    name: str | None = None
    slug: str | None = None
    enabled: bool | None = True
    token: str | None = None
    platform: str | None = "custom"
    session_mode: str | None = "fixed"  # fixed | map | new
    session_id: str | None = None
    use_tools: bool | None = True
    use_memory: bool | None = True
    note: str | None = None


@mgmt_router.get("")
async def list_webhooks() -> dict[str, Any]:
    store = get_webhook_store()
    items = store.list_public()
    return {"ok": True, "count": len(items), "items": items}


@mgmt_router.post("")
async def create_webhook(body: WebhookUpsert) -> dict[str, Any]:
    store = get_webhook_store()
    try:
        row = store.create(body.model_dump(exclude_none=False))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # include token once on create
    raw = store.get_raw(row["id"])
    if raw:
        row = public_endpoint(raw)
        row["token"] = str(raw.get("token") or "")
    return {"ok": True, "item": row}


@mgmt_router.get("/{endpoint_id}")
async def get_webhook(endpoint_id: str) -> dict[str, Any]:
    store = get_webhook_store()
    raw = store.get_raw(endpoint_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Webhook 不存在")
    return {"ok": True, "item": public_endpoint(raw)}


@mgmt_router.put("/{endpoint_id}")
async def update_webhook(endpoint_id: str, body: WebhookUpsert) -> dict[str, Any]:
    store = get_webhook_store()
    data = body.model_dump(exclude_unset=True)
    try:
        row = store.update(endpoint_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="Webhook 不存在")
    return {"ok": True, "item": row}


@mgmt_router.delete("/{endpoint_id}")
async def delete_webhook(endpoint_id: str) -> dict[str, Any]:
    store = get_webhook_store()
    if not store.delete(endpoint_id):
        raise HTTPException(status_code=404, detail="Webhook 不存在")
    return {"ok": True, "id": endpoint_id}


@mgmt_router.post("/{endpoint_id}/regenerate-token")
async def regenerate_webhook_token(endpoint_id: str) -> dict[str, Any]:
    store = get_webhook_store()
    row = store.regenerate_token(endpoint_id)
    if not row:
        raise HTTPException(status_code=404, detail="Webhook 不存在")
    return {"ok": True, "item": row}


@mgmt_router.get("/{endpoint_id}/token")
async def reveal_webhook_token(endpoint_id: str) -> dict[str, Any]:
    store = get_webhook_store()
    tok = store.reveal_token(endpoint_id)
    if tok is None:
        raise HTTPException(status_code=404, detail="Webhook 不存在")
    return {"ok": True, "id": endpoint_id, "token": tok}


# ---------- Inbound ----------


@router.get("/health")
async def webhook_health_global(
    authorization: str | None = Header(default=None),
    x_webhook_token: str | None = Header(default=None, alias="X-Webhook-Token"),
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
) -> dict[str, Any]:
    ep = _resolve_endpoint(
        slug=None,
        authorization=authorization,
        x_webhook_token=x_webhook_token,
        x_api_key=x_api_key,
    )
    slug = ep.get("slug") or ep.get("id")
    return {
        "ok": True,
        "webhook_id": ep.get("id"),
        "name": ep.get("name"),
        "slug": slug,
        "enabled": ep.get("enabled", True),
        "session_mode": ep.get("session_mode"),
        "session_id": ep.get("session_id") or None,
        "use_tools": ep.get("use_tools", True),
        "use_memory": ep.get("use_memory", True),
        "endpoint": f"/api/webhook/{slug}/chat",
    }


@router.get("/{slug}/health")
async def webhook_health_slug(
    slug: str,
    authorization: str | None = Header(default=None),
    x_webhook_token: str | None = Header(default=None, alias="X-Webhook-Token"),
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
) -> dict[str, Any]:
    if slug in ("chat", "sessions", "health"):
        raise HTTPException(status_code=404, detail="Not found")
    ep = _resolve_endpoint(
        slug=slug,
        authorization=authorization,
        x_webhook_token=x_webhook_token,
        x_api_key=x_api_key,
    )
    return {
        "ok": True,
        "webhook_id": ep.get("id"),
        "name": ep.get("name"),
        "slug": ep.get("slug"),
        "enabled": ep.get("enabled", True),
        "session_mode": ep.get("session_mode"),
        "session_id": ep.get("session_id") or None,
        "use_tools": ep.get("use_tools", True),
        "use_memory": ep.get("use_memory", True),
        "endpoint": f"/api/webhook/{ep.get('slug')}/chat",
    }


@router.post("/chat")
async def webhook_chat(
    request: Request,
    authorization: str | None = Header(default=None),
    x_webhook_token: str | None = Header(default=None, alias="X-Webhook-Token"),
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
) -> dict[str, Any]:
    ep = _resolve_endpoint(
        slug=None,
        authorization=authorization,
        x_webhook_token=x_webhook_token,
        x_api_key=x_api_key,
    )
    payload = await _parse_payload(request)
    return await _run_chat(ep, payload)


@router.post("/{slug}/chat")
async def webhook_chat_slug(
    slug: str,
    request: Request,
    authorization: str | None = Header(default=None),
    x_webhook_token: str | None = Header(default=None, alias="X-Webhook-Token"),
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
) -> dict[str, Any]:
    if slug in ("sessions", "health"):
        raise HTTPException(status_code=404, detail="Not found")
    ep = _resolve_endpoint(
        slug=slug,
        authorization=authorization,
        x_webhook_token=x_webhook_token,
        x_api_key=x_api_key,
    )
    payload = await _parse_payload(request)
    return await _run_chat(ep, payload)


@router.get("/sessions")
async def list_webhook_session_bindings(
    authorization: str | None = Header(default=None),
    x_webhook_token: str | None = Header(default=None, alias="X-Webhook-Token"),
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
) -> dict[str, Any]:
    ep = _resolve_endpoint(
        slug=None,
        authorization=authorization,
        x_webhook_token=x_webhook_token,
        x_api_key=x_api_key,
    )
    data = _load_session_map()
    prefix = str(ep.get("id") or "") + ":"
    items = [
        {"key": k, "session_id": v}
        for k, v in sorted(data.items(), key=lambda kv: kv[0])
        if k.startswith(prefix) or not prefix
    ]
    return {"ok": True, "count": len(items), "items": items, "webhook_id": ep.get("id")}
