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


def _clean_api_key(api_key: str) -> str:
    """Strip paste noise (spaces, newlines, zero-width) from API keys."""
    key = (api_key or "").strip()
    if not key:
        return ""
    # common copy-paste junk
    for ch in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u00a0"):
        key = key.replace(ch, "")
    # keys should not contain whitespace mid-string
    key = "".join(key.split())
    return key.strip()


def _models_candidate_urls(base_url: str) -> list[str]:
    """OpenAI-compatible /models URL variants (with/without /v1)."""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return []
    urls: list[str] = [f"{base}/models"]
    # if user omitted /v1, many gateways still expose /v1/models
    if not base.lower().endswith("/v1"):
        urls.append(f"{base}/v1/models")
    # if user put .../v1, also try parent /models (DeepSeek accepts both)
    if base.lower().endswith("/v1"):
        root = base[: -len("/v1")]
        if root:
            urls.append(f"{root}/models")
    # de-dupe
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _auth_error_message(status: int, body: str) -> str:
    text = (body or "").strip()
    low = text.lower()
    if status in (401, 403):
        if "invalid" in low or "authentication" in low or "api key" in low:
            return (
                f"HTTP {status}：API Key 无效或无权访问。"
                "请重新从服务商控制台复制 Key，粘贴后先点「保存」再「拉取模型」。"
            )
        return f"HTTP {status}：鉴权失败，请检查 API Key 是否正确、是否已保存。"
    return f"HTTP {status}"


def _network_error_hint(exc: BaseException) -> str:
    """Human-readable network failure (proxy / DNS / firewall / encoding)."""
    msg = str(exc) or type(exc).__name__
    # Avoid second-order encode errors when building UI text
    try:
        msg.encode("utf-8")
    except Exception:
        msg = repr(exc)
    low = msg.lower()
    tips: list[str] = []
    if "ascii" in low and "codec" in low:
        tips.append("请求头或代理地址含非英文导致编码失败，已改为默认直连")
        tips.append("请确认 API Key / Base URL 为纯英文，勿含中文空格或引号")
    if (
        "all connection attempts failed" in low
        or "connecterror" in low
        or "connection refused" in low
        or "10061" in low
    ):
        tips.append("连接失败：请检查网络；默认不走系统代理")
    if "timed out" in low or "timeout" in low:
        tips.append("连接超时：检查网络/VPN，或 Base URL 是否可达")
    if "name or service not known" in low or "getaddrinfo" in low or "dns" in low:
        tips.append("DNS 解析失败：检查 Base URL 主机名")
    if not tips:
        tips.append("请检查本机网络、防火墙与 Base URL")
    return f"网络错误: {msg} — " + "；".join(tips)


def resolve_app_proxy_url() -> str:
    """Proxy URL from Eva settings / integrations.http only (never system env)."""
    try:
        from app.config import get_settings

        p = (get_settings().proxy_url or "").strip()
        if p:
            return p
    except Exception:
        pass
    try:
        from app.config_store import get_config_store

        integ = (get_config_store().get_raw().get("integrations") or {}).get("http") or {}
        if isinstance(integ, dict):
            p = str(integ.get("proxy_url") or "").strip()
            if p:
                return p
    except Exception:
        pass
    # Explicit PROXY_URL env only (not HTTP_PROXY / system proxy)
    try:
        import os

        p = (os.environ.get("PROXY_URL") or "").strip()
        if p:
            return p
    except Exception:
        pass
    return ""


def _http_client_strategies(*, use_proxy: bool = False) -> list[tuple[str, dict[str, Any]]]:
    """Per-LLM: use_proxy=False → direct only; True → Eva-configured proxy."""
    if not use_proxy:
        return [("direct", {"trust_env": False})]
    p = resolve_app_proxy_url()
    if not p:
        logger.warning("LLM use_proxy=True but no proxy configured; falling back to direct")
        return [("direct", {"trust_env": False})]
    try:
        p.encode("ascii")
    except UnicodeEncodeError:
        logger.warning("ignore non-ascii proxy_url; falling back to direct")
        return [("direct", {"trust_env": False})]
    return [
        ("app_proxy", {"trust_env": False, "proxy": p}),
        # if configured proxy dead, still try direct once
        ("direct_fallback", {"trust_env": False}),
    ]


def _header_safe_api_key(key: str) -> str:
    """HTTP Authorization must be latin-1; strip illegal chars from paste junk."""
    key = _clean_api_key(key)
    try:
        key.encode("latin-1")
        return key
    except UnicodeEncodeError:
        # Keep only latin-1 codepoints (API keys are ASCII in practice)
        return key.encode("latin-1", "ignore").decode("latin-1")


def _parse_models_payload(data: Any, *, base: str) -> list[dict[str, Any]] | None:
    raw_list = data.get("data") if isinstance(data, dict) else data
    if not isinstance(raw_list, list):
        return None
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
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for row in models:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        uniq.append(row)
    uniq.sort(key=lambda x: (x.get("modality") or "", x["id"].lower()))
    return uniq


async def fetch_openai_models(
    *,
    base_url: str,
    api_key: str,
    timeout: float = 30.0,
    use_proxy: bool = False,
) -> dict[str, Any]:
    """GET {base_url}/models — tries URL variants; proxy only if use_proxy=True."""
    base = (base_url or "").strip().rstrip("/")
    key = _header_safe_api_key(api_key)
    if not base:
        return {"ok": False, "error": "请先填写 Base URL"}
    if not key:
        return {"ok": False, "error": "请先填写 API Key（编辑已有项时可用已保存的 Key）"}
    try:
        base.encode("ascii")
    except UnicodeEncodeError:
        return {
            "ok": False,
            "error": "Base URL 不能包含中文或特殊字符，请使用 https://api.xxx.com 形式",
        }
    if use_proxy and not resolve_app_proxy_url():
        return {
            "ok": False,
            "error": (
                "已勾选「使用代理」，但未配置代理地址。"
                "请到设定 → 集成 → HTTP 网络填写代理，或取消勾选后直连。"
            ),
        }

    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": "Eva-LLM/1.0",
    }
    urls = _models_candidate_urls(base)
    strategies = _http_client_strategies(use_proxy=use_proxy)
    last_err = ""
    last_detail = ""
    tried: list[str] = []

    try:
        for strat_name, client_kw in strategies:
            kw: dict[str, Any] = {
                "timeout": timeout,
                "follow_redirects": True,
                "trust_env": False,  # never inherit broken system proxy by default
                **client_kw,
            }
            kw["trust_env"] = bool(kw.get("trust_env", False))
            if not kw.get("proxy"):
                kw.pop("proxy", None)
            try:
                async with httpx.AsyncClient(**kw) as client:
                    for url in urls:
                        tag = f"{strat_name}:{url}"
                        tried.append(tag)
                        try:
                            resp = await client.get(url, headers=headers)
                        except Exception as exc:
                            last_err = _network_error_hint(exc)
                            last_detail = str(exc)
                            logger.warning(
                                "fetch models network error [%s] url=%s err=%s",
                                strat_name,
                                url,
                                exc,
                            )
                            continue
                        if resp.status_code != 200:
                            last_err = _auth_error_message(
                                resp.status_code, resp.text or ""
                            )
                            last_detail = (resp.text or "")[:400]
                            if resp.status_code in (401, 403):
                                return {
                                    "ok": False,
                                    "error": last_err,
                                    "detail": last_detail,
                                    "url": url,
                                    "auth_error": True,
                                    "via": strat_name,
                                }
                            continue
                        try:
                            data = resp.json()
                        except Exception:
                            last_err = "响应不是 JSON"
                            last_detail = (resp.text or "")[:200]
                            continue
                        uniq = _parse_models_payload(data, base=base)
                        if uniq is None:
                            last_err = "响应格式无法解析 models 列表"
                            last_detail = str(data)[:200]
                            continue
                        return {
                            "ok": True,
                            "base_url": base,
                            "source_url": url,
                            "count": len(uniq),
                            "models": uniq,
                            "via": strat_name,
                        }
            except Exception as exc:
                last_err = _network_error_hint(exc)
                last_detail = str(exc)
                logger.warning("fetch models client [%s] failed: %s", strat_name, exc)
                continue

        return {
            "ok": False,
            "error": last_err or "未能从 Base URL 拉取模型列表",
            "detail": last_detail,
            "tried": tried[:20],
        }
    except Exception as e:
        logger.exception("fetch models failed")
        return {"ok": False, "error": _network_error_hint(e)}


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
    out["use_proxy"] = bool(out.get("use_proxy"))
    return out
