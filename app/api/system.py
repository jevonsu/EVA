"""Health / system endpoints."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from fastapi import APIRouter
from fastapi.responses import Response

from app import __version__
from app.config import get_settings
from app.mcp.client import get_mcp_manager
from app.models.schemas import HealthResponse
from app.scheduler.manager import get_scheduler
from app.tools.registry import get_tool_registry

router = APIRouter(tags=["system"])

# Simple SVG icon so browsers stop 404-ing /favicon.ico
_FAVICON_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="6" fill="#111827"/>
  <text x="16" y="22" text-anchor="middle" font-size="16" font-family="Segoe UI,Arial,sans-serif" fill="#22d3ee">AI</text>
</svg>
"""


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    tasks = await get_scheduler().list_tasks()
    agent_name = settings.agent_name
    provider = settings.llm_provider
    model = settings.llm_model
    try:
        from app.config_store import get_config_store
        agent_name = get_config_store().get_agent().get("name") or agent_name
    except Exception:
        logger.warning("Failed to load agent name from config store", exc_info=True)

    try:
        from app.llm.client import get_llm_client
        llm = get_llm_client()
        provider = llm.provider
        model = llm.model
    except Exception:
        logger.warning("Failed to get LLM client, using defaults: %s/%s", provider, model)
    return HealthResponse(
        status="ok",
        agent=agent_name,
        version=__version__,
        llm_provider=provider,
        llm_model=model,
        tools=len(get_tool_registry().list_tools()),
        mcp_servers=get_mcp_manager().connected_count,
        scheduled_tasks=len(tasks),
    )


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(content=_FAVICON_SVG, media_type="image/svg+xml")


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

