"""将模型公开返回的思考内容与回答正文分别保存。"""

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "consultation_turns",
        sa.Column("reasoning", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("consultation_turns", "reasoning")
