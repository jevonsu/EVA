"""Health / system endpoints."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Body
from fastapi.responses import FileResponse, Response

from app import __version__
from app.branding import logo_png
from app.config import get_settings
from app.mcp.client import get_mcp_manager
from app.models.schemas import HealthResponse
from app.scheduler.manager import get_scheduler
from app.tools.registry import get_tool_registry

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    tasks = await get_scheduler().list_tasks()
    agent_name = settings.agent_name
    provider = ""
    model = ""
    llm_configured = False
    try:
        from app.config_store import get_config_store
        agent_name = (
            str(get_config_store().get_agent().get("name") or "").strip()
            or "Eva"
        )
    except Exception:
        logger.warning("Failed to load agent name from config store", exc_info=True)

    try:
        from app.llm.client import get_llm_client
        llm = get_llm_client()
        provider = llm.provider or ""
        model = llm.model or ""
        llm_configured = bool(llm.is_configured)
    except Exception:
        logger.warning("Failed to get LLM client", exc_info=True)
    return HealthResponse(
        status="ok",
        agent=agent_name,
        version=__version__,
        llm_provider=provider,
        llm_model=model,
        llm_configured=llm_configured,
        tools=len(get_tool_registry().list_tools()),
        mcp_servers=get_mcp_manager().connected_count,
        scheduled_tasks=len(tasks),
    )


@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    path = logo_png()
    if path.is_file():
        return FileResponse(path, media_type="image/png")
    return Response(status_code=204)


@router.get("/api/system/update")
async def update_status() -> dict:
    from app.services.online_update import channel_public, check, local_info

    try:
        return check(force=False)
    except Exception as extra:
        return {
            "ok": False,
            "error": str(extra),
            "local": local_info(),
            "channel": channel_public(),
        }


@router.post("/api/system/update/check")
async def update_check() -> dict:
    from app.services.online_update import channel_public, check, local_info

    try:
        return check(force=True)
    except Exception as extra:
        return {
            "ok": False,
            "error": str(extra),
            "local": local_info(),
            "channel": channel_public(),
        }


@router.put("/api/system/update/channel")
async def update_channel(body: dict = Body(default={})) -> dict:
    from app.services.online_update import channel_public, save_channel

    payload = body if isinstance(body, dict) else {}
    repo = payload.get("repo")
    token = payload.get("token")
    save_channel(
        repo=None if repo is None else str(repo),
        token=None if token is None else str(token),
    )
    return {"ok": True, "channel": channel_public()}


@router.post("/api/system/update/download")
async def update_download() -> dict:
    from app.services.online_update import download_and_stage, local_info

    try:
        return download_and_stage(force=True)
    except Exception as extra:
        return {"ok": False, "error": str(extra), "local": local_info()}


@router.post("/api/system/update/apply")
async def update_apply() -> dict:
    """Download latest source zip and overlay program files. data/ workspace/ .env stay."""
    from app.services.online_update import apply_now, download_and_stage, local_info

    try:
        staged = download_and_stage(force=True)
        if not staged.get("downloaded") and not staged.get("newer"):
            return staged
        try:
            applied = apply_now(force=True)
            return {
                **staged,
                **applied,
                "replaced": True,
                "message": applied.get("pip")
                or "程序文件已替换。请在启动器停止后重新启动 Eva。data / 工作区 / .env 未改动。",
            }
        except RuntimeError as extra:
            msg = str(extra)
            if "正在运行" in msg:
                return {
                    **staged,
                    "ok": True,
                    "replaced": False,
                    "pending": True,
                    "error": None,
                    "message": msg + " 更新包已下好，停止服务后在启动器点「更新」。",
                }
            raise
    except Exception as extra:
        return {"ok": False, "error": str(extra), "local": local_info()}


@router.get("/api")
async def api_info() -> dict:
    """Machine-readable service info (UI is served at /)."""
    return {
        "name": get_settings().agent_name,
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
        "ui": "/",
    }

