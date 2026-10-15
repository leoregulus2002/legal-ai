from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.modules.consultation.memory import MemoryStore
from app.modules.consultation.schemas import (
    AttachmentView,
    ConversationInput,
    ConversationView,
    GenerateInput,
    TurnView,
)
from app.modules.consultation.service import ConsultationService

router = APIRouter(prefix="/consultation", tags=["法律咨询"])


def get_service(request: Request) -> ConsultationService:
    return ConsultationService(
        request.app.state.database.sessions,
        request.app.state.settings,
        MemoryStore(request.app.state.redis.client),
    )


Service = Annotated[ConsultationService, Depends(get_service)]


@router.get("/options")
async def options(service: Service) -> dict[str, object]:
    return await service.options()


@router.get("/conversations", response_model=list[ConversationView])
async def conversations(
    service: Service,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[ConversationView]:
    return await service.conversations(offset, limit)


@router.post("/conversations", response_model=ConversationView, status_code=201)
async def create(data: ConversationInput, service: Service) -> ConversationView:
    return await service.create(data.title)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete(conversation_id: UUID, service: Service) -> Response:
    await service.delete(conversation_id)
    return Response(status_code=204)


@router.get("/conversations/{conversation_id}/messages", response_model=list[TurnView])
async def turns(
    conversation_id: UUID,
    service: Service,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> list[TurnView]:
    return await service.turns(conversation_id, after, limit)


@router.get("/conversations/{conversation_id}/attachments", response_model=list[AttachmentView])
async def attachments(conversation_id: UUID, service: Service) -> list[AttachmentView]:
    return await service.attachments(conversation_id)


@router.post(
    "/conversations/{conversation_id}/attachments", response_model=AttachmentView, status_code=201
)
async def upload(conversation_id: UUID, file: UploadFile, service: Service) -> AttachmentView:
    return await service.upload(conversation_id, file)


@router.get("/attachments/{attachment_id}")
async def attachment(attachment_id: UUID, service: Service) -> FileResponse:
    path, mime_type, name = await service.attachment(attachment_id)
    return FileResponse(
        path,
        media_type=mime_type,
        filename=name,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.delete("/attachments/{attachment_id}", status_code=204)
async def remove_attachment(attachment_id: UUID, service: Service) -> Response:
    await service.remove_attachment(attachment_id)
    return Response(status_code=204)


@router.post("/conversations/{conversation_id}/stream")
async def generate(
    conversation_id: UUID, data: GenerateInput, service: Service
) -> StreamingResponse:
    generation = await service.prepare(conversation_id, data)
    return StreamingResponse(
        service.stream(generation),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
