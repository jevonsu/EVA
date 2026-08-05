"""LLM model list + modality classification helpers."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.credentials import looks_like_vision_model

logger = logging.getLogger(__name__)


def classify_model_modality(
    model: str, *, name: str = "", base_url: str = ""
) -> dict[str, str]:
    """Return modality tag for UI: multimodal | text | image | video."""
    blob = f"{model} {name} {base_url}".lower()
    if any(
        k in blob
        for k in (
            "dall-e",
            "dall·e",
            "stable-diffusion",
            "flux",
            "midjourney",
            "imagen",
            "t2i",
            "image-gen",
            "gpt-image",
        )
    ):
        return {
            "modality": "image",
            "label": "生图",
            "hint": "偏图像生成，不一定适合对话/工具调用",
        }
    if any(
        k in blob
        for k in ("sora", "runway", "kling", "pika", "luma", "video", "gen-3", "gen3")
    ) and "chat" not in blob:
        return {
            "modality": "video",
            "label": "视频",
            "hint": "偏视频生成",
        }
    if looks_like_vision_model(model, base_url=base_url, name=name):
        return {
            "modality": "multimodal",
            "label": "全模态",
            "hint": "支持文本 + 识图（多模态）",
        }
    return {
        "modality": "text",
        "label": "文本",
        "hint": "文本对话/工具调用；识图请另配 Vision 模型",
    }


async def fetch_openai_models(
    *,
    base_url: str,
    api_key: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """GET {base_url}/models — OpenAI-compatible."""
    base = (base_url or "").strip().rstrip("/")
    key = (api_key or "").strip()
    if not base:
        return {"ok": False, "error": "请先填写 Base URL"}
    if not key:
        return {"ok": False, "error": "请先填写 API Key（编辑已有项时可用已保存的 Key）"}

    url = f"{base}/models"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            return {
                "ok": False,
                "error": f"HTTP {resp.status_code}",
                "detail": (resp.text or "")[:400],
            }
        data = resp.json()
        raw_list = data.get("data") if isinstance(data, dict) else data
        if not isinstance(raw_list, list):
            return {"ok": False, "error": "响应格式无法解析 models 列表"}
        models: list[dict[str, Any]] = []
        for m in raw_list:
            if isinstance(m, str):
                mid = m
            elif isinstance(m, dict):
                mid = str(m.get("id") or m.get("model") or "").strip()
            else:
                continue
            if not mid:
                continue
            mod = classify_model_modality(mid, base_url=base)
            models.append(
                {
                    "id": mid,
                    "modality": mod["modality"],
                    "modality_label": mod["label"],
                    "modality_hint": mod["hint"],
                }
            )
        # de-dupe by id, stable
        seen: set[str] = set()
        uniq: list[dict[str, Any]] = []
        for row in models:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            uniq.append(row)
        uniq.sort(key=lambda x: (x.get("modality") or "", x["id"].lower()))
        return {
            "ok": True,
            "base_url": base,
            "count": len(uniq),
            "models": uniq,
        }
    except Exception as e:
        logger.exception("fetch models failed")
        return {"ok": False, "error": str(e)}


def enrich_llm_public(llm: dict[str, Any]) -> dict[str, Any]:
    """Add modality fields for list/card UI."""
    out = dict(llm)
    mod = classify_model_modality(
        str(out.get("model") or ""),
        name=str(out.get("name") or ""),
        base_url=str(out.get("base_url") or ""),
    )
    out["modality"] = mod["modality"]
    out["modality_label"] = mod["label"]
    out["modality_hint"] = mod["hint"]
    return out
