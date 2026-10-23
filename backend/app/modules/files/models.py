from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class GeneratedFile(Base):
    __tablename__ = "generated_files"
    __table_args__ = (
        CheckConstraint(
            "(conversation_id IS NOT NULL AND request_id IS NOT NULL AND analysis_run_id IS NULL) "
            "OR (conversation_id IS NULL AND request_id IS NULL AND analysis_run_id IS NOT NULL)",
            name="generated_file_owner",
        ),
        UniqueConstraint("conversation_id", "request_id", "position"),
        UniqueConstraint("analysis_run_id", "position"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("consultation_conversations.id", ondelete="CASCADE"), index=True
    )
    request_id: Mapped[UUID | None]
    analysis_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    name: Mapped[str] = mapped_column(String(200))
    mime_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int]
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
