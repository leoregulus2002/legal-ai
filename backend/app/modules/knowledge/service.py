import difflib
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import anyio
from fastapi import UploadFile

from app.ai.embeddings.client import EmbeddingProvider
from app.common.exceptions import AppError
from app.core.config import Settings
from app.core.secrets import decrypt
from app.modules.knowledge.chunking import split_document
from app.modules.knowledge.extraction import MEDIA_TYPES
from app.modules.knowledge.metadata import has_metadata_value, merge_source_metadata
from app.modules.knowledge.models import (
    KnowledgeAudit,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    ParseRevision,
)
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.knowledge.retrieval import (
    CANDIDATE_LIMIT,
    lexical_indexes,
    query_terms,
    reciprocal_rank_fusion,
)
from app.modules.knowledge.schemas import (
    AuditView,
    ComparisonView,
    CorrectionInput,
    DocumentDetail,
    DocumentPage,
    DocumentView,
    KnowledgeInput,
    KnowledgePage,
    KnowledgeView,
    LegalMetadata,
    ParseResult,
    ReviewInput,
    SearchHit,
    SearchPage,
    SegmentPage,
    SegmentView,
    SourceMetadata,
    VectorizeInput,
    VersionCandidate,
)
from app.modules.knowledge.validation import validate_structure
from app.modules.system_config.models import ModelConfig
from app.modules.system_config.repository import ConfigRepository
from app.modules.system_config.schemas import Policy


def document_view(row: KnowledgeDocument) -> DocumentView:
    values = {
        name: getattr(row, name)
        for name in DocumentView.model_fields
        if name not in {"metadata", "source_metadata"}
    }
    return DocumentView(
        **values,
        metadata=LegalMetadata.model_validate(row.legal_metadata),
        source_metadata=SourceMetadata.model_validate(row.source_metadata)
        if row.source_metadata
        else None,
    )


def review_state(row: KnowledgeDocument) -> dict[str, object]:
    return {
        name: getattr(row, name)
        for name in (
            "source_kind",
            "source_url",
            "source_note",
            "verification_note",
            "legal_status",
            "version_confirmed",
        )
    }


def check_reason(value: str) -> str:
    if not value.strip():
        raise AppError("reason_required", "请填写本次操作说明")
    return value.strip()


def validate_source_url(value: str) -> str:
    value = value.strip()
    if value:
        try:
            parsed = urlsplit(value)
            valid = parsed.scheme in {"https", "http"} and bool(parsed.hostname)
            valid = valid and not parsed.username and not parsed.password
        except ValueError:
            valid = False
        if not valid:
            raise AppError("invalid_source_url", "来源地址请使用不含凭据的 HTTP 或 HTTPS 地址")
    return value


def ready_status(result: ParseResult, acknowledgements: list[str]) -> str:
    if any(
        issue.severity == "ERROR" or issue.id not in acknowledgements for issue in result.issues
    ):
        return "NEEDS_REVIEW"
    return "READY"


class KnowledgeService:
    def __init__(self, repository: KnowledgeRepository, settings: Settings) -> None:
        self.repo, self.settings = repository, settings

    async def base(self, base_id: UUID, *, lock: bool = False) -> KnowledgeBase:
        row = await self.repo.base(base_id, lock=lock)
        if row is None:
            raise AppError("knowledge_not_found", "知识库不存在或已删除", 404)
        return row

    async def document(
        self, base_id: UUID, document_id: UUID, *, lock: bool = False
    ) -> KnowledgeDocument:
        await self.base(base_id, lock=lock)
        row = await self.repo.document(document_id, lock=lock)
        if row is None or row.knowledge_base_id != base_id:
            raise AppError("document_not_found", "文档不存在或已删除", 404)
        return row

    async def audit(
        self,
        base_id: UUID,
        action: str,
        reason: str,
        row: KnowledgeDocument | None = None,
        **details: object,
    ) -> None:
        await self.repo.save(
            KnowledgeAudit(
                knowledge_base_id=base_id,
                document_id=row.id if row else None,
                action=action,
                reason=reason,
                revision=row.revision if row else None,
                details=details,
            )
        )

    async def bases(self, query: str, page: int, page_size: int) -> KnowledgePage:
        rows, total = await self.repo.bases(query.strip(), page, page_size)
        return KnowledgePage(
            items=[KnowledgeView.model_validate(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def save_base(self, data: KnowledgeInput, base_id: UUID | None = None) -> KnowledgeView:
        row = await self.base(base_id, lock=True) if base_id else KnowledgeBase()
        before = {"name": row.name, "description": row.description} if base_id else None
        row.name, row.description, row.updated_at = data.name, data.description, datetime.now(UTC)
        await self.repo.save(row)
        await self.audit(
            row.id,
            "UPDATE_BASE" if base_id else "CREATE_BASE",
            "修改知识库" if base_id else "创建知识库",
            before=before,
            after=data.model_dump(),
        )
        return KnowledgeView.model_validate(row)

    async def delete_base(self, base_id: UUID) -> None:
        row = await self.base(base_id, lock=True)
        await self.repo.remove_base(row)
        await self.audit(base_id, "DELETE_BASE", "删除知识库及全部正式索引，原件与审计留存")

    async def documents(
        self, base_id: UUID, query: str, status: str | None, page: int, page_size: int
    ) -> DocumentPage:
        await self.base(base_id)
        rows, total = await self.repo.documents(base_id, query.strip(), status, page, page_size)
        return DocumentPage(
            items=[document_view(row) for row in rows], total=total, page=page, page_size=page_size
        )

    @staticmethod
    def configured_provider(model: ModelConfig, api_key: str) -> EmbeddingProvider:
        return EmbeddingProvider(
            base_url=model.base_url,
            model_name=model.model_name,
            api_key=api_key,
            protocol="dashscope_embeddings"
            if model.protocol == "dashscope_embeddings"
            else "openai_embeddings",
            dimensions=model.embedding_dimensions,
            batch_size=model.embedding_batch_size,
            timeout=model.embedding_timeout,
            max_input_tokens=model.context_tokens,
            query_instruction=model.embedding_query_instruction,
        )

    async def embedding_provider(self, model_id: UUID) -> EmbeddingProvider:
        model = await ConfigRepository(self.repo.session).model(model_id)
        if model is None or not model.enabled or model.model_type != "embedding":
            raise AppError("embedding_model_required", "请选择已启用的 Embedding 模型")
        return self.configured_provider(model, decrypt(model.api_key_encrypted, self.settings))

    async def upload(
        self,
        base_id: UUID,
        upload: UploadFile,
        mode: str,
        source_url: str,
        source_note: str,
        model_id: UUID | None,
    ) -> DocumentView:
        # 大文件读取不占用知识库行锁，保存时再检查删除竞态。
        await self.base(base_id)
        data = bytearray()
        while chunk := await upload.read(65536):
            data.extend(chunk)
            if len(data) > 25 * 1024 * 1024:
                raise AppError("document_too_large", "单个文件不能超过 25 MB")
        return await self.upload_content(
            base_id,
            upload.filename or "document.txt",
            bytes(data),
            mode,
            source_url,
            source_note,
            model_id,
        )

    async def upload_content(
        self,
        base_id: UUID,
        filename: str,
        data: bytes,
        mode: str,
        source_url: str,
        source_note: str,
        model_id: UUID | None,
    ) -> DocumentView:
        filename = Path(filename.replace("\\", "/")).name
        suffix = Path(filename).suffix.lower()
        if suffix not in MEDIA_TYPES:
            raise AppError("unsupported_document", "支持 PDF、DOCX、TXT、Markdown 和 HTML 文件")
        filename = filename[: 240 - len(suffix)] + suffix if len(filename) > 240 else filename
        if len(data) > 25 * 1024 * 1024:
            raise AppError("document_too_large", "单个文件不能超过 25 MB")
        if not data:
            raise AppError("empty_document", "文件为空，请重新选择")
        if model_id:
            await self.embedding_provider(model_id)
        await self.base(base_id, lock=True)
        file_hash = hashlib.sha256(data).hexdigest()
        duplicate = await self.repo.same_hash(base_id, file_hash)
        row = KnowledgeDocument(
            knowledge_base_id=base_id,
            filename=filename,
            media_type=MEDIA_TYPES[suffix],
            size=len(data),
            original_bytes=bytes(data),
            mode=mode,
            file_hash=file_hash,
            duplicate_of=duplicate,
            source_url=validate_source_url(source_url),
            source_note=source_note.strip(),
            embedding_model_id=model_id,
            embedding_status="QUEUED" if model_id else "DISABLED",
        )
        await self.repo.save(row)
        await self.audit(
            base_id,
            "UPLOAD",
            "上传文档，来源默认待核验的用户上传资料",
            row,
            file_hash=file_hash,
            duplicate_of=str(duplicate) if duplicate else None,
        )
        return document_view(row)

    async def detail(
        self, base_id: UUID, document_id: UUID, revision: int | None = None
    ) -> DocumentDetail:
        row = await self.document(base_id, document_id)
        snapshot = await self.repo.snapshot(
            row.id, revision if revision is not None else row.revision
        )
        if revision is not None and snapshot is None:
            raise AppError("revision_not_found", "解析修订不存在", 404)
        return DocumentDetail(
            document=document_view(row),
            result=ParseResult.model_validate(snapshot.result) if snapshot else None,
            acknowledged_issues=snapshot.acknowledged_issues if snapshot else [],
        )

    async def original(self, base_id: UUID, document_id: UUID) -> tuple[KnowledgeDocument, bytes]:
        row = await self.document(base_id, document_id)
        return row, await self.repo.original(row.id)

    async def delete_document(self, base_id: UUID, document_id: UUID) -> None:
        row = await self.document(base_id, document_id, lock=True)
        await self.repo.clear_published(row.id)
        row.deleted_at, row.published_at, row.processing_token, row.lease_until = (
            datetime.now(UTC),
            None,
            None,
            None,
        )
        await self.audit(base_id, "DELETE_DOCUMENT", "删除文档并移出正式搜索，原件与历史留存", row)

    def require_revision(self, row: KnowledgeDocument, expected: int) -> None:
        if row.revision != expected:
            raise AppError("revision_conflict", "文档已更新，请刷新后再操作", 409)
        if (
            row.processing_token
            or row.status in {"QUEUED", "PROCESSING"}
            or row.embedding_status in {"QUEUED", "PROCESSING"}
        ):
            raise AppError("processing_conflict", "文档正在处理中，请完成后再操作", 409)

    async def invalidate(self, row: KnowledgeDocument) -> None:
        await self.repo.clear_published(row.id)
        row.published_at = None
        row.updated_at = datetime.now(UTC)

    async def correct(
        self,
        base_id: UUID,
        document_id: UUID,
        data: CorrectionInput,
        *,
        source_update: SourceMetadata | None = None,
    ) -> DocumentDetail:
        row = await self.document(base_id, document_id, lock=True)
        self.require_revision(row, data.expected_revision)
        reason = check_reason(data.reason)
        previous = await self.repo.snapshot(row.id, row.revision)
        if previous is None:
            raise AppError("parse_required", "请先重新解析文档")
        result = ParseResult.model_validate(previous.result)
        if source_update:
            previous_result = result.model_copy(deep=True)
            merge_source_metadata(result, source_update, previous_result)
            status = row.legal_status
            if result.metadata_sources.get("legal_status") == "OFFICIAL":
                status = source_update.legal_status
            data = data.model_copy(update={"metadata": result.metadata, "legal_status": status})
            row.source_metadata = source_update.model_dump(mode="json")
        else:
            if result.method == "HUMAN" and not result.metadata_sources:
                result.metadata_sources = {
                    field: "HUMAN"
                    for field, value in result.metadata.model_dump().items()
                    if has_metadata_value(field, value)
                }
                result.metadata_sources["legal_status"] = "HUMAN"
            changed = {
                field
                for field in LegalMetadata.model_fields
                if getattr(data.metadata, field) != getattr(result.metadata, field)
            }
            for field in changed:
                result.metadata_sources[field] = "HUMAN"
            if data.legal_status != row.legal_status:
                result.metadata_sources["legal_status"] = "HUMAN"
            result.anchors = [anchor for anchor in result.anchors if anchor.field not in changed]
            result.method = "HUMAN"
        result.metadata, result.nodes = data.metadata, data.nodes
        result.issues = validate_structure(result, row.mode)
        # 无效区间/层级不保存为可用结构，其他重大识别问题允许保留待修订。
        if not source_update and any(
            issue.code
            in {
                "duplicate_node_id",
                "invalid_range",
                "invalid_hierarchy",
                "missing_parent",
                "label_mismatch",
            }
            for issue in result.issues
        ):
            raise AppError("invalid_structure", "结构边界、标签或归属无效，请对照原文调整")
        if (
            not source_update
            and data.source_kind == "OFFICIAL_VERIFIED"
            and (not data.verification_note.strip() or not data.source_url.strip())
        ):
            raise AppError("verification_required", "官方核验需填写官方来源地址及核验说明")
        if (
            not source_update
            and data.legal_status == "EFFECTIVE"
            and (data.legal_status != row.legal_status or data.version_confirmed)
            and (
                not data.version_confirmed
                or not data.metadata.version_label.strip()
                or not data.metadata.title.strip()
                or not data.metadata.authority.strip()
                or not data.metadata.promulgated_on
                or not data.metadata.effective_on
                or data.metadata.effective_on > datetime.now(UTC).date()
            )
        ):
            raise AppError(
                "incomplete_version",
                "标记现行有效前，请确认版本并补全名称、机关、版本说明及有效日期",
            )
        before = review_state(row)
        for field in before:
            setattr(row, field, getattr(data, field))
        row.source_url = validate_source_url(data.source_url)
        await self.invalidate(row)
        row.revision += 1
        row.legal_metadata = result.metadata.model_dump(mode="json")
        valid_warnings = {issue.id for issue in result.issues if issue.severity == "WARNING"}
        acknowledgements = sorted(valid_warnings.intersection(data.acknowledged_issues))
        row.status = ready_status(result, acknowledgements)
        row.status_message = (
            "官网信息已同步，等待审核发布" if source_update else "人工修订已保存，等待审核发布"
        )
        row.processing_stage = "COMPLETED"
        await self.repo.save(
            ParseRevision(
                document_id=row.id,
                revision=row.revision,
                result=result.model_dump(mode="json"),
                review_state=review_state(row),
                acknowledged_issues=acknowledgements,
            )
        )
        segments = await anyio.to_thread.run_sync(split_document, result, row.mode)
        await self.repo.replace_segments(
            row.id,
            row.revision,
            [
                dict(
                    document_id=row.id,
                    revision=row.revision,
                    sequence=index,
                    node_id=segment.node_id,
                    start=segment.start,
                    end=segment.end,
                    content=segment.content,
                )
                for index, segment in enumerate(segments, 1)
            ],
        )
        row.chunk_count = row.chunk_total = len(segments)
        row.embedded_count = await self.repo.reuse_embeddings(
            row.id, data.expected_revision, row.revision
        )
        previous_embedding_status = row.embedding_status
        if source_update and previous_embedding_status == "FAILED":
            row.embedding_status = "FAILED"
        elif row.embedding_model_id and segments:
            row.embedding_status = "COMPLETED" if row.embedded_count == len(segments) else "QUEUED"
        else:
            row.embedding_status = "DISABLED"
        if row.embedding_status == "COMPLETED":
            row.embedding_message = ""
        await self.audit(
            base_id,
            "SYNC_SOURCE_METADATA" if source_update else "CORRECT",
            reason,
            row,
            before=before,
            after=review_state(row),
            acknowledged_issues=acknowledgements,
            previous_revision=data.expected_revision,
        )
        await self.repo.session.flush()
        return await self.detail(base_id, row.id)

    async def sync_source_metadata(
        self, base_id: UUID, document_id: UUID, expected_revision: int, source: SourceMetadata
    ) -> DocumentDetail:
        row = await self.document(base_id, document_id, lock=True)
        self.require_revision(row, expected_revision)
        if row.status in {"PUBLISHED", "FAILED"}:
            raise AppError(
                "metadata_sync_unavailable", "请先撤回发布或完成解析，再同步官网信息", 409
            )
        snapshot = await self.repo.snapshot(row.id, row.revision)
        if snapshot is None:
            raise AppError("parse_required", "请先完成文档解析")
        result = ParseResult.model_validate(snapshot.result)
        data = CorrectionInput(
            expected_revision=expected_revision,
            metadata=result.metadata,
            nodes=result.nodes,
            source_kind=row.source_kind,
            source_url=row.source_url,
            source_note=row.source_note,
            verification_note=row.verification_note,
            legal_status=row.legal_status,
            version_confirmed=row.version_confirmed,
            acknowledged_issues=snapshot.acknowledged_issues,
            reason="同步官网元数据，保留人工修订与版本确认状态",
        )
        return await self.correct(base_id, document_id, data, source_update=source)

    async def publish(self, base_id: UUID, document_id: UUID, data: ReviewInput) -> DocumentView:
        row = await self.document(base_id, document_id, lock=True)
        self.require_revision(row, data.expected_revision)
        reason = check_reason(data.reason)
        snapshot = await self.repo.snapshot(row.id, row.revision)
        if snapshot is None:
            raise AppError("parse_required", "文档尚未完成解析")
        result = ParseResult.model_validate(snapshot.result)
        issues = validate_structure(result, row.mode)
        if (
            ready_status(result.model_copy(update={"issues": issues}), snapshot.acknowledged_issues)
            != "READY"
        ):
            raise AppError("review_required", "请先修正结构错误并逐项确认校验提示")
        if not row.chunk_count:
            raise AppError("no_segments", "文档没有可发布的正文片段")
        if row.mode == "LEGAL" and (
            not row.version_confirmed
            or not result.metadata.title.strip()
            or not result.metadata.authority.strip()
            or not result.metadata.version_label.strip()
        ):
            raise AppError(
                "version_required", "发布法律文件前，请补全名称、公布机关、版本说明并确认版本"
            )
        if row.embedding_model_id and row.embedding_status != "COMPLETED":
            raise AppError("vectors_incomplete", "已启用向量化，请完成向量化后发布")
        await self.repo.publish(row)
        row.status, row.published_at = "PUBLISHED", datetime.now(UTC)
        row.status_message, row.updated_at = "已人工审核发布", datetime.now(UTC)
        await self.repo.session.flush()
        while await self.index_lexical(row.id):
            pass
        await self.audit(base_id, "PUBLISH", reason, row, review_state=review_state(row))
        await self.repo.session.flush()
        return document_view(row)

    async def withdraw(self, base_id: UUID, document_id: UUID, data: ReviewInput) -> DocumentView:
        row = await self.document(base_id, document_id, lock=True)
        self.require_revision(row, data.expected_revision)
        await self.invalidate(row)
        row.status, row.status_message = "NEEDS_REVIEW", "已撤回发布，等待重新审核"
        await self.audit(base_id, "WITHDRAW", check_reason(data.reason), row)
        return document_view(row)

    async def reparse(self, base_id: UUID, document_id: UUID, data: ReviewInput) -> DocumentView:
        row = await self.document(base_id, document_id, lock=True)
        # 解析失败的 revision=0 同样允许重试。
        if (
            row.revision != data.expected_revision
            or row.processing_token
            or row.status in {"QUEUED", "PROCESSING"}
        ):
            raise AppError("processing_conflict", "文档已更新或正在处理中，请刷新后再操作", 409)
        await self.invalidate(row)
        row.status, row.processing_stage, row.status_message = "QUEUED", "QUEUED", "等待重新解析"
        row.version_confirmed, row.legal_status = False, "UNKNOWN"
        row.embedding_status = "QUEUED" if row.embedding_model_id else "DISABLED"
        row.embedded_count, row.chunk_count, row.chunk_total = 0, 0, 0
        await self.audit(base_id, "REPARSE", check_reason(data.reason), row)
        return document_view(row)

    async def vectorize(
        self, base_id: UUID, document_id: UUID, data: VectorizeInput
    ) -> DocumentView:
        row = await self.document(base_id, document_id, lock=True)
        self.require_revision(row, data.expected_revision)
        if not row.chunk_count:
            raise AppError("no_segments", "请先完成文档解析和切分")
        provider = await self.embedding_provider(data.model_id)
        await self.invalidate(row)
        row.status = "NEEDS_REVIEW"
        # 模型不变且已有部分结果时断点续传；配置改变则全部重算。
        if (
            row.embedding_fingerprint != provider.fingerprint
            or row.embedding_model_id != data.model_id
        ):
            await self.repo.reset_embeddings(row)
            row.embedded_count, row.embedding_dimensions = 0, None
        row.embedding_model_id, row.embedding_fingerprint = data.model_id, provider.fingerprint
        row.embedding_status, row.embedding_message, row.processing_stage = (
            "QUEUED",
            "",
            "VECTORIZING",
        )
        await self.audit(
            base_id, "VECTORIZE", check_reason(data.reason), row, model_id=str(data.model_id)
        )
        return document_view(row)

    async def versions(self, base_id: UUID, document_id: UUID) -> list[VersionCandidate]:
        row = await self.document(base_id, document_id)
        candidates = await self.repo.candidates(row)
        result = []
        for candidate in candidates:
            reasons = []
            if candidate.file_hash == row.file_hash:
                reasons.append("原件 Hash 相同")
            if candidate.content_hash and candidate.content_hash == row.content_hash:
                reasons.append("提取正文相同")
            for field, label in (
                ("title", "法律名称相同"),
                ("authority", "公布机关相同"),
                ("document_number", "文号相同"),
            ):
                if row.legal_metadata.get(field) and row.legal_metadata.get(
                    field
                ) == candidate.legal_metadata.get(field):
                    reasons.append(label)
            result.append(
                VersionCandidate(
                    document=document_view(candidate),
                    match_reasons=reasons,
                    same_content=bool(
                        row.content_hash and row.content_hash == candidate.content_hash
                    ),
                )
            )
        return result

    async def compare(self, base_id: UUID, left_id: UUID, right_id: UUID) -> ComparisonView:
        left, right = await self.document(base_id, left_id), await self.document(base_id, right_id)
        lrev, rrev = (
            await self.repo.snapshot(left.id, left.revision),
            await self.repo.snapshot(right.id, right.revision),
        )
        if not lrev or not rrev:
            raise AppError("parse_required", "两个文件都完成解析后才能比较")
        ltext, rtext = str(lrev.result["text"]), str(rrev.result["text"])

        def make_diff() -> tuple[str, bool]:
            # 对超长单行文本也切分比较单元，限制 CPU 和结果体积。
            def lines(text: str) -> list[str]:
                return [
                    text[start : start + 200] + "\n"
                    for start in range(0, min(len(text), 60000), 200)
                ]

            values = list(
                difflib.unified_diff(
                    lines(ltext), lines(rtext), fromfile="当前文档", tofile="对比文档", n=2
                )
            )
            diff = "".join(values)
            return diff[:60000], len(diff) > 60000 or len(ltext) > 60000 or len(rtext) > 60000

        diff, truncated = await anyio.to_thread.run_sync(make_diff)
        changes = {
            field: [
                str(left.legal_metadata.get(field))
                if left.legal_metadata.get(field) is not None
                else None,
                str(right.legal_metadata.get(field))
                if right.legal_metadata.get(field) is not None
                else None,
            ]
            for field in LegalMetadata.model_fields
            if left.legal_metadata.get(field) != right.legal_metadata.get(field)
        }
        return ComparisonView(
            left=document_view(left),
            right=document_view(right),
            same_file=left.file_hash == right.file_hash,
            same_content=bool(left.content_hash and left.content_hash == right.content_hash),
            metadata_changes=changes,
            diff=diff,
            truncated=truncated,
        )

    async def search(
        self,
        query: str,
        base_id: UUID | None,
        page: int,
        page_size: int,
        model_id: UUID | None = None,
        *,
        vector_threshold: float | None = None,
        keyword_threshold: float | None = None,
        base_ids: list[UUID] | None = None,
    ) -> SearchPage:
        query = query.strip()
        if not query:
            raise AppError("query_required", "请输入搜索内容")
        if base_id:
            await self.base(base_id)
        if base_ids is not None:
            if not base_ids:
                raise AppError("knowledge_not_configured", "请先在法律咨询模型中添加内部知识库")
            if await self.repo.existing_base_ids(base_ids) != set(base_ids):
                raise AppError("invalid_knowledge_base", "咨询知识库已不存在，请重新配置")
        total_chunks, pending = await self.repo.lexical_readiness(base_id, base_ids=base_ids)
        if pending:
            raise AppError("knowledge_index_pending", "知识库搜索索引正在准备，请稍后再试", 503)
        policy = Policy.model_validate(
            (await ConfigRepository(self.repo.session).policy()).settings
        )
        min_vector = (
            policy.knowledge_vector_threshold if vector_threshold is None else vector_threshold
        )
        min_keyword = (
            policy.knowledge_keyword_threshold if keyword_threshold is None else keyword_threshold
        )
        terms = await anyio.to_thread.run_sync(query_terms, query)
        lexical = await self.repo.bm25_candidates(
            terms, base_id, CANDIDATE_LIMIT, min_keyword, base_ids=base_ids
        )
        vector: list[tuple[KnowledgeChunk, KnowledgeDocument, float]] = []
        indexed_models = (
            await self.repo.vector_models(base_id, base_ids=base_ids) if total_chunks else []
        )
        provider = None
        # 显式指定的模型即使没有匹配索引也必须校验，不悄悄改用其他向量空间。
        if model_id is not None:
            provider = await self.embedding_provider(model_id)
        elif total_chunks:
            models = {
                model.id: model
                for model in await ConfigRepository(self.repo.session).models()
                if model.enabled and model.model_type == "embedding"
            }
            for candidate_id, fingerprint in indexed_models:
                model = models.get(candidate_id)
                if model is None:
                    continue
                current = self.configured_provider(model, "")
                if current.fingerprint == fingerprint:
                    provider = await self.embedding_provider(candidate_id)
                    break
        compatible = bool(
            provider
            and any(fingerprint == provider.fingerprint for _, fingerprint in indexed_models)
        )
        if provider and compatible:
            embedding = (await provider.embed([query], purpose="query"))[0]
            vector = await self.repo.vector_candidates(
                embedding,
                provider.fingerprint,
                base_id,
                CANDIDATE_LIMIT,
                min_vector,
                base_ids=base_ids,
            )

        lexical_by_id = {
            chunk.id: (chunk, doc, rank, coverage) for chunk, doc, rank, coverage in lexical
        }
        vector_by_id = {chunk.id: (chunk, doc, rank) for chunk, doc, rank in vector}
        lexical_ranks = {chunk.id: rank for rank, (chunk, *_) in enumerate(lexical, 1)}
        vector_ranks = {chunk.id: rank for rank, (chunk, *_) in enumerate(vector, 1)}
        fused = reciprocal_rank_fusion(list(lexical_by_id), list(vector_by_id))
        items = []
        for chunk_id, fusion_score in fused[(page - 1) * page_size : page * page_size]:
            lexical_hit, vector_hit = lexical_by_id.get(chunk_id), vector_by_id.get(chunk_id)
            hit = vector_hit if vector_hit else lexical_hit
            if hit is None:
                continue
            chunk, doc = hit[:2]
            cosine = max(0.0, min(1.0, vector_hit[2])) if vector_hit else None
            coverage = lexical_hit[3] if lexical_hit else None
            items.append(
                SearchHit(
                    document_id=doc.id,
                    knowledge_base_id=doc.knowledge_base_id,
                    title=str(doc.legal_metadata.get("title") or doc.filename),
                    filename=doc.filename,
                    content=chunk.content,
                    start=chunk.start,
                    end=chunk.end,
                    node_id=chunk.node_id,
                    revision=chunk.revision,
                    source_kind=doc.source_kind,
                    legal_status=doc.legal_status,
                    source_url=doc.source_url,
                    score=cosine if cosine is not None else (coverage or 0.0),
                    score_type="cosine" if cosine is not None else "keyword_coverage",
                    fusion_score=fusion_score,
                    bm25_score=lexical_hit[2] if lexical_hit else None,
                    cosine_score=cosine,
                    keyword_coverage=coverage,
                    lexical_rank=lexical_ranks.get(chunk_id),
                    vector_rank=vector_ranks.get(chunk_id),
                )
            )
        return SearchPage(
            items=items,
            total=len(fused),
            page=page,
            page_size=page_size,
            retrieval_method="hybrid" if compatible else "keyword",
        )

    async def retrieve_local(
        self,
        query: str,
        limit: int,
        *,
        base_ids: list[UUID],
        vector_threshold: float = 0.3,
        keyword_threshold: float = 0,
    ) -> SearchPage:
        return await self.search(
            query,
            None,
            1,
            limit,
            vector_threshold=vector_threshold,
            keyword_threshold=keyword_threshold,
            base_ids=base_ids,
        )

    async def index_lexical(self, document_id: UUID | None = None) -> int:
        rows = await self.repo.lexical_batch(document_id)
        if not rows:
            return 0
        indexes = await anyio.to_thread.run_sync(lexical_indexes, [row.content for row in rows])
        for row, index in zip(rows, indexes, strict=True):
            await self.repo.write_lexical(row, index)
        return len(rows)

    async def segments(
        self, base_id: UUID, document_id: UUID, page: int, page_size: int
    ) -> SegmentPage:
        row = await self.document(base_id, document_id)
        segments = await self.repo.segments(row.id, row.revision, page, page_size)
        return SegmentPage(
            items=[SegmentView.model_validate(segment) for segment in segments],
            total=row.chunk_count,
            page=page,
            page_size=page_size,
        )

    async def audits(
        self, base_id: UUID, document_id: UUID | None, page: int, page_size: int
    ) -> list[AuditView]:
        await self.base(base_id)
        return [
            AuditView.model_validate(row)
            for row in await self.repo.audits(base_id, document_id, page, page_size)
        ]
