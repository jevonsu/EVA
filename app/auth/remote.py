"""Eva → remote card-auth control-plane client.

Supports multi-environment gateways (e.g. company intranet + public egress):
  AUTH_CONTROL_URL=http://10.11.11.41:8090
  AUTH_CONTROL_URLS=公司内网=http://10.11.11.41:8090,外出公网=http://cardserver.hn.takin.cc

Login / session-check fail over across reachable bases when the preferred
address is unreachable (common when switching office ↔ travel networks).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import get_settings

logger = logging.getLogger("app.auth.remote")

# Positive session cache — short so CardServer 吊销 quickly takes effect.
_session_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL = 12.0
# Brief negative cache for network failures to avoid stampede timeouts
_neg_cache: dict[str, float] = {}
_NEG_TTL = 4.0
# Per-base probe cache (login page chips)
_probe_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_PROBE_TTL = 20.0

# Last working control base per session token (office ↔ travel switch)
_last_good_base: dict[str, str] = {}

# Shared client — creating AsyncClient per request is expensive on Windows
_client: httpx.AsyncClient | None = None
_client_loop_id: int | None = None

# Rate-limit identical warning lines (Windows ConnectError often has empty str(e))
_warn_last: dict[str, float] = {}
_WARN_INTERVAL = 30.0


def _format_httpx_err(exc: BaseException) -> str:
    """Human-readable httpx error; many Windows connect failures have empty str(e)."""
    name = type(exc).__name__
    msg = (str(exc) or "").strip()
    cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
    cause_s = (str(cause) or "").strip() if cause else ""
    parts = [name]
    if msg:
        parts.append(msg)
    elif cause_s:
        parts.append(cause_s)
    else:
        if isinstance(exc, httpx.ConnectError):
            parts.append("connection refused or host unreachable")
        elif isinstance(exc, httpx.TimeoutException):
            parts.append("timed out")
        else:
            parts.append("network error")
    return ": ".join(parts) if len(parts) > 1 else parts[0]


def _warn_throttled(key: str, message: str) -> None:
    now = time.time()
    last = _warn_last.get(key, 0.0)
    if now - last < _WARN_INTERVAL:
        return
    _warn_last[key] = now
    logger.warning(message)


def _get_client() -> httpx.AsyncClient:
    """Reuse one AsyncClient per event loop (connect pool + DNS cache).

    trust_env=False: 鉴权网关多为内网地址（如 http://10.11.11.41:8090）。
    若遵循系统 HTTP(S)_PROXY，请求会被代理劫持并常表现为 502，
    与备份环境「直连网关」行为不一致。控制面请求必须直连，不走代理。
    """
    global _client, _client_loop_id
    try:
        loop = asyncio.get_running_loop()
        loop_id = id(loop)
    except RuntimeError:
        loop_id = None

    if _client is None or _client.is_closed or loop_id != _client_loop_id:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=2.0, read=5.0, write=5.0, pool=2.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            trust_env=False,
            proxy=None,
        )
        _client_loop_id = loop_id
    return _client


def _env_base() -> str:
    settings = get_settings()
    return normalize_control_url(getattr(settings, "auth_control_url", None) or "")


def _env_control_key() -> str:
    """Optional default from .env AUTH_CONTROL_KEY (not required if user fills login form)."""
    return (getattr(get_settings(), "auth_control_key", None) or "").strip()


def resolve_control_key(
    override: str | None = None,
    *,
    allow_stock_fallback: bool = False,
) -> str:
    """Prefer login-form/cookie key → .env. No stock default (that was a bypass)."""
    o = (override or "").strip()
    if o:
        return o
    return _env_control_key()


def normalize_control_url(url: str | None) -> str:
    s = (url or "").strip().rstrip("/")
    if not s:
        return ""
    if not (s.startswith("http://") or s.startswith("https://")):
        s = "http://" + s
    return s.rstrip("/")


def _auto_label(url: str) -> str:
    """Guess a short Chinese label from host/IP for chips."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""
    if not host:
        return url
    # RFC1918 private
    if (
        host.startswith("10.")
        or host.startswith("192.168.")
        or re.match(r"^172\.(1[6-9]|2\d|3[0-1])\.", host)
        or host in ("localhost", "127.0.0.1")
    ):
        return "公司内网"
    return "外出公网"


def parse_control_presets() -> list[dict[str, str]]:
    """Parse AUTH_CONTROL_URL + AUTH_CONTROL_URLS into ordered unique presets.

    AUTH_CONTROL_URLS examples:
      公司内网=http://10.11.11.41:8090,外出公网=http://cardserver.hn.takin.cc
      http://10.11.11.41:8090,http://cardserver.hn.takin.cc
    """
    settings = get_settings()
    raw_multi = (getattr(settings, "auth_control_urls", None) or "").strip()
    primary = _env_base()

    items: list[tuple[str, str]] = []  # (label, url)

    def add(label: str, url: str) -> None:
        u = normalize_control_url(url)
        if not u:
            return
        lab = (label or "").strip() or _auto_label(u)
        for _, existing in items:
            if existing == u:
                return
        items.append((lab, u))

    # Multi list first so labels are preserved; primary fills default if alone
    if raw_multi:
        for part in re.split(r"[,;\n]+", raw_multi):
            part = part.strip()
            if not part:
                continue
            if "=" in part and not part.startswith("http"):
                # label=url (label may contain Chinese)
                lab, _, rest = part.partition("=")
                add(lab.strip(), rest.strip())
            elif "|" in part and not part.lower().startswith("http"):
                lab, _, rest = part.partition("|")
                add(lab.strip(), rest.strip())
            else:
                add("", part)

    if primary:
        add(_auto_label(primary), primary)

    # Builtin defaults only when nothing configured (blank project still OK)
    return [{"id": f"p{i}", "label": lab, "url": url} for i, (lab, url) in enumerate(items)]


def allowed_control_urls() -> list[str]:
    """Pin Eva to configured gateways (+ last successful login)."""
    out: list[str] = []

    def push(u: str | None) -> None:
        n = normalize_control_url(u)
        if n and n not in out:
            out.append(n)

    push(_env_base())
    for p in parse_control_presets():
        push(p.get("url"))
    try:
        from app.auth.login_prefs import load_login_prefs

        prefs = load_login_prefs()
        if prefs.get("has_saved"):
            push(prefs.get("control_url"))
    except Exception:
        pass
    return out


def is_allowed_control_url(url: str | None) -> bool:
    n = normalize_control_url(url)
    if not n:
        return False
    allowed = allowed_control_urls()
    if not allowed:
        return True
    return n in allowed


def control_url_candidates(
    preferred: str | None = None,
    *,
    session_token: str | None = None,
) -> list[str]:
    """Ordered list of control bases to try (preferred + last-good + presets).

    The URL the operator typed (``preferred``) and the last working base
    are always tried. The allowlist only constrains failover to other presets
    so a server CardServer is not dropped when .env still lists 127.0.0.1.
    """
    allowed = allowed_control_urls()
    out: list[str] = []

    def push(u: str | None, *, force: bool = False) -> None:
        n = normalize_control_url(u)
        if not n or n in out:
            return
        if allowed and n not in allowed and not force:
            return
        out.append(n)

    if session_token:
        push(_last_good_base.get(session_token[:32]), force=True)
    push(preferred, force=True)
    push(_env_base())
    for p in parse_control_presets():
        push(p.get("url"))
    return out


def resolve_control_base(control_url: str | None = None) -> str:
    return normalize_control_url(control_url) or _env_base()


def control_configured(control_url: str | None = None) -> bool:
    """Gateway URL present; control key is server .env (checked at request time)."""
    if resolve_control_base(control_url):
        return True
    return bool(parse_control_presets())


def _json_headers(
    *,
    control_key: str | None = None,
    with_control_key: bool = True,
) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if with_control_key:
        key = resolve_control_key(control_key)
        if key:
            # Header + Bearer: some Nginx/宝塔/frp setups drop unknown X-* headers
            headers["X-Control-Key"] = key
            headers["Authorization"] = f"Bearer {key}"
    return headers


def _with_control_key(body: dict[str, Any], control_key: str | None) -> dict[str, Any]:
    key = resolve_control_key(control_key)
    if key:
        body = {**body, "control_key": key}
    return body


def _remember_good(session_token: str, base: str) -> None:
    if session_token and base:
        _last_good_base[session_token[:32]] = normalize_control_url(base)


async def probe_control_url(
    base: str,
    *,
    timeout: float = 2.0,
    control_key: str | None = None,
) -> dict[str, Any]:
    """Lightweight reachability probe (does not require a valid session)."""
    base = normalize_control_url(base)
    if not base:
        return {"url": "", "ok": False, "error": "empty", "latency_ms": None}

    key = resolve_control_key(control_key)
    # Cache by base+key so different keys don't share a stale result
    cache_id = f"{base}|k:{key[:8] if key else '-'}"
    now = time.time()
    cached = _probe_cache.get(cache_id)
    if cached and cached[0] > now:
        return dict(cached[1])

    url = f"{base}/api/cards/control/session/check"
    t0 = time.perf_counter()
    try:
        client = _get_client()
        r = await client.post(
            url,
            headers=_json_headers(control_key=key or None),
            json=_with_control_key(
                {
                    "session_token": "__eva_probe__",
                    "device_id": "eva-probe-00",
                    "instance_id": "eva-inst-probe00",
                    "instance_fp": "0" * 64,
                },
                key,
            ),
            timeout=httpx.Timeout(connect=timeout, read=timeout, write=timeout, pool=timeout),
        )
        ms = int((time.perf_counter() - t0) * 1000)
        # Any HTTP response means the control plane is reachable
        ok = r.status_code < 500
        note = ""
        if r.status_code == 403:
            note = "网关可达，但可能需要控制密钥（登录页填写）"
        elif r.status_code in (401, 422):
            note = "网关可达"
        result = {
            "url": base,
            "ok": ok,
            "status": r.status_code,
            "latency_ms": ms,
            "error": "" if ok else f"HTTP {r.status_code}",
            "note": note,
            "needs_control_key": r.status_code == 403 and not key,
        }
    except httpx.HTTPError as e:
        ms = int((time.perf_counter() - t0) * 1000)
        result = {
            "url": base,
            "ok": False,
            "status": None,
            "latency_ms": ms,
            "error": _format_httpx_err(e),
            "note": "",
            "needs_control_key": False,
        }

    _probe_cache[cache_id] = (now + _PROBE_TTL, result)
    return dict(result)


async def probe_all_control_urls(
    extra: list[str] | None = None,
    *,
    timeout: float = 2.0,
    control_key: str | None = None,
) -> list[dict[str, Any]]:
    """Probe configured presets (+ optional extras) concurrently."""
    presets = parse_control_presets()
    urls: list[str] = []
    labels: dict[str, str] = {}
    for p in presets:
        u = p["url"]
        urls.append(u)
        labels[u] = p.get("label") or _auto_label(u)
    for e in extra or []:
        u = normalize_control_url(e)
        if u and u not in labels:
            urls.append(u)
            labels[u] = _auto_label(u)

    if not urls:
        return []

    results = await asyncio.gather(
        *[probe_control_url(u, timeout=timeout, control_key=control_key) for u in urls],
        return_exceptions=True,
    )
    out: list[dict[str, Any]] = []
    for u, r in zip(urls, results):
        if isinstance(r, Exception):
            row = {
                "url": u,
                "ok": False,
                "status": None,
                "latency_ms": None,
                "error": str(r),
                "label": labels.get(u, _auto_label(u)),
            }
        else:
            row = dict(r)
            row["label"] = labels.get(u, _auto_label(u))
        out.append(row)
    # reachable first, then by latency
    out.sort(key=lambda x: (0 if x.get("ok") else 1, x.get("latency_ms") or 99999))
    return out


async def pick_reachable_control_url(
    preferred: str | None = None,
    *,
    timeout: float = 2.0,
) -> str:
    """Return preferred if up, else first reachable preset, else preferred/primary."""
    pref = normalize_control_url(preferred)
    probes = await probe_all_control_urls([pref] if pref else None, timeout=timeout)
    if pref:
        for p in probes:
            if p.get("url") == pref and p.get("ok"):
                return pref
    for p in probes:
        if p.get("ok") and p.get("url"):
            return str(p["url"])
    return pref or _env_base() or (probes[0]["url"] if probes else "")


async def _login_one(
    base: str,
    *,
    card_code: str,
    client_ip: str,
    user_agent: str,
    node_id: str,
    device_id: str,
    device_label: str,
    instance_id: str,
    instance_secret: str,
    instance_fp: str,
    machine_fp: str,
    control_key: str | None = None,
) -> tuple[dict[str, Any] | None, str, bool]:
    """Returns (payload, error, is_network_error)."""
    url = f"{base}/api/cards/control/login"
    key = resolve_control_key(control_key)
    try:
        client = _get_client()
        r = await client.post(
            url,
            headers=_json_headers(control_key=key or None),
            json=_with_control_key(
                {
                    "card_code": card_code,
                    "client_ip": client_ip,
                    "user_agent": user_agent,
                    "node_id": node_id,
                    "device_id": device_id,
                    "device_label": device_label or "",
                    "instance_id": instance_id,
                    "instance_secret": instance_secret or "",
                    "instance_fp": instance_fp,
                    "machine_fp": machine_fp or "",
                },
                key,
            ),
            timeout=httpx.Timeout(connect=3.0, read=12.0, write=12.0, pool=3.0),
        )
    except httpx.ConnectError as e:
        err_s = _format_httpx_err(e)
        _warn_throttled(f"login|{base}", f"control login connect error: {err_s} → {url}")
        return None, f"无法连接鉴权网关 {base}（连接失败）。请检查地址/端口与网络", True
    except httpx.TimeoutException as e:
        err_s = _format_httpx_err(e)
        _warn_throttled(f"login|{base}", f"control login timeout: {err_s} → {url}")
        return None, f"鉴权网关超时 {base}，请检查网络或服务是否卡死", True
    except httpx.HTTPError as e:
        err_s = _format_httpx_err(e)
        _warn_throttled(f"login|{base}", f"control login network error: {err_s} → {url}")
        return None, f"无法连接鉴权网关 {base}（请检查地址与网络）", True

    if r.status_code == 401:
        try:
            detail = r.json().get("detail") or "卡密无效或已失效"
        except Exception:
            detail = "卡密无效或已失效"
        return None, str(detail), False
    if r.status_code == 403:
        if not key:
            return (
                None,
                "鉴权网关要求控制密钥，但本次请求没有带上。"
                "请在登录页填写发卡台管理台「控制密钥」里复制的值"
                "（不是卡密，也不是管理员密码），"
                "或写入本机 .env 的 AUTH_CONTROL_KEY。",
                False,
            )
        return (
            None,
            "鉴权网关拒绝访问（403）：控制密钥与发卡台 AUTH_CONTROL_KEY 不一致。"
            "请到服务器发卡台管理台重新复制当前密钥；"
            "部署后密钥以服务器 .env / data/auth/control_key.txt 为准。"
            "若前面有 Nginx/宝塔反代，请放行 X-Control-Key 与 Authorization。",
            False,
        )
    if r.status_code == 429:
        return None, "尝试过于频繁，请稍后再试", False
    if r.status_code == 422:
        return None, "缺少项目或设备标识，请升级到最新客户端后重试", False
    if r.status_code == 404:
        return (
            None,
            f"鉴权接口不存在 (404)：{url}。请确认网关地址是否为卡密控制面根地址",
            False,
        )
    if r.status_code in (502, 503, 504):
        return (
            None,
            f"鉴权网关不可用 ({r.status_code})：{base}。"
            "请确认网关上的卡密服务已启动；若网关只做转发，检查上游是否正常。",
            True,
        )
    if r.status_code >= 400:
        detail = ""
        try:
            detail = str(r.json().get("detail") or "")[:200]
        except Exception:
            detail = (r.text or "")[:200]
        extra = f"：{detail}" if detail else ""
        return None, f"鉴权服务错误 ({r.status_code}){extra}", False

    try:
        data = r.json()
    except Exception:
        return None, "鉴权服务返回了非 JSON 内容（地址可能不是鉴权网关）", False
    if not data.get("ok") or not data.get("session_token"):
        return None, "鉴权服务返回异常（缺少 session_token）", False
    data["control_url"] = base
    return data, "", False


async def remote_login(
    *,
    card_code: str,
    client_ip: str,
    user_agent: str,
    node_id: str = "eva",
    device_id: str = "",
    device_label: str = "",
    control_url: str | None = None,
    control_key: str | None = None,
    try_fallbacks: bool = True,
) -> tuple[dict[str, Any] | None, str]:
    from app.auth.instance import instance_claims, save_instance_secret

    claims = instance_claims()
    preferred = resolve_control_base(control_url)
    bases = control_url_candidates(preferred) if try_fallbacks else ([preferred] if preferred else [])
    if not bases:
        return None, (
            "请填写鉴权服务地址（网关），例如公司内网 http://10.11.11.41:8090 "
            "或外出公网 http://cardserver.hn.takin.cc"
        )

    last_net_err = ""
    tried: list[str] = []
    for base in bases:
        tried.append(base)
        payload, err, is_net = await _login_one(
            base,
            card_code=card_code,
            client_ip=client_ip,
            user_agent=user_agent,
            node_id=node_id,
            device_id=device_id,
            device_label=device_label,
            instance_id=claims["instance_id"],
            instance_secret=claims["instance_secret"],
            instance_fp=claims["instance_fp"],
            machine_fp=claims["machine_fp"],
            control_key=control_key,
        )
        if payload:
            tok = str(payload.get("session_token") or "")
            issued = str(payload.get("instance_secret") or "")
            if issued:
                save_instance_secret(issued)
                claims["instance_secret"] = issued
            _remember_good(tok, base)
            if base != preferred and preferred:
                logger.info("control login failover: %s → %s", preferred, base)
            return payload, ""
        if is_net:
            last_net_err = err
            continue
        # Auth / config error — don't mask with other bases
        return None, err

    if len(tried) > 1:
        return (
            None,
            f"所有鉴权网关均不可达（已尝试 {len(tried)} 个）。"
            f"最近错误：{last_net_err or '网络失败'}。"
            "公司内网请连 VPN/办公网；外出请选公网网关。",
        )
    return None, last_net_err or "无法连接鉴权网关"


async def _session_check_one(
    base: str,
    session_token: str,
    device_id: str,
    control_key: str | None = None,
) -> dict[str, Any] | None:
    """Single-base session check. Returns auth dict, network-error dict, or None."""
    key = resolve_control_key(control_key)
    from app.auth.instance import instance_claims

    claims = instance_claims()
    inst = claims["instance_id"]
    inst_fp = claims["instance_fp"]
    cache_key = (
        f"{session_token}|{device_id or ''}|{inst}|{inst_fp[:16]}|{base}"
        f"|k:{key[:8] if key else '-'}"
    )
    now = time.time()
    cached = _session_cache.get(cache_key)
    if cached and cached[0] > now:
        data = dict(cached[1])
        data["_control_url"] = base
        return data

    neg_until = _neg_cache.get(cache_key)
    if neg_until and neg_until > now:
        return {
            "_network_error": True,
            "_cached": cached[1] if cached else None,
            "_control_url": base,
        }

    url = f"{base}/api/cards/control/session/check"
    try:
        client = _get_client()
        r = await client.post(
            url,
            headers=_json_headers(control_key=key or None),
            json=_with_control_key(
                {
                    "session_token": session_token,
                    "device_id": device_id or "",
                    "instance_id": inst,
                    "instance_fp": inst_fp,
                },
                key,
            ),
        )
    except httpx.HTTPError as e:
        err_s = _format_httpx_err(e)
        _warn_throttled(
            f"session-check|{base}",
            f"control session check error: {err_s} → {url}",
        )
        _neg_cache[cache_key] = now + _NEG_TTL
        return {
            "_network_error": True,
            "_control_url": base,
        }

    if r.status_code != 200:
        if r.status_code >= 500 or r.status_code in (502, 503, 504):
            _warn_throttled(
                f"session-check-http|{base}|{r.status_code}",
                f"control session check HTTP {r.status_code} → {url}",
            )
            _neg_cache[cache_key] = now + _NEG_TTL
            return {
                "_network_error": True,
                "_control_url": base,
            }
        _session_cache.pop(cache_key, None)
        _neg_cache.pop(cache_key, None)
        if r.status_code == 403:
            return {"_auth_config_error": True, "_control_url": base}
        return {"_rejected": True, "_control_url": base}
    try:
        data = r.json()
    except Exception:
        _warn_throttled(
            f"session-check-json|{base}",
            f"control session check non-JSON response → {url}",
        )
        _session_cache.pop(cache_key, None)
        return None
    if not data.get("authenticated"):
        _session_cache.pop(cache_key, None)
        _neg_cache.pop(cache_key, None)
        return {"_rejected": True, "_control_url": base}
    _neg_cache.pop(cache_key, None)
    data = dict(data)
    data["_control_url"] = base
    _session_cache[cache_key] = (now + _CACHE_TTL, data)
    _remember_good(session_token, base)
    return data


async def remote_session_check(
    session_token: str,
    *,
    device_id: str = "",
    control_url: str | None = None,
    control_key: str | None = None,
) -> dict[str, Any] | None:
    if not session_token:
        return None
    bases = control_url_candidates(control_url, session_token=session_token)
    if not bases:
        return None

    last_net: dict[str, Any] | None = None
    for base in bases:
        result = await _session_check_one(
            base, session_token, device_id, control_key=control_key
        )
        if not result:
            continue
        if result.get("_rejected") or result.get("_auth_config_error"):
            return result
        if result.get("_network_error"):
            last_net = result
            continue
        if result.get("authenticated"):
            preferred = normalize_control_url(control_url)
            if preferred and result.get("_control_url") != preferred:
                logger.info(
                    "session check failover: %s → %s",
                    preferred,
                    result.get("_control_url"),
                )
            return result
    return last_net


def invalidate_local_cache(session_token: str | None = None) -> None:
    if session_token:
        keys = [
            k
            for k in _session_cache
            if k.startswith(session_token + "|") or k == session_token
        ]
        for k in keys:
            _session_cache.pop(k, None)
        neg_keys = [k for k in _neg_cache if k.startswith(session_token + "|")]
        for k in neg_keys:
            _neg_cache.pop(k, None)
        _last_good_base.pop(session_token[:32], None)
    else:
        _session_cache.clear()
        _neg_cache.clear()
        _last_good_base.clear()
