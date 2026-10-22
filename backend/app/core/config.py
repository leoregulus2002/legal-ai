from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    app_name: str = "legal-ai"
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    database_url: SecretStr
    redis_url: SecretStr
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    config_encryption_key: SecretStr | None = None
    attachment_directory: str = "./data/attachments"
    word_extractor_path: str = "antiword"
    word_converter_path: str = ""
    diagnostic_directory: str = "./data/diagnostics"
    mcp_allow_private: bool = False

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            valid = url.drivername == "postgresql+psycopg" and url.host and url.database
        except Exception:
            valid = False
        if not valid:
            raise ValueError("DATABASE_URL 必须为 postgresql+psycopg:// 的完整连接地址")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = urlsplit(value.get_secret_value())
            valid = url.scheme in {"redis", "rediss"} and url.hostname and (url.port or 6379)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("REDIS_URL 必须为 redis:// 或 rediss:// 的完整连接地址")
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_origins(cls, values: list[str]) -> list[str]:
        for value in values:
            url = urlsplit(value)
            if (
                url.scheme not in {"http", "https"}
                or not url.netloc
                or url.path
                or url.query
                or url.fragment
            ):
                raise ValueError("CORS_ORIGINS 必须为 JSON 数组，元素为不带路径的 HTTP(S) origin")
        return values


@lru_cache
def get_settings() -> Settings:
    return Settings()
