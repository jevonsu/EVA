"""SQLite store for cards, sessions, admin sessions, audit log."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from app.auth.security import (
    hash_secret,
    hash_token,
    new_card_code,
    new_token,
    normalize_card_code,
    verify_secret,
)
from app.config import get_settings

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS cards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code_lookup TEXT NOT NULL UNIQUE,
  code_hash TEXT NOT NULL,
  code_hint TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'unused',
  batch_id TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  max_sessions INTEGER NOT NULL DEFAULT 3,
  expires_at REAL,
  created_at REAL NOT NULL,
  activated_at REAL,
  revoked_at REAL,
  last_login_at REAL,
  login_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token_hash TEXT NOT NULL UNIQUE,
  card_id INTEGER NOT NULL,
  ip TEXT NOT NULL DEFAULT '',
  user_agent TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  last_seen_at REAL NOT NULL,
  revoked INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(card_id) REFERENCES cards(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS admin_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token_hash TEXT NOT NULL UNIQUE,
  ip TEXT NOT NULL DEFAULT '',
  user_agent TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  last_seen_at REAL NOT NULL,
  revoked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  event TEXT NOT NULL,
  ip TEXT NOT NULL DEFAULT '',
  detail TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_admin_token ON admin_sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_cards_status ON cards(status);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
"""


@dataclass
class SessionInfo:
    session_id: int
    card_id: int
    card_hint: str
    expires_at: float


@dataclass
class AdminSessionInfo:
    session_id: int
    expires_at: float


class AuthStore:
    def __init__(self, db_path: Path, pepper: str) -> None:
        self.db_path = db_path
        self.pepper = pepper or "CHANGE-ME-IN-ENV"
        self._lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def audit(self, event: str, ip: str = "", detail: dict[str, Any] | str | None = None) -> None:
        if isinstance(detail, dict):
            # never log full card codes
            detail_s = json.dumps(detail, ensure_ascii=False)[:2000]
        else:
            detail_s = (detail or "")[:2000]
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO audit_log(ts, event, ip, detail) VALUES (?,?,?,?)",
                (time.time(), event, ip[:64], detail_s),
            )

    # ---- cards ---------------------------------------------------------------

    def issue_cards(
        self,
        *,
        count: int,
        note: str = "",
        valid_days: int | None = 30,
        max_sessions: int = 3,
        batch_id: str = "",
    ) -> list[str]:
        """Create cards; returns plaintext codes (show once)."""
        count = max(1, min(int(count), 200))
        max_sessions = max(1, min(int(max_sessions), 20))
        now = time.time()
        expires = None
        if valid_days is not None and int(valid_days) > 0:
            expires = now + int(valid_days) * 86400
        batch_id = batch_id or new_token(8)
        plain_codes: list[str] = []
        with self._lock, self._conn() as conn:
            for _ in range(count):
                code = new_card_code()
                # collision extremely unlikely; retry few times
                for _try in range(5):
                    try:
                        conn.execute(
                            """
                            INSERT INTO cards(
                              code_lookup, code_hash, code_hint, status, batch_id, note,
                              max_sessions, expires_at, created_at
                            ) VALUES (?,?,?,?,?,?,?,?,?)
                            """,
                            (
                                hash_token(code, self.pepper),
                                hash_secret(code),
                                code[:7] + "****" + code[-4:],
                                "unused",
                                batch_id,
                                (note or "")[:200],
                                max_sessions,
                                expires,
                                now,
                            ),
                        )
                        plain_codes.append(code)
                        break
                    except sqlite3.IntegrityError:
                        code = new_card_code()
        return plain_codes

    def list_cards(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        q = "SELECT id, code_hint, status, batch_id, note, max_sessions, expires_at, created_at, activated_at, revoked_at, last_login_at, login_count FROM cards"
        args: list[Any] = []
        if status:
            q += " WHERE status=?"
            args.append(status)
        q += " ORDER BY id DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])
        with self._lock, self._conn() as conn:
            rows = conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]

    def card_stats(self) -> dict[str, int]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS c FROM cards GROUP BY status"
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
            sessions = conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE revoked=0 AND expires_at>?",
                (time.time(),),
            ).fetchone()[0]
        out = {r["status"]: r["c"] for r in rows}
        out["total"] = total
        out["active_sessions"] = sessions
        return out

    def revoke_card(self, card_id: int) -> bool:
        now = time.time()
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "UPDATE cards SET status='revoked', revoked_at=? WHERE id=? AND status!='revoked'",
                (now, card_id),
            )
            conn.execute(
                "UPDATE sessions SET revoked=1 WHERE card_id=?",
                (card_id,),
            )
            return cur.rowcount > 0

    def _find_card_by_code(self, conn: sqlite3.Connection, code: str) -> sqlite3.Row | None:
        # O(1) lookup via HMAC(pepper, code); bcrypt hash kept for offline hardening.
        lookup = hash_token(code, self.pepper)
        row = conn.execute(
            "SELECT * FROM cards WHERE code_lookup=?",
            (lookup,),
        ).fetchone()
        if not row:
            return None
        # Defense in depth: bcrypt check (constant-ish cost on hit only)
        if row["code_hash"] and not verify_secret(code, row["code_hash"]):
            return None
        return row

    def login_with_card(
        self,
        code: str,
        *,
        ip: str,
        user_agent: str,
        session_ttl_sec: int = 7 * 86400,
    ) -> tuple[str | None, str]:
        """Returns (session_token, error_message)."""
        code = normalize_card_code(code)
        if not code.startswith("EVA-") or len(code) < 19:
            return None, "卡密格式无效"
        now = time.time()
        with self._lock, self._conn() as conn:
            row = self._find_card_by_code(conn, code)
            if not row:
                return None, "卡密无效或已失效"
            if row["status"] == "revoked":
                return None, "该卡已被吊销"
            if row["expires_at"] and float(row["expires_at"]) < now:
                conn.execute(
                    "UPDATE cards SET status='expired' WHERE id=?",
                    (row["id"],),
                )
                return None, "该卡已过期"
            # concurrent sessions
            active = conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE card_id=? AND revoked=0 AND expires_at>?",
                (row["id"], now),
            ).fetchone()[0]
            max_s = int(row["max_sessions"] or 3)
            if active >= max_s:
                return None, f"已达最大同时在线数（{max_s}），请先在其他设备退出"

            token = new_token(32)
            th = hash_token(token, self.pepper)
            exp = now + max(3600, int(session_ttl_sec))
            conn.execute(
                """
                INSERT INTO sessions(token_hash, card_id, ip, user_agent, created_at, expires_at, last_seen_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (th, row["id"], ip[:64], (user_agent or "")[:300], now, exp, now),
            )
            if row["status"] == "unused":
                conn.execute(
                    """
                    UPDATE cards SET status='active', activated_at=?, last_login_at=?, login_count=login_count+1
                    WHERE id=?
                    """,
                    (now, now, row["id"]),
                )
            else:
                conn.execute(
                    "UPDATE cards SET last_login_at=?, login_count=login_count+1 WHERE id=?",
                    (now, row["id"]),
                )
        return token, ""

    def resolve_session(self, token: str | None) -> SessionInfo | None:
        if not token:
            return None
        th = hash_token(token, self.pepper)
        now = time.time()
        with self._lock, self._conn() as conn:
            row = conn.execute(
                """
                SELECT s.id AS sid, s.expires_at, s.revoked, s.card_id,
                       c.status AS cstatus, c.code_hint, c.expires_at AS cexp
                FROM sessions s
                JOIN cards c ON c.id = s.card_id
                WHERE s.token_hash=?
                """,
                (th,),
            ).fetchone()
            if not row:
                return None
            if row["revoked"] or float(row["expires_at"]) < now:
                return None
            if row["cstatus"] == "revoked":
                return None
            if row["cexp"] and float(row["cexp"]) < now:
                return None
            # sliding activity
            conn.execute(
                "UPDATE sessions SET last_seen_at=? WHERE id=?",
                (now, row["sid"]),
            )
            return SessionInfo(
                session_id=int(row["sid"]),
                card_id=int(row["card_id"]),
                card_hint=str(row["code_hint"]),
                expires_at=float(row["expires_at"]),
            )

    def logout_session(self, token: str | None) -> None:
        if not token:
            return
        th = hash_token(token, self.pepper)
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE sessions SET revoked=1 WHERE token_hash=?",
                (th,),
            )

    # ---- admin ---------------------------------------------------------------

    def create_admin_session(
        self,
        *,
        ip: str,
        user_agent: str,
        ttl_sec: int = 8 * 3600,
    ) -> str:
        token = new_token(32)
        th = hash_token(token, self.pepper)
        now = time.time()
        exp = now + max(1800, int(ttl_sec))
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO admin_sessions(token_hash, ip, user_agent, created_at, expires_at, last_seen_at)
                VALUES (?,?,?,?,?,?)
                """,
                (th, ip[:64], (user_agent or "")[:300], now, exp, now),
            )
        return token

    def resolve_admin_session(self, token: str | None) -> AdminSessionInfo | None:
        if not token:
            return None
        th = hash_token(token, self.pepper)
        now = time.time()
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT id, expires_at, revoked FROM admin_sessions WHERE token_hash=?",
                (th,),
            ).fetchone()
            if not row or row["revoked"] or float(row["expires_at"]) < now:
                return None
            conn.execute(
                "UPDATE admin_sessions SET last_seen_at=? WHERE id=?",
                (now, row["id"]),
            )
            return AdminSessionInfo(session_id=int(row["id"]), expires_at=float(row["expires_at"]))

    def logout_admin(self, token: str | None) -> None:
        if not token:
            return
        th = hash_token(token, self.pepper)
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE admin_sessions SET revoked=1 WHERE token_hash=?",
                (th,),
            )

    def recent_audit(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT ts, event, ip, detail FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


_store: AuthStore | None = None
_store_lock = threading.Lock()


def get_auth_store() -> AuthStore:
    global _store
    with _store_lock:
        if _store is None:
            settings = get_settings()
            db = settings.data_dir / "auth" / "auth.db"
            pepper = getattr(settings, "auth_pepper", "") or getattr(
                settings, "auth_secret", ""
            )
            if not pepper:
                # derive stable-ish pepper from path if unset (still override in prod)
                pepper = "eva-default-pepper-" + str(settings.data_dir)
            _store = AuthStore(db, pepper=str(pepper))
        return _store
