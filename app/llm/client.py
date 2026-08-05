"""Multi-provider OpenAI-compatible LLM client (xAI, OpenAI, custom)."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "xai": {"base_url": "https://api.x.ai/v1", "model": "grok-4.5"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o"},
    "custom": {"base_url": "http://localhost:11434/v1", "model": "llama3.2"},
}


class LLMClient:
    """Async wrapper; active provider comes from runtime config when available."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        provider: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        llm_id: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm_id = llm_id

        # Prefer explicit args, then config store default, then env settings
        cfg = self._load_default_from_store()
        self.provider = (provider or (cfg or {}).get("provider") or self.settings.llm_provider or "xai").lower()
        defaults = PROVIDER_DEFAULTS.get(self.provider, {})

        self.base_url = (
            base_url
            or (cfg or {}).get("base_url")
            or self.settings.llm_base_url
            or defaults.get("base_url", "")
        )
        self.model = (
            model
            or (cfg or {}).get("model")
            or self.settings.llm_model
            or defaults.get("model", "grok-4.5")
        )
        self.api_key = (
            api_key
            if api_key is not None
            else (cfg or {}).get("api_key") or self.settings.llm_api_key or ""
        )
        self.llm_id = llm_id or (cfg or {}).get("id")

        # Grok Build / xAI：优先用本机 `grok login` 的 OAuth（~/.grok/auth.json）
        # 避免配置里写死的 JWT 过期；id=grok-build 或已有 eyJ… token 时自动刷新
        if self.provider == "xai":
            live = self._grok_oauth_token()
            if live and (
                (self.llm_id or "") == "grok-build"
                or not (self.api_key or "").strip()
                or str(self.api_key).startswith("eyJ")
            ):
                self.api_key = live

        self._client = AsyncOpenAI(
            api_key=self.api_key or "not-set",
            base_url=self.base_url,
            timeout=120.0,
        )
        # optional env fallback
        self._fallback: AsyncOpenAI | None = None
        self._fallback_model: str | None = None
        if self.settings.llm_fallback_api_key and self.settings.llm_fallback_base_url:
            self._fallback = AsyncOpenAI(
                api_key=self.settings.llm_fallback_api_key,
                base_url=self.settings.llm_fallback_base_url,
            )
            self._fallback_model = self.settings.llm_fallback_model or self.model

    @staticmethod
    def _load_default_from_store() -> dict[str, Any] | None:
        try:
            from app.config_store import get_config_store

            return get_config_store().get_default_llm()
        except Exception:
            return None

    @staticmethod
    def _grok_oauth_token() -> str:
        """Read Grok Build CLI OAuth access token from ~/.grok/auth.json."""
        try:
            from pathlib import Path
            import json

            path = Path.home() / ".grok" / "auth.json"
            if not path.is_file():
                return ""
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return ""
            for entry in data.values():
                if not isinstance(entry, dict):
                    continue
                tok = (
                    entry.get("key")
                    or entry.get("access_token")
                    or entry.get("token")
                    or ""
                )
                tok = str(tok).strip()
                if tok:
                    return tok
        except Exception:
            logger.debug("Read ~/.grok/auth.json failed", exc_info=True)
        return ""

    @classmethod
    def from_llm_config(cls, llm: dict[str, Any]) -> "LLMClient":
        return cls(
            provider=llm.get("provider"),
            base_url=llm.get("base_url"),
            api_key=llm.get("api_key"),
            model=llm.get("model"),
            llm_id=llm.get("id"),
        )

    @property
    def has_api_key(self) -> bool:
        key = self.api_key
        return bool(key and key not in ("", "not-set", "your-key-here"))

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice

        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            if self._fallback is None:
                raise
            logger.warning("Primary LLM failed (%s), trying fallback", exc)
            kwargs["model"] = self._fallback_model or self.model
            resp = await self._fallback.chat.completions.create(**kwargs)

        choice = resp.choices[0]
        msg = choice.message
        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "{}",
                    },
                }
                for tc in msg.tool_calls
            ]

        usage: dict[str, Any] = {}
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
            }

        return {
            "role": "assistant",
            "content": msg.content,
            "tool_calls": tool_calls,
            "finish_reason": choice.finish_reason,
            "model": resp.model,
            "usage": usage,
        }

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=model or self.model,
            messages=messages,
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    async def test_connection(self) -> dict[str, Any]:
        """Minimal request to verify credentials / endpoint."""
        try:
            result = await self.chat(
                [{"role": "user", "content": "Reply with exactly: ok"}],
                temperature=0,
            )
            return {
                "ok": True,
                "model": result.get("model") or self.model,
                "reply": (result.get("content") or "")[:200],
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "model": self.model}


_llm: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm


def reset_llm_client() -> None:
    global _llm
    _llm = None