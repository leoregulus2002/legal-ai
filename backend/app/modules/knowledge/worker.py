import asyncio
import hashlib
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

import anyio
from psycopg import Error as PsycopgError
from pydantic import TypeAdapter
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.exceptions import AppError
from app.core.config import Settings
from app.modules.knowledge.chunking import split_document
from app.modules.knowledge.extraction import extract
from app.modules.knowledge.metadata import merge_source_metadata
from app.modules.knowledge.models import KnowledgeDocument, ParseRevision
from app.modules.knowledge.parser import parse
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.knowledge.schemas import LegalStatus, ParseIssue, ParseResult, SourceMetadata
from app.modules.knowledge.service import KnowledgeService, document_state
from app.modules.knowledge.validation import validate_structure
from app.modules.public_laws.repository import PublicLawRepository

logger = logging.getLogger(__name__)


class KnowledgeWorker:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self.sessions, self.settings = sessions, settings

    async def locked(
        self,
        repo: KnowledgeRepository,
        base_id: UUID,
        document_id: UUID,
        token: UUID,
        *,
        allow_stopping: bool = False,
    ) -> KnowledgeDocument | None:
        if not await repo.base(base_id, lock=True):
            return None
        row = await repo.document(document_id, lock=True)
        if row is None or row.processing_token != token:
            return None
        if not allow_stopping and await PublicLawRepository(repo.session).document_stop_requested(
            document_id
        ):
            await KnowledgeService(repo, self.settings).fail_processing(
                row,
                row.processing_stage,
                "任务已停止，已完成的向量已保留",
                code="vector_task_stopped",
            )
            return None
        row.lease_until, row.updated_at = (
            datetime.now(UTC) + timedelta(minutes=10),
            datetime.now(UTC),
        )
        return row

    async def stage(self, base_id: UUID, document_id: UUID, token: UUID, stage: str) -> bool:
        async with self.sessions.begin() as session:
            row = await self.locked(KnowledgeRepository(session), base_id, document_id, token)
            if row is None:
                return False
            row.processing_stage = stage
            row.status_message = {
                "STRUCTURING": "正在结构化法律条文",
                "VALIDATING": "正在校验正文和法律条文结构",
                "CHUNKING": "正在准备检索片段",
            }[stage]
        return True

    async def process(self, document_id: UUID, base_id: UUID, token: UUID) -> None:
        async with self.sessions() as session:
            repo = KnowledgeRepository(session)
            row = await repo.document(document_id)
            if not row or row.processing_token != token:
                return
            filename, mode, data = row.filename, row.mode, await repo.original(document_id)
            source_metadata = (
                SourceMetadata.model_validate(row.source_metadata) if row.source_metadata else None
            )
            snapshot = await repo.snapshot(row.id, row.revision)
            previous = ParseResult.model_validate(snapshot.result) if snapshot else None
            previous_status = TypeAdapter(LegalStatus).validate_python(
                snapshot.review_state.get("legal_status", "UNKNOWN") if snapshot else "UNKNOWN"
            )
        async with asyncio.timeout(240):
            extracted = await anyio.to_thread.run_sync(
                extract,
                filename,
                data,
                self.settings.word_extractor_path,
                self.settings.word_converter_path,
                abandon_on_cancel=True,
            )
        if not await self.stage(base_id, document_id, token, "STRUCTURING"):
            return
        result = await anyio.to_thread.run_sync(parse, extracted, mode)
        merge_source_metadata(result, source_metadata, previous)
        if not await self.stage(base_id, document_id, token, "VALIDATING"):
            return
        result.issues = await anyio.to_thread.run_sync(validate_structure, result, mode)
        async with self.sessions.begin() as session:
            repo = KnowledgeRepository(session)
            row = await self.locked(repo, base_id, document_id, token)
            if row is None:
                return
            row.revision += 1
            revision = row.revision
            row.legal_metadata = result.metadata.model_dump(mode="json")
            if source_metadata and result.metadata_sources.get("legal_status") == "OFFICIAL":
                row.legal_status = source_metadata.legal_status
            elif result.metadata_sources.get("legal_status") == "HUMAN":
                row.legal_status = previous_status
            row.content_hash = hashlib.sha256(result.text.encode()).hexdigest()
            row.chunk_total, row.chunk_count, row.embedded_count = 0, 0, 0
            row.embedding_dimensions, row.embedding_fingerprint = None, None
            await repo.save(
                ParseRevision(
                    document_id=row.id,
                    revision=revision,
                    result=result.model_dump(mode="json"),
                    review_state=document_state(row),
                )
            )
            errors = [issue for issue in result.issues if issue.severity == "ERROR"]
            if errors:
                await KnowledgeService(repo, self.settings).fail_processing(
                    row,
                    "VALIDATING",
                    "数据校验未通过，请修订或重新解析后重试",
                    code="validation_failed",
                    issue_codes=[issue.code for issue in errors],
                )
                return
        if not await self.stage(base_id, document_id, token, "CHUNKING"):
            return
        segments = await anyio.to_thread.run_sync(split_document, result, mode)
        if not segments:
            raise AppError("no_segments", "文档没有可用正文片段，请重新解析")
        for start in range(0, len(segments), 100):
            async with self.sessions.begin() as session:
                repo = KnowledgeRepository(session)
                row = await self.locked(repo, base_id, document_id, token)
                if row is None or row.revision != revision:
                    return
                values = [
                    dict(
                        document_id=document_id,
                        revision=revision,
                        sequence=index + 1,
                        node_id=segment.node_id,
                        start=segment.start,
                        end=segment.end,
                        content=segment.content,
                    )
                    for index, segment in enumerate(segments[start : start + 100], start)
                ]
                await repo.append_segments(values)
                row.chunk_total = len(segments)
                row.chunk_count += len(values)
        async with self.sessions.begin() as session:
            repo = KnowledgeRepository(session)
            row = await self.locked(repo, base_id, document_id, token)
            if row is None:
                return
            if not row.embedding_model_id:
                await KnowledgeService(repo, self.settings).fail_processing(
                    row,
                    "VECTORIZING",
                    "请选择向量模型后重试向量化",
                    code="embedding_model_required",
                )
                return
            row.status, row.processing_stage = "PROCESSING", "VECTORIZING"
            row.status_message = "解析与数据校验完成，等待向量化后自动发布"
            row.processing_token, row.lease_until = None, None
            row.embedding_status, row.embedding_message = "QUEUED", ""
            row.failed_stage = None
            await KnowledgeService(repo, self.settings).audit(
                base_id,
                "PARSE",
                "规则解析与文件切分完成",
                row,
                issues=len(result.issues),
                chunk_count=row.chunk_count,
            )

    async def vectorize(self, document_id: UUID, base_id: UUID, token: UUID) -> None:
        while True:
            async with self.sessions.begin() as session:
                repo = KnowledgeRepository(session)
                row = await self.locked(repo, base_id, document_id, token)
                if row is None:
                    return
                if not row.embedding_model_id:
                    raise AppError("embedding_model_required", "请选择向量模型后重试向量化")
                provider = await KnowledgeService(repo, self.settings).embedding_provider(
                    row.embedding_model_id
                )
                if row.embedding_fingerprint and row.embedding_fingerprint != provider.fingerprint:
                    raise AppError("embedding_changed", "向量模型配置已变更，请重新发起向量化")
                row.embedding_fingerprint = provider.fingerprint
                revision, expected_dimensions = row.revision, row.embedding_dimensions
                batch = await repo.embedding_batch(row, limit=provider.batch_size)
                if not batch:
                    row.embedding_status = "COMPLETED"
                    row.embedding_message = ""
                    row.processing_stage, row.status_message = (
                        "PUBLISHING",
                        "向量化完成，正在自动发布",
                    )
                    await KnowledgeService(repo, self.settings).audit(
                        base_id,
                        "EMBED_COMPLETE",
                        "真实向量化完成",
                        row,
                        completed=row.embedded_count,
                        dimensions=row.embedding_dimensions,
                    )
                values = [(segment.id, segment.content) for segment in batch]
            if not values:
                async with self.sessions.begin() as session:
                    repo = KnowledgeRepository(session)
                    row = await self.locked(repo, base_id, document_id, token)
                    if row is None:
                        return
                    await KnowledgeService(repo, self.settings).auto_publish(row)
                    row.processing_token, row.lease_until = None, None
                return
            vectors = await provider.embed([content for _, content in values])
            if expected_dimensions and len(vectors[0]) != expected_dimensions:
                raise AppError(
                    "embedding_dimensions", "模型返回的向量维度发生变化，请更换模型后重新向量化"
                )
            async with self.sessions.begin() as session:
                repo = KnowledgeRepository(session)
                # 在途请求返回的本批向量先落库；下一轮检查停止，避免恢复时重复调用。
                row = await self.locked(repo, base_id, document_id, token, allow_stopping=True)
                if row is None or row.revision != revision:
                    return
                # 调用期间发生的模型配置修改也不能混入同一批向量。
                current = await KnowledgeService(repo, self.settings).embedding_provider(
                    row.embedding_model_id
                )
                if current.fingerprint != provider.fingerprint:
                    raise AppError("embedding_changed", "向量模型配置已变更，请重新发起向量化")
                for (segment_id, _), vector in zip(values, vectors, strict=True):
                    await repo.write_embedding(segment_id, vector)
                row.embedded_count += len(vectors)
                row.embedding_dimensions = len(vectors[0])

    async def failed(
        self, document_id: UUID, base_id: UUID, token: UUID, task: str, exc: Exception
    ) -> None:
        async with self.sessions.begin() as session:
            repo = KnowledgeRepository(session)
            row = await self.locked(repo, base_id, document_id, token)
            if row is None:
                return
            message = (
                exc.message
                if isinstance(exc, AppError)
                else "处理未完成，原件已保留，请检查文件或配置后重试"
            )
            stage = row.processing_stage
            logger.warning(
                "知识库处理失败 knowledge_base_id=%s document_id=%s task=%s stage=%s "
                "revision=%s embedded_count=%s chunk_count=%s type=%s code=%s",
                base_id,
                document_id,
                task,
                stage,
                row.revision,
                row.embedded_count,
                row.chunk_count,
                type(exc).__name__,
                exc.code if isinstance(exc, AppError) else "unexpected_error",
                exc_info=exc,
            )
            if task == "PARSE" and stage in {"EXTRACTING", "STRUCTURING"}:
                # 原始解析失败也保留独立修订，不覆盖先前成功或失败的快照。
                result = ParseResult(
                    text="",
                    extraction_issues=[
                        ParseIssue(
                            id="processing_failed",
                            code="processing_failed",
                            severity="ERROR",
                            message="文件解析未完成，请查看处理说明并重试",
                        )
                    ],
                )
                snapshot = await repo.snapshot(row.id, row.revision)
                if snapshot:
                    previous = ParseResult.model_validate(snapshot.result)
                    result.metadata = previous.metadata.model_copy(deep=True)
                    result.metadata_sources = previous.metadata_sources.copy()
                    merge_source_metadata(result, None, previous)
                result.issues = result.extraction_issues
                row.revision += 1
                await repo.save(
                    ParseRevision(
                        document_id=row.id,
                        revision=row.revision,
                        result=result.model_dump(mode="json"),
                        review_state=document_state(row),
                    )
                )
                row.chunk_count = row.chunk_total = 0
            await KnowledgeService(repo, self.settings).fail_processing(
                row,
                stage,
                message,
                code=exc.code if isinstance(exc, AppError) else "unexpected_error",
            )

    async def run(self, task_kind: str) -> None:
        while True:
            job = None
            try:
                async with self.sessions.begin() as session:
                    job = await KnowledgeRepository(session).claim(task_kind)
                if job:
                    document_id, base_id, token, task = job
                    try:
                        if task == "PARSE":
                            await self.process(document_id, base_id, token)
                        else:
                            await self.vectorize(document_id, base_id, token)
                    except Exception as exc:
                        logger.warning(
                            "知识库任务失败 task=%s document_id=%s type=%s code=%s",
                            task,
                            document_id,
                            type(exc).__name__,
                            exc.code if isinstance(exc, AppError) else "unexpected_error",
                        )
                        await self.failed(document_id, base_id, token, task, exc)
            except asyncio.CancelledError:
                # 正常退出主动归还租约；进程崩溃则由租约超时恢复。
                if job:
                    document_id, base_id, token, task = job
                    try:
                        async with asyncio.timeout(3), self.sessions.begin() as session:
                            row = await self.locked(
                                KnowledgeRepository(session), base_id, document_id, token
                            )
                            if row:
                                row.processing_token, row.lease_until = None, None
                                if task == "PARSE":
                                    row.status, row.processing_stage = "QUEUED", "QUEUED"
                                else:
                                    row.embedding_status = "QUEUED"
                                    row.processing_stage = "VECTORIZING"
                    except Exception as exc:
                        logger.warning(
                            "知识库退出时归还租约失败 document_id=%s task=%s",
                            document_id,
                            task,
                            exc_info=exc,
                        )
                raise
            except Exception as exc:
                logger.warning(
                    "知识库后台处理暂不可用 task=%s type=%s",
                    task_kind,
                    type(exc).__name__,
                    exc_info=exc,
                )
            await asyncio.sleep(1 if job else 3)

    async def maintain_lexical_index(self) -> None:
        while True:
            delay = 3
            try:
                # 独立 Session 和事务；行锁与版本条件保护撤回、重新发布及多进程补建。
                async with self.sessions.begin() as session:
                    indexed = await KnowledgeService(
                        KnowledgeRepository(session), self.settings
                    ).index_lexical()
                delay = 1 if indexed else 3
            except Exception as exc:
                cause = exc.orig if isinstance(exc, DBAPIError) else None
                sqlstate = cause.sqlstate if isinstance(cause, PsycopgError) else None
                # 日志格式器过滤数据库异常原文和绑定参数，仅保留堆栈与 SQLSTATE。
                if isinstance(exc, ProgrammingError):
                    delay = 60
                if sqlstate in {"42P01", "42703"}:
                    logger.warning(
                        "知识库词频索引缺少数据库表或字段 sqlstate=%s retry_seconds=%d；"
                        "请在 backend 目录执行 uv run alembic upgrade head，"
                        "并确认服务连接同一数据库",
                        sqlstate,
                        delay,
                        exc_info=exc,
                    )
                else:
                    logger.warning(
                        "知识库词频索引补建延迟 type=%s sqlstate=%s retry_seconds=%d",
                        type(exc).__name__,
                        sqlstate or "unknown",
                        delay,
                        exc_info=exc,
                    )
            await asyncio.sleep(delay)
