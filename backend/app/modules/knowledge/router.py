from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile

from app.core.database import SessionDependency
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.knowledge.schemas import (
    AuditView,
    ComparisonView,
    CorrectionInput,
    DocumentDetail,
    DocumentPage,
    DocumentStatus,
    DocumentView,
    ImportMode,
    KnowledgeInput,
    KnowledgePage,
    KnowledgeView,
    ReviewInput,
    SearchPage,
    SegmentPage,
    VectorizeInput,
    VersionCandidate,
)
from app.modules.knowledge.service import KnowledgeService, document_view

router = APIRouter(prefix="/knowledge-bases", tags=["知识库"])


def get_service(request: Request, session: SessionDependency) -> KnowledgeService:
    return KnowledgeService(KnowledgeRepository(session), request.app.state.settings)


Service = Annotated[KnowledgeService, Depends(get_service)]
Page = Annotated[int, Query(ge=1, le=100000)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("", response_model=KnowledgePage)
async def bases(
    service: Service,
    q: Annotated[str, Query(max_length=200)] = "",
    page: Page = 1,
    page_size: PageSize = 20,
) -> KnowledgePage:
    return await service.bases(q, page, page_size)


@router.post("", response_model=KnowledgeView, status_code=201)
async def create_base(data: KnowledgeInput, service: Service) -> KnowledgeView:
    return await service.save_base(data)


@router.get("/search", response_model=SearchPage)
async def search(
    service: Service,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    knowledge_base_id: UUID | None = None,
    model_id: UUID | None = None,
    page: Page = 1,
    page_size: PageSize = 20,
) -> SearchPage:
    return await service.search(q, knowledge_base_id, page, page_size, model_id)


@router.get("/{base_id}", response_model=KnowledgeView)
async def get_base(base_id: UUID, service: Service) -> KnowledgeView:
    return KnowledgeView.model_validate(await service.base(base_id))


@router.put("/{base_id}", response_model=KnowledgeView)
async def update_base(base_id: UUID, data: KnowledgeInput, service: Service) -> KnowledgeView:
    return await service.save_base(data, base_id)


@router.delete("/{base_id}", status_code=204)
async def delete_base(base_id: UUID, service: Service) -> Response:
    await service.delete_base(base_id)
    return Response(status_code=204)


@router.get("/{base_id}/documents", response_model=DocumentPage)
async def documents(
    base_id: UUID,
    service: Service,
    q: Annotated[str, Query(max_length=200)] = "",
    status: DocumentStatus | None = None,
    page: Page = 1,
    page_size: PageSize = 20,
) -> DocumentPage:
    return await service.documents(base_id, q, status, page, page_size)


@router.post("/{base_id}/documents", response_model=DocumentView, status_code=202)
async def upload(
    base_id: UUID,
    service: Service,
    file: Annotated[UploadFile, File()],
    mode: Annotated[ImportMode, Form()] = "GENERAL",
    source_url: Annotated[str, Form(max_length=2000)] = "",
    source_note: Annotated[str, Form(max_length=2000)] = "",
    embedding_model_id: Annotated[UUID | None, Form()] = None,
) -> DocumentView:
    try:
        return await service.upload(
            base_id, file, mode, source_url, source_note, embedding_model_id
        )
    finally:
        await file.close()


@router.get("/{base_id}/documents/{document_id}", response_model=DocumentDetail)
async def document(
    base_id: UUID,
    document_id: UUID,
    service: Service,
    revision: Annotated[int | None, Query(ge=1)] = None,
) -> DocumentDetail:
    return await service.detail(base_id, document_id, revision)


@router.get("/{base_id}/documents/{document_id}/status", response_model=DocumentView)
async def document_status(base_id: UUID, document_id: UUID, service: Service) -> DocumentView:
    detail = await service.document(base_id, document_id)
    return document_view(detail)


@router.get("/{base_id}/documents/{document_id}/original")
async def original(base_id: UUID, document_id: UUID, service: Service) -> Response:
    row, data = await service.original(base_id, document_id)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(row.filename, safe='')}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.delete("/{base_id}/documents/{document_id}", status_code=204)
async def delete_document(base_id: UUID, document_id: UUID, service: Service) -> Response:
    await service.delete_document(base_id, document_id)
    return Response(status_code=204)


@router.put("/{base_id}/documents/{document_id}/correction", response_model=DocumentDetail)
async def correct(
    base_id: UUID, document_id: UUID, data: CorrectionInput, service: Service
) -> DocumentDetail:
    return await service.correct(base_id, document_id, data)


@router.post("/{base_id}/documents/{document_id}/publish", response_model=DocumentView)
async def publish(
    base_id: UUID, document_id: UUID, data: ReviewInput, service: Service
) -> DocumentView:
    return await service.publish(base_id, document_id, data)


@router.post("/{base_id}/documents/{document_id}/withdraw", response_model=DocumentView)
async def withdraw(
    base_id: UUID, document_id: UUID, data: ReviewInput, service: Service
) -> DocumentView:
    return await service.withdraw(base_id, document_id, data)


@router.post(
    "/{base_id}/documents/{document_id}/reparse", response_model=DocumentView, status_code=202
)
async def reparse(
    base_id: UUID, document_id: UUID, data: ReviewInput, service: Service
) -> DocumentView:
    return await service.reparse(base_id, document_id, data)


@router.post(
    "/{base_id}/documents/{document_id}/vectorize", response_model=DocumentView, status_code=202
)
async def vectorize(
    base_id: UUID, document_id: UUID, data: VectorizeInput, service: Service
) -> DocumentView:
    return await service.vectorize(base_id, document_id, data)


@router.get("/{base_id}/documents/{document_id}/segments", response_model=SegmentPage)
async def segments(
    base_id: UUID, document_id: UUID, service: Service, page: Page = 1, page_size: PageSize = 20
) -> SegmentPage:
    return await service.segments(base_id, document_id, page, page_size)


@router.get("/{base_id}/documents/{document_id}/versions", response_model=list[VersionCandidate])
async def versions(base_id: UUID, document_id: UUID, service: Service) -> list[VersionCandidate]:
    return await service.versions(base_id, document_id)


@router.get("/{base_id}/documents/{document_id}/compare/{other_id}", response_model=ComparisonView)
async def compare(
    base_id: UUID, document_id: UUID, other_id: UUID, service: Service
) -> ComparisonView:
    return await service.compare(base_id, document_id, other_id)


@router.get("/{base_id}/audit", response_model=list[AuditView])
async def audit(
    base_id: UUID,
    service: Service,
    document_id: UUID | None = None,
    page: Page = 1,
    page_size: PageSize = 20,
) -> list[AuditView]:
    return await service.audits(base_id, document_id, page, page_size)
