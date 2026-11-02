"""Pydantic API / domain schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Role(str, Enum):
    system = "system"
    user = "user"
    assistant = "assistant"
    tool = "tool"


class ChatMessage(BaseModel):
    role: Role | str
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message")
    session_id: str | None = Field(
        default=None,
        description="Reuse an existing session; omit to create a new one",
    )
    session_title: str | None = Field(
        default=None,
        max_length=120,
        description="Title when creating a new session",
    )
    stream: bool = False
    use_tools: bool = True
    use_memory: bool = True
    model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCallRecord(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    model: str
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    ask_deputy: bool = False
    used_deputy: bool = False
    llm_name: str | None = None
    deputy_reason: str | None = None
    form: dict[str, Any] | None = None
    media_paths: list[str] = Field(default_factory=list)


class SessionInfo(BaseModel):
    session_id: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    title: str | None = None


class MemoryItem(BaseModel):
    id: str
    content: str
    kind: str = "note"  # note | fact | preference
    tags: list[str] = Field(default_factory=list)
    session_id: str | None = None
    created_at: datetime
    score: float | None = None
    status: str = "active"
    valid_from: str | None = None
    valid_to: str | None = None
    confidence: float = 1.0
    supersedes_id: str | None = None


class MemoryCreate(BaseModel):
    content: str = Field(..., min_length=1)
    kind: str = "note"
    tags: list[str] = Field(default_factory=list)
    session_id: str | None = None
    confidence: float | None = None
    valid_to: str | None = None
    ttl_days: float | None = None
    supersedes_id: str | None = None


class MemoryUpdate(BaseModel):
    """Editable fields for an existing memory item."""

    content: str = Field(..., min_length=1)
    kind: str = "note"
    tags: list[str] = Field(default_factory=list)
    session_id: str | None = None
    status: str | None = None
    confidence: float | None = None
    valid_to: str | None = None
    ttl_days: float | None = None


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class TaskCreate(BaseModel):
    name: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1, description="Agent prompt to run")
    session_id: str | None = Field(
        default=None,
        description="目标对话 session_id；结果写入该会话。空=首次执行时新建并固定",
    )
    # cron: "*/5 * * * *" or interval seconds
    cron: str | None = None
    interval_seconds: int | None = Field(default=None, ge=1)
    run_once: bool = False
    enabled: bool = True
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="可选 always_new_session=true 表示每次执行新建对话",
    )


class TaskUpdate(BaseModel):
    """Full replace of editable task fields (same shape as create)."""

    name: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1, description="Agent prompt to run")
    session_id: str | None = Field(
        default=None,
        description="目标对话 session_id；结果写入该会话。空=首次执行时新建并固定",
    )
    cron: str | None = None
    interval_seconds: int | None = Field(default=None, ge=1)
    run_once: bool = False
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskInfo(BaseModel):
    id: str
    name: str
    prompt: str
    session_id: str | None = None
    cron: str | None = None
    interval_seconds: int | None = None
    run_once: bool = False
    enabled: bool = True
    status: TaskStatus = TaskStatus.pending
    last_run_at: datetime | None = None
    last_result: str | None = None
    last_error: str | None = None
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    source: str = "builtin"  # builtin | skill | mcp
    display_name: str = ""  # UI-only Chinese label; call name stays in `name`


class HealthResponse(BaseModel):
    status: str
    agent: str
    version: str
    llm_provider: str
    llm_model: str
    llm_configured: bool = False
    tools: int
    mcp_servers: int
    scheduled_tasks: int
