"""System skill: local machine health (CPU / memory / disk). Works without psutil."""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DESC = (
    "检查本机健康：CPU、内存、磁盘、进程数、运行时间，给出评分。"
    "无需参数。未装 psutil 时仍返回主机名/磁盘等基础项。"
    "Agent/Python/当前 LLM 概况请用 builtin system_info。"
)


def register(registry):
    registry.register(
        "server_health_check",
        DESC,
        check_health,
        {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "enum": ["all", "cpu", "memory", "disk"],
                    "description": "可选：只返回某一项，默认 all（本技能无必填参数）",
                }
            },
            "required": [],
        },
        source="skill",
        metadata={"timeout_sec": 15, "group": "dev", "tag": "健康检查"},
    )


def _psutil():
    try:
        import psutil  # type: ignore

        return psutil
    except ImportError:
        return None


def _grade(pct: float | None, *, warn: float = 80, bad: float = 95) -> str:
    if pct is None:
        return "未知"
    if pct < warn:
        return "正常"
    if pct < bad:
        return "偏高"
    return "过高"


def _disk_rows(psutil) -> list[dict]:
    rows: list[dict] = []
    if psutil is not None:
        for part in psutil.disk_partitions(all=False):
            mp = part.mountpoint
            if not mp:
                continue
            try:
                usage = psutil.disk_usage(mp)
            except OSError:
                continue
            pct = float(usage.percent)
            rows.append(
                {
                    "mountpoint": mp,
                    "total_gb": round(usage.total / (1024**3), 2),
                    "used_gb": round(usage.used / (1024**3), 2),
                    "free_gb": round(usage.free / (1024**3), 2),
                    "usage_percent": pct,
                    "health": _grade(pct, warn=85, bad=95),
                }
            )
            if len(rows) >= 8:
                break
        if rows:
            return rows
    roots: list[str] = []
    if os.name == "nt":
        for letter in "CDEFGH":
            p = f"{letter}:\\"
            if Path(p).exists():
                roots.append(p)
    else:
        roots.append("/")
    if not roots:
        roots.append(str(Path.cwd().anchor or Path.cwd()))
    for mp in roots:
        try:
            usage = shutil.disk_usage(mp)
        except OSError:
            continue
        pct = round(100.0 * usage.used / usage.total, 1) if usage.total else 0.0
        rows.append(
            {
                "mountpoint": mp,
                "total_gb": round(usage.total / (1024**3), 2),
                "used_gb": round(usage.used / (1024**3), 2),
                "free_gb": round(usage.free / (1024**3), 2),
                "usage_percent": pct,
                "health": _grade(pct, warn=85, bad=95),
            }
        )
    return rows


async def check_health(section: str = "all") -> str:
    out = await _check_health_all()
    sec = (section or "all").strip().lower()
    if sec == "all":
        return out
    try:
        data = json.loads(out)
    except Exception:
        return out
    if isinstance(data, dict) and sec in data:
        keep = {k: data[k] for k in ("ok", sec, "score", "status", "summary") if k in data}
        return json.dumps(keep, ensure_ascii=False)
    return out


async def _check_health_all() -> str:
    try:
        psutil = _psutil()
        cpu: dict = {"count": os.cpu_count()}
        mem: dict = {}
        net_proc: dict = {}
        uptime: dict = {}
        hint = ""

        if psutil is None:
            hint = "未安装 psutil，仅基础信息。完整检查可在 Eva 目录执行：python -m pip install psutil"
            cpu["usage_percent"] = None
            cpu["health"] = "未知"
        else:
            try:
                # Non-blocking-ish: 50ms sample, not 1s.
                cpu["usage_percent"] = psutil.cpu_percent(interval=0.05)
                cpu["physical_count"] = psutil.cpu_count(logical=False)
                cpu["health"] = _grade(float(cpu["usage_percent"] or 0), warn=80, bad=95)
            except Exception as extra:
                cpu["error"] = str(extra)
                cpu["health"] = "未知"
            try:
                vm = psutil.virtual_memory()
                mem = {
                    "total_gb": round(vm.total / (1024**3), 2),
                    "used_gb": round(vm.used / (1024**3), 2),
                    "available_gb": round(vm.available / (1024**3), 2),
                    "usage_percent": vm.percent,
                    "health": _grade(float(vm.percent), warn=80, bad=95),
                }
            except Exception as extra:
                mem = {"error": str(extra), "health": "未知"}
            try:
                net_proc["process_count"] = len(psutil.pids())
                net_proc["process_health"] = (
                    "正常" if net_proc["process_count"] < 800 else "进程较多"
                )
            except Exception as extra:
                net_proc["process_error"] = str(extra)
            try:
                net_proc["connections"] = len(psutil.net_connections())
            except Exception as extra:
                net_proc["connections"] = None
                net_proc["connections_note"] = f"无法统计连接（{extra}）"
            try:
                up_s = time.time() - psutil.boot_time()
                days = int(up_s // 86400)
                hours = int((up_s % 86400) // 3600)
                minutes = int((up_s % 3600) // 60)
                uptime = {
                    "uptime": f"{days}天 {hours}小时 {minutes}分钟",
                    "uptime_seconds": int(up_s),
                }
            except Exception as extra:
                uptime = {"error": str(extra)}

        disk_rows = _disk_rows(psutil)
        score = 100
        reasons: list[str] = []
        for label, info in (("CPU", cpu), ("内存", mem)):
            h = str(info.get("health") or "")
            if h == "过高":
                score -= 20
                reasons.append(f"{label}过高")
            elif h == "偏高":
                score -= 10
                reasons.append(f"{label}偏高")
        for part in disk_rows:
            if part.get("health") == "过高":
                score -= 15
                reasons.append(f"磁盘 {part.get('mountpoint')} 空间不足")
                break
            if part.get("health") == "偏高":
                score -= 5
                reasons.append(f"磁盘 {part.get('mountpoint')} 空间偏高")
                break
        if psutil is None:
            score = min(score, 80)
            reasons.append("未安装 psutil，评分仅供参考")

        status = "健康" if score >= 80 else ("亚健康" if score >= 60 else "异常")
        return json.dumps(
            {
                "ok": True,
                "psutil": psutil is not None,
                "hostname": platform.node(),
                "platform": platform.platform(),
                "python_version": platform.python_version(),
                "cpu": cpu,
                "memory": mem,
                "disk": {"partitions": disk_rows},
                "network_process": net_proc,
                "uptime": uptime,
                "health_score": max(0, score),
                "health_status": status,
                "health_reasons": reasons or ["一切正常"],
                "hint": hint,
            },
            ensure_ascii=False,
            default=str,
        )
    except Exception as extra:
        logger.exception("健康检查失败")
        return json.dumps({"ok": False, "error": str(extra)}, ensure_ascii=False)
