"""向量模型专属参数与 DashScope 原生协议。"""

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("ai_models", sa.Column("embedding_dimensions", sa.Integer(), nullable=True))
    op.add_column(
        "ai_models",
        sa.Column("embedding_batch_size", sa.Integer(), nullable=False, server_default="8"),
    )
    op.add_column(
        "ai_models",
        sa.Column("embedding_timeout", sa.Integer(), nullable=False, server_default="90"),
    )
    op.add_column(
        "ai_models",
        sa.Column("embedding_query_instruction", sa.Text(), nullable=False, server_default=""),
    )
    op.execute("""UPDATE ai_models SET protocol = 'openai_embeddings', max_output_tokens = 0,
                  temperature = NULL, supports_images = false, supports_pdf = false,
                  supports_json_mode = false WHERE model_type = 'embedding'
                  AND protocol IN ('chat_completions', 'responses')""")


def downgrade() -> None:
    op.execute("""UPDATE ai_models SET protocol = 'chat_completions',
                  max_output_tokens = LEAST(4096, context_tokens - 1)
                  WHERE model_type = 'embedding'
                  AND protocol IN ('openai_embeddings', 'dashscope_embeddings')""")
    for column in (
        "embedding_query_instruction",
        "embedding_timeout",
        "embedding_batch_size",
        "embedding_dimensions",
    ):
        op.drop_column("ai_models", column)
