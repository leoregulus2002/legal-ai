from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from app.core.database import SessionDependency
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.knowledge.schemas import DocumentDetail
from app.modules.knowledge.service import KnowledgeService
from app.modules.public_laws import service
from app.modules.public_laws.http_client import OfficialLawClient
from app.modules.public_laws.library_service import PublicLawLibraryService
from app.modules.public_laws.repository import PublicLawRepository
from app.modules.public_laws.schemas import (
    DownloadLink,
    DownloadRequest,
    PreviewLink,
    PublicLawDetail,
    PublicLawImportInput,
    PublicLawImportResult,
    PublicLawImportState,
    PublicLawMetadataInput,
    PublicLawOptions,
    PublicLawPage,
    PublicLawSearch,
    VectorTaskInput,
    VectorTaskView,
)
from app.modules.public_laws.task_service import PublicLawTaskService

router = APIRouter(prefix="/public-laws", tags=["public-laws"])
LawId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,100}$")]
FileFormat = Annotated[Literal["docx", "pdf"], Query(alias="format")]


def get_official_client(request: Request) -> OfficialLawClient:
    return request.app.state.official_laws


OfficialClient = Annotated[OfficialLawClient, Depends(get_official_client)]


def get_library(
    request: Request, session: SessionDependency, client: OfficialClient
) -> PublicLawLibraryService:
    return PublicLawLibraryService(
        PublicLawRepository(session),
        KnowledgeService(KnowledgeRepository(session), request.app.state.settings),
        client,
    )


Library = Annotated[PublicLawLibraryService, Depends(get_library)]


def get_tasks(library: Library) -> PublicLawTaskService:
    return PublicLawTaskService(library.repo, library.knowledge)


Tasks = Annotated[PublicLawTaskService, Depends(get_tasks)]


@router.get("/vector-tasks/latest", response_model=VectorTaskView | None)
async def latest_task(tasks: Tasks) -> VectorTaskView | None:
    return await tasks.latest()


@router.post("/vector-tasks", response_model=VectorTaskView, status_code=202)
async def start_task(data: VectorTaskInput, tasks: Tasks) -> VectorTaskView:
    return await tasks.start(data)


@router.post("/vector-tasks/{task_id}/stop", response_model=VectorTaskView)
async def stop_task(task_id: UUID, tasks: Tasks) -> VectorTaskView:
    return await tasks.stop(task_id)


@router.get("/options", response_model=PublicLawOptions)
async def get_options(client: OfficialClient) -> PublicLawOptions:
    return await service.options(client=client)


@router.post("/search", response_model=PublicLawPage)
async def search(query: PublicLawSearch, library: Library) -> PublicLawPage:
    return await library.search(query)


@router.post("/import-status", response_model=list[PublicLawImportState])
async def import_status(query: DownloadRequest, library: Library) -> list[PublicLawImportState]:
    return await library.states(query.ids)


@router.post("/{identifier}/import", response_model=PublicLawImportResult, status_code=202)
async def import_law(
    identifier: LawId, data: PublicLawImportInput, library: Library
) -> PublicLawImportResult:
    return await library.import_law(identifier, data)


@router.post("/{identifier}/metadata", response_model=DocumentDetail)
async def sync_metadata(
    identifier: LawId, data: PublicLawMetadataInput, library: Library
) -> DocumentDetail:
    return await library.sync_metadata(identifier, data)


@router.post("/downloads", response_model=list[DownloadLink])
async def downloads(query: DownloadRequest, client: OfficialClient) -> list[DownloadLink]:
    return await service.downloads(query, client=client)


@router.get("/{identifier}", response_model=PublicLawDetail)
async def detail(
    identifier: LawId, client: OfficialClient, decision: bool = False
) -> PublicLawDetail:
    return await service.detail(identifier, client=client, decision=decision)


@router.get("/{identifier}/preview", response_model=PreviewLink)
async def preview(
    identifier: LawId,
    client: OfficialClient,
    file_format: FileFormat = "docx",
    decision: bool = False,
) -> PreviewLink:
    return await service.preview(identifier, file_format, client=client, decision=decision)


@router.get("/{identifier}/download")
async def download(
    identifier: LawId, client: OfficialClient, file_format: FileFormat = "docx"
) -> Response:
    content = await service.download_file(identifier, file_format, client=client)
    media_type = (
        "application/pdf"
        if file_format == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return Response(
        content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{identifier}.{file_format}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
