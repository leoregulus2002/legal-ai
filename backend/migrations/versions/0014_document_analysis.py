"""法律文书分析工作区、持久任务和工具配置。"""

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "ai_models",
        sa.Column("supports_tools", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "analysis_workspaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "analysis_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("analysis_workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("original", sa.LargeBinary(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("spans", sa.JSON(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_analysis_documents_workspace_id", "analysis_documents", ["workspace_id"])
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("analysis_workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column(
            "parent_run_id", sa.Uuid(), sa.ForeignKey("analysis_runs.id", ondelete="SET NULL")
        ),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("checkpoint", sa.JSON(), nullable=False),
        sa.Column("intent", sa.JSON()),
        sa.Column("report", sa.JSON()),
        sa.Column("clarification", sa.Text()),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("model_calls", sa.Integer(), nullable=False),
        sa.Column("tool_calls_count", sa.Integer(), nullable=False),
        sa.Column("elapsed_seconds", sa.Integer(), nullable=False),
        sa.Column("active_started_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("workspace_id", "request_id"),
    )
    for column in ("workspace_id", "status", "lease_until"):
        op.create_index(f"ix_analysis_runs_{column}", "analysis_runs", [column])
    op.create_table(
        "analysis_steps",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("agent", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("summary", sa.String(300), nullable=False),
        sa.Column("output", sa.JSON()),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_analysis_steps_run_id", "analysis_steps", ["run_id"])
    op.create_table(
        "analysis_tool_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent", sa.String(30), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_analysis_tool_calls_run_id", "analysis_tool_calls", ["run_id"])
    op.create_table(
        "analysis_mcp_servers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("token_encrypted", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("allowed_tools", sa.JSON(), nullable=False),
        sa.Column("timeout", sa.Integer(), nullable=False),
        sa.Column("allow_document_content", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "analysis_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("settings", sa.JSON(), nullable=False),
    )
    op.execute(
        sa.insert(
            sa.table(
                "analysis_settings", sa.column("id", sa.Integer()), sa.column("settings", sa.JSON())
            )
        ).values(id=1, settings={})
    )


def downgrade() -> None:
    for table in (
        "analysis_settings",
        "analysis_mcp_servers",
        "analysis_tool_calls",
        "analysis_steps",
        "analysis_runs",
        "analysis_documents",
        "analysis_workspaces",
    ):
        op.drop_table(table)
    op.drop_column("ai_models", "supports_tools")
