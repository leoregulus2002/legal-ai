"""模型配置、提示词、咨询策略及完整会话历史；运行记忆保存在 Redis。"""

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "ai_models",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("model_type", sa.String(30), nullable=False),
        sa.Column("protocol", sa.String(30), nullable=False),
        sa.Column("base_url", sa.String(1000), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("supports_images", sa.Boolean(), nullable=False),
        sa.Column("supports_pdf", sa.Boolean(), nullable=False),
        sa.Column("supports_json_mode", sa.Boolean(), nullable=False),
        sa.Column("context_tokens", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("token_parameter", sa.String(30), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "system_prompts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "system_prompt_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("prompt_id", sa.Uuid(), sa.ForeignKey("system_prompts.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("prompt_id", "version"),
    )
    config = op.create_table(
        "consultation_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("kb_key_encrypted", sa.Text(), nullable=True),
    )
    op.bulk_insert(config, [{"id": 1, "settings": {}, "kb_key_encrypted": None}])
    op.create_table(
        "consultation_conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("history_version", sa.Integer(), nullable=False),
        sa.Column("active_token", sa.Uuid(), nullable=True),
        sa.Column("active_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "consultation_turns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("consultation_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("user_text", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("attachment_ids", sa.JSON(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("conversation_id", "request_id", name="uq_consultation_turns_request"),
        sa.UniqueConstraint("conversation_id", "sequence", name="uq_consultation_turns_sequence"),
    )
    op.create_index(
        "ix_consultation_turns_conversation_id", "consultation_turns", ["conversation_id"]
    )
    op.create_table(
        "consultation_attachments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("consultation_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("mime_type", sa.String(50), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(40), nullable=False, unique=True),
        sa.Column("bound", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_consultation_attachments_conversation_id",
        "consultation_attachments",
        ["conversation_id"],
    )


def downgrade() -> None:
    for table in (
        "consultation_attachments",
        "consultation_turns",
        "consultation_conversations",
        "consultation_config",
        "system_prompt_versions",
        "system_prompts",
        "ai_models",
    ):
        op.drop_table(table)
