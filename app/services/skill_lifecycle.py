"""Skill package lifecycle: live (skills/) vs draft (workspace/skills/).

Policy
------
- **live**: `skills/<id>/` — scanned & registered for the agent tool table.
- **draft**: `workspace/skills/<id>/` — editable sandbox; NOT auto-registered.
- Promote: copy draft → live + rebuild_runtime.
- Validate: syntax + optional import/register preflight (no network).

Session sticky meta tools live in session.metadata["skill_meta_sticky"].
"""

from __future__ import annotations

import ast
import importlib.util
import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

META_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "create_tool",
        "delete_tool",
        "read_skill",
        "list_skills",
        "validate_skill",
        "promote_skill",
    }
)

_STICKY_KEY = "skill_meta_sticky"

# User wants to fix/edit an existing skill without saying「创建工具」
_REPAIR_MARKERS = (
    "修好",
    "修一下",
    "修复",
    "bug",
    "debug",
    "不工作",
    "没生效",
    "无效",
    "假成功",
    "更新代码",
    "改代码",
    "改一下",
    "改下",
    "修改",
    "调试",
    "坏了",
    "失败了",
    "不对",
    "完善",
    "深化",
    "fix",
    "broken",
    "not working",
    "doesn't work",
    "does not work",
)


def project_root() -> Path:
    from app.config import PROJECT_ROOT

    return Path(PROJECT_ROOT)


def skills_root() -> Path:
    from app.services.skills import skills_root as _live

    return _live()


def draft_skills_root() -> Path:
    root = project_root() / "workspace" / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return root


def normalize_skill_id(name: str | None) -> str:
    return (name or "").strip().lower().replace(" ", "_")


def live_skill_dir(name: str) -> Path:
    return skills_root() / normalize_skill_id(name)


def draft_skill_dir(name: str) -> Path:
    return draft_skills_root() / normalize_skill_id(name)


def skill_exists(name: str, *, stage: str = "any") -> bool:
    n = normalize_skill_id(name)
    if not n:
        return False
    live = live_skill_dir(n).is_dir()
    draft = draft_skill_dir(n).is_dir()
    st = (stage or "any").lower()
    if st == "live":
        return live
    if st == "draft":
        return draft
    return live or draft


def list_skill_ids(*, include_draft: bool = True) -> dict[str, list[str]]:
    def _scan(root: Path) -> list[str]:
        if not root.is_dir():
            return []
        out: list[str] = []
        for p in sorted(root.iterdir()):
            if p.is_dir() and not p.name.startswith((".", "_")):
                out.append(p.name)
        return out

    return {
        "live": _scan(skills_root()),
        "draft": _scan(draft_skills_root()) if include_draft else [],
    }


def _trim_skill_md_changelog(text: str) -> tuple[str, bool]:
    """Omit long changelog so read_skill does not blow the update context."""
    src = text or ""
    idx = src.find("## Changelog")
    if idx < 0:
        if len(src) > 4000:
            return src[:4000] + "\n\n…（SKILL.md 已截断；read_skill full=true 看全文）\n", True
        return src, False
    body = src[idx:]
    if len(body) < 800:
        return src, False
    head = src[:idx].rstrip()
    return (
        head
        + "\n\n## Changelog\n（已省略长历史；read_skill full=true 可看完整 changelog）\n",
        True,
    )


def read_skill_package(name: str, *, prefer: str = "live", full: bool = False) -> dict[str, Any]:
    """Read draft and/or live package contents."""
    n = normalize_skill_id(name)
    if not n:
        return {"ok": False, "error": "empty name"}

    prefer = (prefer or "live").lower()
    order = ["draft", "live"] if prefer == "draft" else ["live", "draft"]
    found: dict[str, Any] = {"ok": True, "name": n, "stages": {}}

    for stage in ("live", "draft"):
        root = live_skill_dir(n) if stage == "live" else draft_skill_dir(n)
        if not root.is_dir():
            continue
        pack: dict[str, Any] = {
            "stage": stage,
            "path": str(root.resolve()),
            "files": [],
        }
        for f in ("manifest.json", "handler.py", "SKILL.md"):
            fp = root / f
            if not fp.is_file():
                continue
            text = fp.read_text(encoding="utf-8", errors="replace")
            omitted_changelog = False
            if f == "SKILL.md" and not full:
                text, omitted_changelog = _trim_skill_md_changelog(text)
            pack["files"].append(
                {
                    "name": f,
                    "size": fp.stat().st_size,
                    "content": text[:12000],
                    "truncated": len(text) > 12000,
                    "changelog_omitted": omitted_changelog,
                }
            )
        try:
            man = root / "manifest.json"
            if man.is_file():
                pack["manifest"] = json.loads(man.read_text(encoding="utf-8"))
        except Exception as exc:
            pack["manifest_error"] = str(exc)
        found["stages"][stage] = pack

    if not found["stages"]:
        return {
            "ok": False,
            "error": f"Skill [{n}] not found in skills/ or workspace/skills/.",
            "hint": "list_skills 查看已安装；create_tool stage=draft 可先写草稿。",
            "live_root": str(skills_root()),
            "draft_root": str(draft_skills_root()),
        }

    # Primary view
    for stage in order:
        if stage in found["stages"]:
            found["primary_stage"] = stage
            found["path"] = found["stages"][stage]["path"]
            found["files"] = found["stages"][stage]["files"]
            break
    try:
        from app.tools.tool_meta import meta_for

        found["meta"] = meta_for(n)
    except Exception:
        found["meta"] = {}
    return found


def validate_skill_code(
    name: str,
    handler_code: str | None = None,
    *,
    stage: str = "live",
) -> dict[str, Any]:
    """Syntax + light structural checks. Does not hit the network."""
    n = normalize_skill_id(name)
    code = (handler_code or "").strip()
    source = "inline"
    if not code:
        root = draft_skill_dir(n) if stage == "draft" else live_skill_dir(n)
        if stage == "any":
            if draft_skill_dir(n).joinpath("handler.py").is_file():
                root = draft_skill_dir(n)
                stage = "draft"
            else:
                root = live_skill_dir(n)
                stage = "live"
        hp = root / "handler.py"
        if not hp.is_file():
            return {
                "ok": False,
                "error": f"No handler.py for [{n}] stage={stage}",
                "hint": "传 handler_code 或先 create_tool / 写文件",
            }
        code = hp.read_text(encoding="utf-8", errors="replace")
        source = str(hp)

    issues: list[str] = []
    warnings: list[str] = []
    try:
        compile(code, f"{n}/handler.py", "exec")
    except SyntaxError as e:
        return {
            "ok": False,
            "name": n,
            "source": source,
            "error": f"SyntaxError: {e}",
            "issues": [str(e)],
        }

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {"ok": False, "name": n, "error": f"SyntaxError: {e}"}

    has_register = False
    has_handle = False
    register_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name == "register":
                has_register = True
            if node.name in ("handle", "handler"):
                has_handle = True
        if isinstance(node, ast.Call):
            # registry.register("name", ...)
            func = node.func
            attr = getattr(func, "attr", None)
            if attr == "register" and node.args:
                a0 = node.args[0]
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                    register_names.append(a0.value)

    if not has_register and not has_handle:
        issues.append(
            "缺少 register(registry) 或 async def handle(**kwargs)；"
            "create_tool 会自动脚手架，但手写包需要其一。"
        )
    if register_names and n and n not in register_names:
        warnings.append(
            f"registry.register 名 {register_names} 与 skill id [{n}] 不一致；"
            f"主入口建议 register({n!r}, …)。"
        )
    if re.search(r"(password|api_key|secret|token)\s*=\s*['\"][^'\"]+['\"]", code, re.I):
        warnings.append(
            "疑似硬编码密钥；应改用 integrations + app.services.credentials。"
        )
    try:
        from app.services.skill_spec import connection_hacks_in_text

        for hit in connection_hacks_in_text(code):
            issues.append(hit)
    except Exception as exc:
        warnings.append(f"connection-hack check skipped: {exc}")

    try:
        from app.services.skill_schema import (
            is_empty_schema,
            kwargs_get_keys,
            schema_from_handler_code,
        )

        schema = schema_from_handler_code(code)
        used_keys = kwargs_get_keys(code)
        if used_keys and is_empty_schema(schema):
            issues.append(
                "handler 使用 kwargs.get(...) 但 register() schema 为空，"
                "模型无法传参。请提供 parameters / SCHEMA，或 spec.inputs。"
            )
        elif schema and used_keys:
            props = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
            missing = [k for k in used_keys if k not in props]
            if missing:
                warnings.append(
                    "这些 kwargs 未出现在 schema.properties 中: " + ", ".join(missing[:12])
                )
    except Exception as exc:
        warnings.append(f"schema check skipped: {exc}")

    # Optional import preflight when file on disk
    preflight: str | None = None
    if source != "inline":
        try:
            preflight = _preflight_import(Path(source), n)
            if preflight:
                issues.append(preflight)
        except Exception as exc:
            warnings.append(f"preflight skipped: {exc}")

    ok = not issues
    return {
        "ok": ok,
        "name": n,
        "stage": stage,
        "source": source,
        "has_register": has_register,
        "has_handle": has_handle,
        "register_names": register_names,
        "issues": issues,
        "warnings": warnings,
        "hint": (
            "校验通过，可用 promote_skill 发布到 skills/。"
            if ok and stage == "draft"
            else ("校验通过。" if ok else "先修 issues 再 promote/create_tool stage=live。")
        ),
    }


def load_handler_module(handler_py: Path, mod_name: str):
    """Load handler.py with its folder on sys.path so sibling modules import."""
    import sys

    if not handler_py.is_file():
        return None, "handler.py missing"
    spec = importlib.util.spec_from_file_location(mod_name, handler_py)
    if not spec or not spec.loader:
        return None, "cannot load module spec"
    skill_dir = str(handler_py.parent.resolve())
    inserted = skill_dir not in sys.path
    if inserted:
        sys.path.insert(0, skill_dir)
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod, None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"
    finally:
        if inserted:
            try:
                sys.path.remove(skill_dir)
            except ValueError:
                pass


def _preflight_import(handler_py: Path, skill_id: str) -> str | None:
    """Import handler module; return error string or None."""
    mod_name = f"skill_validate_{skill_id}_{abs(hash(str(handler_py))) % 10**8}"
    mod, err = load_handler_module(handler_py, mod_name)
    if err:
        return f"import failed: {err}" if not err.startswith("handler") else err
    if not hasattr(mod, "register") and not hasattr(mod, "handle") and not hasattr(
        mod, "TOOLS"
    ):
        return "module has neither register(), handle(), nor TOOLS"
    return None


def promote_skill(name: str, *, rebuild: bool = True) -> dict[str, Any]:
    """Copy workspace/skills/<id> → skills/<id> and optionally rebuild runtime."""
    n = normalize_skill_id(name)
    src = draft_skill_dir(n)
    dst = live_skill_dir(n)
    if not src.is_dir():
        return {
            "ok": False,
            "error": f"草稿不存在: workspace/skills/{n}/",
            "hint": "先 create_tool(name=…, stage=draft) 或把文件放到 workspace/skills/",
        }

    v = validate_skill_code(n, stage="draft")
    if not v.get("ok"):
        return {
            "ok": False,
            "error": "草稿校验失败，拒绝 promote",
            "validate": v,
        }

    backup: str | None = None
    if dst.is_dir():
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        bak = skills_root() / f".backup_{n}_{ts}"
        if bak.exists():
            shutil.rmtree(bak, ignore_errors=True)
        shutil.copytree(str(dst), str(bak))
        backup = str(bak)
        shutil.rmtree(dst, ignore_errors=True)

    shutil.copytree(str(src), str(dst))
    # Mark promoted in manifest if present
    man_path = dst / "manifest.json"
    if man_path.is_file():
        try:
            man = json.loads(man_path.read_text(encoding="utf-8"))
            man.setdefault("agentos_meta", {})
            if isinstance(man["agentos_meta"], dict):
                man["agentos_meta"]["promoted_from_draft"] = True
                man["agentos_meta"]["promoted_at"] = datetime.now(timezone.utc).isoformat()
            man_path.write_text(
                json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            logger.exception("promote manifest touch failed")

    runtime: dict[str, Any] | None = None
    if rebuild:
        try:
            import asyncio

            from app.services.runtime import rebuild_runtime

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                # Caller should await rebuild; return path only
                runtime = {"deferred": True}
            else:
                runtime = asyncio.run(rebuild_runtime())
        except Exception as exc:
            runtime = {"error": str(exc)}

    return {
        "ok": True,
        "name": n,
        "draft_path": str(src.resolve()),
        "live_path": str(dst.resolve()),
        "backup": backup,
        "validate": v,
        "runtime": runtime,
        "hint": "已发布到 skills/。若 runtime.deferred=true，请 reload_runtime。",
    }


async def promote_skill_async(name: str) -> dict[str, Any]:
    result = promote_skill(name, rebuild=False)
    if not result.get("ok"):
        return result
    try:
        from app.services.runtime import rebuild_runtime

        result["runtime"] = await rebuild_runtime()
    except Exception as exc:
        result["runtime"] = {"error": str(exc)}
    return result


# ---------------------------------------------------------------------------
# Session sticky meta tools
# ---------------------------------------------------------------------------

# Sticky create/delete must not leak into list/chat turns.
_WRITE_META = frozenset(
    {"create_tool", "delete_tool", "promote_skill", "validate_skill"}
)
_READ_META = frozenset({"list_skills", "read_skill"})


def live_meta_tools_for_turn(
    message: str,
    *,
    sticky: set[str] | None = None,
    this_meta: set[str] | None = None,
    pending: bool = False,
    spec_confirmed: bool = False,
) -> set[str]:
    """Meta tools actually offered *this turn*.

    Old-session sticky ``create_tool`` stays on disk for 确认 / 改技能 follow-up,
    but listing or chatting about 技能 must not re-inject create/delete.
    """
    sticky_s = {str(t) for t in (sticky or set()) if str(t) in META_TOOL_NAMES}
    this_s = {str(t) for t in (this_meta or set()) if str(t) in META_TOOL_NAMES}
    if spec_confirmed or pending:
        return (
            sticky_s
            | this_s
            | {
                "create_tool",
                "read_skill",
                "list_skills",
                "validate_skill",
                "promote_skill",
            }
        ) & META_TOOL_NAMES
    try:
        from app.agent.ask_form import skill_turn_kind

        kind = skill_turn_kind(message)
    except Exception:
        kind = None
    if kind in {"create", "update"}:
        return (sticky_s | this_s) & META_TOOL_NAMES
    if kind == "delete":
        return (this_s | {"delete_tool", "read_skill", "list_skills", "validate_skill"}) & META_TOOL_NAMES
    if kind == "list":
        return ((this_s | {"list_skills"} | (sticky_s & _READ_META)) - _WRITE_META) & META_TOOL_NAMES
    return (this_s - _WRITE_META) & META_TOOL_NAMES


def get_sticky_meta_tools(session: dict[str, Any] | None) -> set[str]:
    if not session or not isinstance(session, dict):
        return set()
    meta = session.get("metadata") or {}
    if not isinstance(meta, dict):
        return set()
    sticky = meta.get(_STICKY_KEY) or {}
    if not isinstance(sticky, dict):
        return set()
    tools = sticky.get("tools") or []
    out = {str(t).strip() for t in tools if str(t).strip() in META_TOOL_NAMES}
    return out


def merge_sticky_meta_tools(
    session: dict[str, Any] | None,
    tools: set[str] | list[str],
) -> dict[str, Any]:
    """Return updated metadata dict fragment (does not write disk)."""
    base = {}
    if session and isinstance(session.get("metadata"), dict):
        base = dict(session["metadata"])
    prev = set(get_sticky_meta_tools(session))
    add = {str(t).strip() for t in tools if str(t).strip() in META_TOOL_NAMES}
    # create/delete imply read + list + validate
    if "create_tool" in add or "delete_tool" in add or "promote_skill" in add:
        add |= {"read_skill", "list_skills", "validate_skill"}
    if "read_skill" in add:
        add.add("list_skills")
    merged = sorted(prev | add)
    base[_STICKY_KEY] = {
        "tools": merged,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return base


async def persist_sticky_meta_tools(
    session_id: str,
    tools: set[str] | list[str],
    *,
    sessions: Any | None = None,
) -> set[str]:
    """Merge sticky tools into session metadata on disk."""
    if not session_id:
        return set()
    try:
        if sessions is None:
            from app.memory.session import get_session_store

            sessions = get_session_store()
        data = await sessions.get(session_id)
        if not data:
            return set()
        new_meta = merge_sticky_meta_tools(data, tools)
        sticky_blob = new_meta.get(_STICKY_KEY) or {}
        updater = getattr(sessions, "update_metadata", None)
        if updater:
            await updater(session_id, {_STICKY_KEY: sticky_blob}, merge=True)
        else:
            write = getattr(sessions, "_write", None)
            if not write:
                logger.warning("persist sticky meta tools: session store has no writer")
                return set()
            data["metadata"] = new_meta
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            await write(session_id, data)
        return {str(t) for t in (sticky_blob.get("tools") or []) if str(t) in META_TOOL_NAMES}
    except Exception:
        logger.exception("persist sticky meta tools failed")
        return set()


_PENDING_KEY = "pending_skill_create"


def get_pending_skill_create(session: dict[str, Any] | None) -> dict[str, Any]:
    if not session or not isinstance(session, dict):
        return {}
    meta = session.get("metadata") or {}
    if not isinstance(meta, dict):
        return {}
    pending = meta.get(_PENDING_KEY) or {}
    return pending if isinstance(pending, dict) else {}


async def persist_pending_skill_create(
    session_id: str,
    *,
    name: str = "",
    reason: str = "spec_card",
    sessions: Any | None = None,
) -> None:
    if not session_id:
        return
    try:
        if sessions is None:
            from app.memory.session import get_session_store

            sessions = get_session_store()
        updater = getattr(sessions, "update_metadata", None)
        if not updater:
            return
        await updater(
            session_id,
            {
                _PENDING_KEY: {
                    "name": (name or "").strip(),
                    "reason": reason,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            },
            merge=True,
        )
    except Exception:
        logger.exception("persist pending skill create failed")


async def clear_pending_skill_create(
    session_id: str,
    *,
    sessions: Any | None = None,
) -> None:
    if not session_id:
        return
    try:
        if sessions is None:
            from app.memory.session import get_session_store

            sessions = get_session_store()
        updater = getattr(sessions, "update_metadata", None)
        if not updater:
            return
        await updater(session_id, {_PENDING_KEY: {}}, merge=True)
    except Exception:
        logger.exception("clear pending skill create failed")


def existing_skill_ids() -> set[str]:
    ids = set(list_skill_ids(include_draft=True)["live"])
    ids |= set(list_skill_ids(include_draft=True)["draft"])
    try:
        from app.tools.registry import get_tool_registry

        for t in get_tool_registry().list_tools():
            if t.source == "skill":
                ids.add(t.name)
                md = t.metadata or {}
                if md.get("skill_id"):
                    ids.add(str(md["skill_id"]))
    except Exception:
        pass
    return {normalize_skill_id(x) for x in ids if x}


def mentioned_skill_ids(query: str) -> set[str]:
    """Skill package ids mentioned in user text."""
    if not query:
        return set()
    q = query.lower()
    found: set[str] = set()
    for sid in sorted(existing_skill_ids(), key=len, reverse=True):
        if not sid or len(sid) < 2:
            continue
        if sid in q or sid.replace("_", " ") in q:
            found.add(sid)
    return found


def query_wants_skill_repair(query: str) -> bool:
    if not query:
        return False
    q = query.lower()
    q_compact = q.replace(" ", "")
    for m in _REPAIR_MARKERS:
        ml = m.lower()
        if ml in q or ml.replace(" ", "") in q_compact:
            return True
    return False


_CAPABILITY_GAP_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\.(docx?|xlsx?|pptx?|pdf)\b|"
            r"办公文档|"
            r"\b(docx|xlsx|pptx|pdf)\b|"
            r"(word|excel|ppt|pptx|pdf|work)[,，、/\s]|"
            r"(word|excel|ppt|pptx|pdf|文档).{0,10}(读取|识别|解析|提取|工具)|"
            r"(读取|识别|解析|提取).{0,16}(word|excel|ppt|pptx|pdf|docx|xlsx|文档|文件)|"
            r"(word|excel|ppt|pdf)的?(识别|读取|解析)?工具",
            re.I,
        ),
        "office",
    ),
    (
        re.compile(r"识图|分析(这|下)?图|看(一下)?图|图片分析", re.I),
        "vision",
    ),
)

_OFFICE_FILE_RX = re.compile(
    r"\.(docx?|xlsx?|pptx?|pdf)\b",
    re.I,
)


def text_mentions_office_files(text: str) -> bool:
    return bool(_OFFICE_FILE_RX.search(text or ""))


def missing_capability_meta_tools(query: str) -> set[str]:
    """Unlock create_tool when the task needs a skill that is not installed."""
    if not query:
        return set()
    have = existing_skill_ids()
    try:
        from app.tools.registry import get_tool_registry

        have |= {t.name for t in get_tool_registry().list_tools()}
    except Exception:
        pass
    try:
        from app.tools.lookup import has_group
    except Exception:
        has_group = lambda _g: False  # noqa: E731
    for rx, group in _CAPABILITY_GAP_PATTERNS:
        if rx.search(query) and group not in have and not has_group(group):
            return {
                "create_tool",
                "read_skill",
                "list_skills",
                "validate_skill",
            }
    return set()


def auto_meta_tools_for_query(query: str) -> set[str]:
    """Unlock create+read when user mentions an existing skill and repair intent."""
    if not query:
        return set()
    unlocked = missing_capability_meta_tools(query)
    skills = mentioned_skill_ids(query)
    if skills and query_wants_skill_repair(query):
        unlocked |= {"create_tool", "read_skill", "list_skills", "validate_skill"}
    if skills and re.search(r"(技能|skill|工具)", query, re.I) and re.search(
        r"(看|读|查|源码|代码|实现|怎么写)", query
    ):
        unlocked |= {"read_skill", "list_skills"}
    return unlocked
