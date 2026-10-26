"""Linear workflow runner: tool / note / human_gate / agent (+ resume, when)."""

from __future__ import annotations

import contextvars
import json
import logging
import re
from typing import Any

from app.workflow.store import WorkflowStore, get_workflow_store

logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.\-]+)\s*\}\}")

# Depth > 0 while an agent step is running (blocks nested workflow.run).
_workflow_agent_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    "workflow_agent_depth", default=0
)


def in_workflow_agent() -> bool:
    """True when executing an agent step inside a workflow."""
    return _workflow_agent_depth.get() > 0


def _resolve_path(ctx: dict[str, Any], path: str) -> Any:
    cur: Any = ctx
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _as_text(val: Any, default: str = "") -> str:
    """Coerce step fields to str. Callables (leaked handlers) have no .strip()."""
    if val is None:
        return default
    if isinstance(val, str):
        return val
    if isinstance(val, (bytes, bytearray)):
        try:
            return val.decode("utf-8", errors="replace")
        except Exception:
            return default
    if isinstance(val, (dict, list, tuple, set)):
        if isinstance(val, dict):
            return str(val.get("name") or val.get("id") or default)
        return default
    if callable(val):
        name = str(getattr(val, "__name__", "") or "").strip()
        if name and name not in ("<lambda>", "<lambda>"):
            return name
        return default
    return str(val)


def render_templates(obj: Any, ctx: dict[str, Any]) -> Any:
    """Replace {{inputs.x}} / {{steps.id.output}} in strings recursively."""
    if isinstance(obj, str):

        def repl(m: re.Match[str]) -> str:
            val = _resolve_path(ctx, m.group(1))
            if val is None:
                return m.group(0)
            if isinstance(val, (dict, list)):
                return json.dumps(val, ensure_ascii=False)
            return str(val)

        return _VAR_RE.sub(repl, obj)
    if isinstance(obj, list):
        return [render_templates(x, ctx) for x in obj]
    if isinstance(obj, dict):
        return {k: render_templates(v, ctx) for k, v in obj.items()}
    return obj


def _truthy(val: Any) -> bool:
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        return val.strip().lower() not in ("", "0", "false", "no", "none", "null")
    if isinstance(val, (list, dict)):
        return bool(val)
    return bool(val)


def eval_when(when: Any, ctx: dict[str, Any]) -> bool:
    """Return True if the step should run. Missing/empty when → always run."""
    if when is None or when is True:
        return True
    if when is False:
        return False
    if isinstance(when, str):
        # bare path: truthy check
        path = when.strip()
        if not path:
            return True
        return _truthy(_resolve_path(ctx, path))
    if not isinstance(when, dict):
        return bool(when)

    path = str(when.get("path") or when.get("key") or "").strip()
    if not path:
        return True
    val = _resolve_path(ctx, path)

    if "eq" in when:
        return val == when["eq"]
    if "ne" in when:
        return val != when["ne"]
    if "in" in when:
        options = when["in"]
        if not isinstance(options, (list, tuple, set)):
            options = [options]
        return val in options
    if "truthy" in when:
        want = bool(when["truthy"])
        return _truthy(val) is want
    # default: path must be truthy
    return _truthy(val)


def _truncate_output(text: str, limit: int = 8000) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "…", True


def _rebuild_ctx_from_run(run: dict[str, Any]) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "inputs": dict(run.get("inputs") or {}),
        "steps": {},
    }
    for rec in run.get("steps") or []:
        if not isinstance(rec, dict):
            continue
        if rec.get("status") not in ("ok", "approved", "skipped"):
            continue
        sid = str(rec.get("id") or "")
        if not sid:
            continue
        # prefer save_as key if present on record
        key = str(rec.get("save_as") or sid)
        ctx["steps"][key] = {
            "output": rec.get("output"),
            "tool": rec.get("tool"),
        }
        if key != sid:
            ctx["steps"][sid] = ctx["steps"][key]
    return ctx


async def _ensure_runtime_ready() -> None:
    from app.tools.registry import get_tool_registry

    registry = get_tool_registry()
    if registry.get("workspace") and registry.get("kb") and registry.get("workflow"):
        return
    try:
        from app.services.runtime import rebuild_runtime

        await rebuild_runtime(reconnect_mcp=False)
    except Exception:
        logger.exception("Workflow runtime rebuild failed")


async def resolve_run_session(
    definition: dict[str, Any],
    *,
    session_id: str | None = None,
    always_new_session: bool = False,
    session_store: Any = None,
) -> str:
    """Pick or create the one conversation this run will write to.

    Priority: always_new → explicit session_id (if it still exists) →
    definition.default_session_id → create a titled session for this run.
    """
    if session_store is None:
        from app.memory.session import get_session_store

        session_store = get_session_store()

    name = str(definition.get("name") or definition.get("id") or "流程").strip() or "流程"
    title = f"工作流 · {name}"[:80]

    if always_new_session:
        created = await session_store.create(title=title)
        return str(created["session_id"])

    candidates: list[str] = []
    explicit = str(session_id or "").strip()
    if explicit:
        candidates.append(explicit)
    default = str(definition.get("default_session_id") or "").strip()
    if default and default not in candidates:
        candidates.append(default)

    for cand in candidates:
        existing = await session_store.get(cand)
        if existing and existing.get("session_id"):
            return str(existing["session_id"])

    created = await session_store.create(title=title)
    return str(created["session_id"])


class WorkflowEngine:
    def __init__(self, store: WorkflowStore | None = None) -> None:
        self.store = store or get_workflow_store()

    def _merge_inputs(
        self, definition: dict[str, Any], inputs: dict[str, Any] | None
    ) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        spec = definition.get("inputs") or {}
        if isinstance(spec, dict):
            for k, meta in spec.items():
                if isinstance(meta, dict) and "default" in meta:
                    merged[k] = meta["default"]
                elif not isinstance(meta, dict):
                    merged[k] = meta
        if inputs:
            merged.update(inputs)
        return merged

    async def prepare_run(
        self,
        workflow_id: str,
        *,
        inputs: dict[str, Any] | None = None,
        trigger: str = "manual",
        max_steps: int = 40,
        session_id: str | None = None,
        always_new_session: bool = False,
    ) -> dict[str, Any]:
        """Create a pending/running run record without executing steps.

        Pins one conversation for the whole run so every agent step writes
        to the same session (instead of opening a new chat per step).

        Returns ``{"ok": True, "definition", "run", "ctx", "max_steps"}`` or error dict.
        """
        definition = await self.store.get_definition(workflow_id)
        if not definition:
            return {"ok": False, "error": f"Workflow not found: {workflow_id}"}
        if definition.get("enabled") is False:
            return {"ok": False, "error": f"Workflow disabled: {workflow_id}"}

        merged_inputs = self._merge_inputs(definition, inputs)
        pinned = await resolve_run_session(
            definition,
            session_id=session_id,
            always_new_session=always_new_session,
        )
        run = await self.store.create_run(
            definition["id"],
            inputs=merged_inputs,
            trigger=trigger,
            session_id=pinned,
        )
        run["status"] = "running"
        run["workflow_name"] = definition.get("name")
        run["session_id"] = pinned
        await self.store.save_run(run)

        steps = list(definition.get("steps") or [])
        if len(steps) > max_steps:
            run["status"] = "failed"
            run["error"] = f"Too many steps (>{max_steps})"
            run["finished_at"] = run["updated_at"]
            await self.store.save_run(run)
            return {"ok": False, "run": run, "error": run["error"]}

        ctx: dict[str, Any] = {"inputs": merged_inputs, "steps": {}}
        return {
            "ok": True,
            "definition": definition,
            "run": run,
            "ctx": ctx,
            "max_steps": max_steps,
        }

    async def run(
        self,
        workflow_id: str,
        *,
        inputs: dict[str, Any] | None = None,
        trigger: str = "manual",
        max_steps: int = 40,
        session_id: str | None = None,
        always_new_session: bool = False,
    ) -> dict[str, Any]:
        prepared = await self.prepare_run(
            workflow_id,
            inputs=inputs,
            trigger=trigger,
            max_steps=max_steps,
            session_id=session_id,
            always_new_session=always_new_session,
        )
        if not prepared.get("ok"):
            return prepared
        return await self._execute_from(
            prepared["definition"],
            prepared["run"],
            prepared["ctx"],
            start_index=0,
            max_steps=int(prepared["max_steps"]),
        )

    async def resume(
        self,
        run_id: str,
        *,
        approved: bool = True,
        note: str = "",
        max_steps: int = 40,
    ) -> dict[str, Any]:
        """Continue a run paused at human_gate."""
        run = await self.store.get_run(run_id)
        if not run:
            return {"ok": False, "error": f"Run not found: {run_id}"}
        if run.get("status") != "waiting_human":
            return {
                "ok": False,
                "error": f"Run status is {run.get('status')}, not waiting_human",
                "run": run,
            }

        workflow_id = run.get("workflow_id") or ""
        definition = await self.store.get_definition(workflow_id)
        if not definition:
            return {"ok": False, "error": f"Workflow not found: {workflow_id}"}

        steps = list(definition.get("steps") or [])
        run_steps = list(run.get("steps") or [])
        if not run_steps:
            return {"ok": False, "error": "Run has no steps to resume"}
        last = run_steps[-1]
        if last.get("type") != "human_gate" or last.get("status") != "waiting_human":
            return {"ok": False, "error": "Last step is not a waiting human_gate"}

        gate_id = str(last.get("id") or "")
        start_index = 0
        for i, step in enumerate(steps):
            if str(step.get("id") or "") == gate_id:
                start_index = i + 1
                break
        else:
            return {"ok": False, "error": f"Gate step id not found in definition: {gate_id}"}

        if not approved:
            last["status"] = "rejected"
            last["output"] = note or "用户拒绝继续"
            run["status"] = "cancelled"
            run["error"] = "human_gate rejected"
            await self.store.save_run(run)
            run["finished_at"] = run.get("updated_at")
            await self.store.save_run(run)
            return {"ok": True, "run": run, "status": "cancelled"}

        last["status"] = "approved"
        last["output"] = note or "用户已确认，继续执行"
        await self.store.save_run(run)

        ctx = _rebuild_ctx_from_run(run)
        ctx["steps"][gate_id] = {"output": last["output"]}
        run["status"] = "running"
        run["error"] = None
        await self.store.save_run(run)

        return await self._execute_from(
            definition, run, ctx, start_index=start_index, max_steps=max_steps
        )

    async def _run_agent_step(
        self,
        step: dict[str, Any],
        ctx: dict[str, Any],
        run: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute one agent step; returns record dict with status ok."""
        from app.agent.core import get_agent

        prompt = render_templates(
            _as_text(step.get("prompt") or step.get("message")), ctx
        )
        if not str(prompt).strip():
            raise ValueError("agent step missing prompt")

        system_extra = step.get("system_extra") or step.get("system") or ""
        if system_extra:
            system_extra = render_templates(system_extra, ctx)
            prompt = f"{system_extra}\n\n---\n\n{prompt}"

        use_tools = step.get("use_tools", True)
        if isinstance(use_tools, str):
            use_tools = use_tools.strip().lower() not in ("0", "false", "no")
        use_memory = step.get("use_memory", True)
        if isinstance(use_memory, str):
            use_memory = use_memory.strip().lower() not in ("0", "false", "no")

        session_id = str(run.get("session_id") or "").strip() or None
        wf_name = str(run.get("workflow_name") or "").strip()
        session_title = f"工作流 · {wf_name}"[:80] if wf_name else None
        agent = get_agent()
        token = _workflow_agent_depth.set(_workflow_agent_depth.get() + 1)
        try:
            result = await agent.chat(
                str(prompt),
                session_id=session_id,
                session_title=session_title,
                use_tools=bool(use_tools),
                use_memory=bool(use_memory),
                allow_deputy=True,
            )
        finally:
            _workflow_agent_depth.reset(token)

        if result.session_id and run.get("session_id") != result.session_id:
            run["session_id"] = result.session_id

        reply = result.reply or ""
        out_s, truncated = _truncate_output(reply)
        rec: dict[str, Any] = {
            "id": str(step.get("id") or "agent"),
            "type": "agent",
            "status": "ok",
            "output": out_s,
            "use_tools": bool(use_tools),
            "session_id": result.session_id,
        }
        if truncated:
            rec["output_truncated"] = True
        if result.tool_calls:
            rec["tool_calls"] = [
                {
                    "name": getattr(tc, "name", None) or (tc.get("name") if isinstance(tc, dict) else None),
                    "arguments": str(
                        getattr(tc, "arguments", None)
                        or (tc.get("arguments") if isinstance(tc, dict) else "")
                        or ""
                    )[:500],
                }
                for tc in (result.tool_calls or [])[:12]
            ]
        return rec

    async def _execute_from(
        self,
        definition: dict[str, Any],
        run: dict[str, Any],
        ctx: dict[str, Any],
        *,
        start_index: int,
        max_steps: int,
    ) -> dict[str, Any]:
        from app.tools.registry import get_tool_registry

        await _ensure_runtime_ready()
        registry = get_tool_registry()
        workflow_id = definition.get("id") or run.get("workflow_id")
        steps = list(definition.get("steps") or [])
        if len(steps) > max_steps:
            run["status"] = "failed"
            run["error"] = f"Too many steps (>{max_steps})"
            run["finished_at"] = run.get("updated_at")
            await self.store.save_run(run)
            return {"ok": False, "run": run, "error": run["error"]}

        for step in steps[start_index:]:
            if not isinstance(step, dict):
                run["status"] = "failed"
                run["error"] = f"Step [{len(run['steps']) + 1}] invalid: not an object"
                run["finished_at"] = run.get("updated_at")
                await self.store.save_run(run)
                return {"ok": False, "run": run, "error": run["error"]}
            sid = _as_text(step.get("id"), f"step_{len(run['steps']) + 1}").strip() or (
                f"step_{len(run['steps']) + 1}"
            )
            stype = _as_text(step.get("type"), "tool").strip().lower() or "tool"
            run["current_step"] = sid
            await self.store.save_run(run)

            # Conditional skip
            when = step.get("when")
            if when is not None and not eval_when(when, ctx):
                rec = {
                    "id": sid,
                    "type": stype,
                    "status": "skipped",
                    "output": "条件不满足，已跳过",
                    "when": when,
                }
                run["steps"].append(rec)
                save_as = step.get("save_as") or sid
                ctx["steps"][save_as] = {"output": rec["output"]}
                await self.store.save_run(run)
                continue

            on_error = str(step.get("on_error") or "fail").strip().lower()
            try:
                if stype == "human_gate":
                    rec = {
                        "id": sid,
                        "type": stype,
                        "status": "waiting_human",
                        "prompt": step.get("prompt")
                        or step.get("message")
                        or "请确认后继续",
                        "output": None,
                    }
                    run["steps"].append(rec)
                    run["status"] = "waiting_human"
                    await self.store.save_run(run)
                    return {
                        "ok": True,
                        "run": run,
                        "status": "waiting_human",
                        "message": rec["prompt"],
                    }

                if stype == "note":
                    msg = render_templates(
                        step.get("message") or step.get("content") or "", ctx
                    )
                    rec = {
                        "id": sid,
                        "type": "note",
                        "status": "ok",
                        "output": msg,
                    }
                    run["steps"].append(rec)
                    save_as = step.get("save_as") or sid
                    ctx["steps"][save_as] = {"output": msg}
                    await self.store.save_run(run)
                    continue

                if stype == "agent":
                    step_with_id = {**step, "id": sid}
                    rec = await self._run_agent_step(step_with_id, ctx, run)
                    rec["id"] = sid
                    save_as = step.get("save_as") or sid
                    rec["save_as"] = save_as
                    run["steps"].append(rec)
                    ctx["steps"][save_as] = {
                        "output": rec["output"],
                        "tool": "agent",
                    }
                    await self.store.save_run(run)
                    continue

                if stype == "tool":
                    tool_name = _as_text(
                        step.get("tool") if step.get("tool") not in (None, "") else step.get("name")
                    ).strip()
                    if not tool_name:
                        raise ValueError("tool step missing tool name")
                    if tool_name in ("create_tool", "delete_tool") and not step.get(
                        "allow_dangerous"
                    ):
                        raise ValueError(
                            f"Tool [{tool_name}] blocked in workflows (set allow_dangerous)"
                        )
                    spec = registry.get(tool_name)
                    if not spec:
                        # one more rebuild attempt
                        await _ensure_runtime_ready()
                        registry = get_tool_registry()
                        spec = registry.get(tool_name)
                    if not spec:
                        raise ValueError(f"Tool not registered: {tool_name}")
                    args = render_templates(
                        step.get("args") or step.get("arguments") or {}, ctx
                    )
                    if not isinstance(args, dict):
                        args = {}
                    result = await registry.execute(tool_name, args)
                    out_s = (
                        result
                        if isinstance(result, str)
                        else json.dumps(result, ensure_ascii=False, default=str)
                    )
                    out_s, truncated = _truncate_output(out_s)
                    rec = {
                        "id": sid,
                        "type": "tool",
                        "tool": tool_name,
                        "args": args,
                        "status": "ok",
                        "output": out_s,
                    }
                    if truncated:
                        rec["output_truncated"] = True
                    run["steps"].append(rec)
                    save_as = step.get("save_as") or sid
                    ctx["steps"][save_as] = {
                        "output": rec["output"],
                        "tool": tool_name,
                    }
                    await self.store.save_run(run)
                    continue

                raise ValueError(f"Unknown step type: {stype}")
            except Exception as e:
                logger.exception("Workflow step failed %s/%s", workflow_id, sid)
                fail_rec = {
                    "id": sid,
                    "type": stype,
                    "status": "failed",
                    "error": str(e),
                }
                run["steps"].append(fail_rec)
                if on_error in ("continue", "skip", "ignore"):
                    run["error"] = f"Step [{sid}] failed (continued): {e}"
                    await self.store.save_run(run)
                    continue
                run["status"] = "failed"
                run["error"] = f"Step [{sid}] failed: {e}"
                run["finished_at"] = run.get("updated_at")
                await self.store.save_run(run)
                return {"ok": False, "run": run, "error": run["error"]}

        run["status"] = "succeeded"
        run["current_step"] = None
        run["finished_at"] = run.get("updated_at")
        await self.store.save_run(run)
        return {"ok": True, "run": run, "status": "succeeded"}


_engine: WorkflowEngine | None = None


def get_workflow_engine() -> WorkflowEngine:
    global _engine
    if _engine is None:
        _engine = WorkflowEngine()
    return _engine
