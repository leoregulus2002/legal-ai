"""关联公开法规与知识库文档，避免重复导入。"""

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("knowledge_documents", sa.Column("public_law_id", sa.String(100), nullable=True))
    # 只关联已核验的官网来源；多份历史上传保留原件，并选择完成状态最优的一份关联。
    op.execute("""
        WITH official_documents AS (
            SELECT id, knowledge_base_id, created_at,
                substring(source_url FROM '[?&]id=([A-Za-z0-9_-]{1,100})(&|#|$)') AS law_id,
                CASE
                    WHEN embedding_status = 'COMPLETED' AND embedding_model_id IS NOT NULL
                        AND chunk_count > 0 AND embedded_count >= chunk_count
                        AND status NOT IN ('FAILED', 'QUEUED', 'PROCESSING') THEN 0
                    WHEN status IN ('QUEUED', 'PROCESSING')
                        OR embedding_status IN ('QUEUED', 'PROCESSING') THEN 1
                    ELSE 2
                END AS priority
            FROM knowledge_documents
            WHERE deleted_at IS NULL AND source_kind = 'OFFICIAL_VERIFIED'
                AND source_url ~ '^https?://flk[.]npc[.]gov[.]cn/detail[?]'
        ), ranked AS (
            SELECT id, law_id,
                row_number() OVER (
                    PARTITION BY law_id, knowledge_base_id
                    ORDER BY priority, created_at DESC, id
                ) AS position
            FROM official_documents WHERE law_id IS NOT NULL
        )
        UPDATE knowledge_documents AS document SET public_law_id = ranked.law_id
        FROM ranked WHERE document.id = ranked.id AND ranked.position = 1
    """)
    op.create_index(
        "uq_knowledge_documents_public_law",
        "knowledge_documents",
        ["public_law_id", "knowledge_base_id"],
        unique=True,
        postgresql_where=sa.text("public_law_id IS NOT NULL AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_knowledge_documents_public_law", table_name="knowledge_documents")
    op.drop_column("knowledge_documents", "public_law_id")
