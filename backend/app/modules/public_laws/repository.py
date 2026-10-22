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

    async def next_items(
        self,
        task_id: UUID,
        *,
        with_document: bool,
        limit: int,
        exclude: Sequence[UUID] = (),
    ) -> list[PublicLawVectorItem]:
        return list(
            await self.session.scalars(
                select(PublicLawVectorItem)
                .where(
                    PublicLawVectorItem.task_id == task_id,
                    PublicLawVectorItem.status.in_(["PROCESSING", "PENDING"]),
                    PublicLawVectorItem.id.not_in(exclude),
                    PublicLawVectorItem.document_id.is_not(None)
                    if with_document
                    else PublicLawVectorItem.document_id.is_(None),
                )
                .order_by(
                    (PublicLawVectorItem.status == "PROCESSING").desc(),
                    PublicLawVectorItem.sequence,
                )
                .limit(limit)
            )
        )

    async def processing_items(self, task_id: UUID) -> list[PublicLawVectorItem]:
        return list(
            await self.session.scalars(
                select(PublicLawVectorItem)
                .where(
                    PublicLawVectorItem.task_id == task_id,
                    PublicLawVectorItem.status == "PROCESSING",
                )
                .order_by(PublicLawVectorItem.sequence)
            )
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

    async def task_item_status_counts(self, task_id: UUID) -> list[tuple[str, int, int]]:
        rows = await self.session.execute(
            select(
                PublicLawVectorItem.status,
                func.count(),
                func.count().filter(
                    KnowledgeDocument.status == "PUBLISHED",
                    KnowledgeDocument.embedding_status == "COMPLETED",
                    KnowledgeDocument.chunk_count > 0,
                    KnowledgeDocument.embedded_count >= KnowledgeDocument.chunk_count,
                    KnowledgeDocument.deleted_at.is_(None),
                    KnowledgeBase.deleted_at.is_(None),
                ),
            )
            .select_from(PublicLawVectorItem)
            .outerjoin(KnowledgeDocument, KnowledgeDocument.id == PublicLawVectorItem.document_id)
            .outerjoin(KnowledgeBase, KnowledgeBase.id == KnowledgeDocument.knowledge_base_id)
            .where(PublicLawVectorItem.task_id == task_id)
            .group_by(PublicLawVectorItem.status)
        )
        return [(status, total, published) for status, total, published in rows]

    async def item_documents(self, document_ids: Sequence[UUID]) -> list[KnowledgeDocument]:
        if not document_ids:
            return []
        return list(
            await self.session.scalars(
                select(KnowledgeDocument)
                .join(KnowledgeBase, KnowledgeBase.id == KnowledgeDocument.knowledge_base_id)
                .where(
                    KnowledgeDocument.id.in_(document_ids),
                    KnowledgeDocument.deleted_at.is_(None),
                    KnowledgeBase.deleted_at.is_(None),
                )
                .execution_options(populate_existing=True)
            )
        )

    async def task_view(self, task: PublicLawVectorTask, counts: dict[str, int]) -> VectorTaskView:
        current_rows = (
            await self.session.execute(
                select(PublicLawVectorItem, KnowledgeDocument)
                .outerjoin(
                    KnowledgeDocument, KnowledgeDocument.id == PublicLawVectorItem.document_id
                )
                .where(
                    PublicLawVectorItem.task_id == task.id,
                    PublicLawVectorItem.status == "PROCESSING",
                )
                .order_by(PublicLawVectorItem.sequence)
            )
        ).all()
        recent = await self.session.scalars(
            select(PublicLawVectorItem)
            .where(
                PublicLawVectorItem.task_id == task.id,
                PublicLawVectorItem.status != "PENDING",
            )
            .order_by(PublicLawVectorItem.updated_at.desc(), PublicLawVectorItem.sequence.desc())
            .limit(50)
        )

        def item_view(item: PublicLawVectorItem) -> VectorTaskItemView:
            return VectorTaskItemView.model_validate(item, from_attributes=True)

        current_items = [
            item_view(item).model_copy(
                update={
                    "stage": document.processing_stage if document else "IMPORTING",
                    "embedded_count": document.embedded_count if document else 0,
                    "chunk_count": document.chunk_count if document else 0,
                }
            )
            for item, document in current_rows
        ]
        current = current_items[0] if current_items else None
        return VectorTaskView(
            id=task.id,
            status=task.status,
            knowledge_base_id=task.knowledge_base_id,
            request_mode=task.request_mode,
            concurrency=task.concurrency,
            download_delay_ms=task.download_delay_ms,
            total=sum(counts.values()) if task.status == "COMPLETED" else task.total,
            discovered=sum(counts.values()),
            completed=counts.get("COMPLETED", 0),
            skipped=counts.get("SKIPPED", 0),
            failed=counts.get("FAILED", 0),
            current=current,
            current_items=current_items,
            stage=current.stage if current else "SCANNING",
            embedded_count=current.embedded_count if current else 0,
            chunk_count=current.chunk_count if current else 0,
            recent=[item_view(item) for item in recent],
            created_at=task.created_at,
            finished_at=task.finished_at,
        )
