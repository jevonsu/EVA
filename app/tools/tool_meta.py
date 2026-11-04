"""Tool display / routing metadata (P1 + dynamic create_tool entries).

Only affects descriptions shown to the LLM (and optionally UI catalog).
Does NOT rename tools, change parameters, or disable anything.

Dynamic meta from create_tool is stored in data/tools/meta_dynamic.json and
merged at read time so new skills participate in P0–P2 routing without restarts
of the meta module (file is re-read on each lookup after cache invalidate).
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# role -> short Chinese label for description prefix
ROLE_PREFIX: dict[str, str] = {
    "primary": "主推",
    "equivalent": "等价·仍可用",
    "fallback": "后备",
    "dev": "开发/运维",
}

# Default UI group ids (live set lives in capability_groups.json).
VALID_GROUPS = frozenset({
    "vision", "media", "memory", "content", "workspace", "network",
    "office", "schedule", "news", "infra", "dev", "other",
})
VALID_ROLES = frozenset({"primary", "equivalent", "fallback", "dev"})

_dynamic_lock = threading.RLock()
_dynamic_cache: dict[str, dict[str, Any]] | None = None
_dynamic_mtime: float | None = None

# Consolidated: one primary per capability; no equivalent tools exposed.
# group aligns with frontend CAPABILITY_GROUPS (vision/media/…/other).
TOOL_META: dict[str, dict[str, str]] = {
    "memory": {"role": "primary", "tag": "长期记忆", "group": "memory"},
    "kb": {"role": "primary", "tag": "知识库", "group": "memory"},
    "workflow": {"role": "primary", "tag": "工作流", "group": "schedule"},
    "workspace": {"role": "primary", "tag": "本地文件", "group": "workspace"},
    "scheduled_task": {"role": "primary", "tag": "定时任务", "group": "schedule"},
    "get_current_time": {"role": "primary", "tag": "时间", "group": "dev"},
    "ask_user": {"role": "primary", "tag": "问用户", "group": "dev"},
    "calculator": {"role": "primary", "tag": "计算", "group": "dev"},
    "system_info": {"role": "primary", "tag": "系统信息", "group": "dev"},
    "update_persona": {"role": "primary", "tag": "人设", "group": "dev"},
    "create_tool": {"role": "primary", "tag": "创建工具", "group": "dev"},
    "capability_groups": {"role": "primary", "tag": "技能分类", "group": "dev"},
    "integrations": {"role": "primary", "tag": "集成配置", "group": "infra"},
    "llms": {"role": "primary", "tag": "对话模型", "group": "dev"},
    "read_skill": {"role": "primary", "tag": "读Skill", "group": "dev"},
    "list_skills": {"role": "primary", "tag": "列Skill", "group": "dev"},
    "validate_skill": {"role": "primary", "tag": "校验Skill", "group": "dev"},
    "promote_skill": {"role": "primary", "tag": "发布Skill", "group": "dev"},
    "delete_tool": {"role": "primary", "tag": "删工具", "group": "dev"},
    "reload_runtime": {"role": "primary", "tag": "热重载", "group": "dev"},
    "list_api_models": {"role": "primary", "tag": "列模型", "group": "dev"},
    "server_health_check": {"role": "primary", "tag": "健康检查", "group": "dev"},
    "terminal": {"role": "primary", "tag": "终端", "group": "dev"},
    "document": {"role": "primary", "tag": "文档", "group": "office"},
}

# Keyword → group for create_tool auto-classification (order matters: first hit wins).
_GROUP_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("vision", ("识图", "看图", "图片", "vision", "image analysis")),
    ("media", ("生图", "改图", "视频", "image gen", "video", "文生图")),
    ("memory", ("记忆", "偏好", "remember", "memory", "recall")),
    ("content", ("文案", "营销", "多平台", "copywriting")),
    ("workspace", ("工作区", "本地文件", "workspace", "读写文件")),
    (
        "network",
        (
            "http", "api", "爬虫", "抓网页", "proxy", "网络请求", "fetch", "url",
            "天气", "weather", "预报", "汇率", "rest",
        ),
    ),
    ("office", ("excel", "pdf", "ppt", "word", "办公", "表格", "文档")),
    ("schedule", ("定时", "cron", "schedule", "提醒", "reminder", "任务调度")),
    ("news", ("资讯", "新闻", "热点", "news")),
    (
        "infra",
        (
            "主机", "ssh", "smb", "共享盘", "数据库",
        ),
    ),
    ("dev", ("脚本", "pip", "热重载", "health", "模型列表", "debug", "运维")),
]


def infer_group(
    name: str = "",
    description: str = "",
    keywords: list[str] | None = None,
    *,
    fallback: str = "other",
) -> str:
    """Infer UI/capability group from name + description + keywords."""
    parts = [name or "", description or ""]
    if keywords:
        parts.extend(str(k) for k in keywords)
    blob = " ".join(parts).lower()
    # Chinese kept as-is for substring match
    blob_raw = " ".join(parts)
    for gid, hints in _GROUP_HINTS:
        for h in hints:
            hl = h.lower()
            if hl in blob or h in blob_raw:
                return gid
    # name token heuristics
    n = (name or "").lower()
    if any(x in n for x in ("smb", "ssh", "host")):
        return "infra"
    if any(x in n for x in ("http", "api", "fetch", "crawl", "proxy")):
        return "network"
    if any(x in n for x in ("office", "excel", "pdf", "ppt", "docx")):
        return "office"
    if any(x in n for x in ("image", "video", "media", "vision")):
        return "media" if "vision" not in n and "识图" not in blob_raw else "vision"
    if any(x in n for x in ("news", "rss")):
        return "news"
    if any(x in n for x in ("task", "remind", "cron", "schedule")):
        return "schedule"
    if any(x in n for x in ("memory", "pref")):
        return "memory"
    fb = (fallback or "other").strip().lower()
    try:
        from app.tools.capability_groups import valid_ids

        ids = valid_ids()
    except Exception:
        ids = set(VALID_GROUPS)
    return fb if fb in ids else "other"


def resolve_group(
    name: str = "",
    group: str | None = None,
    description: str = "",
    keywords: list[str] | None = None,
    *,
    infer: bool = False,
    create: bool = False,
) -> str:
    """Resolve a capability group id.

    Default (infer=False): respect the stored/explicit group, including
    ``other``. Empty group stays ``other`` and is NOT keyword-inferred.
    create=True turns an unknown label into a new user group (Eva / UI).
    """
    try:
        from app.tools.capability_groups import ensure_group, match_group, valid_ids
    except Exception:
        ensure_group = None  # type: ignore[assignment]
        match_group = None  # type: ignore[assignment]
        valid_ids = None  # type: ignore[assignment]

    raw = (group or "").strip()
    if raw:
        found = match_group(raw) if match_group else None
        if found:
            return str(found["id"])
        if create and ensure_group:
            try:
                created = ensure_group(raw)
                return str(created.get("id") or "other")
            except Exception:
                logger.exception("ensure_group(%r) failed", raw)
        ids = set()
        try:
            ids = valid_ids() if valid_ids else set(VALID_GROUPS)
        except Exception:
            ids = set(VALID_GROUPS)
        low = raw.lower()
        if low in ids:
            return low
        if _ID_LIKE.match(raw):
            return low
        return "other"

    static_g = str((TOOL_META.get(name) or {}).get("group") or "").strip()
    if static_g:
        found = match_group(static_g) if match_group else None
        if found:
            return str(found["id"])
        if static_g.lower() in VALID_GROUPS:
            return static_g.lower()
    if infer:
        return infer_group(name, description, keywords, fallback="other")
    return "other"


_ID_LIKE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")

# Already-decorated descriptions start with these markers
_PREFIX_MARKERS = ("【主推", "【等价", "【后备", "【开发")

# Human-readable Chinese labels for UI / chat chips.
DISPLAY_NAMES: dict[str, str] = {
    "memory": "长期记忆",
    "kb": "知识库",
    "workflow": "工作流",
    "workspace": "本地工作区",
    "scheduled_task": "定时任务",
    "get_current_time": "当前时间",
    "calculator": "计算器",
    "system_info": "系统信息",
    "update_persona": "修改人设",
    "create_tool": "创建工具",
    "capability_groups": "技能分类",
    "integrations": "集成配置",
    "llms": "对话模型",
    "read_skill": "查看 Skill 源码",
    "list_skills": "列出 Skills",
    "validate_skill": "校验 Skill",
    "promote_skill": "发布 Skill 草稿",
    "delete_tool": "删除工具",
    "reload_runtime": "热重载运行时",
    "list_api_models": "拉取远程 /models",
    "server_health_check": "服务器健康检查",
    "terminal": "受控终端",
    "document": "办公文档",
}


def display_name_for(name: str | None) -> str:
    """Return a short Chinese label for UI; fall back to prettified call name."""
    key = (name or "").strip()
    if not key:
        return ""
    if key in DISPLAY_NAMES:
        return DISPLAY_NAMES[key]
    try:
        meta = meta_for(key)
        tag = str(meta.get("tag") or "").strip()
        if tag and any("\u4e00" <= c <= "\u9fff" for c in tag):
            return tag
    except Exception:
        pass
    return key.replace("_", " ").strip().title()


def build_prefix(meta: dict[str, str]) -> str:
    role = (meta.get("role") or "").strip()
    role_label = ROLE_PREFIX.get(role)
    if not role_label:
        return ""
    tag = (meta.get("tag") or "").strip()
    if tag:
        return f"【{role_label}·{tag}】"
    return f"【{role_label}】"


# Extra Chinese/English scene phrases → tool name (soft match boost only)
SCENE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "memory": ("记住", "记一下", "长期记忆", "记忆面板", "remember", "recall", "偏好"),
    "kb": (
        "知识库", "wiki", "百科", "手册", "sop", "SOP", "建页", "wiki页",
        "knowledge", "知识页", "handbook", "reference", "作业流程", "标准页",
    ),
    "workflow": (
        "工作流",
        "流水线",
        "workflow",
        "跑流程",
        "执行流程",
        "多步骤",
        "创建工作流",
        "新建流程",
        "修改流程",
        "删除流程",
        "删除工作流",
    ),
    "workspace": (
        "工作区", "本地文件", "列目录", "读文件", "写文件", "删文件",
        "workspace", "重命名", "搜文件", "保存文件", "打开文件",
    ),
    "scheduled_task": (
        "定时任务", "定时", "cron", "schedule", "排程", "每隔", "每天跑",
        "每三天", "任务面板", "提醒", "闹钟",
    ),
    "get_current_time": (
        "几点", "现在几点", "当前时间", "几点了", "现在时间", "what time", "date now",
        "今天几号", "几号", "星期几", "礼拜几", "今日", "日期", "几时", "幾點", "幾時", "而家", "宜家", "時間", "时间", "现在是",
    ),
    "create_tool": ("创建工具", "新建工具", "create tool", "新 skill", "做成工具"),
    "capability_groups": (
        "技能分类", "工具分类", "能力分组", "改分类", "新建分组", "分组",
    ),
    "integrations": (
        "集成", "连接配置", "密码配置", "主机表",
        "设定集成", "ssh", "ssh配置", "保存主机", "密钥", "账号密码",
        "integrations",
    ),
    "llms": (
        "llm", "大模型", "对话模型", "设定llm", "设定模型", "换模型", "默认模型",
        "openai", "deepseek", "grok", "xai", "api key", "api_key", "base_url",
    ),
    "reload_runtime": (
        "热重载", "重载运行时", "reload runtime", "刷新工具",
        "重新加载技能", "重载配置",
    ),
    "list_api_models": (
        "模型列表", "可用模型", "远程模型", "/models",
        "中转站模型", "拉取模型", "供应商模型",
    ),
    "server_health_check": (
        "健康检查", "服务器状态", "cpu占用", "内存占用",
        "磁盘空间", "本机健康", "health check",
    ),
    "terminal": (
        "终端", "命令行", "执行命令", "pip", "pip install", "npm",
        "跑脚本", "安装依赖", "git clone", "cmd", "powershell",
    ),
    "document": (
        "word", "excel", "ppt", "pdf", "markdown", "docx", "xlsx", "pptx",
        "文档", "表格", "幻灯片", "读写excel", "编辑word", "做ppt", "看pdf",
        "办公文档", "markdown文档",
    ),
}


def _dynamic_path() -> Path:
    try:
        from app.config import get_settings

        return get_settings().paths().tool_meta_dynamic
    except Exception:
        from app.config import PROJECT_ROOT

        # Fallback before settings fully bootstrapped
        return PROJECT_ROOT / "data" / "tools" / "meta_dynamic.json"


def load_dynamic_meta(*, force: bool = False) -> dict[str, dict[str, Any]]:
    """Load create_tool-written meta entries (cached; auto-refresh on file mtime)."""
    global _dynamic_cache, _dynamic_mtime
    with _dynamic_lock:
        path = _dynamic_path()
        mtime: float | None = None
        try:
            if path.exists():
                mtime = path.stat().st_mtime
        except OSError:
            mtime = None

        if (
            not force
            and _dynamic_cache is not None
            and _dynamic_mtime == mtime
        ):
            return _dynamic_cache

        data: dict[str, dict[str, Any]] = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8") or "{}")
                if isinstance(raw, dict):
                    for k, v in raw.items():
                        if isinstance(k, str) and isinstance(v, dict):
                            data[k] = dict(v)
            except Exception:
                logger.exception("failed to load dynamic tool meta from %s", path)
        _dynamic_cache = data
        _dynamic_mtime = mtime
        return data


def invalidate_dynamic_meta_cache() -> None:
    global _dynamic_cache, _dynamic_mtime
    with _dynamic_lock:
        _dynamic_cache = None
        _dynamic_mtime = None


def upsert_dynamic_meta(
    name: str,
    *,
    role: str = "primary",
    tag: str = "",
    group: str = "other",
    scene_keywords: list[str] | None = None,
    description_hint: str = "",
    version: str = "",
    changelog: str = "",
) -> dict[str, Any]:
    """Persist meta for a create_tool skill so P0–P2 can see it."""
    safe = (name or "").strip()
    if not safe:
        raise ValueError("name required")
    role_n = (role or "primary").strip().lower()
    if role_n not in VALID_ROLES:
        role_n = "primary"
    keywords = []
    for k in scene_keywords or []:
        s = str(k).strip()
        if s and s not in keywords:
            keywords.append(s)
    existing = load_dynamic_meta().get(safe) or {}
    g_in = (group or "").strip() or str(existing.get("group") or "")
    group_n = resolve_group(
        safe,
        g_in or "other",
        description_hint or "",
        keywords,
        infer=False,
        create=True,
    )
    tag_n = (tag or safe).strip()[:32]
    entry = {
        "role": role_n,
        "tag": tag_n,
        "group": group_n,
        "scene_keywords": keywords,
        "dynamic": True,
        "description_hint": (description_hint or "")[:200],
    }
    if version:
        entry["version"] = str(version)[:32]
    if changelog:
        entry["changelog"] = str(changelog)[:500]
    with _dynamic_lock:
        data = dict(load_dynamic_meta(force=True))
        data[safe] = entry
        path = _dynamic_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
        global _dynamic_cache, _dynamic_mtime
        _dynamic_cache = data
        _dynamic_mtime = mtime
    return entry


def remove_dynamic_meta(name: str) -> bool:
    safe = (name or "").strip()
    if not safe:
        return False
    with _dynamic_lock:
        data = dict(load_dynamic_meta(force=True))
        if safe not in data:
            return False
        del data[safe]
        path = _dynamic_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
        global _dynamic_cache, _dynamic_mtime
        _dynamic_cache = data
        _dynamic_mtime = mtime
    return True


def meta_for(name: str) -> dict[str, Any]:
    """Static TOOL_META first, then dynamic create_tool entries.

    Stored ``group`` (including ``other``) is kept. Keyword inference is
    not re-run on read, so Eva/user classification is not overwritten.
    """
    base = dict(TOOL_META.get(name) or {})
    dyn = load_dynamic_meta().get(name)
    if not dyn and name not in TOOL_META:
        dyn = load_dynamic_meta(force=True).get(name)
    if dyn:
        out = dict(base)
        dyn_clean = {k: v for k, v in dyn.items() if v is not None and v != ""}
        out.update(dyn_clean)
        stored = str(out.get("group") or "").strip()
        out["group"] = resolve_group(
            name,
            stored or None,
            str(out.get("description_hint") or out.get("tag") or ""),
            list(out.get("scene_keywords") or []),
            infer=False,
        )
        if dyn_clean.get("dynamic") is not False:
            out["dynamic"] = True
        return out
    if base:
        stored = str(base.get("group") or "").strip()
        base["group"] = resolve_group(
            name,
            stored or None,
            str(base.get("tag") or ""),
            None,
            infer=False,
        )
        return base
    return base


def decorate_description(name: str, description: str | None) -> str:
    """Return description with routing prefix for LLM / catalog display."""
    desc = description if isinstance(description, str) else str(description or "")
    desc = desc.strip()
    if not desc:
        return desc
    if desc.startswith(_PREFIX_MARKERS):
        return desc
    meta = meta_for(name)
    if not meta:
        return desc
    prefix = build_prefix(meta)
    if not prefix:
        return desc
    return f"{prefix}{desc}"


def user_prompt_meta(name: str, *, skill_id: str | None = None) -> dict[str, Any] | None:
    """Config-stored user edit (description / how_to_call / extra keywords).

    When ``skill_id`` is omitted, returns the *tool* override only.
    When given, tool fields overlay the skill-package override (non-empty wins;
    keywords are unioned).
    """
    try:
        from app.config_store import get_config_store, prompt_meta_active

        store = get_config_store()
        tool_m = store.get_tool_prompt_meta(name)
        if skill_id is None:
            return tool_m
        skill_m = store.get_skill_prompt_meta(skill_id) or store.get_skill_prompt_meta(
            name
        )
        if not tool_m:
            return skill_m
        if not skill_m:
            return tool_m
        desc = str(tool_m.get("description") or "").strip() or str(
            skill_m.get("description") or ""
        ).strip()
        how = str(tool_m.get("how_to_call") or "").strip() or str(
            skill_m.get("how_to_call") or ""
        ).strip()
        kws: list[str] = []
        for src in (skill_m.get("scene_keywords"), tool_m.get("scene_keywords")):
            for k in src or []:
                s = str(k).strip()
                if s and s not in kws:
                    kws.append(s)
        merged = {
            "description": desc,
            "how_to_call": how,
            "scene_keywords": kws,
        }
        return merged if prompt_meta_active(merged) else None
    except Exception:
        return None


def user_prompt_override(name: str, *, skill_id: str | None = None) -> str | None:
    """Config-stored user edit of tool/skill prompt (no code change)."""
    meta = user_prompt_meta(name, skill_id=skill_id)
    if not meta:
        # skill_id omitted → still fall back to same-name skill description
        # so existing tool-only lookups keep working.
        if skill_id is None:
            meta = user_prompt_meta(name, skill_id=name)
        if not meta:
            return None
    text = str(meta.get("description") or "").strip()
    return text or None


def effective_description(
    name: str,
    description: str | None,
    *,
    skill_id: str | None = None,
) -> str:
    """Description actually shown to the LLM / UI (override + routing prefix)."""
    meta = user_prompt_meta(name, skill_id=skill_id)
    if meta is None and skill_id is None:
        meta = user_prompt_meta(name, skill_id=name)
    desc_ovr = str((meta or {}).get("description") or "").strip()
    base = desc_ovr or (description or "").strip()
    out = decorate_description(name, base)
    how = str((meta or {}).get("how_to_call") or "").strip()
    if how and how not in out:
        out = (out.rstrip() + f"\n用户可能这样喊：{how}").strip()
    return out


def tool_role(name: str) -> str:
    meta = meta_for(name) or {}
    return str(meta.get("role") or "")


def role_score_boost(name: str) -> int:
    """Small ranking boost for filter_tools (primary preferred; never excludes)."""
    role = tool_role(name)
    return {
        "primary": 4,
        "fallback": 2,
        "equivalent": 1,
        "dev": 0,
    }.get(role, 0)


def builtin_scene_keywords(name: str) -> tuple[str, ...]:
    """Code + create_tool keywords (not user extras)."""
    static = list(SCENE_KEYWORDS.get(name) or ())
    dyn = load_dynamic_meta().get(name) or {}
    for k in dyn.get("scene_keywords") or []:
        s = str(k).strip()
        if s and s not in static:
            static.append(s)
    tag = str(dyn.get("tag") or (TOOL_META.get(name) or {}).get("tag") or "").strip()
    if tag and tag not in static:
        static.append(tag)
    return tuple(static)


def _user_scene_keywords(name: str) -> list[str]:
    meta = user_prompt_meta(name, skill_id=name) or {}
    out: list[str] = []
    for k in meta.get("scene_keywords") or []:
        s = str(k).strip()
        if s and s not in out:
            out.append(s)
    return out


def _scene_phrases_for(name: str) -> tuple[str, ...]:
    static = list(builtin_scene_keywords(name))
    for s in _user_scene_keywords(name):
        if s not in static:
            static.append(s)
    return tuple(static)


def scene_score_boost(name: str, query: str) -> int:
    """Boost score when query contains tool-specific scene phrases."""
    if not query:
        return 0
    q = query.lower()
    phrases = _scene_phrases_for(name)
    boost = 0
    for p in phrases:
        if p.lower() in q:
            boost += 12
    return boost


# P2 soft Top-N defaults (env can override via registry)
DEFAULT_TOOL_TOP_N = 20
MIN_CONFIDENT_MATCH_SCORE = 6


def routing_instruction_core() -> str:
    """Always-on routing: persist + cores. Skill-dev rules are separate."""
    return (
        "TOOL ROUTING:\n"
        "- Use only tools listed this turn. Cores always listed: "
        "memory/kb/workspace/time. "
        "If a scrape/http skill is installed, use that for URLs. "
        "workflow / scheduled_task / integrations / llms / terminal / document / "
        "reload_runtime / list_api_models / server_health_check appear when needed "
        "(or the user says 全部工具). "
        "CLI/pip/npm/scripts → terminal (workspace; long jobs action=bg). "
        "Word/Excel/PPT/PDF/Markdown → document.\n"
        "- Persist 记住/保存: short prefs→memory; long docs→kb; "
        "automation→workflow; business tables→an installed data skill if any; "
        "chat model keys→llms; business API secrets→integrations "
        "(single fields or items table). Never only say 记住了.\n"
        "- Local files: dirs/rename/txt/code/images → `workspace`; "
        ".docx .xlsx .pptx .pdf → `document`; "
        ".md either (short note→workspace, structured edit→document). "
        "WRITE PATHS: only uploads/docs/exports/scratch/images/videos/skills. "
        "New drafts → scratch/; deliverables → exports/; office drafts → docs/. "
        "NEVER create files at workspace root. "
        "Overwrite existing file → ask_user first, then overwrite=true. "
        "Bare/unknown paths are rewritten under scratch/. "
        "Paths relative to workspace/, no workspace/ prefix.\n"
        "- Do not create_tool for a one-off if an existing tool can do it.\n"
        "- Missing capability → spec card then create_tool; "
        "don't invent 'no permission'."
    )



def routing_instruction_skilldev() -> str:
    """Injected only when create/read/list skill tools are unlocked this turn."""
    return (
        "SKILL LIFECYCLE:\n"
        "- Protected: builtin + reload_runtime / list_api_models / server_health_check / terminal / document.\n"
        "- Shell/pip/npm/scripts → terminal (cwd=workspace; long jobs action=bg). "
        "Not a full admin shell.\n"
        "- Office files → document; do not create_tool for docx/xlsx/pptx/pdf/md.\n"
        "- Spec card first; vague 好/行/随便 is not confirmation.\n"
        "- New skills default live and callable this turn; copy usage.tell_user.\n"
        "- create_tool group: pick from capability_groups (id or 中文名). "
        "Omit → 其它. Do not guess from keywords.\n"
        "- Chat model creds → llms; business API → integrations "
        "(single url/token, or items table for many rows); "
        "never bake secrets into handler/kb.\n"
        "- Fix existing: read_skill → restate → create_tool(name=same, update=true). "
        "No _v2/_fixed names.\n"
        "- Delete: restate name+purpose → delete_tool(confirm_name=same).\n"
        "- Action-style skills: parameters.action.enum of every branch; "
        "list/query/search include limit (default 50). Never register empty properties:{}.\n"
        "- LAN APIs: app.services.skill_http.request + integration_config; "
        "never spoof Host=localhost. "
        "HTTP 502 → check 设定→集成; do not rewrite the skill or delete it."
    )


def routing_instruction(*, skilldev: bool = True) -> str:
    """Short system add-on: one primary tool per capability."""
    parts = [routing_instruction_core()]
    if skilldev:
        parts.append(routing_instruction_skilldev())
    return "\n".join(parts)


def llm_catalog_instruction() -> str:
    """Compact 设定→LLM snapshot so the agent can pick a model without guessing."""
    try:
        from app.services.credentials import list_llms_public

        items = list_llms_public()
    except Exception:
        items = []
    if not items:
        return (
            "LLM CATALOG (设定→LLM): 目前没有已保存的对话模型。"
            "用户若提供供应商 key/地址/模型名，必须用工具 llms action=upsert 写入设定→LLM，"
            "禁止写入 integrations。"
        )
    lines = ["LLM CATALOG (设定→LLM) — 技能调模型用 llm_credentials(id)，不要问用户重复贴已保存的 key："]
    for row in items[:12]:
        flag = []
        if row.get("is_default"):
            flag.append("默认")
        if not row.get("enabled", True):
            flag.append("停用")
        if not row.get("api_key_set"):
            flag.append("无key")
        tag = f" [{' '.join(flag)}]" if flag else ""
        lines.append(
            f"  · id={row.get('id')} name={row.get('name') or '-'} "
            f"model={row.get('model') or '-'} provider={row.get('provider') or '-'}{tag}"
        )
    lines.append(
        "新供应商凭据 → llms upsert；本机已保存 → llms list；"
        "拉远程 /models → list_api_models（任意站点）或 llms action=models（已保存项）。"
    )
    return "\n".join(lines)
