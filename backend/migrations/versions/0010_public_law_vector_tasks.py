"""公开法规串行向量化任务。"""

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "public_law_vector_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("slot", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "knowledge_base_id", sa.Uuid(), sa.ForeignKey("knowledge_bases.id"), nullable=False
        ),
        sa.Column("embedding_model_id", sa.Uuid(), sa.ForeignKey("ai_models.id"), nullable=False),
        sa.Column("embedding_fingerprint", sa.String(64), nullable=False),
        sa.Column("query", sa.JSON()),
        sa.Column("source_page", sa.Integer(), nullable=False),
        sa.Column("scan_complete", sa.Boolean(), nullable=False),
        sa.Column("total", sa.Integer()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("slot = 1", name=op.f("ck_public_law_vector_tasks_singleton_slot")),
    )
    op.create_index(
        "uq_public_law_vector_tasks_active",
        "public_law_vector_tasks",
        ["slot"],
        unique=True,
        postgresql_where=sa.text("status IN ('RUNNING', 'STOPPING')"),
    )
    op.create_table(
        "public_law_vector_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "task_id", sa.Uuid(), sa.ForeignKey("public_law_vector_tasks.id"), nullable=False
        ),
        sa.Column("law_id", sa.String(100), nullable=False),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("decision", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("knowledge_documents.id")),
        sa.Column("error_message", sa.String(300)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("task_id", "law_id"),
    )
    op.create_index("ix_public_law_vector_items_task_id", "public_law_vector_items", ["task_id"])
    op.create_index(
        "ix_public_law_vector_items_queue",
        "public_law_vector_items",
        ["task_id", "status", "sequence"],
    )
    op.create_index(
        "ix_public_law_vector_items_recent", "public_law_vector_items", ["task_id", "updated_at"]
    )


def downgrade() -> None:
    op.drop_table("public_law_vector_items")
    op.drop_table("public_law_vector_tasks")
