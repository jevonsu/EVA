"""Tool listing endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import ToolInfo
from app.tools.registry import get_tool_registry

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("", response_model=list[ToolInfo])
async def list_tools() -> list[ToolInfo]:
    from app.api.config import _safe_parameters
    from app.tools.tool_meta import decorate_description, display_name_for

    registry = get_tool_registry()
    out: list[ToolInfo] = []
    for t in registry.list_tools():
        try:
            desc = t.description if isinstance(t.description, str) else str(t.description or "")
            src = str(t.source or "builtin")
            out.append(
                ToolInfo(
                    name=str(t.name or ""),
                    description=decorate_description(str(t.name or ""), desc),
                    parameters=_safe_parameters(t.parameters),
                    source=src or "builtin",
                    display_name=display_name_for(str(t.name or "")),
                )
            )
        except Exception:
            continue
    return out
