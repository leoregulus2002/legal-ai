"""知识库自动发布、失败阶段与版本发布记录。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("knowledge_documents", sa.Column("failed_stage", sa.String(30)))
    op.create_table(
        "knowledge_publications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id", sa.Uuid(), sa.ForeignKey("knowledge_documents.id"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("embedding_model_id", sa.Uuid(), sa.ForeignKey("ai_models.id")),
        sa.Column("embedding_fingerprint", sa.String(64)),
        sa.Column("embedding_dimensions", sa.Integer()),
        sa.UniqueConstraint("document_id", "revision"),
    )
    op.create_index(
        "ix_knowledge_publications_document_id", "knowledge_publications", ["document_id"]
    )
    # 历史审计与解析快照不改写；每个修订保留首次发布记录。
    op.execute(
        sa.text("""
        INSERT INTO knowledge_publications
            (id, document_id, revision, published_at)
        SELECT DISTINCT ON (document_id, revision) id, document_id, revision, created_at
        FROM knowledge_audits
        WHERE action = 'PUBLISH' AND document_id IS NOT NULL AND revision IS NOT NULL
        ORDER BY document_id, revision, created_at, id
    """)
    )
    op.execute(
        sa.text("""
        INSERT INTO knowledge_publications
            (id, document_id, revision, published_at, embedding_model_id,
             embedding_fingerprint, embedding_dimensions)
        SELECT id, id, revision, published_at, embedding_model_id,
               embedding_fingerprint, embedding_dimensions
        FROM knowledge_documents WHERE published_at IS NOT NULL
        ON CONFLICT (document_id, revision) DO UPDATE SET
            embedding_model_id = EXCLUDED.embedding_model_id,
            embedding_fingerprint = EXCLUDED.embedding_fingerprint,
            embedding_dimensions = EXCLUDED.embedding_dimensions
    """)
    )
    op.execute(
        sa.text("""
        UPDATE knowledge_documents SET status = 'WITHDRAWN'
        WHERE status IN ('NEEDS_REVIEW', 'READY') AND status_message LIKE '已撤回发布%'
    """)
    )
    op.execute(
        sa.text("""
        UPDATE knowledge_documents SET
            status = 'FAILED', processing_stage = 'FAILED', failed_stage = 'VECTORIZING',
            status_message = coalesce(nullif(embedding_message, ''), '向量化未完成，请重试'),
            processing_token = NULL, lease_until = NULL
        WHERE status IN ('NEEDS_REVIEW', 'READY') AND embedding_status = 'FAILED'
    """)
    )
    op.execute(
        sa.text("""
        UPDATE knowledge_documents SET
            status = 'PROCESSING', processing_stage = 'VECTORIZING',
            embedding_status = 'QUEUED', processing_token = NULL, lease_until = NULL,
            status_message = '等待向量化后自动发布'
        WHERE status IN ('NEEDS_REVIEW', 'READY')
    """)
    )
    op.execute(
        sa.text("""
        UPDATE knowledge_documents SET
            status = 'FAILED', processing_stage = 'FAILED', failed_stage = 'CHUNKING',
            status_message = '检索片段不完整，请重新解析后重试',
            embedding_status = 'FAILED', processing_token = NULL, lease_until = NULL
        WHERE status = 'PROCESSING' AND processing_stage = 'VECTORIZING'
          AND (chunk_count = 0 OR chunk_count <> chunk_total)
    """)
    )
    op.execute(
        sa.text("""
        UPDATE knowledge_documents SET
            status = 'FAILED', processing_stage = 'FAILED', failed_stage = 'VALIDATING',
            status_message = '数据校验未通过，请修订或重新解析后重试',
            embedding_status = 'FAILED', processing_token = NULL, lease_until = NULL
        WHERE status = 'PROCESSING' AND processing_stage = 'VECTORIZING'
          AND NOT EXISTS (
              SELECT 1 FROM knowledge_parse_revisions r
              WHERE r.document_id = knowledge_documents.id
                AND r.revision = knowledge_documents.revision
                AND btrim(coalesce(r.result->>'text', '')) <> ''
                AND NOT EXISTS (
                    SELECT 1 FROM jsonb_array_elements(r.result::jsonb->'issues') issue
                    WHERE issue->>'severity' = 'ERROR'
                )
          )
    """)
    )
    op.execute(
        sa.text("""
        UPDATE knowledge_documents SET
            status = 'FAILED', processing_stage = 'FAILED', failed_stage = 'VECTORIZING',
            status_message = '请选择向量模型后重试向量化',
            embedding_status = 'FAILED', processing_token = NULL, lease_until = NULL
        WHERE status = 'PROCESSING' AND processing_stage = 'VECTORIZING'
          AND embedding_model_id IS NULL
    """)
    )
    op.execute(
        sa.text("""
        UPDATE knowledge_documents SET failed_stage = 'EXTRACTING'
        WHERE status = 'FAILED' AND failed_stage IS NULL
    """)
    )


def downgrade() -> None:
    op.execute(
        sa.text("""
        UPDATE knowledge_documents SET status = 'NEEDS_REVIEW', processing_stage = 'COMPLETED',
            embedding_status = 'QUEUED', processing_token = NULL, lease_until = NULL
        WHERE status = 'PROCESSING' AND processing_stage IN ('VECTORIZING', 'PUBLISHING')
    """)
    )
    documents = sa.table("knowledge_documents", sa.column("status", postgresql.TEXT()))
    op.execute(
        documents.update().where(documents.c.status == "WITHDRAWN").values(status="NEEDS_REVIEW")
    )
    op.drop_index("ix_knowledge_publications_document_id", table_name="knowledge_publications")
    op.drop_table("knowledge_publications")
    op.drop_column("knowledge_documents", "failed_stage")
