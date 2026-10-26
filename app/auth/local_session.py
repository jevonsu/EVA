"""Per-install encrypted session file (not cookies).

Bound to this copy's data/ directory only — restarting the same project
on another port keeps the login. A copied folder has a different data
dir (and CardServer fingerprint) and must card-login again.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from app.config import get_settings

_lock = threading.RLock()


def _paths():
    p = get_settings().paths()
    p.auth_dir.mkdir(parents=True, exist_ok=True)
    return p.local_session, p.local_session_key


def _norm_data_dir(raw: Any) -> str:
    try:
        data_s = str(Path(raw).resolve()) if raw is not None else ""
    except Exception:
        data_s = str(raw or "")
    if os.name == "nt":
        data_s = data_s.lower()
    return data_s


def _instance_stamp() -> dict[str, Any]:
    """Bind a session to this copy's data dir (not the listen port)."""
    settings = get_settings()
    return {"data_dir": _norm_data_dir(getattr(settings, "data_dir", None))}


def _load_or_create_key() -> bytes:
    _, key_path = _paths()
    if key_path.is_file():
        raw = key_path.read_bytes()
        if len(raw) >= 32:
            return raw[:32]
    raw = secrets.token_bytes(32)
    key_path.write_bytes(raw)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    return raw


def _encrypt(plain: bytes) -> bytes:
    key = _load_or_create_key()
    try:
        from cryptography.fernet import Fernet

        f = Fernet(base64.urlsafe_b64encode(hashlib.sha256(key).digest()))
        return f.encrypt(plain)
    except Exception:
        nonce = secrets.token_bytes(16)
        stream_key = hashlib.sha256(key + nonce).digest()
        stream = (stream_key * ((len(plain) // len(stream_key)) + 1))[: len(plain)]
        cipher = bytes(a ^ b for a, b in zip(plain, stream))
        tag = hmac.new(stream_key, cipher, hashlib.sha256).digest()[:16]
        return nonce + tag + cipher


def _decrypt(blob: bytes) -> bytes:
    key = _load_or_create_key()
    try:
        from cryptography.fernet import Fernet

        f = Fernet(base64.urlsafe_b64encode(hashlib.sha256(key).digest()))
        return f.decrypt(blob)
    except Exception:
        if len(blob) < 33:
            raise ValueError("corrupt session")
        nonce, tag, cipher = blob[:16], blob[16:32], blob[32:]
        stream_key = hashlib.sha256(key + nonce).digest()
        expect = hmac.new(stream_key, cipher, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(tag, expect):
            raise ValueError("session tampered")
        stream = (stream_key * ((len(cipher) // len(stream_key)) + 1))[: len(cipher)]
        return bytes(a ^ b for a, b in zip(cipher, stream))


def save_local_session(
    *,
    session_token: str,
    device_id: str,
    control_key: str,
    expires_at: float,
) -> None:
    token = (session_token or "").strip()
    if not token:
        return
    stamp = _instance_stamp()
    try:
        from app.auth.instance import load_or_create_instance

        inst_id = str(load_or_create_instance().get("instance_id") or "")
    except Exception:
        inst_id = ""
    body = {
        "session_token": token,
        "device_id": (device_id or "")[:128],
        "control_key": (control_key or "")[:200],
        "expires_at": float(expires_at or 0),
        "saved_at": time.time(),
        "data_dir": stamp["data_dir"],
        "instance_id": inst_id,
    }
    blob = _encrypt(json.dumps(body, ensure_ascii=False).encode("utf-8"))
    path, _ = _paths()
    with _lock:
        path.write_bytes(blob)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def load_local_session() -> dict[str, Any] | None:
    path, key_path = _paths()
    if not path.is_file() or not key_path.is_file():
        return None
    with _lock:
        try:
            raw = _decrypt(path.read_bytes())
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return None
    if not isinstance(data, dict):
        return None
    token = str(data.get("session_token") or "").strip()
    if not token:
        return None
    exp = float(data.get("expires_at") or 0)
    if exp and exp <= time.time():
        clear_local_session()
        return None
    stamp = _instance_stamp()
    saved_dir = _norm_data_dir(data.get("data_dir") or "")
    if not saved_dir or saved_dir != stamp["data_dir"]:
        clear_local_session()
        return None
    saved_inst = str(data.get("instance_id") or "")
    if saved_inst:
        try:
            from app.auth.instance import load_or_create_instance

            now_inst = str(load_or_create_instance().get("instance_id") or "")
        except Exception:
            now_inst = ""
        if now_inst and saved_inst != now_inst:
            clear_local_session()
            return None
    return {
        "session_token": token,
        "device_id": str(data.get("device_id") or "").strip(),
        "control_key": str(data.get("control_key") or "").strip(),
        "expires_at": exp,
    }


def clear_local_session() -> None:
    path, _ = _paths()
    with _lock:
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass
