"""Local username/password user store (JSON under data/auth/)."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from typing import Any

from app.auth.security import hash_secret, new_token, verify_secret
from app.config import get_settings

logger = logging.getLogger("app.auth.users")
_lock = threading.RLock()

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,64}$")
_MIN_PASSWORD_LEN = 8


def _users_path():
    p = get_settings().paths()
    p.auth_dir.mkdir(parents=True, exist_ok=True)
    return p.auth_dir / "users.json"


def _load() -> dict[str, Any]:
    path = _users_path()
    if not path.is_file():
        return {"users": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
        if not isinstance(data, dict):
            return {"users": []}
        users = data.get("users")
        if not isinstance(users, list):
            data["users"] = []
        return data
    except Exception:
        logger.exception("failed to load users.json")
        return {"users": []}


def _save(data: dict[str, Any]) -> None:
    path = _users_path()
    tmp = path.with_suffix(".tmp")
    raw = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(raw, encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def user_count() -> int:
    with _lock:
        return len(_load().get("users") or [])


def needs_setup() -> bool:
    return user_count() == 0


def validate_username(username: str) -> str:
    u = (username or "").strip()
    if not _USERNAME_RE.match(u):
        raise ValueError("用户名须为 3–64 位字母/数字/._-")
    return u


def validate_password(password: str) -> str:
    p = password or ""
    if len(p.encode("utf-8")) < _MIN_PASSWORD_LEN:
        raise ValueError(f"密码至少 {_MIN_PASSWORD_LEN} 个字符")
    if len(p.encode("utf-8")) > 200:
        raise ValueError("密码过长")
    return p


def effective_display_name(row: dict[str, Any] | None) -> str:
    """称呼：有 display_name 用它，否则回落登录用户名。"""
    if not isinstance(row, dict):
        return ""
    dn = str(row.get("display_name") or "").strip()
    if dn:
        return dn
    return str(row.get("username") or "").strip()


def validate_display_name(name: str) -> str:
    n = (name or "").strip()
    if not n:
        raise ValueError("称呼不能为空")
    if len(n) > 64:
        raise ValueError("称呼最多 64 个字符")
    if any(ord(c) < 32 for c in n):
        raise ValueError("称呼含非法字符")
    return n


def public_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "username": row.get("username"),
        "display_name": effective_display_name(row),
        "role": row.get("role") or "user",
        "disabled": bool(row.get("disabled")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def list_users() -> list[dict[str, Any]]:
    with _lock:
        return [public_user(u) for u in (_load().get("users") or []) if isinstance(u, dict)]


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    uid = (user_id or "").strip()
    if not uid:
        return None
    with _lock:
        for u in _load().get("users") or []:
            if isinstance(u, dict) and str(u.get("id")) == uid:
                return u
    return None


def get_user_by_username(username: str) -> dict[str, Any] | None:
    try:
        name = validate_username(username)
    except ValueError:
        name = (username or "").strip()
    if not name:
        return None
    with _lock:
        for u in _load().get("users") or []:
            if isinstance(u, dict) and str(u.get("username") or "").lower() == name.lower():
                return u
    return None


def create_user(
    *,
    username: str,
    password: str,
    role: str = "admin",
) -> dict[str, Any]:
    name = validate_username(username)
    pwd = validate_password(password)
    role_n = (role or "user").strip().lower()
    if role_n not in ("admin", "user"):
        role_n = "user"
    with _lock:
        data = _load()
        users = data.setdefault("users", [])
        for u in users:
            if isinstance(u, dict) and str(u.get("username") or "").lower() == name.lower():
                raise ValueError("用户名已存在")
        now = time.time()
        row = {
            "id": str(uuid.uuid4()),
            "username": name,
            "display_name": name,
            "password_hash": hash_secret(pwd),
            "role": role_n,
            "disabled": False,
            "created_at": now,
            "updated_at": now,
        }
        users.append(row)
        _save(data)
        return public_user(row)


def verify_login(username: str, password: str) -> dict[str, Any] | None:
    """Constant-ish path: always hash-check something when user missing."""
    row = get_user_by_username(username)
    dummy = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.G2oQKqKqKqKqKu"  # invalid
    if not row:
        verify_secret(password or "x", dummy)
        return None
    if row.get("disabled"):
        verify_secret(password or "x", str(row.get("password_hash") or dummy))
        return None
    if not verify_secret(password or "", str(row.get("password_hash") or "")):
        return None
    return row


def change_password(user_id: str, *, old_password: str, new_password: str) -> None:
    pwd_new = validate_password(new_password)
    with _lock:
        data = _load()
        users = data.get("users") or []
        target = None
        for u in users:
            if isinstance(u, dict) and str(u.get("id")) == str(user_id):
                target = u
                break
        if not target:
            raise ValueError("用户不存在")
        if not verify_secret(old_password or "", str(target.get("password_hash") or "")):
            raise ValueError("当前密码不正确")
        target["password_hash"] = hash_secret(pwd_new)
        target["updated_at"] = time.time()
        _save(data)


def set_disabled(user_id: str, disabled: bool) -> dict[str, Any]:
    with _lock:
        data = _load()
        for u in data.get("users") or []:
            if isinstance(u, dict) and str(u.get("id")) == str(user_id):
                u["disabled"] = bool(disabled)
                u["updated_at"] = time.time()
                _save(data)
                return public_user(u)
    raise ValueError("用户不存在")



def set_display_name(user_id: str, display_name: str) -> dict[str, Any]:
    """Update the addressable name EVA uses for the user (not login username)."""
    dn = validate_display_name(display_name)
    with _lock:
        data = _load()
        target = None
        for u in data.get("users") or []:
            if isinstance(u, dict) and str(u.get("id")) == str(user_id):
                target = u
                break
        if not target:
            raise ValueError("用户不存在")
        target["display_name"] = dn
        target["updated_at"] = time.time()
        _save(data)
        return public_user(target)


def rename_username(
    user_id: str,
    *,
    new_username: str,
    password: str,
) -> dict[str, Any]:
    """Change login username. If display_name still equals old username, sync it."""
    name = validate_username(new_username)
    with _lock:
        data = _load()
        users = data.get("users") or []
        target = None
        for u in users:
            if isinstance(u, dict) and str(u.get("id")) == str(user_id):
                target = u
                break
        if not target:
            raise ValueError("用户不存在")
        if not verify_secret(password or "", str(target.get("password_hash") or "")):
            raise ValueError("当前密码不正确")
        old = str(target.get("username") or "")
        if name.lower() != old.lower():
            for u in users:
                if (
                    isinstance(u, dict)
                    and u is not target
                    and str(u.get("username") or "").lower() == name.lower()
                ):
                    raise ValueError("用户名已存在")
        old_dn = str(target.get("display_name") or "").strip()
        target["username"] = name
        # Sync 称呼 when it was still the old login name (or empty)
        if not old_dn or old_dn.lower() == old.lower():
            target["display_name"] = name
        target["updated_at"] = time.time()
        _save(data)
        return public_user(target)


def sole_user_row() -> dict[str, Any] | None:
    """Single-user install helper: return the only user row, else None."""
    with _lock:
        users = [u for u in (_load().get("users") or []) if isinstance(u, dict)]
        if len(users) == 1:
            return users[0]
    return None

def ensure_seed_admin_from_env() -> dict[str, Any] | None:
    """If no users and EVA_ADMIN_USER / EVA_ADMIN_PASSWORD set, create admin."""
    if not needs_setup():
        return None
    settings = get_settings()
    user = (getattr(settings, "eva_admin_user", None) or "").strip()
    password = getattr(settings, "eva_admin_password", None) or ""
    if not user or not password:
        return None
    try:
        row = create_user(username=user, password=password, role="admin")
        logger.info("Seeded admin user from EVA_ADMIN_USER")
        return row
    except Exception:
        logger.exception("Failed to seed admin from env")
        return None


def issue_session_token() -> str:
    return new_token(32)
