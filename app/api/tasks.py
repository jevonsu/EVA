"""Scheduled / background task endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.schemas import TaskCreate, TaskInfo, TaskUpdate
from app.scheduler.manager import get_scheduler

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskInfo])
async def list_tasks() -> list[TaskInfo]:
    return await get_scheduler().list_tasks()


@router.post("", response_model=TaskInfo)
async def create_task(body: TaskCreate) -> TaskInfo:
    try:
        return await get_scheduler().create(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{task_id}", response_model=TaskInfo)
async def get_task(task_id: str) -> TaskInfo:
    task = await get_scheduler().get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.put("/{task_id}", response_model=TaskInfo)
async def update_task(task_id: str, body: TaskUpdate) -> TaskInfo:
    """Edit an existing scheduled task (name, prompt, schedule, session, enabled)."""
    try:
        task = await get_scheduler().update(task_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/{task_id}/run", response_model=TaskInfo)
async def run_task(task_id: str) -> TaskInfo:
    task = await get_scheduler().run_now(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.delete("/{task_id}")
async def delete_task(task_id: str) -> dict:
    """Hard-delete task (remove from store + unschedule)."""
    ok = await get_scheduler().delete(task_id)
    if not ok:
        # fall back to cancel if already only soft-state
        ok = await get_scheduler().cancel(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True, "id": task_id}
