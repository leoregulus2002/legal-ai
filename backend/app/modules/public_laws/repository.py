from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.knowledge.models import KnowledgeBase, KnowledgeDocument
from app.modules.public_laws.models import PublicLawVectorItem, PublicLawVectorTask
from app.modules.public_laws.schemas import VectorTaskItemView, VectorTaskLaw, VectorTaskView


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

    async def admission_lock(self) -> None:
        await self.session.execute(text("SELECT pg_advisory_xact_lock(70201910)"))

    async def worker_lock(self) -> bool:
        return bool(await self.session.scalar(text("SELECT pg_try_advisory_xact_lock(70201911)")))

    async def active_task(self) -> PublicLawVectorTask | None:
        return await self.session.scalar(
            select(PublicLawVectorTask).where(
                PublicLawVectorTask.status.in_(["RUNNING", "STOPPING"])
            )
        )

    async def task(self, task_id: UUID, *, lock: bool = False) -> PublicLawVectorTask | None:
        statement = select(PublicLawVectorTask).where(PublicLawVectorTask.id == task_id)
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement.execution_options(populate_existing=True))

    async def latest_task(self) -> PublicLawVectorTask | None:
        return await self.session.scalar(
            select(PublicLawVectorTask).order_by(PublicLawVectorTask.created_at.desc()).limit(1)
        )

    async def has_processing_laws(self) -> bool:
        return bool(
            await self.session.scalar(
                select(KnowledgeDocument.id)
                .join(KnowledgeBase)
                .where(
                    KnowledgeDocument.public_law_id.is_not(None),
                    KnowledgeDocument.deleted_at.is_(None),
                    KnowledgeBase.deleted_at.is_(None),
                    KnowledgeDocument.status.in_(["QUEUED", "PROCESSING"]),
                )
                .limit(1)
            )
        )

    async def add_task(self, task: PublicLawVectorTask) -> None:
        self.session.add(task)
        await self.session.flush()

    async def add_items(
        self,
        task_id: UUID,
        laws: list[VectorTaskLaw],
        *,
        offset: int = 0,
        completed: set[str] | None = None,
    ) -> None:
        if laws:
            await self.session.execute(
                insert(PublicLawVectorItem)
                .values(
                    [
                        dict(
                            task_id=task_id,
                            law_id=law.id,
                            title=law.title,
                            decision=law.decision,
                            sequence=offset + index,
                            status="SKIPPED" if completed and law.id in completed else "PENDING",
                        )
                        for index, law in enumerate({law.id: law for law in laws}.values())
                    ]
                )
                .on_conflict_do_nothing(index_elements=["task_id", "law_id"])
            )

    async def next_item(self, task_id: UUID) -> PublicLawVectorItem | None:
        return await self.session.scalar(
            select(PublicLawVectorItem)
            .where(
                PublicLawVectorItem.task_id == task_id,
                PublicLawVectorItem.status.in_(["PROCESSING", "PENDING"]),
            )
            .order_by(
                (PublicLawVectorItem.status == "PROCESSING").desc(),
                PublicLawVectorItem.sequence,
            )
            .limit(1)
        )

    async def item(self, item_id: UUID) -> PublicLawVectorItem | None:
        return await self.session.get(PublicLawVectorItem, item_id)

    async def document_stop_requested(self, document_id: UUID) -> bool:
        return bool(
            await self.session.scalar(
                select(PublicLawVectorItem.id)
                .join(PublicLawVectorTask)
                .where(
                    PublicLawVectorItem.document_id == document_id,
                    PublicLawVectorItem.status == "PROCESSING",
                    PublicLawVectorTask.status == "STOPPING",
                )
                .limit(1)
            )
        )

    async def task_view(self, task: PublicLawVectorTask) -> VectorTaskView:
        counts = dict(
            (
                await self.session.execute(
                    select(PublicLawVectorItem.status, func.count())
                    .where(
                        PublicLawVectorItem.task_id == task.id,
                    )
                    .group_by(PublicLawVectorItem.status)
                )
            ).all()
        )
        current = await self.session.scalar(
            select(PublicLawVectorItem)
            .where(
                PublicLawVectorItem.task_id == task.id,
                PublicLawVectorItem.status == "PROCESSING",
            )
            .limit(1)
        )
        recent = await self.session.scalars(
            select(PublicLawVectorItem)
            .where(
                PublicLawVectorItem.task_id == task.id,
                PublicLawVectorItem.status != "PENDING",
            )
            .order_by(PublicLawVectorItem.updated_at.desc(), PublicLawVectorItem.sequence.desc())
            .limit(50)
        )
        document = (
            await self.session.get(KnowledgeDocument, current.document_id)
            if current and current.document_id
            else None
        )

        def item_view(item: PublicLawVectorItem) -> VectorTaskItemView:
            return VectorTaskItemView.model_validate(item, from_attributes=True)

        return VectorTaskView(
            id=task.id,
            status=task.status,
            knowledge_base_id=task.knowledge_base_id,
            total=sum(counts.values()) if task.status == "COMPLETED" else task.total,
            discovered=sum(counts.values()),
            completed=counts.get("COMPLETED", 0),
            skipped=counts.get("SKIPPED", 0),
            failed=counts.get("FAILED", 0),
            current=item_view(current) if current else None,
            stage=document.processing_stage
            if document
            else ("IMPORTING" if current else "SCANNING"),
            embedded_count=document.embedded_count if document else 0,
            chunk_count=document.chunk_count if document else 0,
            recent=[item_view(item) for item in recent],
            created_at=task.created_at,
            finished_at=task.finished_at,
        )
