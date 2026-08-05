"""Background / cron task scheduler backed by APScheduler + JSON store."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.models.schemas import TaskCreate, TaskInfo, TaskStatus, TaskUpdate

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TaskScheduler:
    def __init__(self) -> None:
        settings = get_settings()
        self.path = settings.data_dir / "tasks" / "tasks.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._tasks: dict[str, dict[str, Any]] = {}
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        await self._load()
        for task in self._tasks.values():
            if task.get("enabled") and task.get("status") != TaskStatus.cancelled.value:
                self._schedule(task)
        self._scheduler.start()
        self._started = True
        logger.info("Task scheduler started with %d tasks", len(self._tasks))

    async def shutdown(self) -> None:
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False

    async def _load(self) -> None:
        async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
            raw = await f.read()
        rows = json.loads(raw or "[]")
        self._tasks = {r["id"]: r for r in rows}

    async def _save(self) -> None:
        rows = list(self._tasks.values())
        async with aiofiles.open(self.path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(rows, ensure_ascii=False, indent=2, default=str))

    def _to_info(self, row: dict[str, Any]) -> TaskInfo:
        meta = dict(row.get("metadata") or {})
        # surface last_session_id for UI without breaking schema
        if row.get("last_session_id") and "last_session_id" not in meta:
            meta["last_session_id"] = row.get("last_session_id")
        return TaskInfo(
            id=row["id"],
            name=row["name"],
            prompt=row["prompt"],
            session_id=row.get("session_id"),
            cron=row.get("cron"),
            interval_seconds=row.get("interval_seconds"),
            run_once=bool(row.get("run_once")),
            enabled=bool(row.get("enabled", True)),
            status=TaskStatus(row.get("status", "pending")),
            last_run_at=datetime.fromisoformat(row["last_run_at"])
            if row.get("last_run_at")
            else None,
            last_result=row.get("last_result"),
            last_error=row.get("last_error"),
            created_at=datetime.fromisoformat(row["created_at"]),
            metadata=meta,
        )

    def _schedule(self, task: dict[str, Any]) -> None:
        job_id = f"task-{task['id']}"
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

        trigger: Any
        if task.get("run_once"):
            trigger = DateTrigger(run_date=_now())
        elif task.get("cron"):
            trigger = CronTrigger.from_crontab(task["cron"], timezone="UTC")
        elif task.get("interval_seconds"):
            trigger = IntervalTrigger(seconds=int(task["interval_seconds"]))
        else:
            logger.warning("Task %s has no schedule; skip", task["id"])
            return

        self._scheduler.add_job(
            self._run_task,
            trigger=trigger,
            id=job_id,
            args=[task["id"]],
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    async def _run_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if not task or not task.get("enabled"):
            return

        task["status"] = TaskStatus.running.value
        await self._save()
        logger.info("Running scheduled task %s: %s", task_id, task["name"])

        try:
            from app.agent.core import get_agent

            agent = get_agent()
            meta = task.get("metadata") or {}
            # always_new_session: 每次执行开新对话；否则写入固定 session_id（任务结果出现在该对话）
            always_new = bool(meta.get("always_new_session"))
            sid = None if always_new else (task.get("session_id") or None)
            result = await agent.chat(
                task["prompt"],
                session_id=sid,
                use_tools=True,
                use_memory=True,
            )
            task["status"] = TaskStatus.completed.value
            task["last_result"] = result.reply[:4000]
            task["last_error"] = None
            if always_new:
                # 记录最近一次产生的会话，便于面板「打开对话」；下次仍新建
                task["last_session_id"] = result.session_id
            else:
                task["session_id"] = result.session_id
                task["last_session_id"] = result.session_id
            if task.get("run_once"):
                task["enabled"] = False
        except Exception as exc:
            logger.exception("Task %s failed", task_id)
            task["status"] = TaskStatus.failed.value
            task["last_error"] = str(exc)
        finally:
            task["last_run_at"] = _now().isoformat()
            await self._save()

    async def create(self, body: TaskCreate) -> TaskInfo:
        if not body.run_once and not body.cron and not body.interval_seconds:
            raise ValueError("Provide cron, interval_seconds, or run_once=true")

        task_id = uuid.uuid4().hex
        row = {
            "id": task_id,
            "name": body.name,
            "prompt": body.prompt,
            "session_id": body.session_id,
            "cron": body.cron,
            "interval_seconds": body.interval_seconds,
            "run_once": body.run_once,
            "enabled": body.enabled,
            "status": TaskStatus.pending.value,
            "last_run_at": None,
            "last_result": None,
            "last_error": None,
            "created_at": _now().isoformat(),
            "metadata": body.metadata,
        }
        self._tasks[task_id] = row
        await self._save()
        if body.enabled and self._started:
            self._schedule(row)
        return self._to_info(row)

    async def update(self, task_id: str, body: TaskUpdate) -> TaskInfo | None:
        """Replace editable fields; keep run history. Reschedule if enabled."""
        if not body.run_once and not body.cron and not body.interval_seconds:
            raise ValueError("Provide cron, interval_seconds, or run_once=true")

        row = self._tasks.get(task_id)
        if not row:
            return None

        # Drop old job before mutating schedule fields
        job_id = f"task-{task_id}"
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

        row["name"] = body.name
        row["prompt"] = body.prompt
        row["session_id"] = body.session_id
        row["cron"] = body.cron
        row["interval_seconds"] = body.interval_seconds
        row["run_once"] = body.run_once
        row["enabled"] = body.enabled
        # Client form is source of truth for always_new_session; keep last_session_id for UI
        new_meta = dict(body.metadata or {})
        old_meta = dict(row.get("metadata") or {})
        prev_last = row.get("last_session_id") or old_meta.get("last_session_id")
        if prev_last and "last_session_id" not in new_meta:
            new_meta["last_session_id"] = prev_last
        row["metadata"] = new_meta

        # re-enable cancelled tasks when user turns them back on
        if body.enabled and row.get("status") == TaskStatus.cancelled.value:
            row["status"] = TaskStatus.pending.value
        if not body.enabled:
            row["status"] = TaskStatus.cancelled.value

        await self._save()
        if body.enabled and self._started:
            self._schedule(row)
        return self._to_info(row)

    async def list_tasks(self) -> list[TaskInfo]:
        return [self._to_info(t) for t in self._tasks.values()]

    async def get(self, task_id: str) -> TaskInfo | None:
        row = self._tasks.get(task_id)
        return self._to_info(row) if row else None

    async def cancel(self, task_id: str) -> bool:
        row = self._tasks.get(task_id)
        if not row:
            return False
        row["enabled"] = False
        row["status"] = TaskStatus.cancelled.value
        job_id = f"task-{task_id}"
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
        await self._save()
        return True

    async def delete(self, task_id: str) -> bool:
        """Hard-delete a task: remove from store and cancel job. Returns True if found."""
        if task_id not in self._tasks:
            return False
        job_id = f"task-{task_id}"
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
        del self._tasks[task_id]
        await self._save()
        return True

    async def run_now(self, task_id: str) -> TaskInfo | None:
        if task_id not in self._tasks:
            return None
        await self._run_task(task_id)
        return self._to_info(self._tasks[task_id])


_scheduler: TaskScheduler | None = None


def get_scheduler() -> TaskScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler()
    return _scheduler
