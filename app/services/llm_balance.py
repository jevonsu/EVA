"""Best-effort LLM provider credit / balance lookup.

Why most cards show「暂不可查」:
  OpenAI-compatible chat APIs only standardize /chat/completions and /models.
  Balance/billing is **not** part of the OpenAI API. Only a few vendors expose
  a dedicated balance route (e.g. DeepSeek GET /user/balance). Others require a
  web console, management key, or have no programmatic balance at all (Ollama).

This module probes known endpoints and returns a soft failure when unavailable.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL = 90.0  # seconds


def _cache_key(base_url: str, api_key: str) -> str:
    return f"{(base_url or '').rstrip('/')}|{(api_key or '')[:12]}|len{len(api_key or '')}"


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            m = re.search(r"-?\d+(?:\.\d+)?", s)
            if m:
                try:
                    return float(m.group(0))
                except ValueError:
                    return None
    return None


def _host(base_url: str) -> str:
    try:
        return (urlparse(base_url).netloc or "").lower()
    except Exception:
        return ""


def _is_local_host(host: str) -> bool:
    h = (host or "").split(":")[0].lower()
    return h in (
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
    ) or h.startswith("10.") or h.startswith("192.168.") or h.startswith("172.")


def format_balance_display(amount: float | None, *, unit: str = "", currency: str = "") -> str:
    if amount is None:
        return "—"
    u = (unit or currency or "").strip().upper()
    # Do NOT invent USD when unit unknown — many CN gateways return bare numbers
    if u in ("USD", "$", "US$"):
        return f"${amount:,.2f}"
    if u in ("CNY", "RMB", "¥", "元"):
        return f"¥{amount:,.2f}"
    if u:
        return f"{amount:,.4g} {u}"
    # Unknown unit: plain number with 2 decimals when it looks monetary
    if abs(amount) < 1e6:
        return f"{amount:,.2f}"
    return f"{amount:,.4g}"


def _pick_deepseek(payload: Any) -> dict[str, Any] | None:
    """DeepSeek GET /user/balance → balance_infos[].total_balance."""
    if not isinstance(payload, dict):
        return None
    infos = payload.get("balance_infos")
    if not isinstance(infos, list) or not infos:
        # sometimes nested under data
        data = payload.get("data")
        if isinstance(data, dict):
            infos = data.get("balance_infos")
    if not isinstance(infos, list) or not infos:
        return None
    # Prefer CNY then USD then first
    best = None
    for item in infos:
        if not isinstance(item, dict):
            continue
        total = _num(item.get("total_balance") or item.get("balance"))
        if total is None:
            continue
        cur = str(item.get("currency") or "").upper() or "CNY"
        if cur in ("RMB", "元"):
            cur = "CNY"
        granted = _num(item.get("granted_balance"))
        topped = _num(item.get("topped_up_balance"))
        avail = item.get("is_available", payload.get("is_available"))
        avail_s = "可用" if avail in (True, "true", "True", 1, "1") else (
            "不可用" if avail in (False, "false", "False", 0, "0") else ""
        )
        note_bits = [avail_s] if avail_s else []
        if topped is not None:
            note_bits.append(f"充值 ¥{topped:,.2f}" if cur == "CNY" else f"充值 {topped:,.2f}")
        if granted is not None:
            note_bits.append(f"赠金 ¥{granted:,.2f}" if cur == "CNY" else f"赠金 {granted:,.2f}")
        row = {
            "amount": total,
            "unit": cur if cur in ("CNY", "USD") else cur,
            "field": "balance_infos.total_balance",
            "note": " · ".join(note_bits),
            "granted_balance": granted,
            "topped_up_balance": topped,
        }
        if cur in ("CNY",) or best is None:
            best = row
        if cur == "CNY":
            break
    return best


def _pick_openrouter(payload: Any) -> dict[str, Any] | None:
    """OpenRouter /credits or /key response."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    # GET /credits → total_credits - total_usage
    tc = _num(data.get("total_credits"))
    tu = _num(data.get("total_usage"))
    if tc is not None:
        remain = tc - (tu or 0.0)
        return {
            "amount": remain,
            "unit": "USD",
            "field": "total_credits-total_usage",
            "note": f"已购 ${tc:,.2f} · 已用 ${(tu or 0):,.2f}",
        }

    # GET /key → limit_remaining (per-key cap) or usage
    lr = _num(data.get("limit_remaining"))
    if lr is not None:
        return {
            "amount": lr,
            "unit": "USD",
            "field": "limit_remaining",
            "note": "当前 API Key 剩余额度（非账户总余额）",
        }
    # usage object
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
    if usage:
        # some keys expose limit
        lim = _num(data.get("limit"))
        used = _num(usage.get("total") or usage.get("credits"))
        if lim is not None and used is not None:
            return {
                "amount": lim - used,
                "unit": "USD",
                "field": "limit-usage",
                "note": "Key 限额剩余",
            }
    return None


def _pick_balance(payload: Any) -> dict[str, Any] | None:
    """Heuristic extract of remaining balance from JSON payload."""
    if payload is None:
        return None

    ds = _pick_deepseek(payload)
    if ds:
        return ds
    orr = _pick_openrouter(payload)
    if orr:
        return orr

    if isinstance(payload, dict):
        for path in (
            ("balance",),
            ("credit",),
            ("credits",),
            ("remain",),
            ("remaining",),
            ("quota",),
            ("hard_limit_usd",),
            ("total_available",),
            ("data", "balance"),
            ("data", "credit"),
            ("data", "quota"),
            ("data", "remain_quota"),
            ("data", "total_available"),
            ("data", "hard_limit_usd"),
            ("data", "soft_limit_usd"),
            ("data", "total_credits"),
            ("total_granted",),
            ("data", "total_granted"),
            ("data", "total_used"),
            ("usage", "total_available"),
            ("limit_remaining",),
            ("data", "limit_remaining"),
        ):
            cur: Any = payload
            ok = True
            for p in path:
                if not isinstance(cur, dict) or p not in cur:
                    ok = False
                    break
                cur = cur[p]
            if ok:
                n = _num(cur)
                if n is not None:
                    field = ".".join(path)
                    if "quota" in field.lower() and abs(n) >= 1000:
                        return {
                            "amount": n / 500000.0,
                            "field": field,
                            "unit": "USD",
                            "note": "按常见网关配额单位估算 (quota/500000)",
                            "raw_quota": n,
                        }
                    unit = "USD" if "credit" in field.lower() or "usd" in field.lower() else ""
                    return {"amount": n, "field": field, "unit": unit}

        # NewAPI / OneAPI
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if isinstance(data, dict):
            rq = _num(data.get("remain_quota") or data.get("quota"))
            uq = _num(data.get("used_quota"))
            if rq is not None:
                amount = rq
                unit = ""
                note = ""
                if abs(rq) >= 1000:
                    amount = rq / 500000.0
                    unit = "USD"
                    note = "按常见网关配额单位估算 (quota/500000)"
                return {
                    "amount": amount,
                    "field": "remain_quota",
                    "unit": unit,
                    "note": note,
                    "raw_quota": rq,
                    "used_quota": uq,
                }

    # Generic walk
    prefer = (
        "balance",
        "credit",
        "remain",
        "quota",
        "available",
        "hard_limit",
        "total_available",
        "total_granted",
        "limit_remaining",
    )
    hits = _walk_numbers(payload, prefer)
    if not hits:
        return None
    hits.sort(
        key=lambda kv: (
            0
            if re.search(r"remain|balance|credit|available|limit_remaining", kv[0], re.I)
            else 1,
            -abs(kv[1]),
        )
    )
    k, n = hits[0]
    return {"amount": n, "field": k}


def _walk_numbers(obj: Any, keys: tuple[str, ...], depth: int = 0) -> list[tuple[str, float]]:
    found: list[tuple[str, float]] = []
    if depth > 6:
        return found
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if any(x in kl for x in keys):
                n = _num(v)
                if n is not None:
                    found.append((str(k), n))
            found.extend(_walk_numbers(v, keys, depth + 1))
    elif isinstance(obj, list):
        for it in obj[:40]:
            found.extend(_walk_numbers(it, keys, depth + 1))
    return found


def _join_url(prefix: str, path: str) -> str:
    """Join prefix + path without producing /v1/v1/..."""
    pfx = (prefix or "").rstrip("/")
    pth = "/" + (path or "").lstrip("/")
    # If both sides contribute a /v1 segment, drop one
    if re.search(r"/v1$", pfx, flags=re.I) and re.match(r"/v1(/|$)", pth, flags=re.I):
        pth = pth[3:] or "/"
        if not pth.startswith("/"):
            pth = "/" + pth
    return pfx + pth


def _candidate_urls(base_url: str, provider: str = "") -> list[str]:
    """Short, host-aware balance probe list (avoid spray of 404 noise)."""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return []
    host = _host(base)
    root = re.sub(r"/v1$", "", base, flags=re.I)
    urls: list[str] = []

    def add(*items: str) -> None:
        for u in items:
            u = (u or "").strip().rstrip("/")
            if u and u not in urls:
                urls.append(u)

    # --- Host-specific (preferred, few requests) ---
    if "deepseek.com" in host:
        add(f"{root}/user/balance", "https://api.deepseek.com/user/balance")
        return urls

    if "openrouter.ai" in host:
        add(
            "https://openrouter.ai/api/v1/key",
            "https://openrouter.ai/api/v1/credits",
        )
        return urls

    if "siliconflow" in host:
        add(_join_url(root, "/v1/user/info"), _join_url(root, "/user/info"))
        return urls

    if "x.ai" in host:
        # Public API usually has no balance route
        return urls

    # NewAPI / OneAPI style gateways (yunwu, chatanywhere, many CN relays)
    if any(
        x in host
        for x in (
            "yunwu",
            "chatanywhere",
            "api2d",
            "closeai",
            "openai-sb",
            "aihubmix",
            "gate",
        )
    ) or host.endswith(".ai") or "api." in host:
        # Paths known to work on NewAPI forks (order matters)
        add(
            _join_url(root, "/dashboard/billing/credit_grants"),
            _join_url(base, "/dashboard/billing/subscription"),
            _join_url(root, "/api/user/self"),
            _join_url(base, "/dashboard/billing/credit_grants"),
            _join_url(root, "/v1/dashboard/billing/credit_grants"),
        )
        return urls[:6]

    # Generic: only a few high-value endpoints (no cross product of prefixes)
    for p in (
        "/dashboard/billing/credit_grants",
        "/v1/dashboard/billing/credit_grants",
        "/dashboard/billing/subscription",
        "/user/balance",
        "/v1/user/balance",
        "/api/user/self",
    ):
        add(_join_url(root, p))
        if base != root:
            # only when path does not already start with /v1 or base has no /v1
            if not (base.lower().endswith("/v1") and p.lower().startswith("/v1")):
                add(_join_url(base, p))
    return urls[:8]


async def fetch_llm_balance(
    *,
    base_url: str,
    api_key: str,
    provider: str = "",
    timeout: float = 12.0,
    use_cache: bool = True,
    use_proxy: bool = False,
) -> dict[str, Any]:
    """Probe balance endpoints. Always returns a dict with ok True/False."""
    base = (base_url or "").strip().rstrip("/")
    key = (api_key or "").strip()
    host = _host(base)
    prov = (provider or "").lower()

    if not base:
        return {
            "ok": False,
            "error": "缺少 Base URL",
            "display": "—",
            "hint": "请先填写 LLM Base URL",
        }
    if not key:
        return {
            "ok": False,
            "error": "缺少 API Key",
            "display": "—",
            "hint": "请先填写 API Key",
        }

    # Local / Ollama: no cloud balance
    if "11434" in base or "ollama" in host or "ollama" in prov or (
        _is_local_host(host) and "11434" in base
    ):
        return {
            "ok": True,
            "amount": None,
            "display": "本地 · 无余额",
            "unit": "",
            "note": "Ollama / 本地推理不按云端余额计费",
            "source": "local",
            "provider": prov or "ollama",
            "host": host,
            "local": True,
        }

    ck = _cache_key(base, key)
    if use_cache and ck in _CACHE:
        ts, cached = _CACHE[ck]
        if time.time() - ts < _CACHE_TTL:
            return dict(cached)

    # Sanitize key for HTTP headers (latin-1)
    try:
        key.encode("latin-1")
    except UnicodeEncodeError:
        key = key.encode("latin-1", "ignore").decode("latin-1")

    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": "Eva-LLM-Balance/1.3",
    }
    # Prefer a single header set; only retry NewAPI extras if first pass finds nothing
    headers_primary = headers
    headers_newapi = {
        **headers,
        "New-Api-User": "0",
        "token": key,
    }

    tried: list[dict[str, Any]] = []
    last_err = ""
    auth_fail = False  # 401/403 seen on a real balance route
    auth_detail = ""
    client_kw: dict[str, Any] = {
        "timeout": timeout,
        "follow_redirects": True,
        "trust_env": False,
    }
    if use_proxy:
        try:
            from app.services.model_meta import resolve_app_proxy_url

            proxy = resolve_app_proxy_url()
        except Exception:
            proxy = ""
        if not proxy:
            return {
                "ok": False,
                "error": "已勾选使用代理，但未配置代理地址",
                "display": "代理未配置",
                "hint": "设定 → 集成 → HTTP 网络 填写代理，或取消该 LLM 的「使用代理」",
                "provider": prov,
                "host": host,
            }
        try:
            proxy.encode("ascii")
            client_kw["proxy"] = proxy
        except UnicodeEncodeError:
            return {
                "ok": False,
                "error": "代理地址含非英文字符",
                "display": "代理无效",
                "hint": "请使用 ascii 代理 URL，如 http://127.0.0.1:7890",
                "provider": prov,
                "host": host,
            }
    async def _try_urls(
        client: httpx.AsyncClient, urls: list[str], hdr: dict[str, str]
    ) -> dict[str, Any] | None:
        nonlocal last_err, auth_fail, auth_detail, tried
        for url in urls:
            try:
                resp = await client.get(url, headers=hdr)
            except Exception as exc:
                last_err = str(exc) or type(exc).__name__
                tried.append({"url": url, "error": last_err})
                continue
            tried.append({"url": url, "status": resp.status_code})
            if resp.status_code in (401, 403):
                auth_fail = True
                detail = ""
                try:
                    body = resp.json()
                    if isinstance(body, dict):
                        err = body.get("error")
                        if isinstance(err, dict):
                            detail = str(err.get("message") or "")
                        elif isinstance(err, str):
                            detail = err
                        else:
                            detail = str(body.get("message") or "")
                except Exception:
                    detail = (resp.text or "")[:160]
                auth_detail = detail or f"HTTP {resp.status_code}"
                last_err = f"HTTP {resp.status_code}（密钥无效或无权限）"
                continue
            if resp.status_code == 404:
                continue
            if resp.status_code >= 400:
                last_err = f"HTTP {resp.status_code}"
                continue
            try:
                payload = resp.json()
            except Exception:
                last_err = "非 JSON 响应"
                continue
            picked = _pick_balance(payload)
            if not picked:
                last_err = "响应中无余额字段"
                continue
            amount = float(picked["amount"])
            unit = str(picked.get("unit") or "").strip().upper()
            if unit in ("RMB", "元"):
                unit = "CNY"
            if not unit and isinstance(payload, dict):
                infos = payload.get("balance_infos")
                if isinstance(infos, list) and infos and isinstance(infos[0], dict):
                    unit = str(infos[0].get("currency") or "").upper() or unit
            display = format_balance_display(amount, unit=unit)
            if unit == "CNY" and not display.startswith("¥"):
                display = f"¥{amount:,.2f}"
            return {
                "ok": True,
                "amount": amount,
                "unit": unit,
                "display": display,
                "source": url,
                "field": picked.get("field"),
                "note": picked.get("note") or "",
                "provider": prov,
                "host": host,
            }
        return None

    # Default direct (ignore system HTTP_PROXY) unless this LLM opts into proxy
    urls = _candidate_urls(base, prov)
    async with httpx.AsyncClient(**client_kw) as client:
        hit = await _try_urls(client, urls, headers_primary)
        if hit:
            _CACHE[ck] = (time.time(), hit)
            return hit
        # One optional NewAPI-style header retry (not 3× header explosion)
        if any(
            x in host
            for x in ("yunwu", "api", "gate", "closeai", "aihubmix", "chatanywhere")
        ):
            hit = await _try_urls(client, urls, headers_newapi)
            if hit:
                _CACHE[ck] = (time.time(), hit)
                return hit

    # Auth failed on reachable routes → prefer key error over "no balance API"
    if auth_fail and (
        "deepseek.com" in host
        or "siliconflow" in host
        or any(
            t.get("status") in (401, 403) and "/user/balance" in str(t.get("url") or "")
            for t in tried
        )
    ):
        result = {
            "ok": False,
            "error": last_err or "API Key 无效",
            "display": "密钥无效",
            "tried": len(tried),
            "hint": (
                f"服务商返回鉴权失败：{auth_detail or last_err}。"
                "请到设定 → LLM 检查并重新粘贴正确的 API Key（DeepSeek 在 platform.deepseek.com 创建）。"
            ),
            "provider": prov,
            "host": host,
            "auth_error": True,
        }
        # short negative cache only
        _CACHE[ck] = (time.time() - _CACHE_TTL + 15.0, result)
        return result

    # Friendly reasons by host
    if "deepseek.com" in host or "deepseek" in prov:
        hint = (
            "DeepSeek 支持 GET /user/balance；若仍不可查，请确认 API Key 正确，"
            "并到 platform.deepseek.com 查看账户余额。"
        )
    elif "openrouter.ai" in host:
        hint = (
            "OpenRouter 账户总余额接口 /credits 需要 Management Key；"
            "普通 API Key 仅可能返回 Key 限额。请到 openrouter.ai/credits 查看总余额。"
        )
    elif "chatanywhere" in host:
        hint = (
            "ChatAnywhere 未对普通 API Key 公开稳定的余额接口，请到 chatanywhere.tech 控制台查看余额。"
        )
    elif "x.ai" in host or "xai" in prov:
        hint = "xAI 余额在 console.x.ai 控制台查看，公开 API 通常不提供余额查询。"
    elif "openai.com" in host:
        hint = "OpenAI 已不对普通 API Key 开放 billing 余额接口，请到 platform.openai.com 查看。"
    elif _is_local_host(host):
        hint = "本地/内网地址一般没有云端余额概念。"
    elif auth_fail:
        hint = (
            f"鉴权失败（{auth_detail or last_err}）。请检查 API Key；"
            "部分厂商余额接口还需要管理密钥，普通对话 Key 可能不够。"
        )
    else:
        hint = (
            "该服务商未提供可用的余额 API（OpenAI 兼容接口只保证对话，不保证余额）。"
            "仅 DeepSeek 等少数厂商有官方 /user/balance。"
        )

    result = {
        "ok": False,
        "error": last_err or "未找到可用余额接口",
        "display": "密钥无效" if auth_fail else "暂不可查",
        "tried": len(tried),
        "hint": hint,
        "provider": prov,
        "host": host,
        "auth_error": auth_fail,
    }
    # Failures: short TTL so a fixed network path recovers quickly
    _CACHE[ck] = (time.time() - _CACHE_TTL + 20.0, result)
    return result
