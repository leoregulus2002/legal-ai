from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.database import SessionDependency
from app.modules.knowledge.regulation_repository import RegulationRepository
from app.modules.knowledge.regulation_schemas import (
    RegulationDetail,
    RegulationOptions,
    RegulationPage,
    RegulationQuery,
)
from app.modules.knowledge.regulation_service import RegulationService

router = APIRouter(prefix="/knowledge-bases/regulations", tags=["法律法规检索"])


def get_service(session: SessionDependency) -> RegulationService:
    return RegulationService(RegulationRepository(session))


Service = Annotated[RegulationService, Depends(get_service)]


@router.get("/options", response_model=RegulationOptions)
async def options(service: Service) -> RegulationOptions:
    return await service.options()


@router.get("", response_model=RegulationPage)
async def search(query: Annotated[RegulationQuery, Query()], service: Service) -> RegulationPage:
    return await service.search(query)


@router.get("/{document_id}", response_model=RegulationDetail)
async def detail(document_id: UUID, service: Service) -> RegulationDetail:
    return await service.detail(document_id)
