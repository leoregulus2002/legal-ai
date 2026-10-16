from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.knowledge.schemas import (
    LegalCategory,
    LegalMetadata,
    LegalStatus,
    SourceKind,
    StructureNode,
)


class RegulationQuery(BaseModel):
    q: str = Field(default="", max_length=500)
    scope: Literal["all", "title", "body", "number"] = "all"
    match: Literal["contains", "exact"] = "contains"
    knowledge_base_id: UUID | None = None
    category: LegalCategory | None = None
    authority: str = Field(default="", max_length=300)
    region: str = Field(default="", max_length=100)
    legal_status: LegalStatus | None = None
    promulgated_from: date | None = None
    promulgated_to: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    sort: Literal[
        "relevance", "promulgated_desc", "promulgated_asc", "effective_desc", "effective_asc"
    ] = "relevance"
    page: int = Field(default=1, ge=1, le=100000)
    page_size: int = Field(default=20, ge=1, le=50)


class RegulationSummary(BaseModel):
    document_id: UUID
    knowledge_base_id: UUID
    knowledge_base_name: str
    revision: int
    metadata: LegalMetadata
    legal_status: LegalStatus
    source_kind: SourceKind
    version_confirmed: bool
    source_url: str
    updated_at: datetime
    excerpt: str = ""
    node_id: str | None = None
    article_label: str = ""
    matched_articles: int = 0


class RegulationPage(BaseModel):
    items: list[RegulationSummary]
    total: int
    page: int
    page_size: int
    highlight: str


class RegulationDetail(BaseModel):
    regulation: RegulationSummary
    text: str
    nodes: list[StructureNode]


class RegulationBaseOption(BaseModel):
    id: UUID
    name: str


class RegulationOptions(BaseModel):
    knowledge_bases: list[RegulationBaseOption]
    authorities: list[str]
    regions: list[str]
    document_count: int
