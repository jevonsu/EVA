"""Isolated regressions: never start/stop a real process or start EVA.
All process, audit, model and external-write interfaces are blocked/mocked.
Only the authorization DB writes to pytest's temporary directory.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services import process_actions as actions
from app.services import process_control as pc
from app.services import proc_tree, service_manager, terminal_exec
from app.agent.core import Agent


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(actions, "db_path", lambda: tmp_path / "actions.db")
    monkeypatch.setattr(pc, "_audit", Mock())
    # Exercise the Windows branch without changing host os.name.
    monkeypatch.setattr(pc, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(pc, "_psutil", Mock(side_effect=AssertionError("real psutil forbidden")))
    monkeypatch.setattr(proc_tree, "matches", Mock(return_value=True))
    monkeypatch.setattr(pc, "_protected_self", lambda: {})
    monkeypatch.setattr(service_manager, "mark_stopped", Mock(return_value=True))
    monkeypatch.setattr(terminal_exec, "mark_job_killed", Mock())
    monkeypatch.setattr(pc.subprocess, "run", Mock(side_effect=AssertionError("external command forbidden")))
    monkeypatch.setattr(pc, "_terminate", Mock(return_value={
        "exited": [42], "still_running": [], "unknown": [], "graceful": [42], "forced": [], "errors": {},
    }))
    info = {"ok": True, "pid": 42, "name": "fake", "create_time": 100.0, "fp": "fake-fingerprint",
            "children": [], "children_count": 0, "_origin": {"kind": "service", "id": "svc"}}
    monkeypatch.setattr(pc, "describe", Mock(side_effect=lambda pid: dict(info, pid=pid)))
    turn = {"id": "T1", "sid": "S", "message": "结束进程"}
    monkeypatch.setattr(pc, "_turn", lambda: (turn["id"], turn["sid"], turn["message"]))
    return SimpleNamespace(info=info, turn=turn, tmp=tmp_path)


# Save function before fixture mocks it; it receives only fake psutil handles.
terminate_impl = pc._terminate


def card(sid="S", pid=42):
    # issue() is also tested with real transactional temporary SQLite writes.
    return pc.query(pid=pid)


def history(form):
    return [{"role": "assistant", "content": "请确认", "metadata": {"form": form}}]


def agent(hist):
    a = Agent.__new__(Agent)
    a.llm = SimpleNamespace(is_configured=True, is_cli=False, model="mock", chat=AsyncMock(side_effect=AssertionError("model forbidden")))
    a.settings = SimpleNamespace(max_history_messages=40, max_tool_rounds=5)
    a._agent_cfg = lambda: {}
    saved = []
    async def append(sid, messages, **kw):
        saved.extend(messages)
    a.sessions = SimpleNamespace(get=AsyncMock(return_value={"session_id": "S"}),
                                get_messages=AsyncMock(return_value=hist),
                                append_messages=AsyncMock(side_effect=append))
    a.saved = saved
    return a


async def submit(a, form, message="同意", choice="process", sid="S", **extra):
    return await a.chat(message, session_id=sid,
                        form_reply={"_form_id": form["id"], "choice": choice, **extra})


class Denied(Exception): pass
class Gone(Exception): pass


def fake_ps(constructor):
    return SimpleNamespace(Process=constructor, AccessDenied=Denied, NoSuchProcess=Gone, STATUS_ZOMBIE="zombie")


@pytest.mark.parametrize("exception,exited,unknown", [(Denied("access denied"), [], [42]),
                                                       (Gone(), [42], []),
                                                       (RuntimeError("inspection failed"), [], [42])])
def test_construction_error_never_becomes_exit(monkeypatch, exception, exited, unknown):
    monkeypatch.setattr(pc, "_psutil", lambda: fake_ps(Mock(side_effect=exception)))
    monkeypatch.setattr(pc, "_wait_gone", lambda *a: ([], []))
    r = terminate_impl([42])
    assert r["exited"] == exited and r["unknown"] == unknown


@pytest.mark.parametrize("status", [Denied("status denied"), RuntimeError("status failed"), Gone(), "running", "zombie"])
def test_final_exit_check_is_conservative(monkeypatch, status):
    proc = SimpleNamespace(pid=42, is_running=Mock(return_value=True), terminate=Mock(), kill=Mock(),
                           status=Mock(side_effect=status) if isinstance(status, Exception) else Mock(return_value=status))
    monkeypatch.setattr(pc, "_psutil", lambda: fake_ps(lambda p: proc))
    monkeypatch.setattr(pc, "_wait_gone", lambda *a: ([], [proc]))
    monkeypatch.setattr(pc.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=0)))
    r = terminate_impl([42])
    if isinstance(status, Gone) or status == "zombie":
        assert r["exited"] == [42] and not r["unknown"]
    elif isinstance(status, Exception):
        assert r["unknown"] == [42] and not r["exited"]
    else:
        assert r["still_running"] == [42] and not r["exited"]


@pytest.mark.parametrize("unknown,still", [([42], []), ([], [42]), ([43], [])])
def test_failed_or_partial_exit_never_stops_service(sandbox, unknown, still):
    q = card()
    pc._terminate.return_value.update(exited=[] if 42 in unknown + still else [42], unknown=unknown, still_running=still)
    r = pc.kill_by_form_consent("S", 42, "process", form_id=q["form"]["id"])
    assert not r["ok"] and not r["killed"]
    assert "note" not in r
    service_manager.mark_stopped.assert_not_called()


@pytest.mark.asyncio
async def test_valid_card_executes_and_marks_resolved():
    q = card(); a = agent(history(q["form"]))
    r = await submit(a, q["form"])
    assert "已确认结束" in r.reply and r.resolved_form_id == q["form"]["id"]
    pc._terminate.assert_called_once_with([42])
    service_manager.mark_stopped.assert_called_once()
    a.llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_execution_exception_is_final_and_idempotent():
    q = card(); a = agent(history(q["form"]))
    pc._terminate.side_effect = RuntimeError("mock failure")
    r = await submit(a, q["form"])
    assert "未知" in r.reply and "已确认结束" not in r.reply
    assert actions.get(q["confirm_token"])["state"] == "failed"
    r2 = await submit(a, q["form"])
    assert "不会重复执行" in r2.reply
    pc._terminate.assert_called_once()
    service_manager.mark_stopped.assert_not_called()
    a.llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_storage_exception_does_not_call_model(monkeypatch):
    q = card(); a = agent(history(q["form"]))
    monkeypatch.setattr(actions, "claim", Mock(side_effect=OSError("mock DB unavailable")))
    r = await submit(a, q["form"])
    assert "未知" in r.reply
    pc._terminate.assert_not_called(); a.llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_finish_exception_keeps_claim_not_replayed(monkeypatch):
    q = card(); a = agent(history(q["form"]))
    monkeypatch.setattr(actions, "finish", Mock(side_effect=OSError("mock DB unavailable")))
    r = await submit(a, q["form"])
    assert "未知" in r.reply and actions.get(q["confirm_token"])["state"] == "executing"
    await submit(a, q["form"])
    pc._terminate.assert_called_once(); a.llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_history_write_exception_never_falls_through():
    q = card(); a = agent(history(q["form"]))
    a.sessions.append_messages.side_effect = OSError("mock history unavailable")
    r = await submit(a, q["form"])
    assert "未知" in r.reply
    pc._terminate.assert_called_once(); a.llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_long_agreement_after_plain_messages():
    q = card(); a = agent(history(q["form"]) + [{"role": "user", "content": "看到了"}, {"role": "assistant", "content": "好的"}])
    msg = "同意结束这个进程。" + "我已经阅读了刚才提供的进程作用、程序路径、子进程范围以及关闭后的影响说明。"
    assert len(msg) > 40
    r = await a.chat(msg, session_id="S")
    assert "已确认结束" in r.reply
    pc._terminate.assert_called_once(); a.llm.chat.assert_not_called()


@pytest.mark.parametrize("msg,classification", [("同意", "agree"), ("同意吗？", "ambiguous"),
    ("如果没影响就同意", "ambiguous"), ("不同意", "cancel"), ("先不要结束", "cancel"),
    ("我确认结束 PID 42", "agree"), ("这个进程有什么用", "ambiguous"),
    ("可以告诉我这个程序的用途", "ambiguous"), ("好的我看明白了", "ambiguous"),
    ("同意这个结论", "ambiguous"), ("yes terminate if safe", "ambiguous"),
    ("同意关闭后数据还在吗", "ambiguous"), ("同意结束，不要再问是否同意", "agree"),
    ("不同意，不要再问", "cancel")])
def test_consent_classifier(msg, classification):
    assert pc.classify_confirm_reply(msg) == classification


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["不同意", "先不要结束", "取消"])
async def test_typed_negative_revokes(reply):
    q = card(); a = agent(history(q["form"]))
    r = await a.chat(reply, session_id="S")
    assert "已取消" in r.reply
    assert actions.get(q["confirm_token"])["state"] == "cancelled"
    pc._terminate.assert_not_called()


@pytest.mark.asyncio
async def test_ambiguous_consent_not_executed_or_resolved():
    q = card(); a = agent(history(q["form"]))
    r = await a.chat("同意吗？", session_id="S")
    assert "未执行" in r.reply and r.resolved_form_id is None
    assert actions.get(q["confirm_token"])["state"] == "pending"
    pc._terminate.assert_not_called(); a.llm.chat.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("footer", [False, True])
async def test_cancel_card(footer):
    q = card(); a = agent(history(q["form"]))
    r = await submit(a, q["form"], choice="cancel", **({"_cancel": True} if footer else {}))
    assert "已取消" in r.reply and actions.get(q["confirm_token"])["state"] == "cancelled"
    pc._terminate.assert_not_called()


@pytest.mark.asyncio
async def test_old_card_cannot_execute_or_cancel_new_card():
    old = card(); new = card()
    a = agent(history(old["form"]) + history(new["form"]))
    r = await submit(a, old["form"], choice="cancel")
    assert "不匹配" in r.reply
    assert actions.get(new["confirm_token"])["state"] == "pending"
    r = pc.kill_by_form_consent("S", 42, "process", form_id=old["form"]["id"])
    assert not r["ok"]
    pc._terminate.assert_not_called()


@pytest.mark.parametrize("session,pid", [("other-session", 42), ("S", 999)])
def test_session_and_pid_binding(session, pid):
    q = card()
    r = pc.kill_by_form_consent(session, pid, "process", form_id=q["form"]["id"])
    assert not r["ok"]
    assert actions.get(q["confirm_token"])["state"] == "pending"
    pc._terminate.assert_not_called()


def test_missing_form_and_legacy_card_never_authorize():
    card()
    for fid in ("", "legacy-form"):
        assert not pc.kill_by_form_consent("S", 42, "process", form_id=fid)["ok"]
    pc._terminate.assert_not_called()


@pytest.mark.parametrize("mode", ["reuse", "hard_denied", "new_children"])
def test_identity_and_safety_are_preserved(sandbox, mode):
    q = card()
    if mode == "reuse": proc_tree.matches.return_value = False
    elif mode == "hard_denied": sandbox.info.update(hard_denied=True, deny_reason="EVA/系统关键进程禁止结束")
    else: sandbox.info.update(children=[{"pid": 43, "name": "new"}])
    r = pc.kill_by_form_consent("S", 42, "tree", form_id=q["form"]["id"])
    assert not r["ok"]
    pc._terminate.assert_not_called(); service_manager.mark_stopped.assert_not_called()


@pytest.mark.asyncio
async def test_expired_no_auto_reissue(monkeypatch):
    q = card(); a = agent(history(q["form"]))
    monkeypatch.setattr(pc.time, "time", lambda: 1e12)
    r = await submit(a, q["form"])
    assert "有效期" in r.reply and r.form is None
    pc._terminate.assert_not_called()


def test_atomic_claim_across_connections_and_restart():
    q = card(); token = q["confirm_token"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: actions.claim(token), range(16)))
    assert sum(outcomes) == 1
    # New DB connections (including after restart) cannot re-claim executing.
    assert not actions.claim(token) and actions.get(token)["state"] == "executing"


def test_concurrent_execution_at_most_once():
    q = card()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: pc.kill_by_form_consent("S", 42, "process", form_id=q["form"]["id"]), range(16)))
    assert sum(bool(r["ok"]) for r in results) == 1
    pc._terminate.assert_called_once()


@pytest.mark.asyncio
async def test_resolved_history_does_not_reenter_model():
    q = card(); a = agent(history(q["form"]))
    await submit(a, q["form"])
    a.sessions.get_messages.return_value = history(q["form"]) + a.saved
    r = await a.chat("同意", session_id="S")
    assert "已经处理" in r.reply
    pc._terminate.assert_called_once(); a.llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_generic_ask_is_not_authorization():
    q = card(); f = dict(q["form"], purpose="quiz")
    a = agent(history(f))
    r = await a._handle_kill_confirm_reply(session_id="S", message="同意", history=history(f),
        form_reply={"_form_id": f["id"], "choice": "process"}, max_history=40)
    assert r is None
    pc._terminate.assert_not_called()


@pytest.mark.asyncio
async def test_stream_uses_same_handler(monkeypatch):
    q = card(); a = agent(history(q["form"]))
    # Persona/routing work before history is unrelated; don't let it read app state.
    import app.agent.persona as persona
    monkeypatch.setattr(persona, "build_persona_prompt", lambda *a, **k: "mock")
    monkeypatch.setattr(persona, "use_compact_persona", lambda *a, **k: True)
    result = [s async for s in a.chat_stream("同意", session_id="S",
        form_reply={"_form_id": q["form"]["id"], "choice": "process"})]
    assert "已确认结束" in "".join(result)
    pc._terminate.assert_called_once(); a.llm.chat.assert_not_called()


def test_model_cannot_use_same_turn_or_cross_session(sandbox):
    q = card()
    sandbox.turn["message"] = "同意"
    assert not pc.kill(42, q["confirm_token"])["ok"]
    sandbox.turn.update(id="T2", sid="foreign")
    assert not pc.kill(42, q["confirm_token"])["ok"]
    sandbox.turn.update(sid=None)
    assert not pc.kill(42, q["confirm_token"])["ok"]
    pc._terminate.assert_not_called()


@pytest.mark.asyncio
async def test_typed_different_pid_is_not_authorization():
    q = card(); a = agent(history(q["form"]))
    r = await a.chat("同意结束 PID 999", session_id="S")
    assert "不一致" in r.reply
    pc._terminate.assert_not_called()


@pytest.mark.asyncio
async def test_negative_text_wins_over_card_agree():
    q = card(); a = agent(history(q["form"]))
    r = await submit(a, q["form"], message="不同意")
    assert "已取消" in r.reply
    pc._terminate.assert_not_called()


@pytest.mark.asyncio
async def test_foreign_session_submit_never_calls_model():
    q = card(); a = agent(history(q["form"]))
    r = await submit(a, q["form"], sid="foreign")
    assert "没有与这张卡绑定" in r.reply
    pc._terminate.assert_not_called(); a.llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_terminal_tree_and_bookkeeping(sandbox):
    sandbox.info.update(children=[{"pid": 43, "name": "child"}], children_count=1)
    pc._terminate.return_value["exited"] = [42, 43]
    q = card()
    pc.tree_only_form(q["form"], "后台任务", {"tool": "terminal", "job_id": "mock-job"})
    a = agent(history(q["form"]))
    r = await submit(a, q["form"], choice="tree")
    assert "已确认结束" in r.reply
    pc._terminate.assert_called_once_with([43, 42])
    terminal_exec.mark_job_killed.assert_called_once_with("mock-job")


@pytest.mark.asyncio
async def test_terminal_failure_never_marks_job():
    q = card()
    pc.tree_only_form(q["form"], "后台任务", {"tool": "terminal", "job_id": "mock-job"})
    pc._terminate.side_effect = RuntimeError("fake")
    a = agent(history(q["form"]))
    r = await submit(a, q["form"], choice="tree")
    assert "未知" in r.reply
    terminal_exec.mark_job_killed.assert_not_called()


@pytest.mark.asyncio
async def test_path_block_never_executes(monkeypatch):
    from app.tools import protection
    q = card(); a = agent(history(q["form"]))
    monkeypatch.setattr(protection, "is_action_blocked", lambda *args: True)
    r = await submit(a, q["form"])
    assert "禁止" in r.reply
    pc._terminate.assert_not_called()


@pytest.mark.asyncio
async def test_stream_api_forwards_form_reply(monkeypatch):
    import importlib
    api = importlib.import_module("app.api.chat")
    captured = {}
    async def stream(message, **kw):
        captured.update(kw)
        yield "mock result"
    monkeypatch.setattr(api, "get_agent", lambda: SimpleNamespace(chat_stream=stream))
    body = api.ChatRequest(message="同意", session_id="S", metadata={"form_reply": {"_form_id": "test", "choice": "process"}})
    response = await api.chat_stream(body)
    chunks = [s async for s in response.body_iterator]
    assert captured["form_reply"] == body.metadata["form_reply"]
    assert "mock result" in "".join(chunks)


@pytest.mark.parametrize("mode", ["denied", "unknown", "alive", "exception", "identity"])
def test_internal_service_stop_never_false_success(monkeypatch, mode):
    record = {"id": "svc", "pid": 42, "status": "running", "create_time": 100.0, "fp": "fake-fingerprint"}
    monkeypatch.setattr(service_manager, "_load", lambda: [record])
    save = Mock(); monkeypatch.setattr(service_manager, "_save", save)
    monkeypatch.setattr(service_manager, "_public", lambda r: dict(r))
    monkeypatch.setattr(pc, "_psutil", lambda: fake_ps(Mock(side_effect=Denied("mock")) if mode == "denied" else Mock()))
    if mode == "identity": proc_tree.matches.return_value = False
    if mode == "unknown": pc._terminate.return_value.update(exited=[], unknown=[42])
    if mode == "alive": pc._terminate.return_value.update(exited=[], still_running=[42])
    if mode == "exception": pc._terminate.side_effect = RuntimeError("mock")
    r = service_manager.stop_service("svc")
    assert not r["ok"] and not r.get("stopped") and record["status"] == "running"
    save.assert_not_called()


def test_internal_service_no_such_process_confirms_exit(monkeypatch):
    record = {"id": "svc", "pid": 42, "status": "running"}
    monkeypatch.setattr(service_manager, "_load", lambda: [record])
    monkeypatch.setattr(service_manager, "_save", Mock())
    monkeypatch.setattr(service_manager, "_public", lambda r: dict(r))
    monkeypatch.setattr(pc, "_psutil", lambda: fake_ps(Mock(side_effect=Gone())))
    r = service_manager.stop_service("svc")
    assert r["ok"] and r["already"] == "exited" and not r.get("stopped")
    pc._terminate.assert_not_called()


def test_model_and_form_share_one_shot_authorization(sandbox):
    q = card(); sandbox.turn.update(id="T2", message="同意")
    assert pc.kill(42, q["confirm_token"])["killed"]
    assert not pc.kill_by_form_consent("S", 42, "process", form_id=q["form"]["id"])["ok"]
    pc._terminate.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_cannot_reset_an_executing_authorization():
    q = card(); assert actions.claim(q["confirm_token"])
    a = agent(history(q["form"]))
    r = await submit(a, q["form"], choice="cancel")
    assert "不能再次撤销" in r.reply
    assert actions.get(q["confirm_token"])["state"] == "executing"
    pc._terminate.assert_not_called()


@pytest.mark.parametrize("mode", ["denied", "gone", "reused"])
def test_service_status_unknown_is_not_exited(monkeypatch, mode):
    record = {"pid": 42, "status": "running", "create_time": 100.0, "fp": "fake"}
    proc_tree.matches.return_value = False
    ctor = (Mock(side_effect=Denied()) if mode == "denied" else
            Mock(side_effect=Gone()) if mode == "gone" else
            Mock(return_value=SimpleNamespace(is_running=lambda: True, create_time=lambda: 999.0)))
    monkeypatch.setattr(pc, "_psutil", lambda: fake_ps(ctor))
    status = service_manager._status_of(record)
    if mode == "denied":
        assert status == "running" and "无法核实" in record["status_note"]
    else:
        assert status == "exited"
