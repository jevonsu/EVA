"""Real connectivity checks for 设定 → 集成 → 测试.

Never report ok unless a probe actually succeeded. Empty or invalid
config must fail with a clear error.
"""

from __future__ import annotations

import socket
from typing import Any
from urllib.parse import urlparse

from app.config_store import get_config_store


def _s(v: Any) -> str:
    return str(v or "").strip()


def _ok(detail: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": True, "detail": detail}
    out.update(extra)
    return out


def _fail(error: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "error": error}
    for k, v in extra.items():
        if v is not None:
            out[k] = v
    return out


def _tcp(host: str, port: int, timeout: float = 4.0) -> tuple[bool, str]:
    host = _s(host)
    if not host:
        return False, "主机为空"
    try:
        port_i = int(port)
    except (TypeError, ValueError):
        return False, f"端口无效: {port}"
    if not (1 <= port_i <= 65535):
        return False, f"端口超出范围: {port_i}"
    try:
        with socket.create_connection((host, port_i), timeout=timeout):
            return True, f"{host}:{port_i} 可达"
    except OSError as e:
        return False, f"{host}:{port_i} 无法连接（{e}）"


def _host_port_from_url(url: str, default_port: int) -> tuple[str, int] | None:
    raw = _s(url)
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw
    u = urlparse(raw)
    host = u.hostname or ""
    if not host:
        return None
    if u.port:
        return host, int(u.port)
    if u.scheme == "https":
        return host, 443
    return host, default_port


def _section(iid: str) -> dict[str, Any]:
    """Only the saved integration row — never env / .env / system proxy."""
    raw = get_config_store().get_integrations_raw().get(iid)
    return dict(raw) if isinstance(raw, dict) else {}


async def _probe_http(url: str, *, method: str = "GET", json_body: Any = None) -> tuple[int, str]:
    import httpx

    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, trust_env=False) as client:
        r = await client.request(method, url, json=json_body)
    text = (r.text or "").strip().replace("\n", " ")
    return r.status_code, text[:180]


async def _test_http() -> dict[str, Any]:
    cfg = _section("http")
    proxy = _s(cfg.get("proxy_url"))
    fs = _s(cfg.get("flaresolverr_url"))
    if not proxy and not fs:
        return _fail("未配置 HTTP 代理或 FlareSolverr")

    notes: list[str] = []
    errors: list[str] = []

    if proxy:
        parsed = _host_port_from_url(proxy, 7890)
        if not parsed:
            errors.append(f"代理地址无效: {proxy}")
        else:
            ok, msg = _tcp(*parsed)
            if not ok:
                errors.append("代理 " + msg)
            else:
                try:
                    import httpx

                    last_err = ""
                    worked = False
                    async with httpx.AsyncClient(
                        proxy=proxy,
                        timeout=8.0,
                        follow_redirects=True,
                        trust_env=False,
                    ) as client:
                        for probe in (
                            "http://www.baidu.com",
                            "http://www.gstatic.com/generate_204",
                        ):
                            try:
                                r = await client.get(probe)
                                if r.status_code < 500:
                                    notes.append(
                                        f"代理 {parsed[0]}:{parsed[1]} 工作正常"
                                    )
                                    worked = True
                                    break
                                last_err = f"HTTP {r.status_code}"
                            except Exception as e:
                                last_err = str(e)
                    if not worked:
                        errors.append(
                            f"代理端口可达，但代理请求失败（{last_err or 'unknown'}）"
                        )
                except Exception as e:
                    errors.append(f"代理端口可达，但代理请求失败（{e}）")

    if fs:
        try:
            code, body = await _probe_http(fs, method="POST", json_body={"cmd": "sessions.list"})
            if code >= 500:
                errors.append(f"FlareSolverr HTTP {code}: {body or 'server error'}")
            else:
                notes.append(f"FlareSolverr HTTP {code}")
        except Exception as e:
            errors.append(f"FlareSolverr 无法连接（{e}）")

    if errors:
        return _fail("；".join(errors), detail="；".join(notes) if notes else None)
    return _ok("；".join(notes))


def _probe_hosts(hosts: dict[str, Any]) -> dict[str, Any]:
    if not hosts:
        return _fail("未配置主机")
    notes: list[str] = []
    fails = 0
    for name, hc in list(hosts.items())[:8]:
        row = hc if isinstance(hc, dict) else {"host": str(hc)}
        host = _s(row.get("host"))
        if not host:
            notes.append(f"{name}: 未填 host")
            fails += 1
            continue
        try:
            port = int(row.get("port") or 22)
        except (TypeError, ValueError):
            notes.append(f"{name}: 端口无效")
            fails += 1
            continue
        ok, msg = _tcp(host, port, timeout=3.0)
        notes.append(f"{name}: {msg}")
        if not ok:
            fails += 1
    detail = "；".join(notes)
    if fails:
        return _fail(f"{fails}/{len(notes)} 台不可达。{detail}")
    return _ok(detail)


async def _test_generic(iid: str, raw: dict[str, Any]) -> dict[str, Any]:
    skip = {"_label", "_description", "name", "description"}
    filled = {
        k: v
        for k, v in (raw or {}).items()
        if k not in skip
        and not str(k).startswith("_")
        and _s(v)
        and k not in ("hosts", "hosts_json", "items")
    }
    hosts = raw.get("hosts") if isinstance(raw.get("hosts"), dict) else {}
    items = raw.get("items") if isinstance(raw.get("items"), (dict, list)) else {}
    if not filled and not hosts and not items:
        return _fail("未填写任何连接信息")

    url = ""
    for key in ("rpc_url", "url", "base_url", "endpoint", "api_url"):
        if _s(raw.get(key)):
            url = _s(raw.get(key))
            break
    host = _s(raw.get("host"))

    if url:
        try:
            code, body = await _probe_http(url)
            if code >= 500:
                return _fail(f"HTTP {code}: {body or 'server error'}")
            if code in (401, 403):
                return _fail(f"地址可达但认证失败 HTTP {code}")
            if code >= 400:
                return _fail(f"HTTP {code}: {body or '请求失败'}")
            return _ok(f"HTTP {code}")
        except Exception as e:
            return _fail(f"无法连接（{e}）")

    if host:
        try:
            port = int(raw.get("port") or 80)
        except (TypeError, ValueError):
            return _fail("端口无效")
        ok, msg = _tcp(host, port)
        return _ok(msg) if ok else _fail(msg)

    if hosts:
        return _probe_hosts(hosts)

    if items:
        n = len(items) if not isinstance(items, list) else len(items)
        return _ok(f"已保存 {n} 条明细（无单一地址可探测）")

    return _fail("没有可测试的地址（需要 url / base_url / host）")


def _test_vision() -> dict[str, Any]:
    from app.services.credentials import resolve_vision_skill_llm

    cred = resolve_vision_skill_llm()
    if cred.get("error") or not _s(cred.get("base_url")) or not _s(cred.get("api_key")):
        return _fail(
            _s(cred.get("error")) or "未选择识图模型。请在集成里选一条设定→模型。",
            integration_id="vision",
        )
    label = _s(cred.get("name") or cred.get("model") or cred.get("id"))
    return _ok(f"将使用「{label}」识图（不会自动换别的模型）")


async def run_integration_test(integration_id: str) -> dict[str, Any]:
    iid = _s(integration_id)
    if not iid:
        return _fail("缺少集成 id")

    store = get_config_store()
    raw = store.get_integrations_raw().get(iid)
    pub = store.get_integration_public(iid)
    if not isinstance(raw, dict):
        raw = {}
    if not raw and not pub:
        return _fail("集成不存在")

    testers = {
        "http": _test_http,
        "vision": _test_vision,
    }
    fn = testers.get(iid)
    try:
        if fn is None:
            return await _test_generic(iid, raw)
        result = fn()
        if hasattr(result, "__await__"):
            result = await result  # type: ignore[misc]
        if not isinstance(result, dict) or "ok" not in result:
            return _fail("测试未返回有效结果")
        if result.get("ok") is True and result.get("error"):
            result["ok"] = False
        if result.get("ok") is not True:
            result["ok"] = False
            if not _s(result.get("error")):
                result["error"] = _s(result.get("detail")) or "测试失败"
        return result
    except Exception as e:
        return _fail(str(e))
