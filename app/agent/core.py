"""Agent core: LLM + tool loop + memory/session."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
import re
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from app.config import Settings, get_settings
from app.llm.client import LLMClient, get_llm_client
from app.memory.session import SessionStore, get_session_store, suggest_session_title
from app.memory.store import MemoryStore, get_memory_store
from app.models.schemas import ChatResponse, ToolCallRecord
from app.tools.registry import ToolRegistry, get_tool_registry
from app.tools.protection import preserve_turn_context

logger = logging.getLogger(__name__)

# Always-on: vague questions must not be filled with invented facts.
GROUNDING_INSTRUCTION = (
    "【事实边界】信息不足时说明缺口，最多问 1～3 个关键问题，然后停；"
    "不编造数据、来源、进度、承诺或未查到的细节。"
    "需要事实先调工具或知识库；没查到就说没查到，不要用完整答案填空。"
    "只能推测时必须标明是推测，不要装确定。"
    "不要为了显得有用而编造。"
    "【时间铁律】凡涉及现在几点、今天日期、星期、早晚、多久之后、行程时刻，回答前必须先调用 get_current_time，"
    "只按工具返回的 beijing 字段（北京时间 UTC+8）作答；未调用就不准说任何具体时间或日期，角色扮演模式同样适用。"
    "【何时提问】先用上下文、记忆、知识库和只读工具找答案；可逆、低影响、在用户委托范围内的细节按合理默认自己定，并在回复里说明你的选择。"
    "只有缺少会实质改变结果、又查不到的信息，或必须由用户拍板（花钱、删除、对外发送、结束进程等）时，才调用 ask_user，然后停；"
    "调用后正文不要把同一组问题再写一遍，也不要在正文里出客服式 A/B 长题。"
    "一次以一个自然的问题为主（真正独立的最多 3 个）；选项 2～6 个、简短、互不重叠、真实可执行，需要解释写成「选项 :: 说明」；"
    "不要列「其他/都可以」（表单自带补充框），不要编造未确认可用的服务或账户，不要把高风险选项放第一个当默认。"
    "用户取消或跳过后尊重决定，不要立刻重问同一问题。已有的安全确认（结束进程、删除、发消息、付款等）照常走，不能因为少打断而跳过或替用户同意。"
)

# Long-term memory instruction injected into system prompt
MEMORY_INSTRUCTION = (
    "Memory (tool `memory`): short preference/habit/fact only — not procedures. "
    "Only matched snippets plus explicit pins (and a small session working-memory quota) "
    "are injected, never the full store. "
    "Pinned lines are standing prefs; truncated long notes are pointers (they include id=). "
    "If memory conflicts with kb, follow kb (get the page). "
    "Missing or truncated fact → memory action=get with that id=, or action=recall with a query. "
    "Persist 记住/保存/别忘了: control prefs (preference/constraint/goal/strategy/habit/rule) "
    "→ standing memory; short facts/notes without TTL → active fact memory "
    "(injectable, not certified gold); evidence/inferred/scratch → staging+TTL "
    "(not auto-injected; fetch by id= still works); "
    "long structured docs → kb staging + link_ref; repeatable multi-step → workflow; "
    "tabular business records → an installed data skill if any, not memory. "
    "Do not invent certified/gold knowledge; human review approve for 正式认定. "
    "Never claim saved without a successful tool call."
)

DURABLE_PERSIST_FALLBACK = (
    "DURABLE PERSIST ROUTING: classify content → memory (short/staging) / kb (structured docs, staging) / "
    "workflow (multi-step automation). Must call the target tool before claiming saved. "
    "Staging + review_required until human approve; never auto-certify gold."
)

KB_INSTRUCTION = (
    "KB (tool `kb`): versioned markdown wiki — authority for procedures and standards. "
    "Collections: sop/product/handbook/reference/daily/staging/default. "
    "Agent writes land as staging/green-leaf; formal gold requires human review approve. "
    "Ground in matched snippets; cite [[title]]; truncated → kb get before inventing. "
    "If nothing matches, say so — do not invent procedures. "
    "Long docs → kb staging; short prefs → memory; skill promote syncs refs only (no auto-certify). "
    "session notes → not a procedure source."
)

# Appended when at least one KB page was matched this turn
KB_HIT_INSTRUCTION = (
    "KB GROUNDING THIS TURN: wiki snippets below are the procedure source. "
    "Ignore truncated memory notes that overlap these pages. "
    "If a snippet is truncated, call kb action=get for the full page before inventing missing steps. "
    "Obey any stage order / output format in those pages."
)

GROUNDING_STACK = (
    "SOURCE PRIORITY: kb procedures > pinned short memory prefs > "
    "this-session TASK STATE / SESSION NOTES. "
    "SESSION NOTES and TASK STATE are valid working memory for this conversation's "
    "goals, steps, artifacts, and tool outcomes. They are not SOPs and must not "
    "rewrite kb procedures, but when continuing a multi-step task treat them as "
    "the current task state. "
    "Do not let a slightly edited memory rewrite a knowledge-base procedure. "
    "Never paste handler.py / skill source / raw tool JSON into the user-visible reply "
    "unless the user asked to see the code. After running a skill, say what it did in "
    "one or two sentences — do not dump the tool result."
)

WORKFLOW_INSTRUCTION = (
    "Workflow (tool `workflow`): list|get|create|update|save|run|status|list_runs|resume|reject|delete. "
    "Prefer a saved workflow for multi-step SOPs. "
    "Inside a workflow agent step, do not call workflow run/save/create/update/delete again."
)

INTEGRATION_INSTRUCTION = (
    "CREDENTIALS — two stores, do not mix: "
    "chat models (base_url/api_key/model) → tool `llms` / llm_credentials(); "
    "business APIs → tool `integrations` / integration_config() (single fields or items). "
    "Never put LLM keys in integrations or handler.py; never put host passwords in llms or kb."
)

MEDIA_INSTRUCTION = (
    "Media: only use a media/vision skill if installed and the user asked. "
    "Uploads under uploads/ are already shown on the user bubble — do not re-embed them. "
    "Do not call analysis tools just because files were attached. "
    "Existing workspace image → ![name](relative/path.jpg)."
)

# Live tool results fed back to the LLM this turn (session storage stays shorter).
_TOOL_RESULT_LLM_CHARS = 8000
_TOOL_RESULT_LLM_CHARS_WIDE = 16000
_TOOL_RESULT_LLM_CHARS_TIGHT = 2500
_WIDE_TOOL_GROUPS = frozenset({"office", "network", "vision"})
_WIDE_TOOL_RESULT = frozenset({"workspace"})
_SOURCE_TOOL_RESULT = frozenset({"read_skill", "validate_skill", "list_skills"})
_TIGHT_TOOL_GROUPS = frozenset({"infra"})



def _resolve_user_display_name() -> str:
    """Single-user / local-session display name for persona injection."""
    try:
        from app.auth.local_session import load_local_session
        from app.auth.users import (
            effective_display_name,
            get_user_by_id,
            sole_user_row,
        )

        local = load_local_session() or {}
        uid = str(local.get("user_id") or "")
        if uid:
            row = get_user_by_id(uid)
            if row:
                return effective_display_name(row)
        row = sole_user_row()
        if row:
            return effective_display_name(row)
        return str(local.get("username") or "").strip()
    except Exception:
        return ""


class Agent:
    def __init__(
        self,
        settings: Settings | None = None,
        llm: LLMClient | None = None,
        tools: ToolRegistry | None = None,
        sessions: SessionStore | None = None,
        memory: MemoryStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm or get_llm_client()
        self.tools = tools or get_tool_registry()
        self.sessions = sessions or get_session_store()
        self.memory = memory or get_memory_store()

    @staticmethod
    def _context_query(
        history: list[dict[str, Any]],
        message: str,
        *,
        recent_user_turns: int = 2,
    ) -> str:
        """Build a short query from recent user turns + current message.

        Used for memory match and tool soft-filter so short replies like
        「那个文件」 still see prior path/topic tokens.
        """
        parts: list[str] = []
        user_turns = [
            str(m.get("content") or "").strip()
            for m in history
            if m.get("role") == "user" and str(m.get("content") or "").strip()
        ]
        for t in user_turns[-max(0, int(recent_user_turns)) :]:
            # keep each turn short for filter/memory scoring
            parts.append(t[:400])
        cur = (message or "").strip()
        if cur:
            parts.append(cur)
        # Short confirm / upload ack: keep last spec card in the filter so
        # create_tool / office capability-gap stay unlocked.
        if len(cur) <= 40:
            for m in reversed(history):
                if m.get("role") != "assistant":
                    continue
                asst = str(m.get("content") or "").strip()
                if asst:
                    parts.insert(0, asst[:500])
                break
        return "\n".join(parts)

    @staticmethod
    def _paths_from_history(
        history: list[dict[str, Any]], *, max_msgs: int = 6, max_paths: int = 12
    ) -> list[str]:
        """Harvest path hints from recent assistant metadata / tool results."""
        from app.tools.intent_routing import extract_paths_from_tool_result

        out: list[str] = []
        seen: set[str] = set()
        recent = [m for m in history if m.get("role") == "assistant"][-max_msgs:]
        for m in recent:
            meta = m.get("metadata") or {}
            for p in meta.get("media_paths") or []:
                if isinstance(p, str) and p.strip() and p not in seen:
                    seen.add(p)
                    out.append(p.replace("\\", "/"))
            for tc in meta.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                args = tc.get("arguments") or {}
                if isinstance(args, dict):
                    for k in ("path", "source", "dest", "filename", "script_path"):
                        v = args.get(k)
                        if isinstance(v, str) and v.strip() and v not in seen:
                            seen.add(v)
                            out.append(v.replace("\\", "/"))
                for p in tc.get("media_paths") or []:
                    if isinstance(p, str) and p.strip() and p not in seen:
                        seen.add(p)
                        out.append(p.replace("\\", "/"))
                res = tc.get("result") or ""
                if isinstance(res, str) and res:
                    for p in extract_paths_from_tool_result(res, max_paths=6):
                        if p not in seen:
                            seen.add(p)
                            out.append(p)
            if len(out) >= max_paths:
                break
        return out[:max_paths]

    @preserve_turn_context
    async def chat(
        self,
        message: str,
        *,
        session_id: str | None = None,
        use_tools: bool = True,
        use_memory: bool = True,
        model: str | None = None,
        session_title: str | None = None,
        allow_deputy: bool = False,
        use_deputy: bool = False,
        skip_deputy: bool = False,
        form_reply: Any = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        route_origin: str = "chat.web",
    ) -> ChatResponse:
        if not self.llm.is_configured:
            raise RuntimeError(self.llm.unconfigured_message())
        if getattr(self.llm, "is_cli", False):
            use_tools = False
        # Tools that must act only on the user's own words this turn
        # (terminal service / stop_service) read this.
        try:
            from app.tools.protection import set_turn_context

            set_turn_context(message, session_id)
            if route_origin in ("chat.scheduler", "chat.workflow", "chat.webhook"):
                from app.tools.protection import (
                    UNATTENDED_BLOCKED_ACTIONS,
                    add_blocked_tools,
                )

                add_blocked_tools(UNATTENDED_BLOCKED_ACTIONS)
        except Exception:
            logger.exception("set turn context failed")

        agent_cfg = self._agent_cfg()
        max_history = int(agent_cfg.get("max_history_messages") or self.settings.max_history_messages)
        max_rounds = int(agent_cfg.get("max_tool_rounds") or self.settings.max_tool_rounds)

        title = (
            (session_title or "").strip()
            or suggest_session_title(message)
            or "对话"
        )[:80]
        if session_id:
            session = await self.sessions.get(session_id)
            if session is None:
                session = await self.sessions.create(title=title)
                session_id = session["session_id"]
        else:
            session = await self.sessions.create(title=title)
            session_id = session["session_id"]

        history = await self.sessions.get_messages(session_id, limit=max_history)
        try:
            # New sessions are created after set_turn_context: bind the real id
            # (kill confirm tokens are per session) without changing the turn id.
            from app.tools.protection import (
                get_turn_id,
                get_turn_session_id,
                set_turn_context,
            )

            if get_turn_session_id() != session_id:
                set_turn_context(message, session_id, turn_id=get_turn_id())
        except Exception:
            logger.exception("bind turn session failed")

        # Kill / stop-service confirm card: the user's answer is executed (or
        # cancelled) here, server-side. The model never sees the token, so it
        # must not be asked to act on it (that caused endless re-asking).
        try:
            _kc = await self._handle_kill_confirm_reply(
                session_id=session_id,
                message=message,
                history=history,
                form_reply=form_reply,
                max_history=max_history,
            )
        except Exception:
            logger.exception("kill-confirm reply handling failed")
            _kc = None
        if _kc is not None:
            return _kc

        if isinstance(form_reply, dict):
            try:
                from app.agent.ask_form import (
                    apply_integ_form_reply,
                    is_form_cancel,
                    last_assistant_form,
                )

                from app.agent.ask_form import form_reply_is_stale

                if form_reply_is_stale(last_assistant_form(history, any_age=True), form_reply):
                    ack = (
                        "那个问题已经过期（之后有了新的消息），没有按它执行。"
                        "需要的话请在最新的问题里选，或直接告诉我。"
                    )
                    await self.sessions.append_messages(
                        session_id,
                        [
                            {"role": "user", "content": (message or "").strip() or "（过期的表单回复）"},
                            {"role": "assistant", "content": ack},
                        ],
                        title=suggest_session_title(message),
                        max_history=max_history,
                    )
                    return ChatResponse(
                        session_id=session_id,
                        reply=ack,
                        model=getattr(self.llm, "model", "") or "",
                    )
                if is_form_cancel(form_reply):
                    ack = "好，已取消。没有创建技能，也没有保存配置。"
                    try:
                        _prev = last_assistant_form(history, any_age=True) or {}
                        if _prev.get("purpose") == "kill_confirm":
                            from app.services.process_control import revoke_session_tokens

                            revoke_session_tokens(session_id)
                            ack = "好，已取消，没有结束任何进程。"
                    except Exception:
                        logger.exception("kill-confirm cancel cleanup failed")
                    await self.sessions.append_messages(
                        session_id,
                        [
                            {"role": "user", "content": (message or "取消").strip() or "取消"},
                            {"role": "assistant", "content": ack},
                        ],
                        title=suggest_session_title(message),
                        max_history=max_history,
                    )
                    return ChatResponse(
                        session_id=session_id,
                        reply=ack,
                        model=getattr(self.llm, "model", "") or "",
                    )

                prev_form = last_assistant_form(history, any_age=True)
                extra = str(
                    form_reply.get("other") or form_reply.get("note") or ""
                ).strip()
                if prev_form and prev_form.get("kind") == "integ":
                    cfg_ids = {
                        str(f.get("id") or "")
                        for f in (prev_form.get("fields") or [])
                        if isinstance(f, dict)
                        and str(f.get("id") or "") not in ("other", "note", "_cancel")
                    }
                    has_cfg = any(
                        str(form_reply.get(k) or "").strip() for k in cfg_ids if k
                    )
                    if has_cfg:
                        ok, err = apply_integ_form_reply(prev_form, form_reply)
                        if not ok:
                            fail = f"没能保存配置：{err or '未知错误'}"
                            await self.sessions.append_messages(
                                session_id,
                                [
                                    {"role": "user", "content": message},
                                    {"role": "assistant", "content": fail},
                                ],
                                title=suggest_session_title(message),
                                max_history=max_history,
                            )
                            return ChatResponse(
                                session_id=session_id,
                                reply=fail,
                                model=getattr(self.llm, "model", "") or "",
                            )
                    pending = str(prev_form.get("pending_user") or "").strip()
                    if extra:
                        pending = (pending + "\n用户补充：" + extra).strip()
                    if pending:
                        if has_cfg:
                            message = (
                                pending
                                + "\n（连接信息已保存在本机设定→集成，请立刻重试刚才的事，不要再索要密码或 Key。）"
                            )
                        else:
                            message = pending + "\n（未改集成配置，按用户补充继续。）"
                    form_reply = None
            except Exception:
                logger.exception("apply integ form reply failed")

        from app.agent.deputy import (
            deputy_label,
            get_deputy_row,
            is_skill_work_tool,
            resolve_pending_task,
            should_use_deputy,
        )

        deputy_row = get_deputy_row() if allow_deputy else None
        message, use_deputy, skip_deputy = resolve_pending_task(
            message,
            history,
            use_deputy=use_deputy,
            skip_deputy=skip_deputy,
        )
        active_llm: LLMClient = self.llm
        used_deputy = False
        deputy_reason: str | None = None
        if use_deputy and deputy_row:
            try:
                active_llm = LLMClient.from_llm_config(deputy_row)
                if active_llm.is_configured:
                    used_deputy = True
                    deputy_reason = "user"
                    logger.info(
                        "This turn uses deputy LLM by user confirm: %s",
                        deputy_label(deputy_row),
                    )
                else:
                    active_llm = self.llm
            except Exception:
                logger.exception("Failed to build deputy LLM client")
                active_llm = self.llm

        # 模型路由：主对话（未指定 model、未走副模型时）
        if not used_deputy and not model:
            from app.llm.routing import routed_client as _route

            _feats = [route_origin or "chat.web"]
            if agent_cfg.get("roleplay_enabled"):
                _feats.insert(0, "chat.roleplay")
            active_llm = _route(_feats, fallback=self.llm, allow_cli=False) or self.llm

        tight_ctx = self._is_tight_ctx_llm(active_llm)
        # Tight window only shrinks the prompt; persistence still uses max_history.
        if tight_ctx:
            prompt_max_history = min(max_history, 8)
            if len(history) > prompt_max_history:
                history = history[-prompt_max_history:]
        evo_settings = None
        session_full: dict[str, Any] | None = None
        try:
            from app.agent.evolution import (
                evolution_settings,
                render_evolution_block,
            )

            evo_settings = evolution_settings(agent_cfg)
            session_full = await self.sessions.get(session_id)
            evo_cap = 900 if tight_ctx else int(evo_settings.get("max_chars") or 2200)
            evo_block = render_evolution_block(
                (session_full or {}).get("evolution"),
                max_chars=evo_cap,
            )
        except Exception:
            logger.exception("Load session evolution failed")
            evo_block = ""
            evo_settings = None
            try:
                session_full = await self.sessions.get(session_id)
            except Exception:
                session_full = None

        # Combine current turn + recent user turns for memory match & tool filter
        # (improves 指代 like 「刚才那个文件」 without dumping full history into filter).
        base_filter_query = self._context_query(history, message, recent_user_turns=2)

        from app.tools.intent_routing import (
            build_filter_query,
            durable_persist_requirement,
            extract_paths_from_tool_result,
            force_tools_from_text,
            has_upload_image,
            is_image_only_turn,
            required_tools_from_text,
        )

        intent_force = force_tools_from_text(base_filter_query or message)
        required_tools = required_tools_from_text(message)
        durable_plan = durable_persist_requirement(message)
        if durable_plan:
            intent_force |= set(durable_plan.force_tools)
        # Vague follow-ups ("搞一下那个") reuse on-demand cores from recent tool turns
        try:
            lookback = 4 if self._is_followup_deixis(message) else 2
            intent_force |= self.tools.on_demand_cores_from_history(
                history, lookback=lookback, current_message=message
            )
        except Exception:
            logger.exception("on-demand core sticky from history failed")

        # ---- Skill meta tools: this-turn intent; sticky create does not leak into list/chat ----
        skill_meta_unlocked: set[str] = set()
        this_skill_meta: set[str] = set()
        sticky_meta: set[str] = set()
        try:
            from app.services.skill_lifecycle import (
                META_TOOL_NAMES,
                auto_meta_tools_for_query,
                get_sticky_meta_tools,
                live_meta_tools_for_turn,
                persist_sticky_meta_tools,
            )

            sticky_meta = get_sticky_meta_tools(session_full)
            # Unlock from *this* user sentence only — not the 2-turn context blob
            # (that blob still contains 「删除技能」 after the user asks 「你有什么技能」).
            auto_meta = auto_meta_tools_for_query(message)
            try:
                reg_meta = self.tools._allowed_meta_tools(message)  # noqa: SLF001
            except Exception:
                reg_meta = set()
            this_skill_meta = {
                t for t in (auto_meta | reg_meta) if t in META_TOOL_NAMES
            }
            if this_skill_meta:
                await persist_sticky_meta_tools(
                    session_id,
                    this_skill_meta,
                    sessions=self.sessions,
                )
                if session_full is not None:
                    from app.services.skill_lifecycle import merge_sticky_meta_tools

                    session_full["metadata"] = merge_sticky_meta_tools(
                        session_full, this_skill_meta
                    )
                    sticky_meta = get_sticky_meta_tools(session_full)
        except Exception:
            logger.exception("Skill meta sticky unlock failed")

        # Spec-card confirm / pending create: keep create_tool open even if
        # the user only replies 「确认」 or uploads the files to parse.
        spec_confirmed_this_turn = False
        pending_skill: dict[str, Any] = {}
        upload_after_spec = False
        try:
            from app.services.skill_spec import has_spec_card, is_spec_confirmation
            from app.services.skill_lifecycle import get_pending_skill_create

            last_asst = ""
            for m in reversed(history):
                if m.get("role") == "assistant":
                    last_asst = str(m.get("content") or "")
                    break
            pending_skill = get_pending_skill_create(session_full)
            spec_confirmed_this_turn = is_spec_confirmation(message) and (
                has_spec_card(last_asst) or bool(pending_skill)
            )
            upload_after_spec = (
                ("已上传" in (message or "") or "上传了" in (message or ""))
                and (has_spec_card(last_asst) or bool(pending_skill))
            )
            if spec_confirmed_this_turn or pending_skill or upload_after_spec:
                create_bundle = {
                    "create_tool",
                    "read_skill",
                    "list_skills",
                    "validate_skill",
                    "promote_skill",
                }
                try:
                    from app.services.skill_lifecycle import persist_sticky_meta_tools

                    await persist_sticky_meta_tools(
                        session_id,
                        create_bundle,
                        sessions=self.sessions,
                    )
                except Exception:
                    logger.exception("persist create unlock after spec confirm failed")
        except Exception:
            logger.exception("Spec-confirm create_tool unlock failed")

        facts_ready = False
        try:
            from app.agent.ask_form import skill_facts_already_collected

            facts_ready = skill_facts_already_collected(
                message, history, form_reply
            )
        except Exception:
            facts_ready = False
        try:
            from app.services.skill_lifecycle import (
                META_TOOL_NAMES,
                live_meta_tools_for_turn,
            )

            skill_meta_unlocked = live_meta_tools_for_turn(
                message,
                sticky=sticky_meta,
                this_meta=this_skill_meta,
                pending=bool(pending_skill)
                or bool(upload_after_spec)
                or facts_ready,
                spec_confirmed=bool(spec_confirmed_this_turn) or facts_ready,
            )
            # Context-query force_tools may still contain create_tool from an
            # earlier 「删除/创建技能」. Strip write-meta not allowed this turn.
            intent_force -= META_TOOL_NAMES - skill_meta_unlocked
            intent_force |= skill_meta_unlocked
        except Exception:
            logger.exception("Skill meta live-set failed")
        path_hints: list[str] = []
        # Seed path hints from recent assistant tool metadata in history
        path_hints.extend(self._paths_from_history(history))

        from app.agent.ask_form import (
            should_offer_skill_form,
            skill_authoring_mode,
            skill_intake_form,
        )

        if should_offer_skill_form(
            message, intent_force, history, form_reply=form_reply
        ):
            sform = skill_intake_form(message)
            logger.info("Skill intake form (skip markdown quiz)")
            await self.sessions.append_messages(
                session_id,
                [
                    {"role": "user", "content": message},
                    {
                        "role": "assistant",
                        "content": sform.get("title") or "请在下方确认",
                        "metadata": {"form": sform, "pending_user": message},
                    },
                ],
                title=suggest_session_title(message),
                max_history=max_history,
            )
            return ChatResponse(
                session_id=session_id,
                reply=str(sform.get("title") or "请在下方确认"),
                model=getattr(self.llm, "model", "") or "",
                form=sform,
            )

        # ---- Vision: installed skill uses 设定→集成 model; else native chat LLM ----
        from app.services.vision_input import (
            build_user_content_with_images,
            extract_image_paths_from_message,
            main_llm_supports_vision,
            vision_skill_tool_name,
        )

        # 模型路由：识图（本轮带图片）
        if not used_deputy and not model and has_upload_image(message):
            from app.llm.routing import routed_client as _route

            _vis = _route("vision", fallback=None, allow_cli=False, use_default=False)
            if _vis is not None:
                active_llm = _vis
                tight_ctx = self._is_tight_ctx_llm(active_llm)
        active_model = model or getattr(active_llm, "model", "") or ""
        if used_deputy:
            active_model = getattr(active_llm, "model", "") or ""
        active_base = getattr(active_llm, "base_url", "") or ""
        vision_native = main_llm_supports_vision(
            model=active_model,
            base_url=active_base,
            name=str(getattr(active_llm, "llm_id", "") or ""),
        )
        has_imgs = has_upload_image(message)
        image_paths = extract_image_paths_from_message(message) if has_imgs else []
        vision_tool = vision_skill_tool_name(self.tools)
        if has_imgs and vision_tool and use_tools:
            # Skill installed: never auto-pick chat LLM for pixels
            vision_native = False
            intent_force.add(vision_tool)
            if is_image_only_turn(message):
                required_tools.add(vision_tool)
            logger.info(
                "Vision skill path: tool=%s (model from 设定→集成)",
                vision_tool,
            )
        elif has_imgs and vision_tool and not use_tools:
            intent_force.discard(vision_tool)
            required_tools.discard(vision_tool)
            if not vision_native:
                logger.info("Vision skill installed but tools off; images will not be seen")
                vision_tool = None
        elif vision_native and has_imgs:
            try:
                from app.tools.lookup import tools_in_group

                for n in tools_in_group("vision"):
                    intent_force.discard(n)
                    required_tools.discard(n)
            except Exception:
                pass
            logger.info(
                "Vision native path: model=%s images=%s (no vision skill)",
                active_model,
                image_paths,
            )
        elif has_imgs and not vision_native:
            logger.info("No vision skill and text-only chat model; images will not be seen")

        if (
            allow_deputy
            and deputy_row
            and not used_deputy
            and not skip_deputy
            and should_use_deputy(
                message,
                intent_force | required_tools,
                tools=self.tools,
            )
        ):
            try:
                cand = LLMClient.from_llm_config(deputy_row)
                if cand.is_configured:
                    active_llm = cand
                    used_deputy = True
                    deputy_reason = "skill"
                    tight_ctx = self._is_tight_ctx_llm(active_llm)
                    logger.info(
                        "This turn uses deputy LLM for skill work: %s",
                        deputy_label(deputy_row),
                    )
            except Exception:
                logger.exception("Failed to switch to deputy for skill work")
            if used_deputy and has_imgs and not vision_tool:
                active_model = getattr(active_llm, "model", "") or ""
                active_base = getattr(active_llm, "base_url", "") or ""
                vision_native = main_llm_supports_vision(
                    model=active_model,
                    base_url=active_base,
                    name=str(getattr(active_llm, "llm_id", "") or ""),
                )

        # 模型路由：技能（按技能覆盖 > 技能默认）
        if not used_deputy and not model and use_tools:
            try:
                from app.agent.deputy import is_skill_work_tool as _is_skill
                from app.llm.routing import SKILL_PREFIX, routed_client as _route

                _cands = sorted(
                    n for n in (intent_force | required_tools) if _is_skill(n, self.tools)
                )
                if _cands:
                    _sk = _route(
                        [SKILL_PREFIX + n for n in _cands] + ["skill"],
                        fallback=None,
                        allow_cli=False,
                        use_default=False,
                    )
                    if _sk is not None:
                        active_llm = _sk
                        tight_ctx = self._is_tight_ctx_llm(active_llm)
            except Exception:
                logger.exception("Model routing for skill failed")

        image_only = is_image_only_turn(message)
        if image_only:
            intent_force.discard("kb")
            required_tools.discard("kb")
        from app.agent.persona import build_persona_prompt, use_compact_persona

        # Chat/RP keeps the full persona; business/tool turns use a short identity.
        persona_prompt = build_persona_prompt(
            agent_cfg,
            compact=use_compact_persona(
                base_filter_query or message,
                intent_force=intent_force,
                image_only=image_only,
                tools=self.tools,
            ),
            user_display_name=_resolve_user_display_name(),
        )
        meta_preview = {
            t
            for t in intent_force
            if t
            in {
                "create_tool",
                "delete_tool",
                "read_skill",
                "list_skills",
                "validate_skill",
                "promote_skill",
            }
        }
        system_parts = [persona_prompt]
        system_parts.extend(
            self._ops_instructions(
                use_tools=use_tools,
                max_rounds=max_rounds,
                image_only=image_only,
                include_media=self._message_needs_media(message, has_imgs=has_imgs),
                include_credentials=self._message_needs_credentials(
                    message, intent_force, meta_preview
                ),
                include_llm_catalog=self._message_needs_llm_catalog(
                    message, intent_force, meta_preview
                ),
                include_skilldev_routing=bool(meta_preview),
            )
        )
        if evo_block:
            system_parts.append(evo_block)
        try:
            from app.agent.context_continuity import render_task_state_block

            ts_block = render_task_state_block(
                ((session_full or {}).get("metadata") or {}).get("task_state"),
                max_chars=400 if tight_ctx else 800,
            )
            if ts_block:
                system_parts.append(ts_block)
        except Exception:
            logger.exception("Load session task_state failed")
        if image_only:
            if vision_native and has_imgs:
                system_parts.append(
                    "IMAGE-ONLY TURN:\n"
                    "- User sent image(s) and typed nothing else.\n"
                    "- You can see the image. Describe it in a few sentences, then stop.\n"
                    "- Do not call kb. Do not use numbered stages. Do not offer A/B/C quizzes."
                )
            elif vision_tool:
                system_parts.append(
                    "IMAGE-ONLY TURN:\n"
                    "- User sent image(s) and typed nothing else.\n"
                    f"- Call `{vision_tool}` on the upload path, describe the result, then stop.\n"
                    "- Do not call kb. Do not use numbered stages. Do not offer A/B/C quizzes."
                )
            else:
                system_parts.append(
                    "IMAGE-ONLY TURN:\n"
                    "- User sent image(s) and typed nothing else.\n"
                    "- No vision skill is installed and this model cannot see pixels. "
                    "Say you cannot see the image. Do not invent details."
                )
        elif has_imgs and vision_native:
            system_parts.append(
                "NATIVE VISION THIS TURN:\n"
                "- User attached image(s); pixels are included in the user message.\n"
                "- Analyze them yourself. Prefer NOT calling a vision skill "
                "unless the user asks for that tool."
            )
        elif has_imgs and not vision_native and vision_tool:
            system_parts.append(
                "VISION SKILL THIS TURN:\n"
                f"- Call `{vision_tool}` on the workspace path. The skill uses the LLM from 设定→集成→Vision.\n"
                "- Do not claim you already saw the pixels without a successful tool result."
            )
        if durable_plan:
            system_parts.append(
                "DURABLE PERSIST THIS TURN:\n"
                f"- primary_store={durable_plan.primary} op={durable_plan.op} "
                f"({durable_plan.reason})\n"
                f"- {durable_plan.hint}"
            )
        if intent_force:
            system_parts.append(
                "INTENT ROUTING (this turn): prefer tools "
                + ", ".join(sorted(intent_force))
                + (
                    ". Persist via the primary store above — not always memory."
                    if durable_plan
                    else ""
                )
            )
        # Skill CRUD availability — kill false "no permission" claims
        meta_this_turn = sorted(
            t
            for t in intent_force
            if t
            in {
                "create_tool",
                "delete_tool",
                "read_skill",
                "list_skills",
                "validate_skill",
                "promote_skill",
            }
        )
        authoring_mode = skill_authoring_mode(message)
        if facts_ready and authoring_mode not in {"create", "update"}:
            authoring_mode = "create"
        if meta_this_turn and authoring_mode in {"create", "update"}:
            system_parts.append(
                "SKILL DEV TOOLS AVAILABLE THIS TURN (session-sticky once unlocked):\n"
                f"- Tools: {', '.join(meta_this_turn)}\n"
                "- Policy: business skills under skills/ are mutable; "
                "only builtin/reserved/protected runtime skills are read-only.\n"
                "SKILL INTAKE:\n"
                "- If the user already said what the skill should do, call create_tool "
                "THIS TURN. Do not stop to confirm protocol or capabilities.\n"
                "- Local file/excel/pdf skills need no connection form — create immediately.\n"
                "- Only ask_user when host / API key / password is required and missing. "
                "First explain HOW to get it (short numbered steps), then the form, then STOP.\n"
                "- Do NOT write markdown quizzes, [ ] checkboxes, or a long spec card in prose.\n"
                "- NEVER create/update/delete on vague agreement "
                "(「好/行/随便/你看着办/默认」) when purpose is still empty.\n"
                "- Then create_tool(spec_confirmed=true, user_confirmation=用户原话, "
                "spec_json=..., how_to_call=..., stage=live, "
                "integration_id=..., integration_fields_json={url/账号/token 或 items 明细}).\n"
                "- Connection secrets MUST go to integration_fields_json (设定→集成). "
                "NEVER put passwords/tokens into handler_code, memory, or kb.\n"
                "- After success, copy usage.tell_user verbatim. Show integration summary "
                "(which fields are set; secrets masked). User edits later in 设定→集成.\n"
                "- If integration status is not ready: tell the user to fill 设定→集成; "
                "do not pretend the skill works.\n"
                "- Update: read_skill, restate what changes, then update=true with the same spec fields.\n"
                "- Delete: restate name+purpose; delete_tool(confirm_name=name, user_confirmation=原话).\n"
                "- If create_tool returns action_required=confirm_spec AFTER the user already "
                "gave address/purpose this thread: retry create_tool immediately with "
                "spec_confirmed=true and user_confirmation=用户本轮原文. Do NOT ask again.\n"
                "- NEVER ask the user to reply 「创建技能」to unlock you. These tools are already available.\n"
                "- Word/Excel/PPT/PDF/Markdown → call document. Do not create_tool for those formats.\n"
                "- NEVER claim a skill is live/created unless create_tool returned ok=true this turn.\n"
                "- After create_tool succeeds, immediately use the new skill to finish the user task. "
                "Do not stop at a delivery summary.\n"
                "- Multi-action skills: spec_json.inputs must include action (enum) and a limit "
                "for list/query (default 50). Never ship properties:{}.\n"
                "- LAN APIs: `await skill_http.arequest(...)` + 设定→集成 (never the sync request() "
                "inside async def handle — it freezes every chat); never spoof Host=localhost. "
                "HTTP 502: check 设定→集成; do not rewrite or delete the skill.\n"
                "- NEVER claim you lack skill permission when these tools are listed. "
                "If a call fails, report the tool error JSON (protected/syntax), not 'no permission'."
            )
            from app.agent.ask_form import skill_facts_already_collected

            if skill_facts_already_collected(message, history, form_reply):
                system_parts.append(
                    "FACTS ALREADY IN THIS THREAD — DO NOT ASK AGAIN:\n"
                    "- The user already gave the skill purpose and/or device address/API info.\n"
                    "- Do NOT call ask_user. Do NOT ask 用途/功能范围/端口/规格卡确认.\n"
                    "- Call create_tool THIS TURN with spec_confirmed=true, "
                    "user_confirmation=本轮用户原文, integration_fields_json from the address they gave.\n"
                    "- If the skill already exists, update=true with the same confirmation; "
                    "do not pop another form."
                )
        elif meta_this_turn:
            system_parts.append(
                "SKILL META TOOLS AVAILABLE (follow-up only):\n"
                f"- Tools: {', '.join(meta_this_turn)}\n"
                "- The user is NOT asking to create a new skill this turn.\n"
                "- If they ask what skills you have: call list_skills and answer. "
                "Do NOT start create_tool or show a create/edit intake form.\n"
                "- Only create/update/delete if this message explicitly asks to "
                "创建/新建/修改/编辑/删除 a skill."
            )
        if spec_confirmed_this_turn:
            system_parts.append(
                "SPEC CONFIRMED THIS TURN:\n"
                "- The user accepted the spec card (e.g. 「确认」).\n"
                "- You MUST call create_tool(spec_confirmed=true, "
                "user_confirmation=用户原话, spec_json=完整规格, stage=live) now.\n"
                "- Do not list workspace folders first. Create the skill, then execute "
                "the original task (e.g. read the uploaded files).\n"
                "- Do not ask for another magic phrase."
            )
        elif pending_skill or (
            "已上传" in (message or "")
            and self._text_has_office_files(message)
        ):
            from app.tools.lookup import has_group

            if has_group("office") and not pending_skill:
                system_parts.append(
                    "OFFICE FILES:\n"
                    "- Use tool `document` to read/write/edit/delete "
                    ".docx .xlsx .pptx .pdf .md. Do not create_tool for these."
                )
            elif pending_skill or not has_group("office"):
                system_parts.append(
                    "PENDING SKILL + USER FILES:\n"
                    "- A document-reading skill was requested or specified earlier.\n"
                    "- If list_skills shows it missing: create_tool immediately "
                    "(use the last spec card). Do not recursively list subdirectories.\n"
                    "- After it is live, call it on the uploaded files and complete the task."
                )
        elif use_tools and not meta_this_turn:
            system_parts.append(
                "create_tool is gated unless the user asks to create/fix a skill. "
                "Office files use `document`. "
                "Do not ask them to type 创建技能. Do not invent 'no permission'."
            )
        filter_query = build_filter_query(
            base_filter_query or message,
            path_hints=path_hints,
            extra_tools=intent_force,
        )
        # Memory/KB match on user text only — tool names / paths in filter_query
        # make long notes jump in or out when an unrelated memory is edited.
        retrieve_query = (base_filter_query or message).strip()
        kb_snip = ""
        kb_terms: list[str] = []
        if not image_only:
            try:
                from app.knowledge.store import get_knowledge_store

                kb_snip, kb_terms = await get_knowledge_store().context_for_prompt(
                    retrieve_query,
                    limit=2 if tight_ctx else 4,
                    max_chars=1000 if tight_ctx else 3200,
                    intent_text=message,
                )
            except Exception:
                logger.exception("KB context snippet failed")
        if use_memory:
            snippet = await self.memory.context_snippet(
                retrieve_query,
                limit=3 if tight_ctx else 5,
                max_chars=800 if tight_ctx else 1800,
                max_pin=4 if tight_ctx else 6,
                suppress_terms=kb_terms,
                session_id=session_id,
                working_limit=2 if tight_ctx else 3,
            )
            if snippet:
                system_parts.append(snippet)
        if kb_snip:
            system_parts.append(KB_HIT_INSTRUCTION)
            system_parts.append(kb_snip)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "\n\n".join(system_parts)}
        ]
        # Rebuild history without nested system prompts.
        # Restore recent tool process from metadata as a text block (not role=tool).
        hist_clip = 1200 if tight_ctx else 0
        from app.agent.context_continuity import history_messages_for_llm

        messages.extend(
            history_messages_for_llm(
                history,
                max_content=hist_clip,
                recent_tool_turns=1 if tight_ctx else 2,
            )
        )

        # Persist plain text in session; send multimodal content to LLM when supported
        user_msg = {
            "role": "user",
            "content": message,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        llm_user_content: Any = message
        if vision_native and has_imgs:
            try:
                llm_user_content, attached = build_user_content_with_images(
                    message, force_paths=image_paths or None
                )
                if attached:
                    logger.info("Attached %d image(s) to multimodal user message", len(attached))
                else:
                    # Failed to load pixels — fall back to skill path this turn
                    vision_native = False
                    llm_user_content = message
                    fallback = vision_tool
                    if fallback:
                        intent_force.add(fallback)
                        if is_image_only_turn(message) and self.tools.get(fallback):
                            required_tools.add(fallback)
                    logger.warning(
                        "Native vision attach failed; skill=%s", fallback or "none"
                    )
            except Exception:
                logger.exception("build_user_content_with_images failed")
                llm_user_content = message
        messages.append({"role": "user", "content": llm_user_content})

        tool_records: list[ToolCallRecord] = []
        total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        used_model = (
            (getattr(active_llm, "model", "") or "")
            if used_deputy
            else (model or getattr(active_llm, "model", "") or self.llm.model)
        )
        turn_llm = active_llm
        deputy_client: LLMClient | None = None
        if allow_deputy and deputy_row and not used_deputy:
            try:
                cand = LLMClient.from_llm_config(deputy_row)
                if cand.is_configured:
                    deputy_client = cand
            except Exception:
                logger.exception("Failed to prepare deputy LLM for hard-fail escalate")
        escalate_state: dict[str, Any] = {
            "used": used_deputy,
            "reason": deputy_reason,
        }
        malformed_tools = 0
        pending_form: dict[str, Any] | None = None
        final_content = ""
        cli_media_paths: list[str] = []
        forced_retries = 0
        max_forced_retries = 2
        # Each phase uses at most max_rounds tool batches; extra phases auto-run
        # so the model does not ask the user to type 「继续」.
        max_phases = max(2, min(5, (32 + max(1, max_rounds) - 1) // max(1, max_rounds)))
        phase = 0
        phase_start = 0
        round_i = 0
        auto_continued = 0
        near_limit_nudge_sent = False
        office_nudge_sent = False
        turn_tools: list[dict[str, Any]] | None = None
        last_terminal_state: str | None = None

        while True:
            phase_limit = phase_start + max(1, max_rounds)
            while round_i < phase_limit:
                # Soft budget warning so the model prefers finishing before the hard cap
                if (
                    use_tools
                    and not near_limit_nudge_sent
                    and tool_records
                    and round_i >= max(0, phase_limit - 1)
                ):
                    near_limit_nudge_sent = True
                    digest = self._tool_progress_digest(tool_records)
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"[SYSTEM] 本阶段工具额度还剩最后 1 轮"
                                f"（阶段 {phase + 1}，每阶段最多 {max_rounds} 轮）。\n"
                                f"已操作：{digest}\n"
                                "请先用一两句话写出本阶段已完成的事，再继续调用完成任务所需的下一个工具。"
                                "不要询问用户是否继续；额度用完后系统会自动进入下一阶段。"
                            ),
                        }
                    )

                # Refresh filter query with paths discovered in this turn's tool results
                filter_query = build_filter_query(
                    base_filter_query or message,
                    path_hints=path_hints,
                    extra_tools=intent_force,
                )
                openai_tools = (
                    self.tools.filter_tools(
                        filter_query or message,
                        force_tools=intent_force,
                        top_n=8 if self._is_tight_ctx_llm(turn_llm) else None,
                    )
                    if use_tools
                    else None
                )
                if use_tools and openai_tools is not None:
                    openai_tools = self._merge_turn_tools(
                        turn_tools, openai_tools, intent_force
                    )
                    from app.agent.ask_form import skill_facts_already_collected

                    if skill_facts_already_collected(message, history, form_reply):
                        openai_tools = [
                            t
                            for t in openai_tools
                            if (t.get("function") or {}).get("name") != "ask_user"
                        ]
                    turn_tools = openai_tools
                terminal_state = self.tools.terminal_availability(
                    openai_tools, use_tools=use_tools
                )
                if terminal_state != last_terminal_state:
                    logger.info("EVA_TERMINAL_STATE session=%s state=%s", session_id, terminal_state)
                    last_terminal_state = terminal_state
                self._emit_progress(
                    on_progress,
                    {
                        "type": "phase",
                        "phase": "thinking",
                        "label": "思考中",
                        "round": round_i,
                    },
                )
                result = await self._llm_chat_fit(
                    messages,
                    tools=openai_tools if use_tools else None,
                    model=None if escalate_state.get("used") else model,
                    llm=turn_llm,
                    deputy_llm=None if escalate_state.get("used") else deputy_client,
                    escalate_state=escalate_state,
                )
                if escalate_state.get("used") and not used_deputy and deputy_client:
                    used_deputy = True
                    deputy_reason = str(escalate_state.get("reason") or "hard_fail")
                    turn_llm = deputy_client
                    tight_ctx = self._is_tight_ctx_llm(turn_llm)
                used_model = result.get("model") or used_model
                for k in total_usage:
                    total_usage[k] += int(result.get("usage", {}).get(k, 0) or 0)

                tool_calls = result.get("tool_calls")
                content = result.get("content") or ""
                for p in result.get("media_paths") or []:
                    if isinstance(p, str) and p and p not in cli_media_paths:
                        cli_media_paths.append(p)

                if tool_calls and use_tools:
                    assistant_msg: dict[str, Any] = {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": tool_calls,
                    }
                    messages.append(assistant_msg)

                    office_files_seen = False
                    for tc in tool_calls:
                        fn = tc.get("function") or {}
                        name = fn.get("name", "")
                        raw_args = fn.get("arguments") or "{}"
                        try:
                            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        except json.JSONDecodeError:
                            args = {"raw": raw_args}
                            malformed_tools += 1
                            if (
                                malformed_tools >= 2
                                and deputy_client
                                and not used_deputy
                            ):
                                used_deputy = True
                                deputy_reason = "bad_tool_args"
                                turn_llm = deputy_client
                                escalate_state["used"] = True
                                escalate_state["reason"] = "bad_tool_args"
                                tight_ctx = self._is_tight_ctx_llm(turn_llm)
                                logger.warning(
                                    "Escalate to deputy: consecutive invalid tool JSON"
                                )
                                messages.append(
                                    {
                                        "role": "user",
                                        "content": (
                                            "[SYSTEM] 主模型连续给出无法解析的工具参数。"
                                            "本轮改由副模型继续；默认主模型不变。"
                                        ),
                                    }
                                )

                        _arg_hint = ""
                        if isinstance(args, dict):
                            for k in ("action", "name", "path", "query", "command"):
                                v = args.get(k)
                                if v:
                                    _arg_hint = f"{k}={str(v)[:60]}"
                                    break
                        logger.info(
                            "EVA_TOOL name=%s %s",
                            name,
                            _arg_hint,
                        )
                        logger.info("Tool call round=%s name=%s args=%s", round_i, name, _arg_hint or "{}")
                        _args_ui = (
                            {
                                k: (
                                    v
                                    if not isinstance(v, str) or len(v) <= 80
                                    else v[:80] + "…"
                                )
                                for k, v in (args.items() if isinstance(args, dict) else [])
                            }
                            if isinstance(args, dict)
                            else {}
                        )
                        self._emit_progress(
                            on_progress,
                            {
                                "type": "tool_start",
                                "name": name,
                                "arguments": _args_ui,
                                "label": self._tool_progress_label(name),
                                "detail": _arg_hint or None,
                                "round": round_i,
                            },
                        )
                        if (
                            allow_deputy
                            and deputy_client
                            and not used_deputy
                            and not skip_deputy
                            and is_skill_work_tool(name, self.tools)
                        ):
                            used_deputy = True
                            deputy_reason = "skill_call"
                            turn_llm = deputy_client
                            escalate_state["used"] = True
                            escalate_state["reason"] = "skill_call"
                            tight_ctx = self._is_tight_ctx_llm(turn_llm)
                            logger.info(
                                "Escalate to deputy: skill tool %s",
                                name,
                            )
                        tool_result = await self.tools.execute(name, args)
                        _ok_tool = True
                        try:
                            _pj = json.loads(tool_result) if isinstance(tool_result, str) else None
                            if isinstance(_pj, dict) and (
                                _pj.get("ok") is False or _pj.get("error")
                            ):
                                _ok_tool = False
                        except Exception:
                            pass
                        if name == "terminal":
                            logger.info(
                                "EVA_TERMINAL_RESULT session=%s state=%s",
                                session_id, "tool_error" if not _ok_tool else "returned",
                            )
                        self._emit_progress(
                            on_progress,
                            {
                                "type": "tool_end",
                                "name": name,
                                "ok": _ok_tool,
                                "result": self._summarize_tool_result_for_ui(
                                    name, tool_result
                                ),
                                "label": self._tool_progress_label(name),
                                "round": round_i,
                            },
                        )
                        llm_tool_content = self._clip_tool_result_for_llm(
                            name,
                            tool_result,
                            tight=self._is_tight_ctx_llm(turn_llm),
                        )
                        try:
                            from app.services.integrations_meta import (
                                missing_integration_from_result,
                            )
                            from app.agent.ask_form import integration_needed_form

                            miss = missing_integration_from_result(name, tool_result)
                            if miss:
                                miss["pending_user"] = message
                                llm_tool_content = json.dumps(
                                    {
                                        "ok": False,
                                        "error": "integration_missing",
                                        "tell_user": miss["tell_user"],
                                        "integration_id": miss["integration_id"],
                                        "hint": "已经弹出填写表单。请用户在气泡里填，不要把密钥写进回复。",
                                    },
                                    ensure_ascii=False,
                                )
                                if not pending_form:
                                    pending_form = integration_needed_form(miss)
                        except Exception:
                            logger.exception("missing-integration hint failed")
                        if name in ("process_control", "terminal") and not pending_form:
                            # Kill confirmation card (inform → user decides next turn).
                            try:
                                _pj = json.loads(tool_result) if isinstance(tool_result, str) else {}
                                _f = _pj.get("form") if isinstance(_pj, dict) else None
                                if isinstance(_f, dict) and _f.get("purpose") == "kill_confirm":
                                    pending_form = _f
                            except Exception:
                                pass
                        if name == "ask_user":
                            try:
                                from app.agent.ask_form import (
                                    form_from_tool_payload,
                                    skill_facts_already_collected,
                                )

                                if skill_facts_already_collected(
                                    message, history, form_reply
                                ):
                                    llm_tool_content = json.dumps(
                                        {
                                            "ok": False,
                                            "error": "already_have_facts",
                                            "hint": "用户已提供用途/地址。不要再问。立刻 create_tool(spec_confirmed=true)。",
                                        },
                                        ensure_ascii=False,
                                    )
                                else:
                                    parsed_form = form_from_tool_payload(
                                        args if isinstance(args, dict) else {},
                                        tool_result,
                                    )
                                    if parsed_form:
                                        pending_form = parsed_form
                            except Exception:
                                logger.exception("Parse ask_user form failed")
                        if name == "create_tool":
                            await self._note_create_tool_result(
                                tool_result,
                                session_id=session_id,
                                intent_force=intent_force,
                            )
                        elif name == "workspace" and self._text_has_office_files(tool_result):
                            office_files_seen = True
                        # Sticky: any successful skill-dev tool keeps meta tools open
                        if name in {
                            "create_tool",
                            "delete_tool",
                            "read_skill",
                            "list_skills",
                            "validate_skill",
                            "promote_skill",
                        }:
                            try:
                                from app.services.skill_lifecycle import (
                                    persist_sticky_meta_tools,
                                )

                                sticky_add = {
                                    name,
                                    "read_skill",
                                    "list_skills",
                                    "validate_skill",
                                }
                                if name in (
                                    "create_tool",
                                    "promote_skill",
                                    "delete_tool",
                                ):
                                    sticky_add |= {
                                        "create_tool",
                                        "delete_tool",
                                        "promote_skill",
                                    }
                                await persist_sticky_meta_tools(
                                    session_id,
                                    sticky_add,
                                    sessions=self.sessions,
                                )
                                intent_force |= sticky_add
                            except Exception:
                                logger.exception("sticky after skill tool failed")
                        tool_records.append(
                            ToolCallRecord(
                                id=tc.get("id", ""),
                                name=name,
                                arguments=args if isinstance(args, dict) else {"raw": args},
                                result=tool_result[:4000],
                            )
                        )
                        # Feed paths back into next-round tool filter
                        for p in extract_paths_from_tool_result(tool_result):
                            if p not in path_hints:
                                path_hints.append(p)
                        # Also harvest from args (path/filename fields)
                        if isinstance(args, dict):
                            for k in ("path", "source", "dest", "filename", "script_path"):
                                v = args.get(k)
                                if isinstance(v, str) and v.strip() and v not in path_hints:
                                    path_hints.append(v.strip().replace("\\", "/"))
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.get("id", ""),
                                "content": llm_tool_content,
                            }
                        )
                    if (
                        office_files_seen
                        and not office_nudge_sent
                        and not pending_form
                    ):
                        from app.tools.lookup import first_in_group, has_group

                        office_nudge_sent = True
                        if has_group("office"):
                            intent_force.add(first_in_group("office") or "document")
                            messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        "[SYSTEM] 工作区里已有 docx/xlsx/pptx/pdf/md。"
                                        "请用 document 读取或编辑，不要再列目录，也不要 create_tool。"
                                    ),
                                }
                            )
                        else:
                            intent_force |= {
                                "create_tool",
                                "list_skills",
                                "read_skill",
                                "validate_skill",
                            }
                            messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        "[SYSTEM] 工作区里已有 docx/xlsx/pptx/pdf，"
                                        "但没有能读取这类文件的技能。"
                                        "停止继续列子目录。立刻出示规格卡并 "
                                        "create_tool(spec_confirmed=true, "
                                        "stage=live)，成功后读取这些文件完成任务。"
                                    ),
                                }
                            )
                    round_i += 1
                    if not pending_form:
                        continue

                # --- Hard intercepts when model tries to finish without required tools ---
                if use_tools and forced_retries < max_forced_retries and not pending_form:
                    called = {t.name for t in tool_records}

                    # Durable persist: ANY of primary destinations is enough
                    if durable_plan and durable_plan.require_any_of:
                        need_set = set(durable_plan.require_any_of)
                        if not (called & need_set):
                            forced_retries += 1
                            primary = durable_plan.primary
                            intent_force |= set(durable_plan.force_tools)
                            logger.info(
                                "Force durable persist: primary=%s need_any=%s called=%s",
                                primary,
                                need_set,
                                called,
                            )
                            messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        f"[SYSTEM] Hard rule: this turn must PERSIST knowledge via "
                                        f"`{primary}` (op={durable_plan.op}) but you did not call it. "
                                        f"{durable_plan.hint} "
                                        f"Do not only claim you saved/remembered."
                                    ),
                                }
                            )
                            round_i += 1
                            continue

                    missing_req = required_tools - called
                    if missing_req:
                        forced_retries += 1
                        need = ", ".join(sorted(missing_req))
                        logger.info(
                            "Force tool retry: required=%s called=%s", missing_req, called
                        )
                        # Ensure required tools are force-included next round
                        intent_force |= missing_req
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    f"[SYSTEM] Hard rule: this turn requires tool(s) [{need}] "
                                    f"but you did not call them. "
                                    f"You MUST call `{next(iter(sorted(missing_req)))}` now. "
                                    f"Do not only claim you finished."
                                ),
                            }
                        )
                        round_i += 1
                        continue

                    if self._user_wants_file(message, content):
                        # P0: skip force if a file tool already ran this turn
                        if not (called & {"workspace", "document"}):
                            forced_retries += 1
                            office = self._text_has_office_files(message) or any(
                                k in (message or "").lower()
                                for k in (
                                    "excel",
                                    "xlsx",
                                    "xls",
                                    "docx",
                                    "pptx",
                                    "pdf",
                                    "word",
                                    "ppt",
                                    "powerpoint",
                                    "markdown",
                                    ".md",
                                )
                            )
                            if office:
                                intent_force |= {"document"}
                                must = (
                                    "[SYSTEM] You claimed to create/write an office file "
                                    "without a tool. MUST call document (action=write) now. "
                                    "Path under docs/ or exports/ or scratch/ — never workspace root. "
                                    "If the file already exists, ask_user first then overwrite=true."
                                )
                            else:
                                intent_force |= {"workspace"}
                                must = (
                                    "[SYSTEM] You claimed to create/write a file without a tool. "
                                    "MUST call workspace (action=write) now. "
                                    "Path under scratch/ or exports/ — never workspace root. "
                                    "If the file already exists, ask_user first then overwrite=true."
                                )
                            messages.append({"role": "user", "content": must})
                            round_i += 1
                            continue

                    if self._claimed_skill_created_without_tool(content, called):
                        forced_retries += 1
                        intent_force |= {
                            "create_tool",
                            "list_skills",
                            "read_skill",
                            "validate_skill",
                        }
                        logger.info("Force create_tool: model claimed skill live without calling it")
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "[SYSTEM] 你声称技能已创建/上线，但本轮没有成功调用 create_tool。"
                                    "立刻调用 create_tool(spec_confirmed=true, "
                                    "user_confirmation=用户原话, spec_json=完整规格, stage=live)。"
                                    "禁止再向用户索要「创建技能」口令。"
                                    "创建成功后马上用新技能执行用户任务"
                                    "（如读取已上传的 docx/xlsx/pptx/pdf），不要只写交付总结。"
                                ),
                            }
                        )
                        round_i += 1
                        continue

                    if spec_confirmed_this_turn and "create_tool" not in called:
                        forced_retries += 1
                        intent_force |= {
                            "create_tool",
                            "list_skills",
                            "read_skill",
                            "validate_skill",
                        }
                        logger.info("Force create_tool after spec confirmation")
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "[SYSTEM] 用户已确认规格卡。必须立刻调用 create_tool"
                                    "(spec_confirmed=true, user_confirmation=用户原话, "
                                    "spec_json=完整规格, stage=live)。"
                                    "不要先列目录，不要再问「要开始吗」。"
                                    "创建成功后继续执行原任务。"
                                ),
                            }
                        )
                        round_i += 1
                        continue

                self._emit_progress(
                    on_progress,
                    {
                        "type": "phase",
                        "phase": "writing",
                        "label": "生成回复",
                        "round": round_i,
                    },
                )
                final_content = content
                if pending_form:
                    if pending_form.get("kind") == "integ":
                        title = str(pending_form.get("title") or "").strip()
                        prompt = str(pending_form.get("prompt") or "").strip()
                        final_content = title or prompt or "还没配好"
                    elif not (final_content or "").strip():
                        final_content = (
                            str(pending_form.get("prompt") or "").strip()
                            or str(pending_form.get("title") or "").strip()
                            or "请在下方补充后提交。"
                        )
                    if (final_content or "").strip():
                        messages.append({"role": "assistant", "content": final_content})
                    break
                if use_tools and self._asks_user_to_continue(final_content):
                    from app.agent.ask_form import maybe_quiz_form

                    qform = maybe_quiz_form(final_content, pending_user=message)
                    if qform:
                        pending_form = qform
                        messages.append(
                            {"role": "assistant", "content": final_content}
                        )
                        break
                    logger.info("Model asked user to continue; auto-advancing phase")
                    final_content = ""
                    from app.tools.lookup import has_group

                    if office_files_seen and not has_group("office"):
                        intent_force |= {
                            "create_tool",
                            "list_skills",
                            "read_skill",
                            "validate_skill",
                        }
                    break
                if final_content.strip():
                    messages.append({"role": "assistant", "content": final_content})
                    break
                break

            if pending_form or (final_content or "").strip():
                if (
                    not pending_form
                    and (final_content or "").strip()
                ):
                    from app.agent.ask_form import maybe_quiz_form

                    qform = maybe_quiz_form(final_content, pending_user=message)
                    if qform:
                        pending_form = qform
                break

            called_now = {t.name for t in tool_records}
            if (
                allow_deputy
                and deputy_client
                and not used_deputy
                and required_tools
                and (required_tools - called_now)
            ):
                used_deputy = True
                deputy_reason = "required_tools_missed"
                turn_llm = deputy_client
                escalate_state["used"] = True
                escalate_state["reason"] = "required_tools_missed"
                tight_ctx = self._is_tight_ctx_llm(turn_llm)
                logger.warning(
                    "Escalate to deputy: required tools still missing %s",
                    required_tools - called_now,
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "[SYSTEM] 主模型未完成必要工具调用。"
                            "本轮改由副模型继续；默认主模型不变。"
                            f"仍需调用：{', '.join(sorted(required_tools - called_now))}。"
                        ),
                    }
                )
                phase += 1
                phase_start = round_i
                near_limit_nudge_sent = False
                continue

            if use_tools and tool_records and auto_continued < max_phases - 1:
                auto_continued += 1
                phase += 1
                phase_start = round_i
                near_limit_nudge_sent = False
                digest = self._tool_progress_digest(tool_records)
                logger.info(
                    "Auto phase %s after tool budget: used=%s cap=%s tools=%s",
                    phase + 1,
                    round_i,
                    max_rounds,
                    len(tool_records),
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"[SYSTEM] 阶段 {phase} 的 {max_rounds} 轮工具额度已用完，"
                            "系统已自动进入下一阶段（不要问用户是否继续）。\n"
                            f"已操作：{digest}\n"
                            "请先复述上面已完成的要点，再继续执行剩余步骤。"
                            "不要创建或改写技能，除非本轮用户明确要求。"
                            "Word/Excel/PPT/PDF/Markdown 用 document。"
                            "仍需工具就调用，全部完成后给出最终答复。"
                        ),
                    }
                )
                continue

            created = any(
                (t.name == "create_tool")
                and ("\"ok\": true" in (t.result or "").lower() or '"ok":true' in (t.result or "").lower())
                for t in tool_records
            )
            if (
                not pending_form
                and not created
                and should_offer_skill_form(
                    message, intent_force, history, form_reply=form_reply
                )
            ):
                from app.agent.ask_form import skill_intake_form as _skill_form

                pending_form = _skill_form(message)
                final_content = str(pending_form.get("title") or "请在下方填写")
            else:
                self._emit_progress(
                    on_progress,
                    {
                        "type": "phase",
                        "phase": "writing",
                        "label": "整理结果",
                    },
                )
                from app.llm.routing import routed_client as _route

                _fin = _route("tool_final", fallback=None, allow_cli=False, use_default=False)
                final_content = await self._synthesize_after_tool_cap(
                    messages,
                    tool_records=tool_records,
                    max_rounds=max_rounds,
                    model=None if (used_deputy or _fin is not None) else model,
                    total_usage=total_usage,
                    llm=_fin or turn_llm,
                )
            if final_content:
                messages.append({"role": "assistant", "content": final_content})
            break

        # 工具结果里的本地媒体：写入回复正文，前端气泡可直接预览（历史会话也能看到）
        media_paths = self._collect_media_paths(tool_records)
        for p in cli_media_paths:
            if p and p not in media_paths:
                media_paths.append(p)
        final_content = self._strip_visible_tool_digest(final_content)
        final_content = self._ensure_media_in_reply(final_content, media_paths)

        llm_meta: dict[str, Any] = {}
        if used_deputy:
            llm_meta = {
                "used_deputy": True,
                "llm_name": deputy_label(deputy_row),
                "deputy_reason": deputy_reason or "hard_fail",
            }
        if pending_form:
            if not str(pending_form.get("id") or "").strip():
                try:
                    from app.agent.ask_form import new_form_id

                    pending_form["id"] = new_form_id()  # 每张表单一个问题 id：前端回传，过期回复不会套到新问题上
                except Exception:
                    pass
            llm_meta["form"] = pending_form

        # Persist user + final assistant (and compact tool summary if any)
        to_save: list[dict[str, Any]] = [user_msg]
        if tool_records:
            summary = "; ".join(f"{t.name}()" for t in tool_records)
            # 紧凑工具记录：名称 + 参数键 + 媒体路径（供前端画廊）
            compact_calls = []
            for t in tool_records:
                t_name = (t.name or "").strip()
                # 列表/分析工具不把路径记为可预览媒体，避免助手气泡刷 uploads
                from app.tools.lookup import tool_group as _tool_group

                if t_name in self._LIST_LIKE_TOOLS or _tool_group(t_name) in self._INPUT_ONLY_GROUPS:
                    paths: list[str] = []
                else:
                    paths = self._extract_media_paths_from_text(
                        t.result or "",
                        structured_only=True,
                        allow_list_fields=False,
                    )
                    paths = [p for p in paths if not self._is_upload_path(p)]
                from app.agent.context_continuity import (
                    clip_tool_result_for_storage,
                    redact_sensitive_tool_text,
                    redact_tool_args,
                )

                safe_result = redact_sensitive_tool_text(t.result or "")
                compact_calls.append(
                    {
                        "name": t.name,
                        "arguments": redact_tool_args(
                            t.arguments if isinstance(t.arguments, dict) else {},
                            max_str=80,
                        ),
                        "media_paths": paths,
                        # UI keeps a short redacted summary; result_llm is for next-turn context.
                        "result": self._summarize_tool_result_for_ui(
                            t.name, safe_result
                        ),
                        "result_llm": clip_tool_result_for_storage(
                            t.name, safe_result, limit=2000
                        ),
                    }
                )
            to_save.append(
                {
                    "role": "assistant",
                    "content": final_content,
                    "metadata": {
                        "tools_used": summary,
                        "tool_calls": compact_calls,
                        "media_paths": media_paths,
                        **llm_meta,
                    },
                }
            )
        else:
            asst_save: dict[str, Any] = {"role": "assistant", "content": final_content}
            meta = dict(llm_meta)
            if media_paths:
                meta["media_paths"] = media_paths
            if meta:
                asst_save["metadata"] = meta
            to_save.append(asst_save)

        await self.sessions.append_messages(
            session_id,
            to_save,
            title=suggest_session_title(message),
            max_history=max_history,
        )
        try:
            from app.agent.context_continuity import build_task_state

            prev_ts = ((session_full or {}).get("metadata") or {}).get("task_state")
            new_ts = build_task_state(
                prev=prev_ts if isinstance(prev_ts, dict) else {},
                user_message=message,
                assistant=final_content,
                tool_records=tool_records,
                paths=list(media_paths or []) + list(path_hints or []),
                is_followup=self._is_followup_deixis(message),
            )
            await self.sessions.update_metadata(
                session_id, {"task_state": new_ts}, merge=True
            )
        except Exception:
            logger.exception("Update session task_state failed")
        try:
            from app.services.skill_spec import has_spec_card
            from app.services.skill_lifecycle import persist_pending_skill_create

            if has_spec_card(final_content) and "create_tool" not in {
                t.name for t in tool_records
            }:
                await persist_pending_skill_create(
                    session_id,
                    reason="spec_card",
                    sessions=self.sessions,
                )
        except Exception:
            logger.exception("persist pending skill after spec card failed")

        # Auto evolution: compress older turns when threshold reached
        try:
            await self._maybe_evolve_session(
                session_id,
                agent_cfg=agent_cfg,
                latest_user=message,
                latest_assistant=final_content,
                model=model,
            )
        except Exception:
            logger.exception("Session evolution step failed")

        return ChatResponse(
            session_id=session_id,
            reply=final_content,
            model=used_model,
            tool_calls=tool_records,
            usage=total_usage,
            used_deputy=used_deputy,
            llm_name=deputy_label(deputy_row) if used_deputy else None,
            deputy_reason=deputy_reason,
            form=pending_form,
            media_paths=media_paths,
        )

    async def _maybe_evolve_session(
        self,
        session_id: str,
        *,
        agent_cfg: dict[str, Any],
        latest_user: str,
        latest_assistant: str,
        model: str | None = None,
    ) -> None:
        from app.agent.evolution import (
            evolve_session_context,
            evolution_settings,
            should_evolve,
        )

        settings = evolution_settings(agent_cfg)
        if not settings.get("enabled"):
            return
        data = await self.sessions.get(session_id)
        if not data:
            return
        messages = list(data.get("messages") or [])
        evo = data.get("evolution") if isinstance(data.get("evolution"), dict) else {}
        if not should_evolve(
            message_count=len(messages),
            evolution=evo,
            settings=settings,
        ):
            return

        keep = int(settings.get("keep_messages") or 16)
        # Compress everything except the recent tail
        if len(messages) <= keep + 2:
            older = messages[:-2] if len(messages) > 2 else messages
        else:
            older = messages[: -keep]

        logger.info(
            "Evolving session %s: msgs=%s keep=%s trigger=%s",
            session_id,
            len(messages),
            keep,
            settings.get("trigger_messages"),
        )
        from app.llm.routing import routed_client as _route

        evo_llm = _route("evolution", fallback=None)  # rule or routing default
        new_evo = await evolve_session_context(
            llm=evo_llm or self.llm,
            previous=evo,
            messages_to_compress=older,
            latest_user=latest_user,
            latest_assistant=latest_assistant,
            settings=settings,
            model=None if evo_llm is not None else model,
        )
        await self.sessions.set_evolution(
            session_id,
            new_evo,
            trim_to=keep,
        )

    @staticmethod
    def _is_followup_deixis(message: str) -> bool:
        """Short/vague follow-up that likely refers to the previous task."""
        t = (message or "").strip()
        if not t:
            return False
        keys = (
            "继续",
            "再来",
            "再做",
            "再跑",
            "同样",
            "一样",
            "那个",
            "这个也",
            "还是",
            "搞一下",
            "弄一下",
            "改一下",
            "再处理",
            "同上",
            "刚才",
            "跟上次",
        )
        if any(k in t for k in keys):
            return True
        # Very short ack/continue without a new topic
        compact = "".join(t.split())
        return len(compact) <= 6 and any(
            k in compact for k in ("好", "行", "嗯", "继续", "再", "那个")
        )

    def _tool_budget_instruction(self, max_rounds: int) -> str:
        n = max(1, int(max_rounds or 8))
        return (
            f"TOOL BUDGET: ≤{n} tool rounds per phase; runtime auto-continues — "
            "do not ask 是否继续. Don't recursively list folders. "
            ".docx .xlsx .pptx .pdf .md → tool document (path under docs/exports/scratch)."
        )

    def _ops_instructions(
        self,
        *,
        use_tools: bool,
        max_rounds: int,
        image_only: bool,
        include_media: bool,
        include_credentials: bool,
        include_llm_catalog: bool,
        include_skilldev_routing: bool,
    ) -> list[str]:
        parts = [GROUNDING_INSTRUCTION, MEMORY_INSTRUCTION]
        if not image_only:
            parts.append(KB_INSTRUCTION)
            parts.append(GROUNDING_STACK)
        if include_credentials:
            parts.append(INTEGRATION_INSTRUCTION)
        if use_tools:
            parts.append(WORKFLOW_INSTRUCTION)
        if include_media:
            parts.append(MEDIA_INSTRUCTION)
        if use_tools:
            parts.append(self._tool_budget_instruction(max_rounds))
        try:
            from app.tools.tool_meta import (
                llm_catalog_instruction,
                routing_instruction_core,
                routing_instruction_skilldev,
            )

            if use_tools:
                parts.append(routing_instruction_core())
            if include_skilldev_routing:
                parts.append(routing_instruction_skilldev())
            if include_llm_catalog:
                parts.append(llm_catalog_instruction())
        except Exception:
            pass
        return parts

    @staticmethod
    def _message_needs_media(message: str, *, has_imgs: bool) -> bool:
        if has_imgs:
            return True
        t = (message or "").lower()
        return any(
            k in t
            for k in (
                "图片",
                "识图",
                "生图",
                "视频",
                "image",
                "video",
                "截图",
                "预览",
                "uploads/",
            )
        )

    @staticmethod
    def _message_needs_credentials(
        message: str, intent_force: set[str], meta: set[str] | list[str]
    ) -> bool:
        if meta:
            return True
        if intent_force & {"integrations", "llms", "create_tool"}:
            return True
        t = (message or "").lower()
        return any(
            k in t
            for k in (
                "集成",
                "ssh",
                "api_key",
                "api key",
                "base_url",
                "主机密码",
                "连接配置",
            )
        )

    @staticmethod
    def _message_needs_llm_catalog(
        message: str, intent_force: set[str], meta: set[str] | list[str]
    ) -> bool:
        if meta:
            return True
        if "llms" in intent_force:
            return True
        t = (message or "").lower()
        return any(
            k in t
            for k in (
                "模型",
                "llm",
                "huggingface",
                "部署",
                "deepseek",
                "openai",
                "grok",
                "ollama",
            )
        )

    @staticmethod
    def _merge_turn_tools(
        frozen: list[dict[str, Any]] | None,
        fresh: list[dict[str, Any]],
        intent_force: set[str],
    ) -> list[dict[str, Any]]:
        """Keep first-round tool schemas; union newly forced tools later in the turn."""
        if not frozen:
            return list(fresh)
        have = {
            str((t.get("function") or {}).get("name") or "")
            for t in frozen
        }
        out = list(frozen)
        for t in fresh:
            name = str((t.get("function") or {}).get("name") or "")
            if name and name not in have and name in intent_force:
                out.append(t)
                have.add(name)
        return out

    def _is_tight_ctx_llm(self, llm: LLMClient | None = None) -> bool:
        """Local GGUF / llama.cpp windows (8K–16K) cannot take cloud-sized prompts."""
        client = llm or self.llm
        model = (getattr(client, "model", "") or "").lower()
        url = (getattr(client, "base_url", "") or "").lower()
        if ".gguf" in model or "llama.cpp" in model or "llamacpp" in model:
            return True
        if getattr(client, "use_proxy", False):
            return False
        return any(
            x in url
            for x in (":8080", ":8081", "127.0.0.1", "localhost", "10.11.", "192.168.")
        )

    @staticmethod
    def _is_context_overflow(exc: BaseException) -> bool:
        t = str(exc or "").lower()
        return "exceed" in t and "context" in t

    async def _llm_chat_fit(
        self,
        messages,
        *,
        tools,
        model,
        llm: LLMClient | None = None,
        deputy_llm: LLMClient | None = None,
        escalate_state: dict[str, Any] | None = None,
    ):
        from app.agent.deputy import is_hard_llm_failure

        client = llm or self.llm
        try:
            return await client.chat(messages, tools=tools, model=model)
        except Exception as exc:
            overflow = self._is_context_overflow(exc)
            if overflow:
                try:
                    logger.warning("LLM context overflow; retrying with trimmed prompt")
                    compact = self._shrink_messages_for_ctx(messages)
                    return await client.chat(compact, tools=tools, model=model)
                except Exception as exc2:
                    exc = exc2
                    overflow = self._is_context_overflow(exc2)
            can_escalate = (
                deputy_llm is not None
                and escalate_state is not None
                and not escalate_state.get("used")
                and (overflow or is_hard_llm_failure(exc))
            )
            if not can_escalate:
                raise
            reason = "context_overflow" if overflow else "llm_error"
            escalate_state["used"] = True
            escalate_state["reason"] = reason
            logger.warning("Escalate to deputy (%s): %s", reason, exc)
            # Deputy usually has a wider window — send the original prompt, not the shrink.
            return await deputy_llm.chat(messages, tools=tools)

    @staticmethod
    def _shrink_messages_for_ctx(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep system + last few turns; clip long tool/assistant blobs."""
        if not messages:
            return messages
        sys_msgs = [m for m in messages if m.get("role") == "system"]
        rest = [m for m in messages if m.get("role") != "system"]
        keep = rest[-8:] if len(rest) > 8 else rest

        def _clip(m: dict[str, Any], cap: int) -> dict[str, Any]:
            out = dict(m)
            c = out.get("content")
            if isinstance(c, str) and len(c) > cap:
                out["content"] = c[:cap] + "\n…[trimmed for context]"
            return out

        packed = [_clip(m, 1600) for m in sys_msgs[:1]]
        packed.extend(_clip(m, 900) for m in keep)
        return packed

    @staticmethod
    def _emit_progress(
        on_progress: Callable[[dict[str, Any]], None] | None,
        event: dict[str, Any],
    ) -> None:
        if not on_progress:
            return
        try:
            on_progress(event)
        except Exception:
            logger.debug("on_progress failed", exc_info=True)

    @staticmethod
    def _tool_progress_label(name: str) -> str:
        labels = {
            "kb": "查知识库",
            "memory": "读写记忆",
            "workspace": "读写工作区",
            "workflow": "跑工作流",
            "integrations": "读集成配置",
            "llms": "查看对话模型",
            "list_skills": "列出技能",
            "validate_skill": "校验技能",
            "promote_skill": "发布技能",
            "web_search": "搜索网页",
            "create_tool": "创建技能",
            "read_skill": "读技能代码",
            "delete_tool": "删除技能",
            "terminal": "执行终端命令",
            "document": "读写办公文档",
            "reload_runtime": "热重载",
            "list_api_models": "拉取模型列表",
            "server_health_check": "健康检查",
            "scheduled_task": "查看定时任务",
            "get_current_time": "读取当前时间",
            "ask_user": "向你确认",
        }
        n = (name or "").strip()
        if n in labels:
            return labels[n]
        nice = n.replace("_", " ") if n else "工具"
        return f"调用 {nice}"

    @staticmethod
    def _summarize_tool_result_for_ui(name: str, text: str) -> str:
        raw = (text if isinstance(text, str) else str(text or "")).strip()
        if not raw:
            return ""
        if name in ("read_skill", "validate_skill") or "def register" in raw[:800]:
            try:
                j = json.loads(raw)
                if isinstance(j, dict):
                    if j.get("error"):
                        return f"error: {str(j.get('error'))[:160]}"
                    sid = j.get("id") or j.get("name") or name
                    return f"ok {sid}"
            except Exception:
                pass
            return "ok（源码已省略，不在对话展示）"
        compact = re.sub(r"\s+", " ", raw)
        return compact[:200] + ("…" if len(compact) > 200 else "")

    @staticmethod
    def _clip_tool_result_for_llm(
        name: str, text: str, *, tight: bool = False
    ) -> str:
        raw = text if isinstance(text, str) else str(text or "")
        try:
            from app.tools.lookup import tool_group

            group = tool_group(name)
        except Exception:
            group = ""
        if name in _SOURCE_TOOL_RESULT:
            limit = 1800 if tight else 2800
        elif tight or group in _TIGHT_TOOL_GROUPS:
            limit = _TOOL_RESULT_LLM_CHARS_TIGHT
        elif name in _WIDE_TOOL_RESULT or group in _WIDE_TOOL_GROUPS:
            limit = _TOOL_RESULT_LLM_CHARS_WIDE
        else:
            limit = _TOOL_RESULT_LLM_CHARS
        if len(raw) <= limit:
            return raw
        return (
            raw[:limit]
            + f"\n…[truncated {len(raw) - limit} chars; "
            "call again with a narrower query/limit if you need the rest]"
        )

    @staticmethod
    def _asks_user_to_continue(text: str) -> bool:
        t = (text or "").strip()
        if not t:
            return False
        keys = (
            "是否继续",
            "要不要继续",
            "需要我继续",
            "需要您回复",
            "回复「继续」",
            "回复继续",
            "请回复继续",
            "输入继续",
            "还需要我接着",
            "是否要我接着",
            "要我继续吗",
            "要开始吗",
            "请回复",
            "一句话解锁",
            "回复：「创建",
            "回复:「创建",
            "shall i continue",
            "want me to continue",
            "should i continue",
        )
        low = t.lower()
        return any(k in t or k in low for k in keys)

    @staticmethod
    def _strip_visible_tool_digest(text: str) -> str:
        """Drop tool digests and leaked DSML / special tool markup from replies."""
        t = (text or "").strip()
        if not t:
            return t
        try:
            from app.llm.tool_text import extract_dsml_tool_calls, looks_like_dsml

            if looks_like_dsml(t):
                t, _ = extract_dsml_tool_calls(t)
        except Exception:
            pass
        t = re.sub(
            r"^(?:已操作|已调用工具|已执行)[：:].*?(?:\n{1,2}|$)",
            "",
            t,
            count=1,
            flags=re.IGNORECASE,
        )
        return t.strip()

    @staticmethod
    def _tool_progress_digest(tool_records: list[ToolCallRecord], *, limit: int = 12) -> str:
        if not tool_records:
            return "（尚未调用工具）"
        bits: list[str] = []
        for i, t in enumerate(tool_records[-limit:], start=max(1, len(tool_records) - limit + 1)):
            name = (t.name or "?").strip() or "?"
            args = t.arguments if isinstance(t.arguments, dict) else {}
            hint = ""
            for k in ("path", "action", "query", "name", "id", "title"):
                v = args.get(k)
                if isinstance(v, str) and v.strip():
                    hint = v.strip()[:40]
                    break
            bits.append(f"{i}.{name}" + (f"({hint})" if hint else "()"))
        extra = f" 等共 {len(tool_records)} 次" if len(tool_records) > limit else ""
        return " → ".join(bits) + extra

    async def _synthesize_after_tool_cap(
        self,
        messages: list[dict[str, Any]],
        *,
        tool_records: list[ToolCallRecord],
        max_rounds: int,
        model: str | None,
        total_usage: dict[str, int],
        llm: LLMClient | None = None,
    ) -> str:
        """When tool rounds are exhausted, force a final text answer without tools.

        Keeps the in-turn tool context so the model can summarize progress instead of
        returning the old English cap stub that forced users to type 「继续」.
        """
        tool_names: list[str] = []
        for t in tool_records:
            n = (t.name or "").strip() or "?"
            if not tool_names or tool_names[-1] != n:
                tool_names.append(n)
            if len(tool_names) >= 24:
                break
        tools_hint = "、".join(tool_names) if tool_names else "（无）"

        messages.append(
            {
                "role": "user",
                "content": (
                    "[SYSTEM] 各阶段工具额度均已用完，禁止再调用任何工具。"
                    "请根据已执行的工具结果直接给出完整答复，不要罗列工具名或「已操作」清单。"
                    "不要询问用户是否继续。"
                    f"已调用工具：{tools_hint}。"
                ),
            }
        )
        try:
            result = await self._llm_chat_fit(
                messages, tools=None, model=model, llm=llm
            )
            for k in total_usage:
                total_usage[k] += int(result.get("usage", {}).get(k, 0) or 0)
            content = (result.get("content") or "").strip()
            # Ignore any residual tool_calls; tools are disabled for this pass
            if content:
                return content
        except Exception:
            logger.exception("Finalize after tool-round cap failed")

        if tool_records:
            summary = "；".join(f"{t.name}()" for t in tool_records[:20])
            if len(tool_records) > 20:
                summary += f" 等共 {len(tool_records)} 次"
            return (
                f"本轮工具调用已达配置上限（{max_rounds} 轮），未能自动生成完整结语。\n"
                f"已执行：{summary}。\n"
                "系统已按阶段自动续跑。若仍不完整，可在设定里提高「最大工具轮次」后重试。"
            )
        return (
            f"已达最大工具调用轮次（{max_rounds}），且未产生最终答复。"
            "请重试，或提高配置中的「最大工具轮次」。"
        )

    async def chat_stream(
        self,
        message: str,
        *,
        session_id: str | None = None,
        use_memory: bool = True,
        model: str | None = None,
        session_title: str | None = None,
    ) -> AsyncIterator[str]:
        """Simple streaming path without tool calls."""
        if not self.llm.is_configured:
            raise RuntimeError(self.llm.unconfigured_message())

        agent_cfg = self._agent_cfg()
        max_history = int(agent_cfg.get("max_history_messages") or self.settings.max_history_messages)
        from app.agent.persona import build_persona_prompt, use_compact_persona
        from app.tools.intent_routing import force_tools_from_text, is_image_only_turn

        image_only = is_image_only_turn(message)
        persona_prompt = build_persona_prompt(
            agent_cfg,
            compact=use_compact_persona(
                message,
                intent_force=force_tools_from_text(message),
                image_only=image_only,
                tools=self.tools,
            ),
            user_display_name=_resolve_user_display_name(),
        )

        title = (
            (session_title or "").strip()
            or suggest_session_title(message)
            or "对话"
        )[:80]
        if session_id:
            session = await self.sessions.get(session_id)
            if session is None:
                session = await self.sessions.create(title=title)
                session_id = session["session_id"]
        else:
            session = await self.sessions.create(title=title)
            session_id = session["session_id"]

        history = await self.sessions.get_messages(session_id, limit=max_history)
        filter_query = self._context_query(history, message, recent_user_turns=2)

        system_parts = [persona_prompt]
        system_parts.extend(
            self._ops_instructions(
                use_tools=False,
                max_rounds=1,
                image_only=image_only,
                include_media=self._message_needs_media(message, has_imgs=False),
                include_credentials=False,
                include_llm_catalog=False,
                include_skilldev_routing=False,
            )
        )
        try:
            from app.agent.evolution import evolution_settings, render_evolution_block

            es = evolution_settings(agent_cfg)
            sess = await self.sessions.get(session_id)
            evo_block = render_evolution_block(
                (sess or {}).get("evolution"),
                max_chars=int(es.get("max_chars") or 2200),
            )
            if evo_block:
                system_parts.append(evo_block)
            ts_block = None
            try:
                from app.agent.context_continuity import render_task_state_block

                ts_block = render_task_state_block(
                    ((sess or {}).get("metadata") or {}).get("task_state"),
                    max_chars=800,
                )
            except Exception:
                logger.exception("Load session task_state failed (stream)")
                ts_block = None
            if ts_block:
                system_parts.append(ts_block)
        except Exception:
            logger.exception("Load session evolution failed (stream)")
        retrieve_query = (filter_query or message).strip()
        kb_snip = ""
        kb_terms: list[str] = []
        if not image_only:
            try:
                from app.knowledge.store import get_knowledge_store

                kb_snip, kb_terms = await get_knowledge_store().context_for_prompt(
                    retrieve_query,
                    limit=4,
                    max_chars=3200,
                    intent_text=message,
                )
            except Exception:
                logger.exception("KB context snippet failed (stream)")
        if use_memory:
            snippet = await self.memory.context_snippet(
                retrieve_query,
                limit=5,
                max_chars=1800,
                max_pin=6,
                suppress_terms=kb_terms,
                session_id=session_id,
                working_limit=3,
            )
            if snippet:
                system_parts.append(snippet)
        if kb_snip:
            system_parts.append(KB_HIT_INSTRUCTION)
            system_parts.append(kb_snip)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "\n\n".join(system_parts)}
        ]
        from app.agent.context_continuity import history_messages_for_llm

        messages.extend(history_messages_for_llm(history, recent_tool_turns=2))
        messages.append({"role": "user", "content": message})

        parts: list[str] = []
        stream_llm = self.llm
        if not model:
            from app.llm.routing import routed_client as _route

            stream_llm = _route("chat.stream", fallback=self.llm) or self.llm
        async for delta in stream_llm.chat_stream(messages, model=model):
            parts.append(delta)
            yield delta

        full = "".join(parts)
        await self.sessions.append_messages(
            session_id,
            [
                {"role": "user", "content": message},
                {"role": "assistant", "content": full},
            ],
            title=suggest_session_title(message),
            max_history=max_history,
        )
        try:
            from app.agent.context_continuity import build_task_state

            sess_now = await self.sessions.get(session_id)
            prev_ts = ((sess_now or {}).get("metadata") or {}).get("task_state")
            new_ts = build_task_state(
                prev=prev_ts if isinstance(prev_ts, dict) else {},
                user_message=message,
                assistant=full,
                is_followup=self._is_followup_deixis(message),
            )
            await self.sessions.update_metadata(
                session_id, {"task_state": new_ts}, merge=True
            )
        except Exception:
            logger.exception("Update session task_state failed (stream)")
        try:
            await self._maybe_evolve_session(
                session_id,
                agent_cfg=agent_cfg,
                latest_user=message,
                latest_assistant=full,
                model=model,
            )
        except Exception:
            logger.exception("Session evolution step failed (stream)")
        # Final meta line as SSE comment-friendly payload handled by route
        yield f"\n\n[[session_id:{session_id}]]"

    @staticmethod
    def _agent_cfg() -> dict[str, Any]:
        try:
            from app.config_store import get_config_store

            return get_config_store().get_agent()
        except Exception:
            return {}

    _KILL_CANCEL_RE = re.compile(
        r"取消|算了|不要|不用|不同意|不行|不可以|别|不杀|不结束|不停|不关|\bcancel\b|\bno\b",
        re.I,
    )

    async def _handle_kill_confirm_reply(
        self,
        *,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
        form_reply: Any,
        max_history: int,
    ) -> ChatResponse | None:
        """Answer to a kill_confirm card (process_control / terminal stop).

        Card submit (choice=process|tree) or a short typed 同意 right after the
        card counts as explicit consent → kill server-side with the token stored
        for (session, pid); identity / expiry / session / hard-deny checks stay
        in process_control. choice=cancel / typed 取消 → revoke, no questions.
        Returns None when this turn is not such an answer.
        """
        import asyncio

        from app.agent.ask_form import (
            form_reply_is_stale,
            is_form_cancel,
            last_assistant_form,
            new_form_id,
        )

        typed = not isinstance(form_reply, dict)
        if typed:
            # typed answer: only right after the card (newest assistant message)
            form = last_assistant_form(history)
        else:
            form = last_assistant_form(history, any_age=True)
            if form_reply_is_stale(form, form_reply):
                return None  # generic stale handling below
        if not isinstance(form, dict) or form.get("purpose") != "kill_confirm":
            return None
        try:
            pid = int(form.get("kill_pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        if not pid:
            return None
        ctx = form.get("kill_ctx") if isinstance(form.get("kill_ctx"), dict) else {}
        force_scope = "tree" if ctx.get("scope") == "tree" else None

        from app.services import process_control as pc

        text = (message or "").strip()
        if typed:
            if not text or len(text) > 40:
                return None
            if self._KILL_CANCEL_RE.search(text):
                choice = "cancel"
            elif pc.user_consents(text):
                choice = pc._scope_from_message(text, "process")
            else:
                return None  # something else: let the model handle it
        else:
            choice = "cancel" if is_form_cancel(form_reply) else str(form_reply.get("choice") or "").strip().lower()
            if choice not in ("process", "tree", "cancel"):
                return None

        model_name = getattr(self.llm, "model", "") or ""
        form_id = str(form.get("id") or "")
        what = "停止" if ctx.get("tool") == "terminal" else "结束"
        new_form: dict[str, Any] | None = None
        kill_meta: dict[str, Any] = {"pid": pid, "choice": choice}

        if choice == "cancel":
            pc.revoke_session_tokens(session_id, pid)
            reply = f"好，已取消，没有{what}任何进程（PID {pid} 保持运行）。"
            kill_meta["result"] = "cancelled"
        else:
            blocked = False
            try:
                from app.tools.protection import is_action_blocked

                blocked = is_action_blocked("process_control", "kill")
            except Exception:
                blocked = False
            if blocked:
                res: dict[str, Any] = {
                    "ok": False,
                    "error": "结束进程在当前路径（定时任务/工作流/Webhook）被禁用。",
                }
            else:
                res = await asyncio.to_thread(
                    pc.kill_by_form_consent,
                    session_id,
                    pid,
                    choice,
                    force_scope=force_scope,
                    consent_text=text,
                )
            kill_meta["result"] = "killed" if res.get("killed") else "refused"
            kill_meta["detail"] = {
                k: res.get(k)
                for k in ("targets", "exited", "still_running", "forced", "graceful", "error", "scope")
                if k in res
            }
            if res.get("killed"):
                if ctx.get("job_id"):
                    try:
                        from app.services.terminal_exec import mark_job_killed

                        mark_job_killed(str(ctx["job_id"]))
                    except Exception:
                        logger.exception("mark_job_killed failed")
                targets = res.get("targets") or [pid]
                extra_n = len([t for t in targets if t != pid])
                how = (
                    "已温和退出"
                    if pid in (res.get("graceful") or [])
                    else "温和结束没有响应，已强制结束"
                )
                reply = (
                    f"已按你的确认{what} PID {pid}「{res.get('name') or form.get('title') or ''}」"
                    + (f"及 {extra_n} 个子进程" if extra_n else "")
                    + f"，{how}。"
                )
                still = [x for x in (res.get("still_running") or []) if x != pid]
                if still:
                    reply += f"仍有子进程未退出：{', '.join(map(str, still))}。"
                if res.get("note"):
                    reply += str(res["note"])
            elif res.get("need_requery") and not form.get("reissued"):
                # expired / lost after restart / tree grew: re-inform ONCE
                q = await asyncio.to_thread(pc.query, pid=pid)
                if isinstance(q.get("form"), dict):
                    new_form = q["form"]
                    if ctx.get("tool") == "terminal":
                        pc.tree_only_form(
                            new_form,
                            "后台任务" if ctx.get("job_id") else "服务",
                            {k: v for k, v in ctx.items() if k != "scope"},
                        )
                    new_form["reissued"] = True
                    new_form["id"] = new_form_id()
                    reply = (
                        f"{res.get('error') or '确认已失效'}"
                        "我已重新核对这个进程的信息，请在下面的新卡片里再确认一次（5 分钟内有效）。"
                    )
                else:
                    reply = (
                        f"{res.get('error') or '确认已失效'}重新核对时："
                        f"{q.get('tell_user') or q.get('error') or '进程已不存在'}，没有{what}任何进程。"
                    )
            elif res.get("need_requery"):
                reply = (
                    f"{res.get('error') or '确认已失效'}为避免反复确认，这次不再弹卡片；"
                    f"如果仍要{what}，请直接告诉我（例如「{what} PID {pid}」）。"
                )
            else:
                reply = f"没有{what} PID {pid}：{res.get('error') or '未知原因'}"

        meta: dict[str, Any] = {"kill_confirm": kill_meta}
        if new_form:
            meta["form"] = new_form
        else:
            meta["form_resolved"] = form_id or True
        user_text = text or ("取消" if choice == "cancel" else "同意")
        await self.sessions.append_messages(
            session_id,
            [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": reply, "metadata": meta},
            ],
            title=suggest_session_title(user_text),
            max_history=max_history,
        )
        return ChatResponse(session_id=session_id, reply=reply, model=model_name, form=new_form)

    @staticmethod
    def _sanitize_message(m: dict[str, Any], max_content: int = 0) -> dict[str, Any]:
        content = m.get("content")
        if max_content and isinstance(content, str) and len(content) > max_content:
            content = content[:max_content] + "…"
        out: dict[str, Any] = {"role": m.get("role", "user"), "content": content}
        if m.get("tool_calls"):
            out["tool_calls"] = m["tool_calls"]
        if m.get("tool_call_id"):
            out["tool_call_id"] = m["tool_call_id"]
        if m.get("name"):
            out["name"] = m["name"]
        return out



    @staticmethod
    def _claimed_skill_created_without_tool(reply: str, called: set[str]) -> bool:
        if "create_tool" in called:
            return False
        keys = (
            "已创建",
            "已上线",
            "创建成功",
            "创建并上线",
            "技能已完成",
            "已创建成功",
            "已创建并上线",
            "live 状态",
        )
        return any(k in (reply or "") for k in keys)

    @staticmethod
    def _text_has_office_files(text: str) -> bool:
        try:
            from app.services.skill_lifecycle import text_mentions_office_files

            return text_mentions_office_files(text)
        except Exception:
            low = (text or "").lower()
            return any(ext in low for ext in (".docx", ".xlsx", ".pptx", ".pdf", ".doc", ".xls"))

    async def _note_create_tool_result(
        self,
        tool_result: str,
        *,
        session_id: str,
        intent_force: set[str],
    ) -> None:
        """Keep new skill callable this turn; clear/set pending create state."""
        try:
            payload = json.loads(tool_result) if tool_result else {}
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            return
        try:
            from app.services.skill_lifecycle import (
                clear_pending_skill_create,
                persist_pending_skill_create,
            )
        except Exception:
            return
        if payload.get("ok") and payload.get("tool_name"):
            name = str(payload.get("tool_name") or "").strip()
            if name:
                intent_force.add(name)
            try:
                await clear_pending_skill_create(session_id, sessions=self.sessions)
            except Exception:
                logger.exception("clear pending skill after create_tool failed")
            return
        if payload.get("action_required") == "confirm_spec":
            try:
                await persist_pending_skill_create(
                    session_id,
                    name=str(payload.get("tool_name") or payload.get("name") or ""),
                    reason="confirm_spec",
                    sessions=self.sessions,
                )
            except Exception:
                logger.exception("persist pending skill after confirm_spec failed")

    @staticmethod
    def _user_wants_file(user_msg: str, assistant_reply: str) -> bool:
        """Detect hallucinated file creation claim (caller must skip if workspace/document already called)."""
        file_kw = ("excel", "xlsx", "xls", "docx", "pptx", "pdf", ".md",
                   "製作", "制作", "文件", "生成", "創建", "创建", "重新生成")
        reply_kw = ("已生成", "已重新生成", "搞掂", "搞掂",
                    "created", "generated", "done")
        msg_lower = user_msg.lower()
        if not any(kw in msg_lower for kw in file_kw):
            return False
        reply_lower = assistant_reply.lower()
        if any(kw in reply_lower for kw in reply_kw):
            return True
        if any(w in reply_lower for w in ["已成功", "successfully"]):
            return any(w in msg_lower for w in file_kw)
        return False

    _MEDIA_EXT = (
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
        ".mp4", ".webm", ".mov", ".m4v",
    )

    # 用户上传目录：只在用户气泡展示，不进助手回复 / 自动画廊
    _UPLOAD_PREFIXES = ("uploads/",)

    # 视为「新生成」输出的路径前缀（才自动贴到助手回复）
    _OUTPUT_PREFIXES = (
        "images/generated/",
        "images/output/",
        "generated/",
        "output/",
        "videos/",
        "exports/",
    )

    # 列表/搜索类工具：结果里的路径多为目录枚举，不能当生成媒体
    _LIST_LIKE_TOOLS = frozenset({
        "workspace",
    })

    # 纯读取/分析：参数里的图是输入，不是输出
    _INPUT_ONLY_GROUPS = frozenset({"vision"})

    @classmethod
    def _normalize_media_path(cls, p: str) -> str:
        p = (p or "").strip().strip("\"'`").replace("\\", "/")
        while "//" in p:
            p = p.replace("//", "/")
        while p.startswith("./"):
            p = p[2:]
        if p.lower().startswith("workspace/"):
            p = p[len("workspace/") :]
        p = p.lstrip("/")
        return p

    @classmethod
    def _is_upload_path(cls, p: str) -> bool:
        n = cls._normalize_media_path(p).lower()
        return n.startswith(cls._UPLOAD_PREFIXES) or "/uploads/" in f"/{n}"

    @classmethod
    def _is_output_media_path(cls, p: str) -> bool:
        """仅把明确生成目录下的媒体当作可自动预览的输出。"""
        n = cls._normalize_media_path(p).lower()
        if not n or cls._is_upload_path(n):
            return False
        return any(n.startswith(pref) for pref in cls._OUTPUT_PREFIXES)

    @classmethod
    def _extract_media_paths_from_text(
        cls,
        text: str,
        *,
        structured_only: bool = False,
        allow_list_fields: bool = True,
    ) -> list[str]:
        """从工具结果文本中提取 workspace 相对媒体路径。

        structured_only: 只信 JSON 输出字段 / markdown 图，不扫裸路径（避免 error 文案里的文件名）。
        allow_list_fields: 是否收录 files/paths 列表字段（列表工具应关掉）。
        """
        if not text or not str(text).strip():
            return []
        raw = str(text)
        found: list[str] = []

        def _add(p: str) -> None:
            p = cls._normalize_media_path(p)
            if not p or ".." in p.split("/"):
                return
            low = p.lower()
            if not any(low.endswith(ext) for ext in cls._MEDIA_EXT):
                return
            # 上传图永不作为「工具产出媒体」进入回复
            if cls._is_upload_path(p):
                return
            if p not in found:
                found.append(p)

        # JSON 结构化字段
        try:
            data = json.loads(raw)
        except Exception:
            data = None
        if isinstance(data, dict):
            # 错误结果不抽路径
            if data.get("error") and not any(
                data.get(k) for k in ("saved_paths", "output_path", "saved_path", "preview_markdown")
            ):
                return []

            output_keys = (
                "saved_paths",
                "media_paths",
                "output_paths",
            )
            list_keys = ("paths", "files") if allow_list_fields else ()
            for key in output_keys + list_keys:
                val = data.get(key)
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, str):
                            _add(item)
                        elif isinstance(item, dict):
                            for k in ("path", "file", "filename", "rel", "saved"):
                                if isinstance(item.get(k), str):
                                    _add(item[k])
                elif isinstance(val, str):
                    _add(val)
            for key in (
                "path",
                "file",
                "output_path",
                "saved_path",
                "video_path",
            ):
                if isinstance(data.get(key), str):
                    _add(data[key])
            # image_path / filename 多为输入参数回显，不收录
            md = data.get("preview_markdown")
            if isinstance(md, str):
                for m in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)\)", md):
                    _add(m.group(1))

        if not structured_only:
            # 裸路径（仅非 uploads）；markdown 图
            for m in re.finditer(
                r"(?:workspace[/\\])?([\w./\\-]+\.(?:png|jpe?g|gif|webp|bmp|svg|mp4|webm|mov|m4v))",
                raw,
                flags=re.I,
            ):
                _add(m.group(0))
            for m in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)\)", raw):
                _add(m.group(1))

        return found

    @classmethod
    def _collect_media_paths(cls, tool_records: list[ToolCallRecord]) -> list[str]:
        """收集应展示在助手侧的媒体：优先生成输出，排除 uploads 与列表/分析输入。"""
        out: list[str] = []
        for t in tool_records or []:
            name = (t.name or "").strip()
            from app.tools.lookup import tool_group as _tool_group

            if name in cls._LIST_LIKE_TOOLS or _tool_group(name) in cls._INPUT_ONLY_GROUPS:
                # 列表/分析：不把输入图或目录枚举贴进助手气泡
                continue
            # 生成类工具：只信结构化字段，避免误扫
            paths = cls._extract_media_paths_from_text(
                t.result or "",
                structured_only=True,
                allow_list_fields=False,
            )
            for p in paths:
                if cls._is_upload_path(p):
                    continue
                if p not in out:
                    out.append(p)
        # 二次收紧：若存在明确 generated 路径，只保留输出目录
        generated = [p for p in out if cls._is_output_media_path(p)]
        return generated if generated else out

    @classmethod
    def _ensure_media_in_reply(cls, reply: str, media_paths: list[str]) -> str:
        """若回复未包含「新生成」媒体路径，自动附上 Markdown，便于气泡预览。

        不附 uploads/ 用户上传图（用户气泡已有预览）。
        """
        if not media_paths:
            return reply or ""
        text = reply or ""
        # 去掉误贴的 uploads markdown（用户气泡已有预览）；生成图/视频要保留
        text = re.sub(
            r"!\[[^\]]*\]\((?:workspace/)?uploads/[^)\s]+\)\s*",
            "",
            text,
            flags=re.I,
        )
        text = re.sub(r"\n{3,}", "\n\n", text).rstrip()

        usable = [
            p
            for p in media_paths
            if p and not cls._is_upload_path(p) and p not in text
        ]
        # 优先只贴生成目录；若没有则贴非 upload 的工具输出
        prefer = [p for p in usable if cls._is_output_media_path(p)]
        missing = prefer if prefer else usable
        if not missing:
            return text
        lines = [f"![{Path(p).name}]({p})" for p in missing]
        block = "\n".join(lines)
        if text.strip():
            return text.rstrip() + "\n\n" + block
        return block
_agent: Agent | None = None


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = Agent()
    return _agent
