from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, UploadFile
from fastapi.responses import StreamingResponse

from app.common.exceptions import AppError
from app.modules.document_analysis.export import markdown_report
from app.modules.document_analysis.schemas import (
    AnalysisConfig,
    DocumentDetail,
    DocumentUpdate,
    DocumentView,
    MCPServerInput,
    MCPServerView,
    ResumeInput,
    RunInput,
    RunView,
    WorkspaceInput,
    WorkspaceView,
)
from app.modules.document_analysis.service import AnalysisService

router = APIRouter(prefix="/document-analysis", tags=["法律文书分析"])


def get_service(request: Request) -> AnalysisService:
    return AnalysisService(request.app.state.database.sessions, request.app.state.settings)


Service = Annotated[AnalysisService, Depends(get_service)]


@router.get("/options")
async def options(service: Service) -> dict[str, object]:
    return await service.options()


@router.get("/workspaces")
async def workspaces(service: Service) -> list[WorkspaceView]:
    return await service.workspaces()


@router.post("/workspaces", status_code=201)
async def create_workspace(data: WorkspaceInput, service: Service) -> WorkspaceView:
    return await service.save_workspace(data)


@router.patch("/workspaces/{workspace_id}")
async def update_workspace(
    workspace_id: UUID, data: WorkspaceInput, service: Service
) -> WorkspaceView:
    return await service.save_workspace(data, workspace_id)


@router.delete("/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: UUID, service: Service) -> Response:
    await service.delete_workspace(workspace_id)
    return Response(status_code=204)


@router.get("/workspaces/{workspace_id}/documents")
async def documents(workspace_id: UUID, service: Service) -> list[DocumentView]:
    return await service.documents(workspace_id)


@router.post("/workspaces/{workspace_id}/documents", status_code=201)
async def upload(
    workspace_id: UUID, file: UploadFile, request: Request, service: Service
) -> DocumentView:
    content = bytearray()
    try:
        while chunk := await file.read(65536):
            content.extend(chunk)
            if len(content) > 20 * 1024 * 1024:
                raise AppError("document_too_large", "单份文书不能超过 20 MB")
        if not content:
            raise AppError("empty_document", "上传文书不能为空")
        return await service.upload(
            workspace_id,
            file.filename or "文书",
            bytes(content),
            getattr(request.state, "request_id", None),
        )
    finally:
        await file.close()


@router.get("/workspaces/{workspace_id}/documents/{document_id}")
async def document(workspace_id: UUID, document_id: UUID, service: Service) -> DocumentDetail:
    return await service.document(workspace_id, document_id)


@router.patch("/workspaces/{workspace_id}/documents/{document_id}")
async def update_document(
    workspace_id: UUID, document_id: UUID, data: DocumentUpdate, service: Service
) -> DocumentView:
    return await service.update_document(workspace_id, document_id, data)


@router.delete("/workspaces/{workspace_id}/documents/{document_id}", status_code=204)
async def delete_document(workspace_id: UUID, document_id: UUID, service: Service) -> Response:
    await service.update_document(workspace_id, document_id, None)
    return Response(status_code=204)


@router.get("/workspaces/{workspace_id}/documents/{document_id}/original")
async def original(workspace_id: UUID, document_id: UUID, service: Service) -> Response:
    data, mime, filename = await service.original(workspace_id, document_id)
    return Response(
        data,
        media_type=mime,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename, safe=""),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/workspaces/{workspace_id}/runs")
async def runs(workspace_id: UUID, service: Service) -> list[RunView]:
    return await service.runs(workspace_id)


@router.post("/workspaces/{workspace_id}/runs", status_code=201)
async def create_run(workspace_id: UUID, data: RunInput, service: Service) -> RunView:
    return await service.create_run(workspace_id, data)


@router.get("/workspaces/{workspace_id}/runs/{run_id}")
async def run(workspace_id: UUID, run_id: UUID, service: Service) -> RunView:
    return await service.run(workspace_id, run_id)


@router.post("/workspaces/{workspace_id}/runs/{run_id}/cancel")
async def cancel(workspace_id: UUID, run_id: UUID, service: Service) -> RunView:
    return await service.action(workspace_id, run_id, "cancel")


@router.post("/workspaces/{workspace_id}/runs/{run_id}/resume")
async def resume(workspace_id: UUID, run_id: UUID, data: ResumeInput, service: Service) -> RunView:
    return await service.action(workspace_id, run_id, "resume", data.answer)


@router.post("/workspaces/{workspace_id}/runs/{run_id}/retry")
async def retry(workspace_id: UUID, run_id: UUID, service: Service) -> RunView:
    return await service.action(workspace_id, run_id, "retry")


@router.get("/workspaces/{workspace_id}/runs/{run_id}/export")
async def export(workspace_id: UUID, run_id: UUID, service: Service) -> Response:
    item = await service.run(workspace_id, run_id)
    if item.report is None:
        raise AppError("analysis_report_pending", "分析报告尚未生成")
    return Response(
        markdown_report(item),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote("法律文书分析报告.md"),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/workspaces/{workspace_id}/runs/{run_id}/events")
async def events(workspace_id: UUID, run_id: UUID, service: Service) -> StreamingResponse:
    await service.run(workspace_id, run_id)

    return StreamingResponse(
        service.run_events(workspace_id, run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/config")
async def config(service: Service) -> AnalysisConfig:
    return await service.config()


@router.put("/config")
async def save_config(data: AnalysisConfig, service: Service) -> AnalysisConfig:
    return await service.config(data)


@router.get("/mcp-servers")
async def servers(service: Service) -> list[MCPServerView]:
    return await service.servers()


@router.post("/mcp-servers", status_code=201)
async def create_server(data: MCPServerInput, service: Service) -> MCPServerView:
    return await service.save_server(data)


@router.put("/mcp-servers/{server_id}")
async def update_server(server_id: UUID, data: MCPServerInput, service: Service) -> MCPServerView:
    return await service.save_server(data, server_id)


@router.delete("/mcp-servers/{server_id}", status_code=204)
async def delete_server(server_id: UUID, service: Service) -> Response:
    await service.delete_server(server_id)
    return Response(status_code=204)


@router.post("/mcp-servers/{server_id}/discover")
async def discover(server_id: UUID, service: Service) -> list[dict[str, object]]:
    return await service.discover(server_id)
