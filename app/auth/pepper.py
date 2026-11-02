"""Persistent random auth pepper (no hardcoded defaults)."""

from __future__ import annotations

import logging
import os
import secrets
import threading
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger("app.auth.pepper")
_lock = threading.RLock()
_cached: str | None = None


def _pepper_path() -> Path:
    p = get_settings().paths()
    p.auth_dir.mkdir(parents=True, exist_ok=True)
    return p.auth_dir / "pepper.txt"


def get_auth_pepper() -> str:
    """Return install pepper; create a random one on first use."""
    global _cached
    with _lock:
        if _cached:
            return _cached
        settings = get_settings()
        env = (getattr(settings, "auth_pepper", None) or "").strip()
        if env:
            _cached = env
            return _cached
        path = _pepper_path()
        if path.is_file():
            raw = path.read_text(encoding="utf-8").strip()
            if len(raw) >= 16:
                _cached = raw
                return _cached
        raw = secrets.token_urlsafe(32)
        path.write_text(raw + "\n", encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        logger.info("Generated new auth pepper at %s", path)
        _cached = raw
        return _cached
