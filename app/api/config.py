"""Configuration API — LLM / tools / skills / MCP / agent settings."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from functools import lru_cache
from pydantic import BaseModel, Field, field_validator

from app.config_store import (
    get_config_store,
    parse_scene_keywords,
    prompt_meta_active,
)
from app.llm.client import LLMClient, infer_llm_transport
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
    is_deputy: bool = False
    # Per-LLM: when True, chat / pull models / balance use Eva HTTP proxy
    use_proxy: bool = False
    # api = OpenAI-compatible HTTP (default); cli = local command (e.g. grok)
    # Empty default so omitted field does not shadow a CLI row as "api".
    transport: str = ""
    cli_command: str = ""
    cli_args: str = ""
    cli_cwd: str = ""


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
    """User-editable tool/skill facing copy (stored in config, not code).

    All-empty payload clears the override and restores code defaults.
    Legacy clients that only send ``description`` still work.
    """

    description: str = Field(
        default="",
        description="LLM-facing description. Empty keeps/restores code default.",
    )
    how_to_call: str = Field(
        default="",
        description="User-facing trigger phrase (下次这样说).",
    )
    scene_keywords: list[str] = Field(
        default_factory=list,
        description="Extra routing phrases; unioned with code defaults.",
    )

    @field_validator("scene_keywords", mode="before")
    @classmethod
    def _coerce_keywords(cls, v: Any) -> list[str]:
        return parse_scene_keywords(v)

    def normalized(self) -> dict[str, Any]:
        return {
            "description": (self.description or "").strip(),
            "how_to_call": (self.how_to_call or "").strip()[:200],
            "scene_keywords": list(self.scene_keywords or []),
        }


class CapabilityGroupBody(BaseModel):
    label: str = ""
    icon: str = ""


class CapabilityGroupAssignBody(BaseModel):
    group: str = Field(..., min_length=1)


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
    try:
        from app.services.workspace_bind import binding_public

        data["workspace"] = binding_public()
    except Exception:
        pass
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


def unwrap_settings_export(body: dict[str, Any]) -> dict[str, Any]:
    """Accept a wrapped Eva export or a raw config.json object."""
    if not isinstance(body, dict) or not body:
        raise HTTPException(status_code=400, detail="无效的设定文件")
    kind = body.get("kind")
    if body.get("eva_export"):
        if kind not in (None, "", "settings"):
            raise HTTPException(status_code=400, detail="这不是设定导出文件")
        inner = body.get("config")
        if not isinstance(inner, dict):
            raise HTTPException(status_code=400, detail="导出文件缺少 config")
        return inner
    if any(k in body for k in ("agent", "llms", "integrations", "mcp_servers", "tools")):
        return body
    raise HTTPException(status_code=400, detail="无法识别的设定文件")


@router.get("/export")
async def export_config() -> Response:
    """Download settings (agent / LLM / integrations / tools / MCP)."""
    store = get_config_store()
    raw = store.get_raw()
    raw.pop("skills_catalog", None)
    raw.pop("tools_catalog", None)
    for llm in raw.get("llms") or []:
        if isinstance(llm, dict):
            llm.pop("api_key_set", None)
    payload = {
        "eva_export": 1,
        "kind": "settings",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "config": raw,
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    fname = f"eva-settings-{datetime.now().strftime('%Y%m%d')}.json"
    return Response(
        content=body.encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/import")
async def import_config(body: dict[str, Any]) -> dict[str, Any]:
    """Replace settings from an exported file. Does not touch KB / workflows / chats."""
    from app.agent.persona import persona_public_view

    data = unwrap_settings_export(body)
    store = get_config_store()
    store.replace(data)
    summary = await rebuild_runtime(reconnect_mcp=True)
    public = store.get_public()
    public["agent"] = persona_public_view(store.get_agent())
    return {"ok": True, "config": public, "runtime": summary}


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
    use_proxy: bool | None = None  # None → use stored LLM flag if id given


@router.get("/llms")
async def list_llms() -> list[dict[str, Any]]:
    from app.services.model_meta import enrich_llm_public

    rows = get_config_store().get_public()["llms"]
    return [enrich_llm_public(r) for r in rows]


@router.post("/llms/models")
async def list_remote_models(body: LlmModelsQuery) -> dict[str, Any]:
    """List models from provider using base_url + api_key (or saved key by id)."""
    from app.services.model_meta import _clean_api_key, fetch_openai_models

    base_url = (body.base_url or "").strip()
    api_key = _clean_api_key(body.api_key or "")
    store = get_config_store()
    from app.config_store import _is_masked

    used_saved_key = False
    use_proxy = bool(body.use_proxy) if body.use_proxy is not None else False
    if body.id:
        stored = store.get_llm(body.id)
        if stored:
            if not base_url:
                base_url = str(stored.get("base_url") or "")
            if not api_key or _is_masked(api_key):
                api_key = _clean_api_key(str(stored.get("api_key") or ""))
                used_saved_key = bool(api_key)
            if body.use_proxy is None:
                use_proxy = bool(stored.get("use_proxy"))
    result = await fetch_openai_models(
        base_url=base_url, api_key=api_key, use_proxy=use_proxy
    )
    if used_saved_key and not result.get("ok"):
        # clarify for UI: empty form key → used stored key
        err = str(result.get("error") or "")
        if result.get("auth_error") or "401" in err or "403" in err:
            result["error"] = (
                err
                + "（当前用的是已保存的 Key；若刚改过 Key，请在输入框重新粘贴后先「保存」再拉取。）"
            )
    return result


def _normalize_llm_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Persist / test with a resolved transport; drop leftover CLI fields on API."""
    from app.llm.client import recover_cli_command

    payload = dict(data)
    transport = infer_llm_transport(payload)
    payload["transport"] = transport
    if transport == "cli":
        payload["provider"] = "cli"
        cmd, args = recover_cli_command(payload)
        payload["cli_command"] = cmd
        payload["cli_args"] = args
        payload["cli_cwd"] = str(payload.get("cli_cwd") or "").strip()
    else:
        payload["cli_command"] = ""
        payload["cli_args"] = ""
        payload["cli_cwd"] = ""
    return payload


@router.post("/llms")
async def upsert_llm(body: LLMBody) -> dict[str, Any]:
    from app.services.model_meta import enrich_llm_public

    store = get_config_store()
    payload = _normalize_llm_payload(body.model_dump())
    llm = store.upsert_llm(payload)
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


@router.post("/llms/{llm_id}/deputy")
async def set_deputy_llm(llm_id: str) -> dict[str, Any]:
    store = get_config_store()
    if not store.set_deputy_llm(llm_id):
        raise HTTPException(404, "LLM not found")
    await rebuild_runtime(reconnect_mcp=False)
    return {"ok": True, "deputy_id": llm_id}


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
        use_proxy=bool(llm.get("use_proxy")),
    )
    result["llm_id"] = llm_id
    result["llm_name"] = llm.get("name") or llm_id
    return result


@router.post("/llms/test")
async def test_llm_direct(body: LLMBody) -> dict[str, Any]:
    from app.config_store import _is_masked
    from app.services.model_meta import _clean_api_key

    data = body.model_dump()
    data["api_key"] = _clean_api_key(str(data.get("api_key") or ""))
    data["base_url"] = str(data.get("base_url") or "").strip()
    stored = None
    if data.get("id"):
        stored = get_config_store().get_llm(str(data["id"]))
    # empty / masked form key → fall back to saved entry
    if stored and (not data.get("api_key") or _is_masked(data.get("api_key"))):
        if stored.get("api_key"):
            data["api_key"] = _clean_api_key(str(stored.get("api_key") or ""))
        if not data.get("base_url"):
            data["base_url"] = str(stored.get("base_url") or "")
        if not data.get("model"):
            data["model"] = str(stored.get("model") or "")
        # form may omit use_proxy when testing unsaved — keep stored if not in body
        if "use_proxy" not in body.model_fields_set:
            data["use_proxy"] = bool(stored.get("use_proxy"))
    if stored:
        if not str(data.get("cli_command") or "").strip():
            data["cli_command"] = str(stored.get("cli_command") or "")
        if not str(data.get("cli_args") or "").strip():
            data["cli_args"] = str(stored.get("cli_args") or "")
        if not str(data.get("cli_cwd") or "").strip():
            data["cli_cwd"] = str(stored.get("cli_cwd") or "")
        body_t = str(data.get("transport") or "").strip().lower()
        stored_t = str(stored.get("transport") or "").strip().lower()
        if not body_t or (body_t == "api" and stored_t == "cli" and not data.get("api_key")):
            data["transport"] = stored_t
    data = _normalize_llm_payload(data)
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
    """Probe the integration. ``ok`` is true only when a real check succeeds."""
    from app.services.integration_test import run_integration_test

    result = await run_integration_test(integration_id)
    if not isinstance(result, dict):
        return {"ok": False, "error": "测试未返回结果"}
    if result.get("ok") is not True:
        result["ok"] = False
        if not str(result.get("error") or "").strip():
            result["error"] = str(result.get("detail") or "测试失败")
    return result


# ---- Tools ----

@router.get("/tools")
async def list_config_tools() -> dict[str, Any]:
    store = get_config_store()
    try:
        catalog = _tools_catalog()
    except Exception as exc:
        import logging

        logging.getLogger("app.api.config").exception("tools catalog failed")
        catalog = []
        try:
            catalog = list(_get_builtin_catalog())
        except Exception:
            catalog = []
        return {
            "catalog": catalog,
            "disabled": [],
            "custom": [],
            "error": str(exc)[:300],
        }
    pub = store.get_public()
    tools_sec = pub.get("tools") if isinstance(pub.get("tools"), dict) else {}
    custom = tools_sec.get("custom") if isinstance(tools_sec.get("custom"), list) else []
    return {
        "catalog": catalog,
        "disabled": list(store.disabled_tools()),
        "custom": custom,
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
    """Set or clear description / trigger for a tool (no code edit)."""
    store = get_config_store()
    payload = body.normalized()
    clear = not prompt_meta_active(payload)
    meta = store.set_tool_prompt_meta(
        name,
        description=payload["description"],
        how_to_call=payload["how_to_call"],
        scene_keywords=payload["scene_keywords"],
        clear=clear,
    ) or {}
    invalidate_tools_catalog_cache()
    return {
        "ok": True,
        "name": name,
        "has_override": prompt_meta_active(meta),
        "description": meta.get("description") or "",
        "how_to_call": meta.get("how_to_call") or "",
        "scene_keywords": meta.get("scene_keywords") or [],
    }


@router.put("/tools/{name}/group")
async def set_tool_group(name: str, body: CapabilityGroupAssignBody) -> dict[str, Any]:
    """Move a tool (and same-id skill if any) to a capability group."""
    from app.tools.capability_groups import set_item_group

    try:
        result = set_item_group(name, body.group)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    invalidate_tools_catalog_cache()
    return result


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


@router.get("/skills/export")
async def export_skills(ids: str = "") -> Response:
    """Download business skill packages as a .evaskill zip."""
    from app.services.skill_pack import build_export_zip, export_content_disposition

    want = [x.strip() for x in (ids or "").split(",") if x.strip()]
    try:
        blob, fname, packed = build_export_zip(want or None)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition": export_content_disposition(fname)},
    )


@router.post("/skills/import")
async def import_skills(
    file: UploadFile = File(...),
    overwrite: bool = Query(False),
) -> dict[str, Any]:
    """Install one or more skill packages from a .evaskill / zip file."""
    from app.services.skill_pack import preview_and_install

    raw = await file.read()
    try:
        result = preview_and_install(raw, overwrite=overwrite)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if result.get("installed"):
        invalidate_tools_catalog_cache()
        await rebuild_runtime(reconnect_mcp=False)
    result["filename"] = file.filename or ""
    return result


@router.delete("/skills/{skill_id}")
async def uninstall_skill(skill_id: str) -> dict[str, Any]:
    from app.services.skill_pack import uninstall_skill as _uninstall

    result = _uninstall(skill_id)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "卸载失败")
    invalidate_tools_catalog_cache()
    await rebuild_runtime(reconnect_mcp=False)
    return result


@router.post("/skills/toggle")
async def toggle_skill(body: SkillToggle) -> dict[str, Any]:
    store = get_config_store()
    store.set_skill_disabled(body.id, disabled=not body.enabled)
    invalidate_tools_catalog_cache()
    await rebuild_runtime(reconnect_mcp=False)
    return {"ok": True, "id": body.id, "enabled": body.enabled}


@router.put("/skills/{skill_id}/prompt")
async def set_skill_prompt(skill_id: str, body: PromptOverrideBody) -> dict[str, Any]:
    """Set or clear package description / trigger; fallback for same-name tool."""
    store = get_config_store()
    payload = body.normalized()
    clear = not prompt_meta_active(payload)
    meta = store.set_skill_prompt_meta(
        skill_id,
        description=payload["description"],
        how_to_call=payload["how_to_call"],
        scene_keywords=payload["scene_keywords"],
        clear=clear,
    ) or {}
    invalidate_tools_catalog_cache()
    return {
        "ok": True,
        "id": skill_id,
        "has_override": prompt_meta_active(meta),
        "description": meta.get("description") or "",
        "how_to_call": meta.get("how_to_call") or "",
        "scene_keywords": meta.get("scene_keywords") or [],
    }


@router.put("/skills/{skill_id}/group")
async def set_skill_group(skill_id: str, body: CapabilityGroupAssignBody) -> dict[str, Any]:
    """Move a skill package (and same-name tool) to a capability group."""
    from app.tools.capability_groups import set_item_group

    try:
        result = set_item_group(skill_id, body.group)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    invalidate_tools_catalog_cache()
    return result


@router.get("/capability-groups")
async def list_capability_groups() -> dict[str, Any]:
    from app.tools.capability_groups import public_groups

    return {"groups": public_groups()}


@router.post("/capability-groups")
async def add_capability_group(body: CapabilityGroupBody) -> dict[str, Any]:
    from app.tools.capability_groups import add_group

    try:
        group = add_group(body.label, body.icon or "")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    invalidate_tools_catalog_cache()
    return {"ok": True, "group": group}


@router.patch("/capability-groups/{group_id}")
async def rename_capability_group(group_id: str, body: CapabilityGroupBody) -> dict[str, Any]:
    from app.tools.capability_groups import rename_group

    try:
        group = rename_group(group_id, body.label, body.icon or None)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    invalidate_tools_catalog_cache()
    return {"ok": True, "group": group}


@router.delete("/capability-groups/{group_id}")
async def delete_capability_group(
    group_id: str,
    migrate: str = Query("other"),
) -> dict[str, Any]:
    from app.tools.capability_groups import delete_group

    try:
        result = delete_group(group_id, migrate=migrate or "other")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    invalidate_tools_catalog_cache()
    return result


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

    def _po_sig(bucket: dict[str, Any]) -> tuple[tuple[str, str], ...]:
        rows: list[tuple[str, str]] = []
        for k, v in bucket.items():
            if isinstance(v, dict):
                blob = json.dumps(v, ensure_ascii=False, sort_keys=True)[:120]
            else:
                blob = str(v or "")[:80]
            rows.append((str(k), blob))
        return tuple(sorted(rows))

    return (
        frozenset(store.disabled_tools()),
        frozenset(store.disabled_skills()),
        _po_sig(tool_po),
        _po_sig(skill_po),
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


def _safe_parameters(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"type": "object", "properties": {}}


def _append_catalog_item(
    active: dict[str, dict[str, Any]],
    t: Any,
    *,
    disabled_tools: set[str],
    disabled_skills: set[str],
    display_name_for: Any,
    effective_description: Any,
    meta_for: Any,
    user_prompt_override: Any,
    builtin_scene_keywords: Any,
    user_prompt_meta: Any,
) -> None:
    name = str(getattr(t, "name", "") or "")
    if not name:
        return
    md = dict(getattr(t, "metadata", None) or {})
    extra = meta_for(name)
    if isinstance(extra, dict):
        md.update(extra)
    skill_id = str(md.get("skill_id") or "")
    skill_off = bool(
        skill_id
        and (
            skill_id in disabled_skills
            or skill_id.lower() in {x.lower() for x in disabled_skills}
        )
    )
    source = str(getattr(t, "source", "") or "builtin")
    if source == "skill" and not skill_id:
        skill_off = name in disabled_skills
    tool_off = name in disabled_tools
    enabled = not tool_off and not skill_off
    raw_desc = getattr(t, "description", "") or ""
    base_desc = raw_desc if isinstance(raw_desc, str) else str(raw_desc)
    override = user_prompt_override(name, skill_id=skill_id or None)
    tool_meta = user_prompt_meta(name) or {}
    pkg_meta = (
        user_prompt_meta(name, skill_id=skill_id) or {}
        if skill_id
        else {}
    )
    own_meta = {
        "description": str(tool_meta.get("description") or "").strip()
        or str(pkg_meta.get("description") or "").strip(),
        "how_to_call": str(tool_meta.get("how_to_call") or "").strip()
        or str(pkg_meta.get("how_to_call") or "").strip(),
        "scene_keywords": list(
            tool_meta.get("scene_keywords")
            or pkg_meta.get("scene_keywords")
            or []
        ),
    }
    spec = md.get("spec") if isinstance(md.get("spec"), dict) else {}
    base_how = str(
        md.get("how_to_call") or spec.get("trigger") or ""
    ).strip()
    base_kws = list(builtin_scene_keywords(name) or ())
    for k in md.get("scene_keywords") or []:
        s = str(k).strip()
        if s and s not in base_kws:
            base_kws.append(s)
    how_ovr = str(own_meta.get("how_to_call") or "").strip()
    kw_ovr = list(own_meta.get("scene_keywords") or [])
    active[name] = {
        "name": name,
        "display_name": display_name_for(name),
        "description": effective_description(
            name, base_desc, skill_id=skill_id or None
        ),
        "base_description": base_desc,
        "prompt_override": override or "",
        "prompt_meta": {
            "description": str(own_meta.get("description") or "").strip(),
            "how_to_call": how_ovr,
            "scene_keywords": kw_ovr,
        },
        "has_prompt_override": prompt_meta_active(own_meta) or bool(override),
        "base_how_to_call": base_how,
        "how_to_call": how_ovr or base_how,
        "base_scene_keywords": base_kws,
        "scene_keywords": kw_ovr,
        "parameters": _safe_parameters(getattr(t, "parameters", None)),
        "source": source,
        "enabled": enabled,
        "metadata": md,
        "skill_id": skill_id or None,
        "disabled_reason": (
            "tool" if tool_off else ("skill" if skill_off else None)
        ),
    }


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
        builtin_scene_keywords,
        display_name_for,
        effective_description,
        meta_for,
        user_prompt_meta,
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
        try:
            _append_catalog_item(
                active,
                t,
                disabled_tools=disabled_tools,
                disabled_skills=disabled_skills,
                display_name_for=display_name_for,
                effective_description=effective_description,
                meta_for=meta_for,
                user_prompt_override=user_prompt_override,
                builtin_scene_keywords=builtin_scene_keywords,
                user_prompt_meta=user_prompt_meta,
            )
        except Exception:
            import logging

            logging.getLogger("app.api.config").exception(
                "skip broken tool in catalog: %r", getattr(t, "name", t)
            )

    # Orphan names still listed in tools.disabled (e.g. removed skills)
    for name in disabled_tools:
        if name not in active:
            active[name] = {
                "name": name,
                "display_name": display_name_for(name),
                "description": f"已禁用的工具（{name}）。重新开启后若 skill 仍存在则会恢复注册。",
                "base_description": "",
                "prompt_override": store.get_tool_prompt_override(name) or "",
                "prompt_meta": store.get_tool_prompt_meta(name) or {
                    "description": "",
                    "how_to_call": "",
                    "scene_keywords": [],
                },
                "has_prompt_override": prompt_meta_active(
                    store.get_tool_prompt_meta(name)
                ),
                "base_how_to_call": "",
                "how_to_call": (
                    (store.get_tool_prompt_meta(name) or {}).get("how_to_call") or ""
                ),
                "base_scene_keywords": list(meta_for(name).get("scene_keywords") or []),
                "scene_keywords": (
                    (store.get_tool_prompt_meta(name) or {}).get("scene_keywords")
                    or []
                ),
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
