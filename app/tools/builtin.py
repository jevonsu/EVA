"""Built-in tools registered at startup."""

from __future__ import annotations

import json
import platform
import sys
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.tools.registry import ToolRegistry
from app.tools.workspace_ops import register_workspace_tools


def register_builtin_tools(registry: ToolRegistry) -> None:
    settings = get_settings()
    # Workspace multi-action tool (project/workspace)
    register_workspace_tools(registry)

    async def get_current_time() -> str:
        now = datetime.now(timezone.utc)
        return json.dumps(
            {
                "utc": now.isoformat(),
                "unix": int(now.timestamp()),
                "local_hint": datetime.now().isoformat(),
            },
            ensure_ascii=False,
        )

    async def calculator(expression: str) -> str:
        """Safely evaluate a simple arithmetic expression."""
        allowed = set("0123456789+-*/().% eE")
        expr = expression.strip()
        if not expr or not all(c in allowed or c.isspace() for c in expr):
            return json.dumps({"error": "Only basic arithmetic is allowed"})
        try:
            # Restricted eval
            result = eval(expr, {"__builtins__": {}}, {})  # noqa: S307
            return json.dumps({"expression": expr, "result": result})
        except Exception as exc:
            return json.dumps({"error": str(exc)})


    async def system_info() -> str:
        try:
            from app.tools.protection import protection_summary

            prot = protection_summary()
        except Exception:
            prot = {}
        return json.dumps(
            {
                "agent": settings.agent_name,
                "python": sys.version,
                "platform": platform.platform(),
                "llm_provider": settings.llm_provider,
                "llm_model": settings.llm_model,
                "tool_protection": prot,
            },
            ensure_ascii=False,
        )

    async def memory_tool(
        action: str,
        content: str = "",
        kind: str = "preference",
        tags: str = "",
        query: str = "",
        limit: int = 10,
        id: str = "",
        memory_id: str = "",
    ) -> str:
        """Long-term memory: remember / recall / list / delete.

        Persists to data/memory/long_term.json and appears in the UI Memory panel.
        """
        from app.memory.store import get_memory_store

        store = get_memory_store()
        act = (action or "").strip().lower()
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        item_id = (memory_id or id or "").strip()

        if act in ("remember", "save", "add", "store"):
            text = (content or "").strip()
            if not text:
                return json.dumps(
                    {"ok": False, "error": "content is required for action=remember"},
                    ensure_ascii=False,
                )
            k = (kind or "preference").strip() or "preference"
            item = await store.add(content=text, kind=k, tags=tag_list)
            return json.dumps(
                {
                    "ok": True,
                    "action": "remember",
                    "id": item.id,
                    "content": item.content,
                    "kind": item.kind,
                    "tags": item.tags,
                    "message": "已写入长期记忆，记忆面板可查看",
                },
                ensure_ascii=False,
            )

        if act in ("recall", "search", "get"):
            q = (query or content or "").strip()
            lim = max(1, min(int(limit or 10), 50))
            if q:
                items = await store.search(q, limit=lim)
            else:
                items = await store.list_all(limit=lim)
            return json.dumps(
                {
                    "ok": True,
                    "action": "recall",
                    "query": q,
                    "count": len(items),
                    "items": [
                        {
                            "id": i.id,
                            "content": i.content,
                            "kind": i.kind,
                            "tags": i.tags,
                            "score": i.score,
                            "created_at": i.created_at.isoformat(),
                        }
                        for i in items
                    ],
                },
                ensure_ascii=False,
                default=str,
            )

        if act in ("list", "all"):
            lim = max(1, min(int(limit or 20), 100))
            items = await store.list_all(limit=lim)
            return json.dumps(
                {
                    "ok": True,
                    "action": "list",
                    "count": len(items),
                    "items": [
                        {
                            "id": i.id,
                            "content": i.content,
                            "kind": i.kind,
                            "tags": i.tags,
                            "created_at": i.created_at.isoformat(),
                        }
                        for i in items
                    ],
                },
                ensure_ascii=False,
                default=str,
            )

        if act in ("delete", "remove"):
            if not item_id:
                return json.dumps(
                    {"ok": False, "error": "id/memory_id is required for action=delete"},
                    ensure_ascii=False,
                )
            ok = await store.delete(item_id)
            return json.dumps(
                {"ok": ok, "action": "delete", "id": item_id},
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "ok": False,
                "error": f"Unknown action: {action}. Use remember|recall|list|delete",
            },
            ensure_ascii=False,
        )


    #  Register tool / s

    async def read_skill(name: str) -> str:
        """Read an installed skill"s handler code and metadata from skills/ directory.
        Returns manifest.json, handler.py code, and SKILL.md content.
        Use this BEFORE create_tool(update=true) to examine existing code to fix."""
        import json as _json
        from pathlib import Path as _Path

        from app.services.skills import skills_root

        safe_name = name.strip().lower().replace(" ", "_")
        skill_dir = skills_root() / safe_name

        if not skill_dir.exists():
            return _json.dumps(
                {
                    "error": f"Skill [{safe_name}] not found in skills/ directory.",
                    "hint": "Use workspace action=list or check skills/ folder names.",
                },
                ensure_ascii=False,
            )

        result: dict[str, Any] = {
            "name": safe_name,
            "path": str(skill_dir.resolve()),
            "files": [],
        }
        try:
            from app.tools.tool_meta import meta_for

            result["meta"] = meta_for(safe_name)
        except Exception:
            result["meta"] = {}

        for f in ["manifest.json", "handler.py", "SKILL.md"]:
            fp = skill_dir / f
            if fp.exists():
                content = fp.read_text(encoding="utf-8", errors="replace")
                result["files"].append(
                    {
                        "name": f,
                        "size": len(content),
                        "content": content[:8000],
                        "truncated": len(content) > 8000,
                    }
                )
        return _json.dumps(result, ensure_ascii=False)

    def _parse_scene_keywords(raw: str | list | None) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, list):
            return [str(x).strip() for x in raw if str(x).strip()]
        text = str(raw).strip()
        if not text:
            return []
        # allow JSON array or comma/Chinese-comma separated
        if text.startswith("["):
            try:
                import json as _json

                arr = _json.loads(text)
                if isinstance(arr, list):
                    return [str(x).strip() for x in arr if str(x).strip()]
            except Exception:
                pass
        parts = []
        for chunk in text.replace("，", ",").replace("、", ",").split(","):
            s = chunk.strip()
            if s:
                parts.append(s)
        return parts

    def _enrich_tool_description(desc: str, *, tag: str, scene_keywords: list[str]) -> str:
        """Ensure description has useful Chinese/English scene cues for P2 filter."""
        d = (desc or "").strip()
        extras: list[str] = []
        if tag and tag not in d:
            extras.append(tag)
        for k in scene_keywords:
            if k and k not in d:
                extras.append(k)
        if not extras:
            return d
        # Keep original; append cue line (does not replace user text)
        cue = "；".join(extras[:8])
        if "场景关键词" in d or "scene:" in d.lower():
            return d
        return f"{d}（场景关键词: {cue}）"

    def _collect_skill_registered_tools(safe_name: str) -> list[dict[str, Any]]:
        from app.tools.registry import get_tool_registry

        reg = get_tool_registry()
        found: list[dict[str, Any]] = []
        for t in reg.list_tools():
            md = t.metadata or {}
            if t.name == safe_name or md.get("skill_id") == safe_name:
                found.append(
                    {
                        "name": t.name,
                        "source": t.source,
                        "description": (t.description or "")[:120],
                    }
                )
        return found

    def _bump_version(old: str | None) -> str:
        raw = (old or "0.1.0").strip() or "0.1.0"
        parts = raw.split(".")
        try:
            nums = [int(p) for p in parts[:3]]
            while len(nums) < 3:
                nums.append(0)
            nums[2] += 1
            return f"{nums[0]}.{nums[1]}.{nums[2]}"
        except Exception:
            return "0.1.1"

    def _canonical_skill_stem(name: str) -> str:
        """Strip common 'equivalent' suffixes: _v2, _fixed, _new, …"""
        import re as _re

        n = (name or "").strip().lower()
        n = _re.sub(
            r"(_v\d+|_version\d+|_new|_fixed|_fix|_copy|_tmp|_test|_2|_3)$",
            "",
            n,
        )
        return n or name

    def _find_near_skill_duplicates(safe_name: str, root) -> list[str]:
        """Existing skill folders that look like the same capability."""
        stem = _canonical_skill_stem(safe_name)
        hits: list[str] = []
        try:
            for d in root.iterdir():
                if not d.is_dir() or d.name.startswith((".", "_")):
                    continue
                n = d.name
                if n == safe_name:
                    continue
                n_stem = _canonical_skill_stem(n)
                if n == stem or n_stem == stem or n_stem == safe_name:
                    hits.append(n)
                elif stem and (n.startswith(stem + "_") or stem.startswith(n + "_")):
                    hits.append(n)
        except Exception:
            pass
        return sorted(set(hits))

    def _normalize_handler_code(
        safe_name: str,
        description: str,
        handler_code: str,
        params: dict[str, Any],
    ) -> tuple[str, list[str]]:
        """Auto-wrap bare handlers and force registry name == skill id.

        Returns (code, notes).
        """
        import json as _json
        import re as _re

        notes: list[str] = []
        code = (handler_code or "").strip()
        if not code:
            return "", notes

        # Ensure params is a plain dict for embedding
        if not isinstance(params, dict):
            params = {"type": "object", "properties": {}}
        params_lit = _json.dumps(params, ensure_ascii=False)
        desc_lit = _json.dumps(description or safe_name, ensure_ascii=False)

        has_register = bool(_re.search(r"\bdef\s+register\s*\(", code))
        has_reg_call = "registry.register" in code
        fn_match = _re.search(r"\b(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(", code)
        fn_names = _re.findall(r"\b(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(", code)
        # Prefer handle / run / main / first non-register
        handler_fn = None
        for cand in ("handle", "run", "main", "handler", "execute"):
            if cand in fn_names:
                handler_fn = cand
                break
        if handler_fn is None:
            for n in fn_names:
                if n not in ("register",):
                    handler_fn = n
                    break

        if not has_register:
            if handler_fn and has_reg_call:
                # Weird: register call without def register — wrap as-is
                indented = "\n".join(
                    ("    " + line if line.strip() else "") for line in code.split("\n")
                )
                code = (
                    f'"""Skill: {safe_name} — auto-wrapped register()"""\n'
                    "import json\n"
                    "import logging\n"
                    "from app.tools.registry import ToolRegistry\n\n"
                    "logger = logging.getLogger(__name__)\n\n"
                    "def register(registry: ToolRegistry) -> None:\n"
                    f"{indented}\n"
                )
                notes.append("wrapped code into def register(registry)")
            elif handler_fn:
                # Bare async/sync function(s) → full skill package
                indented = "\n".join(
                    ("    " + line if line.strip() else "") for line in code.split("\n")
                )
                code = (
                    f'"""Skill: {safe_name} — auto-scaffolded"""\n'
                    "import json\n"
                    "import logging\n"
                    "from typing import Any\n"
                    "from app.tools.registry import ToolRegistry\n\n"
                    "logger = logging.getLogger(__name__)\n\n"
                    f"{code}\n\n"
                    "def register(registry: ToolRegistry) -> None:\n"
                    f"    registry.register(\n"
                    f"        { _json.dumps(safe_name) },\n"
                    f"        {desc_lit},\n"
                    f"        {handler_fn},\n"
                    f"        {params_lit},\n"
                    f"        source='skill',\n"
                    f"    )\n"
                )
                notes.append(
                    f"scaffolded register() around function `{handler_fn}` "
                    f"with name={safe_name}"
                )
            else:
                # Treat as body of async handle(**kwargs)
                indented = "\n".join(
                    ("    " + line if line.strip() else "") for line in code.split("\n")
                )
                code = (
                    f'"""Skill: {safe_name} — body auto-wrapped as handle"""\n'
                    "import json\n"
                    "import logging\n"
                    "from typing import Any\n"
                    "from app.tools.registry import ToolRegistry\n\n"
                    "logger = logging.getLogger(__name__)\n\n"
                    "async def handle(**kwargs: Any) -> str:\n"
                    f"{indented}\n\n"
                    "def register(registry: ToolRegistry) -> None:\n"
                    f"    registry.register(\n"
                    f"        { _json.dumps(safe_name) },\n"
                    f"        {desc_lit},\n"
                    f"        handle,\n"
                    f"        {params_lit},\n"
                    f"        source='skill',\n"
                    f"    )\n"
                )
                notes.append("wrapped bare body as async def handle + register()")
        elif not has_reg_call and handler_fn and handler_fn != "register":
            # Has def register but never called registry.register — rebuild register()
            stripped_lines: list[str] = []
            skip = False
            for line in (handler_code or "").splitlines():
                if _re.match(r"\s*def\s+register\s*\(", line):
                    skip = True
                    continue
                if skip:
                    if (
                        line.strip()
                        and not line.startswith((" ", "\t"))
                        and not line.startswith("#")
                    ):
                        skip = False
                    else:
                        continue
                if not skip:
                    stripped_lines.append(line)
            body = "\n".join(stripped_lines).strip() or code
            code = (
                f'"""Skill: {safe_name}"""\n'
                "import json\n"
                "import logging\n"
                "from typing import Any\n"
                "from app.tools.registry import ToolRegistry\n\n"
                "logger = logging.getLogger(__name__)\n\n"
                f"{body}\n\n"
                "def register(registry: ToolRegistry) -> None:\n"
                f"    registry.register(\n"
                f"        { _json.dumps(safe_name) },\n"
                f"        {desc_lit},\n"
                f"        {handler_fn},\n"
                f"        {params_lit},\n"
                f"        source='skill',\n"
                f"    )\n"
            )
            notes.append(
                f"rebuilt register() to registry.register({safe_name!r}, …, {handler_fn})"
            )
        else:
            # Force first-arg name of registry.register(...) to safe_name
            def _fix_name(m: Any) -> str:
                return f'registry.register({_json.dumps(safe_name)}'

            new_code, nsub = _re.subn(
                r"registry\.register\(\s*[\"'][^\"']+[\"']",
                _fix_name,
                code,
            )
            if nsub:
                code = new_code
                notes.append(
                    f"rewrote {nsub} registry.register name(s) → {safe_name!r}"
                )

        # If still no registry.register, last resort scaffold empty handle
        if "registry.register" not in code:
            code = (
                f'"""Skill: {safe_name} — fallback scaffold"""\n'
                "import json\n"
                "from typing import Any\n"
                "from app.tools.registry import ToolRegistry\n\n"
                "async def handle(**kwargs: Any) -> str:\n"
                "    return json.dumps({'ok': True, 'echo': kwargs}, ensure_ascii=False, default=str)\n\n"
                "def register(registry: ToolRegistry) -> None:\n"
                f"    registry.register(\n"
                f"        { _json.dumps(safe_name) },\n"
                f"        {desc_lit},\n"
                f"        handle,\n"
                f"        {params_lit},\n"
                f"        source='skill',\n"
                f"    )\n"
            )
            notes.append("fallback scaffold (original code lacked registry.register)")

        return code, notes

    def _preflight_load_handler(skill_dir, safe_name: str) -> str | None:
        """Import handler in isolation; return error string or None if OK."""
        import importlib.util
        from pathlib import Path as _Path

        from app.tools.registry import ToolRegistry

        hp = _Path(skill_dir) / "handler.py"
        if not hp.is_file():
            return None  # HTTP-only skill
        try:
            mod_name = f"_preflight_{safe_name}_{id(hp)}"
            spec = importlib.util.spec_from_file_location(mod_name, hp)
            if spec is None or spec.loader is None:
                return "Cannot load handler module spec"
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if not hasattr(mod, "register") or not callable(mod.register):
                return "handler.py missing callable register(registry)"
            tmp = ToolRegistry()
            mod.register(tmp)
            names = [t.name for t in tmp.list_tools()]
            if safe_name not in names:
                return (
                    f"register() did not register tool name [{safe_name}]. "
                    f"Got: {names or '(none)'}. "
                    f"Use registry.register({safe_name!r}, description, handler, params, source='skill')."
                )
            return None
        except Exception as e:
            return f"{type(e).__name__}: {e}"

    async def create_agent_tool(
        name: str,
        description: str,
        handler_code: str = "",
        parameters: str = '{"type": "object", "properties": {}}',
        url: str = "",
        method: str = "GET",
        headers: str = "{}",
        update: bool = False,
        role: str = "primary",
        tag: str = "",
        group: str = "",
        scene_keywords: str = "",
        force_new: bool = False,
        changelog: str = "",
    ) -> str:
        """Create a new tool/skill at runtime and hot-reload it.

        Two modes:
          1) HTTP tool - provide url + method + parameters, no code needed.
          2) Python handler - bare async def handle is OK; system scaffolds register().

        Prefer update=true on the **primary** skill name; do not create xxx_v2 equivalents.
        Optional meta: role / tag / group / scene_keywords (group auto-inferred if empty).
        """
        import json as _json
        import shutil
        import tempfile
        from datetime import datetime, timezone
        from pathlib import Path as _Path

        from app.services.skills import skills_root
        from app.tools.registry import get_tool_registry
        from app.tools.tool_meta import (
            VALID_ROLES,
            resolve_group,
            upsert_dynamic_meta,
        )

        safe_name = name.strip().lower().replace(" ", "_")
        if not safe_name or not safe_name.replace("_", "").isalnum():
            return _json.dumps(
                {
                    "error": "Invalid name. Use letters, numbers, underscores only.",
                    "hint": "Example: get_weather, product_price_lookup",
                },
                ensure_ascii=False,
            )
        if safe_name.startswith(("_", ".")):
            return _json.dumps(
                {
                    "error": f"Name [{safe_name}] cannot start with '_' or '.' "
                    "(skills scanner ignores such folders).",
                    "hint": "Use a normal name like weather_lookup.",
                },
                ensure_ascii=False,
            )

        from app.tools.protection import (
            can_llm_create,
            can_llm_update,
            is_protected_skill,
            is_reserved_name,
            protection_reason,
        )

        skill_dir = skills_root() / safe_name
        existing = get_tool_registry().get(safe_name)

        # System / workspace / reserved: never create or overwrite
        if is_reserved_name(safe_name) or (
            existing is not None and existing.source == "builtin"
        ):
            return _json.dumps(
                {
                    "error": protection_reason(safe_name)
                    or f"[{safe_name}] is system-reserved / builtin.",
                    "hint": "换一个名字。workspace、memory、create_tool 等系统工具不可被 skill 覆盖。",
                    "conflict_source": "builtin_or_reserved",
                    "protected": True,
                },
                ensure_ascii=False,
            )

        # Protected platform skills: no update (and no create under same id)
        if is_protected_skill(safe_name):
            ok_u, why = can_llm_update(safe_name)
            if not ok_u:
                return _json.dumps(
                    {
                        "error": why,
                        "hint": "受保护 skill 只能 read_skill 查看，不能 create_tool 覆盖。",
                        "protected": True,
                    },
                    ensure_ascii=False,
                )

        # --- update / backup logic ---
        _backup_dir = None
        is_update = bool(update) and skill_dir.exists()
        if skill_dir.exists():
            if not update:
                return _json.dumps(
                    {
                        "error": f"Tool/skill [{safe_name}] already exists. Set update=true to overwrite it.",
                        "hint": (
                            "先 read_skill(name=%s)，再 create_tool(name=%s, update=true)。"
                            "禁止新建 %s_v2 / %s_fixed 等等价 skill。"
                        )
                        % (safe_name, safe_name, safe_name, safe_name),
                        "path": str(skill_dir),
                        "action_required": "update_primary",
                        "primary_name": safe_name,
                    },
                    ensure_ascii=False,
                )
            ok_u, why = can_llm_update(safe_name)
            if not ok_u:
                return _json.dumps(
                    {"error": why, "protected": True},
                    ensure_ascii=False,
                )
            _backup_dir = _Path(tempfile.mkdtemp()) / safe_name
            shutil.copytree(str(skill_dir), str(_backup_dir))
        else:
            ok_c, why = can_llm_create(safe_name)
            if not ok_c:
                return _json.dumps(
                    {"error": why, "protected": True},
                    ensure_ascii=False,
                )
            # Block accidental "equivalent" skills (nas_fixed, weather_v2, …)
            if not force_new:
                near = _find_near_skill_duplicates(safe_name, skills_root())
                if near:
                    primary = near[0]
                    stem = _canonical_skill_stem(safe_name)
                    if stem in near:
                        primary = stem
                    return _json.dumps(
                        {
                            "error": (
                                f"拒绝创建等价 skill [{safe_name}]："
                                f"已存在相近主入口 {near}。"
                            ),
                            "hint": (
                                f"请 read_skill('{primary}') 后 "
                                f"create_tool(name='{primary}', update=true, …) 就地更新。"
                                "若确实要全新独立工具，传 force_new=true。"
                            ),
                            "action_required": "update_primary",
                            "primary_name": primary,
                            "near_duplicates": near,
                        },
                        ensure_ascii=False,
                    )
        # --- end update/backup ---

        try:
            params = _json.loads(parameters) if isinstance(parameters, str) else parameters
        except _json.JSONDecodeError as e:
            return _json.dumps({"error": f"Invalid parameters JSON: {e}"}, ensure_ascii=False)
        if not isinstance(params, dict):
            params = {"type": "object", "properties": {}}

        has_handler = bool((handler_code or "").strip())
        has_http = bool((url or "").strip())
        if not has_handler and not has_http:
            return _json.dumps(
                {
                    "error": "Provide handler_code (Python) or url (HTTP).",
                    "hint": (
                        "HTTP: url+method。Python: 可只写 async def handle(**kwargs)->str，"
                        "系统会自动补 register() 并注册为 create_tool 的 name。"
                    ),
                },
                ensure_ascii=False,
            )

        # Normalize meta
        role_n = (role or "primary").strip().lower()
        if role_n not in VALID_ROLES:
            role_n = "primary"
        # Prefer primary for real capabilities; equivalent only if explicitly requested
        if role_n == "equivalent" and is_update:
            role_n = "primary"
        kw_list = _parse_scene_keywords(scene_keywords)
        _skip_tokens = {
            "test", "tmp", "temp", "demo", "new", "tool", "skill", "p2", "v1", "v2",
            "fixed", "fix", "copy",
        }
        for part in safe_name.split("_"):
            if (
                len(part) >= 3
                and part.lower() not in _skip_tokens
                and not part.isdigit()
                and part not in kw_list
            ):
                kw_list.append(part)

        tag_n = (tag or safe_name.replace("_", " ")).strip()[:32]
        desc_final = _enrich_tool_description(
            description, tag=tag_n, scene_keywords=kw_list
        )
        group_n = resolve_group(safe_name, group, desc_final, kw_list)

        # Version: bump on update, start 0.1.0 on create
        prev_version = "0.1.0"
        if is_update and skill_dir.joinpath("manifest.json").exists():
            try:
                prev_man = _json.loads(
                    skill_dir.joinpath("manifest.json").read_text(encoding="utf-8")
                )
                prev_version = str(prev_man.get("version") or "0.1.0")
            except Exception:
                prev_version = "0.1.0"
        version_n = _bump_version(prev_version) if is_update else "0.1.0"
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        change_note = (changelog or "").strip() or (
            "update in-place" if is_update else "initial create"
        )

        skill_dir.mkdir(parents=True, exist_ok=True)

        scaffold_notes: list[str] = []
        code_to_write = ""
        if has_handler:
            code_to_write, scaffold_notes = _normalize_handler_code(
                safe_name, desc_final, handler_code, params
            )
            try:
                compile(code_to_write, f"{safe_name}/handler.py", "exec")
            except SyntaxError as e:
                if is_update and _backup_dir and _backup_dir.exists():
                    shutil.rmtree(skill_dir, ignore_errors=True)
                    shutil.copytree(str(_backup_dir), str(skill_dir))
                else:
                    shutil.rmtree(skill_dir, ignore_errors=True)
                return _json.dumps(
                    {
                        "error": f"Python syntax error: {e}",
                        "hint": (
                            "可只提交 async def handle(**kwargs)->str 函数体；"
                            "避免半截 register。参数 parameters 须是合法 JSON schema。"
                        ),
                        "scaffold_notes": scaffold_notes,
                    },
                    ensure_ascii=False,
                )

        manifest_tools = []
        if has_http:
            try:
                headers_dict = _json.loads(headers) if isinstance(headers, str) else {}
            except _json.JSONDecodeError:
                headers_dict = {}
            manifest_tools.append(
                {
                    "name": safe_name,
                    "description": desc_final,
                    "type": "http",
                    "method": (method or "GET").upper(),
                    "url": url,
                    "headers": headers_dict,
                    "parameters": params,
                }
            )

        # Preserve changelog history on update
        history: list[dict[str, str]] = []
        if is_update and _backup_dir and (_backup_dir / "manifest.json").exists():
            try:
                old_m = _json.loads(
                    (_backup_dir / "manifest.json").read_text(encoding="utf-8")
                )
                history = list(old_m.get("changelog") or [])
                if not isinstance(history, list):
                    history = []
            except Exception:
                history = []
        history.append(
            {
                "version": version_n,
                "at": ts,
                "note": change_note[:300],
            }
        )
        history = history[-20:]

        manifest = {
            "id": safe_name,
            "name": safe_name.replace("_", " ").title(),
            "description": desc_final,
            "version": version_n,
            "tools": manifest_tools,
            "changelog": history,
            "agentos_meta": {
                "role": role_n,
                "tag": tag_n,
                "group": group_n,
                "scene_keywords": kw_list,
                "dynamic": True,
                "version": version_n,
            },
        }
        skill_dir.joinpath("manifest.json").write_text(
            _json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        if has_handler and code_to_write:
            skill_dir.joinpath("handler.py").write_text(code_to_write, encoding="utf-8")
            # Preflight before hot-reload (clearer errors than silent miss)
            pre_err = _preflight_load_handler(skill_dir, safe_name)
            if pre_err:
                if is_update and _backup_dir and _backup_dir.exists():
                    shutil.rmtree(skill_dir, ignore_errors=True)
                    shutil.copytree(str(_backup_dir), str(skill_dir))
                else:
                    shutil.rmtree(skill_dir, ignore_errors=True)
                return _json.dumps(
                    {
                        "error": f"Skill load preflight failed: {pre_err}",
                        "expected_name": safe_name,
                        "scaffold_notes": scaffold_notes,
                        "hint": (
                            "最稳写法：只提供 async def handle(**kwargs)->str 返回 json.dumps(...)。"
                            "系统会注册为 name 与 create_tool 的 name 一致。"
                            "若手写 register，registry.register 第一个参数必须是 "
                            f"{safe_name!r}。"
                        ),
                    },
                    ensure_ascii=False,
                )

        # SKILL.md with version / changelog
        hist_lines = "\n".join(
            f"- `{h.get('version')}` ({h.get('at')}): {h.get('note')}" for h in history
        )
        skill_md = (
            f"# {safe_name.replace('_', ' ').title()}\n\n"
            f"{desc_final}\n\n"
            f"## Version\n\n"
            f"- current: `{version_n}`\n"
            f"- updated: {ts}\n\n"
            f"## Changelog\n\n"
            f"{hist_lines or '- (none)'}\n\n"
            f"## AgentOS meta\n\n"
            f"- role: `{role_n}`\n"
            f"- tag: `{tag_n}`\n"
            f"- group: `{group_n}`\n"
            f"- scene_keywords: {', '.join(kw_list) if kw_list else '(none)'}\n\n"
            f"## Notes\n\n"
            f"- Call name: `{safe_name}`\n"
            f"- Soft filter (P2): include Chinese/English keywords, tool name, or 「全部工具」.\n"
            f"- Update in place: read_skill → create_tool(name={safe_name}, update=true).\n"
            f"- Do not create `{safe_name}_v2` / `{safe_name}_fixed` equivalents.\n"
        )
        skill_dir.joinpath("SKILL.md").write_text(skill_md, encoding="utf-8")

        # Persist P0–P2 dynamic meta before reload
        meta_entry = upsert_dynamic_meta(
            safe_name,
            role=role_n,
            tag=tag_n,
            group=group_n,
            scene_keywords=kw_list,
            description_hint=desc_final[:200],
            version=version_n,
            changelog=change_note,
        )

        from app.services.runtime import rebuild_runtime

        await rebuild_runtime()

        registered = _collect_skill_registered_tools(safe_name)
        skill_registered = [r for r in registered if r.get("source") == "skill"]
        name_ok = any(r["name"] == safe_name and r["source"] == "skill" for r in skill_registered)

        if not skill_registered:
            # rollback files
            shutil.rmtree(skill_dir, ignore_errors=True)
            if is_update and _backup_dir and _backup_dir.exists():
                shutil.copytree(str(_backup_dir), str(skill_dir))
                await rebuild_runtime()
            else:
                try:
                    from app.tools.tool_meta import remove_dynamic_meta

                    remove_dynamic_meta(safe_name)
                except Exception:
                    pass
            reg = get_tool_registry()
            msg = (
                f"Tool [{safe_name}] REGISTRATION FAILED after reload. "
                "Files rolled back. "
            )
            if reg.get(safe_name) and reg.get(safe_name).source == "builtin":
                msg += "Name conflicts with a builtin. "
            msg += (
                "handler.register() MUST call registry.register(NAME, …) "
                f"with NAME={safe_name!r}."
            )
            related = [
                t.name
                for t in reg.list_tools()
                if safe_name in t.name or t.name in safe_name
            ]
            return _json.dumps(
                {
                    "error": msg,
                    "expected_name": safe_name,
                    "related_registered_names": related[:20],
                    "scaffold_notes": scaffold_notes,
                    "tip": "Prefer bare async def handle; avoid wrong register names.",
                },
                ensure_ascii=False,
            )

        if not name_ok:
            other_names = [r["name"] for r in skill_registered]
            return _json.dumps(
                {
                    "ok": True,
                    "warning": (
                        f"Skill loaded, but tool name [{safe_name}] was not registered as skill. "
                        f"Registered instead: {other_names}."
                    ),
                    "tool_name": safe_name,
                    "registered_tools": skill_registered,
                    "type": "skill",
                    "version": version_n,
                    "path": str(skill_dir.resolve()),
                    "meta": meta_entry,
                    "updated": is_update,
                    "scaffold_notes": scaffold_notes,
                    "tips": [
                        f"Prefer registry.register('{safe_name}', …).",
                        "Next fix: read_skill → create_tool(update=true) on THIS name.",
                    ],
                },
                ensure_ascii=False,
            )

        extra = [r["name"] for r in skill_registered if r["name"] != safe_name]

        return _json.dumps(
            {
                "ok": True,
                "tool_name": safe_name,
                "registered_tools": skill_registered,
                "extra_tools": extra,
                "type": "skill",
                "version": version_n,
                "previous_version": prev_version if is_update else None,
                "updated": is_update,
                "changelog_entry": history[-1] if history else None,
                "path": str(skill_dir.resolve()),
                "meta": meta_entry,
                "group": group_n,
                "description": desc_final[:300],
                "scaffold_notes": scaffold_notes,
                "tips": [
                    f"Call tool name: {safe_name}",
                    f"UI group: {group_n}",
                    f"Version: {version_n}",
                    "Later fixes: read_skill → create_tool(name=同一名字, update=true, changelog='…').",
                    "Do not create *_v2 / *_fixed equivalents.",
                    "Credentials/hosts/API endpoints → tool `integrations` "
                    f"(upsert id={safe_name} or catalog id); never hardcode secrets; never dump secrets into kb.",
                ],
                "config_hint": (
                    "If this skill needs hosts/URL/password/token, call integrations "
                    f"action=upsert id={safe_name} (or nas/nocodb/qbittorrent/http/netops) "
                    "with fields_json; handler should read app.services.credentials."
                ),
            },
            ensure_ascii=False,
        )

    async def manage_integrations(
        action: str,
        id: str = "",
        fields_json: str = "",
    ) -> str:
        """List / get / upsert / delete skill connection configs (设定→集成).

        Use this for hosts, URLs, usernames, passwords, tokens — NOT kb, NOT skill code.
        """
        import json as _json

        act = (action or "list").strip().lower()
        iid = (id or "").strip()
        store = None
        try:
            from app.config_store import get_config_store

            store = get_config_store()
        except Exception as exc:
            return _json.dumps({"ok": False, "error": f"config store: {exc}"}, ensure_ascii=False)

        try:
            if act in ("list", "ls"):
                items = store.list_integrations_public()
                return _json.dumps(
                    {
                        "ok": True,
                        "action": "list",
                        "count": len(items),
                        "items": items,
                        "hint": "Secrets are masked (*_set=true means configured). "
                        "Update with action=upsert id=... fields_json={...}.",
                    },
                    ensure_ascii=False,
                )

            if act in ("get", "show"):
                if not iid:
                    return _json.dumps(
                        {"ok": False, "error": "id required for get"},
                        ensure_ascii=False,
                    )
                row = store.get_integration_public(iid)
                if not row:
                    return _json.dumps(
                        {
                            "ok": False,
                            "error": f"integration [{iid}] not found",
                            "hint": "Use list; catalog includes http/nas/nocodb/qbittorrent/netops "
                            "or create custom id matching skill name.",
                        },
                        ensure_ascii=False,
                    )
                return _json.dumps({"ok": True, "action": "get", "item": row}, ensure_ascii=False)

            if act in ("upsert", "set", "update", "save", "put"):
                if not iid:
                    return _json.dumps(
                        {"ok": False, "error": "id required for upsert"},
                        ensure_ascii=False,
                    )
                fields: dict[str, Any] = {}
                raw = (fields_json or "").strip()
                if raw:
                    try:
                        parsed = _json.loads(raw)
                        if not isinstance(parsed, dict):
                            return _json.dumps(
                                {"ok": False, "error": "fields_json must be a JSON object"},
                                ensure_ascii=False,
                            )
                        fields = parsed
                    except _json.JSONDecodeError as exc:
                        return _json.dumps(
                            {"ok": False, "error": f"invalid fields_json: {exc}"},
                            ensure_ascii=False,
                        )
                if not fields:
                    return _json.dumps(
                        {
                            "ok": False,
                            "error": "fields_json empty",
                            "hint": 'Example netops: {"hosts_json":"{\\"nas\\":{\\"host\\":\\"10.0.0.1\\",'
                            '\\"user\\":\\"admin\\",\\"port\\":22,\\"password\\":\\"\\",\\"ports\\":[22]}}"} '
                            'or {"hosts":{"nas":{...}}}. nas: {"host","user","password","port"}.',
                        },
                        ensure_ascii=False,
                    )
                row = store.upsert_integration(iid, fields)
                return _json.dumps(
                    {
                        "ok": True,
                        "action": "upsert",
                        "id": iid,
                        "item": row,
                        "hint": "Skill code should read via app.services.credentials "
                        "(nas_config/nocodb_config/qb_config/http_network_config/netops_config). "
                        "Do not store these secrets in kb.",
                    },
                    ensure_ascii=False,
                )

            if act in ("delete", "remove", "clear", "reset"):
                if not iid:
                    return _json.dumps(
                        {"ok": False, "error": "id required for delete"},
                        ensure_ascii=False,
                    )
                ok = store.delete_integration(iid)
                return _json.dumps(
                    {
                        "ok": ok,
                        "action": "delete",
                        "id": iid,
                        "hint": "Builtin integrations reset to defaults; custom entries removed.",
                    },
                    ensure_ascii=False,
                )

            return _json.dumps(
                {
                    "ok": False,
                    "error": f"unknown action [{action}]",
                    "hint": "Use list|get|upsert|delete",
                },
                ensure_ascii=False,
            )
        except ValueError as exc:
            return _json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        except Exception as exc:
            return _json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    # delete tool / skill
    async def delete_agent_tool(name: str) -> str:
        """Delete a mutable skill by name (removes files and unregisters).

        Builtin / reserved / protected skills cannot be deleted.
        Business skills (http, office, nas, …) can be deleted by the LLM.
        """
        import json as _json
        import shutil

        from app.services.skills import skills_root
        from app.tools.protection import can_llm_delete, protection_reason
        from app.tools.registry import get_tool_registry
        from app.tools.tool_meta import remove_dynamic_meta

        safe_name = name.strip().lower().replace(" ", "_")
        if not safe_name or not safe_name.replace("_", "").isalnum():
            return _json.dumps(
                {"error": "Invalid tool name. Use letters, numbers, underscores only."},
                ensure_ascii=False,
            )

        ok_d, why = can_llm_delete(safe_name)
        if not ok_d:
            return _json.dumps(
                {
                    "error": why or protection_reason(safe_name),
                    "protected": True,
                    "hint": "只能删除非保护业务 skill；系统工具与 workspace 相关能力不可删。",
                },
                ensure_ascii=False,
            )

        skill_dir = skills_root() / safe_name
        if not skill_dir.exists():
            existing = get_tool_registry().get(safe_name)
            if existing is not None and existing.source == "skill":
                return _json.dumps(
                    {
                        "error": f"Tool [{safe_name}] is registered as skill but folder missing.",
                        "hint": "Try reload_runtime.",
                    },
                    ensure_ascii=False,
                )
            return _json.dumps(
                {"error": f"Tool/skill [{safe_name}] not found."},
                ensure_ascii=False,
            )

        shutil.rmtree(skill_dir, ignore_errors=True)
        remove_dynamic_meta(safe_name)

        from app.services.runtime import rebuild_runtime

        await rebuild_runtime()

        return _json.dumps(
            {"ok": True, "deleted": safe_name, "meta_removed": True},
            ensure_ascii=False,
        )

    async def kb_tool(
        action: str,
        title: str = "",
        content: str = "",
        page_id: str = "",
        query: str = "",
        tags: str = "",
        collection: str = "",
        heading: str = "",
        text: str = "",
        pinned: bool = False,
        limit: int = 10,
        changelog: str = "",
    ) -> str:
        """Wiki knowledge base: search / get / list / create_page / update_page / append / delete."""
        from app.knowledge.store import get_knowledge_store

        store = get_knowledge_store()
        await store.ensure_seed()
        act = (action or "").strip().lower()
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        coll = (collection or "").strip() or None

        try:
            if act in ("list", "list_pages"):
                rows = await store.list_pages(collection=coll, limit=max(1, min(limit, 100)))
                return json.dumps({"ok": True, "action": "list", "count": len(rows), "pages": rows}, ensure_ascii=False)
            if act in ("list_collections", "collections"):
                cols = await store.list_collections()
                return json.dumps({"ok": True, "action": "list_collections", "collections": cols}, ensure_ascii=False)
            if act in ("search", "find"):
                q = (query or title or content or "").strip()
                if not q:
                    return json.dumps({"ok": False, "error": "query required for search"}, ensure_ascii=False)
                hits = await store.search(q, collection=coll, limit=max(1, min(limit, 20)))
                slim = [
                    {
                        "id": h.get("id"),
                        "title": h.get("title"),
                        "score": h.get("score"),
                        "tags": h.get("tags"),
                        "collection": h.get("collection"),
                        "snippet": h.get("snippet") or (h.get("content") or "")[:300],
                    }
                    for h in hits
                ]
                return json.dumps({"ok": True, "action": "search", "query": q, "count": len(slim), "pages": slim}, ensure_ascii=False)
            if act in ("get", "read"):
                key = (page_id or title or query or "").strip()
                if not key:
                    return json.dumps({"ok": False, "error": "page_id or title required"}, ensure_ascii=False)
                page = await store.get(key) or await store.get_by_title_or_slug(key)
                if not page:
                    return json.dumps({"ok": False, "error": f"page not found: {key}"}, ensure_ascii=False)
                page = dict(page)
                page.pop("versions", None)
                return json.dumps({"ok": True, "action": "get", "page": page}, ensure_ascii=False, default=str)
            if act in ("create_page", "create", "add"):
                if not (title or "").strip():
                    return json.dumps({"ok": False, "error": "title required"}, ensure_ascii=False)
                page = await store.create(
                    title=title.strip(),
                    content=content or "",
                    tags=tag_list,
                    collection=coll or "default",
                    pinned=bool(pinned),
                )
                return json.dumps({"ok": True, "action": "create_page", "page": page}, ensure_ascii=False, default=str)
            if act in ("update_page", "update"):
                pid = (page_id or "").strip()
                if not pid and title:
                    existing = await store.get_by_title_or_slug(title)
                    pid = (existing or {}).get("id") or ""
                if not pid:
                    return json.dumps({"ok": False, "error": "page_id (or existing title) required"}, ensure_ascii=False)
                page = await store.update(
                    pid,
                    title=title or None,
                    content=content if content != "" else None,
                    tags=tag_list or None,
                    collection=coll,
                    changelog=changelog or "kb tool update",
                )
                if not page:
                    return json.dumps({"ok": False, "error": "page not found"}, ensure_ascii=False)
                return json.dumps({"ok": True, "action": "update_page", "page": page}, ensure_ascii=False, default=str)
            if act in ("append",):
                pid = (page_id or "").strip()
                if not pid and title:
                    existing = await store.get_by_title_or_slug(title)
                    pid = (existing or {}).get("id") or ""
                body = (text or content or "").strip()
                if not pid or not body:
                    return json.dumps({"ok": False, "error": "page_id and text/content required"}, ensure_ascii=False)
                page = await store.append(pid, body, heading=heading, changelog=changelog or "append")
                if not page:
                    return json.dumps({"ok": False, "error": "page not found"}, ensure_ascii=False)
                return json.dumps({"ok": True, "action": "append", "page": page}, ensure_ascii=False, default=str)
            if act in ("delete", "remove"):
                pid = (page_id or "").strip()
                if not pid:
                    return json.dumps({"ok": False, "error": "page_id required"}, ensure_ascii=False)
                ok = await store.delete(pid)
                return json.dumps({"ok": ok, "action": "delete", "id": pid}, ensure_ascii=False)
            return json.dumps(
                {
                    "ok": False,
                    "error": f"Unknown action: {action}",
                    "hint": "list|search|get|create_page|update_page|append|delete|list_collections",
                },
                ensure_ascii=False,
            )
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    async def workflow_tool(
        action: str,
        workflow_id: str = "",
        name: str = "",
        description: str = "",
        steps_json: str = "",
        inputs_json: str = "",
        run_id: str = "",
        enabled: bool = True,
    ) -> str:
        """Workflow single entry: list/get/create/update/save/run/delete (+ runs)."""
        from app.workflow.engine import get_workflow_engine, in_workflow_agent
        from app.workflow.store import get_workflow_store

        store = get_workflow_store()
        await store.ensure_seed()
        act = (action or "").strip().lower()

        def _parse_json(raw: str, default: Any) -> Any:
            if not (raw or "").strip():
                return default
            try:
                return json.loads(raw)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON: {e}") from e

        def _normalize_steps(raw: Any) -> list[dict[str, Any]] | None:
            if raw is None:
                return None
            if isinstance(raw, str):
                raw = _parse_json(raw, None)
            if raw is None:
                return None
            if not isinstance(raw, list):
                raise ValueError("steps_json 必须是数组")
            out: list[dict[str, Any]] = []
            for i, s in enumerate(raw):
                if not isinstance(s, dict):
                    raise ValueError(f"steps[{i}] 必须是对象")
                item = dict(s)
                if not item.get("id"):
                    item["id"] = f"step_{i + 1}"
                st = str(item.get("type") or "tool").strip().lower()
                item["type"] = st
                if st not in ("tool", "note", "human_gate", "agent"):
                    raise ValueError(
                        f"steps[{i}] type 无效: {st}（用 tool|note|human_gate|agent）"
                    )
                if st == "tool" and not (item.get("tool") or item.get("name")):
                    raise ValueError(f"steps[{i}] tool 步骤缺少 tool 名")
                if st == "agent" and not str(
                    item.get("prompt") or item.get("message") or ""
                ).strip():
                    raise ValueError(f"steps[{i}] agent 步骤缺少 prompt")
                out.append(item)
            return out

        try:
            if act in ("list", "list_workflows"):
                items = await store.list_definitions()
                return json.dumps({"ok": True, "action": "list", "count": len(items), "workflows": items}, ensure_ascii=False)
            if act in ("get", "read"):
                wid = (workflow_id or name or "").strip()
                if not wid:
                    return json.dumps(
                        {"ok": False, "error": "workflow_id 或 name 必填"},
                        ensure_ascii=False,
                    )
                data = await store.get_definition(wid)
                if not data:
                    return json.dumps({"ok": False, "error": f"not found: {wid}"}, ensure_ascii=False)
                return json.dumps({"ok": True, "action": "get", "workflow": data}, ensure_ascii=False)
            if act in ("save", "create", "update", "upsert"):
                if in_workflow_agent():
                    return json.dumps(
                        {
                            "ok": False,
                            "error": "工作流 agent 步骤内禁止 save/create/update workflow",
                        },
                        ensure_ascii=False,
                    )
                wid_in = (workflow_id or "").strip() or None
                nm = (name or wid_in or "").strip()
                # locate existing by id or name
                existing = None
                if wid_in:
                    existing = await store.get_definition(wid_in)
                if not existing and nm:
                    existing = await store.get_definition(nm)

                if act == "create":
                    if not nm:
                        return json.dumps(
                            {"ok": False, "error": "create 需要 name"},
                            ensure_ascii=False,
                        )
                    if existing:
                        return json.dumps(
                            {
                                "ok": False,
                                "error": f"已存在: {existing.get('id')}，请用 action=update",
                                "existing_id": existing.get("id"),
                            },
                            ensure_ascii=False,
                        )
                    steps = _normalize_steps(steps_json if (steps_json or "").strip() else "[]")
                    if not steps:
                        return json.dumps(
                            {"ok": False, "error": "create 至少需要一个步骤（steps_json）"},
                            ensure_ascii=False,
                        )
                    inputs = _parse_json(inputs_json, {})
                    if not isinstance(inputs, dict):
                        inputs = {}
                    data = await store.save_definition(
                        name=nm,
                        description=description or "",
                        steps=steps,
                        inputs=inputs,
                        enabled=bool(enabled),
                        wf_id=wid_in,
                    )
                    return json.dumps(
                        {"ok": True, "action": "create", "workflow": data},
                        ensure_ascii=False,
                    )

                if act == "update":
                    if not existing:
                        return json.dumps(
                            {
                                "ok": False,
                                "error": "update 目标不存在（传 workflow_id 或 name）",
                            },
                            ensure_ascii=False,
                        )
                    steps = (
                        _normalize_steps(steps_json)
                        if (steps_json or "").strip()
                        else None
                    )
                    if (steps_json or "").strip() and not steps:
                        return json.dumps(
                            {
                                "ok": False,
                                "error": "steps_json 不能为空数组；省略则保留原步骤",
                            },
                            ensure_ascii=False,
                        )
                    inputs = (
                        _parse_json(inputs_json, None)
                        if (inputs_json or "").strip()
                        else None
                    )
                    if inputs is not None and not isinstance(inputs, dict):
                        return json.dumps(
                            {"ok": False, "error": "inputs_json 必须是对象"},
                            ensure_ascii=False,
                        )
                    # name optional rename; if only used as locator keep display name
                    new_nm = (name or "").strip()
                    if new_nm and new_nm == (workflow_id or "").strip():
                        new_nm = str(existing.get("name") or existing.get("id"))
                    if not new_nm:
                        new_nm = str(existing.get("name") or existing.get("id"))
                    # if name was locator (no workflow_id) and equals existing name, keep it
                    if not (workflow_id or "").strip() and name and name == (
                        existing.get("name") or ""
                    ):
                        new_nm = str(existing.get("name") or existing.get("id"))
                    data = await store.save_definition(
                        name=new_nm,
                        description=description
                        if description != ""
                        else (existing.get("description") or ""),
                        steps=steps,
                        inputs=inputs,
                        enabled=bool(enabled),
                        wf_id=str(existing.get("id")),
                    )
                    return json.dumps(
                        {"ok": True, "action": "update", "workflow": data},
                        ensure_ascii=False,
                    )

                # save / upsert
                if not nm and existing:
                    nm = str(existing.get("name") or existing.get("id"))
                if not nm:
                    return json.dumps({"ok": False, "error": "name required"}, ensure_ascii=False)
                steps = (
                    _normalize_steps(steps_json)
                    if (steps_json or "").strip()
                    else None
                )
                inputs = _parse_json(inputs_json, {})
                if not isinstance(inputs, dict):
                    inputs = {}
                data = await store.save_definition(
                    name=nm,
                    description=description or "",
                    steps=steps if isinstance(steps, list) else None,
                    inputs=inputs,
                    enabled=bool(enabled),
                    wf_id=wid_in or (str(existing.get("id")) if existing else None),
                )
                return json.dumps(
                    {"ok": True, "action": act, "workflow": data},
                    ensure_ascii=False,
                )
            if act in ("run", "start", "execute"):
                if in_workflow_agent():
                    return json.dumps(
                        {
                            "ok": False,
                            "error": "工作流 agent 步骤内请勿再次 run workflow（防递归）。请直接完成本步任务。",
                        },
                        ensure_ascii=False,
                    )
                wid = (workflow_id or name or "").strip()
                if not wid:
                    return json.dumps({"ok": False, "error": "workflow_id required"}, ensure_ascii=False)
                inputs = _parse_json(inputs_json, {})
                if not isinstance(inputs, dict):
                    inputs = {}
                result = await get_workflow_engine().run(wid, inputs=inputs, trigger="agent")
                return json.dumps(result, ensure_ascii=False, default=str)
            if act in ("status", "get_run"):
                rid = (run_id or "").strip()
                if not rid:
                    return json.dumps({"ok": False, "error": "run_id required"}, ensure_ascii=False)
                run = await store.get_run(rid)
                if not run:
                    return json.dumps({"ok": False, "error": "run not found"}, ensure_ascii=False)
                return json.dumps({"ok": True, "action": "status", "run": run}, ensure_ascii=False, default=str)
            if act in ("list_runs", "runs"):
                rows = await store.list_runs(workflow_id=(workflow_id or None) or None, limit=20)
                return json.dumps({"ok": True, "action": "list_runs", "runs": rows}, ensure_ascii=False)
            if act in ("resume", "continue", "approve"):
                rid = (run_id or "").strip()
                if not rid:
                    return json.dumps({"ok": False, "error": "run_id required for resume"}, ensure_ascii=False)
                note = (description or name or "").strip()
                approved = act != "reject" and (action or "").lower() not in ("reject", "deny")
                result = await get_workflow_engine().resume(
                    rid, approved=approved, note=note
                )
                return json.dumps(result, ensure_ascii=False, default=str)
            if act in ("reject", "deny"):
                rid = (run_id or "").strip()
                if not rid:
                    return json.dumps({"ok": False, "error": "run_id required"}, ensure_ascii=False)
                result = await get_workflow_engine().resume(
                    rid, approved=False, note=(description or "用户拒绝")
                )
                return json.dumps(result, ensure_ascii=False, default=str)
            if act in ("delete", "remove"):
                if in_workflow_agent():
                    return json.dumps(
                        {
                            "ok": False,
                            "error": "工作流 agent 步骤内禁止 delete workflow",
                        },
                        ensure_ascii=False,
                    )
                wid = (workflow_id or name or "").strip()
                if not wid:
                    return json.dumps(
                        {"ok": False, "error": "workflow_id 或 name 必填（可用中文名称）"},
                        ensure_ascii=False,
                    )
                result = await store.delete_definition(wid, delete_runs=True)
                result["action"] = "delete"
                return json.dumps(result, ensure_ascii=False)
            return json.dumps(
                {
                    "ok": False,
                    "error": f"Unknown action: {action}",
                    "hint": "list|get|save|run|status|list_runs|resume|reject|delete",
                },
                ensure_ascii=False,
            )
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    tools: list[tuple[str, str, Any, dict[str, Any]]] = [
     (
         "get_current_time",
            "Get the current UTC/local time.",
            get_current_time,
            {"type": "object", "properties": {}},
        ),
        (
            "calculator",
            "Evaluate a basic arithmetic expression (e.g. 2+3*4).",
            calculator,
            {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Arithmetic expression"},
                },
                "required": ["expression"],
            },
        ),
        (
            "system_info",
            "Return agent and runtime system information.",
            system_info,
            {"type": "object", "properties": {}},
        ),
        (
            "memory",
            "长期记忆（跨会话；面板可见）。"
            "注入是「匹配检索」而非全量：相关条目才会进 prompt，条目再多也不会整库塞 token。"
            "记住时 action=remember，content 写完整自然语言（场景+偏好），kind=preference|template|habit|rule|fact，可加 tags；"
            "始终生效的规则用 kind=rule 或 tags=always/全局。"
            "回忆用 action=recall（query=关键词）；list；delete。"
            "用户说记住/记一下时必须调用 remember，禁止只口头答应。",
            memory_tool,
            {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["remember", "recall", "list", "delete"],
                        "description": "remember=保存记忆; recall=检索; list=列出最近; delete=按id删除",
                    },
                    "content": {
                        "type": "string",
                        "description": "要保存的完整内容（action=remember 必填）；也可作 recall 的查询词",
                    },
                    "kind": {
                        "type": "string",
                        "description": "记忆类型：preference / fact / note / template 等，默认 preference",
                        "default": "preference",
                    },
                    "tags": {
                        "type": "string",
                        "description": "逗号分隔标签，如 video,prompt,template",
                    },
                    "query": {
                        "type": "string",
                        "description": "检索关键词（action=recall）",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "recall/list 返回条数，默认 10",
                        "default": 10,
                    },
                    "id": {
                        "type": "string",
                        "description": "删除用记忆 id（action=delete）",
                    },
                    "memory_id": {
                        "type": "string",
                        "description": "删除用记忆 id，等同 id",
                    },
                },
                "required": ["action"],
            },
        ),
        (
            "kb",
            "【主推·知识库 Wiki】业务标准与长文档（与 memory 短偏好不同）。"
            "action=search|get|list|create_page|update_page|append|delete|list_collections。"
            "collection 分区：sop=流程标准(如产品内容流水线SOP)、product=产品参数、"
            "handbook=手册红线、reference=提示词/模板、daily=临时纪要、default=未分类。"
            "产品多轮/电商流程：优先 search/get「产品内容流水线SOP」(collection=sop)；"
            "摘要被截断时必须 get 全文再执行阶段，禁止凭空编造步骤。"
            "红线/错误处理 → handbook；提示词写法 → reference。"
            "短偏好/「记住」仍用 memory。create_page 需 title+content；"
            "update/append 需 page_id 或已有 title。",
            kb_tool,
            {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "list",
                            "list_collections",
                            "search",
                            "get",
                            "create_page",
                            "update_page",
                            "append",
                            "delete",
                        ],
                        "description": "知识库操作",
                    },
                    "title": {
                        "type": "string",
                        "description": "页面标题（get/search 也可用标题；主 SOP 为「产品内容流水线SOP」）",
                    },
                    "content": {"type": "string", "description": "页面 Markdown 正文"},
                    "page_id": {"type": "string", "description": "页面 id"},
                    "query": {
                        "type": "string",
                        "description": "search 关键词（可含阶段/平台/产品等）",
                    },
                    "tags": {
                        "type": "string",
                        "description": "逗号分隔标签（细关键词，不是 collection）",
                    },
                    "collection": {
                        "type": "string",
                        "description": (
                            "分类：sop|product|handbook|reference|daily|default。"
                            "search/list 可按分类过滤；create 默认 default，产品流程页建议 sop"
                        ),
                        "default": "default",
                    },
                    "heading": {"type": "string", "description": "append 时可选二级标题"},
                    "text": {"type": "string", "description": "append 正文"},
                    "pinned": {"type": "boolean", "description": "是否置顶"},
                    "limit": {"type": "integer", "default": 10},
                    "changelog": {"type": "string", "description": "更新说明"},
                },
                "required": ["action"],
            },
        ),
        (
            "workflow",
            "【主推·工作流】唯一入口。"
            "action=list|get|create|update|save|run|status|list_runs|resume|reject|delete。"
            "create=新建（不可覆盖）；update=改已有（可省略 steps_json 保留步骤）；"
            "save=upsert；run 执行；delete 支持 id/中文名并清理运行记录。"
            "步骤 type=tool|note|human_gate|agent；变量 {{inputs.x}} {{steps.id.output}}。",
            workflow_tool,
            {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "list",
                            "get",
                            "create",
                            "update",
                            "save",
                            "run",
                            "status",
                            "list_runs",
                            "resume",
                            "reject",
                            "delete",
                        ],
                        "description": "create/update/save 管理定义；run 执行；delete 删除",
                    },
                    "workflow_id": {
                        "type": "string",
                        "description": "流程 id（get/update/run/delete 可用；也可用 name）",
                    },
                    "name": {
                        "type": "string",
                        "description": "显示名（create 必填；delete/get 可用中文名定位）",
                    },
                    "description": {"type": "string"},
                    "steps_json": {
                        "type": "string",
                        "description": '步骤数组 JSON，例 [{"id":"s1","type":"note","message":"hi"}]',
                    },
                    "inputs_json": {
                        "type": "string",
                        "description": "inputs 对象 JSON（create/update/run）",
                    },
                    "run_id": {"type": "string", "description": "status/resume 用"},
                    "enabled": {"type": "boolean", "default": True},
                },
                "required": ["action"],
            },
        ),
        (
            "integrations",
            "【主推·集成配置】设定→集成：主机/URL/账号/密码/Token/SSH 主机表。"
            "action=list|get|upsert|delete。"
            "create_tool/改 skill 时：代码走 create_tool，连接信息走本工具；"
            "禁止把密钥写进 skill 或塞进知识库 kb。"
            "catalog: http/nas/nocodb/qbittorrent/netops，或与 skill 同名自定义 id。",
            manage_integrations,
            {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "get", "upsert", "delete"],
                        "description": "list=一览；get=单条；upsert=写入/合并；delete=清空/删除",
                    },
                    "id": {
                        "type": "string",
                        "description": "集成 id：http|nas|nocodb|qbittorrent|netops 或自定义（建议=skill 名）",
                    },
                    "fields_json": {
                        "type": "string",
                        "description": (
                            "upsert 时的字段 JSON 对象字符串。"
                            'nas: {"host":"...","user":"...","password":"...","port":445}；'
                            'netops: {"hosts":{"nas":{"host":"10.x","user":"u","port":22,"password":"","ports":[22]}}} '
                            '或 {"hosts_json":"{...}"}；'
                            'nocodb: {"base_url","token"|email/password}；'
                            'qbittorrent: {"base_url","user","password"}；'
                            'http: {"proxy_url","flaresolverr_url"}。'
                            "密码留空表示不修改已有值。"
                        ),
                    },
                },
                "required": ["action"],
            },
        ),
        (
            "create_tool",
            "【主推·创建/更新业务 Skill】skills/ 下新建或就地更新（update=true）并热加载。"
            "修已有能力：必须 name=主入口同一名字 + update=true；禁止 xxx_v2/xxx_fixed 等等价包。"
            "HTTP: url+method；Python: 推荐只写 async def handle(**kwargs)->str，系统自动 register。"
            "修改前 read_skill。group 建议传 vision|media|network|infra|office|dev…（可自动推断）。"
            "update 会自动升 version 并写 changelog。"
            "主机/账号/密码/Token 禁止写进代码或 kb → 用 integrations upsert；"
            "handler 用 app.services.credentials 读取。",
            create_agent_tool,
            {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Skill/tool id（小写+下划线），必须与主入口一致。"
                            "更新 nas 就用 name=nas，不要 nas_v2。"
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": "何时使用；请含中文场景词便于软过滤与分组推断。",
                    },
                    "handler_code": {
                        "type": "string",
                        "description": (
                            "推荐最小写法（系统自动脚手架）:\n"
                            "async def handle(**kwargs) -> str:\n"
                            "    import json\n"
                            "    from app.services.credentials import nas_config  # 或 netops_config 等\n"
                            "    return json.dumps({...}, ensure_ascii=False)\n\n"
                            "也可手写 def register(registry)，但 registry.register 第一个参数必须等于 name。\n"
                            "HTTP 模式可省略 handler_code。\n"
                            "规则: httpx 异步、超时、json.dumps(ensure_ascii=False)、"
                            "勿硬编码密钥；连接配置用 integrations + credentials。"
                        ),
                    },
                    "parameters": {
                        "type": "string",
                        "description": "OpenAI parameters schema 的 JSON 字符串",
                    },
                    "url": {
                        "type": "string",
                        "description": "HTTP URL，可用 {param} 占位",
                    },
                    "method": {
                        "type": "string",
                        "description": "HTTP method (GET/POST/PUT/DELETE)",
                    },
                    "headers": {
                        "type": "string",
                        "description": 'JSON headers, e.g. {"Authorization":"Bearer xxx"}',
                    },
                    "update": {
                        "type": "boolean",
                        "description": "true=就地覆盖 skills/<name>/ 并升版本。修 bug 必须 true。",
                        "default": False,
                    },
                    "force_new": {
                        "type": "boolean",
                        "description": (
                            "仅当确实要新建与已有 skill 名字相近的独立工具时为 true。"
                            "默认 false：会拦截 nas_fixed 这类等价名。"
                        ),
                        "default": False,
                    },
                    "changelog": {
                        "type": "string",
                        "description": "本次更新说明（写入 manifest/SKILL.md 版本历史）",
                    },
                    "role": {
                        "type": "string",
                        "description": "primary|equivalent|fallback|dev。业务工具用 primary。",
                        "default": "primary",
                    },
                    "tag": {
                        "type": "string",
                        "description": "短标签，如 天气 / NAS",
                    },
                    "group": {
                        "type": "string",
                        "description": (
                            "UI 分组: vision|media|memory|content|workspace|network|"
                            "office|schedule|news|infra|dev|other。"
                            "可省略，系统按 name/description 自动推断。"
                        ),
                    },
                    "scene_keywords": {
                        "type": "string",
                        "description": "逗号分隔或 JSON 数组，P2 软过滤关键词",
                    },
                },
                "required": ["name", "description"],
            },
        ),
        (
            "read_skill",
            "读取 skills/<name>/ 的 manifest、handler.py、SKILL.md。"
            "更新前必用：read_skill → create_tool(name=同一名字, update=true)。",
            read_skill,
            {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "主入口 skill 名，如 nas / http / office（不要 *_v2）",
                    },
                },
                "required": ["name"],
            },
        ),
        (
            "delete_tool",
            "删除可变业务 skill（删 skills/<name>/）。"
            "不可删 builtin/受保护 skill。"
            "清理误建的等价包（如 xxx_fixed）时用此工具，主能力请用 update 而非删建。",
            delete_agent_tool,
            {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "要删除的 skill 名（误建的等价包名）",
                    },
                },
                "required": ["name"],
            },
        ),
    ]

    for name, desc, handler, params in tools:
        registry.register(name, desc, handler, params, source="builtin")
