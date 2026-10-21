from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ModelConfig(Base):
    __tablename__ = "ai_models"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100))
    model_type: Mapped[str] = mapped_column(String(30))
    protocol: Mapped[str] = mapped_column(String(30))
    base_url: Mapped[str] = mapped_column(String(1000))
    model_name: Mapped[str] = mapped_column(String(200))
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True)
    supports_images: Mapped[bool] = mapped_column(default=False)
    supports_pdf: Mapped[bool] = mapped_column(default=False)
    supports_json_mode: Mapped[bool] = mapped_column(default=False)
    context_tokens: Mapped[int] = mapped_column(default=32000)
    max_output_tokens: Mapped[int] = mapped_column(default=4096)
    token_parameter: Mapped[str] = mapped_column(String(30), default="max_tokens")
    temperature: Mapped[float | None]
    embedding_dimensions: Mapped[int | None]
    embedding_batch_size: Mapped[int] = mapped_column(default=8, server_default="8")
    embedding_timeout: Mapped[int] = mapped_column(default=90, server_default="90")
    embedding_query_instruction: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemPrompt(Base):
    __tablename__ = "system_prompts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True)
    version: Mapped[int] = mapped_column(default=1)


class PromptVersion(Base):
    __tablename__ = "system_prompt_versions"
    __table_args__ = (UniqueConstraint("prompt_id", "version"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    prompt_id: Mapped[UUID] = mapped_column(ForeignKey("system_prompts.id"))
    version: Mapped[int]
    name: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConsultationConfig(Base):
    __tablename__ = "consultation_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    settings: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    kb_key_encrypted: Mapped[str | None] = mapped_column(Text)


class VectorizationConfig(Base):
    __tablename__ = "vectorization_config"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("concurrency BETWEEN 1 AND 10", name="concurrency_range"),
        CheckConstraint("request_mode IN ('serial', 'concurrent')", name="request_mode_values"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    concurrency: Mapped[int] = mapped_column(default=1, server_default="1")
    request_mode: Mapped[str] = mapped_column(
        String(20), default="concurrent", server_default="concurrent"
    )
