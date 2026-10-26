"""Background chat runs: survive client disconnect / session switch.

Runs are in-process (memory). Restarting the server drops active runs.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Keep strong refs so tasks are not GC'd while running
_bg_tasks: set[asyncio.Task] = set()
_MAX_LOGS = 80
_MAX_FINISHED = 40


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatRunManager:
    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}
        # session_id -> active run_id
        self._session_run: dict[str, str] = {}
        # run_id -> list of asyncio.Queue for SSE log fans
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

    def get(self, run_id: str) -> dict[str, Any] | None:
        r = self._runs.get(run_id)
        return self._public(r) if r else None

    def list_for_session(self, session_id: str) -> list[dict[str, Any]]:
        out = []
        for r in self._runs.values():
            if r.get("session_id") == session_id:
                out.append(self._public(r))
        out.sort(key=lambda x: x.get("started_at") or "", reverse=True)
        return out

    def active_run_id(self, session_id: str) -> str | None:
        rid = self._session_run.get(session_id)
        if not rid:
            return None
        r = self._runs.get(rid)
        if r and r.get("status") == "running":
            return rid
        return None

    def list_active_sessions(self) -> list[str]:
        return [
            sid
            for sid, rid in self._session_run.items()
            if (self._runs.get(rid) or {}).get("status") == "running"
        ]

    def _public(self, r: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": r["run_id"],
            "session_id": r["session_id"],
            "status": r["status"],
            "message": r.get("message") or "",
            "error": r.get("error"),
            "started_at": r.get("started_at"),
            "finished_at": r.get("finished_at"),
            "result": r.get("result"),
            "logs": list(r.get("logs") or [])[-20:],
        }

    def subscribe(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.setdefault(run_id, []).append(q)
        # Replay recent logs
        r = self._runs.get(run_id)
        if r:
            for line in list(r.get("logs") or [])[-30:]:
                try:
                    q.put_nowait({"type": "log", "line": line})
                except asyncio.QueueFull:
                    break
            if r.get("status") != "running":
                try:
                    q.put_nowait(self._terminal_event(r))
                except asyncio.QueueFull:
                    pass
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(run_id) or []
        if q in subs:
            subs.remove(q)
        if not subs:
            self._subscribers.pop(run_id, None)

    def _terminal_event(self, r: dict[str, Any]) -> dict[str, Any]:
        if r.get("status") == "completed":
            return {"type": "result", **(r.get("result") or {}), "run_id": r["run_id"]}
        if r.get("status") == "cancelled":
            return {"type": "error", "detail": "cancelled", "run_id": r["run_id"]}
        return {
            "type": "error",
            "detail": r.get("error") or "failed",
            "run_id": r["run_id"],
        }

    def _push(self, run_id: str, event: dict[str, Any]) -> None:
        for q in list(self._subscribers.get(run_id) or []):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except Exception:
                    pass
                try:
                    q.put_nowait(event)
                except Exception:
                    pass

    def _append_log(self, run: dict[str, Any], line: str) -> None:
        logs: deque = run.setdefault("logs", deque(maxlen=_MAX_LOGS))
        if not isinstance(logs, deque):
            logs = deque(logs, maxlen=_MAX_LOGS)
            run["logs"] = logs
        logs.append(line)
        self._push(run["run_id"], {"type": "log", "line": line})

    def cancel(self, run_id: str) -> dict[str, Any] | None:
        r = self._runs.get(run_id)
        if not r:
            return None
        if r.get("status") != "running":
            return self._public(r)
        task: asyncio.Task | None = r.get("_task")
        r["status"] = "cancelled"
        r["finished_at"] = _now()
        r["error"] = "cancelled"
        if task and not task.done():
            task.cancel()
        sid = r.get("session_id")
        if sid and self._session_run.get(sid) == run_id:
            self._session_run.pop(sid, None)
        self._push(run_id, self._terminal_event(r))
        return self._public(r)

    async def start(
        self,
        *,
        message: str,
        session_id: str | None,
        use_tools: bool = True,
        use_memory: bool = True,
        model: str | None = None,
        session_title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.agent.core import get_agent

        from app.memory.session import suggest_session_title

        agent = get_agent()
        title = (
            (session_title or "").strip()
            or suggest_session_title(message)
            or "对话"
        )[:80]
        # Ensure session exists up front so client can switch and still find it
        if session_id:
            session = await agent.sessions.get(session_id)
            if session is None:
                session = await agent.sessions.create(title=title)
                session_id = session["session_id"]
        else:
            session = await agent.sessions.create(title=title)
            session_id = session["session_id"]

        # One active run per session: cancel previous
        prev = self.active_run_id(session_id)
        if prev:
            self.cancel(prev)

        run_id = uuid.uuid4().hex
        run: dict[str, Any] = {
            "run_id": run_id,
            "session_id": session_id,
            "status": "running",
            "message": message,
            "use_tools": use_tools,
            "use_memory": use_memory,
            "model": model,
            "metadata": dict(metadata or {}),
            "error": None,
            "result": None,
            "started_at": _now(),
            "finished_at": None,
            "logs": deque(maxlen=_MAX_LOGS),
            "_task": None,
        }
        self._runs[run_id] = run
        self._session_run[session_id] = run_id
        self._gc_finished()

        task = asyncio.create_task(
            self._execute(
                run_id, message, session_id, use_tools, use_memory, model, metadata
            ),
            name=f"chat-run-{run_id[:8]}",
        )
        run["_task"] = task
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)

        return self._public(run)

    async def _execute(
        self,
        run_id: str,
        message: str,
        session_id: str,
        use_tools: bool,
        use_memory: bool,
        model: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        from app.agent.core import get_agent

        run = self._runs.get(run_id)
        if not run:
            return

        log_q: asyncio.Queue = asyncio.Queue()
        handler = _RunLogHandler(log_q)
        root = logging.getLogger()
        root.addHandler(handler)

        async def _drain_logs() -> None:
            while True:
                try:
                    line = log_q.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if run.get("status") == "running":
                    self._append_log(run, line)

        chat_task: asyncio.Task | None = None
        try:
            agent = get_agent()
            chat_task = asyncio.create_task(
                agent.chat(
                    message,
                    session_id=session_id,
                    use_tools=use_tools,
                    use_memory=use_memory,
                    model=model,
                    allow_deputy=True,
                    use_deputy=bool((metadata or {}).get("use_deputy")),
                    skip_deputy=bool((metadata or {}).get("skip_deputy")),
                    form_reply=(metadata or {}).get("form_reply"),
                )
            )
            while not chat_task.done():
                await _drain_logs()
                await asyncio.wait({chat_task}, timeout=0.2)
            await _drain_logs()
            result = await chat_task

            if run.get("status") == "cancelled":
                return

            result_data = {
                "session_id": result.session_id,
                "reply": result.reply,
                "model": result.model,
                "tool_calls": [
                    {
                        "id": t.id,
                        "name": t.name,
                        "arguments": (
                            {
                                k: (
                                    v
                                    if not isinstance(v, str) or len(v) <= 80
                                    else v[:80] + "…"
                                )
                                for k, v in (t.arguments or {}).items()
                            }
                            if isinstance(t.arguments, dict)
                            else {}
                        ),
                        "result": (
                            (t.result or "")[:200]
                            if not str(t.result or "").lstrip().startswith(
                                ("def ", "import ", "from ", "async def")
                            )
                            else "ok（源码已省略）"
                        ),
                    }
                    for t in (result.tool_calls or [])
                ],
                "usage": result.usage,
                "ask_deputy": bool(getattr(result, "ask_deputy", False)),
                "used_deputy": bool(getattr(result, "used_deputy", False)),
                "llm_name": getattr(result, "llm_name", None),
                "deputy_reason": getattr(result, "deputy_reason", None),
                "form": getattr(result, "form", None),
            }
            run["status"] = "completed"
            run["result"] = result_data
            run["finished_at"] = _now()
            if self._session_run.get(session_id) == run_id:
                self._session_run.pop(session_id, None)
            self._push(run_id, {"type": "result", **result_data, "run_id": run_id})
            logger.info("Chat run %s completed session=%s", run_id[:8], session_id[:8])
        except asyncio.CancelledError:
            if chat_task and not chat_task.done():
                chat_task.cancel()
                try:
                    await chat_task
                except (asyncio.CancelledError, Exception):
                    pass
            run["status"] = "cancelled"
            run["error"] = "cancelled"
            run["finished_at"] = _now()
            if self._session_run.get(session_id) == run_id:
                self._session_run.pop(session_id, None)
            self._push(run_id, self._terminal_event(run))
        except Exception as exc:
            logger.exception("Chat run %s failed", run_id[:8])
            if run.get("status") == "cancelled":
                return
            run["status"] = "failed"
            run["error"] = str(exc)
            run["finished_at"] = _now()
            if self._session_run.get(session_id) == run_id:
                self._session_run.pop(session_id, None)
            self._push(run_id, self._terminal_event(run))
        finally:
            root.removeHandler(handler)
            await _drain_logs()
            run["_task"] = None

    def _gc_finished(self) -> None:
        finished = [
            r
            for r in self._runs.values()
            if r.get("status") in ("completed", "failed", "cancelled")
        ]
        if len(finished) <= _MAX_FINISHED:
            return
        finished.sort(key=lambda x: x.get("finished_at") or "")
        for r in finished[: max(0, len(finished) - _MAX_FINISHED)]:
            rid = r["run_id"]
            self._runs.pop(rid, None)
            self._subscribers.pop(rid, None)


class _RunLogHandler(logging.Handler):
    def __init__(self, q: asyncio.Queue) -> None:
        super().__init__()
        self.q = q
        self.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.q.put_nowait(self.format(record))
        except Exception:
            pass


_manager: ChatRunManager | None = None


def get_chat_run_manager() -> ChatRunManager:
    global _manager
    if _manager is None:
        _manager = ChatRunManager()
    return _manager
