from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.core.database import SessionDependency
from app.modules.system_config.repository import ConfigRepository
from app.modules.system_config.schemas import (
    ModelInput,
    ModelView,
    PolicyInput,
    PolicyView,
    PromptInput,
    PromptView,
    VectorizationSettings,
)
from app.modules.system_config.service import ConfigService

router = APIRouter(prefix="/system-config", tags=["系统配置"])


def get_service(request: Request, session: SessionDependency) -> ConfigService:
    return ConfigService(ConfigRepository(session), request.app.state.settings)


Service = Annotated[ConfigService, Depends(get_service)]


@router.get("/models", response_model=list[ModelView])
async def list_models(service: Service) -> list[ModelView]:
    return await service.models()


@router.post("/models", response_model=ModelView, status_code=201)
async def create_model(data: ModelInput, service: Service) -> ModelView:
    return await service.save_model(data)


@router.put("/models/{model_id}", response_model=ModelView)
async def update_model(model_id: UUID, data: ModelInput, service: Service) -> ModelView:
    return await service.save_model(data, model_id)


@router.get("/prompts", response_model=list[PromptView])
async def list_prompts(service: Service) -> list[PromptView]:
    return await service.prompts()


@router.post("/prompts", response_model=PromptView, status_code=201)
async def create_prompt(data: PromptInput, service: Service) -> PromptView:
    return await service.save_prompt(data)


@router.put("/prompts/{prompt_id}", response_model=PromptView)
async def update_prompt(prompt_id: UUID, data: PromptInput, service: Service) -> PromptView:
    return await service.save_prompt(data, prompt_id)


@router.get("/prompts/{prompt_id}/versions")
async def prompt_versions(prompt_id: UUID, service: Service) -> list[dict[str, object]]:
    return await service.versions(prompt_id)


@router.delete("/prompts/{prompt_id}", status_code=204)
async def delete_prompt(prompt_id: UUID, service: Service) -> Response:
    await service.delete_prompt(prompt_id)
    return Response(status_code=204)


@router.get("/consultation", response_model=PolicyView)
async def get_policy(service: Service) -> PolicyView:
    return await service.policy()


@router.put("/consultation", response_model=PolicyView)
async def update_policy(data: PolicyInput, service: Service) -> PolicyView:
    return await service.save_policy(data)


@router.get("/vectorization", response_model=VectorizationSettings)
async def get_vectorization(service: Service) -> VectorizationSettings:
    return await service.vectorization()


@router.put("/vectorization", response_model=VectorizationSettings)
async def update_vectorization(
    data: VectorizationSettings, service: Service
) -> VectorizationSettings:
    return await service.save_vectorization(data)
