"""Workflow definitions + run history (JSON files)."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from app.config import get_settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _slug(name: str) -> str:
    s = re.sub(r"\s+", "_", (name or "").strip().lower())
    s = re.sub(r"[^\w\u4e00-\u9fff\-]+", "", s, flags=re.UNICODE)
    return (s[:64] or "workflow").strip("_")


class WorkflowStore:
    def __init__(self, root: Path | None = None) -> None:
        settings = get_settings()
        paths = settings.paths()
        self.root = root or paths.workflows_dir
        self.defs = self.root / "definitions" if root else paths.workflow_defs
        self.runs = self.root / "runs" if root else paths.workflow_runs
        self.defs.mkdir(parents=True, exist_ok=True)
        self.runs.mkdir(parents=True, exist_ok=True)
        # Builtin ids the user deleted — do not auto re-seed these
        self._removed_path = (
            self.root / "removed_builtins.json"
            if root
            else paths.workflow_removed_builtins
        )

    def _def_path(self, wf_id: str) -> Path:
        return self.defs / f"{wf_id}.json"

    def _run_path(self, run_id: str) -> Path:
        return self.runs / f"{run_id}.json"

    def _load_removed_builtins(self) -> set[str]:
        if not self._removed_path.exists():
            return set()
        try:
            data = json.loads(self._removed_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return {str(x).strip() for x in data if str(x).strip()}
            if isinstance(data, dict) and isinstance(data.get("ids"), list):
                return {str(x).strip() for x in data["ids"] if str(x).strip()}
        except Exception:
            return set()
        return set()

    def _save_removed_builtins(self, ids: set[str]) -> None:
        payload = {"ids": sorted(ids), "updated_at": _now().isoformat()}
        self._removed_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _mark_builtin_removed(self, wf_id: str) -> None:
        from app.workflow.builtins import all_builtin_definitions

        builtin_ids = {
            str(raw.get("id") or "").strip()
            for raw in all_builtin_definitions()
            if str(raw.get("id") or "").strip()
        }
        if wf_id not in builtin_ids:
            return
        removed = self._load_removed_builtins()
        if wf_id in removed:
            return
        removed.add(wf_id)
        self._save_removed_builtins(removed)

    def _unmark_builtin_removed(self, wf_id: str) -> None:
        removed = self._load_removed_builtins()
        if wf_id not in removed:
            return
        removed.discard(wf_id)
        self._save_removed_builtins(removed)

    async def list_definitions(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(self.defs.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                async with aiofiles.open(path, "r", encoding="utf-8") as f:
                    data = json.loads(await f.read())
                steps = data.get("steps") or []
                has_agent = any(
                    isinstance(s, dict)
                    and str(s.get("type") or "").lower() == "agent"
                    for s in steps
                )
                sched = data.get("schedule") if isinstance(data.get("schedule"), dict) else {}
                items.append(
                    {
                        "id": data.get("id") or path.stem,
                        "name": data.get("name") or path.stem,
                        "description": data.get("description") or "",
                        "version": data.get("version") or "0.1.0",
                        "enabled": data.get("enabled", True),
                        "step_count": len(steps),
                        "updated_at": data.get("updated_at") or "",
                        "has_agent_steps": has_agent,
                        "builtin": bool(data.get("builtin")),
                        "schedule": sched,
                        "default_session_id": str(data.get("default_session_id") or ""),
                        "always_new_session": bool(data.get("always_new_session")),
                    }
                )
            except Exception:
                continue
        return items

    async def get_definition(self, wf_id: str) -> dict[str, Any] | None:
        key = (wf_id or "").strip()
        if not key:
            return None
        path = self._def_path(key)
        if path.exists():
            async with aiofiles.open(path, "r", encoding="utf-8") as f:
                return json.loads(await f.read())
        # resolve by id / name (exact) / case-insensitive id
        key_lower = key.lower()
        for p in self.defs.glob("*.json"):
            try:
                async with aiofiles.open(p, "r", encoding="utf-8") as f:
                    data = json.loads(await f.read())
                did = str(data.get("id") or p.stem)
                dname = str(data.get("name") or "")
                if did == key or dname == key or did.lower() == key_lower:
                    return data
            except Exception:
                continue
        return None

    async def resolve_definition_id(self, wf_id_or_name: str) -> str | None:
        """Return canonical definition id, or None if not found."""
        data = await self.get_definition(wf_id_or_name)
        if not data:
            return None
        return str(data.get("id") or "").strip() or None

    async def save_definition(
        self,
        *,
        name: str,
        description: str = "",
        steps: list[dict[str, Any]] | None = None,
        inputs: dict[str, Any] | None = None,
        enabled: bool = True,
        wf_id: str | None = None,
        version: str | None = None,
        raw: dict[str, Any] | None = None,
        schedule: dict[str, Any] | None = None,
        default_session_id: str | None = None,
        always_new_session: bool | None = None,
    ) -> dict[str, Any]:
        if raw:
            data = dict(raw)
            # resolve existing id when client passes name as id
            cand = data.get("id") or wf_id or data.get("name") or name
            resolved = await self.resolve_definition_id(str(cand or ""))
            data["id"] = (
                resolved
                or data.get("id")
                or wf_id
                or _slug(data.get("name") or name or "workflow")
            )
            data["name"] = data.get("name") or name or data["id"]
            data["updated_at"] = _now().isoformat()
            if "created_at" not in data:
                data["created_at"] = data["updated_at"]
            data.setdefault("version", "0.1.0")
            data.setdefault("enabled", True)
            data.setdefault("steps", [])
            data.setdefault("inputs", {})
        else:
            # Prefer explicit id; else try resolve name → existing id; else slug
            hint = (wf_id or name or "").strip()
            existing = await self.get_definition(hint) if hint else None
            if not existing and wf_id:
                existing = await self.get_definition(wf_id)
            if not existing and name:
                existing = await self.get_definition(name)
            wid = (
                str((existing or {}).get("id") or "").strip()
                or (wf_id or "").strip()
                or _slug(name)
            )
            now = _now().isoformat()
            data = {
                "id": wid,
                "name": (name or (existing or {}).get("name") or wid).strip(),
                "description": description
                if description is not None
                else ((existing or {}).get("description") or ""),
                "version": version
                or (existing.get("version") if existing else None)
                or "0.1.0",
                "enabled": enabled,
                "inputs": inputs if inputs is not None else (existing or {}).get("inputs") or {},
                "steps": steps if steps is not None else (existing or {}).get("steps") or [],
                "created_at": (existing or {}).get("created_at") or now,
                "updated_at": now,
            }
            if schedule is not None:
                data["schedule"] = schedule
            elif existing and isinstance(existing.get("schedule"), dict):
                data["schedule"] = existing.get("schedule")
            if default_session_id is not None:
                data["default_session_id"] = str(default_session_id).strip()
            elif existing:
                data["default_session_id"] = str(
                    existing.get("default_session_id") or ""
                ).strip()
            else:
                data["default_session_id"] = ""
            if always_new_session is not None:
                data["always_new_session"] = bool(always_new_session)
            elif existing:
                data["always_new_session"] = bool(existing.get("always_new_session"))
            else:
                data["always_new_session"] = False
            if data.get("always_new_session"):
                data["default_session_id"] = ""
            if existing:
                # preserve builtin flag etc.
                if "builtin" in existing and "builtin" not in data:
                    data["builtin"] = existing.get("builtin")
            if existing and version is None:
                # bump patch on save if steps changed
                try:
                    parts = str(data["version"]).split(".")
                    nums = [int(x) for x in parts[:3]]
                    while len(nums) < 3:
                        nums.append(0)
                    if steps is not None:
                        nums[2] += 1
                    data["version"] = f"{nums[0]}.{nums[1]}.{nums[2]}"
                except Exception:
                    data["version"] = "0.1.1"

        path = self._def_path(data["id"])
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=2))
        # User re-created a previously deleted builtin → allow seed again if removed later
        self._unmark_builtin_removed(str(data["id"]))
        return data

    async def delete_definition(
        self,
        wf_id: str,
        *,
        delete_runs: bool = True,
    ) -> dict[str, Any]:
        """Delete a workflow definition by id or display name.

        Returns ``{"ok": True, "id": ..., "runs_deleted": n}`` or ``{"ok": False, ...}``.
        Built-in workflows are recorded so ensure_seed will not resurrect them.
        """
        key = (wf_id or "").strip()
        if not key:
            return {"ok": False, "error": "workflow_id required"}

        data = await self.get_definition(key)
        if not data:
            return {"ok": False, "error": f"Workflow not found: {key}", "id": key}

        real_id = str(data.get("id") or "").strip()
        if not real_id:
            return {"ok": False, "error": f"Workflow has no id: {key}"}

        # Prefer canonical path; also unlink any file whose content id matches
        removed_files = 0
        path = self._def_path(real_id)
        if path.exists():
            try:
                path.unlink()
                removed_files += 1
            except OSError as e:
                return {"ok": False, "error": f"Failed to delete file: {e}", "id": real_id}

        # Orphan files named differently but same id field
        for p in list(self.defs.glob("*.json")):
            try:
                async with aiofiles.open(p, "r", encoding="utf-8") as f:
                    row = json.loads(await f.read())
                if str(row.get("id") or "") == real_id:
                    p.unlink(missing_ok=True)
                    removed_files += 1
            except Exception:
                continue

        if removed_files == 0:
            return {"ok": False, "error": f"Definition file missing for id={real_id}", "id": real_id}

        # Prevent ensure_seed from re-creating deleted builtins on next list
        self._mark_builtin_removed(real_id)

        runs_deleted = 0
        if delete_runs:
            cleared = await self.clear_runs(workflow_id=real_id)
            runs_deleted = int(cleared.get("count") or 0)

        return {
            "ok": True,
            "id": real_id,
            "name": data.get("name") or real_id,
            "runs_deleted": runs_deleted,
        }

    async def create_run(
        self,
        workflow_id: str,
        *,
        inputs: dict[str, Any] | None = None,
        trigger: str = "manual",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        from sqlalchemy import insert

        from app.storage.engine import db_connect
        from app.storage.schema import workflow_runs as runs_t
        from app.storage.util import dumps, run_db

        run_id = uuid.uuid4().hex
        now = _now().isoformat()
        run = {
            "id": run_id,
            "workflow_id": workflow_id,
            "status": "pending",
            "trigger": trigger,
            "inputs": inputs or {},
            "steps": [],
            "current_step": None,
            "session_id": str(session_id).strip() if session_id else None,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
        }

        def _do() -> None:
            with db_connect() as conn:
                conn.execute(
                    insert(runs_t).values(
                        id=run_id,
                        workflow_id=workflow_id,
                        status="pending",
                        created_at=now,
                        updated_at=now,
                        finished_at=None,
                        payload_json=dumps(run),
                    )
                )

        await run_db(_do)
        return run

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        from app.storage.engine import db_connect
        from app.storage.schema import workflow_runs as runs_t
        from app.storage.util import loads, run_db
        from sqlalchemy import select

        def _do() -> dict[str, Any] | None:
            with db_connect() as conn:
                row = conn.execute(
                    select(runs_t).where(runs_t.c.id == run_id)
                ).first()
                if not row:
                    return None
                data = loads(row.payload_json, {})
                return data if isinstance(data, dict) else None

        return await run_db(_do)

    async def save_run(self, run: dict[str, Any]) -> dict[str, Any]:
        from app.storage.engine import db_connect
        from app.storage.schema import workflow_runs as runs_t
        from app.storage.util import dumps, run_db
        from sqlalchemy import insert, select, update

        run["updated_at"] = _now().isoformat()
        rid = str(run.get("id") or "")

        def _do() -> None:
            vals = dict(
                workflow_id=str(run.get("workflow_id") or ""),
                status=str(run.get("status") or "pending"),
                created_at=str(run.get("created_at") or ""),
                updated_at=str(run.get("updated_at") or ""),
                finished_at=run.get("finished_at"),
                payload_json=dumps(run),
            )
            with db_connect() as conn:
                exists = conn.execute(
                    select(runs_t.c.id).where(runs_t.c.id == rid)
                ).first()
                if exists:
                    conn.execute(update(runs_t).where(runs_t.c.id == rid).values(**vals))
                else:
                    conn.execute(insert(runs_t).values(id=rid, **vals))

        await run_db(_do)
        return run

    async def list_runs(self, *, workflow_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        from app.storage.engine import db_connect
        from app.storage.schema import workflow_runs as runs_t
        from app.storage.util import loads, run_db
        from sqlalchemy import select

        def _do() -> list[dict[str, Any]]:
            with db_connect() as conn:
                q = select(runs_t).order_by(runs_t.c.updated_at.desc())
                rows = conn.execute(q).all()
            items: list[dict[str, Any]] = []
            for row in rows:
                data = loads(row.payload_json, {})
                if not isinstance(data, dict):
                    continue
                if workflow_id and data.get("workflow_id") != workflow_id:
                    continue
                items.append(
                    {
                        "id": data.get("id"),
                        "workflow_id": data.get("workflow_id"),
                        "workflow_name": data.get("workflow_name"),
                        "status": data.get("status"),
                        "trigger": data.get("trigger"),
                        "created_at": data.get("created_at"),
                        "finished_at": data.get("finished_at"),
                        "error": data.get("error"),
                        "step_count": len(data.get("steps") or []),
                        "current_step": data.get("current_step"),
                        "session_id": data.get("session_id") or None,
                    }
                )
                if len(items) >= limit:
                    break
            return items

        return await run_db(_do)

    async def delete_run(self, run_id: str) -> bool:
        from app.storage.engine import db_connect
        from app.storage.schema import workflow_runs as runs_t
        from app.storage.util import run_db
        from sqlalchemy import delete

        def _do() -> bool:
            with db_connect() as conn:
                res = conn.execute(delete(runs_t).where(runs_t.c.id == run_id))
                return bool(res.rowcount)

        return await run_db(_do)

    async def delete_runs(self, run_ids: list[str]) -> dict[str, Any]:
        deleted: list[str] = []
        missing: list[str] = []
        for rid in run_ids:
            rid = str(rid or "").strip()
            if not rid:
                continue
            if await self.delete_run(rid):
                deleted.append(rid)
            else:
                missing.append(rid)
        return {
            "ok": True,
            "deleted": deleted,
            "missing": missing,
            "count": len(deleted),
        }

    async def clear_runs(self, *, workflow_id: str | None = None) -> dict[str, Any]:
        """Delete run history. If workflow_id set, only that workflow's runs."""
        from app.storage.engine import db_connect
        from app.storage.schema import workflow_runs as runs_t
        from app.storage.util import run_db
        from sqlalchemy import delete, select

        def _do() -> int:
            with db_connect() as conn:
                if workflow_id:
                    res = conn.execute(
                        delete(runs_t).where(runs_t.c.workflow_id == workflow_id)
                    )
                    return int(res.rowcount or 0)
                # count then delete all
                n = len(conn.execute(select(runs_t.c.id)).all())
                conn.execute(delete(runs_t))
                return n

        deleted = await run_db(_do)
        return {"ok": True, "count": deleted}

    async def ensure_seed(self) -> None:
        """Ensure built-in definitions exist. Never overwrite user-edited same id."""
        await self.ensure_builtin_definitions()

    async def ensure_builtin_definitions(self) -> list[str]:
        """Write missing built-in workflows. Returns list of newly created ids.

        Skips ids the user previously deleted (``removed_builtins.json``).
        """
        from app.workflow.builtins import all_builtin_definitions

        removed = self._load_removed_builtins()
        created: list[str] = []
        for raw in all_builtin_definitions():
            wid = str(raw.get("id") or "").strip()
            if not wid:
                continue
            if wid in removed:
                continue
            if self._def_path(wid).exists():
                continue
            existing = await self.get_definition(wid)
            if existing:
                continue
            # save_definition unmarks removed — only call for truly new seeds
            data = dict(raw)
            data["id"] = wid
            data["name"] = data.get("name") or wid
            data["updated_at"] = _now().isoformat()
            data.setdefault("created_at", data["updated_at"])
            data.setdefault("version", "0.1.0")
            data.setdefault("enabled", True)
            data.setdefault("steps", [])
            data.setdefault("inputs", {})
            path = self._def_path(wid)
            async with aiofiles.open(path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2))
            created.append(wid)
        return created


_store: WorkflowStore | None = None


def get_workflow_store() -> WorkflowStore:
    global _store
    if _store is None:
        _store = WorkflowStore()
    return _store
