"""Apply runtime config: rebuild LLM client, tools, skills, MCP."""

from __future__ import annotations

import logging
from typing import Any

from app.agent.core import Agent, get_agent
from app.config_store import get_config_store
from app.llm.client import LLMClient, get_llm_client, reset_llm_client
from app.mcp.client import get_mcp_manager
from app.services.custom_tools import register_custom_tools
from app.services.skills import register_skills
from app.tools.builtin import register_builtin_tools
from app.tools.registry import ToolRegistry, get_tool_registry, reset_tool_registry

logger = logging.getLogger(__name__)


def apply_tool_filters(registry: ToolRegistry | None = None) -> None:
    """Unregister disabled tools (keep them out of openai schema)."""
    registry = registry or get_tool_registry()
    disabled = get_config_store().disabled_tools()
    for name in list(disabled):
        if registry.get(name):
            # mark via unregister — they can be re-registered on full rebuild
            registry.unregister(name)


async def rebuild_runtime(*, reconnect_mcp: bool = False) -> dict[str, Any]:
    """
    Rebuild tool registry + LLM client from config store.
    MCP reconnect is optional (heavier).
    """
    store = get_config_store()
    store.load()

    # rebuild tools from scratch
    reset_tool_registry()
    registry = get_tool_registry()
    register_builtin_tools(registry)
    custom_n = register_custom_tools(registry)
    skill_n = register_skills(registry)
    apply_tool_filters(registry)

    # rebuild LLM
    reset_llm_client()
    llm = get_llm_client()

    # point global agent at new instances
    agent = get_agent()
    agent.llm = llm
    agent.tools = registry
    agent_cfg = store.get_agent()
    # agent reads system prompt via store in chat(); also patch settings fields used as fallback
    if agent_cfg.get("max_tool_rounds"):
        agent.settings.max_tool_rounds = int(agent_cfg["max_tool_rounds"])
    if agent_cfg.get("max_history_messages"):
        agent.settings.max_history_messages = int(agent_cfg["max_history_messages"])
    if agent_cfg.get("name"):
        agent.settings.agent_name = agent_cfg["name"]

    mcp = get_mcp_manager()
    if reconnect_mcp:
        await mcp.shutdown()
        # fresh stack
        from app.mcp.client import MCPManager, reset_mcp_manager

        reset_mcp_manager()
        mcp = get_mcp_manager()
        await mcp.start(registry)
    else:
        # re-register MCP tools if sessions still alive
        if mcp.connected_count:
            try:
                await mcp.reregister_tools(registry)
            except Exception:
                logger.exception("Failed to re-register MCP tools")

    try:
        from app.api.config import invalidate_tools_catalog_cache

        invalidate_tools_catalog_cache()
    except Exception:
        logger.debug("tools catalog cache invalidate skipped", exc_info=True)

    summary = {
        "tools": len(registry.list_tools()),
        "custom_tools": custom_n,
        "skill_tools": skill_n,
        "mcp_servers": mcp.connected_count,
        "llm": {
            "provider": llm.provider,
            "model": llm.model,
            "has_api_key": llm.has_api_key,
        },
        "agent": store.get_agent().get("name"),
    }
    logger.info("Runtime rebuilt: %s", summary)
    return summary
