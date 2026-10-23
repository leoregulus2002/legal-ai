"""Persist files generated in conversations and document analysis."""

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "generated_files",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("consultation_conversations.id", ondelete="CASCADE"),
        ),
        sa.Column("request_id", sa.Uuid()),
        sa.Column(
            "analysis_run_id", sa.Uuid(), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE")
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "(conversation_id IS NOT NULL AND request_id IS NOT NULL AND analysis_run_id IS NULL) "
            "OR (conversation_id IS NULL AND request_id IS NULL AND analysis_run_id IS NOT NULL)",
            name=op.f("ck_generated_files_generated_file_owner"),
        ),
        sa.UniqueConstraint(
            "conversation_id", "request_id", "position", name="uq_generated_files_conversation_id"
        ),
        sa.UniqueConstraint(
            "analysis_run_id", "position", name="uq_generated_files_analysis_run_id"
        ),
    )
    op.create_index("ix_generated_files_conversation_id", "generated_files", ["conversation_id"])
    op.create_index("ix_generated_files_analysis_run_id", "generated_files", ["analysis_run_id"])


def downgrade() -> None:
    op.drop_table("generated_files")
