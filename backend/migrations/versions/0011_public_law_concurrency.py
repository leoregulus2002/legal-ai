"""公开法规自动向量化并发配置。"""

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "vectorization_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("concurrency", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("id = 1", name=op.f("ck_vectorization_config_singleton")),
        sa.CheckConstraint(
            "concurrency BETWEEN 1 AND 10", name=op.f("ck_vectorization_config_concurrency_range")
        ),
    )
    op.bulk_insert(sa.table("vectorization_config", sa.column("id", sa.Integer())), [{"id": 1}])
    op.add_column(
        "public_law_vector_tasks",
        sa.Column("concurrency", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_check_constraint(
        op.f("ck_public_law_vector_tasks_concurrency_range"),
        "public_law_vector_tasks",
        "concurrency BETWEEN 1 AND 10",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_public_law_vector_tasks_concurrency_range"),
        "public_law_vector_tasks",
        type_="check",
    )
    op.drop_column("public_law_vector_tasks", "concurrency")
    op.drop_table("vectorization_config")
