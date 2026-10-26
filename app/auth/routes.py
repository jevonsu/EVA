"""Eva login-only API — card verification via remote control plane."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth.local_session import (
    clear_local_session,
    load_local_session,
    save_local_session,
)
from app.auth.hub_grant import (
    consume_pairing,
    consume_unused_pairing,
    current_pairing,
    ensure_pairing,
    issue_pairing,
    refresh_pairing,
    revoke_pairing,
)

from app.auth.instance import install_fingerprint
from app.auth.offline import (
    check_offline_grant,
    revoke_all_offline_grants,
    revoke_offline_grant,
    save_offline_grant,
    touch_offline_grant,
)
from app.auth.login_prefs import load_login_prefs, public_login_prefs, save_login_prefs
from app.auth.remote import (
    control_configured,
    is_allowed_control_url,
    normalize_control_url,
    parse_control_presets,
    pick_reachable_control_url,
    probe_all_control_urls,
    remote_login,
    remote_session_check,
    resolve_control_base,
)
from app.auth.security import client_ip, login_limiter
from app.config import get_settings

logger = logging.getLogger("app.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Legacy cookie names. Sessions are file-based now; these are only expired.
_LEGACY_AUTH_COOKIES = (
    "eva_sess",
    "eva_csrf",
    "eva_device",
    "eva_control_url",
    "eva_control_key",
)


def _ua(request: Request) -> str:
    return (request.headers.get("user-agent") or "")[:300]


def _ip(request: Request) -> str:
    client = request.client.host if request.client else "0.0.0.0"
    return client_ip({k.lower(): v for k, v in request.headers.items()}, client)


def _clear_auth_cookies(response: Response, settings) -> None:
    """Expire leftover host-wide cookies from older Eva builds."""
    secure = bool(getattr(settings, "auth_cookie_secure", False))
    secure_flag = "; Secure" if secure else ""

    def _expire(name: str, *, httponly: bool) -> None:
        response.delete_cookie(
            name,
            path="/",
            secure=secure,
            httponly=httponly,
            samesite="strict",
        )
        response.delete_cookie(name, path="/", secure=secure, samesite="lax")
        response.delete_cookie(name, path="/")
        http_only = "; HttpOnly" if httponly else ""
        # Explicit expire (some WebView2 builds only honor Max-Age=0)
        for samesite in ("Strict", "Lax"):
            response.headers.append(
                "Set-Cookie",
                f"{name}=; Path=/; Max-Age=0; SameSite={samesite}{http_only}{secure_flag}",
            )

    for name in _LEGACY_AUTH_COOKIES:
        _expire(name, httponly=name != "eva_csrf")


async def resolve_auth(
    request: Request,
) -> dict[str, Any] | None:
    """Hub Bearer or this instance's encrypted session file (never shared cookies)."""
    authz = (request.headers.get("authorization") or "").strip()
    token = ""
    device_id = (request.headers.get("x-eva-device") or "").strip()
    control_url = (request.headers.get("x-eva-control") or "").strip()
    control_key = ""
    from_file = False

    if authz.lower().startswith("bearer "):
        token = authz[7:].strip()
    else:
        local = load_local_session()
        if not local:
            return None
        token = local["session_token"]
        device_id = device_id or local["device_id"]
        control_key = local["control_key"]
        from_file = True

    try:
        prefs = load_login_prefs()
    except Exception:
        prefs = {}
    if not control_url:
        control_url = str(prefs.get("control_url") or "")
    if not control_key:
        control_key = (getattr(get_settings(), "auth_control_key", None) or "").strip()
    if not token or len((device_id or "").strip()) < 8:
        return None

    info = await remote_session_check(
        token,
        device_id=device_id,
        control_url=control_url or None,
        control_key=control_key or None,
    )
    if info and (info.get("_rejected") or info.get("_auth_config_error")):
        revoke_offline_grant(token)
        # Only Eva's own session may wipe pairing. A stale Hub Bearer after
        # CardServer restart must not delete the code the operator just minted.
        if from_file:
            revoke_all_offline_grants()
            revoke_pairing()
            clear_local_session()
        from app.auth.remote import invalidate_local_cache

        invalidate_local_cache(token)
        return None
    if info and info.get("_network_error"):
        offline = check_offline_grant(token, device_id=device_id)
        return _attach_session_material(offline, token, device_id, control_url)
    if info and info.get("authenticated"):
        try:
            touch_offline_grant(token)
        except Exception:
            pass
        effective = str(info.get("_control_url") or control_url or "").strip()
        if effective:
            info["_effective_control_url"] = effective
        return _attach_session_material(info, token, device_id, control_url)
    if not control_configured(control_url or None):
        offline = check_offline_grant(token, device_id=device_id)
        return _attach_session_material(offline, token, device_id, control_url)
    return None


def _attach_session_material(
    info: dict[str, Any] | None,
    token: str,
    device_id: str,
    control_url: str,
) -> dict[str, Any] | None:
    if not info:
        return None
    info["_session_token"] = token
    info["_device_id"] = (device_id or "").strip() or str(info.get("device_id") or "")
    if not info.get("_effective_control_url"):
        ctrl = str(info.get("_control_url") or control_url or "").strip()
        if ctrl:
            info["_effective_control_url"] = ctrl
    return info


def _pairing_from_auth(info: dict[str, Any], *, rotate: bool) -> dict[str, Any]:
    kwargs = dict(
        session_token=str(info.get("_session_token") or ""),
        device_id=str(info.get("_device_id") or info.get("device_id") or ""),
        control_url=str(
            info.get("_effective_control_url") or info.get("_control_url") or ""
        ),
        expires_at=float(info.get("expires_at") or 0),
    )
    if rotate:
        return refresh_pairing(**kwargs)
    return ensure_pairing(**kwargs, rotate=False)


class CardLoginBody(BaseModel):
    card_code: str = Field("", max_length=64)
    website: str = ""
    device_id: str = Field(..., min_length=8, max_length=128)
    device_label: str = Field("", max_length=120)
    # 用户填写的鉴权网关（可与 .env 默认合并；空则自动选可达预设）
    control_url: str = Field("", max_length=300)
    # 控制密钥（网关要求时由用户在登录页填写；也可 .env AUTH_CONTROL_KEY 默认）
    control_key: str = Field("", max_length=200)
    # 首选网关连不上时是否自动尝试其它预设（默认开）
    auto_failover: bool = True


@router.get("/bootstrap")
async def auth_bootstrap(probe: bool = False) -> dict:
    """登录页引导。

    不向客户端强推 .env 默认网关。若用户曾在本节点登录成功，
    通过 login_prefs 在 web / Windows 窗口间共享回填字段与 device_id。
    """
    settings = get_settings()
    default_url = normalize_control_url(
        getattr(settings, "auth_control_url", None) or ""
    )
    presets = parse_control_presets()
    prefs = load_login_prefs()
    return {
        "ok": True,
        "default_control_url": default_url,
        "suggested_control_url": default_url,
        "presets": presets,
        "probes": [],
        "env_has_default": bool(default_url or presets),
        "env_control_key_set": bool(
            (getattr(settings, "auth_control_key", None) or "").strip()
        ),
        "auth_enabled": bool(getattr(settings, "auth_enabled", True)),
        "login_prefs": public_login_prefs(prefs),
        "hint": (
            "客户只需填写卡密。"
            "发卡网关与控制密钥由发卡方写入本机 .env（AUTH_CONTROL_URL / AUTH_CONTROL_KEY），不要让客户填写。"
        ),
    }


@router.get("/login-prefs")
async def get_login_prefs() -> dict:
    """Node-local form prefs for the login page (secrets masked)."""
    return {"ok": True, **public_login_prefs()}


class LoginPrefsBody(BaseModel):
    control_url: str = Field("", max_length=300)
    card_code: str = Field("", max_length=64)
    control_key: str = Field("", max_length=200)
    device_id: str = Field("", max_length=128)


@router.put("/login-prefs")
async def put_login_prefs(body: LoginPrefsBody, request: Request) -> dict:
    """Save shared prefs after successful login (requires a session)."""
    info = await resolve_auth(request)
    if not info and getattr(get_settings(), "auth_enabled", True):
        raise HTTPException(401, "未登录")
    prefs = save_login_prefs(
        control_url=body.control_url,
        device_id=body.device_id or None,
        has_saved=True,
    )
    return {"ok": True, **public_login_prefs(prefs)}


@router.get("/probe")
async def auth_probe(url: str = "", control_key: str = "") -> dict:
    """Probe one or all configured control gateways (login page refresh)."""
    extra = [url] if (url or "").strip() else None
    key = (control_key or "").strip() or None
    probes = await probe_all_control_urls(extra, timeout=2.0, control_key=key)
    suggested = ""
    for p in probes:
        if p.get("ok") and p.get("url"):
            suggested = str(p["url"])
            break
    needs_key = any(p.get("needs_control_key") for p in probes)
    return {
        "ok": True,
        "probes": probes,
        "suggested_control_url": suggested,
        "any_reachable": any(p.get("ok") for p in probes),
        "needs_control_key": needs_key,
        "hint": (
            "网关可达但可能需要控制密钥，请在登录页填写（管理员提供）"
            if needs_key
            else ""
        ),
    }


@router.post("/login")
async def card_login(body: CardLoginBody, request: Request, response: Response) -> dict:
    settings = get_settings()
    if not getattr(settings, "auth_enabled", True):
        raise HTTPException(400, "Auth is disabled")

    typed_url = normalize_control_url(body.control_url)
    control_url = typed_url or resolve_control_base(None)
    if not control_url:
        # Auto-pick first reachable preset when user left URL empty
        control_url = await pick_reachable_control_url(None)
    if not control_url:
        raise HTTPException(
            400,
            "发卡服务未配置。请发卡方在本机 .env 填写 AUTH_CONTROL_URL"
            "（你的 CardServer 地址）后再发给客户。",
        )
    # Operator-typed URL is always accepted (CardServer may have moved to a server).
    # Allowlist only blocks silent failover onto an unknown preset.
    if not typed_url and not is_allowed_control_url(control_url):
        raise HTTPException(
            400,
            "该网关不在本机允许列表中。请使用 .env 的 AUTH_CONTROL_URL / AUTH_CONTROL_URLS，"
            "或上次成功登录过的发卡台地址。",
        )

    ip = _ip(request)
    if body.website:
        raise HTTPException(400, "卡密无效或已失效")

    lim = login_limiter().check(f"login:{ip}", limit=8, window_sec=60)
    if not lim.allowed:
        raise HTTPException(
            429,
            detail=f"尝试过于频繁，请 {int(lim.retry_after_sec) + 1} 秒后重试",
            headers={"Retry-After": str(int(lim.retry_after_sec) + 1)},
        )

    node_base = (getattr(settings, "auth_node_id", None) or "eva").strip() or "eva"
    node_id = f"{node_base}:{int(getattr(settings, 'port', 0) or 0)}"
    device_id = (body.device_id or "").strip()
    if len(device_id) < 8:
        raise HTTPException(400, "缺少设备标识，请刷新页面后重试")

    card_code = (body.card_code or "").strip()
    if len(card_code) < 8:
        raise HTTPException(400, "请输入有效卡密")

    # Form key (if typed) → .env. Never read leftover cookies / saved keys.
    form_key = (body.control_key or "").strip()
    env_key = (getattr(settings, "auth_control_key", None) or "").strip()
    control_key = form_key or env_key

    payload, err = await remote_login(
        card_code=card_code,
        client_ip=ip,
        user_agent=_ua(request),
        node_id=node_id,
        device_id=device_id,
        device_label=body.device_label or "",
        control_url=control_url,
        control_key=control_key or None,
        try_fallbacks=bool(body.auto_failover),
    )
    # Typed key rejected: retry the same gateway with .env key
    if (
        not payload
        and err
        and "403" in err
        and form_key
        and env_key
        and form_key != env_key
    ):
        payload, err = await remote_login(
            card_code=card_code,
            client_ip=ip,
            user_agent=_ua(request),
            node_id=node_id,
            device_id=device_id,
            device_label=body.device_label or "",
            control_url=control_url,
            control_key=env_key,
            try_fallbacks=False,
        )
        if payload:
            control_key = env_key
    if not payload:
        login_limiter().register_failure(f"login:{ip}")
        status = 403 if err and "403" in err else 401
        if status == 403:
            err = (
                "无法通过发卡服务验证（控制密钥与发卡台不一致，或反代丢掉了请求头）。"
                "请发卡方核对 Eva .env 的 AUTH_CONTROL_URL / AUTH_CONTROL_KEY"
                "是否与服务器 CardServer 完全相同。客户只需使用卡密，不要填写控制密钥。"
            )
        raise HTTPException(status, detail=err or "登录失败")

    login_limiter().clear_failures(f"login:{ip}")
    token = payload["session_token"]
    # Prefer the base that actually accepted login (after failover)
    used_control = normalize_control_url(
        str(payload.get("control_url") or control_url)
    ) or control_url
    max_age = max(3600, int(payload.get("expires_at", 0) - __import__("time").time()))
    if max_age > 30 * 86400:
        max_age = int(getattr(settings, "auth_session_days", 7) * 86400)

    # Persist shared prefs so web + Windows window see the same card
    try:
        save_login_prefs(
            control_url=used_control,
            card_code="",
            control_key="",
            device_id=device_id,
            has_saved=True,
        )
    except Exception:
        pass

    pairing: dict[str, Any] = {}
    try:
        pairing = issue_pairing(
            session_token=token,
            device_id=device_id,
            control_url=used_control,
            expires_at=float(payload.get("expires_at") or 0),
        )
    except Exception:
        logger.exception("issue pairing after login failed")
        pairing = {}

    allow_offline = bool(payload.get("allow_offline"))
    if allow_offline:
        save_offline_grant(
            session_token=token,
            device_id=device_id,
            expires_at=float(payload.get("expires_at") or 0),
            card_expires_at=(
                float(payload["card_expires_at"])
                if payload.get("card_expires_at") is not None
                else None
            ),
            card_id=payload.get("card_id"),
            card_hint=str(payload.get("card_hint") or ""),
            allow_offline=True,
            control_url=used_control,
            plan_name=str(payload.get("plan_name") or ""),
            instance_id=str(payload.get("instance_id") or ""),
            instance_fp=install_fingerprint(),
        )

    used_key = control_key or (getattr(settings, "auth_control_key", None) or "").strip()
    save_local_session(
        session_token=token,
        device_id=device_id,
        control_key=used_key,
        expires_at=float(payload.get("expires_at") or 0),
    )
    # Drop any leftover host-wide cookies so :8080 / :8081 cannot share a login
    _clear_auth_cookies(response, settings)
    fail_overed = used_control.rstrip("/") != control_url.rstrip("/")
    return {
        "ok": True,
        "redirect": "/",
        "card_hint": payload.get("card_hint"),
        "expires_at": payload.get("expires_at"),
        "card_expires_at": payload.get("card_expires_at"),
        "plan_name": payload.get("plan_name") or "",
        "device_hint": payload.get("device_hint"),
        "device_bound": True,
        "allow_offline": allow_offline,
        "control_url": used_control,
        "failover": fail_overed,
        "pairing_code": pairing.get("pairing_code") or "",
        "pairing_expires_at": pairing.get("expires_at"),
        "message": (
            f"已自动切换到可达网关 {used_control}" if fail_overed else ""
        ),
    }


@router.get("/me")
async def auth_me(request: Request) -> dict:
    settings = get_settings()
    if not getattr(settings, "auth_enabled", True):
        return {"authenticated": True, "auth_enabled": False, "mode": "open"}
    info = await resolve_auth(request)
    if not info:
        return {
            "authenticated": False,
            "auth_enabled": True,
            "mode": "control",
            "control_configured": control_configured(
                (load_login_prefs() or {}).get("control_url")
            ),
        }
    effective = str(info.get("_effective_control_url") or info.get("_control_url") or "").strip()
    return {
        "authenticated": True,
        "auth_enabled": True,
        "mode": "control",
        "card_hint": info.get("card_hint"),
        "expires_at": info.get("expires_at"),
        "card_expires_at": info.get("card_expires_at"),
        "plan_name": info.get("plan_name") or "",
        "device_bound": True,
        "allow_offline": bool(info.get("allow_offline")),
        "offline": bool(info.get("offline")),
        "control_url": effective
        or str((load_login_prefs() or {}).get("control_url") or ""),
        "pairing": current_pairing(),
    }


class HubPairBody(BaseModel):
    pairing_code: str = Field(..., min_length=8, max_length=24)


def _is_loopback(host: str) -> bool:
    h = (host or "").strip().strip("[]").split("%", 1)[0].lower()
    return h in ("127.0.0.1", "::1", "localhost")


def _is_same_machine(request: Request) -> bool:
    ip = _ip(request)
    if _is_loopback(ip):
        return True
    host = (request.url.hostname or "").strip().strip("[]").lower()
    return bool(ip and host and ip.lower() == host)


@router.post("/hub/adopt")
async def hub_adopt(request: Request) -> dict:
    """Same-machine Hub picks up an already-logged-in Eva (no pairing code)."""
    ip = _ip(request)
    lim = login_limiter().check(f"hub-adopt:{ip}", limit=8, window_sec=60)
    if not lim.allowed:
        raise HTTPException(429, "尝试过于频繁")
    if not _is_same_machine(request):
        raise HTTPException(
            403,
            "跨机对接请使用 Eva 连接码（设定 → 办公室）",
        )
    try:
        got = consume_unused_pairing()
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc
    return got


@router.post("/hub/pair")
async def hub_pair(body: HubPairBody, request: Request) -> dict:
    """Hub exchanges a one-time pairing code for the live Eva session (Bearer)."""
    ip = _ip(request)
    lim = login_limiter().check(f"hub-pair:{ip}", limit=10, window_sec=60)
    if not lim.allowed:
        raise HTTPException(
            429,
            detail=f"尝试过于频繁，请 {int(lim.retry_after_sec) + 1} 秒后重试",
            headers={"Retry-After": str(int(lim.retry_after_sec) + 1)},
        )
    try:
        got = consume_pairing(body.pairing_code)
    except ValueError as exc:
        login_limiter().register_failure(f"hub-pair:{ip}")
        raise HTTPException(401, str(exc)) from exc
    login_limiter().clear_failures(f"hub-pair:{ip}")
    return got


@router.get("/hub/pairing")
async def hub_pairing_status(request: Request) -> dict:
    info = await resolve_auth(request)
    if not info:
        raise HTTPException(401, "未登录")
    cur = current_pairing()
    if cur.get("active") and cur.get("pairing_code"):
        return cur
    try:
        return _pairing_from_auth(info, rotate=False)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/hub/pairing/refresh")
async def hub_pairing_refresh(request: Request) -> dict:
    info = await resolve_auth(request)
    if not info:
        raise HTTPException(401, "未登录")
    try:
        return _pairing_from_auth(info, rotate=True)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
