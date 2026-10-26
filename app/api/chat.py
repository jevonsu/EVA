"""Chat endpoints.

Background runs (POST /async) keep generating after the browser disconnects
or the user switches sessions. Live UI can subscribe to /runs/{id}/events.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.agent.core import get_agent
from app.models.schemas import ChatRequest
from app.services.chat_runs import get_chat_run_manager

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger(__name__)


@router.post("/async")
async def chat_async(body: ChatRequest) -> dict:
    """Start a background chat run; returns immediately with run_id + session_id.

    Generation continues if the client closes the page or switches conversations.
    """
    if not (body.message or "").strip():
        raise HTTPException(400, "message required")
    mgr = get_chat_run_manager()
    try:
        run = await mgr.start(
            message=body.message.strip(),
            session_id=body.session_id,
            use_tools=body.use_tools,
            use_memory=body.use_memory,
            model=body.model,
            session_title=body.session_title,
            metadata=body.metadata,
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("chat async start failed")
        raise HTTPException(500, str(exc)) from exc
    return {"ok": True, **run}


@router.get("/runs")
async def list_runs(
    session_id: str | None = Query(default=None),
    active_only: bool = Query(default=False),
) -> dict:
    mgr = get_chat_run_manager()
    if session_id:
        rows = mgr.list_for_session(session_id)
        if active_only:
            rows = [r for r in rows if r.get("status") == "running"]
        return {"runs": rows, "session_id": session_id}
    active_sessions = mgr.list_active_sessions()
    return {"active_sessions": active_sessions, "runs": []}


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    run = get_chat_run_manager().get(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict:
    run = get_chat_run_manager().cancel(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return {"ok": True, **run}


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str) -> StreamingResponse:
    """SSE: log lines + final result/error. Safe to disconnect (run keeps going)."""
    mgr = get_chat_run_manager()
    run = mgr.get(run_id)
    if not run:
        raise HTTPException(404, "Run not found")

    async def event_gen():
        q = mgr.subscribe(run_id)
        try:
            # Already finished when subscribed
            cur = mgr.get(run_id)
            if cur and cur.get("status") != "running":
                if cur.get("status") == "completed" and cur.get("result"):
                    payload = {"type": "result", **cur["result"], "run_id": run_id}
                    yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'error', 'detail': cur.get('error') or cur.get('status')}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return

            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # Keepalive + status check
                    cur = mgr.get(run_id)
                    if not cur or cur.get("status") != "running":
                        if cur and cur.get("status") == "completed" and cur.get("result"):
                            payload = {"type": "result", **cur["result"], "run_id": run_id}
                            yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
                        elif cur:
                            yield f"data: {json.dumps({'type': 'error', 'detail': cur.get('error') or cur.get('status')}, ensure_ascii=False)}\n\n"
                        yield "data: [DONE]\n\n"
                        return
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
                    continue

                yield f"data: {json.dumps(evt, ensure_ascii=False, default=str)}\n\n"
                if evt.get("type") in ("result", "error"):
                    yield "data: [DONE]\n\n"
                    return
        finally:
            mgr.unsubscribe(run_id, q)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("")
async def chat(body: ChatRequest) -> StreamingResponse:
    """Legacy-compatible: start background run and stream its events (detach-safe)."""
    if body.stream:
        raise HTTPException(
            status_code=400,
            detail="Use POST /api/chat/stream for streaming responses",
        )

    mgr = get_chat_run_manager()
    try:
        run = await mgr.start(
            message=body.message.strip(),
            session_id=body.session_id,
            use_tools=body.use_tools,
            use_memory=body.use_memory,
            model=body.model,
            session_title=body.session_title,
            metadata=body.metadata,
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc

    run_id = run["run_id"]

    async def event_gen():
        # Emit started so client can store run_id even if it disconnects later
        yield f"data: {json.dumps({'type': 'started', 'run_id': run_id, 'session_id': run['session_id']}, ensure_ascii=False)}\n\n"
        q = mgr.subscribe(run_id)
        try:
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    cur = mgr.get(run_id)
                    if not cur or cur.get("status") != "running":
                        if cur and cur.get("status") == "completed" and cur.get("result"):
                            payload = {"type": "result", **cur["result"], "run_id": run_id}
                            yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
                        elif cur:
                            yield f"data: {json.dumps({'type': 'error', 'detail': cur.get('error') or cur.get('status')}, ensure_ascii=False)}\n\n"
                        yield "data: [DONE]\n\n"
                        return
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
                    continue
                yield f"data: {json.dumps(evt, ensure_ascii=False, default=str)}\n\n"
                if evt.get("type") in ("result", "error"):
                    yield "data: [DONE]\n\n"
                    return
        finally:
            # Client left — run continues in background
            mgr.unsubscribe(run_id, q)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/stream")
async def chat_stream(body: ChatRequest) -> StreamingResponse:
    """Token stream (no tools). Prefer /async or POST / for detachable tool runs."""
    agent = get_agent()

    async def event_gen():
        try:
            async for chunk in agent.chat_stream(
                body.message,
                session_id=body.session_id,
                use_memory=body.use_memory,
                model=body.model,
                session_title=body.session_title,
            ):
                for line in chunk.split("\n"):
                    yield f"data: {line}\n"
                yield "\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:
            yield f"data: [ERROR] {exc}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")