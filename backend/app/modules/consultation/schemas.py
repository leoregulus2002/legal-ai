from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.files.schemas import GeneratedFileView


class ConversationInput(BaseModel):
    title: str = Field(default="新咨询", min_length=1, max_length=100)


class ConversationView(ConversationInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    history_version: int
    updated_at: datetime


class AttachmentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    mime_type: str
    size: int
    bound: bool


class TurnView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    request_id: UUID
    sequence: int
    user_text: str
    answer: str
    reasoning: str = ""
    attachment_ids: list[str]
    sources: list[dict[str, object]]
    config_snapshot: dict[str, object]
    created_at: datetime
    files: list[GeneratedFileView] = Field(default_factory=list)


class ToolActivity(BaseModel):
    id: str
    name: str
    status: Literal["preparing", "running", "completed"]
    answer_offset: int = Field(ge=0)
    summary: str = ""
    duration_ms: int | None = None


class ResponsePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["context", "knowledge"]
    query: str = Field(max_length=500)
    file_requested: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_query(self) -> ResponsePlan:
        self.query = self.query.strip()
        if self.mode == "knowledge" and not self.query:
            raise ValueError("Knowledge retrieval requires a query")
        if self.mode == "context" and self.query:
            raise ValueError("Context-only requests must not include a retrieval query")
        return self


class GenerateInput(BaseModel):
    request_id: UUID
    model_id: UUID
    prompt_id: UUID | None = None
    text: str = Field(default="", max_length=30000)
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=10)
    knowledge_enabled: bool = False

    @model_validator(mode="after")
    def validate_content(self) -> GenerateInput:
        if not self.text.strip() and not self.attachment_ids:
            raise ValueError("请输入问题或上传附件")
        if len(set(self.attachment_ids)) != len(self.attachment_ids):
            raise ValueError("附件不能重复")
        if self.knowledge_enabled and not self.text.strip():
            # 纯附件消息交由多模态模型处理，不使用空文字查询知识库。
            self.knowledge_enabled = False
        return self


class ContextUsageInput(BaseModel):
    conversation_id: UUID | None = None
    model_id: UUID
    text: str = Field(default="", max_length=30000)
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=10)
    knowledge_enabled: bool = False


class ContextUsageView(BaseModel):
    used_tokens: int | None
    context_tokens: int
    max_output_tokens: int


class MemoryTurn(BaseModel):
    sequence: int
    user_text: str
    answer: str
    attachment_ids: list[UUID] = Field(default_factory=list)
    generated_files: dict[str, object] | None = None


class Memory(BaseModel):
    history_version: int = 0
    policy_version: str
    covered_through: int = 0
    summary: str = ""
    keywords: list[str] = Field(default_factory=list)
    recent: list[MemoryTurn] = Field(default_factory=list)


class SummaryResult(BaseModel):
    summary: str = Field(max_length=8000)
    keywords: list[str] = Field(max_length=30)
