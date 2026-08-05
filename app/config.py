"""Application settings loaded from environment / .env."""

from __future__ import annotations

import json
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

# Project root (directory that contains app/, skills/, workspace/, data/).
# Resolved from this file so relative paths work regardless of process CWD
# (important for Linux systemd / launching from another directory).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.is_file() else ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_provider: str = "xai"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.x.ai/v1"
    llm_model: str = "grok-4.5"
    llm_fallback_api_key: str = ""
    llm_fallback_base_url: str = ""
    llm_fallback_model: str = ""

    # Server
    host: str = "0.0.0.0"
    port: int = 80
    debug: bool = True
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
    flaresolverr_url: str = "http://127.0.0.1:8191/v1"

    # MCP: JSON array string of server configs
    mcp_servers: str = ""

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
        for sub in ("sessions", "memory", "tasks", "kb", "workflows"):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
