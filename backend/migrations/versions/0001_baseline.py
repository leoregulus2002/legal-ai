"""Phase 1 空业务 schema 基线，仅建立 Alembic 版本记录。"""

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """当前没有业务表，未来表结构由后续迁移创建。"""


def downgrade() -> None:
    """当前没有业务表需要删除。"""
