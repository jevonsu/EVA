"""Memory / knowledge lifecycle (Phase 1–2): status, TTL, confidence, cleanup.

Control plane = memories; data plane = kb pages.
Phase 2 adds status=staging with default TTL.
Phase 3 extends hourly job with knowledge-ref edge cleanup.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

logger = logging.getLogger("app.storage.lifecycle")

STATUS_ACTIVE = "active"
STATUS_STAGING = "staging"
STATUS_EXPIRED = "expired"
STATUS_ARCHIVED = "archived"
STATUS_SUPERSEDED = "superseded"
STATUS_CONFLICTED = "conflicted"
STATUS_REVIEW_REQUIRED = "review_required"

VALID_STATUSES = frozenset(
    {
        STATUS_ACTIVE,
        STATUS_STAGING,
        STATUS_EXPIRED,
        STATUS_ARCHIVED,
        STATUS_SUPERSEDED,
        STATUS_CONFLICTED,
        STATUS_REVIEW_REQUIRED,
    }
)

# Default recall / search surface
VISIBLE_STATUSES = frozenset({STATUS_ACTIVE})

# Soft-archive staging-like memory kinds older than this (fallback if no valid_to)
STAGING_KINDS = frozenset(
    {
        "staging",
        "temp",
        "draft",
        "evidence",
        "scratch",
        "inferred",
        "observation",
        "candidate",
        "hypothesis",
    }
)
# Phase 2: staging TTL band is 3–14d; archive leftovers after 14d
STAGING_MAX_AGE_DAYS = 14

# Soft-archive kb pages in these collections after this many days
STAGING_COLLECTIONS = frozenset({"daily", "staging", "temp", "draft", "candidate"})
STAGING_COLLECTION_MAX_AGE_DAYS = 14
STAGING_KB_DEFAULT_TTL_DAYS = 7

DEFAULT_CONFIDENCE = 1.0
NEW_WRITE_CONFIDENCE = 0.8


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def normalize_status(value: Any, *, archived_flag: bool = False) -> str:
    s = str(value or "").strip().lower()
    if s in VALID_STATUSES:
        return s
    if archived_flag:
        return STATUS_ARCHIVED
    return STATUS_ACTIVE


def parse_iso(value: Any) -> datetime | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def compute_valid_to(
    *,
    valid_to: str | None = None,
    ttl_days: float | int | None = None,
    ttl_hours: float | int | None = None,
) -> str | None:
    """Optional green-leaf expiry. Prefer explicit ISO valid_to; else TTL from now."""
    if valid_to is not None and str(valid_to).strip():
        dt = parse_iso(valid_to)
        if dt is not None:
            return dt.isoformat()
        # keep raw if caller passed something odd — cleanup will ignore unparsable
        return str(valid_to).strip()
    delta = timedelta()
    if ttl_days is not None:
        try:
            delta += timedelta(days=float(ttl_days))
        except (TypeError, ValueError):
            pass
    if ttl_hours is not None:
        try:
            delta += timedelta(hours=float(ttl_hours))
        except (TypeError, ValueError):
            pass
    if delta.total_seconds() <= 0:
        return None
    return (_now() + delta).isoformat()


def clamp_confidence(value: Any, default: float = NEW_WRITE_CONFIDENCE) -> float:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return float(default)
    if c < 0.0:
        return 0.0
    if c > 1.0:
        return 1.0
    return c


def is_expired_by_valid_to(row: dict[str, Any], *, now: datetime | None = None) -> bool:
    vt = parse_iso(row.get("valid_to"))
    if vt is None:
        return False
    now = now or _now()
    return vt <= now


def is_visible_row(
    row: dict[str, Any],
    *,
    include_archived: bool = False,
    now: datetime | None = None,
) -> bool:
    """Whether a memory/kb row should appear in default recall/search/list."""
    now = now or _now()
    status = normalize_status(
        row.get("status"),
        archived_flag=bool(row.get("archived")),
    )
    if include_archived:
        # still hide conflicted unless explicitly wanted later; Phase 1: include all
        # when include_archived, but exclude nothing for simplicity
        return True
    if status not in VISIBLE_STATUSES:
        return False
    if is_expired_by_valid_to(row, now=now):
        return False
    # legacy kb archived bool
    if bool(row.get("archived")) and status == STATUS_ACTIVE:
        return False
    return True


def _table_columns(conn, table: str) -> set[str]:
    dialect = conn.engine.dialect.name
    if dialect == "sqlite":
        rows = conn.execute(text(f"PRAGMA table_info({table})")).mappings().all()
        return {str(r["name"]) for r in rows}
    if dialect in ("postgresql", "postgres"):
        rows = conn.execute(
            text(
                "SELECT column_name AS name FROM information_schema.columns "
                "WHERE table_name = :t"
            ),
            {"t": table},
        ).mappings().all()
        return {str(r["name"]) for r in rows}
    if dialect in ("mysql", "mariadb"):
        rows = conn.execute(text(f"SHOW COLUMNS FROM `{table}`")).mappings().all()
        # Field / field
        out: set[str] = set()
        for r in rows:
            out.add(str(r.get("Field") or r.get("field") or r.get("name") or ""))
        return {c for c in out if c}
    # generic fallback
    try:
        rows = conn.execute(text(f"SELECT * FROM {table} WHERE 1=0")).keys()
        return set(rows)
    except Exception:
        return set()


def _add_column(conn, table: str, column: str, ddl_type: str) -> None:
    dialect = conn.engine.dialect.name
    if dialect in ("mysql", "mariadb"):
        conn.execute(text(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {ddl_type}"))
    else:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))


# (column, sqlite/generic DDL, notes)
_MEMORY_COLS: list[tuple[str, str]] = [
    ("status", "VARCHAR(40) DEFAULT 'active'"),
    ("valid_from", "VARCHAR(40)"),
    ("valid_to", "VARCHAR(40)"),
    ("confidence", "FLOAT DEFAULT 1.0"),
    ("supersedes_id", "VARCHAR(64)"),
]

_KB_COLS: list[tuple[str, str]] = [
    ("status", "VARCHAR(40) DEFAULT 'active'"),
    ("valid_from", "VARCHAR(40)"),
    ("valid_to", "VARCHAR(40)"),
    ("confidence", "FLOAT DEFAULT 1.0"),
    ("supersedes_id", "VARCHAR(64)"),
]


def migrate_lifecycle_schema(conn) -> dict[str, Any]:
    """Safe ALTER for existing DBs. Idempotent. Call after create_all."""
    added: dict[str, list[str]] = {"eva_memories": [], "eva_kb_pages": []}
    errors: list[str] = []

    try:
        mem_cols = _table_columns(conn, "eva_memories")
    except Exception as exc:
        logger.exception("lifecycle migrate: cannot inspect eva_memories")
        return {"added": added, "ok": False, "error": str(exc)}
    for name, ddl in _MEMORY_COLS:
        if name not in mem_cols:
            try:
                _add_column(conn, "eva_memories", name, ddl)
                added["eva_memories"].append(name)
            except Exception as exc:
                errors.append(f"eva_memories.{name}: {exc}")
                logger.warning("lifecycle migrate skip %s.%s: %s", "eva_memories", name, exc)

    try:
        kb_cols = _table_columns(conn, "eva_kb_pages")
    except Exception as exc:
        logger.exception("lifecycle migrate: cannot inspect eva_kb_pages")
        return {"added": added, "ok": False, "error": str(exc), "errors": errors}
    for name, ddl in _KB_COLS:
        if name not in kb_cols:
            try:
                _add_column(conn, "eva_kb_pages", name, ddl)
                added["eva_kb_pages"].append(name)
            except Exception as exc:
                errors.append(f"eva_kb_pages.{name}: {exc}")
                logger.warning("lifecycle migrate skip %s.%s: %s", "eva_kb_pages", name, exc)

    # Backfill existing rows → active / confidence
    conn.execute(
        text(
            "UPDATE eva_memories SET status = 'active' "
            "WHERE status IS NULL OR TRIM(status) = ''"
        )
    )
    conn.execute(
        text(
            "UPDATE eva_memories SET confidence = 1.0 WHERE confidence IS NULL"
        )
    )
    conn.execute(
        text(
            "UPDATE eva_kb_pages SET status = 'active' "
            "WHERE status IS NULL OR TRIM(status) = ''"
        )
    )
    conn.execute(
        text(
            "UPDATE eva_kb_pages SET confidence = 1.0 WHERE confidence IS NULL"
        )
    )
    # Sync legacy archived bool → status
    conn.execute(
        text(
            "UPDATE eva_kb_pages SET status = 'archived' "
            "WHERE archived = 1 AND (status = 'active' OR status IS NULL OR status = '')"
        )
    )

    summary = {
        "added": added,
        "ok": not errors,
        "errors": errors,
    }
    if any(added.values()):
        logger.info("Lifecycle schema migrated: %s", added)
    return summary


def run_lifecycle_cleanup_sync() -> dict[str, int]:
    """Mark past valid_to → expired; soft-archive old staging-like rows."""
    from app.storage.engine import db_connect

    now = _now()
    now_iso = now.isoformat()
    staging_mem_cut = (now - timedelta(days=STAGING_MAX_AGE_DAYS)).isoformat()
    staging_kb_cut = (now - timedelta(days=STAGING_COLLECTION_MAX_AGE_DAYS)).isoformat()

    counts = {
        "memories_expired": 0,
        "kb_expired": 0,
        "memories_archived_staging": 0,
        "kb_archived_staging": 0,
    }

    with db_connect() as conn:
        # Expire by valid_to (active only)
        r1 = conn.execute(
            text(
                "UPDATE eva_memories SET status = 'expired' "
                "WHERE status IN ('active', 'staging') AND valid_to IS NOT NULL AND TRIM(valid_to) != '' "
                "AND valid_to <= :now"
            ),
            {"now": now_iso},
        )
        counts["memories_expired"] = int(r1.rowcount or 0)

        r2 = conn.execute(
            text(
                "UPDATE eva_kb_pages SET status = 'expired' "
                "WHERE status IN ('active', 'staging') AND valid_to IS NOT NULL AND TRIM(valid_to) != '' "
                "AND valid_to <= :now"
            ),
            {"now": now_iso},
        )
        counts["kb_expired"] = int(r2.rowcount or 0)

        # Soft-archive staging-like memories by kind + age
        kinds = sorted(STAGING_KINDS)
        if kinds:
            placeholders = ", ".join(f":k{i}" for i in range(len(kinds)))
            params: dict[str, Any] = {"cut": staging_mem_cut}
            for i, k in enumerate(kinds):
                params[f"k{i}"] = k
            r3 = conn.execute(
                text(
                    f"UPDATE eva_memories SET status = 'archived' "
                    f"WHERE status IN ('active', 'staging') AND lower(kind) IN ({placeholders}) "
                    f"AND created_at <= :cut"
                ),
                params,
            )
            counts["memories_archived_staging"] = int(r3.rowcount or 0)

            # Also archive leftover status=staging (any kind) past max age
            r3b = conn.execute(
                text(
                    "UPDATE eva_memories SET status = 'archived' "
                    "WHERE status = 'staging' AND created_at <= :cut"
                ),
                {"cut": staging_mem_cut},
            )
            counts["memories_archived_staging"] += int(r3b.rowcount or 0)

        colls = sorted(STAGING_COLLECTIONS)
        if colls:
            placeholders = ", ".join(f":c{i}" for i in range(len(colls)))
            params = {"cut": staging_kb_cut}
            for i, c in enumerate(colls):
                params[f"c{i}"] = c
            r4 = conn.execute(
                text(
                    f"UPDATE eva_kb_pages SET status = 'archived', archived = 1 "
                    f"WHERE status IN ('active', 'staging') AND lower(collection) IN ({placeholders}) "
                    f"AND created_at <= :cut"
                ),
                params,
            )
            counts["kb_archived_staging"] = int(r4.rowcount or 0)

            r4b = conn.execute(
                text(
                    "UPDATE eva_kb_pages SET status = 'archived', archived = 1 "
                    "WHERE status = 'staging' AND created_at <= :cut"
                ),
                {"cut": staging_kb_cut},
            )
            counts["kb_archived_staging"] += int(r4b.rowcount or 0)

    # Phase 3: reference edges + anchors
    try:
        from app.knowledge.refs import run_refs_cleanup_sync

        ref_counts = run_refs_cleanup_sync()
        for k, v in (ref_counts or {}).items():
            counts[k] = int(v or 0)
    except Exception:
        logger.exception("Refs cleanup failed (lifecycle continues)")

    total = sum(counts.values())
    if total:
        logger.info("Lifecycle cleanup: %s", counts)
    else:
        logger.debug("Lifecycle cleanup: nothing to do")
    return counts


async def run_lifecycle_cleanup() -> dict[str, int]:
    from app.storage.util import run_db

    return await run_db(run_lifecycle_cleanup_sync)
