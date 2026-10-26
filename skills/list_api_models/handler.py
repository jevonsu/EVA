import json
import logging

logger = logging.getLogger(__name__)

DESC = (
    "向任意 OpenAI 兼容站点拉取 /models（可传 api_url/api_key，默认用设定→LLM 的默认模型凭证）。"
    "本机已保存的对话模型请用工具 llms action=list；"
    "已保存供应商的 /models 也可用 llms action=models。"
    "不要用本工具代替 llms 的增删改。"
)


async def list_models(api_url: str = "", api_key: str = "") -> str:
    """查询 OpenAI 兼容 API 可用模型列表（凭证来自参数或设定 → LLM 默认模型）。"""
    from app.services.credentials import default_llm_credentials
    from app.services.model_meta import fetch_openai_models

    creds = default_llm_credentials()
    base_url = (api_url or creds.get("base_url") or "").strip().rstrip("/")
    key = (api_key or creds.get("api_key") or "").strip()
    use_proxy = bool(str(creds.get("use_proxy") or "").strip())

    if not base_url or not key:
        return json.dumps(
            {
                "ok": False,
                "error": "缺少 API base_url 或 api_key。请传参，或先在设定 → LLM 添加默认模型。",
            },
            ensure_ascii=False,
        )

    result = await fetch_openai_models(
        base_url=base_url, api_key=key, use_proxy=use_proxy
    )
    return json.dumps(result, ensure_ascii=False)


def register(registry):
    registry.register(
        "list_api_models",
        DESC,
        list_models,
        {
            "type": "object",
            "properties": {
                "api_url": {
                    "type": "string",
                    "description": "API 中转地址（可选，默认用系统 LLM base_url）",
                },
                "api_key": {
                    "type": "string",
                    "description": "API Key（可选，默认用系统 LLM key）",
                },
            },
        },
        source="skill",
        metadata={"group": "dev", "tag": "列模型"},
    )
