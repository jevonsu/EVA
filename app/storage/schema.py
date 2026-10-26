"""SQLAlchemy Core tables for Eva business data."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

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
    Column("payload_json", Text, nullable=False),  # full session JSON
)

memories = Table(
    "eva_memories",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("content", Text, nullable=False),
    Column("kind", String(64), nullable=False, default="note"),
    Column("tags_json", Text, nullable=False, default="[]"),
    Column("session_id", String(64), nullable=True),
    Column("created_at", String(40), nullable=False),
)

kb_pages = Table(
    "eva_kb_pages",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("title", String(300), nullable=False),
    Column("slug", String(300), nullable=False, default=""),
    Column("collection", String(80), nullable=False, default="default"),
    Column("tags_json", Text, nullable=False, default="[]"),
    Column("content", Text, nullable=False, default=""),
    Column("version", Integer, nullable=False, default=1),
    Column("pinned", Boolean, nullable=False, default=False),
    Column("archived", Boolean, nullable=False, default=False),
    Column("versions_json", Text, nullable=False, default="[]"),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Column("preview", String(200), nullable=False, default=""),
)

kb_catalog = Table(
    "eva_kb_catalog",
    metadata,
    Column("id", Integer, primary_key=True),  # always 1
    Column("collections_json", Text, nullable=False, default="[]"),
    Column("hidden_json", Text, nullable=False, default="[]"),
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
    Column("payload_json", Text, nullable=False),
)

tasks = Table(
    "eva_tasks",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("name", String(200), nullable=False, default=""),
    Column("enabled", Boolean, nullable=False, default=True),
    Column("status", String(40), nullable=False, default="pending"),
    Column("created_at", String(40), nullable=False),
    Column("payload_json", Text, nullable=False),
)

kv_meta = Table(
    "eva_kv",
    metadata,
    Column("key", String(120), primary_key=True),
    Column("value", Text, nullable=False, default=""),
)
