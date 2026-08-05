import json, logging
logger = logging.getLogger(__name__)

def register(registry):
    async def handler() -> str:
        try:
            from app.services.runtime import rebuild_runtime
            s = await rebuild_runtime()
            return json.dumps({"ok": True, "tools": s.get("tools"), "skills": s.get("skill_tools"), "llm": s.get("llm")}, ensure_ascii=False)
        except Exception as e:
            logger.exception("reload_runtime failed")
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    registry.register("reload_runtime",
        "Reload all tools, skills, MCP, and LLM from disk. Call after manually modifying handler.py files. No parameters needed.",
        handler,
        {"type": "object", "properties": {}},
        source="skill")