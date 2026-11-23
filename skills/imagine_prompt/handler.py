"""imagine_prompt —「Grok提示词」技能：生成 / 检查 Grok Imagine 图像与视频提示词。

与 EVA 侧栏「Grok提示词」网页工具同源：用 Node 运行同目录的 engine.js + core_bundle.js
（core_bundle.js 由网页工具的同一次构建生成，含模式 / 表单 / 选项 / 拼装 / 检查 / 参数规则）。
- 只生成文字，不调用图像/视频生成接口。
- 动态参数、参数更新记录、选项库复用 app/api/prompt_studio.py（data/prompt_studio_params.json 等）。
- 手动联网更新参数、识图只在用户明确要求时执行（confirm=true）。
- 找不到 Node 时退回旧版纯 Python 规则（结果标注 engine=legacy，不保证与网页一致）。
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
HERE = Path(__file__).resolve().parent
ENGINE = HERE / "engine.js"
BUNDLE = HERE / "core_bundle.js"
NODE_TIMEOUT_S = 20
TOOL_HTML_REL = Path("app") / "static" / "tools" / "imagine-prompt-studio.html"
MAX_HISTORY_BYTES = 5 * 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024
VIS_TTL_S = 6 * 3600
_VIS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}  # vision_id -> (time, {minor, real, spicy_block})
_BUILD_RE = re.compile(r"const IPS_BUILD='([0-9a-f]{6,40})'")


# ============================== 旧版纯 Python 规则（无 Node 时兜底 / 旧 parts 拼装） ==============================
LEGACY_MODES = {
    "t2i": "文生图",
    "i2i": "图生图",
    "i2v": "图生视频",
    "t2v": "文生视频",
    "ref": "参考图生视频",
}

LEGACY_GUIDE = {
    "t2i": "推荐结构（经验总结，xAI 未发布官方 Imagine 提示词指南）：subject 主体(必须最前) → details 细节/机位 → art 美术与道具 → light 光线(光源/方向/硬度) → color 色彩(主体与背景分开) → composition 构图(裁切/锐度/单一场景)；人物类加 depth 纵深。",
    "i2i": "先改后保：change 只写要改的部分（不要重写整段场景），再 preserve 列出具体保留项（face/expression/pose/clothing/background/lighting/camera angle…）；换背景时加 match_light。",
    "i2v": "只描述变化：一个主要动作 action + 一个机位 camera + env 环境响应(不要发明新物体) + preserve 保留 + sound/dialogue；2–3 句为宜。",
    "t2v": "第一帧优先：first_frame 写清静态构图(主体明确成年/虚构、服装、场景、光线)，beats 用 then 串联 1–2 个节拍，一个 camera，continuity 写必须保持的内容，sound 指定音频。",
    "ref": "参考图：refs 按顺序编号 <IMAGE_0>、<IMAGE_1>…；若 first_frame_image=true，首帧占 <IMAGE_0>，参考图从 <IMAGE_1> 开始。每张图只承担一个角色；角色少；道具静止。1.5 最多14张/15秒/720p，旧版最多7张/10秒，1.5-lite 不支持。",
}

DEPTH = {
    "shallow": "shallow depth of field",
    "foreground": "a softly blurred element in the foreground",
    "layered": "layered composition with clear foreground, midground and background",
    "atmospheric": "distant elements fade into atmospheric haze",
    "focus": "sharp focus on the subject, soft background",
    "reflections": "reflections on wet pavement",
}

HARD = [
    ("未成年人", re.compile(r"\b(child|children|kids?|little (girl|boy)|loli|lolita|shota|underage|under-age|teens?|teenagers?|teenage|schoolgirls?|schoolboys?|toddlers?|preteens?|minors)\b", re.I)),
    ("未成年人", re.compile(r"(儿童|小孩|少女(?!感)|萝莉|正太|学生妹|未成年|幼女|幼童|女童|男童|小学生|初中生|中学生)")),
    ("非同意性化", re.compile(r"\b(nudify|non-?consensual|deepfakes?|upskirt|hidden camera|spycam)\b", re.I)),
    ("非同意性化", re.compile(r"(偷拍|裸化|深度伪造|强迫|强制|换脸)")),
    ("违法内容", re.compile(r"\b(csam|bestiality|zoophilia)\b", re.I)),
    ("违法内容", re.compile(r"(儿童色情|兽交)")),
]
RISKY = [
    ("年龄模糊", re.compile(r"\b(young|youthful|young-looking|teen-like|school uniform|petite girl)\b|年轻|少女感|看起来很小|校服|稚嫩|童颜", re.I), "明确写 fictional adult 或具体年龄（如 in her mid-20s）"),
    ("真实暗示", re.compile(r"\b(real person|real people|celebrity|celebrities|actual photo|real photo)\b|真人照片|真实人物|明星|名人", re.I), "写 fictional / AI generated character，不使用真实人物或明星名"),
    ("过度性化", re.compile(r"\b(nude|naked|explicit|genitals?|topless|nsfw)\b|全裸|裸体|裸露|性器官|露点", re.I), "容易被拒；成人内容仅适用于辣椒模式下明确的虚构成年角色，硬性底线不变"),
    ("暴力相关", re.compile(r"\b(gore|gory|dismember\w*|real injury|bloodbath|mutilat\w*)\b|血腥|肢解|真实伤害|断肢", re.I), "虚构场景需谨慎，避免指令性语言"),
]
WEAK = [
    (re.compile(r"\b(8k|4k|16k|masterpiece|high quality|best quality|ultra[- ]detailed|highly detailed)\b|高质量|杰作|超清", re.I), "质量词效果有限，改写具体光线/材质/镜头"),
    (re.compile(r"\b(perfect face|no distortion)\b|完美脸", re.I), "模糊指令，改为具体特征 + preserve"),
    (re.compile(r"\b(no blur|not shiny|without text|no text|not blurry)\b|不要模糊", re.I), "负面列表易被忽略，直接描述想要的材质与清晰度"),
    (re.compile(r"\bkeep everything\b|保持一切", re.I), "保留太笼统，写具体 preserve 列表"),
    (re.compile(r"\b(beautiful|gorgeous|stunning|sexy|hot|pretty)\b|美丽|漂亮|性感", re.I), "过于主观，写具体服装/姿态/光线"),
]
SEXUAL = re.compile(r"\b(nude|naked|sexy|sheer|lingerie|erotic|topless|seductive|sensual|nsfw|explicit|bikini)\b|性感|裸|情趣|内衣|诱惑|薄纱|色情", re.I)
AGE_AMBIG = re.compile(r"\b(young|youthful|young-looking|teen-like|school uniform|childlike|petite girl)\b|年轻|少女感|看起来很小|校服|稚嫩|童颜", re.I)
ADULT = re.compile(r"\b(adult|grown|[2-9]\d-year-old|(18|19)-year-old|in (her|his|their) (early |mid-|mid |late )?(20s|30s|40s|50s|60s|twenties|thirties|forties)|mature)\b|成年|成人|([2-9]\d|1[89])岁", re.I)
PERSON = re.compile(r"\b(woman|women|man|men|person|people|girl|boy|lady|guy|she|he|her|his|model|actress|actor|digital human|character|portrait|selfie|face)\b|女性|男性|女人|男人|女孩|男孩|人物|她|他|数字人|角色|肖像|自拍|模特", re.I)
MOOD = re.compile(r"^(cinematic|beautiful|moody|epic|dramatic|stunning|aesthetic|high quality|masterpiece|8k|4k|ultra|best quality|atmospheric|dreamy|gorgeous)\b", re.I)
CAMS = [("push-in", r"push[- ]in|dolly in"), ("pull-out", r"pull[- ]out|dolly out"), ("pan", r"\bpans?\b|\bpanning\b"), ("orbit", r"\borbit"), ("tracking", r"\btracking\b"), ("crane", r"\bcrane\b"), ("handheld", r"handheld"), ("zoom", r"\bzoom"), ("tilt", r"\btilts?\b")]
VERBS = re.compile(r"\b(walks?|turns?|smiles?|waves?|raises?|stands? up|sits? down|runs?|jumps?|dances?|looks? back|lowers?|tucks?|spins?|picks? up|throws?|opens?|nods?|claps?|kneels?|reaches?|lifts?|points?|hugs?|laughs?|drinks?|eats?)\b", re.I)


def _s(x: Any) -> str:
    return str(x or "").strip()


def _sent(x: str) -> str:
    x = _s(x).rstrip("。")
    if not x:
        return ""
    x = x[0].upper() + x[1:]
    return x if re.search(r"[.!?\"”]$", x) else x + "."


def _join(items: list[str]) -> str:
    items = [i for i in (_s(v) for v in items) if i]
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _cj(items: list[str]) -> str:
    items = [i.rstrip(".") for i in (_s(v) for v in items) if i]
    return ", ".join(v if i == 0 else (v[0].lower() + v[1:] if not v.startswith("<IMAGE") else v) for i, v in enumerate(items))


def _list(v: Any) -> list[str]:
    if isinstance(v, str):
        return [p.strip() for p in re.split(r"[,，、]", v) if p.strip()]
    if isinstance(v, list):
        return [_s(p) for p in v if _s(p)]
    return []


def _depth(v: Any) -> list[str]:
    return [DEPTH.get(d.lower(), d) for d in _list(v)]


def legacy_build(mode: str, p: dict[str, Any]) -> str:
    out: list[str] = []
    add = lambda s: out.append(s) if s else None  # noqa: E731
    depth = _depth(p.get("depth"))
    if mode == "t2i":
        add(_sent(p.get("subject")))
        add(_sent(_cj([p.get("details")])))
        add(_sent(_cj([p.get("art"), p.get("color")])))
        add(_sent(_cj([p.get("light"), p.get("composition")] + depth)))
    elif mode == "i2i":
        add(_sent(p.get("change")))
        pres = _list(p.get("preserve"))
        if pres:
            add(f"Keep the exact {_join(pres)}.")
        if p.get("match_light"):
            add("Match the new light direction naturally.")
    elif mode == "i2v":
        if p.get("loop"):
            add("Seamless loop, first frame matches last frame exactly.")
        add(_sent(p.get("action")))
        add(_sent(p.get("env")))
        add(_sent(_cj([p.get("camera")] + depth)))
        pres = _list(p.get("preserve"))
        if pres:
            add(f"Preserve the exact {_join(pres)} throughout.")
    elif mode == "t2v":
        add(_sent(p.get("first_frame")))
        beats = _list(p.get("beats")) if not isinstance(p.get("beats"), str) else [p.get("beats")]
        if beats:
            add(_sent(", then ".join([beats[0]] + [b[0].lower() + b[1:] for b in beats[1:]])))
        cam = _s(p.get("camera"))
        add(_sent(_cj([cam + (" throughout the clip" if cam else "")] + depth)))
        cont = _list(p.get("continuity"))
        if cont:
            add(f"Preserve {_join(cont)}.")
    elif mode == "ref":
        add(_sent(p.get("scene")))
        add(_sent(_cj([p.get("camera")] + depth)))
    if mode in ("i2v", "t2v", "ref"):
        dlg = _s(p.get("dialogue")).strip("\"“”")
        if dlg:
            who = _s(p.get("speaker")) or "She"
            add(f'{who} says "{dlg}".')
        add(_sent(p.get("sound")))
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def legacy_lint(text: str, mode: str = "", p: dict[str, Any] | None = None, spicy: bool = False) -> list[dict[str, str]]:
    p = p or {}
    issues: list[dict[str, str]] = []

    def add(level: str, title: str, fix: str = "") -> None:
        issues.append({"level": level, "title": title, "fix": fix})

    for cat, rx in HARD:
        hits = sorted({m.group(0).lower() for m in rx.finditer(text)})
        if hits:
            add("block", f"硬性禁用词（{cat}）：{'、'.join(hits)}", "零容忍内容：删除相关内容；不提供改写或绕过方法")
    if PERSON.search(text):
        ages = sorted({int(a or b) for a, b in re.findall(r"\b(\d{1,2})[- ]year[- ]old\b|(\d{1,2})\s*岁", text, re.I) if int(a or b) < 18})
        if ages:
            add("block", f"未成年年龄：{ages}", "涉及未成年人的内容零容忍，删除")
    if SEXUAL.search(text) and AGE_AMBIG.search(text):
        add("block", "年龄模糊词与性化词同时出现", "零容忍风险组合，删除")
    for cat, rx, fix in RISKY:
        hits = sorted({m.group(0).lower() for m in rx.finditer(text)})
        if hits:
            add("warn", f"易触发词（{cat}）：{'、'.join(hits)}", fix)
    if SEXUAL.search(text) and PERSON.search(text) and not ADULT.search(text):
        add("warn", "成人向人物描述未写明成年", "写明 fictional adult 或具体年龄")
    if spicy and PERSON.search(text) and not ADULT.search(text):
        add("warn", "辣椒模式：未写明虚构成年角色", "写 fictional adult woman/man 或具体年龄")
    for rx, fix in WEAK:
        hits = sorted({m.group(0).lower() for m in rx.finditer(text)})
        if hits:
            add("tip", f"低效词：{'、'.join(hits)}", fix)
    first = _s(p.get("subject") or p.get("first_frame") or text)
    if MOOD.search(first):
        add("warn", "主体不在最前（以氛围/质量词开头）", "第一句写可拍摄的主体")
    video = mode in ("i2v", "t2v", "ref") or bool(re.search(r"push-in|pan|orbit|tracking|static locked|locked shot", text, re.I))
    if video:
        cams = [n for n, rx in CAMS if re.search(rx, text, re.I)]
        static = bool(re.search(r"static|locked shot|no camera movement", text, re.I))
        if len(cams) > 1:
            add("warn", "多个机位运动：" + " + ".join(cams), "只保留一个机位")
        elif cams and static:
            add("warn", f"机位冲突：静止机位 + {cams[0]}", "二选一")
        elif not cams and not static and mode in ("i2v", "t2v", "ref"):
            add("warn", "未指定机位", "加 Static locked shot 或一个明确机位")
        if mode != "t2v":
            verbs = {v.lower().split(" ")[0].rstrip("s") for v in VERBS.findall(text)}
            if len(verbs) >= 3:
                add("warn", f"多个动作叠加：{', '.join(sorted(verbs))}", "一次一个主要动作")
    if mode in ("i2i", "i2v") and not _list(p.get("preserve")) and not re.search(r"\b(keep|preserve)\b", text, re.I):
        add("warn", "未写保留列表", "写具体 preserve 列表，防止漂移")
    n = len([s for s in re.findall(r"[^.!?]+[.!?]+", text) if len(s.split()) >= 3])
    if n > 5:
        add("warn", f"提示过长（{n} 句）", "2–5 句为宜，先短版再加细节")
    if mode == "ref":
        ff = bool(p.get("first_frame_image"))
        refs = _list(p.get("refs"))
        used = {int(x) for x in re.findall(r"<IMAGE_(\d+)>", text)}
        valid = {i + (1 if ff else 0) for i in range(len(refs))} if refs else used
        for u in sorted(used - valid):
            add("warn", f"引用不存在的 <IMAGE_{u}>", "首帧占 <IMAGE_0> 时参考图从 <IMAGE_1> 开始" if ff and u == 0 else "按参考图列表顺序编号")
        if len(refs) > 14:
            add("warn", "参考图超过 14 张", "1.5 最多 14 张，旧版最多 7 张")
    return issues


def _legacy_result(mode: str, en: str, issues: list[dict[str, str]]) -> str:
    blocked = any(i["level"] == "block" for i in issues)
    return json.dumps(
        {
            "ok": not blocked,
            "mode": mode,
            "mode_name": LEGACY_MODES.get(mode, ""),
            "prompt_en": "" if blocked else en,
            "blocked": blocked,
            "issues": issues,
            "guide": LEGACY_GUIDE.get(mode, ""),
            "note": "旧版规则（未加载共享引擎）：参数（模型/时长/分辨率/比例）不写入提示词。完整工具：EVA 侧栏「Grok提示词」。",
        },
        ensure_ascii=False,
    )




# ============================== 共享引擎（Node + core_bundle.js） ==============================

def _node_path() -> str | None:
    p = shutil.which("node")
    if p:
        return p
    for c in (r"C:\Program Files\nodejs\node.exe", r"C:\Program Files (x86)\nodejs\node.exe", "/usr/bin/node", "/usr/local/bin/node"):
        if os.path.isfile(c):
            return c
    return None


def _engine_ready() -> tuple[str | None, str]:
    if not ENGINE.is_file() or not BUNDLE.is_file():
        return None, "缺少 engine.js / core_bundle.js"
    node = _node_path()
    if not node:
        return None, "未找到 Node.js（node.exe）"
    return node, ""


def _run_engine_sync(node: str, req: dict[str, Any]) -> dict[str, Any]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("NODE_")}  # 不继承 NODE_OPTIONS 等
    kw: dict[str, Any] = {}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        [node, "--disallow-code-generation-from-strings", "--max-old-space-size=192", str(ENGINE)],
        input=json.dumps(req, ensure_ascii=False).encode("utf-8"),
        capture_output=True, timeout=NODE_TIMEOUT_S, cwd=str(HERE), env=env, **kw,
    )
    out = proc.stdout.decode("utf-8", "replace").strip()
    if not out:
        raise RuntimeError("引擎无输出（退出码 %s）" % proc.returncode)
    return json.loads(out)


async def _engine(req: dict[str, Any]) -> dict[str, Any] | None:
    node, _why = _engine_ready()
    if not node:
        return None
    try:
        return await asyncio.to_thread(_run_engine_sync, node, req)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "共享引擎超时（%ss）" % NODE_TIMEOUT_S}
    except Exception as exc:  # 只记录类型
        logger.warning("imagine_prompt engine failed: %s", type(exc).__name__)
        return {"ok": False, "error": "共享引擎运行失败：%s" % type(exc).__name__}


def _ps():
    try:
        from app.api import prompt_studio as ps  # 网页工具后端：参数 / 更新记录 / 选项库 / 识图 / 硬性底线
        return ps
    except Exception as exc:
        logger.warning("imagine_prompt: prompt_studio unavailable: %s", type(exc).__name__)
        return None


def _web_build() -> str:
    try:
        from app.tools.safety import project_root
        root = project_root()
    except Exception:
        root = HERE.parent.parent
    try:
        with open(root / TOOL_HTML_REL, "r", encoding="utf-8") as f:
            m = _BUILD_RE.search(f.read(2_000_000))
        return m.group(1) if m else ""
    except OSError:
        return ""


async def _context(use_builtin: bool) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """网页同款上下文：服务端选项库 + 已保存的官方参数。"""
    ctx: dict[str, Any] = {}
    notes: list[dict[str, str]] = []
    ps = _ps()
    if ps is None:
        notes.append({"level": "warn", "msg": "未能加载网页后端模块：自定义选项库与更新后的参数未使用（按内置规则）"})
        return ctx, notes
    try:
        ctx["user_opts"] = ps._opt_load()
    except Exception as exc:
        notes.append({"level": "warn", "msg": "读取选项库失败（%s），按内置选项" % type(exc).__name__})
    if not use_builtin:
        try:
            ctx["pupd"] = await ps.params_get()
        except Exception as exc:
            notes.append({"level": "warn", "msg": "读取已更新参数失败（%s），按内置参数" % type(exc).__name__})
    return ctx, notes


# ============================== 工具函数 ==============================

def _obj(v: Any, name: str, errs: list[str]) -> dict[str, Any]:
    if v is None or v == "":
        return {}
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            errs.append(f"{name} 必须是 JSON 对象")
            return {}
    if not isinstance(v, dict):
        errs.append(f"{name} 必须是对象")
        return {}
    return v


def _truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "是", "确认", "同意")
    return bool(v)


def _dump(o: dict[str, Any]) -> str:
    return json.dumps(o, ensure_ascii=False)


def _err(msg: str, **extra: Any) -> str:
    return _dump(dict({"ok": False, "error": msg}, **extra))


def _vis_flags(vision_id: Any, image_flags: Any, notes: list[dict[str, str]]) -> dict[str, bool]:
    vis = {"minor": False, "real": False}
    vid = str(vision_id or "").strip()
    if vid:
        hit = _VIS_CACHE.get(vid)
        if hit and time.time() - hit[0] < VIS_TTL_S:
            vis["minor"] = bool(hit[1].get("minor"))
            vis["real"] = bool(hit[1].get("real"))
        else:
            notes.append({"level": "warn", "msg": "vision_id 无效或已过期（EVA 重启后识图结果不保留）：本次未带识图风险标记"})
    if isinstance(image_flags, dict):  # 对话模型给出的风险标记只能加严，不能解除
        vis["minor"] = vis["minor"] or _truthy(image_flags.get("minor"))
        vis["real"] = vis["real"] or _truthy(image_flags.get("real_person") or image_flags.get("real"))
    return vis


def _server_check(res: dict[str, Any], spicy: bool) -> None:
    """后端同一套硬性底线（网页 AI 优化/翻译接口所用）再查一遍：只会加严。"""
    ps = _ps()
    if ps is None or res.get("blocked"):
        return
    text = (res.get("prompt_en") or "") + "\n" + (res.get("prompt_zh") or "")
    try:
        cats = ps.hard_violations(text, bool(spicy))
    except Exception:
        return
    if cats:
        res.update({"ok": False, "blocked": True, "prompt_en": "", "prompt_zh": ""})
        res.setdefault("lint", []).insert(0, {"level": "block", "title": "硬性禁用（后端复核）", "msg": "命中：" + "、".join(cats), "fix": "按零容忍规则不输出提示词，请如实告知用户，不要改写绕过"})


def _finish(res: dict[str, Any], notes: list[dict[str, str]], ignored: list[str], web_build: str) -> str:
    if notes:
        res.setdefault("input_issues", [])
        res["input_issues"] = notes + res["input_issues"]
    if ignored:
        res.setdefault("input_issues", []).append({"level": "warn", "msg": "已忽略未知参数：" + "、".join(ignored[:20])})
    if res.get("engine") == "shared":
        res["web_build"] = web_build or "unknown"
        res["same_build_as_web"] = bool(web_build) and web_build == res.get("build")
        if web_build and not res["same_build_as_web"]:
            res.setdefault("input_issues", []).append({"level": "warn", "msg": "技能引擎与网页工具不是同一构建（%s ≠ %s）：结果可能与网页不同" % (res.get("build"), web_build)})
    if res.get("blocked"):
        res["note"] = "命中硬性禁用：不输出提示词。请如实告知用户原因，不要改写措辞绕过。"
    if "data" in res and res["data"] is None:
        res.pop("data")
    return _dump(res)


def _workspace_file(rel: Any) -> Path | None:
    s = str(rel or "").strip()
    if not s or re.match(r"^[a-z][a-z0-9+.-]*://", s, re.I) or s.startswith("data:"):
        return None
    try:
        from app.tools.safety import resolve_workspace_path
    except Exception:
        return None
    p = resolve_workspace_path(s)
    if p is None or not p.is_file():
        return None
    return p


def _image_data_url(p: Path) -> str:
    raw = p.read_bytes()
    head = raw[:12]
    mime = "image/png" if head.startswith(b"\x89PNG") else "image/jpeg" if head.startswith(b"\xff\xd8") else "image/webp" if head[8:12] == b"WEBP" else ""
    if mime and len(raw) <= 5 * 1024 * 1024:
        return f"data:{mime};base64," + base64.b64encode(raw).decode()
    from io import BytesIO
    from PIL import Image  # 仅在需要压缩时使用（大图或非常见格式）
    with Image.open(BytesIO(raw)) as im:
        im = im.convert("RGB")
        im.thumbnail((2048, 2048))
        buf = BytesIO()
        im.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _http_detail(exc: Exception) -> str:
    d = getattr(exc, "detail", None)
    return str(d if d is not None else type(exc).__name__)[:300]


# ============================== 主入口 ==============================

ACTIONS = ["build", "lint", "guide", "describe", "restore", "params", "params_log", "params_update", "analyze_image"]
KNOWN = {
    "action", "mode", "form", "spicy", "parts", "fields", "params", "translations", "prompt", "prompt_en", "prompt_zh",
    "source_size", "source_ratio", "vision_id", "image_flags", "image_path", "history_entry", "history_path", "history_id",
    "history_title", "confirm", "field", "return_data", "use_builtin_params", "offset", "limit",
}


async def imagine_prompt(action: str = "build", mode: str = "t2i", **kw: Any) -> str:
    """Grok提示词：生成 / 检查 Grok Imagine 提示词（与网页工具同源）。"""
    action = _s(action).lower() or "build"
    action = {"generate": "build", "check": "lint", "help": "guide", "schema": "describe", "options": "describe", "history": "restore",
              "param": "params", "log": "params_log", "update_params": "params_update", "vision": "analyze_image", "识图": "analyze_image"}.get(action, action)
    ignored = [k for k in kw if k not in KNOWN]
    if action not in ACTIONS:
        return _err("action 只能是 " + " / ".join(ACTIONS))
    mode = _s(mode) or "t2i"
    notes: list[dict[str, str]] = []
    errs: list[str] = []
    web_build = _web_build()

    # ---------- 参数与更新记录（只读） / 手动联网更新（需明确确认） ----------
    if action in ("params", "params_log", "params_update"):
        ps = _ps()
        if ps is None:
            return _err("网页后端模块不可用")
        try:
            if action == "params":
                j = await ps.params_get()
                return _dump({"ok": True, "updated": j.get("updated", 0), "fields": j.get("fields", {}), "sources": j.get("sources", {}),
                              "note": "updated=0 表示从未联网更新，按内置参数（来自白皮书与官方文档的内置值）。网页里若勾选了「使用内置参数」，那只保存在浏览器，本技能看不到。"})
            if action == "params_log":
                off = max(0, int(kw.get("offset") or 0))
                lim = min(100, max(1, int(kw.get("limit") or 20)))
                return _dump(await ps.params_log(off, lim))
            if not _truthy(kw.get("confirm")):
                return _err("联网更新参数只在用户明确要求时执行：请先向用户确认，再以 confirm=true 调用（只抓取官方白名单页面，不调用模型，会写入参数文件与更新记录）")
            j = await ps.params_update_run()
            return _dump(dict(j, note="与网页「联网更新参数」相同：已写入 data/prompt_studio_params.json 并追加更新记录；网页下次打开时自动同步。"))
        except Exception as exc:
            return _err("操作失败：" + _http_detail(exc))

    fields = _obj(kw.get("fields"), "fields", errs)
    parts = _obj(kw.get("parts"), "parts", errs)
    params = _obj(kw.get("params"), "params", errs)
    translations = _obj(kw.get("translations"), "translations", errs)
    source_size = _obj(kw.get("source_size"), "source_size", errs)
    if errs:
        return _err("；".join(errs))
    use_builtin = _truthy(kw.get("use_builtin_params"))
    node, why = _engine_ready()
    spicy_in = kw.get("spicy")
    base_req: dict[str, Any] = {"mode": mode}
    if kw.get("form"):
        base_req["form"] = _s(kw.get("form"))
    if spicy_in is not None and spicy_in != "":
        base_req["spicy"] = _truthy(spicy_in)

    # ---------- 无 Node：旧版纯 Python 规则兜底 ----------
    legacy_mode = mode if mode in LEGACY_MODES else re.sub(r"_.*$", "", mode)
    if not node:
        if legacy_mode not in LEGACY_MODES:
            legacy_mode = "t2i"
        tag = {"level": "warn", "msg": f"共享引擎不可用（{why}）：已退回旧版规则，结果不保证与网页工具一致；表单字段 fields、历史还原、识图暂不可用"}
        if action == "guide":
            return _dump({"ok": True, "engine": "legacy", "mode": legacy_mode, "guide": LEGACY_GUIDE[legacy_mode], "depth_options": list(DEPTH), "input_issues": [tag]})
        if action == "lint":
            text = _s(kw.get("prompt") or kw.get("prompt_en"))
            if not text:
                return _err("lint 需要 prompt")
            r = json.loads(_legacy_result(legacy_mode, text, legacy_lint(text, legacy_mode, parts, _truthy(spicy_in))))
        elif action == "build" and parts:
            en = legacy_build(legacy_mode, parts)
            if not en:
                return _err("parts 为空", guide=LEGACY_GUIDE[legacy_mode])
            r = json.loads(_legacy_result(legacy_mode, en, legacy_lint(en, legacy_mode, parts, _truthy(spicy_in))))
        else:
            return _err(f"共享引擎不可用（{why}）：该操作需要共享引擎；旧版只支持 build(parts) / lint / guide")
        r.update({"engine": "legacy", "input_issues": [tag]})
        _server_check(r, _truthy(spicy_in))
        return _finish(r, [], ignored, "")

    ctx, cnotes = await _context(use_builtin)
    notes += cnotes
    base_req.update(ctx)
    if use_builtin:
        base_req["use_builtin_params"] = True
    if translations:
        base_req["translations"] = {str(k): str(v) for k, v in list(translations.items())[:200] if isinstance(v, (str, int, float))}
    if params:
        base_req["params"] = params
    if source_size:
        base_req["source_size"] = source_size
    if kw.get("source_ratio"):
        base_req["source_ratio"] = _s(kw.get("source_ratio"))
    base_req["vis"] = _vis_flags(kw.get("vision_id"), kw.get("image_flags"), notes)
    if _truthy(kw.get("return_data")):
        base_req["return_data"] = True

    # ---------- 写法 / 字段说明 ----------
    if action in ("guide", "describe"):
        req = dict(base_req, op="describe")
        if kw.get("field"):
            req["field"] = _s(kw.get("field"))
        r = await _engine(req)
        if r and r.get("ok") and action == "guide":
            b = r.get("base") or "t2i"
            r["guide"] = LEGACY_GUIDE.get(b, "")
            r["how_to"] = ("用 action=build、fields={字段id: 值} 调用；字段值优先用 options 里的 key（也可用中文/英文名），"
                           "自由文本请给 {\"zh\":\"中文\",\"en\":\"英文\"}——英文由你（对话模型）翻译；没给英文时按网页同款词典翻译，剩下的列在 translation.missing。")
        return _finish(r or {"ok": False, "error": "共享引擎无结果"}, notes, ignored, web_build)

    # ---------- 检查现成提示词 ----------
    if action == "lint":
        text = _s(kw.get("prompt") or kw.get("prompt_en"))
        if not text:
            return _err("lint 需要 prompt（英文提示词）")
        req = dict(base_req, op="lint", prompt_en=text[:6000])
        if kw.get("prompt_zh"):
            req["prompt_zh"] = _s(kw.get("prompt_zh"))[:6000]
        if fields:
            req = dict(req, op="build", fields=fields)
        r = await _engine(req) or {"ok": False, "error": "共享引擎无结果"}
        _server_check(r, bool(r.get("spicy")))
        return _finish(r, notes, ignored, web_build)

    # ---------- 还原网页历史（需用户提供导出文件或记录） ----------
    if action == "restore":
        entry = kw.get("history_entry")
        if isinstance(entry, str) and entry.strip():
            try:
                entry = json.loads(entry)
            except ValueError:
                return _err("history_entry 必须是 JSON 对象")
        if not isinstance(entry, dict):
            p = _workspace_file(kw.get("history_path"))
            if p is None:
                return _err("历史记录保存在浏览器里，技能读不到。请让用户在网页「历史 → 导出」后把 JSON 文件放进 workspace（如 uploads/），再用 history_path 指定；或直接提供一条记录 history_entry")
            if p.stat().st_size > MAX_HISTORY_BYTES:
                return _err("历史文件过大（>5MB）")
            try:
                doc = json.loads(p.read_text(encoding="utf-8-sig"))
            except Exception:
                return _err("历史文件不是有效 JSON")
            items = doc.get("items") if isinstance(doc, dict) else None
            if not isinstance(items, list) or (isinstance(doc, dict) and doc.get("app") not in (None, "imagine-prompt-studio")):
                return _err("不是网页工具导出的历史文件（需要 app=imagine-prompt-studio、items 列表）")
            hid, title = _s(kw.get("history_id")), _s(kw.get("history_title"))
            pick = [x for x in items if isinstance(x, dict) and ((hid and x.get("id") == hid) or (title and title in _s(x.get("title"))))]
            if not pick:
                listing = [{"id": _s(x.get("id"))[:40], "title": _s(x.get("title"))[:60], "mode": _s(x.get("mode"))[:20], "time": x.get("time")} for x in items[:50] if isinstance(x, dict)]
                return _dump({"ok": True, "entries": listing, "total": len(items), "note": "用 history_id（或 history_title）选择一条再调用 restore"})
            entry = pick[0]
        r = await _engine(dict(base_req, op="restore", entry=entry)) or {"ok": False, "error": "共享引擎无结果"}
        _server_check(r, bool(r.get("spicy")))
        return _finish(r, notes, ignored, web_build)

    # ---------- 识图（复用网页识图服务；只在用户明确要求时） ----------
    if action == "analyze_image":
        if not _truthy(kw.get("confirm")):
            return _err("识图会调用「设定 → 集成 → Vision」配置的识图模型（可能产生费用）：只在用户明确要求识图时，以 confirm=true 调用")
        raw = _s(kw.get("image_path"))
        if re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.I) or raw.startswith("data:"):
            return _err("只接受 workspace 内的图片路径（如 uploads/xxx.jpg），不下载网址")
        p = _workspace_file(raw)
        if p is None:
            return _err("找不到该图片：image_path 必须是 workspace 内已存在的文件（聊天上传的图片在 uploads/）。没有图片就不要声称看过图")
        if p.stat().st_size > MAX_IMAGE_BYTES:
            return _err("图片过大（>20MB）")
        ps = _ps()
        if ps is None:
            return _err("网页后端模块不可用")
        lists = await _engine(dict(base_req, op="vis_lists"))
        try:
            url = await asyncio.to_thread(_image_data_url, p)
            v = await ps.analyze_image_run(url, bool((lists or {}).get("spicy")), (lists or {}).get("lists") or {})
        except Exception as exc:
            return _err("识图失败：" + _http_detail(exc))
        finally:
            url = ""
        vid = secrets.token_hex(8)
        _VIS_CACHE[vid] = (time.time(), {"minor": bool(v.get("minor")), "real": bool(v.get("real_person"))})
        for k in [k for k, (t, _) in _VIS_CACHE.items() if time.time() - t > VIS_TTL_S]:
            _VIS_CACHE.pop(k, None)
        return _dump(dict(v, vision_id=vid, note="识图结果只是建议：请据此填写 fields 后再 build，并带上 vision_id（让未成年 / 真实人物风险标记生效）。网页的「识图自动填表」未移植到技能。"))

    # ---------- 生成 ----------
    if not fields and parts:
        if legacy_mode not in LEGACY_MODES:
            legacy_mode = "t2i"
        en = legacy_build(legacy_mode, parts)
        if not en:
            return _err("parts 为空", guide=LEGACY_GUIDE[legacy_mode])
        r = await _engine(dict(base_req, op="lint", prompt_en=en)) or {"ok": False, "error": "共享引擎无结果"}
        r["legacy_parts"] = True
        notes.append({"level": "tip", "msg": "这是旧版 parts（英文片段）调用：文本按旧版拼装，检查与参数用共享规则。建议改用 fields（与网页表单一致，含中英文）"})
        _server_check(r, bool(r.get("spicy")))
        return _finish(r, notes, ignored, web_build)
    r = await _engine(dict(base_req, op="build", fields=fields)) or {"ok": False, "error": "共享引擎无结果"}
    _server_check(r, bool(r.get("spicy")))
    return _finish(r, notes, ignored, web_build)


DESC = (
    "Grok提示词：生成 / 检查 Grok Imagine 图像与视频提示词，与 EVA 侧栏「Grok提示词」网页工具同一套规则（同一构建的规则引擎）。只生成文字，不出图、不出视频。"
    "mode: t2i 文生图 / i2i 图生图 / i2v 图生视频 / t2v 文生视频 / ref 参考图生视频；form: person 人物 / product 产品 / other 其他(动物、场景)；spicy=true 辣椒模式(仅人物，明确虚构成年)。"
    "先用 action=describe 拿到该表单的字段与选项 key，再用 action=build + fields 生成：选项填 key(或中文名)，自由文本填 {\"zh\":\"中文\",\"en\":\"英文\"}，英文由你翻译；"
    "含 角度 angle / 镜头 lens / 景别 framing、图生图保持/修改(aspects: keep 或 {change})、图生视频时间轴与关键帧(tl/seg1/segs/keys/endf)、目标比例 params.ar/iar/i2iar/i2var、模型/时长/分辨率 params。"
    "返回 prompt_en + prompt_zh、lint 问题、settings 与 param_notes 参数建议、translation.missing(未译中文)。"
    "action=lint 检查现成提示词；guide 写法结构；restore 还原网页导出的历史(history_path 或 history_entry)；params / params_log 查当前参数与更新记录；"
    "params_update 联网更新官方参数、analyze_image 识图(workspace 图片 image_path)——这两项只在用户明确要求时以 confirm=true 调用。"
    "旧版 parts(英文片段)仍可用。命中硬性禁用(未成年/真实人物性化/非同意/违法)时 blocked=true 且不返回提示词：如实告知用户，不要改写绕过。"
)


def register(registry):
    obj = {"type": "object"}
    registry.register(
        "imagine_prompt",
        DESC,
        imagine_prompt,
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ACTIONS, "description": "build 生成 / lint 检查 / guide 写法 / describe 字段与选项 / restore 还原历史 / params 当前参数 / params_log 更新记录 / params_update 联网更新(需 confirm) / analyze_image 识图(需 confirm)"},
                "mode": {"type": "string", "description": "t2i / i2i / i2v / t2v / ref（也接受 文生图、图生视频 等中文，或网页表单 key 如 t2i_p）"},
                "form": {"type": "string", "description": "person 人物 / product 产品 / other 其他(动物、场景)；ref 无表单"},
                "spicy": {"type": "boolean", "description": "辣椒模式（只适用于人物表单；只加严检查）"},
                "fields": dict(obj, description="表单字段 {字段id: 值}；字段 id 与可选项见 action=describe"),
                "params": dict(obj, description="生成参数：model / dur / res / ar(文生比例) / iar / i2iar / i2var(目标比例)"),
                "translations": dict(obj, description="你给出的中文→英文翻译表 {中文: 英文}（用于自由文本）"),
                "parts": dict(obj, description="旧版：按模式填写的英文片段（subject/change/action/first_frame/refs…）"),
                "prompt": {"type": "string", "description": "action=lint 要检查的英文提示词"},
                "prompt_zh": {"type": "string", "description": "可选：对应中文"},
                "source_size": dict(obj, description="源图尺寸 {w,h}（图生图/图生视频「保持原图比例」时用）"),
                "source_ratio": {"type": "string", "description": "源图比例，如 3:4"},
                "vision_id": {"type": "string", "description": "analyze_image 返回的 id（带上识图风险标记）"},
                "image_flags": dict(obj, description="你看图得出的风险标记 {minor, real_person}（只能加严）"),
                "image_path": {"type": "string", "description": "analyze_image：workspace 内图片路径，如 uploads/a.jpg"},
                "history_path": {"type": "string", "description": "restore：网页导出的历史 JSON 在 workspace 内的路径"},
                "history_entry": dict(obj, description="restore：一条历史记录"),
                "history_id": {"type": "string"},
                "history_title": {"type": "string"},
                "confirm": {"type": "boolean", "description": "用户明确要求联网更新参数 / 识图时为 true"},
                "field": {"type": "string", "description": "describe：只看某个字段"},
                "return_data": {"type": "boolean"},
                "use_builtin_params": {"type": "boolean", "description": "按内置参数（不用已更新参数）"},
                "offset": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": ["action"],
        },
        source="skill",
        metadata={"group": "media", "tag": "Grok提示词", "timeout_sec": 150},
    )
