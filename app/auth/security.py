"""Cryptography, tokens, rate limiting — high-protection helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque

import bcrypt


# ---- Password / card hashing -------------------------------------------------

def hash_secret(plain: str) -> str:
    """bcrypt hash for admin passwords and card codes (slow by design)."""
    raw = plain.encode("utf-8")
    if len(raw) > 72:
        # bcrypt limit; pre-hash long card codes
        raw = hashlib.sha256(raw).digest()
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_secret(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        raw = plain.encode("utf-8")
        if len(raw) > 72:
            raw = hashlib.sha256(raw).digest()
        return bcrypt.checkpw(raw, hashed.encode("ascii"))
    except Exception:
        return False


def hash_token(token: str, pepper: str) -> str:
    """Fast keyed hash for session tokens (lookup by hash only)."""
    return hmac.new(
        pepper.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def new_card_code() -> str:
    """High-entropy card: EVA-XXXX-XXXX-XXXX-XXXX ( Crockford-ish uppercase )."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
    parts = []
    for _ in range(4):
        parts.append("".join(secrets.choice(alphabet) for _ in range(4)))
    return "EVA-" + "-".join(parts)


def normalize_card_code(code: str) -> str:
    s = (code or "").strip().upper().replace(" ", "")
    # allow pasting without dashes
    if s.startswith("EVA") and "-" not in s and len(s) >= 19:
        body = s[3:]
        if body.startswith("-"):
            body = body[1:]
        chunks = [body[i : i + 4] for i in range(0, min(len(body), 16), 4)]
        s = "EVA-" + "-".join(chunks)
    return s


# ---- Rate limiting (in-process sliding window) ------------------------------

@dataclass
class RateLimitResult:
    allowed: bool
    retry_after_sec: float = 0.0
    reason: str = ""


class SlidingWindowLimiter:
    """Per-key sliding window + optional progressive cooldown after failures."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, Deque[float]] = defaultdict(deque)
        self._fail_until: dict[str, float] = {}
        self._fail_count: dict[str, int] = defaultdict(int)

    def check(self, key: str, *, limit: int, window_sec: float) -> RateLimitResult:
        now = time.monotonic()
        with self._lock:
            until = self._fail_until.get(key, 0.0)
            if until > now:
                return RateLimitResult(
                    False, until - now, "temporarily locked after failed attempts"
                )
            q = self._hits[key]
            cutoff = now - window_sec
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= limit:
                retry = window_sec - (now - q[0]) if q else window_sec
                return RateLimitResult(False, max(retry, 0.1), "rate limit exceeded")
            q.append(now)
            return RateLimitResult(True)

    def register_failure(self, key: str, *, base_lock_sec: float = 2.0) -> float:
        """Exponential lockout: 2s, 4s, 8s … cap 15 min."""
        with self._lock:
            n = self._fail_count[key] + 1
            self._fail_count[key] = n
            lock = min(base_lock_sec * (2 ** min(n - 1, 8)), 900.0)
            self._fail_until[key] = time.monotonic() + lock
            return lock

    def clear_failures(self, key: str) -> None:
        with self._lock:
            self._fail_count.pop(key, None)
            self._fail_until.pop(key, None)


_login_limiter = SlidingWindowLimiter()
_admin_limiter = SlidingWindowLimiter()
_api_limiter = SlidingWindowLimiter()


def login_limiter() -> SlidingWindowLimiter:
    return _login_limiter


def admin_limiter() -> SlidingWindowLimiter:
    return _admin_limiter


def api_limiter() -> SlidingWindowLimiter:
    return _api_limiter


def client_ip(headers: list[tuple[bytes, bytes]] | dict, scope_client: str | None) -> str:
    """Use X-Forwarded-For only when AUTH_TRUST_PROXY is on."""
    trust = False
    try:
        from app.config import get_settings

        trust = bool(getattr(get_settings(), "auth_trust_proxy", False))
    except Exception:
        trust = False
    xf = ""
    if trust:
        if isinstance(headers, dict):
            xf = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For") or ""
        else:
            for k, v in headers:
                if k.lower() == b"x-forwarded-for":
                    xf = v.decode("latin-1", "replace")
                    break
    if xf:
        return xf.split(",")[0].strip()[:64]
    return (scope_client or "0.0.0.0")[:64]
