from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Response

from app.core.database import SessionDependency
from app.modules.files.service import FileService

router = APIRouter(prefix="/files", tags=["生成文件"])


@router.get("/{file_id}")
async def download(file_id: UUID, session: SessionDependency) -> Response:
    name, mime_type, content = await FileService.download(session, file_id)
    return Response(
        content,
        media_type=mime_type,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name, safe=""),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "Content-Security-Policy": "sandbox",
        },
    )
