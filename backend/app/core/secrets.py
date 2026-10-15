from cryptography.fernet import Fernet, InvalidToken

from app.common.exceptions import AppError
from app.core.config import Settings


def cipher(settings: Settings) -> Fernet:
    try:
        if not settings.config_encryption_key:
            raise ValueError
        return Fernet(settings.config_encryption_key.get_secret_value().encode())
    except ValueError as exc:
        raise AppError("encryption_unconfigured", "请先配置后端配置加密主密钥", 503) from exc


def encrypt(value: str, settings: Settings) -> str:
    return cipher(settings).encrypt(value.encode()).decode()


def decrypt(value: str | None, settings: Settings) -> str:
    if not value:
        return ""
    try:
        return cipher(settings).decrypt(value.encode()).decode()
    except (InvalidToken, UnicodeError) as exc:
        raise AppError(
            "credential_unavailable", "模型或知识库凭据无法读取，请检查配置", 503
        ) from exc
