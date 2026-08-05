"""Tool display / routing metadata (P1 + dynamic create_tool entries).

Only affects descriptions shown to the LLM (and optionally UI catalog).
Does NOT rename tools, change parameters, or disable anything.

Dynamic meta from create_tool is stored in data/tool_meta_dynamic.json and
merged at read time so new skills participate in P0–P2 routing without restarts
of the meta module (file is re-read on each lookup after cache invalidate).
"""

from __future__ import annotations

import json
import logging
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

# UI group ids (aligned with frontend CAPABILITY_GROUPS)
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
    # 识图
    "analyze_image_auto": {"role": "primary", "tag": "产品识图", "group": "vision"},
    # 媒体
    "grok_media": {"role": "primary", "tag": "生图/视频", "group": "media"},
    # 记忆
    "memory": {"role": "primary", "tag": "长期记忆", "group": "memory"},
    "kb": {"role": "primary", "tag": "知识库标准", "group": "memory"},
    "workflow": {"role": "primary", "tag": "工作流", "group": "schedule"},
    # 内容
    "product_multi_platform_publisher": {
        "role": "primary",
        "tag": "多平台文案",
        "group": "content",
    },
    # 工作区
    "workspace": {"role": "primary", "tag": "本地文件", "group": "workspace"},
    # 网络
    "http": {"role": "primary", "tag": "HTTP", "group": "network"},
    # 办公
    "office": {"role": "primary", "tag": "办公文档", "group": "office"},
    # 任务（仅 scheduled_task 对接设定→任务面板；reminders 已废弃）
    "scheduled_task": {"role": "primary", "tag": "定时任务", "group": "schedule"},
    "reminders": {"role": "legacy", "tag": "旧提醒·勿用", "group": "schedule"},
    # 资讯
    "search_ai_news": {"role": "primary", "tag": "资讯", "group": "news"},
    # 基础设施
    "nas": {"role": "primary", "tag": "NAS/SMB", "group": "infra"},
    "nocodb": {"role": "primary", "tag": "NocoDB", "group": "infra"},
    "qb_manager": {"role": "primary", "tag": "下载管理", "group": "infra"},
    "prowlarr": {"role": "primary", "tag": "索引器搜索", "group": "infra"},
    "radarr": {"role": "primary", "tag": "电影库", "group": "infra"},
    "sonarr": {"role": "primary", "tag": "剧集库", "group": "infra"},
    "daphile_player": {"role": "primary", "tag": "音乐播放", "group": "media"},
    "search_web": {"role": "primary", "tag": "网页搜索", "group": "network"},
    # 基础 / 元工具
    "get_current_time": {"role": "primary", "tag": "时间", "group": "dev"},
    "calculator": {"role": "primary", "tag": "计算", "group": "dev"},
    "system_info": {"role": "primary", "tag": "系统信息", "group": "dev"},
    "create_tool": {"role": "primary", "tag": "创建工具", "group": "dev"},
    "integrations": {"role": "primary", "tag": "集成配置", "group": "infra"},
    "netops": {"role": "primary", "tag": "网络运维", "group": "infra"},
    "read_skill": {"role": "primary", "tag": "读Skill", "group": "dev"},
    "delete_tool": {"role": "primary", "tag": "删工具", "group": "dev"},
    "reload_runtime": {"role": "primary", "tag": "热重载", "group": "dev"},
    "run_py": {"role": "primary", "tag": "跑脚本/装包", "group": "dev"},
    "list_api_models": {"role": "primary", "tag": "列模型", "group": "dev"},
    "server_health_check": {"role": "primary", "tag": "健康检查", "group": "dev"},
}

# Keyword → group for create_tool auto-classification (order matters: first hit wins).
_GROUP_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("vision", ("识图", "看图", "产品图", "vision", "image analysis", "analyze_image")),
    ("media", ("生图", "改图", "视频", "image gen", "video", "grok_media", "文生图")),
    ("memory", ("记忆", "偏好", "remember", "memory", "recall")),
    ("content", ("文案", "种草", "营销", "小红书", "多平台", "publisher", "copywriting")),
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
            "nas", "smb", "共享盘", "nocodb", "qb", "bt", "下载", "数据库", "qbit",
            "prowlarr", "radarr", "sonarr", "索引器", "pt",
        ),
    ),
    ("dev", ("脚本", "pip", "热重载", "health", "模型列表", "debug", "运维", "run_py")),
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
    if any(x in n for x in ("nas", "smb", "qb", "nocodb", "torrent")):
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
    return fb if fb in VALID_GROUPS else "other"


def resolve_group(
    name: str = "",
    group: str | None = None,
    description: str = "",
    keywords: list[str] | None = None,
) -> str:
    """Prefer explicit non-other group; otherwise infer."""
    g = (group or "").strip().lower()
    if g in VALID_GROUPS and g != "other":
        return g
    # known static tools
    static_g = (TOOL_META.get(name) or {}).get("group")
    if static_g and static_g in VALID_GROUPS and static_g != "other":
        return str(static_g)
    return infer_group(name, description, keywords, fallback=g or "other")

# Already-decorated descriptions start with these markers
_PREFIX_MARKERS = ("【主推", "【等价", "【后备", "【开发")

# Human-readable Chinese labels for UI / chat chips.
DISPLAY_NAMES: dict[str, str] = {
    "analyze_image_auto": "产品识图",
    "grok_media": "生图 / 视频",
    "memory": "长期记忆",
    "kb": "知识库标准",
    "workflow": "工作流",
    "product_multi_platform_publisher": "多平台文案",
    "workspace": "本地工作区",
    "http": "网络请求",
    "office": "办公文档",
    "scheduled_task": "定时任务",
    "reminders": "旧提醒(勿用)",
    "tasks": "定时任务",
    "search_ai_news": "AI / 科技资讯",
    "nas": "NAS / 共享盘",
    "nocodb": "NocoDB 数据库",
    "qb_manager": "qBittorrent 下载",
    "get_current_time": "当前时间",
    "calculator": "计算器",
    "system_info": "系统信息",
    "create_tool": "创建工具",
    "integrations": "集成配置",
    "netops": "网络运维",
    "read_skill": "查看 Skill 源码",
    "delete_tool": "删除工具",
    "reload_runtime": "热重载运行时",
    "run_py": "运行 Python / 装包",
    "list_api_models": "列出 API 模型",
    "server_health_check": "服务器健康检查",
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
    "analyze_image_auto": (
        "识图", "分析图", "产品图", "看图", "图片分析", "vision", "product image",
    ),
    "grok_media": (
        "生图", "改图", "图生视频", "生成视频", "生成图片", "文生图", "主图视频",
        "image to video", "generate video", "generate image",
    ),
    "memory": ("记住", "记一下", "长期记忆", "记忆面板", "remember", "recall", "偏好"),
    "kb": (
        "知识库", "wiki", "百科", "手册", "sop", "SOP", "建页", "wiki页",
        "knowledge", "知识页", "流水线", "产品内容", "提示词标准", "错误规制",
        "handbook", "reference", "作业流程", "标准页",
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
    "office": ("excel", "pdf", "ppt", "word", "办公", "表格"),
    "http": (
        "请求", "接口", "http", "api", "爬", "抓网页", "网页", "url",
        "代理", "proxy", "flaresolverr", "cloudflare", "fetch",
    ),
    "workspace": (
        "工作区", "本地文件", "列目录", "读文件", "写文件", "删文件",
        "workspace", "重命名", "搜文件", "保存文件", "打开文件",
    ),
    "nas": ("nas", "smb", "共享盘"),
    "nocodb": ("nocodb", "数据库表"),
    "qb_manager": ("qb", "bt", "下载", "种子", "qbittorrent"),
    "scheduled_task": (
        "定时任务", "cron", "schedule", "排程", "每隔", "每天跑", "任务面板",
    ),
    # reminders deprecated — do not boost
    "search_ai_news": ("资讯", "新闻", "热点", "科技", "ai新闻", "tech news"),
    "run_py": ("运行脚本", "跑python", "run py", "pip", "装包", "安装包"),
    "create_tool": ("创建工具", "新建工具", "create tool", "新 skill", "做成工具"),
    "integrations": (
        "集成", "连接配置", "凭证", "api key", "密码配置", "主机表",
        "设定集成", "ssh配置", "保存主机", "integrations",
    ),
    "netops": (
        "netops", "ping", "ssh", "端口扫描", "网段扫描", "运维", "tracert", "scp",
    ),
}


def _dynamic_path() -> Path:
    try:
        from app.config import get_settings

        return Path(get_settings().data_dir) / "tool_meta_dynamic.json"
    except Exception:
        from app.config import PROJECT_ROOT

        return PROJECT_ROOT / "data" / "tool_meta_dynamic.json"


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
    group_n = resolve_group(
        safe,
        group,
        description_hint or "",
        keywords,
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

    Dynamic ``group=other`` does not wipe a better static/inferred group.
    """
    base = dict(TOOL_META.get(name) or {})
    dyn = load_dynamic_meta().get(name)
    if not dyn and name not in TOOL_META:
        dyn = load_dynamic_meta(force=True).get(name)
    if dyn:
        out = dict(base)
        dyn_clean = {k: v for k, v in dyn.items() if v is not None and v != ""}
        # Prefer non-other group from static or re-resolve
        dyn_g = str(dyn_clean.get("group") or "").lower()
        base_g = str(out.get("group") or "").lower()
        if dyn_g in ("", "other") and base_g and base_g != "other":
            dyn_clean.pop("group", None)
        out.update(dyn_clean)
        # Final group resolution
        out["group"] = resolve_group(
            name,
            out.get("group"),
            str(out.get("description_hint") or out.get("tag") or ""),
            list(out.get("scene_keywords") or []),
        )
        if dyn_clean.get("dynamic") is not False:
            # Only mark dynamic when entry originated from create_tool file
            out["dynamic"] = True
        return out
    if base:
        if not base.get("group"):
            base["group"] = resolve_group(name, None, str(base.get("tag") or ""), None)
        return base
    return base


def decorate_description(name: str, description: str | None) -> str:
    """Return description with routing prefix for LLM / catalog display."""
    desc = (description or "").strip()
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


def user_prompt_override(name: str, *, skill_id: str | None = None) -> str | None:
    """Config-stored user edit of tool/skill prompt (no code change)."""
    try:
        from app.config_store import get_config_store

        store = get_config_store()
        o = store.get_tool_prompt_override(name)
        if o:
            return o
        if skill_id:
            return store.get_skill_prompt_override(skill_id)
        # skill package often shares id with tool name
        return store.get_skill_prompt_override(name)
    except Exception:
        return None


def effective_description(
    name: str,
    description: str | None,
    *,
    skill_id: str | None = None,
) -> str:
    """Description actually shown to the LLM / UI (override + routing prefix)."""
    base = user_prompt_override(name, skill_id=skill_id)
    if base is None:
        base = (description or "").strip()
    return decorate_description(name, base)


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


def _scene_phrases_for(name: str) -> tuple[str, ...]:
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


def routing_instruction() -> str:
    """Short system add-on: one primary tool per capability."""
    return (
        "TOOL ROUTING:\n"
        "HARD RULES (must follow):\n"
        "1. 通用 HTTP / API / 抓网页 / 代理 / Cloudflare：只能用 `http` "
        "（use_proxy / use_flaresolverr）。禁止为此新建 skill。\n"
        "2. 禁止为单次请求 create_tool；已有工具能完成则禁止创建。\n"
        "3. create_tool 仅当用户明确要求「做成固定工具 / 新建 skill」且现有工具无法覆盖。\n"
        "4. 本地文件：只能用 `workspace`（action=list|read|write|delete|find|rename|info）。"
        "路径相对项目 workspace/ 根，勿加 workspace/ 前缀。\n"
        "5. 识图 → analyze_image_auto；生图/视频 → grok_media；"
        "办公文档 → office；资讯 → search_ai_news；跑脚本/pip → run_py。\n"
        "6. 持久化智能分发（用户说记住/保存/别忘了时）：\n"
        "  · 短偏好/习惯/规则/一句话事实 → memory remember\n"
        "  · 库表/字段/清单/手册/SOP/长结构 → kb create_page|update_page|append|delete\n"
        "  · 可重复多步骤自动化 → workflow create|update|delete\n"
        "  · **主机/账号/密码/Token/API 地址/SSH 主机表 → integrations（禁止塞进 kb）**\n"
        "  · 禁止一律只写 memory；禁止只口头「好的记住了」。\n"
        "  产品图多轮：识图后按 kb「产品内容流水线SOP」(collection=sop) 推进；"
        "摘要不全时 kb get 全文，禁止编造阶段步骤。\n"
        "\n"
        "能力地图（每类唯一入口）:\n"
        "  · 产品识图 → analyze_image_auto\n"
        "  · 生图/视频 → grok_media\n"
        "  · 长期记忆 → memory；知识库标准(sop/product/handbook/reference) → kb；工作流 → workflow\n"
        "  · **连接配置/密钥 → integrations**（设定→集成）\n"
        "  · 通用 HTTP → http\n"
        "  · 本地文件 → workspace\n"
        "  · 办公文档 → office\n"
        "  · 定时任务（设定→任务面板）→ scheduled_task；勿用已停用的 reminders\n"
        "  · 资讯 → search_ai_news\n"
        "  · NAS → nas；NocoDB → nocodb；BT下载 → qb_manager；网络运维 → netops\n"
        "  · 跑脚本/装包 → run_py\n"
        "- Soft Top-N may limit tools per turn; always-include cores stay available.\n"
        "- create_tool / delete_tool 策略:\n"
        "  · 不可动：builtin（workspace/memory/时间计算/create_tool…）与受保护系统 skill"
        "（reload_runtime、list_api_models、server_health_check）。\n"
        "  · 可 create/update/delete：其余业务 skill（http、office、nas、grok_media、netops 等）"
        "及用户新建 skill。\n"
        "  · 勿用 create_tool 包装 workspace/http 已覆盖的能力。\n"
        "  · **凭证与主机表：create_tool 只写代码逻辑；配置用 integrations upsert**"
        "（与 skill 同名或 catalog：nas/nocodb/qbittorrent/http/netops）。"
        "代码内 from app.services.credentials 读取；禁止硬编码密钥，禁止把密钥写进 kb。\n"
        "  · **修/改已有能力：必须 read_skill(主入口名) → create_tool(name=同一主入口, update=true)**；"
        "禁止新建 nas_v2 / xxx_fixed / xxx_new 等等价 skill。\n"
        "  · 新建时务必传 group（vision|media|network|infra|office|dev…），"
        "description 含中文场景词；Python 优先写 async def handle + 让系统包 register，"
        "或 register 内 registry.register 的名字必须与 create_tool 的 name 完全一致。\n"
    )
