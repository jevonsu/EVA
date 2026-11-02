"""One-time Hub pairing after Eva local login.

After a successful password login we mint a short pairing code. Hub
exchanges that code for the live session token (Bearer). Disk stores
only code_hash — session material is read from the live local session.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from typing import Any

from app.config import get_settings

_lock = threading.RLock()
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PAIRING_TTL_SEC = 30 * 60
# In-memory only: last issued plaintext code for UI until used/expired
_last_code: str = ""
_last_code_exp: float = 0.0


def _path():
    p = get_settings().paths().hub_pairing
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _pepper() -> str:
    from app.auth.pepper import get_auth_pepper

    return get_auth_pepper()


def _hash(value: str) -> str:
    return hmac.new(
        _pepper().encode("utf-8"),
        (value or "").encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _new_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    return raw[:4] + "-" + raw[4:]


def normalize_pairing_code(raw: str | None) -> str:
    s = (raw or "").strip().upper().replace(" ", "")
    if "-" not in s and len(s) == 8:
        s = s[:4] + "-" + s[4:]
    return s


def _load() -> dict[str, Any]:
    p = _path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data: dict[str, Any]) -> None:
    # Never persist plaintext pairing_code / session_token
    clean = {k: v for k, v in data.items() if k not in ("pairing_code", "session_token")}
    _path().write_text(
        json.dumps(clean, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _alive(row: dict[str, Any]) -> bool:
    if not row or row.get("used"):
        return False
    return float(row.get("pairing_expires_at") or 0) > time.time()


def _session_valid(expires_at: float) -> bool:
    exp = float(expires_at or 0)
    return exp <= 0 or exp > time.time()


def _load_live_session() -> dict[str, Any] | None:
    try:
        from app.auth.local_session import load_local_session

        return load_local_session()
    except Exception:
        return None


def session_from_bearer(token: str) -> dict[str, Any] | None:
    """Hub Bearer matches this install's live local session."""
    tok = (token or "").strip()
    if not tok:
        return None
    local = _load_live_session()
    if not local:
        return None
    live = str(local.get("session_token") or "")
    if not live or not hmac.compare_digest(live.encode("utf-8"), tok.encode("utf-8")):
        return None
    return {
        "authenticated": True,
        "mode": "local",
        "user_id": local.get("user_id"),
        "username": local.get("username"),
        "role": local.get("role") or "user",
        "expires_at": local.get("expires_at"),
        "device_id": local.get("device_id") or "",
        "_session_token": live,
        "_device_id": local.get("device_id") or "",
    }


def issue_pairing(
    *,
    session_token: str,
    device_id: str,
    control_url: str,
    expires_at: float,
) -> dict[str, Any]:
    """Mint a fresh pairing code bound to the current Eva session."""
    global _last_code, _last_code_exp
    token = (session_token or "").strip()
    if not token:
        raise ValueError("missing session")
    code = _new_code()
    now = time.time()
    pair_exp = min(now + PAIRING_TTL_SEC, float(expires_at or (now + PAIRING_TTL_SEC)))
    if float(expires_at or 0) <= 0:
        pair_exp = now + PAIRING_TTL_SEC
    row = {
        "code_hash": _hash(code),
        "code_hint": code[:2] + "••" + code[-2:],
        "device_id": (device_id or "")[:128],
        "control_url": (control_url or "")[:300],
        "session_expires_at": float(expires_at or 0),
        "pairing_expires_at": pair_exp,
        "used": False,
        "created_at": now,
    }
    with _lock:
        _save(row)
        _last_code = code
        _last_code_exp = pair_exp
    return public_pairing(row, plaintext_code=code)


def public_pairing(
    row: dict[str, Any] | None = None, *, plaintext_code: str = ""
) -> dict[str, Any]:
    global _last_code, _last_code_exp
    data = row if isinstance(row, dict) else None
    with _lock:
        if data is None:
            data = _load()
        if not _alive(data):
            _last_code = ""
            _last_code_exp = 0.0
            return {
                "ok": True,
                "active": False,
                "pairing_code": "",
                "expires_at": None,
                "remaining_sec": 0,
            }
        rem = max(0, int(float(data.get("pairing_expires_at") or 0) - time.time()))
        code = plaintext_code or ""
        if not code and _last_code and _last_code_exp > time.time():
            if hmac.compare_digest(_hash(_last_code), str(data.get("code_hash") or "")):
                code = _last_code
        return {
            "ok": True,
            "active": True,
            "pairing_code": code,
            "expires_at": data.get("pairing_expires_at"),
            "remaining_sec": rem,
            "hint": data.get("code_hint") or "",
        }


def current_pairing() -> dict[str, Any]:
    with _lock:
        return public_pairing(_load())


def _resolve_session_material(
    *,
    session_token: str = "",
    device_id: str = "",
    control_url: str = "",
    expires_at: float = 0,
) -> tuple[str, str, str, float]:
    token = (session_token or "").strip()
    dev = (device_id or "").strip()
    ctrl = (control_url or "").strip()
    exp = float(expires_at or 0)
    with _lock:
        data = _load()
    if not dev:
        dev = str(data.get("device_id") or "").strip()
    if not ctrl:
        ctrl = str(data.get("control_url") or "").strip()
    if not exp:
        exp = float(data.get("session_expires_at") or 0)
    local = _load_live_session()
    if local:
        token = str(local.get("session_token") or "").strip() or token
        dev = dev or str(local.get("device_id") or "").strip()
        exp = float(local.get("expires_at") or 0) or exp
    return token, dev, ctrl, exp


def ensure_pairing(
    *,
    session_token: str = "",
    device_id: str = "",
    control_url: str = "",
    expires_at: float = 0,
    rotate: bool = False,
) -> dict[str, Any]:
    token, dev, ctrl, exp = _resolve_session_material(
        session_token=session_token,
        device_id=device_id,
        control_url=control_url,
        expires_at=expires_at,
    )
    if not token:
        raise ValueError("请先在 Eva 用账号密码登录")
    if not _session_valid(exp):
        raise ValueError("Eva 会话已过期，请重新登录")
    if not rotate:
        with _lock:
            data = _load()
            if _alive(data):
                return public_pairing(data)
    return issue_pairing(
        session_token=token,
        device_id=dev,
        control_url=ctrl,
        expires_at=exp,
    )


def refresh_pairing(
    *,
    session_token: str = "",
    device_id: str = "",
    control_url: str = "",
    expires_at: float = 0,
) -> dict[str, Any]:
    return ensure_pairing(
        session_token=session_token,
        device_id=device_id,
        control_url=control_url,
        expires_at=expires_at,
        rotate=True,
    )


def _hub_payload_from_live(data: dict[str, Any]) -> dict[str, Any]:
    local = _load_live_session()
    if not local or not local.get("session_token"):
        raise ValueError("Eva 会话不可用，请重新登录")
    if not _session_valid(float(local.get("expires_at") or 0)):
        raise ValueError("Eva 会话已过期，请重新登录")
    return {
        "ok": True,
        "hub_token": str(local.get("session_token") or ""),
        "device_id": str(local.get("device_id") or data.get("device_id") or ""),
        "control_url": str(data.get("control_url") or ""),
        "expires_at": local.get("expires_at"),
    }


def consume_unused_pairing() -> dict[str, Any]:
    """Same-machine Hub adopt after Eva already logged in."""
    global _last_code, _last_code_exp
    now = time.time()
    with _lock:
        data = _load()
        if not data or not _alive(data):
            raise ValueError("Eva 尚未登录，或连接码已用完/过期。请先在 Eva 登录。")
        payload = _hub_payload_from_live(data)
        data["used"] = True
        data["paired_at"] = now
        _save(data)
        _last_code = ""
        _last_code_exp = 0.0
        payload["mode"] = "adopted"
        return payload


def consume_pairing(code: str) -> dict[str, Any]:
    """Single-use exchange. Returns session material for Hub."""
    global _last_code, _last_code_exp
    want = normalize_pairing_code(code)
    if len(want) < 8:
        raise ValueError("连接码无效")
    now = time.time()
    with _lock:
        data = _load()
        if not data:
            raise ValueError("没有待配对的连接码，请先在 Eva 登录")
        if data.get("used"):
            raise ValueError("连接码已使用，请在 Eva 设定里刷新")
        if float(data.get("pairing_expires_at") or 0) <= now:
            raise ValueError("连接码已过期，请在 Eva 设定里刷新")
        if not hmac.compare_digest(str(data.get("code_hash") or ""), _hash(want)):
            raise ValueError("连接码不正确")
        payload = _hub_payload_from_live(data)
        data["used"] = True
        data["paired_at"] = now
        _save(data)
        _last_code = ""
        _last_code_exp = 0.0
        return payload


def revoke_pairing() -> None:
    global _last_code, _last_code_exp
    with _lock:
        _last_code = ""
        _last_code_exp = 0.0
        p = _path()
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                _save({})
