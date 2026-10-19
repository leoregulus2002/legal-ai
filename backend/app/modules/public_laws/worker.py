import asyncio
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.exceptions import AppError
from app.core.config import Settings
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.knowledge.service import KnowledgeService
from app.modules.knowledge.worker import KnowledgeWorker
from app.modules.public_laws import service as official
from app.modules.public_laws.library_service import PublicLawLibraryService, import_state
from app.modules.public_laws.repository import PublicLawRepository
from app.modules.public_laws.schemas import PublicLawImportInput, PublicLawSearch, VectorTaskLaw
from app.modules.public_laws.task_service import PublicLawTaskService

logger = logging.getLogger(__name__)


class PublicLawVectorWorker:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self.sessions, self.settings = sessions, settings
        self.knowledge_worker = KnowledgeWorker(sessions, settings)

    def services(self, session: AsyncSession) -> tuple[PublicLawRepository, KnowledgeService]:
        return PublicLawRepository(session), KnowledgeService(
            KnowledgeRepository(session), self.settings
        )

    async def tick(self) -> None:
        async with self.sessions.begin() as session:
            repo, knowledge = self.services(session)
            task = await repo.active_task()
            if task is None:
                return
            task_id = task.id
            item = await repo.next_item(task_id)
            if task.status == "STOPPING":
                if item and item.document_id and item.status == "PROCESSING":
                    await knowledge.repo.base(task.knowledge_base_id, lock=True)
                    row = await knowledge.repo.document(item.document_id, lock=True)
                    # 已持有执行互斥锁，此时本任务没有仍在执行的处理步骤。
                    if row and row.status in {"QUEUED", "PROCESSING"}:
                        await knowledge.fail_processing(
                            row,
                            row.processing_stage,
                            "任务已停止，已完成的向量已保留",
                            code="vector_task_stopped",
                        )
                    item.status = "COMPLETED" if row and row.status == "PUBLISHED" else "STOPPED"
                elif item and item.status == "PROCESSING":
                    item.status = "STOPPED"
                await PublicLawTaskService(repo, knowledge).finish(task_id, "STOPPED")
                return
            await knowledge.base(task.knowledge_base_id)
            if item is None or item.document_id is None:
                provider = await knowledge.embedding_provider(task.embedding_model_id)
                if provider.fingerprint != task.embedding_fingerprint:
                    raise AppError("embedding_changed", "向量模型配置已变更，请停止后重新发起任务")
            if item is None:
                if task.scan_complete:
                    await PublicLawTaskService(repo, knowledge).finish(task_id, "COMPLETED")
                    return
                query = PublicLawSearch.model_validate(task.query).model_copy(
                    update={"page_num": task.source_page}
                )
                source_page = task.source_page
            else:
                item_id, law_id, decision = item.id, item.law_id, item.decision
                base_id, model_id = task.knowledge_base_id, task.embedding_model_id
                document_id = item.document_id
                if item.status == "PENDING":
                    states = await repo.imports([law_id])
                    if any(import_state(row, base).status == "COMPLETED" for row, base in states):
                        item.status = "SKIPPED"
                        return
                    item.status = "PROCESSING"
        if item is None:
            # 不在任务行上持锁进行网络请求，停止请求可立即落库。
            page = await official.search(query)
            if not page.items and page.has_more:
                raise official.invalid_response("empty_source_page")
            async with self.sessions.begin() as session:
                repo, _ = self.services(session)
                task = await repo.task(task_id, lock=True)
                if task is None or task.status != "RUNNING":
                    return
                states = await repo.imports([law.id for law in page.items])
                completed = {
                    row.public_law_id
                    for row, base in states
                    if row.public_law_id and import_state(row, base).status == "COMPLETED"
                }
                await repo.add_items(
                    task_id,
                    [
                        VectorTaskLaw(
                            id=law.id,
                            title=law.title,
                            decision=law.category == "修改、废止的决定",
                        )
                        for law in page.items
                    ],
                    offset=(source_page - 1) * 50,
                    completed=completed,
                )
                task.total = page.total
                task.source_page = source_page + 1
                task.scan_complete = not page.has_more
                task.query = query.model_copy(update={"search_type": page.search_type}).model_dump(
                    mode="json"
                )
            return
        if document_id is None:
            try:
                async with self.sessions.begin() as session:
                    repo, knowledge = self.services(session)
                    task = await repo.task(task_id)
                    if task is None or task.status != "RUNNING":
                        return
                    result = await PublicLawLibraryService(repo, knowledge).import_law(
                        law_id,
                        PublicLawImportInput(
                            knowledge_base_id=base_id,
                            embedding_model_id=model_id,
                            decision=decision,
                        ),
                        from_task=True,
                    )
                    item = await repo.item(item_id)
                    if item:
                        item.document_id = result.state.document_id
            except Exception as exc:
                await self.item_failed(item_id, exc)
            return
        await self.process_document(task_id, item_id, document_id, base_id)

    async def process_document(
        self, task_id: UUID, item_id: UUID, document_id: UUID, base_id: UUID
    ) -> None:
        async with self.sessions.begin() as session:
            repo, knowledge = self.services(session)
            row = await knowledge.repo.document(document_id)
            item = await repo.item(item_id)
            if item is None:
                return
            if row is None:
                item.status, item.error_message = "FAILED", "文档已移除，请重新发起任务"
                return
            if row.status == "PUBLISHED" and row.embedding_status == "COMPLETED":
                item.status = "COMPLETED"
                return
            if row.status == "FAILED":
                item.status, item.error_message = "FAILED", "此法规未完成处理，请查看文档后重试"
                return
            task = await repo.task(task_id)
            if task is None or task.status != "RUNNING":
                return
            kind = "EMBED" if row.processing_stage in {"VECTORIZING", "PUBLISHING"} else "PARSE"
            job = await knowledge.repo.claim(kind, document_id=document_id)
        if job is None:
            return
        _, _, token, kind = job
        try:
            if kind == "PARSE":
                await self.knowledge_worker.process(document_id, base_id, token)
            else:
                await self.knowledge_worker.vectorize(document_id, base_id, token)
        except asyncio.CancelledError:
            async with self.sessions.begin() as session:
                row = await self.knowledge_worker.locked(
                    KnowledgeRepository(session), base_id, document_id, token
                )
                if row:
                    row.processing_token, row.lease_until = None, None
                    if kind == "PARSE":
                        row.status, row.processing_stage = "QUEUED", "QUEUED"
                    else:
                        row.embedding_status = "QUEUED"
            raise
        except Exception as exc:
            logger.warning(
                "公开法规处理失败 document_id=%s type=%s", document_id, type(exc).__name__
            )
            await self.knowledge_worker.failed(document_id, base_id, token, kind, exc)

    async def item_failed(self, item_id: UUID, exc: Exception) -> None:
        logger.warning("公开法规导入失败 item_id=%s type=%s", item_id, type(exc).__name__)
        async with self.sessions.begin() as session:
            repo, _ = self.services(session)
            item = await repo.item(item_id)
            if item:
                item.status = "FAILED"
                item.error_message = (
                    exc.message if isinstance(exc, AppError) else "此法规导入未完成，请稍后重试"
                )

    async def abort(self, exc: AppError) -> None:
        async with self.sessions.begin() as session:
            repo, knowledge = self.services(session)
            task = await repo.active_task()
            if task is None:
                return
            item = await repo.next_item(task.id)
            if item and item.status == "PROCESSING":
                if item.document_id:
                    await knowledge.repo.base(task.knowledge_base_id, lock=True)
                    row = await knowledge.repo.document(item.document_id, lock=True)
                    if row and row.status in {"QUEUED", "PROCESSING"}:
                        await knowledge.fail_processing(
                            row,
                            row.processing_stage,
                            "任务已中断，请检查配置后重试",
                            code=exc.code,
                        )
                item.status, item.error_message = "FAILED", exc.message
            await PublicLawTaskService(repo, knowledge).finish(task.id, "FAILED")

    async def run(self) -> None:
        while True:
            try:
                # 跨进程执行互斥；锁会在连接关闭或进程退出后自动释放。
                async with self.sessions.begin() as guard:
                    if await PublicLawRepository(guard).worker_lock():
                        try:
                            await self.tick()
                        except AppError as exc:
                            logger.warning("公开法规任务已暂停 code=%s", exc.code)
                            await self.abort(exc)
                        except Exception as exc:
                            logger.warning("公开法规向量化暂不可用 type=%s", type(exc).__name__)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("公开法规向量化后台暂不可用 type=%s", type(exc).__name__)
            await asyncio.sleep(1)
