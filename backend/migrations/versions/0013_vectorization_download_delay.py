"""自动向量化支持下载间隔。"""

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    for table in ("vectorization_config", "public_law_vector_tasks"):
        op.add_column(
            table,
            sa.Column("download_delay_ms", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_download_delay_range"),
            table,
            "download_delay_ms BETWEEN 0 AND 60000",
        )
    op.add_column(
        "public_law_vector_tasks",
        sa.Column("next_download_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("public_law_vector_tasks", "next_download_at")
    for table in ("public_law_vector_tasks", "vectorization_config"):
        op.drop_constraint(op.f(f"ck_{table}_download_delay_range"), table, type_="check")
        op.drop_column(table, "download_delay_ms")
