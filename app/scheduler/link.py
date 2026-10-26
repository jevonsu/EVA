"""Bind a workflow definition to a scheduled task (same store as 设定→定时任务)."""

from __future__ import annotations

from typing import Any

from app.models.schemas import TaskCreate, TaskUpdate


def normalize_schedule(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    mode = str(data.get("mode") or "off").strip().lower()
    if mode in ("", "none", "disabled", "false"):
        mode = "off"
    cron = str(data.get("cron") or "").strip() or None
    interval = data.get("interval_seconds")
    try:
        interval_i = int(interval) if interval not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        interval_i = None
    if interval_i is not None and interval_i < 1:
        interval_i = None
    run_once = bool(data.get("run_once") or mode == "once")
    if mode == "off" and (cron or interval_i or run_once):
        mode = "once" if run_once else ("interval" if interval_i else "cron")
    enabled = bool(data.get("enabled", True)) and mode != "off"
    return {
        "mode": mode,
        "enabled": enabled,
        "cron": cron,
        "interval_seconds": interval_i,
        "run_once": run_once,
        "task_id": str(data.get("task_id") or "").strip(),
    }


def schedule_label(sched: dict[str, Any] | None) -> str:
    s = normalize_schedule(sched)
    if not s["enabled"]:
        return ""
    if s["run_once"] or s["mode"] == "once":
        return "到点跑一次"
    if s["interval_seconds"]:
        mins = max(1, int(round(int(s["interval_seconds"]) / 60)))
        return f"每 {mins} 分钟"
    if s["cron"]:
        return f"cron {s['cron']}"
    return "已定时"


async def sync_workflow_schedule(
    definition: dict[str, Any],
    schedule: dict[str, Any] | None,
) -> dict[str, Any]:
    """Create / update / delete the task that fires this workflow."""
    from app.scheduler.manager import get_scheduler

    s = normalize_schedule(schedule)
    wid = str(definition.get("id") or "").strip()
    if not wid:
        raise ValueError("workflow id required")
    sch = get_scheduler()
    existing = None
    if s["task_id"]:
        existing = sch._tasks.get(s["task_id"])
    if not existing:
        existing = sch.find_by_workflow(wid)

    if not s["enabled"]:
        if existing:
            await sch.delete(str(existing["id"]))
        out = {
            "mode": "off",
            "enabled": False,
            "cron": None,
            "interval_seconds": None,
            "run_once": False,
            "task_id": "",
        }
        definition["schedule"] = out
        return out

    if not s["run_once"] and not s["cron"] and not s["interval_seconds"]:
        raise ValueError("定时需要 cron、间隔分钟或只跑一次")

    name = f"工作流 · {definition.get('name') or wid}"
    prompt = f"运行已保存的工作流「{definition.get('name') or wid}」（id={wid}）。"
    always_new = bool(definition.get("always_new_session"))
    sid = str(definition.get("default_session_id") or "").strip() or None
    if not always_new and not sid and existing:
        sid = str(existing.get("session_id") or "").strip() or None
    if always_new:
        sid = None
    meta: dict[str, Any] = {"kind": "workflow", "workflow_id": wid}
    if always_new:
        meta["always_new_session"] = True
    if existing:
        info = await sch.update(
            str(existing["id"]),
            TaskUpdate(
                name=name,
                prompt=prompt,
                session_id=sid,
                cron=s["cron"],
                interval_seconds=s["interval_seconds"],
                run_once=s["run_once"],
                enabled=True,
                metadata=meta,
            ),
        )
    else:
        info = await sch.create(
            TaskCreate(
                name=name,
                prompt=prompt,
                session_id=sid,
                cron=s["cron"],
                interval_seconds=s["interval_seconds"],
                run_once=s["run_once"],
                enabled=True,
                metadata=meta,
            )
        )
    if not info:
        raise ValueError("无法写入定时任务")
    out = {
        "mode": s["mode"] if s["mode"] != "off" else ("once" if s["run_once"] else "cron" if s["cron"] else "interval"),
        "enabled": True,
        "cron": s["cron"],
        "interval_seconds": s["interval_seconds"],
        "run_once": s["run_once"],
        "task_id": info.id,
    }
    definition["schedule"] = out
    return out


async def unsync_workflow_schedule(workflow_id: str) -> None:
    from app.scheduler.manager import get_scheduler

    sch = get_scheduler()
    row = sch.find_by_workflow(workflow_id)
    if row:
        await sch.delete(str(row["id"]))
