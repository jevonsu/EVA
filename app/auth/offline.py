"""Brief offline grace after a successful online card check.

Only cards with allow_offline=true get a local grant. It is not a
stand-in for CardServer: 吊销 must win as soon as the gateway is
reachable, and the grace itself is short.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from pathlib import Path
from typing import Any

from app.config import get_settings

_lock = threading.RLock()

# If CardServer is unreachable, honor a grant only this long after last online OK.
OFFLINE_GRACE_SEC = 120.0


def _path() -> Path:
    settings = get_settings()
    p = settings.paths().offline_grants
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _pepper() -> str:
    from app.auth.pepper import get_auth_pepper

    return get_auth_pepper()


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _sign(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(_pepper().encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()


def _load() -> dict[str, Any]:
    p = _path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data: dict[str, Any]) -> None:
    p = _path()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_offline_grant(
    *,
    session_token: str,
    device_id: str,
    expires_at: float,
    card_expires_at: float | None,
    card_id: int | None,
    card_hint: str,
    allow_offline: bool,
    control_url: str = "",
    plan_name: str = "",
    instance_id: str = "",
    instance_fp: str = "",
) -> None:
    """Persist offline grant after successful online login."""
    if not allow_offline or not session_token:
        return
    # 离线有效期：会话到期与卡到期取更短；卡永不过期则用会话到期
    exp = float(expires_at)
    if card_expires_at is not None:
        exp = min(exp, float(card_expires_at))
    body = {
        "device_id": (device_id or "")[:128],
        "instance_id": (instance_id or "")[:128],
        "instance_fp": (instance_fp or "")[:128],
        "expires_at": exp,
        "card_expires_at": card_expires_at,
        "card_id": card_id,
        "card_hint": (card_hint or "")[:80],
        "plan_name": (plan_name or "")[:80],
        "allow_offline": True,
        "control_url": (control_url or "")[:300],
        "saved_at": time.time(),
        "last_online_at": time.time(),
    }
    body["sig"] = _sign({k: body[k] for k in body if k != "sig"})
    key = _token_key(session_token)
    with _lock:
        data = _load()
        # prune expired
        now = time.time()
        data = {
            k: v
            for k, v in data.items()
            if isinstance(v, dict) and float(v.get("expires_at") or 0) > now
        }
        data[key] = body
        _save(data)


def check_offline_grant(
    session_token: str,
    *,
    device_id: str = "",
) -> dict[str, Any] | None:
    """Return auth info if a valid offline grant exists."""
    if not session_token:
        return None
    key = _token_key(session_token)
    now = time.time()
    with _lock:
        data = _load()
        row = data.get(key)
        if not isinstance(row, dict):
            return None
        sig = row.get("sig") or ""
        payload = {k: row[k] for k in row if k != "sig"}
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        if not payload.get("allow_offline"):
            return None
        if float(payload.get("expires_at") or 0) <= now:
            data.pop(key, None)
            _save(data)
            return None
        last_online = float(payload.get("last_online_at") or payload.get("saved_at") or 0)
        if last_online <= 0 or (now - last_online) > OFFLINE_GRACE_SEC:
            data.pop(key, None)
            _save(data)
            return None
        saved_dev = str(payload.get("device_id") or "")
        if saved_dev and device_id and saved_dev != device_id:
            return None
        try:
            from app.auth.instance import install_fingerprint, load_or_create_instance

            inst = load_or_create_instance()
            saved_inst = str(payload.get("instance_id") or "")
            if saved_inst and saved_inst != str(inst.get("instance_id") or ""):
                return None
            saved_fp = str(payload.get("instance_fp") or "")
            if saved_fp and saved_fp != install_fingerprint():
                return None
        except Exception:
            return None
        return {
            "ok": True,
            "authenticated": True,
            "offline": True,
            "card_id": payload.get("card_id"),
            "card_hint": payload.get("card_hint"),
            "expires_at": payload.get("expires_at"),
            "card_expires_at": payload.get("card_expires_at"),
            "plan_name": payload.get("plan_name") or "",
            "allow_offline": True,
            "device_id": saved_dev,
            "instance_id": str(payload.get("instance_id") or ""),
        }


def touch_offline_grant(session_token: str | None) -> None:
    """Record that CardServer just confirmed this session online."""
    if not session_token:
        return
    key = _token_key(session_token)
    now = time.time()
    with _lock:
        data = _load()
        row = data.get(key)
        if not isinstance(row, dict):
            return
        payload = {k: row[k] for k in row if k != "sig"}
        payload["last_online_at"] = now
        payload["sig"] = _sign(payload)
        data[key] = payload
        _save(data)


def revoke_offline_grant(session_token: str | None) -> None:
    if not session_token:
        return
    key = _token_key(session_token)
    with _lock:
        data = _load()
        if key in data:
            data.pop(key, None)
            _save(data)


def revoke_all_offline_grants() -> None:
    with _lock:
        _save({})
