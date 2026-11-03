"""Health / system endpoints."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from fastapi import APIRouter
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



# ---- 在线更新（Web 前端，三平台） ----
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool


async def _require_admin(request: Request) -> None:
    from app.api.config import _settings_actor

    actor = await _settings_actor(request)
    if not actor:
        raise HTTPException(status_code=401, detail="未登录")
    role = str(actor.get("role") or "")
    if role and role != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以更新")


@router.get("/api/update/status")
async def update_status(request: Request, force: bool = False) -> dict:
    from app.services import online_update as ou

    try:
        return await run_in_threadpool(ou.web_status, force=force)
    except Exception as extra:
        return {"ok": False, "newer": False, "error": str(extra)}


@router.post("/api/update/apply")
async def update_apply(request: Request) -> dict:
    await _require_admin(request)
    from app.services import online_update as ou

    try:
        return await run_in_threadpool(ou.web_apply)
    except Exception as extra:
        logger.warning("web update failed", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新失败：{extra}")
