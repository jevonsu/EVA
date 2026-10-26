"""OpenAI-compatible LLM client.

Chat only uses LLMs in ``data/config.json`` → ``llms``.
Fresh install ships a DeepSeek template with an empty API Key.
No silent fallbacks to ``.env`` or ``~/.grok/auth.json``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, AsyncIterator

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_NO_TEMPERATURE = re.compile(
    r"(?i)(\bo1\b|\bo3\b|\bo4\b|gpt-5|gpt5|reasoner|reasoning)"
)


def _sanitize_api_key(api_key: str) -> str:
    from app.services.model_meta import _clean_api_key

    return _clean_api_key(api_key or "")


def _explain_llm_http_error(exc: BaseException) -> RuntimeError:
    """Turn OpenAI/gateway HTTP errors into a short Chinese action."""
    status = int(getattr(exc, "status_code", 0) or 0)
    raw = str(exc) or type(exc).__name__
    low = raw.lower()
    auth = status in (401, 403) or any(
        s in low
        for s in (
            "authentication",
            "invalid_api_key",
            "invalid api key",
            "api key is invalid",
            "incorrect api key",
            "unauthorized",
        )
    )
    if auth:
        return RuntimeError(
            "模型 API Key 无效或无权访问。"
            "请打开设定 → 模型，选中当前默认项，把完整 Key 重新粘贴进去再保存"
            "（不要粘带星号的掩码）。中转站请确认 Key 未过期、套餐未停。"
        )
    if status == 429 or "rate limit" in low or "quota" in low:
        return RuntimeError("模型额度或频率已用尽（429）。请稍后再试，或换一条模型。")
    if status in (502, 503, 504) or "bad gateway" in low:
        return RuntimeError(f"模型服务暂时不可用（HTTP {status or '网关错误'}）。请稍后重试。")
    snippet = raw.replace("\n", " ").strip()
    if len(snippet) > 240:
        snippet = snippet[:240] + "…"
    return RuntimeError(f"调用模型失败：{snippet}")

# UI form hints only — never auto-selected as the active chat model
PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "xai": {"base_url": "https://api.x.ai/v1", "model": "grok-4.5"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o"},
    "custom": {"base_url": "http://localhost:11434/v1", "model": "llama3.2"},
}


def infer_llm_transport(row: dict[str, Any] | None) -> str:
    """Decide api vs cli for a stored or form LLM row.

    Explicit ``cli`` always wins. Empty/unknown transport infers from
    ``cli_command``. Explicit ``api`` stays API unless the row has a CLI
    command and no API key — pydantic/UI often default transport to api,
    which would otherwise treat a CLI form as an incomplete HTTP LLM.
    """
    data = row if isinstance(row, dict) else {}
    transport = str(data.get("transport") or "").strip().lower()
    provider = str(data.get("provider") or "").strip().lower()
    cmd = str(data.get("cli_command") or "").strip()
    key = str(data.get("api_key") or "").strip()
    base = str(data.get("base_url") or "").strip()
    recovered, _ = recover_cli_command(data)
    if transport == "cli" or provider == "cli":
        return "cli"
    if cmd:
        if transport == "api" and key:
            return "api"
        return "cli"
    # Older save dropped cli_* and stored Grok Build as an empty API row.
    if recovered and not key and not base:
        return "cli"
    if transport == "api":
        return "api"
    return "api"


_GROK_CLI_ARGS = (
    "--prompt-file {prompt_file} --output-format plain --max-turns 32 --always-approve"
)


def recover_cli_command(row: dict[str, Any] | None) -> tuple[str, str]:
    """Fill a lost Grok Build command when an older save dropped cli_* fields."""
    data = row if isinstance(row, dict) else {}
    cmd = str(data.get("cli_command") or "").strip()
    args = str(data.get("cli_args") or "").strip()
    if cmd:
        return cmd, args
    name = str(data.get("name") or "").strip().lower()
    provider = str(data.get("provider") or "").strip().lower()
    if provider == "cli" or "grok build" in name or name == "grok":
        return "grok", args or _GROK_CLI_ARGS
    return "", args


def _async_openai():
    """Lazy import — openai package costs ~2s on cold start and is unused until chat."""
    from openai import AsyncOpenAI

    return AsyncOpenAI


class LLMClient:
    """Async wrapper; active model is always an explicit user-added LLM row.

    Resolution:
      * ``LLMClient()`` / ``get_llm_client()`` → default enabled row in config store
      * ``LLMClient.from_llm_config(row)`` → that row only (test / one-shot)
      * No store row and no explicit args → unconfigured (``has_api_key`` is False)
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        provider: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        llm_id: str | None = None,
        use_proxy: bool | None = None,
        _from_store: bool = True,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = None
        self._http = None
        self._fallback = None
        self._fallback_model: str | None = None
        self._fallback_cfg = None
        self.use_proxy = bool(use_proxy) if use_proxy is not None else False
        self.transport = "api"
        self.cli_command = ""
        self.cli_args = ""
        self.cli_cwd = ""

        # Explicit construction (test endpoint / from_llm_config) — use only args
        if not _from_store or any(
            x is not None
            for x in (provider, base_url, api_key, model, llm_id, use_proxy)
        ):
            self.provider = (provider or "").strip().lower()
            self.base_url = (base_url or "").strip().rstrip("/")
            self.model = (model or "").strip()
            self.api_key = _sanitize_api_key(
                (api_key if api_key is not None else "") or ""
            )
            self.llm_id = llm_id
            if use_proxy is not None:
                self.use_proxy = bool(use_proxy)
            return

        # Default path: only the UI-configured default LLM
        cfg = self._load_default_from_store()
        if not cfg:
            self.provider = ""
            self.base_url = ""
            self.model = ""
            self.api_key = ""
            self.llm_id = None
            self.use_proxy = False
            return

        self.provider = str(cfg.get("provider") or "").strip().lower()
        self.base_url = str(cfg.get("base_url") or "").strip().rstrip("/")
        self.model = str(cfg.get("model") or "").strip()
        self.api_key = _sanitize_api_key(cfg.get("api_key") or "")
        self.llm_id = cfg.get("id")
        self.use_proxy = bool(cfg.get("use_proxy"))
        self._apply_cli_from_row(cfg)

    def _apply_cli_from_row(self, row: dict[str, Any] | None) -> None:
        data = row if isinstance(row, dict) else {}
        self.transport = infer_llm_transport(data)
        cmd, args = recover_cli_command(data)
        self.cli_command = cmd
        self.cli_args = args
        self.cli_cwd = str(data.get("cli_cwd") or "").strip()

    @property
    def is_cli(self) -> bool:
        if self.transport == "cli":
            return True
        if self.transport == "api":
            return False
        return bool(self.cli_command)

    def _ensure_clients(self) -> None:
        if self.is_cli:
            return
        if self._client is not None:
            return
        if not self.has_api_key:
            raise RuntimeError(
                "未配置可用的 LLM。请打开设定 → LLM，添加模型并填写 API Key。"
            )
        if not self.base_url:
            raise RuntimeError("LLM 未填写 base_url。请在设定 → LLM 中补全。")
        if not self.model:
            raise RuntimeError("LLM 未填写 model。请在设定 → LLM 中补全。")
        AsyncOpenAI = _async_openai()
        # Always use a dedicated httpx client with trust_env=False.
        # Default OpenAI SDK inherits HTTP_PROXY and 502s LAN llama.cpp
        # (e.g. 10.11.x.x via Clash 127.0.0.1:7897).
        import httpx

        http_kwargs: dict[str, Any] = {
            "follow_redirects": True,
            "trust_env": False,
            "timeout": httpx.Timeout(300.0, connect=20.0),
        }
        if self.use_proxy:
            from app.services.model_meta import resolve_app_proxy_url

            proxy = resolve_app_proxy_url()
            if not proxy:
                raise RuntimeError(
                    "该 LLM 已勾选「使用代理」，但未配置代理地址。"
                    "请到设定 → 集成 → HTTP 网络填写代理，或取消该 LLM 的代理勾选。"
                )
            try:
                proxy.encode("ascii")
            except UnicodeEncodeError as exc:
                raise RuntimeError("代理地址含非英文字符，无法使用") from exc
            http_kwargs["proxy"] = proxy
            http_kwargs["timeout"] = httpx.Timeout(120.0, connect=20.0)
        self._http = httpx.AsyncClient(**http_kwargs)
        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=http_kwargs["timeout"],
            http_client=self._http,
        )

    @staticmethod
    def _load_default_from_store() -> dict[str, Any] | None:
        try:
            from app.config_store import get_config_store

            return get_config_store().get_default_llm()
        except Exception:
            return None

    @classmethod
    def from_llm_config(cls, llm: dict[str, Any]) -> "LLMClient":
        inst = cls(
            provider=llm.get("provider") or "",
            base_url=llm.get("base_url") or "",
            api_key=llm.get("api_key") or "",
            model=llm.get("model") or "",
            llm_id=llm.get("id"),
            use_proxy=bool(llm.get("use_proxy")),
            _from_store=False,
        )
        inst._apply_cli_from_row(llm)
        return inst

    @staticmethod
    def _supports_temperature(model: str) -> bool:
        return not bool(_NO_TEMPERATURE.search(model or ""))

    @staticmethod
    def _coerce_json(raw: Any) -> Any:
        if not isinstance(raw, str):
            return raw
        text = raw.strip()
        if not text:
            return raw
        if text[0] not in "{[":
            return raw
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return raw
        if isinstance(parsed, str) and parsed.strip()[:1] in "{[":
            try:
                return json.loads(parsed)
            except json.JSONDecodeError:
                return parsed
        return parsed

    @classmethod
    def _completion_to_dict(cls, resp: Any) -> dict[str, Any]:
        """Accept ChatCompletion / dict / JSON string / plain text from 中转站."""
        if resp is None:
            raise RuntimeError("LLM 返回空响应")

        if not isinstance(resp, (str, bytes, dict)) and hasattr(resp, "choices"):
            choice = resp.choices[0] if resp.choices else None
            if choice is None:
                raise RuntimeError("LLM 返回了空的 choices")
            msg = choice.message
            tool_calls = None
            if getattr(msg, "tool_calls", None):
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
            if getattr(resp, "usage", None):
                usage = {
                    "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(resp.usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(resp.usage, "total_tokens", 0) or 0,
                }
            return {
                "role": "assistant",
                "content": getattr(msg, "content", None),
                "tool_calls": tool_calls,
                "finish_reason": getattr(choice, "finish_reason", None),
                "model": getattr(resp, "model", "") or "",
                "usage": usage,
            }

        data = cls._coerce_json(resp)
        if isinstance(data, str):
            return {
                "role": "assistant",
                "content": data,
                "tool_calls": None,
                "finish_reason": "stop",
                "model": "",
                "usage": {},
            }
        if not isinstance(data, dict):
            raise RuntimeError(
                f"LLM 返回格式异常（{type(resp).__name__}），不是标准 chat.completions"
            )
        err = data.get("error")
        if err:
            if isinstance(err, dict):
                msg = str(err.get("message") or err)
            else:
                msg = str(err)
            raise RuntimeError(msg or "LLM 返回 error")

        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            ch0 = choices[0] if isinstance(choices[0], dict) else {}
            msg = ch0.get("message") if isinstance(ch0.get("message"), dict) else {}
            raw_tcs = msg.get("tool_calls")
            tool_calls = None
            if isinstance(raw_tcs, list) and raw_tcs:
                tool_calls = []
                for tc in raw_tcs:
                    if not isinstance(tc, dict):
                        continue
                    fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                    tool_calls.append(
                        {
                            "id": str(tc.get("id") or ""),
                            "type": "function",
                            "function": {
                                "name": str(fn.get("name") or ""),
                                "arguments": fn.get("arguments") or "{}",
                            },
                        }
                    )
            usage_raw = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            return {
                "role": "assistant",
                "content": msg.get("content"),
                "tool_calls": tool_calls,
                "finish_reason": ch0.get("finish_reason"),
                "model": str(data.get("model") or ""),
                "usage": {
                    "prompt_tokens": int(usage_raw.get("prompt_tokens") or 0),
                    "completion_tokens": int(usage_raw.get("completion_tokens") or 0),
                    "total_tokens": int(usage_raw.get("total_tokens") or 0),
                },
            }

        # Responses API-ish
        if isinstance(data.get("output_text"), str) and data.get("output_text").strip():
            return {
                "role": "assistant",
                "content": data.get("output_text"),
                "tool_calls": None,
                "finish_reason": "stop",
                "model": str(data.get("model") or ""),
                "usage": {},
            }

        snippet = json.dumps(data, ensure_ascii=False)[:240]
        raise RuntimeError(f"LLM 返回缺少 choices，无法解析：{snippet}")

    @property
    def has_api_key(self) -> bool:
        key = self.api_key
        return bool(key and key not in ("", "not-set", "your-key-here"))

    @property
    def is_configured(self) -> bool:
        """True when a user-added LLM has enough fields to attempt chat."""
        if self.is_cli:
            return bool(self.cli_command)
        return bool(self.has_api_key and self.base_url and self.model)

    def unconfigured_message(self) -> str:
        if self.is_cli or self.cli_command:
            return (
                "CLI 模型未填写命令。请打开设定 → 模型，编辑该条并填写可执行文件"
                "（例如 grok）后再对话。"
            )
        return (
            "未配置 LLM。请打开设定 → LLM，添加模型（base_url / model / API Key）后再对话。"
        )

    async def _cli_chat(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        from app.llm.cli_backend import run_cli_completion

        if not self.cli_command:
            raise RuntimeError("CLI 模型未填写命令。请打开设定 → 模型，填写可执行文件。")
        text = await run_cli_completion(
            command=self.cli_command,
            args_tpl=self.cli_args,
            cwd=self.cli_cwd,
            messages=messages,
            model=self.model,
        )
        from app.llm.cli_media import import_cli_media

        text, media_paths = import_cli_media(text, cwd=self.cli_cwd)
        return {
            "role": "assistant",
            "content": text,
            "tool_calls": None,
            "finish_reason": "stop",
            "model": self.model or "cli",
            "usage": {},
            "media_paths": media_paths,
        }

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.is_cli:
            return await self._cli_chat(messages)
        used_model = model or self.model
        kwargs: dict[str, Any] = {
            "model": used_model,
            "messages": messages,
        }
        if self._supports_temperature(used_model):
            kwargs["temperature"] = temperature
        if tools:
            kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice

        self._ensure_clients()
        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except TypeError:
            # Older / strict gateways reject unexpected kwargs
            kwargs.pop("temperature", None)
            try:
                resp = await self._client.chat.completions.create(**kwargs)
            except Exception as extra:
                raise _explain_llm_http_error(extra) from extra
        except Exception as extra:
            raise _explain_llm_http_error(extra) from extra
        try:
            return self._completion_to_dict(resp)
        except AttributeError as exc:
            raise RuntimeError(
                f"LLM 返回格式异常（{type(resp).__name__}），无法读取 choices。"
                "请确认 base_url 指向 OpenAI 兼容的 /v1，且模型名正确。"
            ) from exc

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        if self.is_cli:
            result = await self._cli_chat(messages)
            text = result.get("content") or ""
            if text:
                yield str(text)
            return
        self._ensure_clients()
        used_model = model or self.model
        stream_kw: dict[str, Any] = {
            "model": used_model,
            "messages": messages,
            "stream": True,
        }
        if self._supports_temperature(used_model):
            stream_kw["temperature"] = temperature
        try:
            stream = await self._client.chat.completions.create(**stream_kw)
        except Exception as extra:
            raise _explain_llm_http_error(extra) from extra
        async for chunk in stream:
            if isinstance(chunk, str):
                text = chunk.strip()
                if text.startswith("data:"):
                    text = text[5:].strip()
                if not text or text == "[DONE]":
                    continue
                parsed = self._coerce_json(text)
                if isinstance(parsed, str):
                    if parsed:
                        yield parsed
                    continue
                if isinstance(parsed, dict):
                    choices = parsed.get("choices") or []
                    if choices and isinstance(choices[0], dict):
                        delta = (choices[0].get("delta") or {}).get("content")
                        if delta:
                            yield str(delta)
                    elif parsed.get("output_text"):
                        yield str(parsed["output_text"])
                continue
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            delta = choices[0].delta
            if delta and delta.content:
                yield delta.content

    async def test_connection(self) -> dict[str, Any]:
        """Minimal chat completion to verify credentials."""
        if not self.is_configured:
            err = (
                "未配置完整的 CLI 模型（需要命令）"
                if self.is_cli or self.cli_command
                else "未配置完整的 LLM（需要 base_url、model、API Key）"
            )
            return {
                "ok": False,
                "error": err,
                "model": self.model or "",
            }
        try:
            result = await self.chat(
                [{"role": "user", "content": "ping"}],
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
