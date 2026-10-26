"""MCP client manager — connects to external MCP servers and exposes tools."""

from __future__ import annotations

import logging
import os
import shlex
from contextlib import AsyncExitStack
from typing import Any

from app.config import get_settings
from app.tools.registry import ToolRegistry, get_tool_registry

logger = logging.getLogger(__name__)


def split_command_line(command: str, args: list[str] | None = None) -> tuple[str, list[str]]:
    """Normalize user-facing command line into (executable, args).

    Users often paste ``npx -y @scope/pkg`` into a single field.
    Uses POSIX splitting on Linux/macOS and Windows-aware rules on Windows.
    """
    existing = list(args or [])
    cmd = (command or "").strip()
    if not cmd:
        return "", existing
    # If args already provided and command has no spaces, keep as-is
    if existing and " " not in cmd and "\t" not in cmd:
        return cmd, existing
    try:
        # posix=True on Linux/macOS; Windows needs non-posix for backslash paths
        parts = shlex.split(cmd, posix=(os.name != "nt"))
    except ValueError:
        parts = cmd.split()
    if not parts:
        return "", existing
    if existing:
        # command field was only the binary; args separate
        if len(parts) == 1:
            return parts[0], existing
        # both filled with full line + args → prefer split line, ignore dup args
        return parts[0], parts[1:]
    return parts[0], parts[1:]


class MCPManager:
    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._sessions: dict[str, Any] = {}
        self._connected = False
        self.server_names: list[str] = []
        self._tool_names: list[str] = []
        # name -> status info for UI
        self._status: dict[str, dict[str, Any]] = {}

    @property
    def connected_count(self) -> int:
        return len(self._sessions)

    def status_snapshot(self) -> dict[str, dict[str, Any]]:
        return dict(self._status)

    def tools_for_server(self, server_name: str) -> list[str]:
        prefix = f"mcp_{server_name}_".replace("-", "_").replace(".", "_")
        # registered names use sanitized server name
        safe = server_name.replace("-", "_").replace(".", "_")
        prefix = f"mcp_{safe}_"
        return [n for n in self._tool_names if n.startswith(prefix) or f"_{safe}_" in n]

    def _resolve_configs(self) -> list[dict[str, Any]]:
        try:
            from app.config_store import get_config_store

            rows = get_config_store().list_mcp()
            if rows:
                return [r for r in rows if r.get("enabled", True) and r.get("command")]
        except Exception:
            pass
        return get_settings().parse_mcp_servers()

    async def start(self, registry: ToolRegistry | None = None) -> None:
        configs = self._resolve_configs()
        self._status = {}
        if not configs:
            logger.info("No MCP servers configured")
            return

        registry = registry or get_tool_registry()

        try:
            from mcp.client.session import ClientSession
            from mcp.client.stdio import StdioServerParameters, stdio_client
        except ImportError:
            logger.warning("mcp package not available; MCP disabled")
            for cfg in configs:
                name = cfg.get("name") or cfg.get("command") or "mcp"
                self._status[str(name)] = {
                    "connected": False,
                    "error": "未安装 mcp Python 包，请 pip install mcp",
                    "tool_count": 0,
                    "tools": [],
                }
            return

        # fresh stack if restarting
        if self._connected:
            await self.shutdown()
            self._stack = AsyncExitStack()

        await self._stack.__aenter__()
        self._connected = True

        for cfg in configs:
            name = str(cfg.get("name") or cfg.get("command") or "mcp")
            raw_cmd = cfg.get("command") or ""
            raw_args = cfg.get("args") or []
            command, args = split_command_line(str(raw_cmd), list(raw_args) if raw_args else None)
            if not command:
                logger.warning("MCP config missing command: %s", cfg)
                self._status[name] = {
                    "connected": False,
                    "error": "未填写启动命令",
                    "tool_count": 0,
                    "tools": [],
                }
                continue
            env = cfg.get("env") or None
            if isinstance(env, dict) and not env:
                env = None
            try:
                params = StdioServerParameters(command=command, args=args, env=env)
                read, write = await self._stack.enter_async_context(stdio_client(params))
                session = await self._stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                self._sessions[name] = session
                self.server_names.append(name)
                before = len(self._tool_names)
                await self._register_tools(name, session, registry)
                tools = self._tool_names[before:]
                self._status[name] = {
                    "connected": True,
                    "error": None,
                    "tool_count": len(tools),
                    "tools": tools,
                    "command": command,
                    "args": args,
                }
                logger.info("MCP server connected: %s (%d tools)", name, len(tools))
            except Exception as exc:
                logger.exception("Failed to connect MCP server: %s", name)
                self._status[name] = {
                    "connected": False,
                    "error": str(exc)[:300],
                    "tool_count": 0,
                    "tools": [],
                    "command": command,
                    "args": args,
                }

    async def reregister_tools(self, registry: ToolRegistry) -> None:
        for name, session in self._sessions.items():
            await self._register_tools(name, session, registry)

    async def _register_tools(
        self,
        server_name: str,
        session: Any,
        registry: ToolRegistry,
    ) -> None:
        listed = await session.list_tools()
        tools = getattr(listed, "tools", listed) or []
        for tool in tools:
            t_name = getattr(tool, "name", None) or tool.get("name")
            t_desc = getattr(tool, "description", None) or tool.get("description") or ""
            t_schema = (
                getattr(tool, "inputSchema", None)
                or getattr(tool, "input_schema", None)
                or (tool.get("inputSchema") if isinstance(tool, dict) else None)
                or {"type": "object", "properties": {}}
            )
            safe_server = server_name.replace("-", "_").replace(".", "_").replace(" ", "_")
            full_name = f"mcp_{safe_server}_{t_name}".replace("-", "_").replace(".", "_")

            async def handler(
                _session=session,
                _tool=t_name,
                **kwargs: Any,
            ) -> str:
                result = await _session.call_tool(_tool, arguments=kwargs or {})
                parts = []
                content = getattr(result, "content", None) or []
                for part in content:
                    text = getattr(part, "text", None)
                    if text is not None:
                        parts.append(text)
                    else:
                        parts.append(str(part))
                return "\n".join(parts) if parts else str(result)

            registry.register(
                full_name,
                f"[扩展·{server_name}] {t_desc}",
                handler,
                t_schema if isinstance(t_schema, dict) else {"type": "object", "properties": {}},
                source="mcp",
                metadata={"server": server_name, "original_name": t_name},
            )
            self._tool_names.append(full_name)

    async def shutdown(self) -> None:
        if self._connected:
            try:
                await self._stack.aclose()
            except Exception:
                logger.exception("Error closing MCP sessions")
            self._sessions.clear()
            self.server_names.clear()
            self._tool_names.clear()
            self._connected = False
            self._stack = AsyncExitStack()
            # keep last status for UI until next start overwrites


_manager: MCPManager | None = None


def get_mcp_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager


def reset_mcp_manager() -> None:
    global _manager
    _manager = None
