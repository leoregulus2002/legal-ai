"""自动向量化支持线性和并发请求模式。"""

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 既有配置和任务沿用并发流水线，避免升级改变运行中的任务。
    for table in ("vectorization_config", "public_law_vector_tasks"):
        op.add_column(
            table,
            sa.Column("request_mode", sa.String(20), nullable=False, server_default="concurrent"),
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_request_mode_values"),
            table,
            "request_mode IN ('serial', 'concurrent')",
        )
    op.create_check_constraint(
        op.f("ck_public_law_vector_tasks_serial_concurrency"),
        "public_law_vector_tasks",
        "request_mode != 'serial' OR concurrency = 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_public_law_vector_tasks_serial_concurrency"),
        "public_law_vector_tasks",
        type_="check",
    )
    for table in ("public_law_vector_tasks", "vectorization_config"):
        op.drop_constraint(op.f(f"ck_{table}_request_mode_values"), table, type_="check")
        op.drop_column(table, "request_mode")
