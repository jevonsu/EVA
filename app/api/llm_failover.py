"""主备模型自动切换 API。

需登录（EVA 现有会话）::

    GET  /api/llm/failover            配置（push_token 只回 push_token_set）+ 模型列表 + 状态
    PUT  /api/llm/failover            保存配置
    GET  /api/llm/failover/status     当前状态（活动模型、主模型上/下线、最近切换原因）
    POST /api/llm/failover/test       测试主模型：探测 /models + 发一条 ping（只测主模型）
    POST /api/llm/failover/reset      清除熔断状态（立即重新尝试主模型）
    POST /api/llm/failover/push_token 生成新的推送令牌（只显示这一次）
    DELETE /api/llm/failover/push_token 清除推送令牌（推送接口随即停用）
    POST /api/llm/primary             更新主模型 base_url / api_key / model（会话鉴权）

免会话、仅凭推送令牌（Kaggle 笔记本推送新隧道地址用）::

    POST /api/llm-push/primary
    Header: Authorization: Bearer <push_token>   （或 X-EVA-Push-Token: <push_token>）
    Body:   {"base_url": "https://xxx.trycloudflare.com/v1", "api_key": "...", "model": "eva-uncensored"}
    未设置令牌时该接口一律 403。

接口与日志不返回任何 API Key。
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request

from app.llm import failover as fo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm", tags=["llm-failover"])
push_router = APIRouter(prefix="/api/llm-push", tags=["llm-failover"])


def _llm_list() -> list[dict[str, Any]]:
    from app.config_store import get_config_store
    from app.llm.client import LLMClient

    out = []
    for x in get_config_store().list_llms():
        try:
            is_cli = bool(LLMClient.from_llm_config(x).is_cli)
        except Exception:
            is_cli = False
        out.append(
            {
                "id": x.get("id"),
                "name": x.get("name") or x.get("model") or x.get("id"),
                "model": x.get("model") or "",
                "host": urlparse(str(x.get("base_url") or "")).netloc,
                "enabled": x.get("enabled", True) is not False,
                "is_default": bool(x.get("is_default")),
                "is_cli": is_cli,
                "api_key_set": bool(x.get("api_key")),
            }
        )
    return out


@router.get("/failover")
async def get_failover() -> dict[str, Any]:
    return {"config": fo.public_cfg(), "llms": _llm_list(), "status": fo.status()}


@router.put("/failover")
async def put_failover(body: dict[str, Any]) -> dict[str, Any]:
    data = body.get("config", body) if isinstance(body, dict) else {}
    if not isinstance(data, dict):
        raise HTTPException(400, "配置格式错误")
    data = {k: v for k, v in data.items() if k != "push_token"}
    cfg = fo.normalize_cfg({**fo.get_cfg(), **data})
    if cfg["enabled"]:
        prow = fo.primary_row(cfg)
        if not prow:
            raise HTTPException(400, "主模型不存在或已停用")
        if not fo.backup_rows(cfg, str(prow.get("id"))):
            raise HTTPException(400, "至少需要一个可用的备用模型（且不能与主模型相同）")
    saved = fo.save_cfg(data)
    logger.info(
        "LLM failover config saved: enabled=%s primary=%s backups=%s tools_use_backup=%s",
        saved["enabled"], saved["primary_llm_id"] or "(默认模型)", saved["backup_llm_ids"], saved["tools_use_backup"],
    )
    return {"ok": True, "config": fo.public_cfg(saved), "status": fo.status()}


@router.get("/failover/status")
async def get_status() -> dict[str, Any]:
    return fo.status()


@router.post("/failover/reset")
async def reset_breaker() -> dict[str, Any]:
    fo.reset_runtime(keep_health=False)
    return {"ok": True, "status": fo.status()}


@router.post("/failover/test")
async def test_primary() -> dict[str, Any]:
    cfg = fo.get_cfg()
    prow = fo.primary_row(cfg)
    if not prow:
        raise HTTPException(400, "未找到主模型")
    probe = await fo.probe(prow, cfg)
    chat: dict[str, Any]
    cli = fo.member_client(prow, "primary", cfg)
    t0 = time.time()
    if not cli.is_configured:
        chat = {"ok": False, "error": "配置不完整（缺 base_url / model / Key）"}
    else:
        import asyncio

        try:
            res = await asyncio.wait_for(
                cli._raw_chat([{"role": "user", "content": "ping"}], temperature=0),
                timeout=cfg["response_timeout"],
            )
            fo.check_result(res)
            chat = {"ok": True, "ms": int((time.time() - t0) * 1000), "reply": str(res.get("content") or "")[:120], "model": res.get("model") or prow.get("model")}
        except Exception as exc:  # noqa: BLE001
            _, _, reason = fo.classify(exc)
            chat = {"ok": False, "ms": int((time.time() - t0) * 1000), "error": fo.scrub(reason, str(prow.get("api_key") or ""))}
    if chat.get("ok"):
        fo._mark_ok(prow)
    elif cfg.get("enabled") and not probe.get("ok"):
        fo._mark_fail(prow, "测试失败：" + str(chat.get("error") or probe.get("error") or ""), trip=True, cfg=cfg, is_primary=True)
    return {"ok": bool(chat.get("ok")), "primary": {"id": prow.get("id"), "name": fo._name(prow)}, "probe": probe, "chat": chat, "status": fo.status()}


@router.post("/failover/push_token")
async def make_push_token() -> dict[str, Any]:
    tok = fo.new_push_token()
    logger.info("LLM failover: new push token generated")
    return {"ok": True, "push_token": tok}


@router.delete("/failover/push_token")
async def clear_push_token() -> dict[str, Any]:
    cfg = fo.get_cfg()
    cfg["push_token"] = ""
    from app.config_store import get_config_store

    get_config_store().update_section(fo.CFG_KEY, fo.normalize_cfg(cfg))
    return {"ok": True}


async def _apply_primary_update(body: dict[str, Any], *, source: str) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise HTTPException(400, "格式错误")
    base = str(body.get("base_url") or "").strip().rstrip("/")
    key = body.get("api_key")
    model = str(body.get("model") or "").strip()
    llm_id = str(body.get("llm_id") or "").strip()
    if not base:
        raise HTTPException(400, "缺少 base_url")
    pu = urlparse(base)
    if pu.scheme not in ("http", "https") or not pu.netloc:
        raise HTTPException(400, "base_url 必须是 http(s):// 开头的完整地址")
    if len(base) > 300 or (isinstance(key, str) and len(key) > 400) or len(model) > 120:
        raise HTTPException(400, "字段过长")
    from app.config_store import get_config_store

    store = get_config_store()
    cfg = fo.get_cfg()
    row = store.get_llm(llm_id) if llm_id else fo.primary_row(cfg)
    if not row:
        raise HTTPException(404, "未找到主模型（请先在设定→模型添加，并在 主备切换 里选为主模型）")
    patch: dict[str, Any] = {"id": row["id"], "base_url": base}
    if isinstance(key, str) and key.strip():
        patch["api_key"] = key.strip()
    if model:
        patch["model"] = model
    store.upsert_llm(patch)
    fo.reset_runtime(keep_health=True)
    h = fo.health(str(row["id"]))
    h.fails = 0
    h.down_until = 0.0
    h.last_error = ""
    try:
        from app.agent.core import get_agent
        from app.llm.client import get_llm_client, reset_llm_client

        reset_llm_client()
        get_agent().llm = get_llm_client()
    except Exception:
        logger.exception("LLM client refresh after primary update failed")
    new_row = store.get_llm(str(row["id"])) or row
    logger.info("LLM failover: primary %s updated via %s -> host %s, model %s", fo._name(new_row), source, pu.netloc, new_row.get("model"))
    fo._event("update", f"{fo._name(new_row)} 地址已更新（{source}）：{pu.netloc}")
    probe = {"skipped": True}
    if body.get("probe", True) is not False:
        probe = await fo.probe(new_row, cfg)
        if probe.get("ok"):
            fo._mark_ok(new_row)
    return {"ok": True, "llm_id": row["id"], "host": pu.netloc, "model": new_row.get("model"), "probe": probe}


@router.post("/primary")
async def update_primary(body: dict[str, Any]) -> dict[str, Any]:
    return await _apply_primary_update(body, source="设定页/API")


_PUSH_FAILS: list[float] = []


@push_router.post("/primary")
async def push_primary(request: Request) -> dict[str, Any]:
    now = time.time()
    _PUSH_FAILS[:] = [t for t in _PUSH_FAILS if now - t < 300]
    if len(_PUSH_FAILS) >= 10:
        raise HTTPException(429, "失败次数过多，请 5 分钟后再试")
    authz = (request.headers.get("authorization") or "").strip()
    tok = authz[7:].strip() if authz.lower().startswith("bearer ") else ""
    tok = tok or (request.headers.get("x-eva-push-token") or "").strip()
    if not fo.get_cfg().get("push_token"):
        raise HTTPException(403, "未设置推送令牌（设定 → 模型路由 → 主备切换 里生成）")
    if not fo.check_push_token(tok):
        _PUSH_FAILS.append(now)
        logger.warning("LLM failover: push rejected (bad token) from %s", request.client.host if request.client else "?")
        raise HTTPException(403, "推送令牌无效")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "需要 JSON 请求体")
    return await _apply_primary_update(body, source="推送接口")
