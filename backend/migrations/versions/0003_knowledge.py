"""知识库、法律原件、解析快照、审计、切分和真实向量。"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def stamp(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        stamp("created_at"),
        stamp("updated_at"),
    )
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "knowledge_base_id", sa.Uuid(), sa.ForeignKey("knowledge_bases.id"), nullable=False
        ),
        sa.Column("filename", sa.String(240), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("original_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("source_kind", sa.String(30), nullable=False),
        sa.Column("source_url", sa.String(2000), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.Column("verification_note", sa.Text(), nullable=False),
        sa.Column("legal_status", sa.String(30), nullable=False),
        sa.Column("version_confirmed", sa.Boolean(), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("duplicate_of", sa.Uuid(), sa.ForeignKey("knowledge_documents.id")),
        sa.Column("legal_metadata", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status_message", sa.String(300), nullable=False),
        sa.Column("processing_token", sa.Uuid()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("processing_stage", sa.String(30), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("chunk_total", sa.Integer(), nullable=False),
        sa.Column("embedded_count", sa.Integer(), nullable=False),
        sa.Column("embedding_status", sa.String(30), nullable=False),
        sa.Column("embedding_model_id", sa.Uuid(), sa.ForeignKey("ai_models.id")),
        sa.Column("embedding_fingerprint", sa.String(64)),
        sa.Column("embedding_dimensions", sa.Integer()),
        sa.Column("embedding_message", sa.String(300), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        stamp("created_at"),
        stamp("updated_at"),
    )
    for column in ("knowledge_base_id", "status", "file_hash", "content_hash"):
        op.create_index(f"ix_knowledge_documents_{column}", "knowledge_documents", [column])
    op.create_table(
        "knowledge_parse_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id", sa.Uuid(), sa.ForeignKey("knowledge_documents.id"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("review_state", sa.JSON(), nullable=False),
        sa.Column("acknowledged_issues", sa.JSON(), nullable=False),
        stamp("created_at"),
        sa.UniqueConstraint("document_id", "revision"),
    )
    op.create_index(
        "ix_knowledge_parse_revisions_document_id", "knowledge_parse_revisions", ["document_id"]
    )
    op.create_table(
        "knowledge_audits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "knowledge_base_id", sa.Uuid(), sa.ForeignKey("knowledge_bases.id"), nullable=False
        ),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("knowledge_documents.id")),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer()),
        sa.Column("details", sa.JSON(), nullable=False),
        stamp("created_at"),
    )
    for column in ("knowledge_base_id", "document_id"):
        op.create_index(f"ix_knowledge_audits_{column}", "knowledge_audits", [column])
    op.create_table(
        "knowledge_segments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id", sa.Uuid(), sa.ForeignKey("knowledge_documents.id"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(80)),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector()),
        sa.UniqueConstraint("document_id", "revision", "sequence"),
    )
    op.create_index("ix_knowledge_segments_document_id", "knowledge_segments", ["document_id"])
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "knowledge_base_id", sa.Uuid(), sa.ForeignKey("knowledge_bases.id"), nullable=False
        ),
        sa.Column(
            "document_id", sa.Uuid(), sa.ForeignKey("knowledge_documents.id"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(80)),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector()),
        sa.Column("embedding_model_id", sa.Uuid(), sa.ForeignKey("ai_models.id")),
        sa.Column("embedding_fingerprint", sa.String(64)),
        sa.Column("embedding_dimensions", sa.Integer()),
    )
    for column in ("knowledge_base_id", "document_id"):
        op.create_index(f"ix_knowledge_chunks_{column}", "knowledge_chunks", [column])


def downgrade() -> None:
    for table in (
        "knowledge_chunks",
        "knowledge_segments",
        "knowledge_audits",
        "knowledge_parse_revisions",
        "knowledge_documents",
        "knowledge_bases",
    ):
        op.drop_table(table)
    # vector 可能被其他业务使用，不移除扩展。
