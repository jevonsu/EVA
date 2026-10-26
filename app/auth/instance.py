"""Stable Eva install identity.

instance_id is created once per data/ directory and does not include the
listen port. Copying the folder to a new path changes the install
fingerprint; CardServer treats that as a different (unauthorized) copy.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import socket
import threading
import time
from pathlib import Path
from typing import Any

from app.config import get_settings

_lock = threading.RLock()

_EMPTY = {
    "instance_id": "",
    "instance_secret": "",
    "created_at": 0.0,
}


def _path() -> Path:
    p = get_settings().paths().instance_json
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _new_instance_id() -> str:
    return "eva-inst-" + secrets.token_hex(16)


def _machine_guid() -> str:
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography"
            ) as key:
                val, _ = winreg.QueryValueEx(key, "MachineGuid")
                if val:
                    return str(val).strip()
        except OSError:
            pass
    return socket.gethostname() or "unknown-host"


def install_fingerprint() -> str:
    """Hash of this copy's resolved data dir (not the listen port)."""
    settings = get_settings()
    data_dir = getattr(settings, "data_dir", None)
    try:
        raw = str(Path(data_dir).resolve()) if data_dir is not None else ""
    except OSError:
        raw = str(data_dir or "")
    if os.name == "nt":
        raw = raw.lower()
    return hashlib.sha256(f"eva-install|{raw}".encode("utf-8")).hexdigest()


def machine_fingerprint() -> str:
    return hashlib.sha256(f"eva-machine|{_machine_guid()}".encode("utf-8")).hexdigest()


def _read_unlocked() -> dict[str, Any]:
    p = _path()
    data = dict(_EMPTY)
    if not p.is_file():
        return data
    try:
        raw = json.loads(p.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        return data
    if not isinstance(raw, dict):
        return data
    data["instance_id"] = str(raw.get("instance_id") or "").strip()[:128]
    data["instance_secret"] = str(raw.get("instance_secret") or "").strip()[:200]
    try:
        data["created_at"] = float(raw.get("created_at") or 0)
    except (TypeError, ValueError):
        data["created_at"] = 0.0
    return data


def _write_unlocked(data: dict[str, Any]) -> None:
    p = _path()
    out = {
        "instance_id": str(data.get("instance_id") or "").strip()[:128],
        "instance_secret": str(data.get("instance_secret") or "").strip()[:200],
        "created_at": float(data.get("created_at") or 0),
    }
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def load_or_create_instance() -> dict[str, Any]:
    """Return this install's identity, creating instance_id on first run."""
    with _lock:
        data = _read_unlocked()
        iid = str(data.get("instance_id") or "").strip()
        if len(iid) < 8:
            data = {
                "instance_id": _new_instance_id(),
                "instance_secret": "",
                "created_at": time.time(),
            }
            _write_unlocked(data)
        return {
            "instance_id": str(data["instance_id"]),
            "instance_secret": str(data.get("instance_secret") or ""),
            "created_at": float(data.get("created_at") or 0),
        }


def save_instance_secret(secret: str) -> None:
    """Persist the CardServer-issued install secret (shown once at bind)."""
    s = (secret or "").strip()
    if not s:
        return
    with _lock:
        data = _read_unlocked()
        if len(str(data.get("instance_id") or "").strip()) < 8:
            data["instance_id"] = _new_instance_id()
            data["created_at"] = time.time()
        data["instance_secret"] = s[:200]
        _write_unlocked(data)


def instance_claims() -> dict[str, str]:
    """Fields Eva must send to CardServer on login / session check."""
    row = load_or_create_instance()
    return {
        "instance_id": row["instance_id"],
        "instance_secret": str(row.get("instance_secret") or ""),
        "instance_fp": install_fingerprint(),
        "machine_fp": machine_fingerprint(),
    }
