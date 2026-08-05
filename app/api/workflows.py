"""Workflow definition + run REST API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.workflow.engine import get_workflow_engine
from app.workflow.store import get_workflow_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

# Track in-flight background runs (best-effort; process-local).
_bg_tasks: set[asyncio.Task[Any]] = set()


class WorkflowBody(BaseModel):
    id: str | None = None
    name: str = Field(..., min_length=1)
    description: str = ""
    enabled: bool = True
    version: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    # full raw optional
    raw: dict[str, Any] | None = None


class WorkflowRunBody(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    trigger: str = "manual"
    background: bool = False


class WorkflowResumeBody(BaseModel):
    approved: bool = True
    note: str = ""
    background: bool = False


def _definition_summary(data: dict[str, Any]) -> dict[str, Any]:
    steps = data.get("steps") or []
    has_agent = any(
        isinstance(s, dict) and str(s.get("type") or "").lower() == "agent" for s in steps
    )
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "description": data.get("description") or "",
        "version": data.get("version") or "0.1.0",
        "enabled": data.get("enabled", True),
        "step_count": len(steps),
        "updated_at": data.get("updated_at") or "",
        "has_agent_steps": has_agent,
        "builtin": bool(data.get("builtin")),
    }


@router.get("")
async def list_workflows() -> list[dict[str, Any]]:
    store = get_workflow_store()
    await store.ensure_seed()
    items = await store.list_definitions()
    # enrich has_agent_steps when missing (older list path)
    out: list[dict[str, Any]] = []
    for it in items:
        if "has_agent_steps" in it:
            out.append(it)
            continue
        full = await store.get_definition(str(it.get("id") or ""))
        if full:
            out.append({**it, **{k: v for k, v in _definition_summary(full).items() if k in ("has_agent_steps", "builtin")}})
        else:
            out.append(it)
    return out


class WorkflowRunsDeleteBody(BaseModel):
    ids: list[str] = Field(default_factory=list)


@router.get("/runs")
async def list_runs(
    workflow_id: str | None = None,
    limit: int = Query(30, ge=1, le=100),
) -> list[dict[str, Any]]:
    return await get_workflow_store().list_runs(workflow_id=workflow_id, limit=limit)


@router.delete("/runs")
async def clear_runs(
    workflow_id: str | None = None,
) -> dict[str, Any]:
    """Clear run history (all, or only one workflow)."""
    return await get_workflow_store().clear_runs(workflow_id=workflow_id or None)


@router.post("/runs/bulk-delete")
async def bulk_delete_runs(body: WorkflowRunsDeleteBody) -> dict[str, Any]:
    """Delete selected run records by id."""
    ids = [str(x).strip() for x in (body.ids or []) if str(x).strip()]
    if not ids:
        raise HTTPException(400, "ids required")
    return await get_workflow_store().delete_runs(ids)


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    run = await get_workflow_store().get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str) -> dict[str, Any]:
    ok = await get_workflow_store().delete_run(run_id)
    if not ok:
        raise HTTPException(404, "Run not found")
    return {"ok": True, "id": run_id, "count": 1}


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, body: WorkflowResumeBody | None = None) -> dict[str, Any]:
    """Continue a run paused at human_gate."""
    body = body or WorkflowResumeBody()
    engine = get_workflow_engine()
    if body.background:
        # Mark running optimistically for pollers; resume will re-read state
        run = await get_workflow_store().get_run(run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        if run.get("status") != "waiting_human":
            raise HTTPException(400, f"Run status is {run.get('status')}, not waiting_human")

        async def _bg() -> None:
            try:
                await engine.resume(run_id, approved=body.approved, note=body.note or "")
            except Exception:
                logger.exception("Background resume failed %s", run_id)

        task = asyncio.create_task(_bg())
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)
        return {
            "ok": True,
            "status": "running" if body.approved else "cancelled",
            "background": True,
            "run": run,
            "message": "resuming in background" if body.approved else "cancelling",
        }

    result = await engine.resume(
        run_id, approved=body.approved, note=body.note or ""
    )
    if not result.get("ok") and not result.get("run"):
        raise HTTPException(400, result.get("error") or "resume failed")
    return result


@router.get("/{wf_id}")
async def get_workflow(wf_id: str) -> dict[str, Any]:
    store = get_workflow_store()
    await store.ensure_seed()
    data = await store.get_definition(wf_id)
    if not data:
        raise HTTPException(404, "Workflow not found")
    return data


@router.post("")
async def upsert_workflow(body: WorkflowBody) -> dict[str, Any]:
    store = get_workflow_store()
    if body.raw:
        data = await store.save_definition(name=body.name, raw=body.raw, wf_id=body.id)
    else:
        data = await store.save_definition(
            name=body.name,
            description=body.description,
            steps=body.steps,
            inputs=body.inputs,
            enabled=body.enabled,
            wf_id=body.id,
            version=body.version,
        )
    return data


@router.delete("/{wf_id}")
async def delete_workflow(wf_id: str) -> dict[str, Any]:
    result = await get_workflow_store().delete_definition(wf_id)
    if not result.get("ok"):
        raise HTTPException(404, result.get("error") or "Workflow not found")
    return result


@router.post("/{wf_id}/run")
async def run_workflow(wf_id: str, body: WorkflowRunBody | None = None) -> dict[str, Any]:
    """Direct execute workflow (UI / agent). Pass inputs for {{inputs.*}}.

    When ``background=true``, create the run and execute in a task; poll GET /runs/{id}.
    """
    body = body or WorkflowRunBody()
    engine = get_workflow_engine()
    inputs = body.inputs or {}
    trigger = body.trigger or "manual"

    if body.background:
        prepared = await engine.prepare_run(wf_id, inputs=inputs, trigger=trigger)
        if not prepared.get("ok"):
            if prepared.get("run"):
                return prepared
            raise HTTPException(400, prepared.get("error") or "run failed")

        definition = prepared["definition"]
        run = prepared["run"]
        ctx = prepared["ctx"]
        max_steps = int(prepared["max_steps"])

        async def _bg() -> None:
            try:
                await engine._execute_from(  # noqa: SLF001 — intentional internal continue
                    definition, run, ctx, start_index=0, max_steps=max_steps
                )
            except Exception as exc:
                logger.exception("Background workflow failed %s", run.get("id"))
                try:
                    run["status"] = "failed"
                    run["error"] = str(exc)
                    await get_workflow_store().save_run(run)
                except Exception:
                    pass

        task = asyncio.create_task(_bg())
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)
        return {
            "ok": True,
            "status": "running",
            "background": True,
            "run": run,
            "message": "started in background; poll GET /api/workflows/runs/{id}",
        }

    result = await engine.run(wf_id, inputs=inputs, trigger=trigger)
    if not result.get("ok") and not result.get("run"):
        raise HTTPException(400, result.get("error") or "run failed")
    return result
