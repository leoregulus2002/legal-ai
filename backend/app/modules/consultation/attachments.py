import base64
from pathlib import Path
from uuid import UUID, uuid4

import anyio
from fastapi import UploadFile

from app.common.exceptions import AppError
from app.modules.consultation.models import Attachment
from app.modules.system_config.schemas import Policy


class AttachmentStorage:
    def __init__(self, directory: str) -> None:
        self.directory = Path(directory)

    def path(self, storage_key: str) -> anyio.Path:
        if len(storage_key) != 32 or any(char not in "0123456789abcdef" for char in storage_key):
            raise AppError("invalid_attachment", "附件不可用", 404)
        return anyio.Path(self.directory / storage_key)

    async def upload(self, upload: UploadFile, conversation_id: UUID, policy: Policy) -> Attachment:
        content = bytearray()
        while chunk := await upload.read(65536):
            content.extend(chunk)
            if len(content) > policy.max_file_mb * 1024 * 1024:
                raise AppError("file_too_large", "附件超过大小限制")
        data = bytes(content)
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif data.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            mime = "image/webp"
        elif data.startswith(b"%PDF-"):
            mime = "application/pdf"
        else:
            raise AppError("unsupported_file", "仅支持 JPEG、PNG、WebP 图片和 PDF")
        key = uuid4().hex
        await anyio.Path(self.directory).mkdir(parents=True, exist_ok=True)
        await self.path(key).write_bytes(data)
        return Attachment(
            conversation_id=conversation_id,
            name=Path(upload.filename or "附件").name[:200],
            mime_type=mime,
            size=len(data),
            storage_key=key,
        )

    async def content(self, row: Attachment) -> dict[str, object]:
        try:
            data = await self.path(row.storage_key).read_bytes()
        except OSError as exc:
            raise AppError("attachment_unavailable", "附件无法读取，请重新上传", 404) from exc
        encoded = f"data:{row.mime_type};base64," + base64.b64encode(data).decode()
        if row.mime_type == "application/pdf":
            return {"type": "file", "file": {"filename": row.name, "file_data": encoded}}
        return {"type": "image_url", "image_url": {"url": encoded}}

    async def remove(self, storage_key: str) -> None:
        await self.path(storage_key).unlink(missing_ok=True)
