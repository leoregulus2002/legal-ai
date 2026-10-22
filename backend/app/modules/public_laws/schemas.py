from datetime import date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from app.modules.knowledge.schemas import SourceMetadata

Code = Annotated[int, Field(ge=0, le=1000000)]
LawIdentifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")]
VectorizationStatus = Literal[
    "NOT_IMPORTED", "DISABLED", "QUEUED", "PROCESSING", "COMPLETED", "FAILED"
]


class OfficialRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class SortOrder(OfficialRequest):
    order: Literal["-1", "flfg_code_id", "zdjg_code_id", "sxx", "gbrq", "sxrq", "_score"] = "-1"
    sort: Literal["", "ASC", "DESC"] = ""

    @model_validator(mode="after")
    def validate_direction(self) -> Self:
        if (self.order == "-1") != (self.sort == ""):
            raise ValueError("排序字段与方向不匹配")
        return self


class PublicLawSearch(OfficialRequest):
    search_range: Literal[1, 2] = 1
    sxrq: list[date] = Field(default_factory=list, max_length=2)
    gbrq: list[date] = Field(default_factory=list, max_length=2)
    search_type: Literal[1, 2] = 2
    sxx: list[Literal[1, 2, 3, 4]] = Field(default_factory=list, max_length=4)
    gbrq_year: list[Annotated[int, Field(ge=1949, le=9999)]] = Field(
        default_factory=list, max_length=300
    )
    flfg_code_id: list[Code] = Field(default_factory=list, max_length=1000)
    zdjg_code_id: list[Code] = Field(default_factory=list, max_length=1000)
    search_content: str = Field(default="", max_length=500)
    order_by_param: SortOrder = Field(default_factory=SortOrder)
    page_num: int = Field(default=1, ge=1, le=100000)
    page_size: Literal[10, 20, 50] = 20
    vectorization: Literal["all", "not_vectorized"] = "all"
    cursor: str | None = Field(default=None, pattern=r"^[1-9]\d{0,5}:[0-4]?\d$")

    @field_validator("sxrq", "gbrq")
    @classmethod
    def validate_date_range(cls, values: list[date]) -> list[date]:
        if values and (len(values) != 2 or values[0] > values[1]):
            raise ValueError("日期区间必须包含有序的起止日期")
        return values


class FilterNode(BaseModel):
    key: str
    label: str
    code_ids: list[int]
    children: list["FilterNode"] = Field(default_factory=list)


class PublicLawOptions(BaseModel):
    categories: list[FilterNode]
    authorities: list[FilterNode]


class PublicLaw(BaseModel):
    id: str
    title: str
    published_on: str | None
    effective_on: str | None
    status: int | None
    category: str
    authority: str
    source_url: str
    vectorization_status: VectorizationStatus = "NOT_IMPORTED"
    imports: list["PublicLawImportState"] = Field(default_factory=list)


class PublicLawImportState(BaseModel):
    law_id: str
    document_id: UUID
    knowledge_base_id: UUID
    knowledge_base_name: str
    status: VectorizationStatus
    embedded_count: int
    chunk_count: int


class PublicLawDetail(PublicLaw):
    preview_formats: list[Literal["docx", "pdf"]]
    source_metadata: SourceMetadata


class PreviewLink(BaseModel):
    url: str


class PublicLawPage(BaseModel):
    items: list[PublicLaw]
    total: int | None
    page: int
    page_size: int
    search_type: Literal[1, 2]
    next_cursor: str | None = None
    has_more: bool = False


class DownloadRequest(BaseModel):
    ids: list[LawIdentifier] = Field(min_length=1, max_length=50)


class PublicLawImportInput(BaseModel):
    knowledge_base_id: UUID
    embedding_model_id: UUID
    decision: bool = False


class PublicLawMetadataInput(BaseModel):
    knowledge_base_id: UUID
    document_id: UUID
    expected_revision: int = Field(ge=1)


class PublicLawImportResult(BaseModel):
    state: PublicLawImportState
    action: Literal["IMPORTED", "RETRIED", "EXISTING"]


class DownloadLink(BaseModel):
    url: str


class VectorTaskLaw(BaseModel):
    id: LawIdentifier
    title: str = Field(min_length=1, max_length=1000)
    decision: bool = False


class VectorTaskInput(BaseModel):
    knowledge_base_id: UUID
    embedding_model_id: UUID
    query: PublicLawSearch | None = None
    laws: list[VectorTaskLaw] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if (self.query is None) == (not self.laws):
            raise ValueError("请选择检索范围或法规列表")
        return self


class VectorTaskItemView(BaseModel):
    id: UUID
    law_id: str
    title: str
    status: str
    document_id: UUID | None
    error_message: str | None
    stage: str | None = None
    embedded_count: int = 0
    chunk_count: int = 0


class VectorTaskView(BaseModel):
    id: UUID
    status: Literal["RUNNING", "STOPPING", "STOPPED", "COMPLETED", "FAILED"]
    knowledge_base_id: UUID
    request_mode: Literal["serial", "concurrent"]
    concurrency: int
    download_delay_ms: int
    total: int | None
    discovered: int
    completed: int
    skipped: int
    failed: int
    current: VectorTaskItemView | None
    current_items: list[VectorTaskItemView]
    stage: str | None
    embedded_count: int
    chunk_count: int
    recent: list[VectorTaskItemView]
    created_at: datetime
    finished_at: datetime | None
