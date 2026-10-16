from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    filename: Mapped[str] = mapped_column(String(240))
    media_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int]
    original_bytes: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    source_kind: Mapped[str] = mapped_column(String(30), default="USER_UPLOADED")
    source_url: Mapped[str] = mapped_column(String(2000), default="")
    source_note: Mapped[str] = mapped_column(Text, default="")
    verification_note: Mapped[str] = mapped_column(Text, default="")
    legal_status: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    version_confirmed: Mapped[bool] = mapped_column(default=False)
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    duplicate_of: Mapped[UUID | None] = mapped_column(ForeignKey("knowledge_documents.id"))
    legal_metadata: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(default=0)
    status_message: Mapped[str] = mapped_column(String(300), default="等待解析")
    processing_token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_stage: Mapped[str] = mapped_column(String(30), default="QUEUED")
    chunk_count: Mapped[int] = mapped_column(default=0)
    chunk_total: Mapped[int] = mapped_column(default=0)
    embedded_count: Mapped[int] = mapped_column(default=0)
    embedding_status: Mapped[str] = mapped_column(String(30), default="DISABLED")
    embedding_model_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_models.id"))
    embedding_fingerprint: Mapped[str | None] = mapped_column(String(64))
    embedding_dimensions: Mapped[int | None]
    embedding_message: Mapped[str] = mapped_column(String(300), default="")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ParseRevision(Base):
    __tablename__ = "knowledge_parse_revisions"
    __table_args__ = (UniqueConstraint("document_id", "revision"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    revision: Mapped[int]
    result: Mapped[dict[str, object]] = mapped_column(JSON)
    review_state: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    acknowledged_issues: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeAudit(Base):
    __tablename__ = "knowledge_audits"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_documents.id"), index=True
    )
    action: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(100), default="single-workspace")
    reason: Mapped[str] = mapped_column(Text)
    revision: Mapped[int | None]
    details: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        Index("ix_knowledge_chunks_lexical_terms", "lexical_terms", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    revision: Mapped[int]
    node_id: Mapped[str | None] = mapped_column(String(80))
    start: Mapped[int]
    end: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    lexical_terms: Mapped[dict[str, int]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    lexical_length: Mapped[int] = mapped_column(default=0, server_default="0")
    lexical_version: Mapped[int] = mapped_column(default=0, server_default="0")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), deferred=True)
    embedding_model_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_models.id"))
    embedding_fingerprint: Mapped[str | None] = mapped_column(String(64))
    embedding_dimensions: Mapped[int | None]


class KnowledgeSegment(Base):
    __tablename__ = "knowledge_segments"
    __table_args__ = (UniqueConstraint("document_id", "revision", "sequence"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    revision: Mapped[int]
    sequence: Mapped[int]
    node_id: Mapped[str | None] = mapped_column(String(80))
    start: Mapped[int]
    end: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), deferred=True)
