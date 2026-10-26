"""Application settings loaded from environment / .env."""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SYSTEM_PROMPT = """\
You are a capable backend AI agent. You can use tools to help the user.
Be concise, accurate, and proactive. When a tool is needed, call it.
If a task is long-running, suggest creating a scheduled task.
Reply in the same language the user uses.
"""


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def runtime_root() -> Path:
    """Writable project root (``data/``, ``workspace/``, ``.env``)."""
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_root() -> Path:
    """Read-only resource root (``skills/``, static assets)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if _is_frozen() and meipass:
        return Path(meipass)
    return runtime_root()


# Project root for data / workspace / .env (not process CWD).
PROJECT_ROOT = runtime_root()
RESOURCE_ROOT = resource_root()
_ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.is_file() else ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM — optional legacy env seed only; chat uses UI-added models in data/config.json
    # Keep empty for a blank project: users must add LLM in 设定 → LLM.
    llm_provider: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_fallback_api_key: str = ""
    llm_fallback_base_url: str = ""
    llm_fallback_model: str = ""

    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    # Default off for delivery. True = verbose terminal logs + HTTP access log.
    debug: bool = False
    cors_origins: str = "*"

    # Agent
    agent_name: str = "PythonAIAgent"
    agent_system_prompt: str = ""
    max_tool_rounds: int = 8
    max_history_messages: int = 40

    # Data (relative paths resolve against PROJECT_ROOT, not process CWD)
    data_dir: Path = Path("data")

    # Network (optional; also readable via integrations.http in config.json)
    proxy_url: str = ""
    flaresolverr_url: str = ""

    # MCP: JSON array string of server configs
    mcp_servers: str = ""

    # ---- Card login（鉴权服务由管理员侧提供，本机只做登录门禁）----
    auth_enabled: bool = True
    # 可选：默认鉴权网关预填（用户登录页可改）
    auth_control_url: str = ""
    # 多环境网关预设（公司内网 / 外出公网等），逗号分隔：
    # 标签=URL 或 纯 URL。例：
    # 公司内网=http://10.11.11.41:8090,外出公网=http://cardserver.hn.takin.cc
    auth_control_urls: str = ""
    # 控制面共享密钥：仅写在本机 .env，不在登录页展示；请求网关时带 X-Control-Key
    auth_control_key: str = ""
    # 本节点标识（写入鉴权会话，便于审计）
    auth_node_id: str = "eva"
    auth_session_days: int = 7
    auth_cookie_secure: bool = False
    # Only honor X-Forwarded-For when sitting behind a trusted reverse proxy
    auth_trust_proxy: bool = False

    @field_validator("data_dir", mode="before")
    @classmethod
    def _path(cls, v: Any) -> Path:
        p = Path(v) if not isinstance(v, Path) else v
        if not p.is_absolute():
            p = (PROJECT_ROOT / p).resolve()
        return p

    @property
    def system_prompt(self) -> str:
        return (self.agent_system_prompt or DEFAULT_SYSTEM_PROMPT).strip()

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def parse_mcp_servers(self) -> list[dict[str, Any]]:
        raw = self.mcp_servers.strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return [data]
        except json.JSONDecodeError:
            pass
        return []

    def ensure_dirs(self) -> None:
        """Create canonical ``data/`` layout and migrate legacy flat files."""
        from app.paths import get_data_paths

        get_data_paths(self.data_dir).ensure()

    def paths(self):
        """Shortcut: ``get_settings().paths()`` → :class:`app.paths.DataPaths`."""
        from app.paths import get_data_paths

        return get_data_paths(self.data_dir)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


def configure_logging(debug: bool | None = None) -> None:
    """Delivery stays quiet (INFO). DEBUG=true prints app + request details."""
    import logging

    if debug is None:
        debug = bool(getattr(get_settings(), "debug", False))
    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            encoding="utf-8",
        )
    root.setLevel(level)
    for handler in root.handlers:
        handler.setLevel(level)
    logging.getLogger("app").setLevel(level)
    logging.getLogger("uvicorn").setLevel(level)
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO if debug else logging.WARNING)
    # httpx floods the console with auth probes unless debug is on
    logging.getLogger("httpx").setLevel(logging.INFO if debug else logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.INFO if debug else logging.WARNING)
