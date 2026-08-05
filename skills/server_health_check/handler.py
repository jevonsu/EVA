import logging
import json
import os
import platform
import time
import subprocess
import shutil
logger = logging.getLogger(__name__)

def register(registry):
    registry.register(
        "server_health_check",
        "检查服务器健康状态，包括系统资源（CPU、内存、磁盘空间、进程数、运行时间等），返回健康评估报告与建议。",
        check_health,
        {
            "type": "object",
            "properties": {},
            "required": []
        },
        source="skill"
    )

async def check_health(params: str) -> str:
    try:
        result = {}
        
        # 1. 系统基本信息
        result["hostname"] = platform.node()
        result["platform"] = platform.platform()
        result["python_version"] = platform.python_version()
        result["boot_time"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(psutil_boot_time())) if has_psutil() else "N/A"
        
        # 2. CPU 信息
        cpu_info = {}
        try:
            import psutil
            cpu_info["usage_percent"] = psutil.cpu_percent(interval=1)
            cpu_info["count"] = psutil.cpu_count()
            cpu_info["physical_count"] = psutil.cpu_count(logical=False)
            cpu_info["load_avg"] = [round(x, 2) for x in psutil.getloadavg()] if hasattr(psutil, "getloadavg") else "N/A"
            # CPU 健康判断
            if cpu_info["usage_percent"] < 50:
                cpu_info["health"] = "✅ 正常"
            elif cpu_info["usage_percent"] < 80:
                cpu_info["health"] = "⚠️ 偏高"
            else:
                cpu_info["health"] = "🔴 過高"
        except Exception as e:
            cpu_info["error"] = str(e)
        result["cpu"] = cpu_info
        
        # 3. 内存信息
        mem_info = {}
        try:
            import psutil
            mem = psutil.virtual_memory()
            mem_info["total_gb"] = round(mem.total / (1024**3), 2)
            mem_info["used_gb"] = round(mem.used / (1024**3), 2)
            mem_info["available_gb"] = round(mem.available / (1024**3), 2)
            mem_info["usage_percent"] = mem.percent
            if mem.percent < 60:
                mem_info["health"] = "✅ 正常"
            elif mem.percent < 80:
                mem_info["health"] = "⚠️ 偏高"
            else:
                mem_info["health"] = "🔴 不足"
        except Exception as e:
            mem_info["error"] = str(e)
        result["memory"] = mem_info
        
        # 4. 磁盘信息
        disk_info = {}
        try:
            import psutil
            disk_partitions = []
            for part in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disk_partitions.append({
                        "mountpoint": part.mountpoint,
                        "total_gb": round(usage.total / (1024**3), 2),
                        "used_gb": round(usage.used / (1024**3), 2),
                        "free_gb": round(usage.free / (1024**3), 2),
                        "usage_percent": usage.percent,
                        "health": "✅ 正常" if usage.percent < 85 else ("⚠️ 偏高" if usage.percent < 95 else "🔴 不足")
                    })
                except:
                    pass
            disk_info["partitions"] = disk_partitions
        except Exception as e:
            disk_info["error"] = str(e)
        result["disk"] = disk_info
        
        # 5. 网络/进程信息
        net_proc_info = {}
        try:
            import psutil
            net_proc_info["connections"] = len(psutil.net_connections()) if hasattr(psutil, 'net_connections') else "N/A"
            net_proc_info["process_count"] = len(psutil.pids())
            if net_proc_info["process_count"] < 500:
                net_proc_info["process_health"] = "✅ 正常"
            else:
                net_proc_info["process_health"] = "⚠️ 較多進程"
        except Exception as e:
            net_proc_info["error"] = str(e)
        result["network_process"] = net_proc_info
        
        # 6. 运行时间
        uptime_info = {}
        try:
            import psutil
            uptime_seconds = time.time() - psutil.boot_time()
            days = int(uptime_seconds // 86400)
            hours = int((uptime_seconds % 86400) // 3600)
            minutes = int((uptime_seconds % 3600) // 60)
            uptime_info["uptime"] = f"{days}天 {hours}小時 {minutes}分鐘"
            uptime_info["uptime_seconds"] = int(uptime_seconds)
        except Exception as e:
            uptime_info["error"] = str(e)
        result["uptime"] = uptime_info
        
        # 7. 总体健康评分
        score = 100
        reasons = []
        
        if cpu_info.get("health") == "🔴 過高":
            score -= 20
            reasons.append("CPU使用率過高")
        elif cpu_info.get("health") == "⚠️ 偏高":
            score -= 10
            reasons.append("CPU使用率偏高")
            
        if mem_info.get("health") == "🔴 不足":
            score -= 20
            reasons.append("記憶體不足")
        elif mem_info.get("health") == "⚠️ 偏高":
            score -= 10
            reasons.append("記憶體使用率偏高")
        
        for part in disk_info.get("partitions", []):
            if part["health"] == "🔴 不足":
                score -= 15
                reasons.append(f"磁盤 {part['mountpoint']} 空間不足")
                break
            elif part["health"] == "⚠️ 偏高":
                score -= 5
                reasons.append(f"磁盤 {part['mountpoint']} 空間偏高")
                break
        
        result["health_score"] = max(0, score)
        result["health_status"] = "🟢 健康" if score >= 80 else ("🟡 亞健康" if score >= 60 else "🔴 異常")
        result["health_reasons"] = reasons if reasons else ["一切正常"]
        
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"健康檢查失敗: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)

def has_psutil():
    try:
        import psutil
        return True
    except ImportError:
        return False

def psutil_boot_time():
    import psutil
    return psutil.boot_time()
