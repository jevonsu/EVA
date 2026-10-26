"""Tool / skill registry — OpenAI function-calling schema + async handlers."""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

ToolHandler = Callable[..., Awaitable[str] | str]

# Valid source values; any other value is rejected by register().
_VALID_SOURCES = frozenset({"builtin", "skill", "custom", "mcp"})


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    source: str = "builtin"
    metadata: dict[str, Any] = field(default_factory=dict)

    def openai_schema(self) -> dict[str, Any]:
        from app.tools.tool_meta import effective_description

        params = self.parameters
        if not params:
            params = {"type": "object", "properties": {}}
        # Routing prefix + optional user prompt override from config
        # (does not mutate registered description / parameters / name).
        skill_id = None
        if isinstance(self.metadata, dict):
            skill_id = self.metadata.get("skill_id")
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": effective_description(
                    self.name, self.description, skill_id=skill_id
                ),
                "parameters": params,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        handler: ToolHandler,
        parameters: dict[str, Any] | None = None,
        *,
        source: str = "builtin",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if source not in _VALID_SOURCES:
            logger.warning(
                "Invalid source %r for tool %s, falling back to 'custom'", source, name
            )
            source = "custom"

        existing = self._tools.get(name)
        if existing:
            if existing.source != source:
                logger.warning(
                    "Cannot overwrite tool %r from source %r with source %r. "
                    "Unregister it first if intentional.",
                    name, existing.source, source,
                )
                return
            logger.warning("Overwriting tool: %s", name)

        if callable(description) and not callable(handler):
            description, handler = handler, description
        if not isinstance(description, str):
            description = str(description or "")
        if not callable(handler):
            logger.error("Tool %s registered without a callable handler", name)

            async def _missing_handler(**_kwargs: Any) -> str:
                return json.dumps({"error": f"tool {name} has no handler"}, ensure_ascii=False)

            handler = _missing_handler
        params = parameters if isinstance(parameters, dict) else {"type": "object", "properties": {}}
        self._tools[name] = ToolSpec(
            name=str(name or ""),
            description=description,
            parameters=params,
            handler=handler,
            source=source,
            metadata=metadata or {},
        )
        logger.info("Registered tool [%s] %s", source, name)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def openai_tools(self) -> list[dict[str, Any]]:
        return [t.openai_schema() for t in self._tools.values()]

    def filter_tools(
        self,
        query: str,
        *,
        top_n: int | None = None,
        force_tools: set[str] | list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return OpenAI tool schemas relevant to *query* (P2 soft Top-N).

        Safety guarantees (no feature loss by default):
        - Always-include tools stay available.
        - Tool names explicitly mentioned in the user message are forced in.
        - *force_tools* (intent routing / prior-turn hints) always get a seat.
        - User phrases like 「全部工具」 → full toolset.
        - Weak / empty matches → core always-include (+ forced/named), not every skill.
        - Soft Top-N only adds skills with a confident match.
        """
        return self._filter_by_query(query, top_n=top_n, force_tools=force_tools)

    # -----------------------------------------------------------------
    #  Intelligent tool filtering by user-query keywords (P2 soft Top-N)
    # -----------------------------------------------------------------
    # Core tools always offered to the model (must exist in the registry).
    # Intentionally excludes create_tool / delete_tool — those are gated by
    # explicit user intent (see _META_TOOLS_CONDITIONAL).
    # Cross-cutting essentials only (saves tokens; others via soft filter).
    # workflow / scheduled_task / integrations / llms are on-demand (scene + intent).
    _ALWAYS_INCLUDE = frozenset({
        "memory",
        "kb",
        "workspace",
        "get_current_time",
        "ask_user",
    })

    # Not always-on; re-offered after recent use or explicit intent/scene.
    _ON_DEMAND_CORES = frozenset({
        "workflow",
        "scheduled_task",
        "integrations",
        "llms",
        "terminal",
        "document",
        "reload_runtime",
        "list_api_models",
        "server_health_check",
    })

    # Only injected when the user clearly asks to create/update/delete a skill.
    # read_skill / list / validate unlocked together with create/update/delete.
    # Session sticky + force_tools can keep them available across turns.
    _META_TOOLS_CONDITIONAL = frozenset(
        {
            "create_tool",
            "delete_tool",
            "read_skill",
            "list_skills",
            "validate_skill",
            "promote_skill",
        }
    )

    # Exact phrase markers (fast path)
    _CREATE_TOOL_MARKERS = (
        "创建工具",
        "创建技能",
        "新建工具",
        "新建技能",
        "新建skill",
        "新建 skill",
        "创建skill",
        "创建 skill",
        "做成工具",
        "做成技能",
        "做成skill",
        "做成 skill",
        "封装成工具",
        "封装成技能",
        "封装成skill",
        "封装成 skill",
        "写一个工具",
        "写一个技能",
        "写一个skill",
        "写一个 skill",
        "做一个工具",
        "做一个技能",
        "做个工具",
        "做个技能",
        "做一下工具",
        "做一下技能",
        "开发技能",
        "写技能",
        "技能创建",
        "技能新建",
        "create tool",
        "create a tool",
        "create skill",
        "create a skill",
        "new skill",
        "new tool",
        "make a skill",
        "make a tool",
    )

    # Allow short fillers: 「创建一个天气 skill 工具」「新建一个 xxx 技能」
    _CREATE_TOOL_PATTERNS = (
        r"创建.{0,20}(工具|skill|技能)",
        r"新建.{0,20}(工具|skill|技能)",
        r"做成.{0,12}(工具|skill|技能)",
        r"封装成.{0,12}(工具|skill|技能)",
        r"写一个.{0,12}(工具|skill|技能)",
        r"做(一个|个|一下).{0,20}(工具|skill|技能)",
        r"开发.{0,12}(工具|skill|技能)",
        r"(工具|skill|技能).{0,8}(创建|新建)",
        r"create\s+(a\s+)?(new\s+)?(tool|skill)",
        r"make\s+(a\s+)?(new\s+)?(tool|skill)",
        r"new\s+(tool|skill)",
    )

    # Update / edit existing skill → unlock create_tool(update=true) + read_skill
    _UPDATE_TOOL_MARKERS = (
        "更新工具",
        "更新技能",
        "更新skill",
        "更新 skill",
        "修改工具",
        "修改技能",
        "修改skill",
        "修改 skill",
        "编辑工具",
        "编辑技能",
        "编辑skill",
        "编辑 skill",
        "改工具",
        "改技能",
        "改skill",
        "改 skill",
        "修复skill",
        "修复技能",
        "修一下skill",
        "修一下技能",
        "技能更新",
        "技能修改",
        "技能编辑",
        "update skill",
        "update tool",
        "edit skill",
        "edit tool",
        "fix skill",
        "modify skill",
    )

    _UPDATE_TOOL_PATTERNS = (
        r"(更新|修改|编辑|改一下|改下|修好|修一下|修复|改进).{0,20}(工具|skill|技能)",
        r"(工具|skill|技能).{0,12}(更新|修改|编辑|修复)",
        r"(update|edit|fix|modify)\s+(the\s+)?(tool|skill)",
        r"(tool|skill)\s+(update|edit|fix)",
    )

    _DELETE_TOOL_MARKERS = (
        "删除工具",
        "删除技能",
        "删除skill",
        "删除 skill",
        "刪除工具",
        "刪除技能",
        "刪除skill",
        "卸載工具",
        "卸载工具",
        "卸载技能",
        "去掉工具",
        "去掉技能",
        "移除工具",
        "移除技能",
        "技能删除",
        "delete tool",
        "delete skill",
        "remove tool",
        "remove skill",
        "uninstall tool",
        "uninstall skill",
    )

    _DELETE_TOOL_PATTERNS = (
        r"删除.{0,16}(工具|skill|技能)",
        r"刪除.{0,16}(工具|skill|技能)",
        r"卸载.{0,12}(工具|skill|技能)",
        r"卸載.{0,12}(工具|skill|技能)",
        r"移除.{0,12}(工具|skill|技能)",
        r"去掉.{0,12}(工具|skill|技能)",
        r"(工具|skill|技能).{0,8}(删除|刪除|卸载|移除)",
        r"delete\s+(the\s+)?(tool|skill)",
        r"remove\s+(the\s+)?(tool|skill)",
        r"uninstall\s+(the\s+)?(tool|skill)",
    )

    # Explicit inspect skill source (read-only)
    _READ_SKILL_MARKERS = (
        "read_skill",
        "查看skill",
        "查看 skill",
        "查看技能",
        "读skill",
        "读 skill",
        "读技能",
        "看skill",
        "看 skill",
        "看技能",
        "skill源码",
        "技能源码",
        "skill 源码",
        "read skill",
        "show skill",
        "inspect skill",
    )

    _READ_SKILL_PATTERNS = (
        r"(读|查看|看一下|看下|打开).{0,16}(skill|技能)(源码|代码|实现)?",
        r"(skill|技能).{0,8}(源码|代码|实现)",
        r"(read|show|inspect|view)\s+(the\s+)?skill",
    )

    _LIST_SKILL_MARKERS = (
        "你有什么技能",
        "有什么技能",
        "有哪些技能",
        "会什么技能",
        "会哪些技能",
        "列出技能",
        "技能列表",
        "全部技能",
        "所有技能",
        "list skills",
        "what skills",
    )

    _LIST_SKILL_PATTERNS = (
        r"(你)?(有|会)(什么|哪些).{0,8}(技能|skill)",
        r"(列出|有哪些|有什么|全部|所有).{0,12}(技能|skill)",
        r"list\s+skills?",
    )

    _FULL_TOOLSET_MARKERS = (
        "全部工具",
        "所有工具",
        "全部skill",
        "全部 skill",
        "所有skill",
        "所有 skill",
        "all tools",
        "every tool",
        "use any tool",
        "any tool",
        "随便用工具",
        "不限工具",
        "打开全部工具",
    )

    _STOP_WORDS = frozenset({
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "out", "off", "over",
        "under", "again", "further", "then", "once", "here", "there", "when",
        "where", "why", "how", "all", "each", "every", "both", "few", "more",
        "most", "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "just", "because", "but", "and",
        "or", "if", "while", "what", "which", "who", "whom", "this", "that",
        "these", "those", "it", "its", "my", "your", "his", "her", "our",
        "their", "me", "him", "us", "them", "i", "you", "he", "she", "we",
        "they", "about", "up", "down", "also", "any", "get", "please", "help",
        "need", "want", "like", "tell", "show", "find", "make", "give",
        "use", "try", "let", "say", "know", "think", "see", "come", "go",
        "take", "put", "set", "ask", "answer", "call", "check", "start",
        "stop", "run", "done", "doing",
    })

    @classmethod
    def _extract_keywords(cls, text: str) -> list[str]:
        """Extract meaningful English words and Chinese substrings."""
        import re
        text = text if isinstance(text, str) else str(text or "")
        text = text.strip()
        if not text:
            return []

        keywords: list[str] = []

        ignore = cls._routing_ignore_tokens()
        eng_tokens = re.findall(r"[a-zA-Z][a-zA-Z]+", text)
        for w in eng_tokens:
            wl = w.lower()
            if wl not in ToolRegistry._STOP_WORDS and wl not in ignore:
                keywords.append(wl)

        chn_chars = re.findall(r"[一-鿿]", text)
        for i in range(len(chn_chars) - 1):
            pair = chn_chars[i] + chn_chars[i + 1]
            keywords.append(pair)

        chn_segments = re.findall(r"[一-鿿]{3,}", text)
        keywords.extend(chn_segments)

        return list(set(keywords))

    @classmethod
    def _routing_ignore_tokens(cls) -> set[str]:
        """Agent display name must not drag in skills by substring."""
        out = {"lily", "lilyth"}
        try:
            from app.config_store import get_config_store

            name = str((get_config_store().get_agent() or {}).get("name") or "").strip()
        except Exception:
            name = ""
        if name:
            compact = name.replace(" ", "").lower()
            if compact:
                out.add(compact)
            for part in name.replace("-", " ").replace("_", " ").split():
                p = part.strip().lower()
                if len(p) >= 2:
                    out.add(p)
        return out

    @classmethod
    def _wants_full_toolset(cls, query: str) -> bool:
        if not query:
            return False
        q = query.lower().replace(" ", "")
        q_raw = query.lower()
        for marker in cls._FULL_TOOLSET_MARKERS:
            m = marker.lower()
            if m.replace(" ", "") in q or m in q_raw:
                return True
        return False

    @classmethod
    def _query_has_marker(cls, query: str, markers: tuple[str, ...]) -> bool:
        if not query:
            return False
        q = query.lower()
        q_compact = q.replace(" ", "")
        for marker in markers:
            m = marker.lower()
            if m in q or m.replace(" ", "") in q_compact:
                return True
        return False

    @classmethod
    def _query_has_pattern(cls, query: str, patterns: tuple[str, ...]) -> bool:
        if not query:
            return False
        import re

        q = query.lower()
        for pat in patterns:
            if re.search(pat, q, flags=re.IGNORECASE):
                return True
        return False

    def _expand_meta_bundle(self, allowed: set[str]) -> set[str]:
        """Companion tools for a coherent skill-dev workflow."""
        out = set(allowed)
        if "create_tool" in out or "delete_tool" in out or "promote_skill" in out:
            out |= {"read_skill", "list_skills", "validate_skill"}
        if "validate_skill" in out:
            out |= {"read_skill", "list_skills"}
        if "read_skill" in out:
            out.add("list_skills")
        if "list_skills" in out and not out - {"list_skills"}:
            pass  # list alone is fine
        # promote only when create/update/promote intent already present
        if "create_tool" in out:
            out.add("promote_skill")
        return out & self._META_TOOLS_CONDITIONAL

    def _allowed_meta_tools(self, query: str) -> set[str]:
        """Unlock skill meta tools only when user intent is explicit (or named).

        - create / update / edit → create_tool + read/list/validate/promote
        - delete → delete_tool + read/list
        - read / inspect → read_skill + list
        - existing skill id + repair verbs → create + read (see skill_lifecycle)
        - 「全部工具」 still does *not* auto-unlock create/delete (anti-spam).
        """
        allowed: set[str] = set()
        named = self._named_tools_in_query(query or "")
        q = query or ""

        wants_create = (
            "create_tool" in named
            or "promote_skill" in named
            or self._query_has_marker(q, self._CREATE_TOOL_MARKERS)
            or self._query_has_pattern(q, self._CREATE_TOOL_PATTERNS)
            or self._query_has_marker(q, self._UPDATE_TOOL_MARKERS)
            or self._query_has_pattern(q, self._UPDATE_TOOL_PATTERNS)
        )
        wants_delete = (
            "delete_tool" in named
            or self._query_has_marker(q, self._DELETE_TOOL_MARKERS)
            or self._query_has_pattern(q, self._DELETE_TOOL_PATTERNS)
        )
        wants_read = (
            "read_skill" in named
            or "list_skills" in named
            or "validate_skill" in named
            or self._query_has_marker(q, self._READ_SKILL_MARKERS)
            or self._query_has_pattern(q, self._READ_SKILL_PATTERNS)
        )
        wants_list = (
            "list_skills" in named
            or self._query_has_marker(q, self._LIST_SKILL_MARKERS)
            or self._query_has_pattern(q, self._LIST_SKILL_PATTERNS)
        )
        # Explicit promote / 发布 / 草稿
        q_low = q.lower()
        if (
            "promote_skill" in named
            or "发布技能" in q
            or "发布 skill" in q_low
            or "promote skill" in q_low
            or (
                "草稿" in q
                and ("发布" in q or "promote" in q_low or "上线" in q)
            )
        ):
            allowed.add("promote_skill")
            wants_create = True

        if wants_create:
            allowed.add("create_tool")
        if wants_delete:
            allowed.add("delete_tool")
        if wants_read:
            allowed.add("read_skill")
        if wants_list:
            allowed.add("list_skills")

        # Existing skill name + repair/debug intent (e.g. 「修 xxx 技能」)
        try:
            from app.services.skill_lifecycle import auto_meta_tools_for_query

            allowed |= auto_meta_tools_for_query(q)
        except Exception:
            pass

        return self._expand_meta_bundle(allowed)

    def _iter_visible_tools(
        self,
        query: str,
        *,
        force_tools: set[str] | None = None,
    ) -> list[ToolSpec]:
        """All registered tools minus gated meta tools (unless intent / force)."""
        allowed_meta = self._allowed_meta_tools(query or "")
        if force_tools:
            allowed_meta |= {
                n for n in force_tools if n in self._META_TOOLS_CONDITIONAL
            }
            allowed_meta = self._expand_meta_bundle(allowed_meta)
        out: list[ToolSpec] = []
        for spec in self._tools.values():
            if (
                spec.name in self._META_TOOLS_CONDITIONAL
                and spec.name not in allowed_meta
            ):
                continue
            out.append(spec)
        return out

    def _openai_tools_for_query(
        self,
        query: str,
        *,
        force_tools: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        return [
            t.openai_schema()
            for t in self._iter_visible_tools(query, force_tools=force_tools)
        ]

    def _core_plus_named_specs(
        self,
        visible_by_name: dict[str, ToolSpec],
        *,
        named: set[str],
        allowed_meta: set[str],
    ) -> list[ToolSpec]:
        """Always-include cores + explicitly named / forced tools. No skill dump."""
        selected: list[ToolSpec] = []
        seen: set[str] = set()

        def _add(spec: ToolSpec | None) -> None:
            if spec is None or spec.name in seen:
                return
            seen.add(spec.name)
            selected.append(spec)

        for name in self._ALWAYS_INCLUDE:
            _add(visible_by_name.get(name))
        for name in sorted(named):
            spec = visible_by_name.get(name)
            if spec is None:
                continue
            if (
                spec.name in self._META_TOOLS_CONDITIONAL
                and spec.name not in allowed_meta
            ):
                continue
            _add(spec)
        return selected

    @classmethod
    def on_demand_cores_from_history(
        cls,
        history: list[dict[str, Any]] | None,
        *,
        lookback: int = 2,
    ) -> set[str]:
        """Re-offer workflow/schedule/integrations/llms used in recent tool turns.

        Skips chat-only assistant messages so a later 「搞一下那个」 still sees
        the last task tools, without keeping them on every RP turn forever.
        """
        if not history or lookback <= 0:
            return set()
        found: set[str] = set()
        seen_asst = 0
        for m in reversed(history):
            if m.get("role") != "assistant":
                continue
            seen_asst += 1
            meta = m.get("metadata") if isinstance(m.get("metadata"), dict) else {}
            for tc in meta.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                n = str(tc.get("name") or "").strip()
                if n in cls._ON_DEMAND_CORES:
                    found.add(n)
            used = str(meta.get("tools_used") or "")
            if used:
                for n in cls._ON_DEMAND_CORES:
                    if n in used:
                        found.add(n)
            if seen_asst >= lookback:
                break
        return found

    def _named_tools_in_query(self, query: str) -> set[str]:
        """Force-include tools whose names appear as tokens, not substrings.

        ``http`` must not match ``https://…``. Short names use a word boundary.
        """
        if not query:
            return set()
        q = query.lower()
        found: set[str] = set()
        names = sorted(self._tools.keys(), key=len, reverse=True)
        for name in names:
            nl = name.lower()
            if not nl:
                continue
            if len(nl) <= 4 or nl.isalnum():
                pat = r"(?<![a-z0-9_])" + re.escape(nl) + r"(?![a-z0-9_])"
                if re.search(pat, q):
                    found.add(name)
                    continue
            elif nl in q:
                found.add(name)
                continue
            spaced = nl.replace("_", " ")
            if spaced and spaced != nl and spaced in q:
                found.add(name)
        return found

    def _resolve_top_n(self, top_n: int | None) -> int:
        import os

        from app.tools.tool_meta import DEFAULT_TOOL_TOP_N

        if top_n is not None:
            return max(5, min(int(top_n), 200))
        env = os.environ.get("AGENTOS_TOOL_TOP_N", "").strip()
        if env.isdigit():
            return max(5, min(int(env), 200))
        return max(5, min(int(DEFAULT_TOOL_TOP_N), 200))

    def _filter_by_query(
        self,
        query: str,
        *,
        top_n: int | None = None,
        force_tools: set[str] | list[str] | None = None,
    ) -> list[dict[str, Any]]:
        from app.tools.tool_meta import (
            MIN_CONFIDENT_MATCH_SCORE,
            decorate_description,
            role_score_boost,
            scene_score_boost,
        )

        forced: set[str] = set()
        if force_tools:
            forced = {str(x).strip() for x in force_tools if str(x).strip()}

        visible = self._iter_visible_tools(query or "", force_tools=forced or None)
        total = len(visible)
        if total == 0:
            return []

        # Explicit full-set request (still respects create/delete gating)
        if self._wants_full_toolset(query or ""):
            logger.info("filter_tools: full toolset requested by user")
            return self._openai_tools_for_query(query or "", force_tools=forced or None)

        limit = self._resolve_top_n(top_n)
        keywords = self._extract_keywords(query or "")
        named = self._named_tools_in_query(query or "")
        allowed_meta = self._allowed_meta_tools(query or "")
        if forced:
            allowed_meta |= {
                n for n in forced if n in self._META_TOOLS_CONDITIONAL
            }
            if "create_tool" in allowed_meta or "delete_tool" in allowed_meta:
                allowed_meta.add("read_skill")
        # Meta tools named or intent-matched get a forced seat
        named = named | allowed_meta | (forced & {s.name for s in visible})
        visible_by_name = {s.name: s for s in visible}

        def _core_schemas() -> list[dict[str, Any]]:
            specs = self._core_plus_named_specs(
                visible_by_name, named=named, allowed_meta=allowed_meta
            )
            return [s.openai_schema() for s in specs]

        # Empty / no keywords and no explicit tool names → cores only (not every skill)
        if not keywords and not named:
            logger.info("filter_tools: no keywords, using core toolset")
            return _core_schemas()

        scored: list[tuple[int, ToolSpec]] = []
        score_map: dict[str, int] = {}

        for spec in visible:
            score = 0
            n = spec.name.lower()
            raw_desc = spec.description if isinstance(spec.description, str) else str(spec.description or "")
            d = (decorate_description(spec.name, raw_desc) + " " + raw_desc).lower()

            for kw in keywords:
                kwl = kw.lower()
                if kwl in n or n in kwl:
                    score += 15
                if kwl in d:
                    score += 3
                if spec.parameters:
                    ps = json.dumps(spec.parameters).lower()
                    if kwl in ps:
                        score += 1

            score += scene_score_boost(spec.name, query or "")

            if spec.name in self._ALWAYS_INCLUDE:
                score = max(score, 1)
            if spec.name in named:
                # Explicit mention always wins a seat
                score = max(score, 100)

            if score > 0:
                score += role_score_boost(spec.name)
                scored.append((score, spec))
                score_map[spec.name] = score

        if not scored:
            logger.info("filter_tools: no match, using core toolset")
            return _core_schemas()

        scored.sort(key=lambda x: -x[0])
        best = scored[0][0]

        # Only always-include floor (score ~1+role) and no named tools → cores, not all skills
        if best < MIN_CONFIDENT_MATCH_SCORE and not named:
            logger.info(
                "filter_tools: weak match best=%s, using core toolset",
                best,
            )
            return _core_schemas()

        selected: list[ToolSpec] = []
        selected_names: set[str] = set()

        def _add(spec: ToolSpec) -> None:
            if spec.name in selected_names:
                return
            selected_names.add(spec.name)
            selected.append(spec)

        # 1) Forced seats
        for name in self._ALWAYS_INCLUDE:
            spec = visible_by_name.get(name) or self._tools.get(name)
            if spec and spec.name in visible_by_name:
                _add(spec)
        for name in named:
            spec = visible_by_name.get(name) or self._tools.get(name)
            if spec and (
                spec.name not in self._META_TOOLS_CONDITIONAL
                or spec.name in allowed_meta
            ):
                if spec.name in visible_by_name:
                    _add(spec)

        # 2) Fill by confident score only (do not pad with weak skills up to Top-N)
        for score, spec in scored:
            if len(selected) >= limit:
                break
            if (
                score < MIN_CONFIDENT_MATCH_SCORE
                and spec.name not in named
                and spec.name not in self._ALWAYS_INCLUDE
            ):
                continue
            _add(spec)

        # 3) If forced seats already filled the budget, still ensure top-scored
        #    non-forced tools get a chance by expanding slightly (cap +8)
        if len(selected) >= limit:
            expand_cap = min(total, limit + 8)
            for score, spec in scored:
                if len(selected) >= expand_cap:
                    break
                if score >= MIN_CONFIDENT_MATCH_SCORE:
                    _add(spec)

        # Preserve score order for the model (forced first is ok, then by score)
        selected.sort(
            key=lambda s: (
                0 if s.name in named else 1 if s.name in self._ALWAYS_INCLUDE else 2,
                -score_map.get(s.name, 0),
                s.name,
            )
        )

        result = [spec.openai_schema() for spec in selected]
        logger.info(
            "filter_tools: soft top_n=%s selected=%d/%d best=%s named=%s meta=%s query=%r",
            limit,
            len(result),
            total,
            best,
            sorted(named - allowed_meta),
            sorted(allowed_meta),
            (query or "")[:60],
        )
        return result



    async def execute(self, name: str, arguments: dict[str, Any] | str) -> str:
        spec = self._tools.get(name)
        if not spec:
            return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)

        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError:
                arguments = {"raw": arguments}

        if not isinstance(arguments, dict):
            arguments = {"value": arguments}

        # skill 可通过 metadata.timeout_sec 覆盖
        try:
            timeout = float((spec.metadata or {}).get("timeout_sec") or 120)
        except (TypeError, ValueError):
            timeout = 120.0
        timeout = max(5.0, min(timeout, 3600.0))

        try:
            result = spec.handler(**arguments)
            if inspect.isawaitable(result):
                result = await asyncio.wait_for(result, timeout=timeout)
            else:
                loop = asyncio.get_running_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, functools.partial(spec.handler, **arguments)
                    ),
                    timeout=timeout,
                )
            if not isinstance(result, str):
                result = json.dumps(result, ensure_ascii=False, default=str)
            return result
        except asyncio.TimeoutError:
            logger.error("Tool %s timed out after %ss", name, int(timeout))
            return json.dumps(
                {"error": f"Tool {name} timed out after {int(timeout)}s"},
                ensure_ascii=False,
            )
        except TypeError as exc:
            # Only retry on signature mismatch, not handler-internal TypeErrors.
            try:
                sig = inspect.signature(spec.handler)
                param_names = set(sig.parameters.keys())
                arg_names = set(arguments.keys())

                has_var_keyword = any(
                    p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values()
                )
                unexpected_args = arg_names - param_names

                # If the handler accepts **kwargs or all arg names match,
                # the TypeError came from the handler body, not a mismatch.
                if has_var_keyword or not unexpected_args:
                    logger.exception("Tool %s TypeError in handler body", name)
                    return json.dumps({"error": str(exc)}, ensure_ascii=False)

                # Retry with only the parameters the handler expects.
                allowed = {k: v for k, v in arguments.items() if k in param_names}
                result = spec.handler(**allowed)
                if inspect.isawaitable(result):
                    result = await asyncio.wait_for(result, timeout=timeout)
                else:
                    loop = asyncio.get_running_loop()
                    result = await asyncio.wait_for(
                        loop.run_in_executor(
                            None, functools.partial(spec.handler, **allowed)
                        ),
                        timeout=timeout,
                    )
                if not isinstance(result, str):
                    result = json.dumps(result, ensure_ascii=False, default=str)
                return result
            except asyncio.TimeoutError:
                logger.error("Tool %s timed out after %ss", name, int(timeout))
                return json.dumps(
                    {"error": f"Tool {name} timed out after {int(timeout)}s"},
                    ensure_ascii=False,
                )
            except Exception as inner:
                logger.exception("Tool %s failed", name)
                return json.dumps(
                    {"error": str(inner), "original": str(exc)},
                    ensure_ascii=False,
                )
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            return json.dumps({"error": str(exc)}, ensure_ascii=False)


_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def reset_tool_registry() -> None:
    global _registry
    _registry = None
