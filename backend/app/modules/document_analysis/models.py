from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AnalysisWorkspace(Base):
    __tablename__ = "analysis_workspaces"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisDocument(Base):
    __tablename__ = "analysis_documents"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_workspaces.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(200))
    mime_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(default=1)
    kind: Mapped[str] = mapped_column(String(20), default="auto")
    status: Mapped[str] = mapped_column(String(20), default="ready")
    character_count: Mapped[int]
    original: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    text: Mapped[str] = mapped_column(Text, deferred=True)
    spans: Mapped[list[dict[str, object]]] = mapped_column(JSON, deferred=True)
    deleted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (UniqueConstraint("workspace_id", "request_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_workspaces.id", ondelete="CASCADE"), index=True
    )
    request_id: Mapped[UUID]
    parent_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL")
    )
    instruction: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(30), default="queued")
    input: Mapped[dict[str, object]] = mapped_column(JSON)
    config_snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    checkpoint: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    intent: Mapped[dict[str, object] | None] = mapped_column(JSON)
    report: Mapped[dict[str, object] | None] = mapped_column(JSON)
    clarification: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    lease_token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    model_calls: Mapped[int] = mapped_column(default=0)
    tool_calls_count: Mapped[int] = mapped_column(default=0)
    elapsed_seconds: Mapped[int] = mapped_column(default=0)
    active_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisStep(Base):
    __tablename__ = "analysis_steps"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    agent: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="running")
    attempt: Mapped[int] = mapped_column(default=1)
    summary: Mapped[str] = mapped_column(String(300), default="")
    output: Mapped[dict[str, object] | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalysisToolCall(Base):
    __tablename__ = "analysis_tool_calls"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    agent: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    status: Mapped[str] = mapped_column(String(20))
    duration_ms: Mapped[int] = mapped_column(default=0)
    result: Mapped[dict[str, object] | None] = mapped_column(JSON, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisMCPServer(Base):
    __tablename__ = "analysis_mcp_servers"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(1000))
    token_encrypted: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=False)
    allowed_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    timeout: Mapped[int] = mapped_column(default=30)
    allow_document_content: Mapped[bool] = mapped_column(default=False)


class AnalysisSettings(Base):
    __tablename__ = "analysis_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    settings: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
