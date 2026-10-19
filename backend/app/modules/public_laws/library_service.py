import re
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from app.common.exceptions import AppError
from app.modules.knowledge.models import KnowledgeBase, KnowledgeDocument
from app.modules.knowledge.schemas import DocumentActionInput, DocumentDetail, VectorizeInput
from app.modules.knowledge.service import KnowledgeService
from app.modules.public_laws import service as official
from app.modules.public_laws.repository import PublicLawRepository
from app.modules.public_laws.schemas import (
    PublicLaw,
    PublicLawImportInput,
    PublicLawImportResult,
    PublicLawImportState,
    PublicLawMetadataInput,
    PublicLawPage,
    PublicLawSearch,
    VectorizationStatus,
)


def import_state(row: KnowledgeDocument, base: KnowledgeBase) -> PublicLawImportState:
    status: VectorizationStatus
    if row.status == "FAILED" or row.embedding_status == "FAILED":
        status = "FAILED"
    elif row.status in {"QUEUED", "PROCESSING"}:
        status = "PROCESSING" if row.status == "PROCESSING" else "QUEUED"
    elif (
        row.embedding_status == "COMPLETED"
        and row.embedding_model_id
        and row.chunk_count > 0
        and row.embedded_count >= row.chunk_count
    ):
        status = "COMPLETED"
    elif row.embedding_status in {"QUEUED", "PROCESSING"}:
        status = "PROCESSING" if row.embedding_status == "PROCESSING" else "QUEUED"
    else:
        status = "DISABLED"
    return PublicLawImportState(
        law_id=row.public_law_id or "",
        document_id=row.id,
        knowledge_base_id=base.id,
        knowledge_base_name=base.name,
        status=status,
        embedded_count=row.embedded_count,
        chunk_count=row.chunk_count,
    )


class PublicLawLibraryService:
    def __init__(self, repository: PublicLawRepository, knowledge: KnowledgeService) -> None:
        self.repo, self.knowledge = repository, knowledge

    async def states(self, identifiers: list[str]) -> list[PublicLawImportState]:
        return [import_state(row, base) for row, base in await self.repo.imports(identifiers)]

    async def sync_metadata(self, identifier: str, data: PublicLawMetadataInput) -> DocumentDetail:
        row = await self.knowledge.document(data.knowledge_base_id, data.document_id)
        if row.public_law_id != identifier:
            raise AppError("public_law_mismatch", "文档与公开法规的关联不匹配", 409)
        self.knowledge.require_revision(row, data.expected_revision)
        if row.status in {"PUBLISHED", "FAILED"}:
            raise AppError(
                "metadata_sync_unavailable", "请先撤回发布或完成解析，再同步官网信息", 409
            )
        origin = row.source_metadata.get("source_url") or row.source_url
        decision = isinstance(origin, str) and parse_qs(urlsplit(origin).query).get("type") == [
            "decision"
        ]
        law = await official.detail(identifier, decision=decision)
        return await self.knowledge.sync_source_metadata(
            data.knowledge_base_id, data.document_id, data.expected_revision, law.source_metadata
        )

    async def annotate(self, items: list[PublicLaw]) -> None:
        states = await self.states([item.id for item in items])
        priorities = {"COMPLETED": 0, "PROCESSING": 1, "QUEUED": 2, "FAILED": 3, "DISABLED": 4}
        by_law: dict[str, list[PublicLawImportState]] = {}
        for state in states:
            by_law.setdefault(state.law_id, []).append(state)
        for item in items:
            item.imports = sorted(
                by_law.get(item.id, []), key=lambda state: priorities[state.status]
            )
            item.vectorization_status = item.imports[0].status if item.imports else "NOT_IMPORTED"

    async def search(self, query: PublicLawSearch) -> PublicLawPage:
        if query.vectorization == "all":
            result = await official.search(query)
            await self.annotate(result.items)
            return result
        source_page, offset = (1, 0)
        if query.cursor:
            source_page, offset = map(int, query.cursor.split(":"))
        if source_page > 100000:
            raise AppError("invalid_cursor", "分页位置已失效，请重新检索")
        matches: list[PublicLaw] = []
        search_type = query.search_type
        next_cursor: str | None = None
        # 官网不接受本地向量状态；按其排序逐页扫描，并记录精确的下一条位置。
        # 单次最多扫描五页，密集排除时仍可继续翻页，不伪造筛选总数。
        for _ in range(5):
            source = await official.search(
                query.model_copy(
                    update={"page_num": source_page, "page_size": 50, "search_type": search_type}
                )
            )
            search_type = source.search_type
            next_cursor = None
            await self.annotate(source.items)
            for index, item in enumerate(source.items[offset:], offset):
                if item.vectorization_status != "COMPLETED":
                    matches.append(item)
                if len(matches) == query.page_size:
                    if index + 1 < len(source.items):
                        next_cursor = f"{source_page}:{index + 1}"
                    elif source.has_more:
                        next_cursor = f"{source_page + 1}:0"
                    break
            if len(matches) == query.page_size or not source.has_more:
                break
            if not source.items:
                raise official.invalid_response("empty_source_page")
            source_page, offset = source_page + 1, 0
            next_cursor = f"{source_page}:0"
        else:
            next_cursor = f"{source_page}:0"
        return PublicLawPage(
            items=matches,
            total=None,
            page=query.page_num,
            page_size=query.page_size,
            search_type=search_type,
            has_more=next_cursor is not None,
            next_cursor=next_cursor,
        )

    async def import_law(
        self, identifier: str, data: PublicLawImportInput, *, from_task: bool = False
    ) -> PublicLawImportResult:
        if not from_task:
            await self.repo.admission_lock()
            if await self.repo.active_task():
                raise AppError(
                    "vector_task_active", "已有向量化任务，请查看进度或停止后再操作", 409
                )
        await self.knowledge.base(data.knowledge_base_id)
        await self.knowledge.embedding_provider(data.embedding_model_id)
        existing = await self.repo.imports([identifier], data.knowledge_base_id)
        law = None
        content = None
        if not existing:
            law = await official.detail(identifier, decision=data.decision)
            file_format: Literal["docx", "pdf"] = (
                "pdf" if law.preview_formats == ["pdf"] else "docx"
            )
            content = await official.download_file(identifier, file_format)
            if len(content) > 25 * 1024 * 1024:
                raise AppError("document_too_large", "单个文件不能超过 25 MB")
        # 与知识库现有写操作采用相同锁顺序，锁定后再次去重，防止并发重复导入。
        base = await self.knowledge.base(data.knowledge_base_id, lock=True)
        existing = await self.repo.imports([identifier], base.id)
        if existing:
            row = await self.knowledge.document(base.id, existing[0][0].id, lock=True)
            state = import_state(row, base)
            if state.status in {"COMPLETED", "QUEUED", "PROCESSING"}:
                return PublicLawImportResult(state=state, action="EXISTING")
            if (
                not row.chunk_count
                or row.chunk_count != row.chunk_total
                or (
                    row.status == "FAILED" and row.failed_stage not in {"VECTORIZING", "PUBLISHING"}
                )
            ):
                row.embedding_model_id = data.embedding_model_id
                await self.knowledge.reparse(
                    base.id,
                    row.id,
                    DocumentActionInput(
                        expected_revision=row.revision, reason="重试公开法规导入与向量化"
                    ),
                    from_public_task=from_task,
                )
            else:
                await self.knowledge.vectorize(
                    base.id,
                    row.id,
                    VectorizeInput(
                        expected_revision=row.revision,
                        reason="公开法规补充或重试向量化",
                        model_id=data.embedding_model_id,
                    ),
                    from_public_task=from_task,
                )
            return PublicLawImportResult(state=import_state(row, base), action="RETRIED")
        if law is None or content is None:
            raise AppError("import_changed", "导入状态已变化，请重新操作", 409)
        filename = re.sub(r"[\\/\x00-\x1f]", "_", law.title) + f".{file_format}"
        document = await self.knowledge.upload_content(
            base.id,
            filename,
            content,
            "LEGAL",
            law.source_url,
            "从国家法律法规数据库导入；解析、结构化、数据校验及向量化成功后自动发布",
            data.embedding_model_id,
        )
        row = await self.knowledge.document(base.id, document.id)
        row.public_law_id = identifier
        row.source_metadata = law.source_metadata.model_dump(mode="json")
        row.legal_metadata = law.source_metadata.metadata.model_dump(mode="json")
        row.legal_status = law.source_metadata.legal_status
        row.source_kind = "OFFICIAL_VERIFIED"
        row.verification_note = "原件通过国家法律法规数据库官方文件接口获取"
        await self.repo.save(row)
        await self.knowledge.audit(
            base.id,
            "IMPORT_PUBLIC_LAW",
            "导入公开法规并加入解析与向量化队列",
            row,
            public_law_id=identifier,
        )
        return PublicLawImportResult(state=import_state(row, base), action="IMPORTED")
