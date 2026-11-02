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



def _review_hint(status, valid_to=None, kind="item"):
    """Ground-truth review state for the agent: never claim review unless queued."""
    st = str(status or "active").strip().lower()
    if st in ("staging", "review_required", "conflicted"):
        return {"pending_review": True, "status": st,
                "say": f"该{kind}在待评审队列：用户可在「设定 → 评审」中批准/驳回。"}
    if st == "active" and valid_to:
        return {"pending_review": False, "status": st,
                "say": f"该{kind}是临时生效（至 {valid_to}），不在评审队列；不要叫用户去评审。"}
    if st == "active":
        return {"pending_review": False, "status": st,
                "say": f"该{kind}已正式生效（已通过评审或无需评审），评审页不会有它；不要再说需要评审/批准。"}
    return {"pending_review": False, "status": st, "say": f"该{kind}状态为 {st}，不在评审队列。"}

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


    _PERSONA_IDENTITY = ("name", "language", "background")
    _PERSONA_ROLEPLAY = (
        "roleplay_enabled", "roleplay_intensity", "roleplay_background",
        "relationship", "personality", "speech_patterns",
        "example_dialogue", "ooc_rules",
    )
    _PERSONA_EDITABLE = _PERSONA_IDENTITY + _PERSONA_ROLEPLAY

    async def update_persona(action: str = "get", **fields) -> str:
        """Read / update the agent's own persona (same path as 设定→人设 save)."""
        from app.config_store import get_config_store
        from app.agent.persona import persona_public_view

        store = get_config_store()
        act = (action or "get").strip().lower()
        if act == "get":
            cur = persona_public_view(store.get_agent())
            return json.dumps({"ok": True, "persona": {k: cur.get(k) for k in _PERSONA_EDITABLE}}, ensure_ascii=False)
        if act != "update":
            return json.dumps({"ok": False, "error": "action 只能是 get|update"}, ensure_ascii=False)

        scope = str(fields.pop("scope", None) or fields.pop("update_scope", None) or "auto").strip().lower()
        if scope not in ("auto", "identity", "roleplay", "all"):
            return json.dumps({"ok": False, "error": "scope 只能是 auto|identity|roleplay|all"}, ensure_ascii=False)

        rejected = [k for k in fields if k not in _PERSONA_EDITABLE]
        payload = {k: v for k, v in fields.items() if k in _PERSONA_EDITABLE and v is not None}
        # blank strings never clear identity by accident
        for k in list(payload):
            if k in _PERSONA_IDENTITY and isinstance(payload[k], str) and not payload[k].strip():
                payload.pop(k)

        has_rp = any(k in payload for k in _PERSONA_ROLEPLAY)
        has_id = any(k in payload for k in _PERSONA_IDENTITY)
        stripped_identity: list[str] = []
        # auto: 只要带了角色扮演字段，就丢掉同一次调用里的 name/language/background
        # （模型常会顺手重写背景；真要一起改须 scope=all）
        if scope == "roleplay" or (scope == "auto" and has_rp):
            for k in _PERSONA_IDENTITY:
                if k in payload:
                    payload.pop(k)
                    stripped_identity.append(k)
        elif scope == "identity":
            for k in _PERSONA_ROLEPLAY:
                payload.pop(k, None)

        if not payload:
            return json.dumps({
                "ok": False,
                "error": "没有可改字段",
                "allowed": list(_PERSONA_EDITABLE),
                "rejected": rejected,
                "stripped_identity": stripped_identity,
                "hint": "只改角色扮演时不要传 background；若名字和扮演一起改请 scope=all",
            }, ensure_ascii=False)

        if "roleplay_enabled" in payload and not isinstance(payload["roleplay_enabled"], bool):
            payload["roleplay_enabled"] = str(payload["roleplay_enabled"]).strip().lower() in ("1", "true", "yes", "on", "开", "开启")
        if "roleplay_intensity" in payload and payload["roleplay_intensity"] not in ("light", "medium", "deep"):
            return json.dumps({"ok": False, "error": "roleplay_intensity 只能是 light|medium|deep"}, ensure_ascii=False)
        for k, v in list(payload.items()):
            if k != "roleplay_enabled":
                payload[k] = str(v)[:8000]
        try:
            from app.api.config import AgentUpdate
            payload = AgentUpdate(**payload).model_dump(exclude_unset=True)
        except Exception as exc:
            return json.dumps({"ok": False, "error": f"字段校验失败: {exc}"}, ensure_ascii=False)
        # defense: never write keys we stripped
        for k in stripped_identity:
            payload.pop(k, None)
        # strip pasted 名字/语言/【角色背景】 wrappers from free-text backgrounds
        try:
            from app.agent.persona import sanitize_background_body
            for _bk in ("background", "roleplay_background"):
                if _bk in payload and isinstance(payload.get(_bk), str):
                    payload[_bk] = sanitize_background_body(payload[_bk])
        except Exception:
            pass
        store.update_section("agent", payload)
        try:
            from app.services.runtime import rebuild_runtime
            await rebuild_runtime(reconnect_mcp=False)
        except Exception as exc:
            return json.dumps({
                "ok": True,
                "updated": sorted(payload),
                "scope": scope,
                "stripped_identity": stripped_identity,
                "warning": f"已保存，运行时重建失败（下轮或重启生效）: {exc}",
            }, ensure_ascii=False)
        return json.dumps({
            "ok": True,
            "updated": sorted(payload),
            "rejected": rejected,
            "scope": scope,
            "stripped_identity": stripped_identity,
            "note": "已写入设定→人设，下一轮起生效；未列出的字段保持原值",
        }, ensure_ascii=False)

    async def system_info() -> str:
        try:
            from app.tools.protection import protection_summary

            prot = protection_summary()
        except Exception:
            prot = {}
        llm_provider = ""
        llm_model = ""
        try:
            from app.llm.client import get_llm_client

            llm = get_llm_client()
            llm_provider = llm.provider or ""
            llm_model = llm.model or ""
        except Exception:
            pass
        return json.dumps(
            {
                "agent": settings.agent_name,
                "python": sys.version,
                "platform": platform.platform(),
                "llm_provider": llm_provider,
                "llm_model": llm_model,
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
        confidence: float = 0.8,
        valid_to: str = "",
        ttl_days: float = 0,
        supersedes_id: str = "",
        include_archived: bool = False,
        status: str = "",
        from_type: str = "memory",
        from_id: str = "",
        to_type: str = "kb",
        to_id: str = "",
        edge_type: str = "references",
        reason: str = "",
        ref_id: str = "",
        soft: bool = True,
        reference_type: str = "user_explicit",
        resolution: str = "",
        scope: str = "",
        node_type: str = "",
        node_id: str = "",
    ) -> str:
        """Long-term memory: remember / recall / list / delete / refs.

        Persists to SQL (eva_memories) and appears in the UI Memory panel.
        Phase 2: control kinds (preference/constraint/goal/strategy) → standing;
        evidence/inferred → staging + TTL; long facts prefer kb + memory summary.
        Phase 3: link_ref / unlink_ref / list_refs / add_anchor for knowledge edges. Phase 4: skill_graph / sync_skill_refs for skill→kb declarations.
        Default recall/list hide expired/archived/superseded/conflicted/staging.
        """
        from app.memory.store import get_memory_store
        from app.memory.control_plane import (
            classify_memory_write,
            should_prefer_kb,
            short_summary,
        )

        store = get_memory_store()
        act = (action or "").strip().lower()
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        item_id = (memory_id or id or "").strip()

        if act in ("remember", "save", "add", "store"):
            text_body = (content or "").strip()
            if not text_body:
                return json.dumps(
                    {"ok": False, "error": "content is required for action=remember"},
                    ensure_ascii=False,
                )
            k = (kind or "preference").strip() or "preference"
            st_raw = (status or "").strip()
            ttl = float(ttl_days) if ttl_days else None
            meta = classify_memory_write(
                kind=k,
                tags=tag_list,
                content=text_body,
                status=st_raw or None,
                ttl_days=ttl,
                valid_to=(valid_to or "").strip() or None,
                confidence=float(confidence) if confidence is not None else None,
                explicit_status=bool(st_raw),
            )
            kb_page = None
            mem_content = text_body
            # Long factual/evidence → kb staging page + short memory pointer
            if meta.get("prefer_kb") and should_prefer_kb(meta["kind"], text_body):
                try:
                    from app.knowledge.store import get_knowledge_store

                    kb = get_knowledge_store()
                    await kb.ensure_seed()
                    title = short_summary(text_body, max_chars=60) or "候选知识"
                    page = await kb.create(
                        title=f"[staging] {title}",
                        content=text_body,
                        tags=list(meta["tags"]) + ["from_memory"],
                        collection="staging",
                        confidence=float(meta["confidence"]),
                        ttl_days=meta.get("ttl_days") or 7,
                        status="staging",
                        source="agent",
                    )
                    kb_page = {"id": page.get("id"), "title": page.get("title")}
                    mem_content = (
                        f"{short_summary(text_body)} "
                        f"【知识库 staging:{page.get('id')}】"
                    )
                    if "needs_kb" not in {t.lower() for t in meta["tags"]}:
                        meta["tags"] = list(meta["tags"]) + ["needs_kb"]
                    if "kb_ref" not in {t.lower() for t in meta["tags"]}:
                        meta["tags"] = list(meta["tags"]) + [f"kb_ref={page.get('id')}"]
                except Exception as exc:
                    # Fall back to summary-only memory; do not fail remember
                    mem_content = (
                        f"{short_summary(text_body)} 【长文宜入知识库；kb写入失败:{exc}】"
                    )

            sid = (supersedes_id or "").strip() or None
            if not sid and meta.get("plane") == "control":
                try:
                    from app.memory.control_plane import find_supersede_id

                    existing = await store.list_all(limit=200, include_archived=False)
                    rows = [
                        {
                            "id": i.id,
                            "content": i.content,
                            "kind": i.kind,
                            "tags": i.tags,
                            "status": i.status,
                        }
                        for i in existing
                    ]
                    sid = find_supersede_id(
                        rows,
                        kind=meta["kind"],
                        content=text_body,
                        tags=list(meta["tags"]),
                    )
                except Exception:
                    sid = None
            try:
                item = await store.add(
                    content=mem_content,
                    kind=meta["kind"],
                    tags=list(meta["tags"]),
                    confidence=float(meta["confidence"]),
                    valid_to=(valid_to or "").strip() or None,
                    ttl_days=meta.get("ttl_days"),
                    supersedes_id=sid,
                    status=meta["status"],
                    explicit_status=True,
                    apply_control_plane=False,  # already classified above
                    auto_supersede=False,
                    source="agent",
                )
            except ValueError as exc:
                msg = str(exc)
                if "blocked_hard_constraint" in msg:
                    return json.dumps(
                        {
                            "ok": False,
                            "action": "remember",
                            "error": "blocked_hard_constraint",
                            "message": msg,
                        },
                        ensure_ascii=False,
                    )
                raise
            out = {
                "ok": True,
                "action": "remember",
                "id": item.id,
                "content": item.content,
                "kind": item.kind,
                "tags": item.tags,
                "status": item.status,
                "confidence": item.confidence,
                "valid_to": item.valid_to,
                "plane": meta.get("plane"),
                "review": _review_hint(item.status, item.valid_to, "记忆"),
                "supersedes_id": item.supersedes_id,
                "message": (
                    "已写入长期记忆（控制面可 standing；事实/无TTL 进暂存，正式认定需人工评审）"
                    if item.status in ("staging", "review_required")
                    else "已写入长期记忆并直接生效（无需评审），记忆面板可查看"
                ),
            }
            if kb_page:
                out["kb_page"] = kb_page
                out["message"] = "长文已进知识库 staging，记忆保留摘要引用"
                # Ensure references edge even if tag parse missed
                try:
                    from app.knowledge.refs import attach_kb_ref_for_memory, attach_controls_edge
                    from app.memory.control_plane import is_control_kind

                    attach_kb_ref_for_memory(
                        memory_id=item.id, kb_id=str(kb_page["id"])
                    )
                    if is_control_kind(meta["kind"]):
                        attach_controls_edge(
                            memory_id=item.id,
                            target_type="kb",
                            target_id=str(kb_page["id"]),
                            reason="control→kb staging",
                        )
                except Exception:
                    pass
            if meta.get("notes"):
                out["notes"] = meta["notes"]
            return json.dumps(out, ensure_ascii=False)

        if act in ("recall", "search", "get"):
            q = (query or content or "").strip()
            lim = max(1, min(int(limit or 10), 50))
            if q:
                items = await store.search(
                    q, limit=lim, include_archived=bool(include_archived)
                )
            else:
                items = await store.list_all(
                    limit=lim, include_archived=bool(include_archived)
                )
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
                            "status": i.status,
                            "confidence": i.confidence,
                            "valid_to": i.valid_to,
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
            items = await store.list_all(
                limit=lim, include_archived=bool(include_archived)
            )
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
                            "status": i.status,
                            "confidence": i.confidence,
                            "valid_to": i.valid_to,
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

        if act in ("link_ref", "link", "attach_ref"):
            from app.knowledge.refs import get_ref_store

            ft = (from_type or "memory").strip() or "memory"
            fid = (from_id or item_id or "").strip()
            tt = (to_type or "kb").strip() or "kb"
            tid = (to_id or "").strip()
            if not fid or not tid:
                return json.dumps(
                    {
                        "ok": False,
                        "error": "from_id and to_id required for link_ref "
                        "(memory/skill/kb ids)",
                    },
                    ensure_ascii=False,
                )
            try:
                edge = await get_ref_store().link(
                    from_type=ft,
                    from_id=fid,
                    to_type=tt,
                    to_id=tid,
                    edge_type=(edge_type or "references").strip() or "references",
                    reason=(reason or "").strip() or None,
                    created_by="tool:memory",
                )
            except ValueError as exc:
                return json.dumps(
                    {"ok": False, "error": str(exc)}, ensure_ascii=False
                )
            return json.dumps(
                {"ok": True, "action": "link_ref", "ref": edge},
                ensure_ascii=False,
                default=str,
            )

        if act in ("unlink_ref", "unlink"):
            from app.knowledge.refs import get_ref_store

            try:
                result = await get_ref_store().unlink(
                    ref_id=(ref_id or "").strip() or None,
                    from_type=(from_type or "").strip() or None,
                    from_id=(from_id or item_id or "").strip() or None,
                    to_type=(to_type or "").strip() or None,
                    to_id=(to_id or "").strip() or None,
                    edge_type=(edge_type or "").strip() or None,
                    soft=bool(soft),
                )
            except ValueError as exc:
                return json.dumps(
                    {"ok": False, "error": str(exc)}, ensure_ascii=False
                )
            return json.dumps(
                {"ok": True, "action": "unlink_ref", **result},
                ensure_ascii=False,
                default=str,
            )

        if act in ("list_refs", "refs"):
            from app.knowledge.refs import get_ref_store

            nt = (node_type or from_type or "memory").strip() or "memory"
            nid = (node_id or from_id or item_id or "").strip()
            lim = max(1, min(int(limit or 50), 200))
            rows = await get_ref_store().list_refs(
                node_type=nt if nid else None,
                node_id=nid or None,
                edge_type=(edge_type or "").strip() or None,
                include_expired=bool(include_archived),
                limit=lim,
            )
            return json.dumps(
                {
                    "ok": True,
                    "action": "list_refs",
                    "node_type": nt if nid else None,
                    "node_id": nid or None,
                    "count": len(rows),
                    "refs": rows,
                },
                ensure_ascii=False,
                default=str,
            )

        if act in ("add_anchor", "anchor"):
            from app.knowledge.refs import get_ref_store

            res = (resolution or content or "").strip()
            if not res:
                return json.dumps(
                    {
                        "ok": False,
                        "error": "resolution/content required for add_anchor",
                    },
                    ensure_ascii=False,
                )
            try:
                row = await get_ref_store().add_anchor(
                    reference_type=(reference_type or "user_explicit").strip(),
                    resolution=res,
                    scope=(scope or query or "").strip() or None,
                    confidence=float(confidence) if confidence is not None else 0.9,
                    source="tool:memory",
                    subject_type=(from_type or "").strip() or None,
                    subject_id=(from_id or item_id or "").strip() or None,
                    ttl_days=float(ttl_days) if ttl_days else None,
                )
            except ValueError as exc:
                return json.dumps(
                    {"ok": False, "error": str(exc)}, ensure_ascii=False
                )
            return json.dumps(
                {"ok": True, "action": "add_anchor", "anchor": row},
                ensure_ascii=False,
                default=str,
            )

        if act in ("list_conflicts", "conflicts"):
            from app.knowledge.refs import get_ref_store

            lim = max(1, min(int(limit or 20), 100))
            rows = await get_ref_store().list_conflicts(limit=lim)
            return json.dumps(
                {
                    "ok": True,
                    "action": "list_conflicts",
                    "count": len(rows),
                    "conflicts": rows,
                },
                ensure_ascii=False,
                default=str,
            )

        if act in ("skill_graph", "list_skill_graph", "skill_refs"):
            from app.knowledge.skill_refs import list_skill_kb_graph

            sid = (from_id or node_id or query or "").strip() or None
            lim = max(1, min(int(limit or 100), 500))
            graph = await list_skill_kb_graph(skill_id=sid, limit=lim)
            return json.dumps(
                {"ok": True, "action": "skill_graph", **graph},
                ensure_ascii=False,
                default=str,
            )

        if act in ("sync_skill_refs", "sync_skill_knowledge_refs"):
            from app.knowledge.skill_refs import (
                sync_all_skill_knowledge_refs,
                sync_skill_knowledge_refs,
            )

            sid = (from_id or node_id or query or "").strip()
            if sid:
                result = await sync_skill_knowledge_refs(sid)
            else:
                result = await sync_all_skill_knowledge_refs()
            return json.dumps(
                {"ok": True, "action": "sync_skill_refs", **result},
                ensure_ascii=False,
                default=str,
            )

        return json.dumps(
            {
                "ok": False,
                "error": (
                    f"Unknown action: {action}. Use remember|recall|list|delete|"
                    "link_ref|unlink_ref|list_refs|add_anchor|list_conflicts|"
                    "skill_graph|sync_skill_refs"
                ),
            },
            ensure_ascii=False,
        )


    #  Register tool / s

    async def read_skill(name: str, stage: str = "auto", full: bool = False) -> str:
        """Read skill package from skills/ (live) and/or workspace/skills/ (draft).

        Use BEFORE create_tool(update=true). stage=live|draft|auto (prefer live, else draft).
        full=true 才返回完整 SKILL.md changelog（默认省略长历史以省 token）。
        """
        import json as _json

        from app.services.skill_lifecycle import read_skill_package

        prefer = "draft" if (stage or "").strip().lower() == "draft" else "live"
        result = read_skill_package(name, prefer=prefer, full=bool(full))
        if result.get("ok"):
            spec = {}
            primary = (result.get("stages") or {}).get(result.get("primary_stage") or "") or {}
            man = primary.get("manifest") if isinstance(primary.get("manifest"), dict) else {}
            meta = man.get("agentos_meta") if isinstance(man.get("agentos_meta"), dict) else {}
            if isinstance(meta.get("spec"), dict):
                spec = meta["spec"]
            spec.setdefault("integration_id", meta.get("integration_id") or "")
            spec.setdefault("llm_id", meta.get("llm_id") or spec.get("llm_id") or "")
            from app.services.credentials import list_llms_public
            from app.services.skill_spec import skill_integration_view

            result["integration"] = skill_integration_view(result.get("name") or name, spec)
            result["llm_id"] = spec.get("llm_id") or ""
            result["llms"] = list_llms_public()
            result["hint"] = (
                "对话模型看 llms（设定→LLM），用 llm_credentials(id)。"
                "业务连接看 integration（设定→集成；单一字段或 items 明细表），用 integration_config(id)。"
                "不要把 LLM key 写进集成或代码。"
            )
        return _json.dumps(result, ensure_ascii=False)

    async def list_skills_tool(include_draft: bool = True) -> str:
        """List live (skills/) and draft (workspace/skills/) skill package ids."""
        import json as _json

        from app.services.skill_lifecycle import list_skill_ids, skills_root, draft_skills_root
        from app.tools.protection import PROTECTED_SKILLS

        data = list_skill_ids(include_draft=bool(include_draft))
        from app.config_store import get_config_store
        from app.services.skill_spec import skill_integration_view
        from app.tools.tool_meta import meta_for

        disabled = {str(x) for x in (get_config_store().disabled_skills() or [])}
        live = [s for s in data["live"] if s not in disabled]
        items = []
        for sid in live:
            md = meta_for(sid) or {}
            items.append(
                {
                    "id": sid,
                    "stage": "live",
                    "group": str(md.get("group") or "other"),
                    "integration": skill_integration_view(sid),
                }
            )
        if include_draft:
            for sid in data["draft"]:
                md = meta_for(sid) or {}
                items.append(
                    {
                        "id": sid,
                        "stage": "draft",
                        "group": str(md.get("group") or "other"),
                        "integration": skill_integration_view(sid),
                    }
                )
        return _json.dumps(
            {
                "ok": True,
                "live": live,
                "draft": data["draft"],
                "disabled": sorted(disabled),
                "items": items,
                "live_root": str(skills_root()),
                "draft_root": str(draft_skills_root()),
                "protected": sorted(PROTECTED_SKILLS),
                "hint": (
                    "正式包在 skills/；disabled 里的技能本轮不可调用。"
                    "每条的 group 是设定→能力 的分类；改分类用 capability_groups。"
                    "每条的 integration 是设定→集成里的连接信息（密钥已打码）。"
                    "修改地址/密码请 integrations upsert 或让用户去设定→集成。"
                ),
            },
            ensure_ascii=False,
        )

    async def validate_skill_tool(
        name: str = "",
        handler_code: str = "",
        stage: str = "auto",
    ) -> str:
        """Validate skill handler syntax/structure without network calls."""
        import json as _json

        from app.services.skill_lifecycle import validate_skill_code

        st = (stage or "auto").strip().lower()
        if st == "auto":
            st = "any"
        result = validate_skill_code(
            name or "inline",
            handler_code or None,
            stage=st,
        )
        return _json.dumps(result, ensure_ascii=False)

    async def promote_skill_tool(name: str) -> str:
        """Promote workspace/skills/<id> draft → skills/<id> live and hot-reload."""
        import json as _json

        from app.tools.protection import (
            allow_create_tool as _allow_ct,
            create_tool_disabled_payload,
            is_tool_blocked,
        )

        if is_tool_blocked("promote_skill") or not _allow_ct():
            return _json.dumps(
                create_tool_disabled_payload("promote_skill"),
                ensure_ascii=False,
            )

        from app.services.skill_lifecycle import promote_skill_async

        result = await promote_skill_async(name)
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
                        "description": (t.description if isinstance(t.description, str) else str(t.description or ""))[:120],
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

        from app.services.skill_schema import (
            ensure_register_schema,
            strip_duplicate_scaffold_header,
        )

        code, strip_notes = strip_duplicate_scaffold_header(code)
        notes.extend(strip_notes)

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

        code, schema_notes = ensure_register_schema(code, params)
        notes.extend(schema_notes)
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
            # F02: only load handlers under skills / workspace/skills
            from app.services.skill_lifecycle import _assert_handler_under_skills

            _assert_handler_under_skills(hp)
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
        stage: str = "",
        promote: bool = False,
        spec_confirmed: bool = False,
        user_confirmation: str = "",
        spec_json: str = "",
        how_to_call: str = "",
        integration_id: str = "",
        integration_fields_json: str = "",
        llm_id: str = "",
        llm_fields_json: str = "",
    ) -> str:
        """Create/update a skill package.

        New skills default to live (callable this turn) after a confirmed spec.
        stage=draft only for explicitly risky sandboxes.
        """
        import json as _json
        import shutil
        import tempfile
        from datetime import datetime, timezone
        from pathlib import Path as _Path

        from app.tools.protection import (
            allow_create_tool as _allow_ct,
            create_tool_disabled_payload,
            is_tool_blocked,
        )

        if is_tool_blocked("create_tool") or not _allow_ct():
            return _json.dumps(
                create_tool_disabled_payload("create_tool"),
                ensure_ascii=False,
            )

        from app.services.skill_lifecycle import (
            draft_skill_dir,
            live_skill_dir,
            promote_skill_async,
            skills_root,
            validate_skill_code,
        )
        from app.services.skill_spec import (
            integration_status as _integ_status,
            connection_hacks_in_text,
            leaked_secrets_in_text,
            looks_like_llm_fields,
            looks_like_needs_integration,
            looks_like_needs_llm,
            fields_to_llm_payload,
            parse_spec_json,
            refuse_payload,
            resolve_skill_integration_id,
            skill_integration_view,
            spec_gaps,
            usage_card,
        )
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

        live_dir = live_skill_dir(safe_name)
        draft_dir = draft_skill_dir(safe_name)
        stage_n = (stage or "").strip().lower()
        if stage_n not in ("", "draft", "live", "auto"):
            stage_n = "auto"
        spec = parse_spec_json(spec_json)
        if how_to_call and not spec.get("trigger"):
            spec["trigger"] = how_to_call.strip()
        if (description or "").strip() and not spec.get("purpose"):
            spec["purpose"] = description.strip()[:400]
        gaps = spec_gaps(
            spec,
            description=description,
            how_to_call=how_to_call,
            spec_confirmed=bool(spec_confirmed),
            user_confirmation=user_confirmation,
            is_update=bool(update),
        )
        if gaps:
            return _json.dumps(
                refuse_payload(
                    name=safe_name,
                    spec=spec,
                    gaps=gaps,
                    is_update=bool(update),
                ),
                ensure_ascii=False,
            )

        integ_fields: dict[str, Any] = {}
        raw_fields = (integration_fields_json or "").strip()
        if raw_fields:
            try:
                parsed_f = _json.loads(raw_fields)
                if isinstance(parsed_f, dict):
                    integ_fields = parsed_f
                else:
                    return _json.dumps(
                        {"ok": False, "error": "integration_fields_json 必须是 JSON 对象"},
                        ensure_ascii=False,
                    )
            except _json.JSONDecodeError as exc:
                return _json.dumps(
                    {"ok": False, "error": f"integration_fields_json 无效: {exc}"},
                    ensure_ascii=False,
                )
        llm_fields: dict[str, Any] = {}
        raw_llm = (llm_fields_json or "").strip()
        if raw_llm:
            try:
                parsed_l = _json.loads(raw_llm)
                if isinstance(parsed_l, dict):
                    llm_fields = parsed_l
                else:
                    return _json.dumps(
                        {"ok": False, "error": "llm_fields_json 必须是 JSON 对象"},
                        ensure_ascii=False,
                    )
            except _json.JSONDecodeError as exc:
                return _json.dumps(
                    {"ok": False, "error": f"llm_fields_json 无效: {exc}"},
                    ensure_ascii=False,
                )
        # User often pastes OpenAI/DeepSeek keys into integration_fields — move them.
        if looks_like_llm_fields(integ_fields):
            llm_fields = {**integ_fields, **llm_fields}
            integ_fields = {}
        bound_llm = (llm_id or "").strip() or spec.get("llm_id") or ""
        if llm_fields:
            try:
                from app.config_store import get_config_store
                from app.services.runtime import rebuild_runtime

                payload = fields_to_llm_payload(llm_fields, llm_id=bound_llm)
                saved = get_config_store().upsert_llm(payload)
                bound_llm = str(saved.get("id") or bound_llm)
                spec["llm_id"] = bound_llm
                await rebuild_runtime(reconnect_mcp=False)
            except Exception as exc:
                return _json.dumps(
                    {
                        "ok": False,
                        "error": f"写入设定→LLM 失败: {exc}",
                        "action_required": "write_llm",
                        "hint": "对话模型的 base_url/api_key/model 用 llms action=upsert，不要写进 integrations。",
                    },
                    ensure_ascii=False,
                )
        elif looks_like_needs_llm(spec, description, handler_code):
            spec["llm_id"] = bound_llm
        integ_id = (
            (integration_id or "").strip()
            or spec.get("integration_id")
            or resolve_skill_integration_id(safe_name, spec)
        )
        secret_vals = [
            str(v).strip()
            for k, v in {**integ_fields, **llm_fields}.items()
            if str(v).strip()
            and any(s in str(k).lower() for s in ("pass", "token", "secret", "key"))
        ]
        leaks = leaked_secrets_in_text(
            f"{handler_code or ''}\n{description or ''}",
            secret_vals,
        )
        hacks = connection_hacks_in_text(handler_code or "")
        if hacks:
            return _json.dumps(
                {
                    "ok": False,
                    "error": "拒绝把 502/认证问题修成伪造 Host",
                    "action_required": "use_skill_http",
                    "gaps": hacks,
                    "hint": (
                        "局域网 NocoDB/qB/NAS 请 from app.services.skill_http import request，"
                        "用设定→集成的 base_url + 账号密码。"
                        "NocoDB 完整操作必须 email/password（PAT/nc_pat_ 不够）。"
                        "502 不要改 handler，更不要删除技能。"
                    ),
                },
                ensure_ascii=False,
            )
        if leaks:
            dest = "llms / llm_fields_json" if (llm_fields or looks_like_needs_llm(spec, description, handler_code)) else "integrations"
            return _json.dumps(
                {
                    "ok": False,
                    "error": "连接密钥不能写进技能代码",
                    "action_required": "write_llm" if dest.startswith("llms") else "write_integration",
                    "gaps": leaks,
                    "llm_id": bound_llm,
                    "integration_id": integ_id or safe_name,
                    "hint": (
                        "对话模型 key → 工具 llms action=upsert 或 llm_fields_json（设定→LLM）。"
                        "业务连接 → integration_fields_json 或 integrations upsert"
                        "（单一：url/账号/token；多记录：items 明细表）。"
                        "handler 用 llm_credentials() 或 integration_config(id)，禁止硬编码。"
                    ),
                },
                ensure_ascii=False,
            )
        needs_integ = bool(integ_fields) or looks_like_needs_integration(
            spec, description, handler_code
        )
        if needs_integ and not integ_id:
            integ_id = safe_name
        if integ_id and needs_integ:
            spec["integration_id"] = integ_id
            try:
                from app.config_store import get_config_store

                store = get_config_store()
                from app.services.integrations_meta import pack_custom_integration

                existing = store.get_integrations_raw().get(integ_id)
                payload = pack_custom_integration(
                    integ_id,
                    integ_fields,
                    name=str(integ_fields.get("_label") or safe_name),
                    skill_id=safe_name,
                    existing=existing if isinstance(existing, dict) else {},
                )
                store.upsert_integration(integ_id, payload)
            except Exception as exc:
                return _json.dumps(
                    {
                        "ok": False,
                        "error": f"写入集成失败: {exc}",
                        "action_required": "write_integration",
                        "integration_id": integ_id,
                    },
                    ensure_ascii=False,
                )

        if stage_n in ("", "auto"):
            # Confirmed create/update: live so the user can call it this session
            if update and draft_dir.is_dir() and not live_dir.is_dir():
                stage_n = "draft"
            else:
                stage_n = "live"
        is_draft = stage_n == "draft"
        skill_dir = draft_dir if is_draft else live_dir
        # For update checks: existence at target stage
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
        # Seed draft from live when editing production into sandbox
        if is_draft and update and not skill_dir.exists() and live_dir.is_dir():
            skill_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(live_dir), str(skill_dir), dirs_exist_ok=True)

        is_update = bool(update) and skill_dir.exists()
        # Creating a new live package while a live folder already exists
        if skill_dir.exists():
            if not update:
                return _json.dumps(
                    {
                        "error": (
                            f"Tool/skill [{safe_name}] already exists "
                            f"({'draft' if is_draft else 'live'}). "
                            "Set update=true to overwrite it."
                        ),
                        "hint": (
                            "先 read_skill(name=%s)，再 create_tool(name=%s, update=true, stage=%s)。"
                            "禁止新建 %s_v2 / %s_fixed 等等价 skill。"
                        )
                        % (
                            safe_name,
                            safe_name,
                            "draft" if is_draft else "live",
                            safe_name,
                            safe_name,
                        ),
                        "path": str(skill_dir),
                        "stage": "draft" if is_draft else "live",
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
            # New package: still block if live exists under same id (unless draft sandbox)
            if not is_draft and live_dir.is_dir() and not update:
                return _json.dumps(
                    {
                        "error": f"Live skill [{safe_name}] already exists.",
                        "hint": f"create_tool(name={safe_name}, update=true, stage=live) 或 stage=draft 先改草稿。",
                        "path": str(live_dir),
                    },
                    ensure_ascii=False,
                )
            ok_c, why = can_llm_create(safe_name)
            if not ok_c:
                return _json.dumps(
                    {"error": why, "protected": True},
                    ensure_ascii=False,
                )
            # Block accidental "equivalent" skills (*_fixed, *_v2, …)
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

        from app.services.skill_schema import resolve_skill_parameters, schema_from_handler_code

        old_params = None
        if is_update:
            old_hp = skill_dir / "handler.py"
            if old_hp.is_file():
                try:
                    old_params = schema_from_handler_code(
                        old_hp.read_text(encoding="utf-8", errors="replace")
                    )
                except Exception:
                    old_params = None
        params, schema_notes, schema_err = resolve_skill_parameters(
            params,
            spec=spec,
            handler_code=handler_code or "",
            old_params=old_params,
            no_params=bool(spec.get("no_params")),
        )
        if schema_err:
            return _json.dumps(
                {
                    "ok": False,
                    "error": schema_err,
                    "action_required": "fill_parameters",
                    "hint": (
                        "把 inputs 写进 spec_json，或传 parameters JSON schema，"
                        "或在 handler 里写 SCHEMA = {...}。"
                    ),
                    "notes": schema_notes,
                },
                ensure_ascii=False,
            )

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

        # Version: bump on update, start 0.1.0 on create
        prev_version = "0.1.0"
        prev_group = ""
        if is_update and skill_dir.joinpath("manifest.json").exists():
            try:
                prev_man = _json.loads(
                    skill_dir.joinpath("manifest.json").read_text(encoding="utf-8")
                )
                prev_version = str(prev_man.get("version") or "0.1.0")
                am_prev = prev_man.get("agentos_meta")
                if isinstance(am_prev, dict):
                    prev_group = str(am_prev.get("group") or "")
            except Exception:
                prev_version = "0.1.0"
                prev_group = ""
        raw_group = (group or "").strip()
        if raw_group:
            group_n = resolve_group(
                safe_name, raw_group, desc_final, kw_list, infer=False, create=True
            )
        elif is_update and prev_group:
            group_n = resolve_group(
                safe_name, prev_group, desc_final, kw_list, infer=False, create=False
            )
        else:
            group_n = "other"
        version_n = _bump_version(prev_version) if is_update else "0.1.0"
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        change_note = (changelog or "").strip() or (
            "update in-place" if is_update else "initial create"
        )

        skill_dir.mkdir(parents=True, exist_ok=True)

        scaffold_notes: list[str] = list(schema_notes)
        code_to_write = ""
        if has_handler:
            code_to_write, extra_notes = _normalize_handler_code(
                safe_name, desc_final, handler_code, params
            )
            scaffold_notes.extend(extra_notes)
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
                "spec": spec,
                "how_to_call": spec.get("trigger") or how_to_call.strip(),
                "integration_id": spec.get("integration_id") or integ_id or "",
                "llm_id": spec.get("llm_id") or bound_llm or "",
                "user_confirmation": (user_confirmation or "").strip()[:200],
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
            f"## Skill meta\n\n"
            f"- role: `{role_n}`\n"
            f"- tag: `{tag_n}`\n"
            f"- group: `{group_n}`\n"
            f"- scene_keywords: {', '.join(kw_list) if kw_list else '(none)'}\n\n"
            f"## Notes\n\n"
            f"- Call name: `{safe_name}`\n"
            f"- How to call: {spec.get('trigger') or how_to_call or safe_name}\n"
            f"- Soft filter (P2): include Chinese/English keywords, tool name, or 「全部工具」.\n"
            f"- Update in place: read_skill → create_tool(name={safe_name}, update=true).\n"
            f"- Do not create `{safe_name}_v2` / `{safe_name}_fixed` equivalents.\n"
        )
        skill_dir.joinpath("SKILL.md").write_text(skill_md, encoding="utf-8")

        # Validate handler before publish/reload
        v_stage = "draft" if is_draft else "live"
        validation = validate_skill_code(safe_name, stage=v_stage)
        if not validation.get("ok") and has_handler:
            if is_update and _backup_dir and _backup_dir.exists():
                shutil.rmtree(skill_dir, ignore_errors=True)
                shutil.copytree(str(_backup_dir), str(skill_dir))
            elif not is_update:
                shutil.rmtree(skill_dir, ignore_errors=True)
            return _json.dumps(
                {
                    "error": "validate_skill failed after write; rolled back",
                    "validate": validation,
                    "stage": v_stage,
                },
                ensure_ascii=False,
            )

        # Persist P0–P2 dynamic meta only for live packages
        meta_entry = None
        if not is_draft:
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

        promote_result = None
        if is_draft and promote:
            promote_result = await promote_skill_async(safe_name)
            if not promote_result.get("ok"):
                return _json.dumps(
                    {
                        "ok": False,
                        "error": "draft written but promote failed",
                        "path": str(skill_dir.resolve()),
                        "stage": "draft",
                        "validate": validation,
                        "promote": promote_result,
                    },
                    ensure_ascii=False,
                )
            if isinstance(promote_result, dict):
                promote_result.setdefault("knowledge_certified", False)
                promote_result.setdefault(
                    "hint_gate",
                    "promote 不同步认定知识；knowledge_refs 仅为引用边",
                )
            is_draft = False
            skill_dir = live_dir
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

        integ_id, integ_st = _integ_status(spec.get("integration_id") or "")
        ready_live = (not integ_id) or integ_st in ("ready",)

        if is_draft:
            card = usage_card(
                name=safe_name,
                spec=spec,
                ready=False,
                stage="draft",
                integration_id=integ_id,
                integration_status=integ_st,
            )
            return _json.dumps(
                {
                    "ok": True,
                    "tool_name": safe_name,
                    "type": "skill_draft",
                    "stage": "draft",
                    "ready": False,
                    "version": version_n,
                    "previous_version": prev_version if is_update else None,
                    "updated": is_update,
                    "changelog_entry": history[-1] if history else None,
                    "path": str(skill_dir.resolve()),
                    "live_path": str(live_dir.resolve()),
                    "validate": validation,
                    "loaded": False,
                    "spec": spec,
                    "integration": skill_integration_view(safe_name, spec),
                    "usage": card,
                    "tell_user": card["tell_user"],
                    "scaffold_notes": scaffold_notes,
                    "tips": [
                        f"草稿已写入 workspace/skills/{safe_name}/（对话里还不能调用）。",
                        f"确认无误后 create_tool(name={safe_name}, promote=true) 发布。",
                    ],
                },
                ensure_ascii=False,
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
                    "validate": validation,
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
                    "stage": "live",
                    "version": version_n,
                    "path": str(skill_dir.resolve()),
                    "meta": meta_entry,
                    "updated": is_update,
                    "validate": validation,
                    "promote": promote_result,
                    "scaffold_notes": scaffold_notes,
                    "tips": [
                        f"Prefer registry.register('{safe_name}', …).",
                        "Next fix: read_skill → create_tool(update=true) on THIS name.",
                    ],
                },
                ensure_ascii=False,
            )

        extra = [r["name"] for r in skill_registered if r["name"] != safe_name]
        integ_id, integ_st = _integ_status(spec.get("integration_id") or "")
        ready_live = (not integ_id) or integ_st in ("ready",)
        card = usage_card(
            name=safe_name,
            spec=spec,
            ready=ready_live,
            stage="live",
            integration_id=integ_id,
            integration_status=integ_st,
        )

        return _json.dumps(
            {
                "ok": True,
                "tool_name": safe_name,
                "registered_tools": skill_registered,
                "extra_tools": extra,
                "type": "skill",
                "stage": "live",
                "loaded": True,
                "ready": ready_live,
                "version": version_n,
                "previous_version": prev_version if is_update else None,
                "updated": is_update,
                "changelog_entry": history[-1] if history else None,
                "path": str(skill_dir.resolve()),
                "meta": meta_entry,
                "group": group_n,
                "description": desc_final[:300],
                "spec": spec,
                "integration": skill_integration_view(safe_name, spec),
                "usage": card,
                "tell_user": card["tell_user"],
                "validate": validation,
                "promote": promote_result,
                "scaffold_notes": scaffold_notes,
                "tips": [
                    card["tell_user"],
                    f"调用名: {safe_name}",
                    f"分类: {group_n}",
                    f"示例参数: {card.get('example_args') or '{}'}",
                    "以后修改：先向用户复述改动，再 create_tool(name=同一名字, update=true)。",
                ],
                "llm_id": spec.get("llm_id") or bound_llm or "",
                "config_hint": (
                    "对话模型：工具 llms（设定→LLM），handler 用 llm_credentials(llm_id)。"
                    "业务连接：工具 integrations（单一 url/token 或 items 明细表），handler 用 integration_config(id)。"
                ),
            },
            ensure_ascii=False,
        )

    async def manage_capability_groups(
        action: str,
        id: str = "",
        label: str = "",
        icon: str = "",
        name: str = "",
        group: str = "",
        confirm_id: str = "",
    ) -> str:
        """List / add / rename / delete / assign skill+tool capability groups."""
        import json as _json

        from app.tools.capability_groups import (
            add_group,
            delete_group,
            public_groups,
            rename_group,
            set_item_group,
        )

        act = (action or "list").strip().lower()
        if act in ("list", "ls"):
            groups = public_groups()
            return _json.dumps(
                {
                    "ok": True,
                    "action": "list",
                    "count": len(groups),
                    "groups": groups,
                    "hint": (
                        "这是设定→能力/工具函数 共用的分类。"
                        "create_tool 的 group 填这里的 id 或中文名；没有则新建。"
                        "省略 group 会放进「其它」，不会按关键词乱分。"
                        "把已有技能改分类用 action=assign，name=技能id，group=分类。"
                    ),
                },
                ensure_ascii=False,
            )
        if act == "add":
            try:
                entry = add_group(label or id, icon)
            except ValueError as e:
                return _json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
            return _json.dumps(
                {"ok": True, "action": "add", "group": entry},
                ensure_ascii=False,
            )
        if act == "rename":
            gid = (id or "").strip()
            try:
                entry = rename_group(gid, label or "", icon or None)
            except ValueError as e:
                return _json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
            return _json.dumps(
                {"ok": True, "action": "rename", "group": entry},
                ensure_ascii=False,
            )
        if act == "delete":
            gid = (id or "").strip()
            if (confirm_id or "").strip() != gid:
                return _json.dumps(
                    {
                        "ok": False,
                        "error": "删除分组需要 confirm_id 与 id 相同。组内技能会移到「其它」。",
                    },
                    ensure_ascii=False,
                )
            try:
                result = delete_group(gid, migrate="other")
            except ValueError as e:
                return _json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
            result["action"] = "delete"
            return _json.dumps(result, ensure_ascii=False)
        if act == "assign":
            sid = (name or id or "").strip()
            try:
                result = set_item_group(sid, group or label)
            except ValueError as e:
                return _json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
            result["action"] = "assign"
            return _json.dumps(result, ensure_ascii=False)
        return _json.dumps(
            {
                "ok": False,
                "error": f"unknown action {act}",
                "hint": "action=list|add|rename|delete|assign",
            },
            ensure_ascii=False,
        )

    async def manage_llms(
        action: str,
        id: str = "",
        fields_json: str = "",
    ) -> str:
        """List / get / upsert / delete 设定→LLM rows. Not integrations."""
        import json as _json

        act = (action or "list").strip().lower()
        lid = (id or "").strip()
        try:
            from app.config_store import get_config_store
            from app.services.credentials import list_llms_public, llm_credentials
            from app.services.skill_spec import fields_to_llm_payload

            store = get_config_store()
        except Exception as exc:
            return _json.dumps({"ok": False, "error": f"config store: {exc}"}, ensure_ascii=False)

        if act in ("list", "ls"):
            items = list_llms_public()
            default_id = next((x["id"] for x in items if x.get("is_default")), "")
            return _json.dumps(
                {
                    "ok": True,
                    "action": "list",
                    "count": len(items),
                    "default_id": default_id,
                    "items": items,
                    "hint": (
                        "这是设定→LLM 里已保存的对话模型（密钥已脱敏）。"
                        "技能要调模型请用 llm_credentials(id)，不要把 api_key 写入 integrations。"
                        "用户新给的供应商 key 用 action=upsert。"
                    ),
                },
                ensure_ascii=False,
            )

        if act in ("get", "show"):
            items = {x["id"]: x for x in list_llms_public()}
            by_name = {x.get("name"): x for x in items.values()}
            row = items.get(lid) or by_name.get(lid)
            if not row:
                return _json.dumps(
                    {"ok": False, "error": f"LLM [{lid}] 不存在", "hint": "先 llms action=list"},
                    ensure_ascii=False,
                )
            return _json.dumps({"ok": True, "action": "get", "item": row}, ensure_ascii=False)

        if act in ("upsert", "set", "update", "save", "put"):
            fields: dict[str, Any] = {}
            raw = (fields_json or "").strip()
            if raw:
                try:
                    parsed = _json.loads(raw)
                    if not isinstance(parsed, dict):
                        return _json.dumps(
                            {"ok": False, "error": "fields_json 必须是 JSON 对象"},
                            ensure_ascii=False,
                        )
                    fields = parsed
                except _json.JSONDecodeError as exc:
                    return _json.dumps(
                        {"ok": False, "error": f"fields_json 无效: {exc}"},
                        ensure_ascii=False,
                    )
            if not fields:
                return _json.dumps(
                    {
                        "ok": False,
                        "error": "fields_json 为空",
                        "hint": '例：{"name":"DeepSeek","provider":"deepseek","base_url":"https://api.deepseek.com/v1","api_key":"...","model":"deepseek-chat","is_default":true}',
                    },
                    ensure_ascii=False,
                )
            payload = fields_to_llm_payload(fields, llm_id=lid)
            saved = store.upsert_llm(payload)
            try:
                from app.services.runtime import rebuild_runtime

                await rebuild_runtime(reconnect_mcp=False)
            except Exception:
                pass
            pub = next(
                (x for x in list_llms_public() if x.get("id") == saved.get("id")),
                {"id": saved.get("id"), "name": saved.get("name")},
            )
            return _json.dumps(
                {
                    "ok": True,
                    "action": "upsert",
                    "item": pub,
                    "hint": "已写入设定→LLM。技能里用 llm_credentials(%r)。" % (saved.get("id") or ""),
                },
                ensure_ascii=False,
            )

        if act in ("default", "set_default"):
            if not lid:
                return _json.dumps({"ok": False, "error": "id required for set_default"}, ensure_ascii=False)
            if not store.set_default_llm(lid):
                return _json.dumps({"ok": False, "error": f"LLM [{lid}] 不存在"}, ensure_ascii=False)
            try:
                from app.services.runtime import rebuild_runtime

                await rebuild_runtime(reconnect_mcp=False)
            except Exception:
                pass
            return _json.dumps({"ok": True, "action": "set_default", "id": lid}, ensure_ascii=False)

        if act in ("delete", "remove"):
            if not lid:
                return _json.dumps({"ok": False, "error": "id required for delete"}, ensure_ascii=False)
            if not store.delete_llm(lid):
                return _json.dumps({"ok": False, "error": f"LLM [{lid}] 不存在"}, ensure_ascii=False)
            try:
                from app.services.runtime import rebuild_runtime

                await rebuild_runtime(reconnect_mcp=False)
            except Exception:
                pass
            return _json.dumps({"ok": True, "action": "delete", "id": lid}, ensure_ascii=False)

        if act in ("models", "pull", "remote"):
            from app.services.model_meta import _clean_api_key, fetch_openai_models

            creds = llm_credentials(lid)
            raw = (fields_json or "").strip()
            extra: dict[str, Any] = {}
            if raw:
                try:
                    parsed = _json.loads(raw)
                    extra = parsed if isinstance(parsed, dict) else {}
                except _json.JSONDecodeError:
                    extra = {}
            base = str(extra.get("base_url") or creds.get("base_url") or "").strip()
            key = _clean_api_key(str(extra.get("api_key") or creds.get("api_key") or ""))
            if not base or not key:
                return _json.dumps(
                    {
                        "ok": False,
                        "error": "缺少 base_url 或 api_key",
                        "hint": "先 llms action=upsert 保存模型，或在 fields_json 里带上。",
                    },
                    ensure_ascii=False,
                )
            result = await fetch_openai_models(base_url=base, api_key=key, use_proxy=False)
            result["source"] = "llm"
            return _json.dumps(result, ensure_ascii=False)

        return _json.dumps(
            {
                "ok": False,
                "error": f"unknown action {act}",
                "hint": "list|get|upsert|set_default|delete|models",
            },
            ensure_ascii=False,
        )

    async def manage_integrations(
        action: str,
        id: str = "",
        fields_json: str = "",
    ) -> str:
        """List / get / upsert / delete skill connection configs (设定→集成).

        Use this for URLs, usernames, passwords, tokens, and items tables — NOT kb, NOT skill code.
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
                            "hint": "Use list; builtin catalog is http, plus any custom ids. "
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
                            "hint": (
                                '单一：{"url":"...","token":"..."}；'
                                '内容式加 items：{"url":"...","items":{"bot1":{"name":"bot1","webhook":"https://..."}}}；'
                                'http：{"proxy_url":"..."}'
                            ),
                        },
                        ensure_ascii=False,
                    )
                from app.services.integrations_meta import pack_custom_integration

                existing = store.get_integrations_raw().get(iid)
                fields = pack_custom_integration(
                    iid,
                    fields,
                    existing=existing if isinstance(existing, dict) else {},
                )
                row = store.upsert_integration(iid, fields)
                return _json.dumps(
                    {
                        "ok": True,
                        "action": "upsert",
                        "id": iid,
                        "item": row,
                        "hint": "Skill code should read via integration_config(id). "
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
    async def delete_agent_tool(
        name: str,
        stage: str = "live",
        confirm_name: str = "",
        user_confirmation: str = "",
    ) -> str:
        """Delete a mutable skill by name (removes files and unregisters).

        stage=live|draft|both. Builtin / reserved / protected cannot be deleted.
        Requires confirm_name==name and a non-vague user_confirmation.
        """
        import json as _json
        import shutil

        from app.tools.protection import (
            allow_create_tool as _allow_ct,
            create_tool_disabled_payload,
            is_tool_blocked,
        )

        if is_tool_blocked("delete_tool") or not _allow_ct():
            return _json.dumps(
                create_tool_disabled_payload("delete_tool"),
                ensure_ascii=False,
            )

        from app.services.skill_lifecycle import draft_skill_dir, live_skill_dir
        from app.services.skill_spec import is_vague_confirmation
        from app.tools.protection import can_llm_delete, protection_reason
        from app.tools.registry import get_tool_registry
        from app.tools.tool_meta import remove_dynamic_meta

        safe_name = name.strip().lower().replace(" ", "_")
        if not safe_name or not safe_name.replace("_", "").isalnum():
            return _json.dumps(
                {"error": "Invalid tool name. Use letters, numbers, underscores only."},
                ensure_ascii=False,
            )
        confirm = (confirm_name or "").strip().lower().replace(" ", "_")
        if confirm != safe_name:
            return _json.dumps(
                {
                    "ok": False,
                    "error": "删除前必须向用户复述技能名，并传入 confirm_name=该名字",
                    "action_required": "confirm_delete",
                    "skill": safe_name,
                    "hint": (
                        f"先告诉用户将删除「{safe_name}」及其用途，"
                        "得到明确点名同意后，再 delete_tool"
                        f"(name={safe_name}, confirm_name={safe_name}, "
                        "user_confirmation=用户原话)。"
                    ),
                },
                ensure_ascii=False,
            )
        if is_vague_confirmation(user_confirmation):
            return _json.dumps(
                {
                    "ok": False,
                    "error": "用户确认太模糊，不能删除技能",
                    "action_required": "confirm_delete",
                    "skill": safe_name,
                    "hint": "需要用户明确说出要删的技能名或用途，仅「好/行/删吧」不够。",
                },
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

        st = (stage or "live").strip().lower()
        if st not in ("live", "draft", "both"):
            st = "live"
        deleted: list[str] = []
        live = live_skill_dir(safe_name)
        draft = draft_skill_dir(safe_name)

        if st in ("live", "both") and live.is_dir():
            shutil.rmtree(live, ignore_errors=True)
            deleted.append("live")
        if st in ("draft", "both") and draft.is_dir():
            shutil.rmtree(draft, ignore_errors=True)
            deleted.append("draft")

        if not deleted:
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
                {
                    "error": f"Tool/skill [{safe_name}] not found for stage={st}.",
                    "hint": "list_skills 查看 live/draft。",
                },
                ensure_ascii=False,
            )

        from app.services.skill_spec import skill_integration_view
        from app.services.integrations_meta import unlink_skill_from_integrations

        integ_view = skill_integration_view(safe_name)
        unlinked: list[str] = []
        if "live" in deleted:
            unlinked = unlink_skill_from_integrations(safe_name)

        if "live" in deleted:
            remove_dynamic_meta(safe_name)
            from app.services.runtime import rebuild_runtime

            await rebuild_runtime()

        return _json.dumps(
            {
                "ok": True,
                "deleted": safe_name,
                "stages_removed": deleted,
                "meta_removed": "live" in deleted,
                "integration": integ_view,
                "unlinked_integrations": unlinked,
                "tell_user": (
                    f"技能 {safe_name} 已删除。"
                    + (
                        f"对应集成「{integ_view.get('id')}」仍在设定→集成里（连接信息未删），"
                        "用户可继续改，或自行删除该集成。"
                        if integ_view.get("linked")
                        else (
                            f"已从集成 {', '.join(unlinked)} 解除绑定，连接配置仍保留。"
                            if unlinked
                            else "未绑定集成。"
                        )
                    )
                ),
            },
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
        confidence: float = 0.8,
        valid_to: str = "",
        ttl_days: float = 0,
        supersedes_id: str = "",
        include_archived: bool = False,
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
                rows = await store.list_pages(
                    collection=coll,
                    include_archived=bool(include_archived),
                    limit=max(1, min(limit, 100)),
                )
                return json.dumps({"ok": True, "action": "list", "count": len(rows), "pages": rows}, ensure_ascii=False)
            if act in ("list_collections", "collections"):
                cols = await store.list_collections()
                return json.dumps({"ok": True, "action": "list_collections", "collections": cols}, ensure_ascii=False)
            if act in ("search", "find"):
                q = (query or title or content or "").strip()
                if not q:
                    return json.dumps({"ok": False, "error": "query required for search"}, ensure_ascii=False)
                hits = await store.search(
                    q,
                    collection=coll,
                    limit=max(1, min(limit, 20)),
                    include_archived=bool(include_archived),
                )
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
                return json.dumps({"ok": True, "action": "get", "page": page, "review": _review_hint((page or {}).get("status"), (page or {}).get("valid_to"), "知识页")}, ensure_ascii=False, default=str)
            if act in ("create_page", "create", "add"):
                if not (title or "").strip():
                    return json.dumps({"ok": False, "error": "title required"}, ensure_ascii=False)
                ttl = float(ttl_days) if ttl_days else None
                coll_use = coll or "default"
                st_use = "active"
                # Staging / candidate collections → status=staging + default TTL
                if coll_use.lower() in ("staging", "temp", "draft", "candidate", "daily"):
                    st_use = "staging"
                    if not (ttl and ttl > 0) and not (valid_to or "").strip():
                        ttl = 7.0
                page = await store.create(
                    title=title.strip(),
                    content=content or "",
                    tags=tag_list,
                    collection=coll_use,
                    pinned=bool(pinned),
                    confidence=float(confidence) if confidence is not None else None,
                    valid_to=(valid_to or "").strip() or None,
                    ttl_days=ttl if ttl and ttl > 0 else None,
                    supersedes_id=(supersedes_id or "").strip() or None,
                    status=st_use,
                    source="agent",
                )
                return json.dumps({"ok": True, "action": "create_page", "page": page, "review": _review_hint((page or {}).get("status"), (page or {}).get("valid_to"), "知识页")}, ensure_ascii=False, default=str)
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
                    source="agent",
                )
                if not page:
                    return json.dumps({"ok": False, "error": "page not found"}, ensure_ascii=False)
                return json.dumps({"ok": True, "action": "update_page", "page": page, "review": _review_hint((page or {}).get("status"), (page or {}).get("valid_to"), "知识页")}, ensure_ascii=False, default=str)
            if act in ("append",):
                pid = (page_id or "").strip()
                if not pid and title:
                    existing = await store.get_by_title_or_slug(title)
                    pid = (existing or {}).get("id") or ""
                body = (text or content or "").strip()
                if not pid or not body:
                    return json.dumps({"ok": False, "error": "page_id and text/content required"}, ensure_ascii=False)
                page = await store.append(
                    pid, body, heading=heading, changelog=changelog or "append", source="agent"
                )
                if not page:
                    return json.dumps({"ok": False, "error": "page not found"}, ensure_ascii=False)
                return json.dumps({"ok": True, "action": "append", "page": page, "review": _review_hint((page or {}).get("status"), (page or {}).get("valid_to"), "知识页")}, ensure_ascii=False, default=str)
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
        schedule_json: str = "",
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

        def _parse_schedule() -> dict[str, Any] | None:
            if not (schedule_json or "").strip():
                return None
            raw = _parse_json(schedule_json, None)
            if raw is None:
                return None
            if not isinstance(raw, dict):
                raise ValueError("schedule_json 必须是对象")
            return raw

        async def _apply_schedule(data: dict[str, Any], sched: dict[str, Any] | None) -> dict[str, Any]:
            if sched is None:
                return data
            from app.scheduler.link import sync_workflow_schedule

            out = await sync_workflow_schedule(data, sched)
            data["schedule"] = out
            return await store.save_definition(
                name=str(data.get("name") or ""),
                description=str(data.get("description") or ""),
                steps=list(data.get("steps") or []),
                inputs=dict(data.get("inputs") or {}),
                enabled=bool(data.get("enabled", True)),
                wf_id=str(data.get("id") or ""),
                schedule=out,
            )

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
                    data = await _apply_schedule(data, _parse_schedule())
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
                    data = await _apply_schedule(data, _parse_schedule())
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
                data = await _apply_schedule(data, _parse_schedule())
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
                before = await store.get_definition(wid)
                result = await store.delete_definition(wid, delete_runs=True)
                result["action"] = "delete"
                if result.get("ok") and before:
                    from app.scheduler.link import unsync_workflow_schedule

                    try:
                        await unsync_workflow_schedule(str(before.get("id") or wid))
                    except Exception:
                        pass
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

    async def scheduled_task_tool(
        action: str,
        task_id: str = "",
        name: str = "",
        prompt: str = "",
        cron: str = "",
        interval_minutes: int = 0,
        interval_seconds: int = 0,
        run_once: bool = False,
        enabled: bool = True,
        session_id: str = "",
        always_new_session: bool = False,
        workflow_id: str = "",
        workflow_name: str = "",
    ) -> str:
        """Create / list / update scheduled tasks (设定→定时任务)."""
        from app.models.schemas import TaskCreate, TaskUpdate
        from app.scheduler.manager import get_scheduler
        from app.workflow.store import get_workflow_store

        sch = get_scheduler()
        act = (action or "").strip().lower()

        def _info(t) -> dict[str, Any]:
            meta = dict(getattr(t, "metadata", None) or {})
            return {
                "id": t.id,
                "name": t.name,
                "prompt": t.prompt,
                "cron": t.cron,
                "interval_seconds": t.interval_seconds,
                "run_once": t.run_once,
                "enabled": t.enabled,
                "status": t.status.value if hasattr(t.status, "value") else t.status,
                "session_id": t.session_id,
                "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
                "last_error": t.last_error,
                "workflow_id": meta.get("workflow_id") or "",
            }

        try:
            if act in ("list", "list_tasks"):
                items = await sch.list_tasks()
                return json.dumps(
                    {"ok": True, "action": "list", "count": len(items), "tasks": [_info(t) for t in items]},
                    ensure_ascii=False,
                )
            if act in ("get", "read"):
                tid = (task_id or name or "").strip()
                if not tid:
                    return json.dumps({"ok": False, "error": "task_id 或 name 必填"}, ensure_ascii=False)
                hit = await sch.get(tid)
                if not hit:
                    for t in await sch.list_tasks():
                        if t.name == tid or t.id == tid:
                            hit = t
                            break
                if not hit:
                    return json.dumps({"ok": False, "error": f"not found: {tid}"}, ensure_ascii=False)
                return json.dumps({"ok": True, "action": "get", "task": _info(hit)}, ensure_ascii=False)
            if act in ("create", "add", "schedule"):
                wid = (workflow_id or "").strip()
                wname = (workflow_name or "").strip()
                if wname and not wid:
                    wf = await get_workflow_store().get_definition(wname)
                    if not wf:
                        return json.dumps(
                            {"ok": False, "error": f"工作流不存在: {wname}。先 workflow action=list 确认名称。"},
                            ensure_ascii=False,
                        )
                    wid = str(wf.get("id") or "")
                    wname = str(wf.get("name") or wname)
                elif wid:
                    wf = await get_workflow_store().get_definition(wid)
                    if not wf:
                        return json.dumps(
                            {"ok": False, "error": f"工作流不存在: {wid}"},
                            ensure_ascii=False,
                        )
                    wname = wname or str(wf.get("name") or wid)
                secs = int(interval_seconds or 0)
                if not secs and int(interval_minutes or 0) > 0:
                    secs = int(interval_minutes) * 60
                cron_s = (cron or "").strip() or None
                once = bool(run_once)
                if not once and not cron_s and not secs:
                    return json.dumps(
                        {
                            "ok": False,
                            "error": "请提供 cron、interval_minutes 或 run_once=true",
                            "hint": "每天 9 点本地可先用 cron；每隔 N 分钟用 interval_minutes",
                        },
                        ensure_ascii=False,
                    )
                meta: dict[str, Any] = {}
                if always_new_session:
                    meta["always_new_session"] = True
                if wid:
                    meta["kind"] = "workflow"
                    meta["workflow_id"] = wid
                    nm = (name or "").strip() or f"工作流 · {wname or wid}"
                    pr = (prompt or "").strip() or f"运行已保存的工作流「{wname or wid}」（id={wid}）。"
                    existing = sch.find_by_workflow(wid)
                    if existing:
                        info = await sch.update(
                            str(existing["id"]),
                            TaskUpdate(
                                name=nm,
                                prompt=pr,
                                cron=cron_s,
                                interval_seconds=secs or None,
                                run_once=once,
                                enabled=bool(enabled),
                                session_id=(session_id or "").strip() or None,
                                metadata=meta,
                            ),
                        )
                        if wid:
                            store = get_workflow_store()
                            wf_def = await store.get_definition(wid)
                            if wf_def and info:
                                mode = "once" if once else ("interval" if secs else "cron")
                                wf_def["schedule"] = {
                                    "mode": mode,
                                    "enabled": bool(enabled),
                                    "cron": cron_s,
                                    "interval_seconds": secs or None,
                                    "run_once": once,
                                    "task_id": info.id,
                                }
                                await store.save_definition(
                                    name=str(wf_def.get("name") or wid),
                                    description=str(wf_def.get("description") or ""),
                                    steps=list(wf_def.get("steps") or []),
                                    inputs=dict(wf_def.get("inputs") or {}),
                                    enabled=bool(wf_def.get("enabled", True)),
                                    wf_id=wid,
                                    schedule=wf_def["schedule"],
                                )
                        return json.dumps(
                            {"ok": True, "action": "update", "task": _info(info), "note": "已更新该工作流的定时"},
                            ensure_ascii=False,
                        )
                else:
                    nm = (name or "").strip()
                    pr = (prompt or "").strip()
                    if not nm or not pr:
                        return json.dumps(
                            {"ok": False, "error": "create 需要 name + prompt，或提供 workflow_id/workflow_name"},
                            ensure_ascii=False,
                        )
                info = await sch.create(
                    TaskCreate(
                        name=nm,
                        prompt=pr,
                        cron=cron_s,
                        interval_seconds=secs or None,
                        run_once=once,
                        enabled=bool(enabled),
                        session_id=(session_id or "").strip() or None,
                        metadata=meta,
                    )
                )
                if wid:
                    store = get_workflow_store()
                    wf_def = await store.get_definition(wid)
                    if wf_def:
                        mode = "once" if once else ("interval" if secs else "cron")
                        wf_def["schedule"] = {
                            "mode": mode,
                            "enabled": bool(enabled),
                            "cron": cron_s,
                            "interval_seconds": secs or None,
                            "run_once": once,
                            "task_id": info.id,
                        }
                        await store.save_definition(
                            name=str(wf_def.get("name") or wid),
                            description=str(wf_def.get("description") or ""),
                            steps=list(wf_def.get("steps") or []),
                            inputs=dict(wf_def.get("inputs") or {}),
                            enabled=bool(wf_def.get("enabled", True)),
                            wf_id=wid,
                            schedule=wf_def["schedule"],
                        )
                return json.dumps({"ok": True, "action": "create", "task": _info(info)}, ensure_ascii=False)
            if act in ("update",):
                tid = (task_id or "").strip()
                if not tid:
                    return json.dumps({"ok": False, "error": "update 需要 task_id"}, ensure_ascii=False)
                cur = await sch.get(tid)
                if not cur:
                    return json.dumps({"ok": False, "error": f"not found: {tid}"}, ensure_ascii=False)
                secs = int(interval_seconds or 0)
                if not secs and int(interval_minutes or 0) > 0:
                    secs = int(interval_minutes) * 60
                cron_s = (cron or "").strip() or cur.cron
                once = bool(run_once) if run_once else cur.run_once
                interval = secs or cur.interval_seconds
                meta = dict(cur.metadata or {})
                if always_new_session:
                    meta["always_new_session"] = True
                info = await sch.update(
                    tid,
                    TaskUpdate(
                        name=(name or "").strip() or cur.name,
                        prompt=(prompt or "").strip() or cur.prompt,
                        cron=cron_s,
                        interval_seconds=interval,
                        run_once=once,
                        enabled=bool(enabled),
                        session_id=(session_id or "").strip() or cur.session_id,
                        metadata=meta,
                    ),
                )
                return json.dumps({"ok": True, "action": "update", "task": _info(info)}, ensure_ascii=False)
            if act in ("delete", "remove", "unschedule"):
                tid = (task_id or name or "").strip()
                if not tid:
                    return json.dumps({"ok": False, "error": "task_id 或 name 必填"}, ensure_ascii=False)
                hit = await sch.get(tid)
                if not hit:
                    for t in await sch.list_tasks():
                        if t.name == tid:
                            hit = t
                            break
                if not hit:
                    return json.dumps({"ok": False, "error": f"not found: {tid}"}, ensure_ascii=False)
                await sch.delete(hit.id)
                wid = str((hit.metadata or {}).get("workflow_id") or "")
                if wid:
                    store = get_workflow_store()
                    wf_def = await store.get_definition(wid)
                    if wf_def:
                        await store.save_definition(
                            name=str(wf_def.get("name") or wid),
                            description=str(wf_def.get("description") or ""),
                            steps=list(wf_def.get("steps") or []),
                            inputs=dict(wf_def.get("inputs") or {}),
                            enabled=bool(wf_def.get("enabled", True)),
                            wf_id=wid,
                            schedule={"mode": "off", "enabled": False, "task_id": ""},
                        )
                return json.dumps({"ok": True, "action": "delete", "id": hit.id}, ensure_ascii=False)
            if act in ("run", "run_now"):
                tid = (task_id or "").strip()
                if not tid:
                    return json.dumps({"ok": False, "error": "task_id required"}, ensure_ascii=False)
                info = await sch.run_now(tid)
                if not info:
                    return json.dumps({"ok": False, "error": f"not found: {tid}"}, ensure_ascii=False)
                return json.dumps({"ok": True, "action": "run", "task": _info(info)}, ensure_ascii=False)
            return json.dumps(
                {
                    "ok": False,
                    "error": f"Unknown action: {action}",
                    "hint": "list|get|create|update|delete|run；绑工作流时传 workflow_id 或 workflow_name",
                },
                ensure_ascii=False,
            )
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    async def ask_user(
        title: str = "",
        prompt: str = "",
        options: str = "",
        multi: str = "",
        fields: str = "",
        spec: str = "",
    ) -> str:
        """Pause this turn and show a form under the bubble."""
        from app.agent.ask_form import build_form

        form = build_form(
            title=title,
            prompt=prompt,
            options=options,
            multi=multi,
            fields=fields,
            spec=spec,
        )
        if not form:
            return json.dumps(
                {
                    "ok": False,
                    "error": "需要 options（单选）/ multi（多选）/ fields（输入）或 spec",
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {"ok": True, "action": "ask_user", "wait": True, "form": form},
            ensure_ascii=False,
        )

    tools: list[tuple[str, str, Any, dict[str, Any]]] = [
     (
         "get_current_time",
            "Get the current UTC/local time.",
            get_current_time,
            {"type": "object", "properties": {}},
        ),
        (
            "ask_user",
            "需要用户补充或选择时调用，然后停止本轮。"
            "options=单选（每行一项）；multi=多选（每行一项）；fields=输入框标题（每行一项）。"
            "也可写 spec，每行一种控件，例：单选 付款：到付 / 现结\\n多选 需要：入库 / 查物流\\n输入 单号。"
            "不要用正文 A/B 长题代替本工具。",
            ask_user,
            {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "短标题，如「还差这几项」",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "一两句说明为什么要问",
                    },
                    "options": {
                        "type": "string",
                        "description": "单选，每行一个。例：到付\\n现结",
                    },
                    "multi": {
                        "type": "string",
                        "description": "多选，每行一个。例：入库\\n查物流\\n开单",
                    },
                    "fields": {
                        "type": "string",
                        "description": "输入框标题，每行一个。例：快递单号\\n备注",
                    },
                    "spec": {
                        "type": "string",
                        "description": (
                            "混合表单，每行一个控件。"
                            "例：单选 付款：到付 / 现结\\n多选 附件：发票 / 照片\\n输入 单号"
                        ),
                    },
                },
                "required": [],
            },
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
            "update_persona",
            "读/改助手【自己的】人设（等价设定→人设保存）。"
            "基础背景(background)只在扮演关闭时生效；扮演背景(roleplay_background)只在扮演开启时生效，二者独立。"
            "【重要】改扮演背景用 roleplay_background，改基础背景用 background；只改角色扮演时不要传 background/name/language；"
            "scope 默认 auto：一旦带角色扮演字段，会自动忽略同次调用里的背景/名字/语言，防止误改。"
            "只改名字/语言/背景用 scope=identity；两边一起改才用 scope=all。"
            "「你叫我Y」→ memory。不能改模型/密钥/端口。",
            update_persona,
            {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["get", "update"], "description": "get 读取；update 写入"},
                    "scope": {"type": "string", "enum": ["auto", "identity", "roleplay", "all"], "description": "auto默认：有角色扮演字段则忽略 name/language/background；identity只改身份；roleplay只改扮演；all允许同次改两边"},
                    "name": {"type": "string", "description": "显示名称"},
                    "language": {"type": "string", "description": "回复语言，如 中文 / English"},
                    "background": {"type": "string", "description": "基础角色背景（仅扮演关闭时注入）；改扮演背景请用 roleplay_background"},
                    "roleplay_background": {"type": "string", "description": "扮演用角色背景（仅扮演开启时注入，替代基础背景）"},
                    "roleplay_enabled": {"type": "boolean", "description": "是否开启角色扮演"},
                    "roleplay_intensity": {"type": "string", "enum": ["light", "medium", "deep"], "description": "扮演强度"},
                    "relationship": {"type": "string", "description": "与用户的关系"},
                    "personality": {"type": "string", "description": "性格"},
                    "speech_patterns": {"type": "string", "description": "说话方式/口癖"},
                    "example_dialogue": {"type": "string", "description": "示例对话"},
                    "ooc_rules": {"type": "string", "description": "出戏规则"},
                },
                "required": ["action"],
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
            "注入是「匹配检索」而非全量：相关条目才会进 prompt。"
            "控制面 kind=preference|constraint|goal|strategy|habit|rule → standing，自动 supersede 同主题旧条；"
            "证据/推断 kind=evidence|inferred|observation|staging → status=staging，默认 TTL 7 天，不进 standing 注入；"
            "无 TTL 的 fact/note → staging（不可自称金叶/正式）；长事实写 kb staging + 记忆摘要；正式认定须人工评审。"
            "是否待评审只看返回的 status / review.pending_review：仅 staging/review_required 会出现在「设定→评审」；active（含 preference/constraint 控制面）已直接生效，不要告诉用户去评审。"
            "Phase3：link_ref/unlink_ref/list_refs；add_anchor；list_conflicts。Phase4：skill_graph 看技能→知识边；sync_skill_refs 只同步引用边、不自动认定知识。"
            "标签 kb_ref=ID 或 controls=kb:ID 在 remember 时自动建边。"
            "回忆用 action=recall；list；delete。用户说记住时必须调用 remember；但「你叫X/改助手名字或人设」用 update_persona，不要 memory（写暂存/绿叶，非自由金叶）。",
            memory_tool,
            {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "remember",
                            "recall",
                            "list",
                            "delete",
                            "link_ref",
                            "unlink_ref",
                            "list_refs",
                            "add_anchor",
                            "list_conflicts",
                            "skill_graph",
                            "sync_skill_refs",
                        ],
                        "description": "remember/recall/list/delete；Phase3 refs；Phase4: skill_graph|sync_skill_refs",
                    },
                    "content": {
                        "type": "string",
                        "description": "要保存的完整内容（action=remember 必填）；也可作 recall 的查询词",
                    },
                    "kind": {
                        "type": "string",
                        "description": "记忆类型：preference|constraint|goal|strategy|habit|rule（控制面）或 evidence|inferred|fact|note（证据/事实），默认 preference",
                        "default": "preference",
                    },
                    "status": {
                        "type": "string",
                        "description": "可选 active|staging；通常由 kind 自动决定。Agent 不可写 gold/certified；无TTL事实强制 staging，正式认定走评审。",
                        "default": "",
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
                    "confidence": {
                        "type": "number",
                        "description": "置信度 0~1，默认 0.8（临时事实可更低）",
                        "default": 0.8,
                    },
                    "valid_to": {
                        "type": "string",
                        "description": "可选到期时间 ISO8601；到期后默认 recall 不可见",
                    },
                    "ttl_days": {
                        "type": "number",
                        "description": "可选存活天数（绿叶临时事实）；与 valid_to 二选一",
                        "default": 0,
                    },
                    "supersedes_id": {
                        "type": "string",
                        "description": "可选：取代的旧记忆 id（旧条目标为 superseded）",
                    },
                    "include_archived": {
                        "type": "boolean",
                        "description": "recall/list 是否包含过期/归档/被取代等非 active；list_refs 是否含 expired",
                        "default": False,
                    },
                    "from_type": {
                        "type": "string",
                        "description": "link_ref 起点类型 memory|kb|skill|reference",
                        "default": "memory",
                    },
                    "from_id": {
                        "type": "string",
                        "description": "link_ref / list_refs 起点 id（技能名或记忆/kb id）",
                    },
                    "to_type": {
                        "type": "string",
                        "description": "link_ref 终点类型",
                        "default": "kb",
                    },
                    "to_id": {
                        "type": "string",
                        "description": "link_ref 终点 id",
                    },
                    "edge_type": {
                        "type": "string",
                        "description": "references|controls|supersedes|contradicts",
                        "default": "references",
                    },
                    "reason": {
                        "type": "string",
                        "description": "建边原因（可选）",
                    },
                    "ref_id": {
                        "type": "string",
                        "description": "unlink_ref 时的边 id",
                    },
                    "soft": {
                        "type": "boolean",
                        "description": "unlink_ref 软删除（status=expired），默认 true",
                        "default": True,
                    },
                    "node_type": {
                        "type": "string",
                        "description": "list_refs 节点类型（可替代 from_type）",
                    },
                    "node_id": {
                        "type": "string",
                        "description": "list_refs 节点 id（可替代 from_id）",
                    },
                    "reference_type": {
                        "type": "string",
                        "description": "add_anchor: user_explicit|authority|precedent|evidence|hierarchy",
                        "default": "user_explicit",
                    },
                    "resolution": {
                        "type": "string",
                        "description": "add_anchor 仲裁结论文本",
                    },
                    "scope": {
                        "type": "string",
                        "description": "add_anchor 作用域/主题关键词",
                    },
                },
                "required": ["action"],
            },
        ),
        (
            "kb",
            "【主推·知识库 Wiki】业务标准与长文档（与 memory 短偏好不同）。"
            "action=search|get|list|create_page|update_page|append|delete|list_collections。"
            "collection 分区：sop=流程标准、product=产品参数、"
            "handbook=手册、reference=模板、daily=纪要、staging=候选（默认 TTL）、default=未分类。"
            "Agent create 默认进暂存/绿叶，不可直接写金叶；正式认定须人工评审批准。"
            "是否待评审只以工具返回的 page.status / review.pending_review 为准：staging/review_required 才在「设定→评审」队列；status=active 表示已正式（可能用户已在评审页批准），禁止再说要评审/批准，也不要依据页面正文里自己写的『状态』说明。"
            "空库就说空，禁止编造不存在的 SOP 标题或阶段步骤。"
            "只有 kb list/search 真正命中的页面才能当流程依据。"
            "短偏好/「记住」仍用 memory。create_page 需 title+content；"
            "update/append 需 page_id 或已有 title。prefer link_ref；skill promote 不自动认定知识。",
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
                        "description": "页面标题（get/search 可用标题；必须是库里已有的标题）",
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
                    "confidence": {
                        "type": "number",
                        "description": "置信度 0~1，默认 0.8",
                        "default": 0.8,
                    },
                    "valid_to": {
                        "type": "string",
                        "description": "可选到期 ISO8601；到期后默认 search/list 不可见",
                    },
                    "ttl_days": {
                        "type": "number",
                        "description": "可选存活天数（临时页）；与 valid_to 二选一",
                        "default": 0,
                    },
                    "supersedes_id": {
                        "type": "string",
                        "description": "可选：取代的旧页面 id",
                    },
                    "include_archived": {
                        "type": "boolean",
                        "description": "list/search 是否包含归档/过期/被取代等",
                        "default": False,
                    },
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
            "定时：create/update 可带 schedule_json，或另调 scheduled_task（workflow_id）。"
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
                    "schedule_json": {
                        "type": "string",
                        "description": (
                            "可选定时 JSON。"
                            '例 {"mode":"interval","interval_seconds":3600} '
                            '或 {"mode":"daily"} 请改用 scheduled_task + cron；'
                            '{"mode":"cron","cron":"0 1 * * *"}；{"mode":"off"} 取消定时。'
                        ),
                    },
                },
                "required": ["action"],
            },
        ),
        (
            "scheduled_task",
            "【主推·定时任务】设定→定时任务的唯一入口。"
            "action=list|get|create|update|delete|run。"
            "create 必须给 cron（分 时 日 月 周，UTC）或 interval_minutes 或 run_once=true。"
            "要把已有工作流定时跑：传 workflow_id 或 workflow_name，不要说系统没有 cron。"
            "普通提醒则 name+prompt。delete 取消定时。",
            scheduled_task_tool,
            {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "get", "create", "update", "delete", "run"],
                        "description": "create=新建/绑定工作流定时；delete=取消",
                    },
                    "task_id": {"type": "string", "description": "get/update/delete/run 用"},
                    "name": {"type": "string", "description": "任务名；绑工作流时可省略"},
                    "prompt": {
                        "type": "string",
                        "description": "到点让 Agent 做的事；绑工作流时可省略",
                    },
                    "cron": {
                        "type": "string",
                        "description": "5 段 cron（UTC），例 0 1 * * * = 每天 01:00 UTC",
                    },
                    "interval_minutes": {
                        "type": "integer",
                        "description": "每隔多少分钟（与 cron 二选一）",
                    },
                    "interval_seconds": {"type": "integer", "description": "间隔秒，优先于 minutes"},
                    "run_once": {"type": "boolean", "description": "只跑一次"},
                    "enabled": {"type": "boolean", "default": True},
                    "session_id": {
                        "type": "string",
                        "description": "结果写入的对话 id（界面用下拉选标题，不必手填）",
                    },
                    "always_new_session": {"type": "boolean"},
                    "workflow_id": {"type": "string", "description": "绑定已有工作流 id"},
                    "workflow_name": {"type": "string", "description": "绑定已有工作流中文名"},
                },
                "required": ["action"],
            },
        ),
        (
            "integrations",
            "【主推·集成配置】设定→集成：业务连接（天气、短信、支付、企微等）。"
            "action=list|get|upsert|delete。"
            "自定义分两种：单一（url/账号/token）与内容式（连接字段 + items 明细表，多 bot/用户/webhook）。"
            "禁止把 DeepSeek/OpenAI/xAI 等对话模型的 api_key/base_url/model 写这里——"
            "那些走工具 llms（设定→LLM）。"
            "create_tool 时业务连接走本工具，并写 _schema.layout=single|content；禁止把密钥写进 skill 或 kb。"
            "平台预置仅 HTTP 网络（代理）。其它连接用自定义集成，id 建议与 skill 同名。",
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
                        "description": "集成 id：http 或自定义（建议=skill 名）",
                    },
                    "fields_json": {
                        "type": "string",
                        "description": (
                            "upsert 时的字段 JSON 对象字符串。"
                            'http: {"proxy_url","flaresolverr_url"}；'
                            '单一：{"url":"...","token":"..."}；'
                            '内容式加 items：{"items":{"bot1":{"name":"bot1","webhook":"https://..."}}}。'
                            "密码留空表示不修改已有值。"
                        ),
                    },
                },
                "required": ["action"],
            },
        ),
        (
            "llms",
            "【主推·对话模型】设定→LLM：列出/新增/改默认/删本机已保存的对话模型。"
            "action=list|get|upsert|set_default|delete|models。"
            "创建/改技能前先 list，确认现有模型。"
            "边界：本工具只管已保存供应商；未入库的站点/中转站要看 /models 用技能 list_api_models。"
            "用户给的 OpenAI/DeepSeek/xAI key、base_url、model 必须 upsert 到这里，禁止写入 integrations。"
            "技能里用 from app.services.credentials import llm_credentials。",
            manage_llms,
            {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "get", "upsert", "set_default", "delete", "models"],
                        "description": "list=本机已配置模型；models=向供应商拉取 /models；upsert=写入设定→LLM",
                    },
                    "id": {
                        "type": "string",
                        "description": "LLM id 或名称（get/set_default/delete/models）",
                    },
                    "fields_json": {
                        "type": "string",
                        "description": (
                            "upsert 字段 JSON。"
                            '例：{"name":"DeepSeek","provider":"deepseek",'
                            '"base_url":"https://api.deepseek.com/v1",'
                            '"api_key":"...","model":"deepseek-chat","is_default":true}'
                        ),
                    },
                },
                "required": ["action"],
            },
        ),
        (
            "create_tool",
            "【主推·创建/更新业务 Skill】"
            "必须先向用户出示规格卡并得到明确确认，禁止在「好/行/随便」时创建。"
            "必填：spec_confirmed=true、user_confirmation=用户原话、spec_json。"
            "新建默认 live（当轮即可调用）。"
            "先 llms action=list 看已有对话模型。"
            "对话模型 key → llm_fields_json / 工具 llms（设定→LLM），handler 用 llm_credentials()。"
            "业务连接 → integration_fields_json / integrations（单一 url/token，或多记录 items），handler 用 integration_config()。"
            "禁止把 LLM 的 api_key 写进集成。代码里出现明文密钥会失败。"
            "修已有：先 read_skill 再 update=true。"
            "多操作技能必须 parameters.action.enum + 各动作字段；"
            "list/query 必须有 limit（默认 50）。禁止空 properties:{}。"
            "局域网服务用 skill_http.request，禁止伪造 Host=localhost；"
            "NocoDB 完整 CRUD 用 email+password 不是 PAT；502 不要改代码、不要删技能。"
            "分组：group 填 capability_groups 的 id 或中文名；省略则放进「其它」，不要靠关键词猜。",
            create_agent_tool,
            {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Skill/tool id（小写+下划线），必须与主入口一致。"
                            "更新已有技能用同一 name，不要加 _v2。"
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": "何时使用；请含中文场景词便于软过滤。分组请填 group，省略则放进「其它」。",
                    },
                    "handler_code": {
                        "type": "string",
                        "description": (
                            "推荐最小写法（系统自动脚手架）:\n"
                            "async def handle(**kwargs) -> str:\n"
                            "    import json\n"
                            "    from app.services.credentials import llm_credentials, integration_config\n"
                            "    llm = llm_credentials()  # 或 llm_credentials('设定里的 llm id')\n"
                            "    # 业务连接：cfg=integration_config('id')；多记录读 cfg.get('items')\n"
                            "    return json.dumps({...}, ensure_ascii=False)\n\n"
                            "也可手写 def register(registry)，但 registry.register 第一个参数必须等于 name。\n"
                            "规则: 对话模型走 llm_credentials；业务连接走 integration_config；勿硬编码密钥。"
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
                        "description": "true=就地覆盖并升版本。修 bug 必须 true。",
                        "default": False,
                    },
                    "stage": {
                        "type": "string",
                        "description": (
                            "draft|live|auto。auto=live（当轮可调用）。"
                            "仅当用户要求先沙箱时用 draft。"
                        ),
                    },
                    "promote": {
                        "type": "boolean",
                        "description": "true=写完 draft 后立即 promote 到 skills/ 并热加载。",
                        "default": False,
                    },
                    "force_new": {
                        "type": "boolean",
                        "description": (
                            "仅当确实要新建与已有 skill 名字相近的独立工具时为 true。"
                            "默认 false：会拦截 my_skill_fixed 这类等价名。"
                        ),
                        "default": False,
                    },
                    "changelog": {
                        "type": "string",
                        "description": "本次更新说明（写入 manifest/SKILL.md 版本历史）",
                    },
                    "spec_confirmed": {
                        "type": "boolean",
                        "description": "用户已看过规格卡并明确确认后才为 true。默认 false。",
                        "default": False,
                    },
                    "user_confirmation": {
                        "type": "string",
                        "description": "用户确认原话。不能是「好/行/随便/你看着办」。",
                    },
                    "how_to_call": {
                        "type": "string",
                        "description": "用户以后怎么喊这个技能，一句人话，如「查一下上海天气」。",
                    },
                    "spec_json": {
                        "type": "string",
                        "description": (
                            "规格 JSON："
                            '{"purpose":"...","trigger":"...","inputs":'
                            '[{"name":"city","type":"string","example":"上海","required":true}],'
                            '"success":"...","failure":"...","llm_id":"","integration_id":"","no_params":false}'
                        ),
                    },
                    "llm_id": {
                        "type": "string",
                        "description": "绑定的设定→LLM id。技能要调对话模型时填写；空=默认模型。",
                    },
                    "llm_fields_json": {
                        "type": "string",
                        "description": (
                            "用户新给的对话模型字段，写入设定→LLM，禁止写进 handler 或 integrations。"
                            '例：{"name":"DeepSeek","provider":"deepseek","base_url":"https://api.deepseek.com/v1",'
                            '"api_key":"...","model":"deepseek-chat"}'
                        ),
                    },
                    "integration_id": {
                        "type": "string",
                        "description": (
                            "绑定的集成 id（业务连接）。默认与技能同名。"
                            "不要把 LLM 供应商 key 写这里。"
                        ),
                    },
                    "integration_fields_json": {
                        "type": "string",
                        "description": (
                            "业务连接字段 JSON，写入设定→集成。"
                            '单一：{"url":"...","token":"..."}；'
                            '内容式：{"url":"...","items":{"u1":{"name":"张三","userid":"id"}}}。'
                            "对话模型请用 llm_fields_json。"
                        ),
                    },
                    "role": {
                        "type": "string",
                        "description": "primary|equivalent|fallback|dev。业务工具用 primary。",
                        "default": "primary",
                    },
                    "tag": {
                        "type": "string",
                        "description": "短标签，如 天气 / 主机",
                    },
                    "group": {
                        "type": "string",
                        "description": (
                            "设定→能力/工具函数 的分类：填已有分组的 id 或中文名；"
                            "没有则新建该分组。省略则放进「其它」，不会按关键词乱分。"
                            "先 capability_groups action=list 看现有分类。"
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
            "capability_groups",
            "【主推·技能分类】设定→能力/工具函数 共用的分组。"
            "action=list|add|rename|delete|assign。"
            "新建技能前 list，把 group 传给 create_tool；"
            "省略 group 会进「其它」，不要按天气/图片等词乱放。"
            "已有技能改分类：assign + name + group（中文名也可，没有就新建）。",
            manage_capability_groups,
            {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "add", "rename", "delete", "assign"],
                        "description": "list=现有分类；add=新建；rename=改名；delete=删除（技能移到其它）；assign=把技能/工具放进某分类",
                    },
                    "id": {
                        "type": "string",
                        "description": "分组 id（rename/delete）；assign 时也可当技能名后备",
                    },
                    "label": {
                        "type": "string",
                        "description": "中文名（add/rename）；assign 时也可当 group 后备",
                    },
                    "icon": {
                        "type": "string",
                        "description": "可选图标名，如 picture / folder-open",
                    },
                    "name": {
                        "type": "string",
                        "description": "assign 时的技能或工具 id",
                    },
                    "group": {
                        "type": "string",
                        "description": "assign 的目标分类 id 或中文名",
                    },
                    "confirm_id": {
                        "type": "string",
                        "description": "delete 时必须与 id 相同",
                    },
                },
                "required": ["action"],
            },
        ),
        (
            "list_skills",
            "列出 live(skills/) 与 draft(workspace/skills/) 技能包 id。改 skill 前先 list。",
            list_skills_tool,
            {
                "type": "object",
                "properties": {
                    "include_draft": {
                        "type": "boolean",
                        "description": "是否包含草稿，默认 true",
                        "default": True,
                    },
                },
                "required": [],
            },
        ),
        (
            "read_skill",
            "读取 live/draft skill 的 manifest、handler.py、SKILL.md。"
            "更新前必用：read_skill → create_tool(name=同一名字, update=true)。",
            read_skill,
            {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "主入口 skill 名（不要 *_v2）",
                    },
                    "stage": {
                        "type": "string",
                        "description": "auto|live|draft，默认 auto（优先 live）",
                    },
                    "full": {
                        "type": "boolean",
                        "description": "true=返回完整 SKILL.md（含长 changelog）；默认 false 省略历史",
                        "default": False,
                    },
                },
                "required": ["name"],
            },
        ),
        (
            "validate_skill",
            "校验 skill handler 语法/结构（不访问网络）。promote 或 stage=live 前建议调用。",
            validate_skill_tool,
            {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "skill id；与 handler_code 二选一或同时（优先 code）",
                    },
                    "handler_code": {
                        "type": "string",
                        "description": "可选：直接校验这段代码",
                    },
                    "stage": {
                        "type": "string",
                        "description": "auto|live|draft，从磁盘读 handler 时用",
                    },
                },
                "required": [],
            },
        ),
        (
            "promote_skill",
            "将 workspace/skills/<id> 草稿发布到 skills/<id> 并热加载。先 validate 再 promote。"
            "仅发布技能包；knowledge_refs 同步为引用边，不会把目标知识自动认定为正式/金叶。"
            "技能 handler 若写 memory/kb 仍走 agent 门禁（暂存），须人工评审批准。",
            promote_skill_tool,
            {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "要发布的 skill id",
                    },
                },
                "required": ["name"],
            },
        ),
        (
            "delete_tool",
            "删除可变业务 skill。必须先向用户复述技能名和用途。"
            "confirm_name 必须等于 name；user_confirmation 必须是用户明确点名同意，不能是「好/删吧」。"
            "不可删 builtin/受保护 skill。"
            "HTTP 502/连不上不是删技能的理由。",
            delete_agent_tool,
            {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "要删除的 skill 名",
                    },
                    "confirm_name": {
                        "type": "string",
                        "description": "必须与 name 完全一致",
                    },
                    "user_confirmation": {
                        "type": "string",
                        "description": "用户明确同意删除的原话",
                    },
                    "stage": {
                        "type": "string",
                        "description": "live|draft|both，默认 live",
                    },
                },
                "required": ["name", "confirm_name"],
            },
        ),
    ]

    for name, desc, handler, params in tools:
        registry.register(name, desc, handler, params, source="builtin")
