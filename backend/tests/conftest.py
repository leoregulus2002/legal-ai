import os
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# 导入默认 ASGI 入口前提供纯测试配置，不读取开发或生产凭据。
os.environ["DATABASE_URL"] = "postgresql+psycopg://test:test@localhost/test"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["APP_ENV"] = "test"
os.environ["DEBUG"] = "false"
os.environ["CORS_ORIGINS"] = '["http://localhost:5173"]'

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
def application() -> FastAPI:
    settings = Settings(_env_file=None)
    return create_app(settings)


@pytest.fixture
def client(application: FastAPI) -> Iterator[TestClient]:
    with (
        patch("app.core.database.Database.ping", new_callable=AsyncMock),
        patch("app.core.redis.RedisClient.ping", new_callable=AsyncMock),
        TestClient(application, raise_server_exceptions=False) as test_client,
    ):
        yield test_client
