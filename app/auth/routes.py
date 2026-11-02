"""Eva login API — local username/password (CardServer optional/deprecated)."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth.hub_grant import (
    consume_pairing,
    consume_unused_pairing,
    current_pairing,
    ensure_pairing,
    issue_pairing,
    refresh_pairing,
    revoke_pairing,
)
from app.auth.local_session import (
    clear_local_session,
    load_local_session,
    save_local_session,
)
from app.auth.login_prefs import load_login_prefs, public_login_prefs, save_login_prefs
from app.auth.security import client_ip, login_limiter
from app.auth.users import (
    change_password,
    create_user,
    effective_display_name,
    ensure_seed_admin_from_env,
    get_user_by_id,
    issue_session_token,
    list_users,
    needs_setup,
    public_user,
    set_display_name,
    validate_password,
    validate_username,
    verify_login,
)
from app.config import get_settings

logger = logging.getLogger("app.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

_COOKIE_NAME = "eva_sess"
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


def _session_max_age(settings) -> int:
    days = int(getattr(settings, "auth_session_days", 7) or 7)
    return max(3600, days * 86400)


def _set_session_cookie(response: Response, settings, token: str, max_age: int) -> None:
    secure = bool(getattr(settings, "auth_cookie_secure", False))
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        max_age=max_age,
        expires=max_age,
        path="/",
        httponly=True,
        secure=secure,
        samesite="strict",
    )


def _clear_auth_cookies(response: Response, settings) -> None:
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
        for samesite in ("Strict", "Lax"):
            response.headers.append(
                "Set-Cookie",
                f"{name}=; Path=/; Max-Age=0; SameSite={samesite}{http_only}{secure_flag}",
            )

    for name in _LEGACY_AUTH_COOKIES:
        _expire(name, httponly=name != "eva_csrf")


def _card_remote_enabled() -> bool:
    return bool(getattr(get_settings(), "auth_card_remote", False))


async def resolve_auth(request: Request) -> dict[str, Any] | None:
    """Validate local password session (cookie / Bearer / encrypted file)."""
    authz = (request.headers.get("authorization") or "").strip()
    token = ""
    device_id = (request.headers.get("x-eva-device") or "").strip()
    from_file = False
    local = load_local_session()

    if authz.lower().startswith("bearer "):
        token = authz[7:].strip()
    else:
        cookie_tok = (request.cookies.get(_COOKIE_NAME) or "").strip()
        if local and local.get("session_token"):
            token = local["session_token"]
            device_id = device_id or local.get("device_id") or ""
            from_file = True
            # Prefer file; if cookie mismatches, ignore cookie
            if cookie_tok and cookie_tok != token:
                pass
        elif cookie_tok:
            token = cookie_tok

    if not token:
        return None

    # File session is authoritative for this install
    if local and hmac_equal(local.get("session_token") or "", token):
        user_id = str(local.get("user_id") or "")
        user = get_user_by_id(user_id) if user_id else None
        if not user or user.get("disabled"):
            if from_file:
                clear_local_session()
                try:
                    revoke_pairing()
                except Exception:
                    pass
            return None
        return {
            "authenticated": True,
            "mode": "local",
            "user_id": user_id,
            "username": str(user.get("username") or local.get("username") or ""),
            "display_name": effective_display_name(user),
            "role": str(local.get("role") or user.get("role") or "user"),
            "expires_at": local.get("expires_at"),
            "device_id": device_id or local.get("device_id") or "",
            "_session_token": token,
            "_device_id": device_id or local.get("device_id") or "",
        }

    # Bearer-only (Hub) — accept if matches live pairing material
    try:
        from app.auth.hub_grant import session_from_bearer

        hub_info = session_from_bearer(token)
        if hub_info:
            return hub_info
    except Exception:
        pass
    return None


def hmac_equal(a: str, b: str) -> bool:
    import hmac as _hmac

    return _hmac.compare_digest((a or "").encode("utf-8"), (b or "").encode("utf-8"))


def _pairing_from_auth(info: dict[str, Any], *, rotate: bool) -> dict[str, Any]:
    kwargs = dict(
        session_token=str(info.get("_session_token") or ""),
        device_id=str(info.get("_device_id") or info.get("device_id") or ""),
        control_url="",
        expires_at=float(info.get("expires_at") or 0),
    )
    if rotate:
        return refresh_pairing(**kwargs)
    return ensure_pairing(**kwargs, rotate=False)


class PasswordLoginBody(BaseModel):
    username: str = Field("", max_length=64)
    password: str = Field("", max_length=200)
    website: str = ""
    device_id: str = Field("", max_length=128)
    device_label: str = Field("", max_length=120)
    # Deprecated card fields (ignored unless AUTH_CARD_REMOTE)
    card_code: str = Field("", max_length=64)
    control_url: str = Field("", max_length=300)
    control_key: str = Field("", max_length=200)
    auto_failover: bool = True


class SetupBody(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8, max_length=200)
    website: str = ""
    device_id: str = Field("", max_length=128)
    device_label: str = Field("", max_length=120)


class ChangePasswordBody(BaseModel):
    old_password: str = Field(..., max_length=200)
    new_password: str = Field(..., min_length=8, max_length=200)


@router.get("/bootstrap")
async def auth_bootstrap(probe: bool = False) -> dict:
    settings = get_settings()
    ensure_seed_admin_from_env()
    setup = needs_setup()
    prefs = load_login_prefs()
    return {
        "ok": True,
        "auth_mode": "password",
        "needs_setup": setup,
        "auth_enabled": bool(getattr(settings, "auth_enabled", True)),
        "card_remote_enabled": _card_remote_enabled(),
        "login_prefs": public_login_prefs(prefs),
        "hint": (
            "首次使用：创建管理员账号与密码。"
            if setup
            else "使用本机账号与密码登录。"
        ),
        # Deprecated fields kept empty for old UI
        "default_control_url": "",
        "suggested_control_url": "",
        "presets": [],
        "probes": [],
        "env_has_default": False,
        "env_control_key_set": False,
    }


@router.get("/login-prefs")
async def get_login_prefs() -> dict:
    return {"ok": True, **public_login_prefs()}


class LoginPrefsBody(BaseModel):
    control_url: str = Field("", max_length=300)
    card_code: str = Field("", max_length=64)
    control_key: str = Field("", max_length=200)
    device_id: str = Field("", max_length=128)


@router.put("/login-prefs")
async def put_login_prefs(body: LoginPrefsBody, request: Request) -> dict:
    info = await resolve_auth(request)
    if not info and getattr(get_settings(), "auth_enabled", True):
        raise HTTPException(401, "未登录")
    prefs = save_login_prefs(
        control_url="",
        device_id=body.device_id or None,
        has_saved=True,
    )
    return {"ok": True, **public_login_prefs(prefs)}


@router.get("/probe")
async def auth_probe(url: str = "", control_key: str = "") -> dict:
    """Deprecated: CardServer probe disabled by default."""
    return {
        "ok": True,
        "probes": [],
        "suggested_control_url": "",
        "any_reachable": False,
        "needs_control_key": False,
        "hint": "本机已改为账号密码登录，网关探测已停用。",
        "deprecated": True,
    }


def _finish_login(
    *,
    response: Response,
    settings,
    user: dict[str, Any],
    device_id: str,
) -> dict[str, Any]:
    token = issue_session_token()
    max_age = _session_max_age(settings)
    expires_at = time.time() + max_age
    save_local_session(
        session_token=token,
        device_id=device_id,
        expires_at=expires_at,
        user_id=str(user.get("id") or ""),
        username=str(user.get("username") or ""),
        role=str(user.get("role") or "user"),
        auth_mode="password",
    )
    pairing: dict[str, Any] = {}
    try:
        pairing = issue_pairing(
            session_token=token,
            device_id=device_id,
            control_url="",
            expires_at=expires_at,
        )
    except Exception:
        logger.exception("issue pairing after login failed")
        pairing = {}
    try:
        save_login_prefs(device_id=device_id or None, has_saved=True, control_url="")
    except Exception:
        pass
    _clear_auth_cookies(response, settings)
    _set_session_cookie(response, settings, token, max_age)
    return {
        "ok": True,
        "redirect": "/",
        "auth_mode": "password",
        "username": user.get("username"),
        "role": user.get("role") or "user",
        "expires_at": expires_at,
        "device_bound": bool(device_id),
        "pairing_code": pairing.get("pairing_code") or "",
        "pairing_expires_at": pairing.get("expires_at"),
        "message": "",
    }


@router.post("/setup")
async def auth_setup(body: SetupBody, request: Request, response: Response) -> dict:
    """Create the first admin when no users exist."""
    settings = get_settings()
    if not getattr(settings, "auth_enabled", True):
        raise HTTPException(400, "Auth is disabled")
    ensure_seed_admin_from_env()
    if not needs_setup():
        raise HTTPException(400, "已完成初始化，请直接登录")
    if body.website:
        raise HTTPException(400, "用户名或密码错误")
    ip = _ip(request)
    lim = login_limiter().check(f"setup:{ip}", limit=5, window_sec=300)
    if not lim.allowed:
        raise HTTPException(
            429,
            detail=f"尝试过于频繁，请 {int(lim.retry_after_sec) + 1} 秒后重试",
            headers={"Retry-After": str(int(lim.retry_after_sec) + 1)},
        )
    try:
        validate_username(body.username)
        validate_password(body.password)
        user = create_user(username=body.username, password=body.password, role="admin")
    except ValueError as exc:
        login_limiter().register_failure(f"setup:{ip}")
        raise HTTPException(400, str(exc)) from exc
    login_limiter().clear_failures(f"setup:{ip}")
    device_id = (body.device_id or "").strip()
    return _finish_login(response=response, settings=settings, user=user, device_id=device_id)


@router.post("/login")
async def password_login(
    body: PasswordLoginBody, request: Request, response: Response
) -> dict:
    settings = get_settings()
    if not getattr(settings, "auth_enabled", True):
        raise HTTPException(400, "Auth is disabled")

    ensure_seed_admin_from_env()
    if needs_setup():
        raise HTTPException(400, "请先创建管理员账号（/api/auth/setup）")

    if body.website:
        raise HTTPException(400, "用户名或密码错误")

    ip = _ip(request)
    lim = login_limiter().check(f"login:{ip}", limit=8, window_sec=60)
    if not lim.allowed:
        raise HTTPException(
            429,
            detail=f"尝试过于频繁，请 {int(lim.retry_after_sec) + 1} 秒后重试",
            headers={"Retry-After": str(int(lim.retry_after_sec) + 1)},
        )

    username = (body.username or "").strip()
    password = body.password or ""
    # Compatibility: if only card_code filled and remote disabled, reject clearly
    if not username and (body.card_code or "").strip():
        if _card_remote_enabled():
            raise HTTPException(
                400,
                "卡密登录已弃用。请设置 AUTH_CARD_REMOTE 并使用独立发卡流程，或改用账号密码。",
            )
        raise HTTPException(400, "请使用账号密码登录（卡密已停用）")

    row = verify_login(username, password)
    if not row:
        login_limiter().register_failure(f"login:{ip}")
        raise HTTPException(401, "用户名或密码错误")

    login_limiter().clear_failures(f"login:{ip}")
    device_id = (body.device_id or "").strip()
    return _finish_login(
        response=response,
        settings=settings,
        user=row,
        device_id=device_id,
    )


@router.post("/logout")
async def auth_logout(request: Request, response: Response) -> dict:
    settings = get_settings()
    try:
        revoke_pairing()
    except Exception:
        pass
    clear_local_session()
    _clear_auth_cookies(response, settings)
    return {"ok": True}


@router.post("/change-password")
async def auth_change_password(
    body: ChangePasswordBody, request: Request, response: Response
) -> dict:
    settings = get_settings()
    info = await resolve_auth(request)
    if not info:
        raise HTTPException(401, "未登录")
    try:
        change_password(
            str(info.get("user_id") or ""),
            old_password=body.old_password,
            new_password=body.new_password,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    # Password change invalidates this install's session — force re-login
    try:
        revoke_pairing()
    except Exception:
        pass
    clear_local_session()
    _clear_auth_cookies(response, settings)
    return {
        "ok": True,
        "need_relogin": True,
        "message": "密码已更新，请重新登录",
    }


class DisplayNameBody(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=64)


@router.patch("/profile")
async def auth_update_profile(body: DisplayNameBody, request: Request) -> dict:
    """Update EVA's addressable name for the signed-in user (not login password)."""
    info = await resolve_auth(request)
    if not info:
        raise HTTPException(401, "未登录")
    try:
        row = set_display_name(str(info.get("user_id") or ""), body.display_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "ok": True,
        "username": row.get("username"),
        "display_name": row.get("display_name"),
        "message": "称呼已更新",
    }


class CreateUserBody(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8, max_length=200)
    role: str = Field("user", max_length=16)


@router.get("/users")
async def auth_list_users(request: Request) -> dict:
    info = await resolve_auth(request)
    if not info:
        raise HTTPException(401, "未登录")
    if str(info.get("role") or "") != "admin":
        raise HTTPException(403, "需要管理员")
    return {"ok": True, "users": list_users()}


@router.post("/users")
async def auth_create_user(body: CreateUserBody, request: Request) -> dict:
    info = await resolve_auth(request)
    if not info:
        raise HTTPException(401, "未登录")
    if str(info.get("role") or "") != "admin":
        raise HTTPException(403, "需要管理员")
    role = (body.role or "user").strip().lower()
    if role not in ("admin", "user"):
        role = "user"
    try:
        validate_username(body.username)
        validate_password(body.password)
        row = create_user(username=body.username, password=body.password, role=role)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "user": row}


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
            "mode": "local",
            "needs_setup": needs_setup(),
        }
    display_name = str(info.get("display_name") or "").strip()
    if not display_name:
        uid = str(info.get("user_id") or "")
        row = get_user_by_id(uid) if uid else None
        display_name = effective_display_name(row) if row else str(info.get("username") or "")
    return {
        "authenticated": True,
        "auth_enabled": True,
        "mode": "local",
        "username": info.get("username"),
        "display_name": display_name or info.get("username"),
        "role": info.get("role"),
        "user_id": info.get("user_id"),
        "expires_at": info.get("expires_at"),
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
    ip = _ip(request)
    lim = login_limiter().check(f"hub-adopt:{ip}", limit=8, window_sec=60)
    if not lim.allowed:
        raise HTTPException(429, "尝试过于频繁")
    if not _is_same_machine(request):
        raise HTTPException(403, "跨机对接请使用 Eva 连接码（设定 → 办公室）")
    try:
        got = consume_unused_pairing()
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc
    return got


@router.post("/hub/pair")
async def hub_pair(body: HubPairBody, request: Request) -> dict:
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
