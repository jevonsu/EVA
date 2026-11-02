import json
import logging

logger = logging.getLogger(__name__)

DESC = (
    "热重载：从磁盘重新加载工具、技能、MCP 与 LLM。"
    "手动改过 handler.py、导入技能或改过设定后调用。无需参数。"
    "改 app/ 源码仍须重启进程，本工具不能代替重启。"
)


def register(registry):
    async def handler(reason: str = "") -> str:
        if reason:
            logger.info("reload_runtime: %s", reason[:200])
        try:
            from app.services.runtime import rebuild_runtime

            s = await rebuild_runtime()
            return json.dumps(
                {
                    "ok": True,
                    "tools": s.get("tools"),
                    "skills": s.get("skill_tools"),
                    "llm": s.get("llm"),
                },
                ensure_ascii=False,
            )
        except Exception as e:
            logger.exception("reload_runtime failed")
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    registry.register(
        "reload_runtime",
        DESC,
        handler,
        {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "可选：重载原因，仅写日志；可省略（本技能无必填参数）",
                }
            },
            "required": [],
        },
        source="skill",
        metadata={"group": "dev", "tag": "热重载"},
    )
