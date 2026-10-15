from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


def validate_endpoint(value: str) -> str:
    url = urlsplit(value)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("请输入不含凭据或查询参数的 HTTP(S) 地址")
    return value.rstrip("/")


class ModelInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    model_type: Literal["chat", "embedding", "other"] = "chat"
    protocol: Literal["chat_completions", "responses"] = "chat_completions"
    base_url: str = Field(max_length=1000)
    model_name: str = Field(min_length=1, max_length=200)
    api_key: SecretStr | None = Field(default=None, max_length=2000)
    clear_api_key: bool = False
    enabled: bool = True
    supports_images: bool = False
    supports_pdf: bool = False
    supports_json_mode: bool = False
    context_tokens: int = Field(default=32000, ge=1024, le=4_000_000)
    max_output_tokens: int = Field(default=4096, ge=128, le=200_000)
    token_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    temperature: float | None = Field(default=None, ge=0, le=2)

    _endpoint = field_validator("base_url")(validate_endpoint)

    @model_validator(mode="after")
    def validate_budget(self) -> ModelInput:
        if self.max_output_tokens >= self.context_tokens:
            raise ValueError("输出上限必须小于上下文预算")
        if self.api_key and self.clear_api_key:
            raise ValueError("不能同时设置和清除密钥")
        return self


class ModelView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    model_type: str
    protocol: str
    base_url: str
    model_name: str
    enabled: bool
    supports_images: bool
    supports_pdf: bool
    supports_json_mode: bool
    context_tokens: int
    max_output_tokens: int
    token_parameter: str
    temperature: float | None
    has_api_key: bool = False


class PromptInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=30000)
    enabled: bool = True


class PromptView(PromptInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version: int


class Policy(BaseModel):
    allowed_model_ids: list[UUID] = Field(default_factory=list, max_length=100)
    default_model_id: UUID | None = None
    default_prompt_id: UUID | None = None
    recent_turns: int = Field(default=6, ge=1, le=30)
    summary_chars: int = Field(default=2000, ge=200, le=8000)
    keyword_count: int = Field(default=12, ge=1, le=30)
    memory_ttl_days: int = Field(default=7, ge=1, le=90)
    knowledge_url: str = Field(default="", max_length=1000)
    knowledge_threshold: float = Field(default=0.7, ge=0, le=1)
    knowledge_limit: int = Field(default=5, ge=1, le=20)
    knowledge_timeout: int = Field(default=15, ge=1, le=120)
    request_timeout: int = Field(default=300, ge=30, le=900)
    max_attachments: int = Field(default=5, ge=1, le=10)
    max_file_mb: int = Field(default=10, ge=1, le=25)
    max_total_mb: int = Field(default=20, ge=1, le=50)

    @field_validator("knowledge_url")
    @classmethod
    def validate_knowledge_url(cls, value: str) -> str:
        return validate_endpoint(value) if value else ""

    @model_validator(mode="after")
    def validate_defaults(self) -> Policy:
        if len(set(self.allowed_model_ids)) != len(self.allowed_model_ids):
            raise ValueError("模型列表不能重复")
        if self.default_model_id and self.default_model_id not in self.allowed_model_ids:
            raise ValueError("默认模型必须在法律咨询模型列表中")
        return self


class PolicyInput(Policy):
    knowledge_api_key: SecretStr | None = Field(default=None, max_length=2000)
    clear_knowledge_api_key: bool = False


class PolicyView(Policy):
    has_knowledge_api_key: bool = False
