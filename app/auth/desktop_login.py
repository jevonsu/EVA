"""Password login from the Eva launcher (no web form)."""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("app.auth.desktop_login")


def launcher_login(
    *,
    username: str = "",
    password: str = "",
    card_code: str = "",  # deprecated alias ignored
    control_url: str = "",
    control_key: str = "",
    port: int = 0,
) -> tuple[bool, str]:
    """Verify local username/password and write the encrypted session.

    Returns (ok, message). Secrets are not logged.
    """
    # Legacy callers may still pass card_code — reject clearly
    if (card_code or "").strip() and not (username or "").strip():
        return False, "卡密登录已停用，请在启动器填写用户名与密码"

    user = (username or "").strip()
    pwd = password or ""
    if len(user) < 3:
        return False, "请填写用户名（至少 3 位）"
    if len(pwd) < 8:
        return False, "密码至少 8 位"

    try:
        from app.auth.users import (
            create_user,
            ensure_seed_admin_from_env,
            issue_session_token,
            needs_setup,
            verify_login,
        )

        ensure_seed_admin_from_env()
        if needs_setup():
            row = create_user(username=user, password=pwd, role="admin")
        else:
            row = verify_login(user, pwd)
            if not row:
                return False, "用户名或密码错误"
    except ValueError as exc:
        return False, str(exc)
    except Exception as exc:
        logger.exception("launcher login failed")
        return False, str(exc)

    try:
        _persist(row, port=port)
    except Exception as exc:
        logger.exception("persist session failed")
        return False, str(exc)
    return True, f"登录成功 · {row.get('username') or user}"


def _persist(user: dict[str, Any], *, port: int = 0) -> None:
    from app.auth.hub_grant import issue_pairing
    from app.auth.local_session import save_local_session
    from app.auth.login_prefs import load_login_prefs, save_login_prefs
    from app.auth.users import issue_session_token
    from app.config import get_settings

    settings = get_settings()
    days = int(getattr(settings, "auth_session_days", 7) or 7)
    max_age = max(3600, days * 86400)
    expires_at = time.time() + max_age
    token = issue_session_token()
    prefs = load_login_prefs()
    device_id = str(prefs.get("device_id") or "")
    try:
        save_login_prefs(control_url="", device_id=device_id or None, has_saved=True)
    except Exception:
        logger.exception("save_login_prefs failed")
    try:
        issue_pairing(
            session_token=token,
            device_id=device_id,
            control_url="",
            expires_at=expires_at,
        )
    except Exception:
        logger.exception("issue pairing after launcher login failed")
    save_local_session(
        session_token=token,
        device_id=device_id,
        expires_at=expires_at,
        user_id=str(user.get("id") or ""),
        username=str(user.get("username") or ""),
        role=str(user.get("role") or "user"),
        auth_mode="password",
    )


def session_ok() -> bool:
    try:
        from app.auth.local_session import load_local_session

        return bool(load_local_session())
    except Exception:
        return False


def session_info() -> dict[str, Any]:
    try:
        from app.auth.local_session import load_local_session
        from app.auth.users import effective_display_name, get_user_by_id

        local = load_local_session()
        if not local:
            return {"ok": False}
        uid = str(local.get("user_id") or "")
        username = str(local.get("username") or "")
        display_name = username
        if uid:
            row = get_user_by_id(uid)
            if row:
                display_name = effective_display_name(row)
                username = str(row.get("username") or username)
        return {
            "ok": True,
            "username": username,
            "display_name": display_name,
            "role": str(local.get("role") or ""),
            "user_id": uid,
        }
    except Exception:
        return {"ok": False}


def launcher_logout() -> tuple[bool, str]:
    try:
        from app.auth.hub_grant import revoke_pairing
        from app.auth.local_session import clear_local_session

        try:
            revoke_pairing()
        except Exception:
            pass
        clear_local_session()
        return True, "已注销本机会话"
    except Exception as exc:
        logger.exception("launcher logout failed")
        return False, str(exc)



def launcher_change_password(
    *,
    username: str = "",
    old_password: str = "",
    new_password: str = "",
) -> tuple[bool, str]:
    """Change password from launcher; clears session so user must re-login."""
    user = (username or "").strip()
    if len(user) < 3:
        return False, "请填写当前用户名"
    try:
        from app.auth.users import change_password, get_user_by_username, validate_password

        validate_password(new_password or "")
        row = get_user_by_username(user)
        if not row:
            return False, "用户不存在"
        change_password(
            str(row.get("id") or ""),
            old_password=old_password or "",
            new_password=new_password or "",
        )
    except ValueError as exc:
        return False, str(exc)
    except Exception as exc:
        logger.exception("launcher change password failed")
        return False, str(exc)
    try:
        launcher_logout()
    except Exception:
        pass
    return True, "密码已更新，请重新登录"


def launcher_rename_user(
    *,
    username: str = "",
    password: str = "",
    new_username: str = "",
) -> tuple[bool, str]:
    """Rename login username from launcher; refreshes local session if logged in."""
    user = (username or "").strip()
    new_u = (new_username or "").strip()
    if len(user) < 3:
        return False, "请填写当前用户名"
    if len(new_u) < 3:
        return False, "新用户名至少 3 位"
    try:
        from app.auth.local_session import load_local_session, save_local_session
        from app.auth.users import get_user_by_username, rename_username

        row = get_user_by_username(user)
        if not row:
            return False, "用户不存在"
        pub = rename_username(
            str(row.get("id") or ""),
            new_username=new_u,
            password=password or "",
        )
    except ValueError as exc:
        return False, str(exc)
    except Exception as exc:
        logger.exception("launcher rename failed")
        return False, str(exc)

    # Keep session if this install was logged in as that user
    try:
        local = load_local_session()
        if local and str(local.get("user_id") or "") == str(pub.get("id") or ""):
            save_local_session(
                session_token=str(local.get("session_token") or ""),
                device_id=str(local.get("device_id") or ""),
                expires_at=float(local.get("expires_at") or 0),
                user_id=str(pub.get("id") or ""),
                username=str(pub.get("username") or new_u),
                role=str(pub.get("role") or local.get("role") or "user"),
                auth_mode=str(local.get("auth_mode") or "password"),
            )
    except Exception:
        logger.exception("refresh session after rename failed")
    return True, f"用户名已改为 {pub.get('username') or new_u}"
