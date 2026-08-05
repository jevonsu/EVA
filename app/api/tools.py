"""Tool listing endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import ToolInfo
from app.tools.registry import get_tool_registry

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("", response_model=list[ToolInfo])
async def list_tools() -> list[ToolInfo]:
    from app.tools.tool_meta import decorate_description, display_name_for

    registry = get_tool_registry()
    return [
        ToolInfo(
            name=t.name,
            description=decorate_description(t.name, t.description),
            parameters=t.parameters,
            source=t.source,
            display_name=display_name_for(t.name),
        )
        for t in registry.list_tools()
    ]
