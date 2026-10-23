from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.modules.files.models import GeneratedFile


class FileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, file_id: UUID) -> GeneratedFile | None:
        return await self.session.scalar(
            select(GeneratedFile)
            .where(GeneratedFile.id == file_id)
            .options(undefer(GeneratedFile.content))
        )

    async def consultation(
        self, conversation_id: UUID, requests: list[UUID]
    ) -> list[GeneratedFile]:
        return list(
            await self.session.scalars(
                select(GeneratedFile)
                .where(
                    GeneratedFile.conversation_id == conversation_id,
                    GeneratedFile.request_id.in_(requests),
                )
                .order_by(GeneratedFile.created_at, GeneratedFile.position)
            )
        )

    async def analysis(self, run_id: UUID) -> list[GeneratedFile]:
        return list(
            await self.session.scalars(
                select(GeneratedFile)
                .where(GeneratedFile.analysis_run_id == run_id)
                .order_by(GeneratedFile.position)
            )
        )

    async def save(self, rows: list[GeneratedFile]) -> None:
        self.session.add_all(rows)
        await self.session.flush()

    async def delete_analysis(self, run_id: UUID) -> None:
        await self.session.execute(
            delete(GeneratedFile).where(GeneratedFile.analysis_run_id == run_id)
        )
