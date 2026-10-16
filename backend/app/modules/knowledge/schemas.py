from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ImportMode = Literal["GENERAL", "LEGAL"]
SourceKind = Literal["OFFICIAL_VERIFIED", "USER_UPLOADED", "THIRD_PARTY", "PENDING_REVIEW"]
LegalStatus = Literal["UNKNOWN", "NOT_YET_EFFECTIVE", "EFFECTIVE", "AMENDED", "REPEALED"]
LegalCategory = Literal[
    "UNCLASSIFIED",
    "CONSTITUTION",
    "LAW",
    "ADMINISTRATIVE_REGULATION",
    "SUPERVISION_REGULATION",
    "LOCAL_REGULATION",
    "DEPARTMENT_RULE",
    "LOCAL_GOVERNMENT_RULE",
    "JUDICIAL_INTERPRETATION",
    "OTHER",
]
DocumentStatus = Literal["QUEUED", "PROCESSING", "FAILED", "NEEDS_REVIEW", "READY", "PUBLISHED"]
NodeKind = Literal[
    "PART", "CHAPTER", "SECTION", "ARTICLE", "PARAGRAPH", "ITEM", "SUBITEM", "SUPPLEMENT", "ANNEX"
]


class KnowledgeInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def nonblank(self) -> "KnowledgeInput":
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("知识库名称不能为空")
        return self


class KnowledgeView(KnowledgeInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    updated_at: datetime


class KnowledgePage(BaseModel):
    items: list[KnowledgeView]
    total: int
    page: int
    page_size: int


class LegalMetadata(BaseModel):
    title: str = Field(default="", max_length=300)
    authority: str = Field(default="", max_length=300)
    document_number: str = Field(default="", max_length=200)
    promulgated_on: date | None = None
    effective_on: date | None = None
    version_label: str = Field(default="", max_length=200)
    category: LegalCategory = "UNCLASSIFIED"
    region: str = Field(default="", max_length=100)


class SourceMetadata(BaseModel):
    metadata: LegalMetadata
    legal_status: LegalStatus = "UNKNOWN"
    source_url: str = Field(max_length=2000)
    fetched_at: datetime


class Anchor(BaseModel):
    field: str
    start: int
    end: int
    text: str


class SourceSpan(BaseModel):
    kind: str
    index: int
    start: int
    end: int


class StructureNode(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    kind: NodeKind
    label: str = Field(default="", max_length=300)
    number: int | None = Field(default=None, ge=1, le=100000)
    suffix: int = Field(default=0, ge=0, le=10000)
    parent_id: str | None = None
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class ParseIssue(BaseModel):
    id: str
    code: str
    severity: Literal["ERROR", "WARNING"]
    message: str
    node_id: str | None = None
    start: int | None = None
    end: int | None = None


class ParseResult(BaseModel):
    parser_version: str = "rules-1"
    method: Literal["RULE", "HUMAN", "AI_ASSISTED"] = "RULE"
    text: str
    spans: list[SourceSpan] = Field(default_factory=list)
    nodes: list[StructureNode] = Field(default_factory=list, max_length=20000)
    metadata: LegalMetadata = Field(default_factory=LegalMetadata)
    metadata_sources: dict[str, Literal["TEXT", "OFFICIAL", "HUMAN"]] = Field(default_factory=dict)
    anchors: list[Anchor] = Field(default_factory=list)
    extraction_issues: list[ParseIssue] = Field(default_factory=list)
    issues: list[ParseIssue] = Field(default_factory=list)
    ai_provenance: dict[str, str] | None = None


class DocumentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    knowledge_base_id: UUID
    filename: str
    media_type: str
    size: int
    mode: ImportMode
    status: DocumentStatus
    source_kind: SourceKind
    source_url: str
    public_law_id: str | None
    source_metadata: SourceMetadata | None = None
    source_note: str
    verification_note: str
    legal_status: LegalStatus
    version_confirmed: bool
    file_hash: str
    content_hash: str | None
    duplicate_of: UUID | None
    revision: int
    status_message: str
    processing_stage: str
    chunk_count: int
    chunk_total: int
    embedded_count: int
    embedding_status: Literal["DISABLED", "QUEUED", "PROCESSING", "COMPLETED", "FAILED"]
    embedding_model_id: UUID | None
    embedding_dimensions: int | None
    embedding_message: str
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    metadata: LegalMetadata = Field(default_factory=LegalMetadata)


class DocumentPage(BaseModel):
    items: list[DocumentView]
    total: int
    page: int
    page_size: int


class DocumentDetail(BaseModel):
    document: DocumentView
    result: ParseResult | None
    acknowledged_issues: list[str]


class CorrectionInput(BaseModel):
    expected_revision: int = Field(ge=1)
    metadata: LegalMetadata
    nodes: list[StructureNode] = Field(max_length=20000)
    source_kind: SourceKind
    source_url: str = Field(default="", max_length=2000)
    source_note: str = Field(default="", max_length=2000)
    verification_note: str = Field(default="", max_length=2000)
    legal_status: LegalStatus = "UNKNOWN"
    version_confirmed: bool = False
    acknowledged_issues: list[str] = Field(default_factory=list, max_length=20000)
    reason: str = Field(min_length=1, max_length=2000)


class ReviewInput(BaseModel):
    expected_revision: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=2000)


class AuditView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    action: str
    actor: str
    reason: str
    revision: int | None
    details: dict[str, object]
    created_at: datetime


class VersionCandidate(BaseModel):
    document: DocumentView
    match_reasons: list[str]
    same_content: bool


class ComparisonView(BaseModel):
    left: DocumentView
    right: DocumentView
    same_file: bool
    same_content: bool
    metadata_changes: dict[str, list[str | None]]
    diff: str
    truncated: bool


class SearchHit(BaseModel):
    document_id: UUID
    knowledge_base_id: UUID
    title: str
    filename: str
    content: str
    start: int
    end: int
    node_id: str | None
    revision: int
    source_kind: SourceKind
    legal_status: LegalStatus
    source_url: str
    score: float
    score_type: Literal["cosine", "keyword_coverage"]
    fusion_score: float
    bm25_score: float | None = None
    cosine_score: float | None = None
    keyword_coverage: float | None = None
    lexical_rank: int | None = None
    vector_rank: int | None = None


class SearchPage(BaseModel):
    items: list[SearchHit]
    total: int
    page: int
    page_size: int
    retrieval_method: Literal["hybrid", "keyword"]
    candidate_limit: int = 100


class VectorizeInput(ReviewInput):
    model_id: UUID


class SegmentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sequence: int
    node_id: str | None
    start: int
    end: int
    content: str


class SegmentPage(BaseModel):
    items: list[SegmentView]
    total: int
    page: int
    page_size: int
