"""Lightweight intent → primary tool mapping (rule-based, before LLM).

Used to:
  1) Force-include tools in soft filter (so the model can see them)
  2) Detect mandatory tool use for hard retry
  3) Intelligent durable-persist routing: 记住 → memory | kb | workflow
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class IntentHit:
    intent_id: str
    tools: list[str]
    # If True, final answer without calling at least one of these tools → force retry
    require_tool: bool = False
    # Optional: which tool name must appear (first in tools) when require_tool
    require_any_of: list[str] = field(default_factory=list)
    confidence: float = 1.0


@dataclass
class DurablePersistPlan:
    """How to persist user knowledge this turn (smart fan-out)."""

    primary: str  # memory | kb | workflow
    force_tools: list[str]
    # Hard retry: satisfied if ANY of these tools was called
    require_any_of: list[str]
    op: str  # create | update | delete | remember
    reason: str
    hint: str  # short system guidance for the model


# Durable-write intent markers (user wants something persisted)
_PERSIST_MARKERS = re.compile(
    r"(记住|记一下|记着|记得住|以后都要|以后记得|别忘了|记在|"
    r"存到记忆|写入记忆|记下来|帮我记|帮我保存|"
    r"写(入|进|到)?知识库|保存到知识库|建(一个)?(知识)?页|更新知识库|知识库(里)?(加上|删掉|删除|更新)|"
    r"做成工作流|做成流程|保存(为|成)?工作流|创建工作流|新建流程|更新工作流|删除工作流|删掉流程|"
    r"\bremember\b|\bmemorize\b|\bsave (this |it )?to (memory|kb|wiki|workflow)\b)",
    re.I,
)

# Explicit destination overrides
_EXPLICIT_MEMORY = re.compile(
    r"(长期记忆|记忆面板|存到记忆|写入记忆|记在记忆|"
    r"\b(long[- ]?term )?memory\b)",
    re.I,
)
_EXPLICIT_KB = re.compile(
    r"(知识库|wiki|百科|知识页|写入知识库|保存到知识库|建(一个)?页|"
    r"\bknowledge base\b|\bwiki\b)",
    re.I,
)
_EXPLICIT_WORKFLOW = re.compile(
    r"(工作流|做成流程|做成工作流|保存(为|成)?工作流|创建工作流|新建流程|"
    r"修改工作流|更新工作流|删除工作流|删掉流程|"
    r"\bworkflow\b)",
    re.I,
)
# Content-shape signals → prefer kb (structured / long / catalogs)
_KB_SHAPE = re.compile(
    r"(数据库|数据表|表结构|字段|schema|base\b|bases\b|tables?\b|"
    r"库名|表名|清单|列表如下|如下[:：]|参数表|规格|手册|sop|SOP|"
    r"标准作业|红线|提示词标准|文档|章节|多个库|几个库|几张表|"
    r"product|collection\s*=)",
    re.I,
)

# Multi-step automation → workflow
_WF_SHAPE = re.compile(
    r"(每(次|天|周|月)|自动(执行|跑|完成)|按步骤|多步骤|先.+再.+然后|"
    r"流水线|编排|human_gate|停一下问我|定时跑|一键执行|"
    r"步骤[1一123]|第[一二三1-3]步)",
    re.I,
)

# Short preference / habit → memory
_MEM_SHAPE = re.compile(
    r"(喜欢|偏好|以后都|默认用|风格|语气|别用|不要再用|称呼我|"
    r"我是|习惯|总是|永远|规则是)",
    re.I,
)

# CRUD op signals
_OP_DELETE = re.compile(
    r"(删除|删掉|去掉|移除|忘掉|忘记|取消记住|不要再记|"
    r"\bdelete\b|\bremove\b|\bforget\b)",
    re.I,
)
_OP_UPDATE = re.compile(
    r"(更新|修改|改成|改为|覆盖|append|追加|编辑|"
    r"\bupdate\b|\bedit\b|\bchange\b)",
    re.I,
)


def classify_durable_persist(text: str) -> DurablePersistPlan | None:
    """Route 记住/保存类意图到 memory | kb | workflow.

    Returns None if this turn is not a durable-persist request.
    """
    t = (text or "").strip()
    if not t:
        return None
    free = user_free_text(t) or t
    if not _PERSIST_MARKERS.search(free) and not _PERSIST_MARKERS.search(t):
        # Still allow pure "写入知识库/创建工作流" without 记住
        if not (
            _EXPLICIT_KB.search(free)
            or _EXPLICIT_WORKFLOW.search(free)
            or _EXPLICIT_MEMORY.search(free)
        ):
            return None
        # explicit dest without 记住 — only if write-ish verb present
        if not re.search(
            r"(写|存|建|创建|更新|修改|删除|删掉|保存|做成|记)",
            free,
            re.I,
        ):
            return None

    op = "remember"
    if _OP_DELETE.search(free):
        op = "delete"
    elif _OP_UPDATE.search(free):
        op = "update"

    # 1) Explicit destination wins (workflow / kb / memory)
    hit_wf = bool(_EXPLICIT_WORKFLOW.search(free))
    hit_kb = bool(_EXPLICIT_KB.search(free))
    hit_mem = bool(_EXPLICIT_MEMORY.search(free))
    primary: str | None = None
    reason = ""
    if hit_wf and not hit_kb:
        primary, reason = "workflow", "explicit_workflow"
    elif hit_kb and not hit_wf:
        primary, reason = "kb", "explicit_kb"
    elif hit_mem and not hit_kb and not hit_wf:
        # 「存到记忆」wins only when they named the memory store — not 记住尾款
        primary, reason = "memory", "explicit_memory"
    elif hit_wf and hit_kb:
        # both mentioned: prefer workflow if create/run process, else kb for docs
        primary, reason = (
            ("workflow", "explicit_both_prefer_wf")
            if _WF_SHAPE.search(free)
            else ("kb", "explicit_both_prefer_kb")
        )
    else:
        # 2) Content shape scoring
        score_kb = 0
        score_wf = 0
        score_mem = 0
        if _KB_SHAPE.search(free):
            score_kb += 3
        if _WF_SHAPE.search(free):
            score_wf += 3
        if _MEM_SHAPE.search(free):
            score_mem += 2
        if len(free) >= 180:
            score_kb += 2
        if len(free) >= 400:
            score_kb += 2
        if free.count("\n") >= 3 or free.count("、") >= 4 or free.count("- ") >= 3:
            score_kb += 2
        if re.search(r"(步骤|[1-9][\.、．)]\s*\S+){2,}", free):
            score_wf += 2

        ranked = [
            (score_wf, "workflow", f"shape_wf:{score_wf}"),
            (score_kb, "kb", f"shape_kb:{score_kb}"),
            (score_mem, "memory", f"shape_mem:{score_mem}"),
        ]
        ranked.sort(key=lambda x: x[0], reverse=True)
        if ranked[0][0] > 0:
            primary, reason = ranked[0][1], ranked[0][2]
        else:
            primary, reason = "memory", "shape_mem:0"

    # Map op for tools
    if primary == "memory":
        if op == "delete":
            hint = (
                "PERSIST→memory DELETE: call `memory` action=delete (need id) "
                "or recall then delete. Do not only say forgotten."
            )
            tool_op = "delete"
        else:
            hint = (
                "PERSIST→memory: call `memory` action=remember with COMPLETE natural-language "
                "content (who/what/when/how), kind=preference|habit|rule|fact, useful tags. "
                "Do not only reply 好的记住了."
            )
            tool_op = "remember"
        force = ["memory"]
        require = ["memory"]
    elif primary == "kb":
        if op == "delete":
            hint = (
                "PERSIST→kb DELETE: call `kb` action=search/list then delete by id. "
                "Confirm target page; do not only claim deleted."
            )
            tool_op = "delete"
        elif op == "update":
            hint = (
                "PERSIST→kb UPDATE: call `kb` action=search/get then update_page or append "
                "with full structured Markdown. collection=product|sop|handbook|reference as fits."
            )
            tool_op = "update"
        else:
            hint = (
                "PERSIST→kb CREATE: call `kb` action=create_page (or update_page if exists). "
                "Use structured Markdown; pick collection "
                "(product=库表/参数, sop=流程, handbook=红线, reference=模板). "
                "Long catalogs must NOT go only to memory."
            )
            tool_op = "create"
        force = ["kb"]
        # also allow memory for a short index pointer when creating rich kb
        if op != "delete":
            force.append("memory")
        require = ["kb"]
    elif primary == "workflow":
        if op == "delete":
            hint = (
                "PERSIST→workflow DELETE: call `workflow` action=delete "
                "(workflow_id or Chinese name). Do not only claim deleted."
            )
            tool_op = "delete"
        elif op == "update":
            hint = (
                "PERSIST→workflow UPDATE: call `workflow` action=get then update "
                "with steps_json/inputs as needed. "
                "Timer changes: scheduled_task create/update with workflow_id."
            )
            tool_op = "update"
        else:
            hint = (
                "PERSIST→workflow CREATE: call `workflow` action=create with name + steps_json "
                "(tool|note|human_gate|agent). "
                "If the user wants it on a timer, also call `scheduled_task` action=create "
                "with workflow_id/workflow_name + cron or interval_minutes. "
                "Do not say there is no cron entry."
            )
            tool_op = "create"
        force = ["workflow", "scheduled_task"]
        if op != "delete":
            force.append("memory")  # optional short pointer
        require = ["workflow"]
    else:
        force = ["memory"]
        require = ["memory"]
        tool_op = "remember"
        hint = (
            "PERSIST→memory: call `memory` action=remember with COMPLETE natural-language "
            "content. Do not only reply 好的记住了."
        )

    return DurablePersistPlan(
        primary=primary,
        force_tools=force,
        require_any_of=require,
        op=tool_op,
        reason=reason,
        hint=hint,
    )


# Ordered: first match wins for require_tool; all matching intents merge force tools.
# NOTE: generic 记住 is handled by classify_durable_persist (not force-memory-only).
_INTENT_RULES: list[tuple[str, re.Pattern[str], list[str], bool]] = [
    # memory recall (not write)
    (
        "memory_recall",
        re.compile(
            r"(你还记得|记得我|我的偏好|回忆一下|查(一下)?记忆|长期记忆|"
            r"\brecall\b|\bwhat do you remember\b)",
            re.I,
        ),
        ["memory"],
        False,
    ),
    # knowledge base wiki / business standards (browse — write handled by durable plan)
    (
        "kb",
        re.compile(
            r"(知识库|wiki|百科|手册|sop|SOP|写入知识库|建(一个)?页|知识页|"
            r"作业流程|提示词标准|"
            r"\bknowledge base\b|\bwiki\b|\bhandbook\b)",
            re.I,
        ),
        ["kb"],
        False,
    ),
    # workflow (single tool entry for CRUD + run)
    (
        "workflow",
        re.compile(
            r"(工作流|流水线|跑(一下)?流程|执行工作流|多步骤流程|"
            r"创建(一个)?(工作流|流程)|新建(一个)?(工作流|流程)|"
            r"修改(工作流|流程)|更新(工作流|流程)|删除(工作流|流程)|删掉(工作流|流程)|"
            r"\bworkflow\b|\brun workflow\b|\bcreate workflow\b|\bdelete workflow\b)",
            re.I,
        ),
        ["workflow"],
        False,
    ),
    # workspace / local files
    (
        "workspace",
        re.compile(
            r"(工作区|workspace|列(一下)?目录|有哪些文件|读(一下)?文件|写(入|个)?文件|"
            r"删(除)?文件|重命名|搜(索)?文件|保存到|打开文件|"
            r"\blist (files|dir)|read file|write file\b)",
            re.I,
        ),
        ["workspace", "document"],
        False,
    ),
    # schedule — 统一走 scheduled_task（设定→任务面板）
    (
        "schedule",
        re.compile(
            r"(定时任务|cron|每隔|每小时|每天.*跑|每三天|例行|"
            r"schedule|提醒我|设(个|一个)?提醒|闹钟|到点提醒|"
            r"定时|排程|到点(跑|执行)|自动跑)",
            re.I,
        ),
        ["scheduled_task", "workflow"],
        False,
    ),
    (
        "llms",
        re.compile(
            r"(对话模型|设定.?llm|大模型|模型列表|api[ _-]?key|base_url|"
            r"\bllms\b|\bopenai\b|\bdeepseek\b|\bxai\b)",
            re.I,
        ),
        ["llms", "list_api_models"],
        False,
    ),
    (
        "list_api_models",
        re.compile(
            r"(远程模型|/models|中转站模型|拉取模型|供应商模型|"
            r"这个(接口|中转|站点).{0,6}(哪些|什么)模型)",
            re.I,
        ),
        ["list_api_models", "llms"],
        False,
    ),
    (
        "reload_runtime",
        re.compile(
            r"(热重载|重载运行时|reload\s*runtime|刷新工具|"
            r"重新加载(技能|工具|配置)|重载配置)",
            re.I,
        ),
        ["reload_runtime"],
        False,
    ),
    (
        "server_health_check",
        re.compile(
            r"(健康检查|服务器状态|本机健康|health\s*check|"
            r"(cpu|内存|磁盘).{0,4}(占用|空间|够不够)|"
            r"机器(卡不卡|卡吗)|本机(卡不卡|资源))",
            re.I,
        ),
        ["server_health_check"],
        False,
    ),
    (
        "integrations",
        re.compile(
            r"(设定.?集成|连接配置|ssh配置|主机密码|业务.?api|"
            r"\bintegrations\b|\bssh\b)",
            re.I,
        ),
        ["integrations"],
        False,
    ),
    (
        "terminal",
        re.compile(
            r"(执行|跑|运行).{0,8}(命令|脚本|终端)|"
            r"(终端|命令行|cmd|powershell)|"
            r"\bpip\s+install\b|\bnpm\s+i(nstall)?\b|\bgit\s+clone\b|"
            r"安装(依赖|python包|节点包)",
            re.I,
        ),
        ["terminal"],
        False,
    ),
    (
        "document",
        re.compile(
            r"\.(docx|xlsx|pptx|pdf|md)\b|"
            r"\b(docx|xlsx|pptx)\b|"
            r"(word|excel|powerpoint|ppt).{0,4}(文档|表格|幻灯片|文件)|"
            r"(文档|表格|幻灯片).{0,4}(word|excel|ppt|pdf)|"
            r"(读|写|改|编辑|打开|做|生成|删除).{0,8}"
            r"(word|excel|ppt|pdf|markdown|docx|xlsx|pptx|文档|表格|幻灯片)|"
            r"办公文档|markdown文档",
            re.I,
        ),
        ["document"],
        False,
    ),
    # skill / tool package management (create_tool / read_skill / delete_tool)
    (
        "skill_create",
        re.compile(
            r"(创建|新建|做成|封装成|写一个|做一个|做个|做一下|开发).{0,20}(工具|skill|技能)|"
            r"(工具|skill|技能).{0,8}(创建|新建)|"
            r"\bcreate_tool\b|"
            r"create\s+(a\s+)?(new\s+)?(tool|skill)|"
            r"new\s+(tool|skill)|make\s+(a\s+)?(new\s+)?(tool|skill)",
            re.I,
        ),
        ["create_tool", "read_skill"],
        False,
    ),
    (
        "skill_update",
        re.compile(
            r"(更新|修改|编辑|改一下|改下|修好|修一下|修复|改进).{0,20}(工具|skill|技能)|"
            r"(工具|skill|技能).{0,12}(更新|修改|编辑|修复)|"
            r"(update|edit|fix|modify)\s+(the\s+)?(tool|skill)",
            re.I,
        ),
        ["create_tool", "read_skill"],
        False,
    ),
    (
        "skill_delete",
        re.compile(
            r"(删除|刪除|卸载|卸載|移除|去掉).{0,16}(工具|skill|技能)|"
            r"(工具|skill|技能).{0,8}(删除|刪除|卸载|移除)|"
            r"\bdelete_tool\b|"
            r"(delete|remove|uninstall)\s+(the\s+)?(tool|skill)",
            re.I,
        ),
        ["delete_tool", "read_skill"],
        False,
    ),
    (
        "skill_read",
        re.compile(
            r"(读|查看|看一下|看下).{0,16}(skill|技能)(源码|代码|实现)?|"
            r"(skill|技能).{0,8}(源码|代码|实现)|"
            r"\bread_skill\b|"
            r"(read|show|inspect|view)\s+(the\s+)?skill",
            re.I,
        ),
        ["read_skill", "list_skills"],
        False,
    ),
    (
        "skill_list",
        re.compile(
            r"(你)?(有|会)(什么|哪些).{0,8}(技能|skill)|"
            r"(列出|有哪些|有什么|全部|所有).{0,12}(技能|skill)|"
            r"技能列表|"
            r"\blist_skills\b|"
            r"list\s+skills?|"
            r"what skills",
            re.I,
        ),
        ["list_skills"],
        False,
    ),
    (
        "skill_promote",
        re.compile(
            r"(发布|上线|promote).{0,12}(技能|skill|草稿)|"
            r"(技能|skill|草稿).{0,8}(发布|上线)|"
            r"\bpromote_skill\b",
            re.I,
        ),
        ["promote_skill", "validate_skill", "read_skill", "list_skills"],
        False,
    ),
]


def match_intents(text: str) -> list[IntentHit]:
    """Return all matching intents (may be multiple)."""
    t = text if isinstance(text, str) else str(text or "")
    if not t.strip():
        return []
    hits: list[IntentHit] = []
    for intent_id, pat, tools, require in _INTENT_RULES:
        if pat.search(t):
            hits.append(
                IntentHit(
                    intent_id=intent_id,
                    tools=list(tools),
                    require_tool=require,
                    require_any_of=list(tools) if require else [],
                    confidence=1.0,
                )
            )
    return hits


_IMAGE_EXT = re.compile(
    r"\.(?:png|jpe?g|gif|webp|bmp|heic|heif)\b",
    re.I,
)
_UPLOAD_IMAGE_LINE = re.compile(
    r"(?:图片|image)\s*[:：]\s*(?:workspace/)?uploads/[^\s]+",
    re.I,
)
_UPLOAD_PATH = re.compile(
    r"(?<![A-Za-z0-9_/\\])(?:workspace/)?uploads/[\w./\\-]+\.(?:png|jpe?g|gif|webp|bmp|heic|heif)\b",
    re.I,
)
# Boilerplate the frontend appends for attachments (not user free text)
_ATTACH_BOILERPLATE = re.compile(
    r"【用户上传的(?:文件|图片|产品图片)】|"
    r"界面已在用户消息中预览|"
    r"仅当用户明确要求|"
    r"不要仅因附件|"
    r"用户本轮未打字|"
    r"只描述/识别|"
    r"不要编造业务流程",
    re.I,
)

# Legacy name kept so older imports do not break. No longer injected.
IMAGE_ONLY_KB_BOOST = ""


def has_upload_image(text: str) -> bool:
    """True if message references an image under uploads/."""
    t = text or ""
    if _UPLOAD_IMAGE_LINE.search(t):
        return True
    if _UPLOAD_PATH.search(t):
        return True
    # generic uploads path + image extension anywhere
    if "uploads/" in t.replace("\\", "/") and _IMAGE_EXT.search(t):
        return True
    return False


def user_free_text(text: str) -> str:
    """Strip attachment boilerplate / path lines; what the user actually typed."""
    if not text:
        return ""
    lines_out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if _ATTACH_BOILERPLATE.search(s):
            continue
        if re.match(r"^[-*]\s*(图片|视频|文件|image|video|file)\s*[:：]", s, re.I):
            continue
        if _UPLOAD_PATH.search(s) and len(s) < 180:
            continue
        if s.startswith("说明：") and ("附件" in s or "上传" in s):
            continue
        lines_out.append(s)
    return "\n".join(lines_out).strip()


def is_image_only_turn(text: str) -> bool:
    """Upload image present and user typed no meaningful question (test / silent send)."""
    if not has_upload_image(text):
        return False
    free = user_free_text(text)
    if not free:
        return True
    # only punctuation / very short ack
    compact = re.sub(r"[\s\W_]+", "", free, flags=re.U)
    return len(compact) <= 1


def force_tools_from_text(text: str) -> set[str]:
    """Union of tools that should be force-included for this user text."""
    from app.tools.lookup import tool_registered, tools_in_group

    # Silent image upload: only an installed vision-group skill (if any).
    if is_image_only_turn(text):
        return set(tools_in_group("vision"))
    out: set[str] = set()
    for h in match_intents(text):
        out.update(h.tools)
    plan = classify_durable_persist(text)
    if plan:
        out.update(plan.force_tools)
    return {n for n in out if tool_registered(n)}


def required_tools_from_text(text: str) -> set[str]:
    """Tools that MUST ALL be called before a final answer is allowed.

    Note: durable-persist uses require_any_of via durable_persist_requirement()
    and is handled separately in Agent hard-retry (any-of semantics).
    """
    out: set[str] = set()
    for h in match_intents(text):
        if h.require_tool:
            out.update(h.require_any_of or h.tools)
    # Image-only: do not hard-require a specific vision skill here
    # (native multimodal models can see the image; core.py picks a skill if needed).
    return out


def durable_persist_requirement(text: str) -> DurablePersistPlan | None:
    """If this turn must persist knowledge, return the routing plan (any-of tools)."""
    return classify_durable_persist(text)


def extract_paths_from_tool_result(text: str, *, max_paths: int = 12) -> list[str]:
    """Pull workspace-relative path-like strings from tool JSON/text for filter query."""
    if not text:
        return []
    found: list[str] = []
    # common JSON keys
    for m in re.finditer(
        r'"(?:path|source|dest|deleted|script_path|filename|file|saved_paths?)"\s*:\s*"([^"]+)"',
        text,
    ):
        found.append(m.group(1))
    for m in re.finditer(
        r'"(?:files|entries)"\s*:\s*\[([^\]]*)\]',
        text,
    ):
        for m2 in re.finditer(r'"([^"]+\.[a-zA-Z0-9]{1,8})"', m.group(1)):
            found.append(m2.group(1))
    # bare relative paths
    for m in re.finditer(
        r"(?<![A-Za-z0-9_/\\])(?:uploads|images|videos|scratch|temp)/[\w./\\-]+",
        text,
    ):
        found.append(m.group(0).replace("\\", "/"))
    # dedupe preserve order
    out: list[str] = []
    seen: set[str] = set()
    for p in found:
        p = p.replace("\\", "/").strip()
        if not p or p in seen:
            continue
        if ".." in p:
            continue
        seen.add(p)
        out.append(p)
        if len(out) >= max_paths:
            break
    return out


def build_filter_query(
    base_query: str,
    *,
    path_hints: Iterable[str] | None = None,
    extra_tools: Iterable[str] | None = None,
) -> str:
    """Augment the tool soft-filter query with path tokens.

    Tool names are force-seated via ``force_tools``, not stuffed into the query
    (that made ``http`` match ``https://`` and unlocked meta tools by accident).
    """
    _ = extra_tools
    parts = [base_query if isinstance(base_query, str) else str(base_query or "")]
    paths = [str(p) for p in list(path_hints or []) if p]
    if paths:
        parts.append("paths: " + " ".join(paths[:12]))
    return "\n".join(p for p in parts if isinstance(p, str) and p.strip())
