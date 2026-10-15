from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Conversation(Base):
    __tablename__ = "consultation_conversations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(100), default="新咨询")
    history_version: Mapped[int] = mapped_column(default=0)
    active_token: Mapped[UUID | None]
    active_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Turn(Base):
    __tablename__ = "consultation_turns"
    __table_args__ = (
        UniqueConstraint("conversation_id", "request_id", name="uq_consultation_turns_request"),
        UniqueConstraint("conversation_id", "sequence", name="uq_consultation_turns_sequence"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("consultation_conversations.id", ondelete="CASCADE"), index=True
    )
    request_id: Mapped[UUID]
    sequence: Mapped[int]
    user_text: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    attachment_ids: Mapped[list[str]] = mapped_column(JSON)
    sources: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    config_snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Attachment(Base):
    __tablename__ = "consultation_attachments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("consultation_conversations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    mime_type: Mapped[str] = mapped_column(String(50))
    size: Mapped[int]
    storage_key: Mapped[str] = mapped_column(String(40), unique=True)
    bound: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
