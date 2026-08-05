"""Auth HTTP API — card login + admin card platform."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth.security import (
    admin_limiter,
    client_ip,
    login_limiter,
    normalize_card_code,
    verify_secret,
)
from app.auth.store import get_auth_store
from app.config import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_USER = "eva_sess"
COOKIE_ADMIN = "eva_admin"
COOKIE_CSRF = "eva_csrf"


def _ua(request: Request) -> str:
    return (request.headers.get("user-agent") or "")[:300]


def _ip(request: Request) -> str:
    client = request.client.host if request.client else "0.0.0.0"
    return client_ip(
        {k.lower(): v for k, v in request.headers.items()},
        client,
    )


def _cookie_opts(settings) -> dict[str, Any]:
    secure = bool(getattr(settings, "auth_cookie_secure", False))
    return {
        "httponly": True,
        "samesite": "strict",
        "secure": secure,
        "path": "/",
    }


# ---- User card login ---------------------------------------------------------

class CardLoginBody(BaseModel):
    card_code: str = Field(..., min_length=8, max_length=64)
    # honeypot — bots fill this; humans leave empty
    website: str = ""


@router.post("/login")
async def card_login(body: CardLoginBody, request: Request, response: Response) -> dict:
    settings = get_settings()
    if not getattr(settings, "auth_enabled", True):
        raise HTTPException(400, "Auth is disabled")

    ip = _ip(request)
    if body.website:
        # silent trap
        get_auth_store().audit("honeypot_trip", ip, {"path": "login"})
        raise HTTPException(400, "卡密无效或已失效")

    lim = login_limiter().check(f"login:{ip}", limit=8, window_sec=60)
    if not lim.allowed:
        raise HTTPException(
            429,
            detail=f"尝试过于频繁，请 {int(lim.retry_after_sec) + 1} 秒后重试",
            headers={"Retry-After": str(int(lim.retry_after_sec) + 1)},
        )

    store = get_auth_store()
    token, err = store.login_with_card(
        body.card_code,
        ip=ip,
        user_agent=_ua(request),
        session_ttl_sec=int(getattr(settings, "auth_session_days", 7) * 86400),
    )
    if not token:
        lock = login_limiter().register_failure(f"login:{ip}")
        store.audit("login_fail", ip, {"reason": err[:80]})
        raise HTTPException(401, detail=err or "登录失败")

    login_limiter().clear_failures(f"login:{ip}")
    store.audit("login_ok", ip, {"hint": normalize_card_code(body.card_code)[:7]})

    opts = _cookie_opts(settings)
    max_age = int(getattr(settings, "auth_session_days", 7) * 86400)
    response.set_cookie(COOKIE_USER, token, max_age=max_age, **opts)
    # double-submit CSRF for future form posts
    csrf = secrets.token_urlsafe(24)
    response.set_cookie(
        COOKIE_CSRF,
        csrf,
        max_age=max_age,
        httponly=False,
        samesite="strict",
        secure=opts["secure"],
        path="/",
    )
    return {"ok": True, "redirect": "/"}


@router.post("/logout")
async def card_logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(COOKIE_USER)
    get_auth_store().logout_session(token)
    get_auth_store().audit("logout", _ip(request))
    response.delete_cookie(COOKIE_USER, path="/")
    response.delete_cookie(COOKIE_CSRF, path="/")
    return {"ok": True}


@router.get("/me")
async def auth_me(request: Request) -> dict:
    settings = get_settings()
    if not getattr(settings, "auth_enabled", True):
        return {"authenticated": True, "auth_enabled": False}
    sess = get_auth_store().resolve_session(request.cookies.get(COOKIE_USER))
    if not sess:
        return {"authenticated": False, "auth_enabled": True}
    return {
        "authenticated": True,
        "auth_enabled": True,
        "card_hint": sess.card_hint,
        "expires_at": sess.expires_at,
    }


# ---- Admin -------------------------------------------------------------------

class AdminLoginBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)
    website: str = ""


def require_admin(request: Request) -> None:
    settings = get_settings()
    if not getattr(settings, "auth_enabled", True):
        return
    adm = get_auth_store().resolve_admin_session(request.cookies.get(COOKIE_ADMIN))
    if not adm:
        raise HTTPException(401, "管理员未登录")


@router.post("/admin/login")
async def admin_login(body: AdminLoginBody, request: Request, response: Response) -> dict:
    settings = get_settings()
    ip = _ip(request)
    if body.website:
        get_auth_store().audit("honeypot_trip", ip, {"path": "admin_login"})
        raise HTTPException(401, "用户名或密码错误")

    lim = admin_limiter().check(f"admin:{ip}", limit=5, window_sec=120)
    if not lim.allowed:
        raise HTTPException(
            429,
            detail=f"尝试过于频繁，请 {int(lim.retry_after_sec) + 1} 秒后重试",
            headers={"Retry-After": str(int(lim.retry_after_sec) + 1)},
        )

    user = (getattr(settings, "auth_admin_user", None) or "admin").strip()
    # password: prefer bcrypt hash AUTH_ADMIN_PASSWORD_HASH, else plain AUTH_ADMIN_PASSWORD
    pwd_hash = (getattr(settings, "auth_admin_password_hash", None) or "").strip()
    pwd_plain = (getattr(settings, "auth_admin_password", None) or "").strip()

    ok = False
    if body.username.strip() == user:
        if pwd_hash:
            ok = verify_secret(body.password, pwd_hash)
        elif pwd_plain:
            ok = secrets.compare_digest(body.password, pwd_plain)
        else:
            # refuse empty password config
            ok = False

    if not ok:
        admin_limiter().register_failure(f"admin:{ip}", base_lock_sec=3.0)
        get_auth_store().audit("admin_login_fail", ip)
        raise HTTPException(401, "用户名或密码错误")

    admin_limiter().clear_failures(f"admin:{ip}")
    token = get_auth_store().create_admin_session(ip=ip, user_agent=_ua(request))
    get_auth_store().audit("admin_login_ok", ip)
    opts = _cookie_opts(settings)
    response.set_cookie(COOKIE_ADMIN, token, max_age=8 * 3600, **opts)
    return {"ok": True, "redirect": "/admin"}


@router.post("/admin/logout")
async def admin_logout(request: Request, response: Response) -> dict:
    get_auth_store().logout_admin(request.cookies.get(COOKIE_ADMIN))
    get_auth_store().audit("admin_logout", _ip(request))
    response.delete_cookie(COOKIE_ADMIN, path="/")
    return {"ok": True}


@router.get("/admin/me")
async def admin_me(request: Request) -> dict:
    require_admin(request)
    return {"authenticated": True, "role": "admin"}


class IssueBody(BaseModel):
    count: int = Field(1, ge=1, le=100)
    note: str = ""
    valid_days: int | None = Field(30, ge=0, le=3650)
    max_sessions: int = Field(3, ge=1, le=20)


@router.post("/admin/cards/issue")
async def admin_issue(body: IssueBody, request: Request) -> dict:
    require_admin(request)
    store = get_auth_store()
    days = body.valid_days if body.valid_days and body.valid_days > 0 else None
    codes = store.issue_cards(
        count=body.count,
        note=body.note,
        valid_days=days,
        max_sessions=body.max_sessions,
    )
    store.audit(
        "cards_issue",
        _ip(request),
        {"count": len(codes), "valid_days": days, "note": (body.note or "")[:80]},
    )
    # plaintext returned once — admin UI must display & allow copy; not stored again
    return {"ok": True, "count": len(codes), "cards": codes}


@router.get("/admin/cards")
async def admin_list_cards(
    request: Request,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    require_admin(request)
    rows = get_auth_store().list_cards(status=status or None, limit=limit, offset=offset)
    return {"ok": True, "items": rows, "stats": get_auth_store().card_stats()}


@router.post("/admin/cards/{card_id}/revoke")
async def admin_revoke(card_id: int, request: Request) -> dict:
    require_admin(request)
    ok = get_auth_store().revoke_card(card_id)
    if not ok:
        raise HTTPException(404, "卡不存在或已吊销")
    get_auth_store().audit("card_revoke", _ip(request), {"card_id": card_id})
    return {"ok": True}


@router.get("/admin/stats")
async def admin_stats(request: Request) -> dict:
    require_admin(request)
    return {
        "ok": True,
        "stats": get_auth_store().card_stats(),
        "audit": get_auth_store().recent_audit(40),
    }
