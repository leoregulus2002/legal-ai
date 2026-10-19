from datetime import UTC, datetime
from uuid import UUID

from app.common.exceptions import AppError
from app.modules.knowledge.service import KnowledgeService
from app.modules.public_laws.models import PublicLawVectorTask
from app.modules.public_laws.repository import PublicLawRepository
from app.modules.public_laws.schemas import VectorTaskInput, VectorTaskView
from app.modules.system_config.repository import ConfigRepository
from app.modules.system_config.service import ConfigService


class PublicLawTaskService:
    def __init__(self, repo: PublicLawRepository, knowledge: KnowledgeService) -> None:
        self.repo, self.knowledge = repo, knowledge

    async def latest(self) -> VectorTaskView | None:
        task = await self.repo.latest_task()
        return await self.view(task) if task else None

    async def view(self, task: PublicLawVectorTask) -> VectorTaskView:
        historical_failures = ("FAILED", "STOPPED")
        counts: dict[str, int] = {}
        for status, total, published in await self.repo.task_item_status_counts(task.id):
            recovered = published if status in historical_failures else 0
            counts[status] = counts.get(status, 0) + total - recovered
            counts["COMPLETED"] = counts.get("COMPLETED", 0) + recovered
        result = await self.repo.task_view(task, counts)
        candidates = [item for item in result.recent if item.status in historical_failures]
        documents = {
            row.id: row
            for row in await self.repo.item_documents(
                [item.document_id for item in candidates if item.document_id]
            )
        }
        for item in candidates:
            document = documents.get(item.document_id) if item.document_id else None
            if (
                document
                and document.status == "PUBLISHED"
                and document.embedding_status == "COMPLETED"
                and document.chunk_count > 0
                and document.embedded_count >= document.chunk_count
            ):
                # 只修正当前展示；任务当时的失败状态与错误记录保持原样。
                item.status, item.error_message, item.stage = "COMPLETED", None, "COMPLETED"
                item.embedded_count, item.chunk_count = (
                    document.embedded_count,
                    document.chunk_count,
                )
        return result

    async def start(self, data: VectorTaskInput) -> VectorTaskView:
        await self.repo.admission_lock()
        if await self.repo.active_task():
            raise AppError("vector_task_active", "已有向量化任务，请查看进度或停止后再操作", 409)
        if await self.repo.has_processing_laws():
            raise AppError("public_laws_processing", "已有公开法规正在处理，请完成后再开始", 409)
        await self.knowledge.base(data.knowledge_base_id)
        provider = await self.knowledge.embedding_provider(data.embedding_model_id)
        configuration = await ConfigService(
            ConfigRepository(self.repo.session), self.knowledge.settings
        ).vectorization()
        query = (
            data.query.model_copy(
                update={
                    "page_num": 1,
                    "page_size": 50,
                    "cursor": None,
                    "vectorization": "all",
                }
            )
            if data.query
            else None
        )
        task = PublicLawVectorTask(
            knowledge_base_id=data.knowledge_base_id,
            embedding_model_id=data.embedding_model_id,
            concurrency=configuration.concurrency,
            embedding_fingerprint=provider.fingerprint,
            query=query.model_dump(mode="json") if query else None,
            total=None if query else len({law.id for law in data.laws}),
            scan_complete=query is None,
        )
        await self.repo.add_task(task)
        await self.repo.add_items(task.id, data.laws)
        return await self.view(task)

    async def stop(self, task_id: UUID) -> VectorTaskView:
        task = await self.repo.task(task_id, lock=True)
        if task is None:
            raise AppError("vector_task_missing", "向量化任务不存在", 404)
        if task.status == "RUNNING":
            task.status = "STOPPING"
        return await self.view(task)

    async def finish(self, task_id: UUID, status: str) -> None:
        task = await self.repo.task(task_id, lock=True)
        if task and task.status in {"RUNNING", "STOPPING"}:
            task.status = "STOPPED" if task.status == "STOPPING" else status
            task.finished_at = datetime.now(UTC)
