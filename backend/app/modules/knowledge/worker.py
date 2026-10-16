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
from app.modules.knowledge.service import KnowledgeService, ready_status, review_state
from app.modules.knowledge.validation import validate_structure

logger = logging.getLogger(__name__)


class KnowledgeWorker:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self.sessions, self.settings = sessions, settings

    async def locked(
        self, repo: KnowledgeRepository, base_id: UUID, document_id: UUID, token: UUID
    ) -> KnowledgeDocument | None:
        if not await repo.base(base_id, lock=True):
            return None
        row = await repo.document(document_id, lock=True)
        if row is None or row.processing_token != token:
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
                extract, filename, data, abandon_on_cancel=True
            )
        if not await self.stage(base_id, document_id, token, "STRUCTURING"):
            return
        result = await anyio.to_thread.run_sync(parse, extracted, mode)
        merge_source_metadata(result, source_metadata, previous)
        result.issues = await anyio.to_thread.run_sync(validate_structure, result, mode)
        if not await self.stage(base_id, document_id, token, "CHUNKING"):
            return
        segments = await anyio.to_thread.run_sync(split_document, result, mode)
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
            row.chunk_total, row.chunk_count, row.embedded_count = len(segments), 0, 0
            row.embedding_dimensions, row.embedding_fingerprint = None, None
            await repo.save(
                ParseRevision(
                    document_id=row.id,
                    revision=revision,
                    result=result.model_dump(mode="json"),
                    review_state=review_state(row),
                    acknowledged_issues=[],
                )
            )
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
                row.chunk_count += len(values)
        async with self.sessions.begin() as session:
            repo = KnowledgeRepository(session)
            row = await self.locked(repo, base_id, document_id, token)
            if row is None:
                return
            row.status = ready_status(result, [])
            row.processing_stage, row.status_message = "COMPLETED", "解析及切分完成，等待人工审核"
            row.processing_token, row.lease_until = None, None
            row.embedding_status = "QUEUED" if row.embedding_model_id and segments else "DISABLED"
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
                if row is None or not row.embedding_model_id:
                    return
                provider = await KnowledgeService(repo, self.settings).embedding_provider(
                    row.embedding_model_id
                )
                if row.embedding_fingerprint and row.embedding_fingerprint != provider.fingerprint:
                    raise AppError("embedding_changed", "向量模型配置已变更，请重新发起向量化")
                row.embedding_fingerprint = provider.fingerprint
                revision, expected_dimensions = row.revision, row.embedding_dimensions
                batch = await repo.embedding_batch(row, limit=provider.batch_size)
                if not batch:
                    row.embedding_status, row.processing_stage = "COMPLETED", "COMPLETED"
                    row.embedding_message, row.processing_token, row.lease_until = "", None, None
                    await KnowledgeService(repo, self.settings).audit(
                        base_id,
                        "EMBED_COMPLETE",
                        "真实向量化完成",
                        row,
                        completed=row.embedded_count,
                        dimensions=row.embedding_dimensions,
                    )
                    return
                values = [(segment.id, segment.content) for segment in batch]
            vectors = await provider.embed([content for _, content in values])
            if expected_dimensions and len(vectors[0]) != expected_dimensions:
                raise AppError(
                    "embedding_dimensions", "模型返回的向量维度发生变化，请更换模型后重新向量化"
                )
            async with self.sessions.begin() as session:
                repo = KnowledgeRepository(session)
                row = await self.locked(repo, base_id, document_id, token)
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
            row.processing_token, row.lease_until, row.processing_stage = None, None, "FAILED"
            if task == "PARSE":
                row.status, row.status_message = "FAILED", message
                row.embedding_status = "DISABLED" if not row.embedding_model_id else "FAILED"
                # 保留失败快照，上一轮成功或部分解析快照亦不覆盖。
                result = ParseResult(
                    text="",
                    extraction_issues=[
                        ParseIssue(
                            id="extraction_failed",
                            code="extraction_failed",
                            severity="ERROR",
                            message=message,
                        )
                    ],
                )
                snapshot = await repo.snapshot(row.id, row.revision)
                if snapshot:
                    previous = ParseResult.model_validate(snapshot.result)
                    result.metadata = previous.metadata.model_copy(deep=True)
                    result.metadata_sources = previous.metadata_sources.copy()
                    merge_source_metadata(result, None, previous)
                failure_review_state = review_state(row)
                if snapshot and result.metadata_sources.get("legal_status") == "HUMAN":
                    failure_review_state["legal_status"] = snapshot.review_state.get(
                        "legal_status", "UNKNOWN"
                    )
                result.issues = result.extraction_issues
                row.revision += 1
                await repo.save(
                    ParseRevision(
                        document_id=row.id,
                        revision=row.revision,
                        result=result.model_dump(mode="json"),
                        review_state=failure_review_state,
                        acknowledged_issues=[],
                    )
                )
                row.chunk_count = row.chunk_total = 0
            else:
                row.embedding_status, row.embedding_message = "FAILED", message
            await KnowledgeService(repo, self.settings).audit(
                base_id, f"{task}_FAILED", message, row
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
                    except Exception:
                        logger.warning("知识库退出时归还租约失败")
                raise
            except Exception as exc:
                logger.warning("知识库后台处理暂不可用 type=%s", type(exc).__name__)
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
                # 不输出 SQL、绑定参数或异常原文，避免把资料和凭据带入日志。
                if isinstance(exc, ProgrammingError):
                    delay = 60
                if sqlstate in {"42P01", "42703"}:
                    logger.warning(
                        "知识库词频索引缺少数据库表或字段 sqlstate=%s retry_seconds=%d；"
                        "请在 backend 目录执行 uv run alembic upgrade head，"
                        "并确认服务连接同一数据库",
                        sqlstate,
                        delay,
                    )
                else:
                    logger.warning(
                        "知识库词频索引补建延迟 type=%s sqlstate=%s retry_seconds=%d",
                        type(exc).__name__,
                        sqlstate or "unknown",
                        delay,
                    )
            await asyncio.sleep(delay)
