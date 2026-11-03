"""SQLAlchemy Core tables for Eva business data."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.mysql import LONGTEXT

# MySQL TEXT is only 64KB; long sessions/JSON need LONGTEXT (sqlite/pg unchanged)
LongText = Text().with_variant(LONGTEXT(), "mysql", "mariadb")

metadata = MetaData()

# Chat sessions — full document as JSON for schema flexibility
sessions = Table(
    "eva_sessions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("title", String(200), nullable=True),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Column("message_count", Integer, nullable=False, default=0),
    Column("payload_json", LongText, nullable=False),  # full session JSON
)

memories = Table(
    "eva_memories",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("content", LongText, nullable=False),
    Column("kind", String(64), nullable=False, default="note"),
    Column("tags_json", LongText, nullable=False, default="[]"),
    Column("session_id", String(64), nullable=True),
    Column("created_at", String(40), nullable=False),
    # Phase 1 lifecycle (control plane)
    Column("status", String(40), nullable=False, default="active"),
    Column("valid_from", String(40), nullable=True),
    Column("valid_to", String(40), nullable=True),
    Column("confidence", Float, nullable=False, default=1.0),
    Column("supersedes_id", String(64), nullable=True),
)

kb_pages = Table(
    "eva_kb_pages",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("title", String(300), nullable=False),
    Column("slug", String(300), nullable=False, default=""),
    Column("collection", String(80), nullable=False, default="default"),
    Column("tags_json", LongText, nullable=False, default="[]"),
    Column("content", LongText, nullable=False, default=""),
    Column("version", Integer, nullable=False, default=1),
    Column("pinned", Boolean, nullable=False, default=False),
    Column("archived", Boolean, nullable=False, default=False),
    Column("versions_json", LongText, nullable=False, default="[]"),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Column("preview", String(200), nullable=False, default=""),
    # Phase 1 lifecycle (data plane)
    Column("status", String(40), nullable=False, default="active"),
    Column("valid_from", String(40), nullable=True),
    Column("valid_to", String(40), nullable=True),
    Column("confidence", Float, nullable=False, default=1.0),
    Column("supersedes_id", String(64), nullable=True),
)

kb_catalog = Table(
    "eva_kb_catalog",
    metadata,
    Column("id", Integer, primary_key=True),  # always 1
    Column("collections_json", LongText, nullable=False, default="[]"),
    Column("hidden_json", LongText, nullable=False, default="[]"),
)

workflow_runs = Table(
    "eva_workflow_runs",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("workflow_id", String(120), nullable=False, default=""),
    Column("status", String(40), nullable=False, default="pending"),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Column("finished_at", String(40), nullable=True),
    Column("payload_json", LongText, nullable=False),
)

tasks = Table(
    "eva_tasks",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("name", String(200), nullable=False, default=""),
    Column("enabled", Boolean, nullable=False, default=True),
    Column("status", String(40), nullable=False, default="pending"),
    Column("created_at", String(40), nullable=False),
    Column("payload_json", LongText, nullable=False),
)


# Phase 3: knowledge reference edges (memory/skill/kb graph links)
knowledge_refs = Table(
    "eva_knowledge_refs",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("from_type", String(40), nullable=False),  # memory|kb|skill|reference
    Column("from_id", String(120), nullable=False),
    Column("to_type", String(40), nullable=False),
    Column("to_id", String(120), nullable=False),
    Column("edge_type", String(40), nullable=False),  # references|controls|supersedes|contradicts
    Column("status", String(40), nullable=False, default="active"),  # active|dormant|expired
    Column("valid_from", String(40), nullable=True),
    Column("valid_to", String(40), nullable=True),
    Column("use_count", Integer, nullable=False, default=0),
    Column("last_used_at", String(40), nullable=True),
    Column("weight", Float, nullable=False, default=1.0),
    Column("reason", LongText, nullable=True),
    Column("created_by", String(80), nullable=True),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Column("meta_json", LongText, nullable=False, default="{}"),
)

# Phase 3: arbitration anchors (参照库)
reference_anchors = Table(
    "eva_reference_anchors",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("reference_type", String(40), nullable=False),  # user_explicit|authority|precedent|evidence|hierarchy
    Column("scope", String(200), nullable=True),
    Column("condition", LongText, nullable=True),
    Column("resolution", LongText, nullable=False, default=""),
    Column("confidence", Float, nullable=False, default=0.8),
    Column("status", String(40), nullable=False, default="active"),
    Column("valid_from", String(40), nullable=True),
    Column("valid_to", String(40), nullable=True),
    Column("source", String(200), nullable=True),
    Column("created_from", String(120), nullable=True),
    Column("subject_type", String(40), nullable=True),
    Column("subject_id", String(120), nullable=True),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
)

# Phase 3: conflict / review log (no full UI)
conflict_logs = Table(
    "eva_conflict_logs",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("created_at", String(40), nullable=False),
    Column("level", String(20), nullable=False, default="L2"),
    Column("status", String(40), nullable=False, default="logged"),
    Column("summary", LongText, nullable=False, default=""),
    Column("payload_json", LongText, nullable=False, default="{}"),
)

kv_meta = Table(
    "eva_kv",
    metadata,
    Column("key", String(120), primary_key=True),
    Column("value", LongText, nullable=False, default=""),
)
