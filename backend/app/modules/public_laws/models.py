from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PublicLawVectorTask(Base):
    __tablename__ = "public_law_vector_tasks"
    __table_args__ = (
        CheckConstraint("slot = 1", name="singleton_slot"),
        CheckConstraint("concurrency BETWEEN 1 AND 10", name="concurrency_range"),
        CheckConstraint("request_mode IN ('serial', 'concurrent')", name="request_mode_values"),
        CheckConstraint("download_delay_ms BETWEEN 0 AND 60000", name="download_delay_range"),
        CheckConstraint("request_mode != 'serial' OR concurrency = 1", name="serial_concurrency"),
        Index(
            "uq_public_law_vector_tasks_active",
            "slot",
            unique=True,
            postgresql_where=text("status IN ('RUNNING', 'STOPPING')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slot: Mapped[int] = mapped_column(default=1, server_default="1")
    concurrency: Mapped[int] = mapped_column(default=1, server_default="1")
    download_delay_ms: Mapped[int] = mapped_column(default=0, server_default="0")
    next_download_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_mode: Mapped[str] = mapped_column(
        String(20), default="concurrent", server_default="concurrent"
    )
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    knowledge_base_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_bases.id"))
    embedding_model_id: Mapped[UUID] = mapped_column(ForeignKey("ai_models.id"))
    embedding_fingerprint: Mapped[str] = mapped_column(String(64))
    query: Mapped[dict[str, object] | None] = mapped_column(JSON)
    source_page: Mapped[int] = mapped_column(default=1)
    scan_complete: Mapped[bool] = mapped_column(default=False)
    total: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PublicLawVectorItem(Base):
    __tablename__ = "public_law_vector_items"
    __table_args__ = (
        UniqueConstraint("task_id", "law_id"),
        Index("ix_public_law_vector_items_queue", "task_id", "status", "sequence"),
        Index("ix_public_law_vector_items_recent", "task_id", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("public_law_vector_tasks.id"), index=True)
    law_id: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(1000))
    sequence: Mapped[int]
    decision: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    document_id: Mapped[UUID | None] = mapped_column(ForeignKey("knowledge_documents.id"))
    error_message: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
