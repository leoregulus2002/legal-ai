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
from app.modules.public_laws.models import PublicLawVectorTask
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
        jobs: dict[UUID, asyncio.Task[None]] = {}
        try:
            while True:
                for item_id, job in list(jobs.items()):
                    if job.done():
                        del jobs[item_id]
                        job.result()
                query: PublicLawSearch | None = None
                async with self.sessions.begin() as session:
                    repo, knowledge = self.services(session)
                    task = await repo.active_task()
                    if task is None:
                        return
                    task_id = task.id
                    stopping = task.status == "STOPPING"
                    if stopping:
                        if not jobs:
                            await self.finish_items(repo, knowledge, task)
                            await PublicLawTaskService(repo, knowledge).finish(task_id, "STOPPED")
                            return
                        items = []
                    else:
                        await knowledge.base(task.knowledge_base_id)
                        provider = await knowledge.embedding_provider(task.embedding_model_id)
                        if provider.fingerprint != task.embedding_fingerprint:
                            raise AppError(
                                "embedding_changed", "向量模型配置已变更，请停止后重新发起任务"
                            )
                        available = task.concurrency - len(jobs)
                        items = (
                            await repo.next_items(task_id, limit=available, exclude=list(jobs))
                            if available > 0
                            else []
                        )
                        if not items and available > 0:
                            if not task.scan_complete:
                                query = PublicLawSearch.model_validate(task.query).model_copy(
                                    update={"page_num": task.source_page}
                                )
                            elif not jobs:
                                await PublicLawTaskService(repo, knowledge).finish(
                                    task_id, "COMPLETED"
                                )
                                return
                # 单个协调器始终持有跨进程互斥锁；每条法规使用独立 Session。
                for item in items:
                    jobs[item.id] = asyncio.create_task(self.process_item(task_id, item.id))
                if query is not None:
                    await self.scan_page(task_id, query)
                if jobs:
                    await asyncio.wait(
                        jobs.values(), timeout=1, return_when=asyncio.FIRST_COMPLETED
                    )
        finally:
            # 退出协调器前回收全部子任务，避免释放互斥锁后仍有旧任务执行。
            for job in jobs.values():
                job.cancel()
            await asyncio.gather(*jobs.values(), return_exceptions=True)

    async def scan_page(self, task_id: UUID, query: PublicLawSearch) -> None:
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
                offset=(query.page_num - 1) * 50,
                completed=completed,
            )
            task.total = page.total
            task.source_page = query.page_num + 1
            task.scan_complete = not page.has_more
            task.query = query.model_copy(update={"search_type": page.search_type}).model_dump(
                mode="json"
            )

    async def process_item(self, task_id: UUID, item_id: UUID) -> None:
        async with self.sessions.begin() as session:
            repo, _ = self.services(session)
            task = await repo.task(task_id)
            item = await repo.item(item_id)
            if task is None or task.status != "RUNNING" or item is None:
                return
            if item.status not in {"PENDING", "PROCESSING"}:
                return
            law_id, decision = item.law_id, item.decision
            base_id, model_id = task.knowledge_base_id, task.embedding_model_id
            document_id = item.document_id
            if item.status == "PENDING":
                states = await repo.imports([law_id])
                if any(import_state(row, base).status == "COMPLETED" for row, base in states):
                    item.status = "SKIPPED"
                    return
                item.status = "PROCESSING"
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
            task = await repo.task(task_id)
            if task is None or task.status != "RUNNING":
                return
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
            kind = "EMBED" if row.processing_stage in {"VECTORIZING", "PUBLISHING"} else "PARSE"
            job = await knowledge.repo.claim(kind, document_id=document_id)
        if job is None:
            # 进程异常退出后，等待旧租约到期，避免空转争抢同一文档。
            await asyncio.sleep(1)
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

    async def finish_items(
        self,
        repo: PublicLawRepository,
        knowledge: KnowledgeService,
        task: PublicLawVectorTask,
        exc: AppError | None = None,
    ) -> None:
        # 调用前已等待或取消全部在途处理；停止与中断必须覆盖每条并行法规。
        for item in await repo.processing_items(task.id):
            row = None
            if item.document_id:
                await knowledge.repo.base(task.knowledge_base_id, lock=True)
                row = await knowledge.repo.document(item.document_id, lock=True)
                if row and row.status in {"QUEUED", "PROCESSING"}:
                    await knowledge.fail_processing(
                        row,
                        row.processing_stage,
                        "任务已中断，请检查配置后重试" if exc else "任务已停止，已完成的向量已保留",
                        code=exc.code if exc else "vector_task_stopped",
                    )
            if row and row.status == "PUBLISHED" and row.embedding_status == "COMPLETED":
                item.status, item.error_message = "COMPLETED", None
            else:
                item.status = "FAILED" if exc else "STOPPED"
                item.error_message = exc.message if exc else None

    async def abort(self, exc: AppError) -> None:
        async with self.sessions.begin() as session:
            repo, knowledge = self.services(session)
            task = await repo.active_task()
            if task is None:
                return
            await self.finish_items(repo, knowledge, task, exc)
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
