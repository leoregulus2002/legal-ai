from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_load_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_NAME", "legal-test")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("CORS_ORIGINS", '["https://example.com"]')
    settings = Settings(_env_file=None)
    assert settings.app_name == "legal-test"
    assert settings.debug is True
    assert settings.cors_origins == ["https://example.com"]
    assert "test:test" not in repr(settings)


@pytest.mark.parametrize(
    "field,value",
    [
        ("database_url", "sqlite:///bad"),
        ("redis_url", "http://invalid"),
        ("cors_origins", ["http://example.com/path"]),
    ],
)
def test_settings_reject_invalid_config(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_settings_load_dotenv(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("APP_NAME=dotenv-app\n", encoding="utf-8")
    settings = Settings(_env_file=env_file)
    assert settings.app_name == "dotenv-app"
