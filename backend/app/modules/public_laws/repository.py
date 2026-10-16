from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.knowledge.models import KnowledgeBase, KnowledgeDocument


class PublicLawRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def imports(
        self, identifiers: list[str], base_id: UUID | None = None
    ) -> Sequence[tuple[KnowledgeDocument, KnowledgeBase]]:
        if not identifiers:
            return []
        statement = (
            select(KnowledgeDocument, KnowledgeBase)
            .join(KnowledgeBase, KnowledgeBase.id == KnowledgeDocument.knowledge_base_id)
            .where(
                KnowledgeDocument.public_law_id.in_(identifiers),
                KnowledgeDocument.deleted_at.is_(None),
                KnowledgeBase.deleted_at.is_(None),
            )
            .order_by(KnowledgeDocument.created_at)
            .execution_options(populate_existing=True)
        )
        if base_id is not None:
            statement = statement.where(KnowledgeDocument.knowledge_base_id == base_id)
        rows = await self.session.execute(statement)
        return [(document, base) for document, base in rows]

    async def save(self, document: KnowledgeDocument) -> None:
        self.session.add(document)
        await self.session.flush()
