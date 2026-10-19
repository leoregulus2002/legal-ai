from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.system_config.models import (
    ConsultationConfig,
    ModelConfig,
    PromptVersion,
    SystemPrompt,
    VectorizationConfig,
)


class ConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def models(self) -> list[ModelConfig]:
        return list(
            await self.session.scalars(select(ModelConfig).order_by(ModelConfig.created_at))
        )

    async def model(self, model_id: UUID, *, lock: bool = False) -> ModelConfig | None:
        return await self.session.get(ModelConfig, model_id, with_for_update=lock)

    async def prompts(self) -> list[SystemPrompt]:
        return list(await self.session.scalars(select(SystemPrompt).order_by(SystemPrompt.name)))

    async def prompt(self, prompt_id: UUID, *, lock: bool = False) -> SystemPrompt | None:
        return await self.session.get(SystemPrompt, prompt_id, with_for_update=lock)

    async def versions(self, prompt_id: UUID) -> list[PromptVersion]:
        return list(
            await self.session.scalars(
                select(PromptVersion)
                .where(PromptVersion.prompt_id == prompt_id)
                .order_by(PromptVersion.version.desc())
            )
        )

    async def delete_prompt(self, row: SystemPrompt) -> None:
        await self.session.execute(delete(PromptVersion).where(PromptVersion.prompt_id == row.id))
        await self.session.delete(row)
        await self.session.flush()

    async def policy(self, *, lock: bool = False) -> ConsultationConfig:
        row = await self.session.get(ConsultationConfig, 1, with_for_update=lock)
        if row is None:
            raise RuntimeError("consultation_config migration is required")
        return row

    async def vectorization(self, *, lock: bool = False) -> VectorizationConfig:
        row = await self.session.get(VectorizationConfig, 1, with_for_update=lock)
        if row is None:
            raise RuntimeError("vectorization_config migration is required")
        return row

    async def save(self, row: ModelConfig | SystemPrompt | PromptVersion) -> None:
        self.session.add(row)
        await self.session.flush()
