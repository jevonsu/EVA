"""Durable, session/form-bound one-shot process authorizations.

SQLite compare-and-set serializes claims across threads AND workers. An action
left executing by a crash is never retried automatically: its outcome is unknown.
Legacy JSON tokens intentionally are not imported (they were not form-bound).
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


def db_path() -> Path:
    from app.config import PROJECT_ROOT

    return Path(PROJECT_ROOT) / "data" / "process_actions.sqlite3"


@contextmanager
def connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS actions (
            token TEXT PRIMARY KEY, form_id TEXT UNIQUE NOT NULL,
            session_id TEXT NOT NULL, pid INTEGER NOT NULL, issued REAL NOT NULL,
            expires REAL NOT NULL, payload TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending', result TEXT
        )""")
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def _decode(row):
    if row is None:
        return None
    return {**json.loads(row["payload"]), "state": row["state"],
            "result": json.loads(row["result"]) if row["result"] else None}


def issue(token: str, payload: dict) -> None:
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        # A new process card supersedes previous pending process cards in this session.
        con.execute("UPDATE actions SET state='superseded' WHERE session_id=? AND state='pending'",
                    (payload["session_id"],))
        con.execute("INSERT INTO actions(token,form_id,session_id,pid,issued,expires,payload) VALUES(?,?,?,?,?,?,?)",
                    (token, payload["form_id"], payload["session_id"], payload["pid"],
                     payload["issued"], payload["expires"], json.dumps(payload)))


def get(token: str):
    with connect() as con:
        return _decode(con.execute("SELECT * FROM actions WHERE token=?", (token,)).fetchone())


def find(session_id: str, pid: int, form_id: str):
    with connect() as con:
        row = con.execute("SELECT * FROM actions WHERE session_id=? AND pid=? AND form_id=?",
                          (session_id, pid, form_id)).fetchone()
        return (row["token"], _decode(row)) if row else (None, None)


def claim(token: str) -> bool:
    with connect() as con:
        cur = con.execute("UPDATE actions SET state='executing' WHERE token=? AND state='pending' AND expires>=?",
                          (token, time.time()))
        return cur.rowcount == 1


def finish(token: str, result: dict) -> None:
    with connect() as con:
        con.execute("UPDATE actions SET state=?,result=? WHERE token=? AND state='executing'",
                    ("completed" if result.get("ok") else "failed", json.dumps(result, ensure_ascii=False), token))


def revoke(session_id: str, pid: int | None = None, form_id: str | None = None) -> int:
    sql = "UPDATE actions SET state='cancelled' WHERE session_id=? AND state='pending'"
    args: list = [session_id]
    if pid is not None:
        sql += " AND pid=?"
        args.append(pid)
    if form_id is not None:
        sql += " AND form_id=?"
        args.append(form_id)
    with connect() as con:
        return con.execute(sql, args).rowcount
