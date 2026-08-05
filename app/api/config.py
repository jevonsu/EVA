"""Configuration API — LLM / tools / skills / MCP / agent settings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from functools import lru_cache
from pydantic import BaseModel, Field

from app.config_store import get_config_store
from app.llm.client import LLMClient
from app.services.runtime import rebuild_runtime
from app.services.skills import scan_skills
from app.tools.builtin import register_builtin_tools
from app.tools.registry import ToolRegistry, get_tool_registry

router = APIRouter(prefix="/api/config", tags=["config"])


class AgentUpdate(BaseModel):
    name: str | None = None
    role: list[str] | str | None = None
    language: str | None = None
    language_style: list[str] | str | None = None
    background: str | None = None
    # Roleplay (opt-in)
    roleplay_enabled: bool | None = None
    roleplay_intensity: str | None = Field(
        default=None,
        description="light | medium | deep",
    )
    relationship: str | None = None
    personality: str | None = None
    speech_patterns: str | None = None
    example_dialogue: str | None = None
    ooc_rules: str | None = None
    decision_tree: str | None = None
    language_calibrator: str | None = None
    sop: str | None = None
    hard_boundaries: str | None = None
    greeting: str | None = None
    persona_options: dict[str, list[str]] | None = None
    max_tool_rounds: int | None = Field(default=None, ge=1, le=64)
    max_history_messages: int | None = Field(default=None, ge=4, le=200)
    # Session evolution / auto context compress
    evolution_enabled: bool | None = None
    evolution_trigger_messages: int | None = Field(
        default=None,
        ge=6,
        le=200,
        description="自上次演化起累计消息数达到该值则压缩",
    )
    evolution_keep_messages: int | None = Field(
        default=None,
        ge=4,
        le=80,
        description="演化后磁盘保留的最近原始消息条数",
    )
    evolution_max_entries: int | None = Field(
        default=None,
        ge=4,
        le=40,
        description="演化摘要最多条目数",
    )
    evolution_max_chars: int | None = Field(
        default=None,
        ge=400,
        le=8000,
        description="注入 system 的演化文本最大字符",
    )


class LLMBody(BaseModel):
    id: str | None = None
    name: str = "LLM"
    provider: str = "xai"
    base_url: str = "https://api.x.ai/v1"
    api_key: str = ""
    model: str = "grok-4.5"
    enabled: bool = True
    is_default: bool = False


class ToolToggle(BaseModel):
    name: str
    enabled: bool = True


class CustomToolBody(BaseModel):
    id: str | None = None
    name: str
    description: str = ""
    type: str = "http"
    method: str = "GET"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any | None = None
    parameters: dict[str, Any] | None = None
    timeout: float = 20
    enabled: bool = True


class SkillToggle(BaseModel):
    id: str
    enabled: bool = True


class PromptOverrideBody(BaseModel):
    """User-editable LLM-facing description (stored in config, not code)."""

    description: str = Field(
        default="",
        description="Empty string clears the override and restores code default.",
    )


class MCPBody(BaseModel):
    id: str | None = None
    name: str = ""
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    # optional friendly fields
    preset_id: str | None = None
    label: str | None = None  # display alias


@router.get("")
async def get_config() -> dict[str, Any]:
    """Public config for the settings form.

    Intentionally omits skills/tools catalogs — those are loaded on demand via
    ``/api/config/skills`` and ``/api/config/tools`` so the common path stays fast.
    """
    from app.agent.persona import persona_public_view

    store = get_config_store()
    data = store.get_public()
    data["agent"] = persona_public_view(store.get_agent())
    return data


@router.put("")
async def put_config(body: dict[str, Any]) -> dict[str, Any]:
    store = get_config_store()
    store.replace(body)
    summary = await rebuild_runtime(reconnect_mcp=True)
    return {"ok": True, "config": store.get_public(), "runtime": summary}


@router.post("/reload")
async def reload_config(reconnect_mcp: bool = True) -> dict[str, Any]:
    get_config_store().load()
    summary = await rebuild_runtime(reconnect_mcp=reconnect_mcp)
    return {"ok": True, "runtime": summary}


# ---- Agent ----

@router.patch("/agent")
async def update_agent(body: AgentUpdate) -> dict[str, Any]:
    from app.agent.persona import persona_public_view

    store = get_config_store()
    # Allow empty strings to clear persona fields; section replace + compact
    payload = body.model_dump(exclude_unset=True)
    store.update_section("agent", payload)
    await rebuild_runtime(reconnect_mcp=False)
    agent = persona_public_view(store.get_agent())
    return {"ok": True, "agent": agent}


@router.get("/agent")
async def get_agent_config() -> dict[str, Any]:
    from app.agent.persona import persona_public_view

    return persona_public_view(get_config_store().get_agent())


# ---- LLM ----

class LlmModelsQuery(BaseModel):
    """Fetch model list from OpenAI-compatible /models."""

    base_url: str = ""
    api_key: str = ""
    id: str | None = None  # existing llm id — use stored key if api_key empty


@router.get("/llms")
async def list_llms() -> list[dict[str, Any]]:
    from app.services.model_meta import enrich_llm_public

    rows = get_config_store().get_public()["llms"]
    return [enrich_llm_public(r) for r in rows]


@router.post("/llms/models")
async def list_remote_models(body: LlmModelsQuery) -> dict[str, Any]:
    """List models from provider using base_url + api_key (or saved key by id)."""
    from app.services.model_meta import fetch_openai_models

    base_url = (body.base_url or "").strip()
    api_key = (body.api_key or "").strip()
    store = get_config_store()
    from app.config_store import _is_masked

    if body.id and (not api_key or _is_masked(api_key)):
        stored = store.get_llm(body.id)
        if stored:
            if not base_url:
                base_url = str(stored.get("base_url") or "")
            if not api_key or _is_masked(api_key):
                api_key = str(stored.get("api_key") or "")
    return await fetch_openai_models(base_url=base_url, api_key=api_key)


@router.post("/llms")
async def upsert_llm(body: LLMBody) -> dict[str, Any]:
    from app.services.model_meta import enrich_llm_public

    store = get_config_store()
    llm = store.upsert_llm(body.model_dump())
    await rebuild_runtime(reconnect_mcp=False)
    public = store.get_public()
    for row in public["llms"]:
        if row["id"] == llm["id"]:
            return {"ok": True, "llm": enrich_llm_public(row)}
    return {"ok": True, "llm": enrich_llm_public(llm)}


@router.post("/llms/{llm_id}/default")
async def set_default_llm(llm_id: str) -> dict[str, Any]:
    store = get_config_store()
    if not store.set_default_llm(llm_id):
        raise HTTPException(404, "LLM not found")
    await rebuild_runtime(reconnect_mcp=False)
    return {"ok": True, "default_id": llm_id}


@router.post("/llms/{llm_id}/test")
async def test_llm(llm_id: str) -> dict[str, Any]:
    store = get_config_store()
    llm = store.get_llm(llm_id)
    if not llm:
        raise HTTPException(404, "LLM not found")
    client = LLMClient.from_llm_config(llm)
    result = await client.test_connection()
    return result


@router.get("/llms/{llm_id}/balance")
async def llm_balance(llm_id: str, refresh: bool = False) -> dict[str, Any]:
    """Best-effort credit/balance for one LLM entry (provider-dependent)."""
    from app.services.llm_balance import fetch_llm_balance

    store = get_config_store()
    llm = store.get_llm(llm_id)
    if not llm:
        raise HTTPException(404, "LLM not found")
    result = await fetch_llm_balance(
        base_url=str(llm.get("base_url") or ""),
        api_key=str(llm.get("api_key") or ""),
        provider=str(llm.get("provider") or ""),
        use_cache=not refresh,
    )
    result["llm_id"] = llm_id
    result["llm_name"] = llm.get("name") or llm_id
    return result


@router.post("/llms/test")
async def test_llm_direct(body: LLMBody) -> dict[str, Any]:
    data = body.model_dump()
    if not data.get("api_key") and data.get("id"):
        store = get_config_store()
        stored = store.get_llm(data["id"])
        if stored and stored.get("api_key"):
            data["api_key"] = stored["api_key"]
    client = LLMClient.from_llm_config(data)
    result = await client.test_connection()
    return result


@router.delete("/llms/{llm_id}")
async def delete_llm(llm_id: str) -> dict[str, Any]:
    store = get_config_store()
    if not store.delete_llm(llm_id):
        raise HTTPException(404, "LLM not found")
    await rebuild_runtime(reconnect_mcp=False)
    return {"ok": True}


# ---- Integrations (skill connection configs) ----

class IntegrationUpsert(BaseModel):
    """Partial field map; secret fields empty/masked = keep existing."""

    config: dict[str, Any] = Field(default_factory=dict)
    name: str | None = None
    description: str | None = None


@router.get("/integrations")
async def list_integrations() -> dict[str, Any]:
    store = get_config_store()
    items = store.list_integrations_public()
    from app.services.integrations_meta import skill_to_integration

    return {
        "items": items,
        "skill_map": skill_to_integration(),
    }


@router.get("/integrations/{integration_id}")
async def get_integration(integration_id: str) -> dict[str, Any]:
    row = get_config_store().get_integration_public(integration_id)
    if not row:
        raise HTTPException(404, "Integration not found")
    return row


@router.put("/integrations/{integration_id}")
async def upsert_integration(
    integration_id: str, body: IntegrationUpsert
) -> dict[str, Any]:
    store = get_config_store()
    try:
        payload = dict(body.config or {})
        # optional display meta for custom integrations (stored as non-secret fields)
        if body.name is not None:
            payload["_label"] = body.name
        if body.description is not None:
            payload["_description"] = body.description
        row = store.upsert_integration(integration_id, payload)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    # skills read config at call time; no full rebuild required
    return {"ok": True, "integration": row}


@router.delete("/integrations/{integration_id}")
async def delete_integration(integration_id: str) -> dict[str, Any]:
    store = get_config_store()
    if not store.delete_integration(integration_id):
        raise HTTPException(404, "Integration not found")
    return {"ok": True, "id": integration_id}


@router.post("/integrations/{integration_id}/test")
async def test_integration(integration_id: str) -> dict[str, Any]:
    """Best-effort connectivity check for known integrations."""
    iid = (integration_id or "").strip()
    store = get_config_store()
    raw = store.get_integrations_raw().get(iid) or {}
    try:
        if iid == "nocodb":
            from app.services.credentials import nocodb_config

            cfg = nocodb_config()
            if not cfg.get("base_url"):
                return {"ok": False, "error": "未配置 base_url"}
            import httpx

            url = cfg["base_url"].rstrip("/") + "/api/v1/health"
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(url)
            return {
                "ok": r.status_code < 500,
                "status_code": r.status_code,
                "detail": "health endpoint reachable" if r.status_code < 500 else r.text[:200],
            }
        if iid == "http":
            from app.services.credentials import http_network_config

            cfg = http_network_config()
            return {
                "ok": True,
                "detail": f"proxy={cfg.get('proxy_url') or '（空）'}; flaresolverr={cfg.get('flaresolverr_url') or '（空）'}",
            }
        if iid == "nas":
            from app.services.credentials import nas_config

            cfg = nas_config()
            if not cfg.get("host"):
                return {"ok": False, "error": "未配置 host"}
            return {
                "ok": True,
                "detail": f"已配置 {cfg.get('user') or '?'}@{cfg.get('host')}:{cfg.get('port')}",
            }
        if iid == "qbittorrent":
            from app.services.credentials import qb_config

            cfg = qb_config()
            if not cfg.get("base_url"):
                return {"ok": False, "error": "未配置 base_url"}
            import httpx

            url = cfg["base_url"].rstrip("/") + "/api/v2/app/version"
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(url)
            # 403 without cookie is still "reachable"
            return {
                "ok": r.status_code in (200, 401, 403),
                "status_code": r.status_code,
                "detail": "WebUI reachable" if r.status_code in (200, 401, 403) else r.text[:200],
            }
        if not raw and not store.get_integration_public(iid):
            raise HTTPException(404, "Integration not found")
        return {"ok": True, "detail": "已保存配置（无专用测试）", "keys": list(raw.keys())}
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---- Tools ----

@router.get("/tools")
async def list_config_tools() -> dict[str, Any]:
    store = get_config_store()
    return {
        "catalog": _tools_catalog(),
        "disabled": list(store.disabled_tools()),
        "custom": store.get_public().get("tools", {}).get("custom", []),
    }


@router.post("/tools/toggle")
async def toggle_tool(body: ToolToggle) -> dict[str, Any]:
    store = get_config_store()
    store.set_tool_disabled(body.name, disabled=not body.enabled)
    invalidate_tools_catalog_cache()
    await rebuild_runtime(reconnect_mcp=False)
    return {"ok": True, "name": body.name, "enabled": body.enabled}


@router.put("/tools/{name}/prompt")
async def set_tool_prompt(name: str, body: PromptOverrideBody) -> dict[str, Any]:
    """Set or clear LLM-facing description for a tool (no code edit)."""
    store = get_config_store()
    text = (body.description or "").strip()
    store.set_tool_prompt_override(name, text or None)
    invalidate_tools_catalog_cache()
    # No full rebuild required — applied at schema build time
    return {
        "ok": True,
        "name": name,
        "has_override": bool(text),
        "description": store.get_tool_prompt_override(name) or "",
    }


@router.post("/tools/custom")
async def upsert_custom_tool(body: CustomToolBody) -> dict[str, Any]:
    store = get_config_store()
    tool = store.upsert_custom_tool(body.model_dump())
    await rebuild_runtime(reconnect_mcp=False)
    return {"ok": True, "tool": tool}


@router.delete("/tools/custom/{tool_id}")
async def delete_custom_tool(tool_id: str) -> dict[str, Any]:
    store = get_config_store()
    if not store.delete_custom_tool(tool_id):
        raise HTTPException(404, "Custom tool not found")
    await rebuild_runtime(reconnect_mcp=False)
    return {"ok": True}


# ---- Skills ----

@router.get("/skills")
async def list_skills() -> list[dict[str, Any]]:
    return scan_skills()


@router.post("/skills/toggle")
async def toggle_skill(body: SkillToggle) -> dict[str, Any]:
    store = get_config_store()
    store.set_skill_disabled(body.id, disabled=not body.enabled)
    invalidate_tools_catalog_cache()
    await rebuild_runtime(reconnect_mcp=False)
    return {"ok": True, "id": body.id, "enabled": body.enabled}


@router.put("/skills/{skill_id}/prompt")
async def set_skill_prompt(skill_id: str, body: PromptOverrideBody) -> dict[str, Any]:
    """Set or clear package description; also used as fallback for same-name tool."""
    store = get_config_store()
    text = (body.description or "").strip()
    store.set_skill_prompt_override(skill_id, text or None)
    invalidate_tools_catalog_cache()
    return {
        "ok": True,
        "id": skill_id,
        "has_override": bool(text),
        "description": store.get_skill_prompt_override(skill_id) or "",
    }


# ---- MCP ----

@router.get("/mcp/presets")
async def list_mcp_presets() -> list[dict[str, Any]]:
    """One-click templates for ordinary users."""
    from app.mcp.presets import mcp_presets

    return mcp_presets()


@router.get("/mcp")
async def list_mcp() -> list[dict[str, Any]]:
    """List configured MCP servers with live connection status."""
    from app.mcp.client import get_mcp_manager

    rows = get_config_store().list_mcp()
    status = get_mcp_manager().status_snapshot()
    out: list[dict[str, Any]] = []
    for r in rows:
        name = str(r.get("name") or r.get("id") or "")
        st = status.get(name) or {}
        item = dict(r)
        item["status"] = {
            "connected": bool(st.get("connected")),
            "error": st.get("error"),
            "tool_count": int(st.get("tool_count") or 0),
            "tools": list(st.get("tools") or [])[:30],
        }
        if r.get("enabled") is False:
            item["status"]["connected"] = False
            item["status"]["error"] = item["status"].get("error") or "已停用"
        out.append(item)
    return out


@router.post("/mcp")
async def upsert_mcp(body: MCPBody) -> dict[str, Any]:
    """Save MCP server. Accepts full command line or command+args; optional preset_id."""
    from app.mcp.client import split_command_line
    from app.mcp.presets import preset_by_id

    store = get_config_store()
    data = body.model_dump()
    # apply preset defaults when fields empty
    preset_id = (data.pop("preset_id", None) or "").strip()
    if preset_id:
        preset = preset_by_id(preset_id)
        if preset and preset.get("id") != "custom":
            if not (data.get("name") or "").strip():
                data["name"] = preset.get("name") or preset.get("title")
            if not (data.get("command") or "").strip():
                data["command"] = preset.get("command") or ""
                data["args"] = list(preset.get("args") or [])
            if not data.get("env") and preset.get("env"):
                data["env"] = dict(preset.get("env") or {})
            data["label"] = data.get("label") or preset.get("title")
            data["preset_id"] = preset_id

    name = (data.get("name") or data.get("label") or "").strip()
    command = (data.get("command") or "").strip()
    if not name:
        raise HTTPException(400, "请填写名称")
    if not command:
        raise HTTPException(400, "请填写启动命令，或先选一个预设")

    cmd, args = split_command_line(command, list(data.get("args") or []))
    data["name"] = name
    data["command"] = cmd
    data["args"] = args
    data["enabled"] = bool(data.get("enabled", True))
    if not isinstance(data.get("env"), dict):
        data["env"] = {}

    server = store.upsert_mcp(data)
    summary = await rebuild_runtime(reconnect_mcp=True)
    # attach status for this server
    from app.mcp.client import get_mcp_manager

    st = get_mcp_manager().status_snapshot().get(name) or {}
    return {
        "ok": True,
        "server": server,
        "status": st,
        "mcp_connected": summary.get("mcp_servers"),
        "message": (
            f"已连接，提供 {st.get('tool_count') or 0} 个能力"
            if st.get("connected")
            else f"已保存，但连接失败：{st.get('error') or '未知错误'}"
        ),
    }


@router.delete("/mcp/{server_id}")
async def delete_mcp(server_id: str) -> dict[str, Any]:
    store = get_config_store()
    if not store.delete_mcp(server_id):
        raise HTTPException(404, "MCP server not found")
    await rebuild_runtime(reconnect_mcp=True)
    return {"ok": True}


@router.post("/mcp/reconnect")
async def reconnect_mcp() -> dict[str, Any]:
    """Reconnect all enabled MCP servers and return status list."""
    summary = await rebuild_runtime(reconnect_mcp=True)
    rows = await list_mcp()
    return {"ok": True, "summary": summary, "servers": rows}


# Tools UI catalog is expensive (re-imports every skill handler). Cache until
# runtime rebuild / tool toggles / prompt overrides change.
_tools_catalog_cache: list[dict[str, Any]] | None = None
_tools_catalog_cache_sig: tuple[Any, ...] | None = None


def invalidate_tools_catalog_cache() -> None:
    """Drop cached tools catalog (call after registry or enablement changes)."""
    global _tools_catalog_cache, _tools_catalog_cache_sig
    _tools_catalog_cache = None
    _tools_catalog_cache_sig = None


def _tools_catalog_signature() -> tuple[Any, ...]:
    store = get_config_store()
    po = store.get_raw().get("prompt_overrides") or {}
    if not isinstance(po, dict):
        po = {}
    tool_po = po.get("tools") or {}
    skill_po = po.get("skills") or {}
    if not isinstance(tool_po, dict):
        tool_po = {}
    if not isinstance(skill_po, dict):
        skill_po = {}
    return (
        frozenset(store.disabled_tools()),
        frozenset(store.disabled_skills()),
        tuple(sorted((str(k), str(v or "")[:80]) for k, v in tool_po.items())),
        tuple(sorted((str(k), str(v or "")[:80]) for k, v in skill_po.items())),
        len(get_tool_registry().list_tools()),
    )


def _full_tool_registry_snapshot() -> ToolRegistry:
    """Register builtins + custom + all skills (including disabled packages).

    Used only for UI catalog so disabled tools remain visible and re-toggleable.
    Does not replace the live agent registry.
    """
    from app.services.custom_tools import register_custom_tools
    from app.services.skills import register_skills

    tmp = ToolRegistry()
    register_builtin_tools(tmp)
    register_custom_tools(tmp)
    register_skills(tmp, include_disabled=True)
    return tmp


@lru_cache(maxsize=1)
def _get_builtin_catalog() -> list[dict[str, Any]]:
    """Pre-compute the full builtin tool catalog once."""
    from app.tools.tool_meta import display_name_for

    tmp = ToolRegistry()
    register_builtin_tools(tmp)
    return [
        {
            "name": t.name,
            "display_name": display_name_for(t.name),
            "description": t.description,
            "parameters": t.parameters,
            "source": t.source,
        }
        for t in tmp.list_tools()
    ]


def _tools_catalog() -> list[dict[str, Any]]:
    """Full tool catalog for UI: every known tool with enabled flag.

    Disabled tools are *unregistered* from the live agent registry so the LLM
    cannot call them — but they must still appear here so the user can re-enable.
    Result is cached; call ``invalidate_tools_catalog_cache`` after mutations.
    """
    global _tools_catalog_cache, _tools_catalog_cache_sig

    sig = _tools_catalog_signature()
    if _tools_catalog_cache is not None and _tools_catalog_cache_sig == sig:
        return _tools_catalog_cache

    from app.tools.tool_meta import (
        display_name_for,
        effective_description,
        meta_for,
        user_prompt_override,
    )

    store = get_config_store()
    disabled_tools = store.disabled_tools()
    disabled_skills = store.disabled_skills()

    try:
        snap = _full_tool_registry_snapshot()
        specs = list(snap.list_tools())
    except Exception:
        # Fallback: live registry + builtins only
        specs = list(get_tool_registry().list_tools())
        for t in _get_builtin_catalog():
            if not any(s.name == t["name"] for s in specs):
                # synthetic minimal
                from app.tools.registry import ToolSpec

                async def _noop() -> str:
                    return "{}"

                specs.append(
                    ToolSpec(
                        name=t["name"],
                        description=t.get("description") or "",
                        parameters=t.get("parameters") or {},
                        handler=_noop,
                        source=t.get("source") or "builtin",
                    )
                )

    active: dict[str, dict[str, Any]] = {}
    for t in specs:
        md = dict(t.metadata or {})
        md.update(meta_for(t.name))
        skill_id = str(md.get("skill_id") or "")
        # skill package disabled → tool shows as off
        skill_off = bool(
            skill_id
            and (
                skill_id in disabled_skills
                or skill_id.lower() in {x.lower() for x in disabled_skills}
            )
        )
        # Tasks folder vs scheduled_task name
        if t.source == "skill" and not skill_id:
            # try match skill by tool name
            skill_off = t.name in disabled_skills

        tool_off = t.name in disabled_tools
        enabled = not tool_off and not skill_off
        base_desc = (t.description or "").strip()
        override = user_prompt_override(t.name, skill_id=skill_id or None)

        active[t.name] = {
            "name": t.name,
            "display_name": display_name_for(t.name),
            "description": effective_description(
                t.name, base_desc, skill_id=skill_id or None
            ),
            "base_description": base_desc,
            "prompt_override": override or "",
            "has_prompt_override": bool(override),
            "parameters": t.parameters,
            "source": t.source,
            "enabled": enabled,
            "metadata": md,
            "skill_id": skill_id or None,
            "disabled_reason": (
                "tool"
                if tool_off
                else ("skill" if skill_off else None)
            ),
        }

    # Orphan names still listed in tools.disabled (e.g. removed skills)
    for name in disabled_tools:
        if name not in active:
            active[name] = {
                "name": name,
                "display_name": display_name_for(name),
                "description": f"已禁用的工具（{name}）。重新开启后若 skill 仍存在则会恢复注册。",
                "base_description": "",
                "prompt_override": store.get_tool_prompt_override(name) or "",
                "has_prompt_override": bool(store.get_tool_prompt_override(name)),
                "parameters": {"type": "object", "properties": {}},
                "source": "skill",
                "enabled": False,
                "metadata": meta_for(name),
                "skill_id": None,
                "disabled_reason": "tool",
            }

    result = sorted(
        active.values(),
        key=lambda x: (0 if x.get("enabled") else 1, x.get("source") or "", x["name"]),
    )
    _tools_catalog_cache = result
    _tools_catalog_cache_sig = sig
    return result
