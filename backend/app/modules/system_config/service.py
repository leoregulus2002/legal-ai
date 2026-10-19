from uuid import UUID

from app.common.exceptions import AppError
from app.core.config import Settings
from app.core.secrets import encrypt
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.system_config.models import ModelConfig, PromptVersion, SystemPrompt
from app.modules.system_config.repository import ConfigRepository
from app.modules.system_config.schemas import (
    ModelInput,
    ModelView,
    Policy,
    PolicyInput,
    PolicyView,
    PromptInput,
    PromptView,
    VectorizationSettings,
)


class ConfigService:
    def __init__(self, repository: ConfigRepository, settings: Settings) -> None:
        self.repo = repository
        self.settings = settings

    @staticmethod
    def model_view(row: ModelConfig) -> ModelView:
        return ModelView.model_validate(row).model_copy(
            update={"has_api_key": bool(row.api_key_encrypted)}
        )

    async def save_model(self, data: ModelInput, model_id: UUID | None = None) -> ModelView:
        policy = Policy.model_validate((await self.repo.policy(lock=True)).settings)
        row = await self.repo.model(model_id, lock=True) if model_id else ModelConfig()
        if row is None:
            raise AppError("model_not_found", "模型不存在", 404)
        for key, value in data.model_dump(exclude={"api_key", "clear_api_key"}).items():
            setattr(row, key, value)
        if data.api_key:
            row.api_key_encrypted = encrypt(data.api_key.get_secret_value(), self.settings)
        elif data.clear_api_key:
            row.api_key_encrypted = None
        if model_id in policy.allowed_model_ids and (not row.enabled or row.model_type != "chat"):
            raise AppError("model_in_use", "请先从法律咨询可用模型中移除此模型")
        await self.repo.save(row)
        return self.model_view(row)

    async def save_prompt(self, data: PromptInput, prompt_id: UUID | None = None) -> PromptView:
        policy = Policy.model_validate((await self.repo.policy(lock=True)).settings)
        row = await self.repo.prompt(prompt_id, lock=True) if prompt_id else SystemPrompt(version=0)
        if row is None:
            raise AppError("prompt_not_found", "系统提示词不存在", 404)
        if prompt_id and prompt_id == policy.default_prompt_id and not data.enabled:
            raise AppError("prompt_in_use", "请先更换默认系统提示词")
        row.name, row.content, row.enabled = data.name, data.content, data.enabled
        row.version += 1
        await self.repo.save(row)
        await self.repo.save(
            PromptVersion(prompt_id=row.id, version=row.version, name=row.name, content=row.content)
        )
        return PromptView.model_validate(row)

    async def delete_prompt(self, prompt_id: UUID) -> None:
        policy_row = await self.repo.policy(lock=True)
        policy = Policy.model_validate(policy_row.settings)
        row = await self.repo.prompt(prompt_id, lock=True)
        if row is None:
            raise AppError("prompt_not_found", "系统提示词不存在", 404)
        if policy.default_prompt_id == prompt_id:
            policy.default_prompt_id = None
            policy_row.settings = policy.model_dump(mode="json")
        await self.repo.delete_prompt(row)

    async def models(self) -> list[ModelView]:
        return [self.model_view(row) for row in await self.repo.models()]

    async def prompts(self) -> list[PromptView]:
        return [PromptView.model_validate(row) for row in await self.repo.prompts()]

    async def versions(self, prompt_id: UUID) -> list[dict[str, object]]:
        if not await self.repo.prompt(prompt_id):
            raise AppError("prompt_not_found", "系统提示词不存在", 404)
        return [
            {"version": row.version, "name": row.name, "content": row.content}
            for row in await self.repo.versions(prompt_id)
        ]

    async def policy(self) -> PolicyView:
        row = await self.repo.policy()
        return PolicyView.model_validate(row.settings)

    async def vectorization(self) -> VectorizationSettings:
        return VectorizationSettings.model_validate(await self.repo.vectorization())

    async def save_vectorization(self, data: VectorizationSettings) -> VectorizationSettings:
        row = await self.repo.vectorization(lock=True)
        row.concurrency = data.concurrency
        await self.repo.session.flush()
        return VectorizationSettings.model_validate(row)

    async def save_policy(self, data: PolicyInput) -> PolicyView:
        row = await self.repo.policy(lock=True)
        for model_id in data.allowed_model_ids:
            model = await self.repo.model(model_id)
            if not model or not model.enabled or model.model_type != "chat":
                raise AppError("invalid_consultation_model", "请选择已启用的对话模型")
        if data.default_prompt_id:
            prompt = await self.repo.prompt(data.default_prompt_id)
            if not prompt or not prompt.enabled:
                raise AppError("invalid_prompt", "请选择已启用的系统提示词")
        existing = await KnowledgeRepository(self.repo.session).existing_base_ids(
            data.knowledge_base_ids
        )
        if existing != set(data.knowledge_base_ids):
            raise AppError("invalid_knowledge_base", "所选知识库已不存在，请重新选择")
        row.settings = Policy.model_validate(data.model_dump()).model_dump(mode="json")
        return PolicyView.model_validate(row.settings)
