"""Shared login form prefs for this Eva node.

Only the gateway URL and a stable device_id are persisted.
Card codes and control keys are never written to disk.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger("app.auth.login_prefs")

_lock = threading.RLock()

_EMPTY: dict[str, Any] = {
    "control_url": "",
    "card_code": "",
    "control_key": "",
    "device_id": "",
    "has_saved": False,
}


def _path() -> Path:
    settings = get_settings()
    # next to offline_grants.json
    p = settings.paths().offline_grants.parent / "login_prefs.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _new_device_id() -> str:
    return "eva-" + secrets.token_hex(16)


def mask_card_code(code: str) -> str:
    s = (code or "").strip()
    if len(s) < 8:
        return ""
    parts = [p for p in s.split("-") if p]
    if len(parts) >= 3:
        return parts[0] + "-****-" + parts[-1]
    return s[:3] + "****" + s[-2:]


def public_login_prefs(prefs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Safe view for unauthenticated login-page bootstrap (no raw secrets)."""
    data = prefs if isinstance(prefs, dict) else load_login_prefs()
    return {
        "has_saved": bool(data.get("has_saved")),
        "control_url": str(data.get("control_url") or "").strip(),
        "card_saved": False,
        "card_hint": "",
        "control_key_set": False,
        "device_id": str(data.get("device_id") or "").strip(),
    }


def load_login_prefs() -> dict[str, Any]:
    """Return prefs; ensure a stable device_id exists for this node."""
    with _lock:
        p = _path()
        data = dict(_EMPTY)
        if p.is_file():
            try:
                raw = json.loads(p.read_text(encoding="utf-8") or "{}")
                if isinstance(raw, dict):
                    data.update({k: raw.get(k, data.get(k)) for k in _EMPTY})
            except Exception:
                logger.warning("login_prefs: corrupt file, resetting")
        # Always keep one node-level device id (shared by web + window)
        did = str(data.get("device_id") or "").strip()
        dirty = bool(data.get("card_code") or data.get("control_key"))
        if len(did) < 8:
            did = _new_device_id()
            data["device_id"] = did
            dirty = True
        data["card_code"] = ""
        data["control_key"] = ""
        data["has_saved"] = bool(data.get("has_saved")) and bool(
            str(data.get("control_url") or "").strip()
        )
        if dirty:
            _write_unlocked(data)
        return {
            "control_url": str(data.get("control_url") or "").strip(),
            "card_code": "",
            "control_key": "",
            "device_id": did,
            "has_saved": bool(data.get("has_saved")),
        }


def _write_unlocked(data: dict[str, Any]) -> None:
    p = _path()
    out = {
        "control_url": str(data.get("control_url") or "").strip()[:300],
        "card_code": "",
        "control_key": "",
        "device_id": str(data.get("device_id") or "").strip()[:128],
        "has_saved": bool(data.get("has_saved")),
    }
    if len(out["device_id"]) < 8:
        out["device_id"] = _new_device_id()
    p.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def save_login_prefs(
    *,
    control_url: str | None = None,
    card_code: str | None = None,
    control_key: str | None = None,
    device_id: str | None = None,
    has_saved: bool = True,
) -> dict[str, Any]:
    """Merge and persist prefs."""
    with _lock:
        p = _path()
        data = dict(_EMPTY)
        if p.is_file():
            try:
                raw = json.loads(p.read_text(encoding="utf-8") or "{}")
                if isinstance(raw, dict):
                    for k in _EMPTY:
                        if k in raw:
                            data[k] = raw[k]
            except Exception:
                pass
        if control_url is not None:
            data["control_url"] = str(control_url or "").strip()[:300]
        data["card_code"] = ""
        data["control_key"] = ""
        did = str(device_id or data.get("device_id") or "").strip()
        if len(did) < 8:
            did = str(data.get("device_id") or "").strip()
        if len(did) < 8:
            did = _new_device_id()
        data["device_id"] = did[:128]
        # Password mode: has_saved tracks device preference, not control_url
        data["has_saved"] = bool(has_saved)
        _write_unlocked(data)
        return {
            "control_url": data["control_url"],
            "card_code": "",
            "control_key": "",
            "device_id": data["device_id"],
            "has_saved": data["has_saved"],
        }


def clear_login_secrets() -> dict[str, Any]:
    """Clear remembered card/gateway/key; keep stable device_id."""
    with _lock:
        p = _path()
        did = ""
        if p.is_file():
            try:
                raw = json.loads(p.read_text(encoding="utf-8") or "{}")
                did = str((raw or {}).get("device_id") or "").strip()
            except Exception:
                pass
        if len(did) < 8:
            did = _new_device_id()
        data = {
            "control_url": "",
            "card_code": "",
            "control_key": "",
            "device_id": did,
            "has_saved": False,
        }
        _write_unlocked(data)
        return dict(data)
