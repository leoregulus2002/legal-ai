from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Float, and_, case, cast, delete, func, insert, or_, select, true, update
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.knowledge.models import (
    KnowledgeAudit,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSegment,
    ParseRevision,
)
from app.modules.knowledge.retrieval import LEXICAL_VERSION, LexicalIndex


class KnowledgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(
        self, row: KnowledgeBase | KnowledgeDocument | ParseRevision | KnowledgeAudit
    ) -> None:
        self.session.add(row)
        await self.session.flush()

    async def base(self, base_id: UUID, *, lock: bool = False) -> KnowledgeBase | None:
        statement = select(KnowledgeBase).where(
            KnowledgeBase.id == base_id, KnowledgeBase.deleted_at.is_(None)
        )
        return await self.session.scalar(statement.with_for_update() if lock else statement)

    async def bases(self, query: str, page: int, page_size: int) -> tuple[list[KnowledgeBase], int]:
        criteria = [KnowledgeBase.deleted_at.is_(None)]
        if query:
            criteria.append(KnowledgeBase.name.icontains(query, autoescape=True))
        count = await self.session.scalar(
            select(func.count()).select_from(KnowledgeBase).where(*criteria)
        )
        rows = await self.session.scalars(
            select(KnowledgeBase)
            .where(*criteria)
            .order_by(KnowledgeBase.updated_at.desc(), KnowledgeBase.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows), count or 0

    async def existing_base_ids(self, ids: list[UUID]) -> set[UUID]:
        if not ids:
            return set()
        return set(
            await self.session.scalars(
                select(KnowledgeBase.id).where(
                    KnowledgeBase.id.in_(ids), KnowledgeBase.deleted_at.is_(None)
                )
            )
        )

    async def document(self, document_id: UUID, *, lock: bool = False) -> KnowledgeDocument | None:
        statement = select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id, KnowledgeDocument.deleted_at.is_(None)
        )
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(statement)

    async def documents(
        self, base_id: UUID, query: str, status: str | None, page: int, page_size: int
    ) -> tuple[list[KnowledgeDocument], int]:
        criteria = [
            KnowledgeDocument.knowledge_base_id == base_id,
            KnowledgeDocument.deleted_at.is_(None),
        ]
        if query:
            criteria.append(
                or_(
                    KnowledgeDocument.filename.icontains(query, autoescape=True),
                    KnowledgeDocument.legal_metadata["title"]
                    .as_string()
                    .icontains(query, autoescape=True),
                )
            )
        if status:
            criteria.append(KnowledgeDocument.status == status)
        total = await self.session.scalar(
            select(func.count()).select_from(KnowledgeDocument).where(*criteria)
        )
        rows = await self.session.scalars(
            select(KnowledgeDocument)
            .where(*criteria)
            .order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows), total or 0

    async def original(self, document_id: UUID) -> bytes:
        data = await self.session.scalar(
            select(KnowledgeDocument.original_bytes).where(KnowledgeDocument.id == document_id)
        )
        if data is None:
            raise RuntimeError("document original missing")
        return data

    async def snapshot(self, document_id: UUID, revision: int) -> ParseRevision | None:
        return await self.session.scalar(
            select(ParseRevision).where(
                ParseRevision.document_id == document_id, ParseRevision.revision == revision
            )
        )

    async def snapshots(self, document_id: UUID) -> list[ParseRevision]:
        return list(
            await self.session.scalars(
                select(ParseRevision)
                .where(ParseRevision.document_id == document_id)
                .order_by(ParseRevision.revision.desc())
            )
        )

    async def same_hash(self, base_id: UUID, file_hash: str) -> UUID | None:
        return await self.session.scalar(
            select(KnowledgeDocument.id)
            .where(
                KnowledgeDocument.knowledge_base_id == base_id,
                KnowledgeDocument.file_hash == file_hash,
                KnowledgeDocument.deleted_at.is_(None),
            )
            .order_by(KnowledgeDocument.created_at)
            .limit(1)
        )

    async def candidates(self, row: KnowledgeDocument) -> list[KnowledgeDocument]:
        metadata = row.legal_metadata
        matches = [KnowledgeDocument.file_hash == row.file_hash]
        if row.content_hash:
            matches.append(KnowledgeDocument.content_hash == row.content_hash)
        for field in ("title", "document_number"):
            if metadata.get(field):
                matches.append(
                    KnowledgeDocument.legal_metadata[field].as_string() == str(metadata[field])
                )
        return list(
            await self.session.scalars(
                select(KnowledgeDocument)
                .where(
                    KnowledgeDocument.knowledge_base_id == row.knowledge_base_id,
                    KnowledgeDocument.id != row.id,
                    KnowledgeDocument.deleted_at.is_(None),
                    or_(*matches),
                )
                .order_by(KnowledgeDocument.created_at.desc())
                .limit(100)
            )
        )

    async def clear_published(self, document_id: UUID) -> None:
        await self.session.execute(
            delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)
        )

    async def remove_base(self, row: KnowledgeBase) -> None:
        now = datetime.now(UTC)
        row.deleted_at = row.updated_at = now
        await self.session.execute(
            delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_base_id == row.id)
        )
        await self.session.execute(
            update(KnowledgeDocument)
            .where(
                KnowledgeDocument.knowledge_base_id == row.id,
                KnowledgeDocument.deleted_at.is_(None),
            )
            .values(deleted_at=now, published_at=None, processing_token=None, lease_until=None)
        )
        await self.session.flush()

    async def audits(
        self, base_id: UUID, document_id: UUID | None, page: int, page_size: int
    ) -> list[KnowledgeAudit]:
        statement = select(KnowledgeAudit).where(KnowledgeAudit.knowledge_base_id == base_id)
        if document_id:
            statement = statement.where(KnowledgeAudit.document_id == document_id)
        return list(
            await self.session.scalars(
                statement.order_by(KnowledgeAudit.created_at.desc(), KnowledgeAudit.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )

    async def replace_segments(
        self, document_id: UUID, revision: int, values: list[dict[str, object]]
    ) -> None:
        await self.session.execute(
            delete(KnowledgeSegment).where(
                KnowledgeSegment.document_id == document_id, KnowledgeSegment.revision == revision
            )
        )
        if values:
            await self.session.execute(insert(KnowledgeSegment), values)

    async def append_segments(self, values: list[dict[str, object]]) -> None:
        if values:
            await self.session.execute(insert(KnowledgeSegment), values)

    async def segments(
        self, document_id: UUID, revision: int, page: int, page_size: int
    ) -> list[KnowledgeSegment]:
        return list(
            await self.session.scalars(
                select(KnowledgeSegment)
                .where(
                    KnowledgeSegment.document_id == document_id,
                    KnowledgeSegment.revision == revision,
                )
                .order_by(KnowledgeSegment.sequence)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )

    async def publish(self, row: KnowledgeDocument) -> None:
        await self.clear_published(row.id)
        await self.session.execute(
            insert(KnowledgeChunk).from_select(
                [
                    "id",
                    "knowledge_base_id",
                    "document_id",
                    "revision",
                    "node_id",
                    "start",
                    "end",
                    "content",
                    "embedding",
                    "embedding_model_id",
                    "embedding_fingerprint",
                    "embedding_dimensions",
                ],
                select(
                    KnowledgeSegment.id,
                    KnowledgeBase.id,
                    KnowledgeSegment.document_id,
                    KnowledgeSegment.revision,
                    KnowledgeSegment.node_id,
                    KnowledgeSegment.start,
                    KnowledgeSegment.end,
                    KnowledgeSegment.content,
                    KnowledgeSegment.embedding,
                    KnowledgeDocument.embedding_model_id,
                    KnowledgeDocument.embedding_fingerprint,
                    KnowledgeDocument.embedding_dimensions,
                )
                .select_from(KnowledgeSegment)
                .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeSegment.document_id)
                .join(KnowledgeBase, KnowledgeBase.id == KnowledgeDocument.knowledge_base_id)
                .where(
                    KnowledgeSegment.document_id == row.id,
                    KnowledgeSegment.revision == row.revision,
                ),
            )
        )

    async def claim(self, task: str) -> tuple[UUID, UUID, UUID, str] | None:
        now = datetime.now(UTC)
        expired = and_(
            KnowledgeDocument.processing_token.is_not(None), KnowledgeDocument.lease_until < now
        )
        queued = (
            KnowledgeDocument.status == "QUEUED"
            if task == "PARSE"
            else and_(
                KnowledgeDocument.embedding_status == "QUEUED",
                KnowledgeDocument.processing_token.is_(None),
            )
        )
        eligible = (
            KnowledgeDocument.status.in_(["QUEUED", "PROCESSING"])
            if task == "PARSE"
            else and_(
                KnowledgeDocument.status.not_in(["QUEUED", "PROCESSING", "FAILED"]),
                KnowledgeDocument.embedding_status.in_(["QUEUED", "PROCESSING"]),
            )
        )
        row = await self.session.scalar(
            select(KnowledgeDocument)
            .join(KnowledgeBase)
            .where(
                KnowledgeDocument.deleted_at.is_(None),
                KnowledgeBase.deleted_at.is_(None),
                eligible,
                or_(queued, expired),
            )
            .order_by(KnowledgeDocument.created_at)
            .with_for_update(of=KnowledgeDocument, skip_locked=True)
            .limit(1)
        )
        if row is None:
            return None
        token = uuid4()
        row.processing_token, row.lease_until = token, now + timedelta(minutes=10)
        if task == "PARSE":
            row.status, row.processing_stage, row.status_message = (
                "PROCESSING",
                "EXTRACTING",
                "正在提取正文",
            )
        else:
            row.embedding_status, row.processing_stage = "PROCESSING", "VECTORIZING"
        row.updated_at = now
        return row.id, row.knowledge_base_id, token, task

    async def embedding_batch(
        self, row: KnowledgeDocument, limit: int = 8
    ) -> list[KnowledgeSegment]:
        return list(
            await self.session.scalars(
                select(KnowledgeSegment)
                .where(
                    KnowledgeSegment.document_id == row.id,
                    KnowledgeSegment.revision == row.revision,
                    KnowledgeSegment.embedding.is_(None),
                )
                .order_by(KnowledgeSegment.sequence)
                .limit(limit)
            )
        )

    async def write_embedding(self, segment_id: UUID, embedding: list[float]) -> None:
        await self.session.execute(
            update(KnowledgeSegment)
            .where(KnowledgeSegment.id == segment_id)
            .values(embedding=embedding)
        )

    async def reset_embeddings(self, row: KnowledgeDocument) -> None:
        await self.session.execute(
            update(KnowledgeSegment)
            .where(
                KnowledgeSegment.document_id == row.id, KnowledgeSegment.revision == row.revision
            )
            .values(embedding=None)
        )

    async def reuse_embeddings(self, document_id: UUID, previous: int, current: int) -> int:
        original = KnowledgeSegment.__table__.alias("previous_segments")
        await self.session.execute(
            update(KnowledgeSegment)
            .where(
                KnowledgeSegment.document_id == document_id,
                KnowledgeSegment.revision == current,
                original.c.document_id == document_id,
                original.c.revision == previous,
                original.c.start == KnowledgeSegment.start,
                original.c.end == KnowledgeSegment.end,
                original.c.content == KnowledgeSegment.content,
                original.c.embedding.is_not(None),
            )
            .values(embedding=original.c.embedding)
            .execution_options(synchronize_session=False)
        )
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(KnowledgeSegment)
                .where(
                    KnowledgeSegment.document_id == document_id,
                    KnowledgeSegment.revision == current,
                    KnowledgeSegment.embedding.is_not(None),
                )
            )
            or 0
        )

    @staticmethod
    def search_criteria(
        base_id: UUID | None = None, base_ids: list[UUID] | None = None
    ) -> list[ColumnElement[bool]]:
        criteria: list[ColumnElement[bool]] = [
            KnowledgeBase.deleted_at.is_(None),
            KnowledgeDocument.deleted_at.is_(None),
            KnowledgeDocument.status == "PUBLISHED",
            KnowledgeChunk.revision == KnowledgeDocument.revision,
        ]
        if base_id:
            criteria.append(KnowledgeChunk.knowledge_base_id == base_id)
        if base_ids is not None:
            # 空列表也必须施加范围限制，不能意外退回全库检索。
            criteria.append(KnowledgeChunk.knowledge_base_id.in_(base_ids))
        return criteria

    async def lexical_batch(
        self, document_id: UUID | None = None, limit: int = 100
    ) -> list[KnowledgeChunk]:
        criteria = self.search_criteria()
        criteria.append(KnowledgeChunk.lexical_version != LEXICAL_VERSION)
        if document_id:
            criteria.append(KnowledgeChunk.document_id == document_id)
        return list(
            await self.session.scalars(
                select(KnowledgeChunk)
                .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
                .join(KnowledgeBase, KnowledgeBase.id == KnowledgeChunk.knowledge_base_id)
                .where(*criteria)
                .order_by(KnowledgeChunk.id)
                .limit(limit)
                .with_for_update(of=KnowledgeChunk, skip_locked=True)
            )
        )

    async def write_lexical(self, row: KnowledgeChunk, index: LexicalIndex) -> None:
        await self.session.execute(
            update(KnowledgeChunk)
            .where(KnowledgeChunk.id == row.id, KnowledgeChunk.revision == row.revision)
            .values(
                lexical_terms=index.terms,
                lexical_length=index.length,
                lexical_version=LEXICAL_VERSION,
            )
        )

    async def lexical_readiness(
        self, base_id: UUID | None, *, base_ids: list[UUID] | None = None
    ) -> tuple[int, int]:
        result = (
            await self.session.execute(
                select(
                    func.count(),
                    func.coalesce(
                        func.sum(
                            case((KnowledgeChunk.lexical_version != LEXICAL_VERSION, 1), else_=0)
                        ),
                        0,
                    ),
                )
                .select_from(KnowledgeChunk)
                .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
                .join(KnowledgeBase, KnowledgeBase.id == KnowledgeChunk.knowledge_base_id)
                .where(*self.search_criteria(base_id, base_ids))
            )
        ).one()
        return int(result[0]), int(result[1])

    async def bm25_candidates(
        self,
        terms: list[str],
        base_id: UUID | None,
        limit: int,
        min_coverage: float,
        *,
        base_ids: list[UUID] | None = None,
    ) -> list[tuple[KnowledgeChunk, KnowledgeDocument, float, float]]:
        if not terms:
            return []
        criteria = self.search_criteria(base_id, base_ids)
        criteria.append(KnowledgeChunk.lexical_version == LEXICAL_VERSION)
        # NOT MATERIALIZED 允许词项存在条件下推至 JSONB GIN 索引，避免将全库正文送入应用。
        corpus = (
            select(KnowledgeChunk.lexical_terms, KnowledgeChunk.lexical_length)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .join(KnowledgeBase, KnowledgeBase.id == KnowledgeChunk.knowledge_base_id)
            .where(*criteria)
            .cte("lexical_corpus")
            .prefix_with("NOT MATERIALIZED", dialect="postgresql")
        )
        stats = (
            select(
                cast(func.count(), Float).label("n"),
                func.greatest(func.coalesce(func.avg(corpus.c.lexical_length), 1), 1).label(
                    "avg_length"
                ),
            )
            .select_from(corpus)
            .cte("lexical_stats")
        )
        scores = []
        matches = []
        for term in terms:
            frequency = func.coalesce(KnowledgeChunk.lexical_terms[term].as_integer(), 0)
            document_frequency = (
                select(func.count())
                .select_from(corpus)
                .where(corpus.c.lexical_terms.bool_op("?")(term))
                .correlate(None)
                .scalar_subquery()
            )
            idf = func.ln(1 + (stats.c.n - document_frequency + 0.5) / (document_frequency + 0.5))
            normalization = 1.2 * (0.25 + 0.75 * KnowledgeChunk.lexical_length / stats.c.avg_length)
            scores.append(idf * frequency * 2.2 / (frequency + normalization))
            matches.append(case((frequency > 0, 1.0), else_=0.0))
        score = sum(scores)
        coverage = sum(matches) / len(terms)
        rows = await self.session.execute(
            select(
                KnowledgeChunk, KnowledgeDocument, score.label("bm25"), coverage.label("coverage")
            )
            .select_from(KnowledgeChunk)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .join(KnowledgeBase, KnowledgeBase.id == KnowledgeChunk.knowledge_base_id)
            .join(stats, true())
            .where(
                *criteria,
                KnowledgeChunk.lexical_terms.bool_op("?|")(array(terms)),
                coverage >= min_coverage,
            )
            .order_by(score.desc(), KnowledgeChunk.id)
            .limit(limit)
        )
        return [
            (chunk, doc, float(rank), float(hit_coverage))
            for chunk, doc, rank, hit_coverage in rows
        ]

    async def vector_candidates(
        self,
        vector: list[float],
        fingerprint: str,
        base_id: UUID | None,
        limit: int,
        threshold: float,
        *,
        base_ids: list[UUID] | None = None,
    ) -> list[tuple[KnowledgeChunk, KnowledgeDocument, float]]:
        compatible = and_(
            KnowledgeChunk.embedding_fingerprint == fingerprint,
            KnowledgeChunk.embedding_dimensions == len(vector),
        )
        # CASE 保证不同维度的向量绝不执行距离计算，不依赖 WHERE 求值顺序。
        score = case((compatible, 1 - KnowledgeChunk.embedding.cosine_distance(vector)), else_=None)
        rows = await self.session.execute(
            select(KnowledgeChunk, KnowledgeDocument, score.label("score"))
            .select_from(KnowledgeChunk)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .join(KnowledgeBase, KnowledgeBase.id == KnowledgeChunk.knowledge_base_id)
            .where(
                *self.search_criteria(base_id, base_ids),
                KnowledgeChunk.embedding.is_not(None),
                compatible,
                score >= threshold,
            )
            .order_by(score.desc(), KnowledgeChunk.id)
            .limit(limit)
        )
        return [(chunk, doc, float(rank)) for chunk, doc, rank in rows]

    async def vector_models(
        self, base_id: UUID | None = None, *, base_ids: list[UUID] | None = None
    ) -> list[tuple[UUID, str]]:
        latest = func.max(KnowledgeDocument.published_at)
        rows = await self.session.execute(
            select(
                KnowledgeChunk.embedding_model_id,
                KnowledgeChunk.embedding_fingerprint,
            )
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .join(KnowledgeBase, KnowledgeBase.id == KnowledgeChunk.knowledge_base_id)
            .where(
                *self.search_criteria(base_id, base_ids),
                KnowledgeChunk.embedding.is_not(None),
                KnowledgeChunk.embedding_model_id.is_not(None),
                KnowledgeChunk.embedding_fingerprint.is_not(None),
            )
            .group_by(KnowledgeChunk.embedding_model_id, KnowledgeChunk.embedding_fingerprint)
            .order_by(
                latest.desc(),
                KnowledgeChunk.embedding_model_id,
                KnowledgeChunk.embedding_fingerprint,
            )
        )
        return [(model_id, fingerprint) for model_id, fingerprint in rows]
