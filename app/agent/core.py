"""Agent core: LLM + tool loop + memory/session."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, AsyncIterator

from app.config import Settings, get_settings
from app.llm.client import LLMClient, get_llm_client
from app.memory.session import SessionStore, get_session_store
from app.memory.store import MemoryStore, get_memory_store
from app.models.schemas import ChatResponse, ToolCallRecord
from app.tools.registry import ToolRegistry, get_tool_registry

logger = logging.getLogger(__name__)

# Long-term memory instruction injected into system prompt
MEMORY_INSTRUCTION = (
    "You have a long-term memory system that persists across conversations "
    "(Memory panel / data/memory/long_term.json).\n"
    "IMPORTANT — injection is MATCH-BASED, not a full dump:\n"
    "- Only a few memories relevant to the current turn are injected (saves tokens as the store grows).\n"
    "- If something important is missing, call `memory` action=recall with a focused query.\n"
    "CRITICAL — DURABLE PERSIST (智能分发，禁止一律塞 memory):\n"
    "When user says 记住/记一下/保存/别忘了/写成知识库/做成工作流 — pick the right store:\n"
    "  · memory — 短偏好/习惯/规则/一句话事实（kind=preference|habit|rule|fact + tags）\n"
    "  · kb — 长结构：库表/字段/手册/SOP/清单/参数（create_page|update_page|append|delete）\n"
    "  · workflow — 可重复多步骤流程（action=create|update|delete）\n"
    "- NEVER only reply 「好的我记住了」 without a successful tool call to the chosen store.\n"
    "- Optional: after kb/workflow write, you MAY also memory.remember a 1-line index pointer.\n"
    "CRITICAL — using memory:\n"
    "- Obey any matched memories injected below.\n"
    "- action=recall for more detail; list for recent; delete by id."
)

DURABLE_PERSIST_FALLBACK = (
    "DURABLE PERSIST ROUTING: classify content → memory (short) / kb (structured docs) / "
    "workflow (multi-step automation). Prefer kb for NocoDB bases/tables/fields catalogs. "
    "Must call the target tool before claiming saved."
)

KB_INSTRUCTION = (
    "You have a wiki-style knowledge base (设定→知识库 / tool `kb`).\n"
    "- Pages are full documents (Markdown), versioned; not the same as short memory notes.\n"
    "- Collections partition topics: sop=流程标准, product=产品参数, handbook=手册红线, "
    "reference=模板/提示词标准, daily=临时纪要, default=未分类.\n"
    "- Matched page snippets may be injected below; for full text use kb action=get "
    "(or search with collection when the topic is clear).\n"
    "- GROUNDING (anti-hallucination):\n"
    "  * Prefer matched KB pages + long-term memory over invention.\n"
    "  * If answering from KB, follow its procedures/formats; cite [[title]].\n"
    "  * Distinguish 可确认 / 推测 / 需补充 when facts are incomplete; never present guesses as facts.\n"
    "  * If no KB/memory covers the question, say so briefly and ask for missing info — do not fabricate SOP steps or product specs.\n"
    "- Manage wiki: create_page / update_page / append / search / list / list_collections.\n"
    "- Long handbooks/SOP → kb; short preferences → memory."
)

# Appended when at least one KB page was matched this turn
KB_HIT_INSTRUCTION = (
    "KB GROUNDING THIS TURN: wiki snippets are injected below. "
    "Treat them as authoritative for procedures and standards. "
    "If a snippet is truncated, call kb action=get for the full page before inventing missing steps. "
    "Obey any stage order / output format in those pages."
)

WORKFLOW_INSTRUCTION = (
    "Declarative workflows (设定→工作流) use ONE tool: `workflow`.\n"
    "- action=list|get|create|update|save|run|status|list_runs|resume|reject|delete\n"
    "- create=新建；update=改已有；save=upsert；run=执行；delete=删定义（id 或中文名，并清运行记录）\n"
    "- Step types: tool / note / human_gate / agent. Variables: {{inputs.x}} {{steps.id.output}}\n"
    "- Prefer running a saved workflow for multi-step SOPs instead of improvising.\n"
    "- Built-ins: commercial_content_pipeline、commercial_video_a_prime_then_b、demo_workspace_hello\n"
    "- Domain templates in kb; media generation via grok_media only when user asks.\n"
    "- Inside a workflow agent step, do NOT call workflow run/save/create/update/delete again."
)

INTEGRATION_INSTRUCTION = (
    "INTEGRATIONS (设定→集成 / tool `integrations`) — connection configs & secrets:\n"
    "CRITICAL — where things live:\n"
    "  · Host/IP, URL, username, password, token, API key, SSH hosts table, proxy → "
    "**integrations** (data/config.json → integrations.*). Use tool `integrations`.\n"
    "  · Skill/tool **code** → create_tool / read_skill / delete_tool (skills/<id>/).\n"
    "  · Long SOP/handbook prose → kb. Short prefs → memory.\n"
    "FORBIDDEN when creating or updating skills/tools:\n"
    "  · Do NOT put passwords/tokens/API keys into skill handler.py, SKILL.md, or workspace files.\n"
    "  · Do NOT dump host/SSH/NAS/NocoDB/qB credential tables into **kb** as a substitute for 集成.\n"
    "  · Do NOT invent a parallel skill-local secrets file as the primary store "
    "(prefer integrations; skill may only fallback-read legacy files).\n"
    "WHEN user adds/changes servers, accounts, or API endpoints for a skill:\n"
    "  1) integrations action=get|list to see current config\n"
    "  2) integrations action=upsert id=<skill_or_catalog_id> fields_json={...}\n"
    "  3) skill code must read via app.services.credentials / integrations "
    "(see nas/nocodb/qb/http/netops patterns), not hardcode.\n"
    "Catalog ids: http, nas, nocodb, qbittorrent, netops — or custom id matching the skill name.\n"
    "kb is for procedures and docs, NOT for live connection credentials."
)

MEDIA_INSTRUCTION = (
    "When you generate or save images/videos under the workspace, the UI can preview them. "
    "For image generation, image editing, and short video: use the tool `grok_media` "
    "(【主推·生图/视频】— local Grok Build CLI / xAI video API — no IMAGE_GEN_API_KEY needed). "
    "For product image analysis: if the main LLM is multimodal (vision), images may be "
    "attached to the user message — analyze them yourself. "
    "If the main LLM is text-only, you MUST use `analyze_image_auto` (【主推·产品识图】). "
    "Prefer tools that return saved_paths. "
    "\n\n"
    "MEDIA PREFS (mandatory):\n"
    "- Before calling `grok_media` for NEW generation or EDIT, if the user has NOT "
    "clearly specified the needed prefs, DO NOT generate yet — ask them first in plain language "
    "(Chinese/Cantonese as appropriate), then call the tool with full parameters.\n"
    "- Image / edit must confirm when missing: quality (standard|high), count n (1–4), "
    "aspect_ratio (e.g. 1:1, 16:9, 9:16).\n"
    "- Video must confirm when missing: duration (6 or 10 seconds), resolution (480p|720p), "
    "aspect_ratio (e.g. 16:9, 9:16, 1:1).\n"
    "- If the user already gave some prefs (e.g. 「一张 16:9」), only ask for the remaining missing ones.\n"
    "- If the user says 「默认 / 随便 / 你决定」, pick sensible defaults and proceed "
    "(image: high, n=1, 1:1; video: 6s, 720p, 9:16 for product/portrait else 16:9).\n"
    "- When `grok_media` returns status=need_confirm, present its options to the user; do not invent a failure.\n"
    "\n"
    "In your final reply, briefly describe the result; newly generated local media will be attached automatically. "
    "IMPORTANT — user uploads: files under uploads/ are already previewed on the USER bubble. "
    "Do NOT re-paste, re-list, or markdown-embed those upload images in your reply. "
    "Do NOT call analysis/search/generation tools merely because the user attached files — "
    "only use tools when the user explicitly asks to analyze, process, generate, or otherwise act on them. "
    "If the user asks to view an existing workspace image (e.g. 1.jpg), mention it as Markdown: ![name](relative/path.jpg)."
)


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

    async def chat(
        self,
        message: str,
        *,
        session_id: str | None = None,
        use_tools: bool = True,
        use_memory: bool = True,
        model: str | None = None,
    ) -> ChatResponse:
        if not self.llm.has_api_key:
            raise RuntimeError(
                "未配置可用的 LLM API Key。请打开前端「配置」页添加 LLM，或在 .env 中设置 LLM_API_KEY。"
            )

        agent_cfg = self._agent_cfg()
        max_history = int(agent_cfg.get("max_history_messages") or self.settings.max_history_messages)
        max_rounds = int(agent_cfg.get("max_tool_rounds") or self.settings.max_tool_rounds)
        from app.agent.persona import build_persona_prompt

        # User-editable persona only; tool/memory/ops rules injected below (fixed)
        persona_prompt = build_persona_prompt(agent_cfg)

        if session_id:
            session = await self.sessions.get(session_id)
            if session is None:
                session = await self.sessions.create(title=message[:60])
                session_id = session["session_id"]
        else:
            session = await self.sessions.create(title=message[:60])
            session_id = session["session_id"]

        history = await self.sessions.get_messages(session_id, limit=max_history)
        evo_settings = None
        try:
            from app.agent.evolution import (
                evolution_settings,
                render_evolution_block,
            )

            evo_settings = evolution_settings(agent_cfg)
            session_full = await self.sessions.get(session_id)
            evo_block = render_evolution_block(
                (session_full or {}).get("evolution"),
                max_chars=int(evo_settings.get("max_chars") or 2200),
            )
        except Exception:
            logger.exception("Load session evolution failed")
            evo_block = ""
            evo_settings = None

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
        path_hints: list[str] = []
        # Seed path hints from recent assistant tool metadata in history
        path_hints.extend(self._paths_from_history(history))

        # ---- Vision routing: native multimodal vs analyze_image_auto skill ----
        from app.services.vision_input import (
            build_user_content_with_images,
            extract_image_paths_from_message,
            main_llm_supports_vision,
        )

        active_model = model or getattr(self.llm, "model", "") or ""
        active_base = getattr(self.llm, "base_url", "") or ""
        vision_native = main_llm_supports_vision(
            model=active_model,
            base_url=active_base,
            name=str(getattr(self.llm, "llm_id", "") or ""),
        )
        has_imgs = has_upload_image(message)
        image_paths = extract_image_paths_from_message(message) if has_imgs else []
        # Main LLM can see pixels → do NOT force the vision skill
        if vision_native and has_imgs:
            intent_force.discard("analyze_image_auto")
            required_tools.discard("analyze_image_auto")
            logger.info(
                "Vision native path: model=%s images=%s (skip force analyze_image_auto)",
                active_model,
                image_paths,
            )
        elif has_imgs and not vision_native:
            # Text-only main model: keep skill path
            intent_force.add("analyze_image_auto")
            if is_image_only_turn(message):
                required_tools.add("analyze_image_auto")
            logger.info(
                "Vision skill path: model=%s is text-only; force analyze_image_auto",
                active_model,
            )

        system_parts = [persona_prompt]
        system_parts.append(MEMORY_INSTRUCTION)
        system_parts.append(KB_INSTRUCTION)
        system_parts.append(INTEGRATION_INSTRUCTION)
        system_parts.append(WORKFLOW_INSTRUCTION)
        system_parts.append(MEDIA_INSTRUCTION)
        try:
            from app.tools.tool_meta import routing_instruction

            system_parts.append(routing_instruction())
        except Exception:
            pass
        if evo_block:
            system_parts.append(evo_block)
        if is_image_only_turn(message):
            if vision_native and has_imgs:
                system_parts.append(
                    "IMAGE-ONLY TURN (native vision LLM):\n"
                    "- User sent product image(s) with no written question.\n"
                    "- The images are already attached to this user message as multimodal content — "
                    "YOU CAN SEE THEM. Do NOT claim you cannot see images.\n"
                    "- Do NOT call `analyze_image_auto` unless the user explicitly asks for that tool "
                    "or you need a second specialized pass.\n"
                    "- Prefer knowledge page [[产品内容流水线SOP]] (aliases: 产品辨识与咨询): "
                    "run 阶段1 output format (可确认 / 推测 / 需补充), then 阶段1.5 with at most 3 choice questions.\n"
                    "- Do NOT skip to full copy/prompts until the user answers or says 随便/默认.\n"
                    "- If KB snippet is truncated, call `kb` action=get title=产品内容流水线SOP.\n"
                    "- End with A/B choices (not open-ended essay questions)."
                )
            else:
                system_parts.append(
                    "IMAGE-ONLY TURN (text-only main LLM — use vision skill):\n"
                    "- User sent product image(s) with no written question.\n"
                    "- You CANNOT see pixels directly. You MUST call `analyze_image_auto` "
                    "on the upload path before concluding.\n"
                    "- Prefer knowledge page [[产品内容流水线SOP]] (aliases: 产品辨识与咨询): "
                    "run 阶段1 output format (可确认 / 推测 / 需补充), then 阶段1.5 with at most 3 choice questions.\n"
                    "- Do NOT skip to full copy/prompts generation until the user answers or says 随便/默认.\n"
                    "- If KB snippet is truncated, call `kb` action=get title=产品内容流水线SOP for full page.\n"
                    "- End with A/B choices (not open-ended essay questions)."
                )
        elif has_imgs and vision_native:
            system_parts.append(
                "NATIVE VISION THIS TURN:\n"
                "- User attached image(s); pixels are included in the user message.\n"
                "- Analyze them yourself. Prefer NOT calling `analyze_image_auto` "
                "unless the user asks for that tool or structured product JSON from the skill.\n"
                "- Still obey product SOP / KB when the task is product content pipeline."
            )
        elif has_imgs and not vision_native:
            system_parts.append(
                "TEXT-ONLY MAIN LLM + IMAGES:\n"
                "- Current main model does not accept image_url.\n"
                "- To understand uploaded images, call `analyze_image_auto` with the workspace path.\n"
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
        filter_query = build_filter_query(
            base_filter_query or message,
            path_hints=path_hints,
            extra_tools=intent_force,
        )
        if use_memory:
            snippet = await self.memory.context_snippet(
                filter_query or message, limit=5, max_chars=1800, max_pin=3
            )
            if snippet:
                system_parts.append(snippet)
            try:
                from app.knowledge.store import get_knowledge_store

                kb_snip = await get_knowledge_store().context_snippet(
                    filter_query or message,
                    limit=4,
                    max_chars=3200,
                    intent_text=message,
                )
                if kb_snip:
                    system_parts.append(KB_HIT_INSTRUCTION)
                    system_parts.append(kb_snip)
            except Exception:
                logger.exception("KB context snippet failed")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "\n\n".join(system_parts)}
        ]
        # Rebuild history without nested system prompts
        for m in history:
            role = m.get("role")
            if role == "system":
                continue
            messages.append(self._sanitize_message(m))

        # Persist plain text in session; send multimodal content to LLM when supported
        user_msg = {"role": "user", "content": message}
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
                    intent_force.add("analyze_image_auto")
                    if is_image_only_turn(message):
                        required_tools.add("analyze_image_auto")
                    logger.warning(
                        "Native vision attach failed; forcing analyze_image_auto"
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
        used_model = model or self.llm.model
        final_content = ""
        forced_retries = 0
        max_forced_retries = 2
        # Primary tool budget; may auto-extend once so long tasks don't stall on the English cap stub.
        budget = max_rounds
        round_i = 0
        auto_continued = False
        near_limit_nudge_sent = False

        while True:
            while round_i <= budget:
                # Soft budget warning so the model prefers finishing before the hard cap
                if (
                    use_tools
                    and not near_limit_nudge_sent
                    and tool_records
                    and round_i >= max(0, budget - 1)
                ):
                    near_limit_nudge_sent = True
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"[SYSTEM] 提示：本轮工具调用即将达到上限"
                                f"（已进行 {round_i}/{budget} 轮）。"
                                "请优先给出用户可见的完整最终答复；非必要不要再调用工具。"
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
                    )
                    if use_tools
                    else None
                )
                result = await self.llm.chat(
                    messages,
                    tools=openai_tools if use_tools else None,
                    model=model,
                )
                used_model = result.get("model") or used_model
                for k in total_usage:
                    total_usage[k] += int(result.get("usage", {}).get(k, 0) or 0)

                tool_calls = result.get("tool_calls")
                content = result.get("content") or ""

                if tool_calls and use_tools:
                    assistant_msg: dict[str, Any] = {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": tool_calls,
                    }
                    messages.append(assistant_msg)

                    for tc in tool_calls:
                        fn = tc.get("function") or {}
                        name = fn.get("name", "")
                        raw_args = fn.get("arguments") or "{}"
                        try:
                            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        except json.JSONDecodeError:
                            args = {"raw": raw_args}

                        logger.info("Tool call round=%s name=%s args=%s", round_i, name, args)
                        tool_result = await self.tools.execute(name, args)
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
                                "content": tool_result,
                            }
                        )
                    round_i += 1
                    continue

                # --- Hard intercepts when model tries to finish without required tools ---
                if use_tools and forced_retries < max_forced_retries:
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
                        forced_retries += 1
                        intent_force |= {"office", "workspace"}
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "[SYSTEM] You claimed to create/write a file without a tool. "
                                    "MUST call workspace (action=write) or office now."
                                ),
                            }
                        )
                        round_i += 1
                        continue

                final_content = content
                messages.append({"role": "assistant", "content": final_content})
                break

            if (final_content or "").strip():
                break

            # Cap hit with no text answer: auto-continue once (same turn, keep tool context)
            if use_tools and tool_records and not auto_continued:
                auto_continued = True
                extra = max(4, min(12, max_rounds))
                budget = round_i + extra
                near_limit_nudge_sent = False
                logger.info(
                    "Auto-continue after tool-round cap: used=%s extra=%s tools=%s",
                    round_i,
                    extra,
                    len(tool_records),
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "[SYSTEM] 工具调用轮次已达配置上限，系统已自动继续"
                            "（无需用户再输入「继续」）。"
                            "请基于上文已有工具结果继续完成用户任务；"
                            "仍需工具可继续调用，完成后给出完整最终答复。"
                        ),
                    }
                )
                continue

            # Still no final answer: force one no-tools synthesis on full tool context
            final_content = await self._synthesize_after_tool_cap(
                messages,
                tool_records=tool_records,
                max_rounds=max_rounds,
                model=model,
                total_usage=total_usage,
            )
            if final_content:
                messages.append({"role": "assistant", "content": final_content})
            break

        # 工具结果里的本地媒体：写入回复正文，前端气泡可直接预览（历史会话也能看到）
        media_paths = self._collect_media_paths(tool_records)
        final_content = self._ensure_media_in_reply(final_content, media_paths)

        # Persist user + final assistant (and compact tool summary if any)
        to_save: list[dict[str, Any]] = [user_msg]
        if tool_records:
            summary = "; ".join(f"{t.name}()" for t in tool_records)
            # 紧凑工具记录：名称 + 参数键 + 媒体路径（供前端画廊）
            compact_calls = []
            for t in tool_records:
                t_name = (t.name or "").strip()
                # 列表/分析工具不把路径记为可预览媒体，避免助手气泡刷 uploads
                if t_name in self._LIST_LIKE_TOOLS or t_name in self._INPUT_ONLY_TOOLS:
                    paths: list[str] = []
                else:
                    paths = self._extract_media_paths_from_text(
                        t.result or "",
                        structured_only=True,
                        allow_list_fields=False,
                    )
                    paths = [p for p in paths if not self._is_upload_path(p)]
                compact_calls.append(
                    {
                        "name": t.name,
                        "arguments": (
                            {
                                k: (
                                    v
                                    if not isinstance(v, str) or len(v) <= 80
                                    else v[:80] + "…"
                                )
                                for k, v in (t.arguments or {}).items()
                            }
                            if isinstance(t.arguments, dict)
                            else {}
                        ),
                        "media_paths": paths,
                        # 保留短结果摘要；完整结果可能很大
                        "result": (t.result or "")[:500],
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
                    },
                }
            )
        else:
            to_save.append({"role": "assistant", "content": final_content})

        await self.sessions.append_messages(
            session_id,
            to_save,
            title=message[:60],
            max_history=max_history,
        )

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
        new_evo = await evolve_session_context(
            llm=self.llm,
            previous=evo,
            messages_to_compress=older,
            latest_user=latest_user,
            latest_assistant=latest_assistant,
            settings=settings,
            model=model,
        )
        await self.sessions.set_evolution(
            session_id,
            new_evo,
            trim_to=keep,
        )

    async def _synthesize_after_tool_cap(
        self,
        messages: list[dict[str, Any]],
        *,
        tool_records: list[ToolCallRecord],
        max_rounds: int,
        model: str | None,
        total_usage: dict[str, int],
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
                    "[SYSTEM] 工具调用轮次已达上限，禁止再调用任何工具。"
                    "请仅根据上文已执行的工具结果，直接输出完整、可用的最终答复。"
                    "若任务未全部完成，请明确：已完成部分、未完成部分、以及建议的下一步。"
                    f"本轮已调用工具：{tools_hint}。"
                ),
            }
        )
        try:
            result = await self.llm.chat(messages, tools=None, model=model)
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
                "系统已尽量自动续跑；若结果仍不完整，可提高配置中的「最大工具轮次」后重试。"
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
    ) -> AsyncIterator[str]:
        """Simple streaming path without tool calls."""
        if not self.llm.has_api_key:
            raise RuntimeError("未配置可用的 LLM API Key。请打开前端「配置」页添加 LLM。")

        agent_cfg = self._agent_cfg()
        max_history = int(agent_cfg.get("max_history_messages") or self.settings.max_history_messages)
        from app.agent.persona import build_persona_prompt

        persona_prompt = build_persona_prompt(agent_cfg)

        if session_id:
            session = await self.sessions.get(session_id)
            if session is None:
                session = await self.sessions.create(title=message[:60])
                session_id = session["session_id"]
        else:
            session = await self.sessions.create(title=message[:60])
            session_id = session["session_id"]

        history = await self.sessions.get_messages(session_id, limit=max_history)
        filter_query = self._context_query(history, message, recent_user_turns=2)

        system_parts = [persona_prompt]
        system_parts.append(MEMORY_INSTRUCTION)
        system_parts.append(KB_INSTRUCTION)
        system_parts.append(INTEGRATION_INSTRUCTION)
        system_parts.append(WORKFLOW_INSTRUCTION)
        system_parts.append(MEDIA_INSTRUCTION)
        try:
            from app.tools.tool_meta import routing_instruction

            system_parts.append(routing_instruction())
        except Exception:
            pass
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
        except Exception:
            logger.exception("Load session evolution failed (stream)")
        if use_memory:
            snippet = await self.memory.context_snippet(
                filter_query or message, limit=5, max_chars=1800, max_pin=3
            )
            if snippet:
                system_parts.append(snippet)
            try:
                from app.knowledge.store import get_knowledge_store

                kb_snip = await get_knowledge_store().context_snippet(
                    filter_query or message,
                    limit=4,
                    max_chars=3200,
                    intent_text=message,
                )
                if kb_snip:
                    system_parts.append(KB_HIT_INSTRUCTION)
                    system_parts.append(kb_snip)
            except Exception:
                logger.exception("KB context snippet failed (stream)")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "\n\n".join(system_parts)}
        ]
        for m in history:
            if m.get("role") == "system":
                continue
            messages.append(self._sanitize_message(m))
        messages.append({"role": "user", "content": message})

        parts: list[str] = []
        async for delta in self.llm.chat_stream(messages, model=model):
            parts.append(delta)
            yield delta

        full = "".join(parts)
        await self.sessions.append_messages(
            session_id,
            [
                {"role": "user", "content": message},
                {"role": "assistant", "content": full},
            ],
            title=message[:60],
            max_history=max_history,
        )
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

    @staticmethod
    def _sanitize_message(m: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"role": m.get("role", "user"), "content": m.get("content")}
        if m.get("tool_calls"):
            out["tool_calls"] = m["tool_calls"]
        if m.get("tool_call_id"):
            out["tool_call_id"] = m["tool_call_id"]
        if m.get("name"):
            out["name"] = m["name"]
        return out



    @staticmethod
    def _user_wants_file(user_msg: str, assistant_reply: str) -> bool:
        """Detect if user asked for file creation but LLM hallucinated without calling any tool."""
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
        "find_web_project",
    })

    # 纯读取/分析：参数里的图是输入，不是输出
    _INPUT_ONLY_TOOLS = frozenset({
        "analyze_image_auto",
    })

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
            if name in cls._LIST_LIKE_TOOLS or name in cls._INPUT_ONLY_TOOLS:
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
        # 去掉误贴的 uploads / 裸文件名 markdown（用户气泡已有预览）
        text = re.sub(
            r"!\[[^\]]*\]\((?:workspace/)?uploads/[^)\s]+\)\s*",
            "",
            text,
            flags=re.I,
        )
        # 文末裸路径图堆（无目录），保留 images/generated 等带子路径的输出
        text = re.sub(
            r"(?:\n{0,2}!\[[^\]]*\]\((?:workspace/)?[^/\\\s)]+\.(?:png|jpe?g|gif|webp|bmp|svg)\)\s*)+$",
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
