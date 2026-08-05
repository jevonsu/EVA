import logging
import json
import httpx

logger = logging.getLogger(__name__)


async def list_models(api_url: str = "", api_key: str = "") -> str:
    """查询 OpenAI 兼容 API 可用模型列表（凭证来自参数 / 默认 LLM / 环境变量）。"""
    from app.services.credentials import default_llm_credentials

    creds = default_llm_credentials()
    base_url = (api_url or creds.get("base_url") or "").strip().rstrip("/")
    key = (api_key or creds.get("api_key") or "").strip()

    if not base_url or not key:
        return json.dumps(
            {
                "error": "缺少 API base_url 或 api_key。请传参，或配置默认 LLM / 环境变量 LLM_BASE_URL、LLM_API_KEY。",
            },
            ensure_ascii=False,
        )

    url = f"{base_url}/models"
    headers = {"Authorization": f"Bearer {key}"}

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                models = [m["id"] for m in data.get("data", [])]
                image_models = [
                    m
                    for m in models
                    if any(
                        k in m.lower()
                        for k in [
                            "dall",
                            "image",
                            "sd",
                            "stable",
                            "flux",
                            "midjourney",
                            "kandinsky",
                            "pixart",
                            "t2i",
                            "i2i",
                        ]
                    )
                ]
                video_models = [
                    m
                    for m in models
                    if any(
                        k in m.lower()
                        for k in ["runway", "kling", "pika", "sora", "video", "gen"]
                    )
                ]
                chat_models = [
                    m for m in models if m not in image_models and m not in video_models
                ]
                result = {
                    "total": len(models),
                    "chat_models": chat_models[:50],
                    "image_models": image_models,
                    "video_models": video_models,
                    "all_models": models,
                    "base_url": base_url,
                }
                return json.dumps(result, ensure_ascii=False, indent=2)
            return json.dumps(
                {"error": f"HTTP {resp.status_code}", "detail": resp.text[:500]},
                ensure_ascii=False,
            )
        except Exception as e:
            logger.exception("查询模型列表失败")
            return json.dumps({"error": str(e)}, ensure_ascii=False)


def register(registry):
    registry.register(
        "list_api_models",
        "查询 OpenAI 兼容 API 中转站点可用的模型列表（默认用当前 LLM 配置）。",
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
    )
