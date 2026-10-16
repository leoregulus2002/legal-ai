"""正式片段的 BM25 词频索引；历史片段由后台任务分批补建。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "lexical_terms",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column("lexical_length", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column("lexical_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_knowledge_chunks_lexical_terms",
        "knowledge_chunks",
        ["lexical_terms"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_chunks_lexical_terms", table_name="knowledge_chunks")
    for column in ("lexical_version", "lexical_length", "lexical_terms"):
        op.drop_column("knowledge_chunks", column)
