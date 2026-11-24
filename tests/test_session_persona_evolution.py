"""Mock tests for session persona, session history, and evolution editing.

Uses a temporary SQLite database and in-memory config. Never starts EVA,
never reads real data/, and never starts or stops host processes.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.agent.evolution_entries import (
    delete_manual_entry,
    merge_evolution,
    normalize_digest,
    query_entries,
    upsert_manual_entry,
)
from app.agent.session_persona import (
    ROLE_CHANGE_HINT,
    build_persona_record,
    resolve_session_agent,
    snapshot_persona_fields,
)
from app.tools.intent_routing import force_tools_from_text


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data))
    from app.config import get_settings

    get_settings.cache_clear()
    from app.storage import engine as eng
    from app.storage import settings as st

    st._cached = st.StorageSettings(backend="sqlite", sqlite_path=str((data / "eva.db").resolve()))
    eng.dispose_engine()
    eng.create_tables(eng.get_engine(force=True))
    from app.config_store import reset_config_store
    from app.memory.session import reset_session_store
    from app.memory.store import reset_memory_store

    reset_config_store()
    reset_session_store()
    reset_memory_store()
    return data


def _public(name="公共助手", **extra):
    from app.config_store import get_config_store

    payload = {"name": name, "language": "简体中文", "background": "公共背景", **extra}
    get_config_store().update_section("agent", payload)
    return get_config_store().get_agent()


def test_inherit_default_and_blank(isolated):
    public = _public()
    effective, info = resolve_session_agent(public, None)
    assert info["mode"] == "inherit"
    assert effective["name"] == "公共助手"
    sess = {"metadata": {}}
    effective, info = resolve_session_agent(public, sess)
    assert info["mode"] == "inherit"
    sess = {"metadata": {"persona": {"mode": "override", "agent": {"name": "   "}}}}
    effective, info = resolve_session_agent(public, sess)
    assert info["mode"] == "inherit"
    assert effective["name"] == "公共助手"


def test_override_independent_of_public(isolated):
    public = _public()
    rec = build_persona_record(
        mode="override",
        agent_fields={"name": "会话角色", "background": "独立背景", "language": "简体中文"},
    )
    sess = {"metadata": {"persona": rec}, "messages": [{"role": "user", "content": "hi"}]}
    effective, info = resolve_session_agent(public, sess)
    assert info["mode"] == "override"
    assert effective["name"] == "会话角色"
    # public change does not affect override
    public2 = _public(name="改过的公共")
    effective2, _ = resolve_session_agent(public2, sess)
    assert effective2["name"] == "会话角色"
    assert public2["name"] == "改过的公共"
    # inherit then follows public
    rec2 = build_persona_record(mode="inherit", agent_fields={}, previous=rec)
    sess["metadata"]["persona"] = rec2
    effective3, info3 = resolve_session_agent(public2, sess)
    assert info3["mode"] == "inherit"
    assert effective3["name"] == "改过的公共"
    assert info3["show_role_change_hint"]


def test_runtime_knobs_not_in_snapshot(isolated):
    snap = snapshot_persona_fields(
        {"name": "A", "max_tool_rounds": 32, "evolution_enabled": False}
    )
    assert "max_tool_rounds" not in snap
    assert "evolution_enabled" not in snap
    public = _public(max_tool_rounds=9)
    rec = build_persona_record(mode="override", agent_fields={"name": "B"})
    eff, _ = resolve_session_agent(public, {"metadata": {"persona": rec}})
    assert eff["name"] == "B"
    assert int(eff.get("max_tool_rounds") or 0) == 9


def test_merge_keeps_manual_and_tombstones():
    prev = normalize_digest(
        {
            "entries": [
                {"id": "m1", "kind": "preference", "content": "手动保留", "source": "manual", "protected": True},
                {"id": "a1", "kind": "fact", "content": "旧自动", "source": "auto"},
            ]
        }
    )
    prev = delete_manual_entry(prev, "a1")
    generated = {
        "entries": [
            {"kind": "fact", "content": "旧自动"},  # resurrect attempt
            {"kind": "goal", "content": "新自动目标"},
            {"kind": "preference", "content": "手动保留"},
        ]
    }
    merged = merge_evolution(prev, generated, max_entries=12)
    contents = [e["content"] for e in merged["entries"]]
    assert "手动保留" in contents
    assert "旧自动" not in contents
    assert "新自动目标" in contents
    assert any(e.get("protected") or e.get("source") == "manual" for e in merged["entries"] if e["content"] == "手动保留")


def test_query_pagination_and_page_correction():
    rows = [
        {"content": f"条目{i}", "kind": "fact", "tags": ["t1"] if i % 2 == 0 else [], "source": "manual", "updated_at": f"2026-01-{i:02d}", "scope": "session"}
        for i in range(1, 16)
    ]
    page = query_entries(rows, page=2, page_size=10)
    assert page["page"] == 2
    assert page["total"] == 15
    assert len(page["items"]) == 5
    filtered = query_entries(rows, tag="t1", page=9, page_size=10)
    assert filtered["page"] == 1
    assert filtered["total"] == 7
    empty = query_entries(rows, q="不存在的关键词")
    assert empty["empty"] and empty["total"] == 0


@pytest.mark.asyncio
async def test_session_crud_and_history_isolation(isolated):
    from app.config_store import get_config_store
    from app.memory.session import get_session_store
    from app.services.session_history import excerpt_session, query_sessions

    _public()
    store = get_session_store()
    a = await store.create(title="项目计划")
    b = await store.create(title="角色闲聊")
    await store.append_messages(a["session_id"], [
        {"role": "user", "content": "我们下周开会，api_key=sk-secret-123456"},
        {"role": "assistant", "content": "好的"},
    ])
    rec = build_persona_record(mode="override", agent_fields={"name": "只属于B", "background": "隐藏人设正文xyzzy"})
    await store.update_metadata(b["session_id"], {"persona": rec}, merge=True)
    found = await query_sessions(q="开会")
    assert found["total"] == 1
    assert found["items"][0]["session_id"] == a["session_id"]
    assert "sk-secret" not in (found["items"][0].get("snippet") or "")
    leaked = await query_sessions(q="xyzzy")
    assert leaked["total"] == 0
    listed = await query_sessions(page=1, page_size=10)
    assert listed["total"] == 2
    assert "visibility" in listed
    ex = await excerpt_session(a["session_id"], offset=0, limit=10)
    assert ex["ok"]
    blob = json.dumps(ex, ensure_ascii=False)
    assert "sk-secret" not in blob
    with pytest.raises(KeyError):
        await excerpt_session("missing-session-id")


@pytest.mark.asyncio
async def test_update_persona_scope(isolated, monkeypatch):
    from app.tools.builtin import register_builtin_tools
    from app.tools.registry import ToolRegistry
    from app.memory.session import get_session_store
    from app.config_store import get_config_store
    from app.tools import protection

    _public(name="公共助手")
    store = get_session_store()
    sess = await store.create(title="测试对话")
    monkeypatch.setattr(protection, "get_turn_session_id", lambda: sess["session_id"])
    reg = ToolRegistry()
    register_builtin_tools(reg)
    tool = reg.get("update_persona")
    out = json.loads(await tool.handler(action="update", name="会话角色", scope="identity"))
    assert out["ok"] is True
    assert out["target"] == "session"
    public = get_config_store().get_agent()
    assert public["name"] == "公共助手"
    data = await store.get(sess["session_id"])
    assert data["metadata"]["persona"]["mode"] == "override"
    assert data["metadata"]["persona"]["agent"]["name"] == "会话角色"
    assert ROLE_CHANGE_HINT in (out.get("role_change_hint") or "")
    # explicit global
    out2 = json.loads(await tool.handler(action="update", name="新公共", scope="identity", target="global"))
    assert out2["ok"] is True
    assert get_config_store().get_agent()["name"] == "新公共"
    data = await store.get(sess["session_id"])
    assert data["metadata"]["persona"]["agent"]["name"] == "会话角色"


@pytest.mark.asyncio
async def test_evolution_crud_and_tags(isolated):
    from app.memory.session import get_session_store
    from app.services import evolution_catalog as cat

    store = get_session_store()
    sess = await store.create(title="演化会话")
    tag = cat.create_tag("关系")
    entry = await cat.save_entry(
        scope="session",
        session_id=sess["session_id"],
        payload={"kind": "preference", "content": "喜欢被叫测试昵称Alpha", "tags": [tag["id"]]},
    )
    assert entry["scope"] == "session"
    assert entry["source"] == "manual"
    renamed = cat.rename_tag(tag["id"], "关系设定")
    assert renamed["name"] == "关系设定"
    listed = await cat.query_evolution_entries(scope="session", session_id=sess["session_id"], tag="关系设定")
    assert listed["total"] == 1
    assert listed["items"][0]["tag_names"] == ["关系设定"]
    glob = await cat.save_entry(scope="global", session_id=None, payload={"kind": "fact", "content": "用户时区是上海", "tags": [tag["id"]]})
    assert glob["scope"] == "global"
    usage = await cat.tag_usage(tag["id"])
    assert usage["total"] == 2
    deleted = await cat.delete_tag(tag["id"])
    assert deleted["entries_preserved"] is True
    listed2 = await cat.query_evolution_entries(scope="all", session_id=sess["session_id"])
    assert listed2["total"] == 2
    assert all(not item["tags"] for item in listed2["items"])
    # pagination 10
    for i in range(12):
        await cat.save_entry(scope="global", session_id=None, payload={"kind": "fact", "content": f"公共要点{i}"})
    page1 = await cat.query_evolution_entries(scope="global", page=1, page_size=10)
    assert page1["page_size"] == 10
    assert len(page1["items"]) == 10
    page2 = await cat.query_evolution_entries(scope="global", page=2, page_size=10)
    assert page2["page"] == 2
    assert page2["total"] >= 13


class _FakeLLM:
    is_configured = True
    is_cli = False
    model = "mock"
    llm_id = "mock"

    def __init__(self):
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return {"content": "好的", "model": "mock", "usage": {}}

    async def chat_stream(self, messages, **kwargs):
        self.calls.append(messages)
        yield "好"
        yield "的"


def _agent(isolated):
    from app.agent.core import Agent
    from app.config import get_settings
    from app.memory.session import get_session_store
    from app.memory.store import get_memory_store
    from app.tools.registry import ToolRegistry

    llm = _FakeLLM()
    mem = get_memory_store()
    mem.context_snippet = AsyncMock(return_value="")
    a = Agent(settings=get_settings(), llm=llm, tools=ToolRegistry(), sessions=get_session_store(), memory=mem)
    return a, llm


@pytest.mark.asyncio
async def test_chat_and_stream_use_frozen_session_persona(isolated, monkeypatch):
    from app.memory.session import get_session_store
    from app.tools import protection

    public = _public(name="公共助手", background="公共背景")
    store = get_session_store()
    sess = await store.create(title="独立")
    rec = build_persona_record(mode="override", agent_fields={"name": "会话角色", "background": "独立背景"})
    await store.update_metadata(sess["session_id"], {"persona": rec}, merge=True)
    monkeypatch.setattr(protection, "set_turn_context", lambda *a, **k: None)
    a, llm = _agent(isolated)
    resp = await a.chat("你好", session_id=sess["session_id"], use_tools=False, use_memory=False)
    assert resp.reply
    system = llm.calls[0][0]["content"]
    assert "会话角色" in system
    assert "独立背景" in system
    assert "公共助手" not in system
    # mid-turn public change should not affect already frozen call; next call inherit would
    _public(name="改公共")
    llm.calls.clear()
    parts = []
    async for d in a.chat_stream("继续", session_id=sess["session_id"], use_memory=False):
        parts.append(d)
    system2 = llm.calls[0][0]["content"]
    assert "会话角色" in system2
    assert "改公共" not in system2


@pytest.mark.asyncio
async def test_session_history_tool_and_unknown(isolated):
    from app.tools.builtin import register_builtin_tools
    from app.tools.registry import ToolRegistry
    from app.memory.session import get_session_store

    store = get_session_store()
    await store.create(title="alpha 计划")
    await store.create(title="beta 复盘")
    reg = ToolRegistry()
    register_builtin_tools(reg)
    tool = reg.get("session_history")
    listed = json.loads(await tool.handler(action="list", page=1, page_size=10))
    assert listed["ok"] and listed["total"] == 2
    searched = json.loads(await tool.handler(action="search", query="复盘"))
    assert searched["total"] == 1
    missing = json.loads(await tool.handler(action="read", session_id="no-such"))
    assert missing["ok"] is False


def test_intent_forces_session_history():
    assert "session_history" in force_tools_from_text("我有多少对话")
    assert "session_history" in force_tools_from_text("列出所有会话")
    assert "session_history" in force_tools_from_text("之前那个聊天记录")


def test_process_consent_source_not_reverted():
    from pathlib import Path
    core = (Path(__file__).resolve().parents[1] / "app/agent/core.py").read_text(encoding="utf-8")
    assert "_handle_kill_confirm_reply" in core
    assert "不会自动重试或重新询问同意" in core


def test_manual_entries_not_written_to_memory(isolated):
    # Saving persona / evolution must not create memory rows.
    from app.config_store import get_config_store
    from app.memory.session import get_session_store
    from app.memory.store import get_memory_store
    from app.services import evolution_catalog as cat

    async def _run():
        _public()
        store = get_session_store()
        sess = await store.create(title="m")
        rec = build_persona_record(mode="override", agent_fields={"name": "角色X", "relationship": "密友"})
        await store.update_metadata(sess["session_id"], {"persona": rec}, merge=True)
        await cat.save_entry(scope="session", session_id=sess["session_id"], payload={"kind": "preference", "content": "只在本会话"})
        await cat.save_entry(scope="global", session_id=None, payload={"kind": "fact", "content": "公共演化事实"})
        mem = get_memory_store()
        return await mem.list_all(limit=50, include_archived=True)

    items = asyncio.run(_run())
    blob = " ".join(getattr(x, "content", "") or str(x) for x in (items or []))
    assert "角色X" not in blob
    assert "只在本会话" not in blob
    assert "公共演化事实" not in blob
