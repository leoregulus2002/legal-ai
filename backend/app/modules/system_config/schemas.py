from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_core import PydanticCustomError


def validate_endpoint(value: str) -> str:
    value = value.strip()
    try:
        url = urlsplit(value)
        _ = url.port
    except ValueError:
        raise PydanticCustomError("user_input", "请输入有效的 HTTP(S) 接口地址") from None
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise PydanticCustomError("user_input", "请输入不含凭据或查询参数的 HTTP(S) 地址")
    return value.rstrip("/")


class ModelInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    model_type: Literal["chat", "embedding", "other"] = "chat"
    protocol: Literal[
        "chat_completions", "responses", "openai_embeddings", "dashscope_embeddings"
    ] = "chat_completions"
    base_url: str = Field(max_length=1000)
    model_name: str = Field(min_length=1, max_length=200)
    api_key: SecretStr | None = Field(default=None, max_length=2000)
    clear_api_key: bool = False
    enabled: bool = True
    supports_images: bool = False
    supports_pdf: bool = False
    supports_json_mode: bool = False
    context_tokens: int = Field(default=32000, ge=1, le=4_000_000)
    max_output_tokens: int = Field(default=4096, ge=0, le=200_000)
    token_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    temperature: float | None = Field(default=None, ge=0, le=2)
    embedding_dimensions: int | None = Field(default=None, ge=1, le=4096)
    embedding_batch_size: int = Field(default=8, ge=1, le=32)
    embedding_timeout: int = Field(default=90, ge=1, le=300)
    embedding_query_instruction: str = Field(default="", max_length=2000)

    _endpoint = field_validator("base_url")(validate_endpoint)

    @model_validator(mode="after")
    def validate_budget(self) -> ModelInput:
        if self.model_type == "embedding":
            if self.protocol in {"chat_completions", "responses"}:
                self.protocol = "openai_embeddings"
            self.max_output_tokens = 0
            self.temperature = None
            self.supports_images = self.supports_pdf = self.supports_json_mode = False
            if self.embedding_query_instruction and self.protocol != "dashscope_embeddings":
                raise PydanticCustomError("user_input", "检索指令仅适用于 DashScope 原生协议")
        else:
            if self.context_tokens < 1024:
                raise PydanticCustomError("user_input", "对话模型上下文窗口至少为 1024")
            if self.protocol not in {"chat_completions", "responses"}:
                raise PydanticCustomError("user_input", "对话模型请选择对话协议")
            if self.max_output_tokens < 128 or self.max_output_tokens >= self.context_tokens:
                raise PydanticCustomError("user_input", "输出上限至少为 128，且必须小于上下文预算")
        if self.api_key and self.clear_api_key:
            raise PydanticCustomError("user_input", "不能同时设置和清除密钥")
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
    embedding_dimensions: int | None = None
    embedding_batch_size: int = 8
    embedding_timeout: int = 90
    embedding_query_instruction: str = ""
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
    knowledge_base_ids: list[UUID] = Field(default_factory=list, max_length=100)
    knowledge_vector_threshold: float = Field(default=0.3, ge=0, le=1)
    knowledge_keyword_threshold: float = Field(default=0, ge=0, le=1)
    knowledge_limit: int = Field(default=5, ge=1, le=20)
    request_timeout: int = Field(default=300, ge=30, le=900)
    max_attachments: int = Field(default=5, ge=1, le=10)
    max_file_mb: int = Field(default=10, ge=1, le=25)
    max_total_mb: int = Field(default=20, ge=1, le=50)

    @model_validator(mode="after")
    def validate_defaults(self) -> Policy:
        if len(set(self.allowed_model_ids)) != len(self.allowed_model_ids):
            raise ValueError("模型列表不能重复")
        if len(set(self.knowledge_base_ids)) != len(self.knowledge_base_ids):
            raise PydanticCustomError("user_input", "知识库不能重复添加")
        if self.default_model_id and self.default_model_id not in self.allowed_model_ids:
            raise ValueError("默认模型必须在法律咨询模型列表中")
        return self


PolicyInput = Policy
PolicyView = Policy
