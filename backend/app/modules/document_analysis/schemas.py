from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.modules.files.schemas import GeneratedFileView

DocumentKind = Literal["auto", "contract", "litigation", "judgment", "other"]
Intent = Literal[
    "comprehensive", "summary", "contract_review", "litigation", "judgment", "compare", "question"
]
RunStatus = Literal[
    "queued", "running", "needs_input", "completed", "partial", "failed", "cancelled"
]
AgentRole = Literal["contract", "litigation", "judgment", "research", "review"]
AnalysisRole = AgentRole | Literal["intent"]
ROLE_LABELS: dict[AnalysisRole, str] = {
    "intent": "意图识别与任务规划",
    "contract": "合同分析",
    "litigation": "诉讼与材料分析",
    "judgment": "裁判文书分析",
    "research": "法律研究与工具检索",
    "review": "报告独立复核",
}


class WorkspaceInput(BaseModel):
    name: str = Field(default="新文书分析", min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("empty name")
        return value.strip()


class WorkspaceView(WorkspaceInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    updated_at: datetime


class Span(BaseModel):
    id: str
    kind: str
    index: int
    start: int
    end: int


class DocumentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    filename: str
    mime_type: str
    size: int
    sha256: str
    revision: int
    kind: DocumentKind
    status: Literal["ready", "needs_ocr"]
    character_count: int
    created_at: datetime


class DocumentDetail(DocumentView):
    text: str
    spans: list[Span]


class DocumentUpdate(BaseModel):
    kind: DocumentKind


class RunInput(BaseModel):
    request_id: UUID
    instruction: str = Field(min_length=1, max_length=10000)
    document_ids: list[UUID] = Field(default_factory=list, max_length=30)
    model_id: UUID | None = None
    automatic: bool = True
    intent: Literal[
        "auto",
        "comprehensive",
        "summary",
        "contract_review",
        "litigation",
        "judgment",
        "compare",
        "question",
    ] = "auto"
    perspective: str = Field(default="auto", max_length=100)
    jurisdiction: str = Field(default="auto", min_length=1, max_length=100)
    relevant_date: date | None = None
    depth: Literal["auto", "standard", "deep"] = "auto"
    knowledge_base_ids: list[UUID] = Field(default_factory=list, max_length=100)
    mcp_server_ids: list[UUID] = Field(default_factory=list, max_length=10)
    parent_run_id: UUID | None = None

    @field_validator("instruction", "jurisdiction")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("empty input")
        return value.strip()


class ResumeInput(BaseModel):
    answer: str = Field(min_length=1, max_length=10000)


class IntentResult(BaseModel):
    file_requested: bool = False
    conversation_title: str = Field(default="", max_length=40)
    primary_intent: Intent = "comprehensive"
    secondary_intents: list[Intent] = Field(default_factory=list, max_length=6)
    document_kinds: dict[str, DocumentKind] = Field(default_factory=dict)
    agents: list[Literal["contract", "litigation", "judgment"]] = Field(
        default_factory=list, max_length=3
    )
    focus: list[str] = Field(default_factory=list, max_length=12)
    clarification: str | None = Field(default=None, max_length=1000)
    rationale: str = Field(default="", max_length=1000)
    perspective: str = Field(default="中立", min_length=1, max_length=100)
    jurisdiction: str = Field(default="中国大陆", min_length=1, max_length=100)
    relevant_date: date | None = None
    depth: Literal["standard", "deep"] = "standard"
    document_ids: list[UUID] | None = Field(default=None, max_length=30)
    knowledge_base_ids: list[UUID] = Field(default_factory=list, max_length=100)
    mcp_server_ids: list[UUID] = Field(default_factory=list, max_length=10)

    @field_validator("conversation_title", mode="before")
    @classmethod
    def clean_conversation_title(cls, value: object) -> str:
        if not isinstance(value, str):
            return ""
        return " ".join(value.split()).strip("\"'“”《》` ")[:40]


class IntentPlan(IntentResult):
    # AI 必须明确给出选择；历史存储视图保留默认值以兼容已有任务。
    primary_intent: Intent = Field(...)
    file_requested: bool = Field(...)
    perspective: str = Field(min_length=1, max_length=100)
    jurisdiction: str = Field(min_length=1, max_length=100)
    depth: Literal["standard", "deep"] = Field(...)
    document_ids: list[UUID] | None = Field(max_length=30)
    knowledge_base_ids: list[UUID] = Field(max_length=100)
    mcp_server_ids: list[UUID] = Field(max_length=10)


class DocumentCitation(BaseModel):
    document_id: UUID
    revision: int = Field(ge=1)
    span_id: str
    quote: str = Field(min_length=1, max_length=2000)


class LawCitation(BaseModel):
    source_id: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=2000)


class Finding(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    severity: Literal["high", "medium", "low", "info"] = "info"
    statement_type: Literal[
        "contract_term", "party_claim", "evidence_record", "court_finding", "analysis"
    ] = "analysis"
    analysis: str = Field(min_length=1, max_length=6000)
    suggestion: str = Field(default="", max_length=4000)
    evidence_status: Literal["supported", "limited", "unverified"] = "unverified"
    document_citations: list[DocumentCitation] = Field(default_factory=list, max_length=20)
    law_citations: list[LawCitation] = Field(default_factory=list, max_length=20)
    uncertainty: str = Field(default="", max_length=2000)


class AgentReport(BaseModel):
    summary: str = Field(min_length=1, max_length=6000)
    findings: list[Finding] = Field(default_factory=list, max_length=40)
    timeline: list[str] = Field(
        default_factory=list,
        max_length=50,
        description=(
            "时间线必须是字符串数组，每项用文字描述材料支持的日期及事件。"
            "不得返回日期/事件对象，不得推断或补造未知日期；无依据时返回空数组。"
        ),
    )
    missing_materials: list[str] = Field(default_factory=list, max_length=30)


class ReviewResult(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)
    issues: list[str] = Field(default_factory=list, max_length=40)
    rejected_finding_ids: list[str] = Field(default_factory=list, max_length=100)
    revise_agents: list[Literal["contract", "litigation", "judgment"]] = Field(
        default_factory=list, max_length=3
    )

    @field_validator("summary")
    @classmethod
    def substantive_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("empty review")
        return value.strip()


class SourceView(BaseModel):
    id: str
    title: str
    content: str
    source: str
    metadata: dict[str, object] = Field(default_factory=dict)


class Report(BaseModel):
    summary: str
    findings: list[Finding]
    timeline: list[str] = Field(default_factory=list)
    missing_materials: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    sources: list[SourceView] = Field(default_factory=list)
    review_summary: str = ""


class StepView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    agent: str
    status: str
    attempt: int
    summary: str
    started_at: datetime
    finished_at: datetime | None


class ToolCallView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    agent: str
    name: str
    status: str
    duration_ms: int
    created_at: datetime


class RunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    workspace_name: str | None = None
    files: list[GeneratedFileView] = Field(default_factory=list)
    status: RunStatus
    stage: str
    instruction: str
    intent: IntentResult | None
    report: Report | None
    clarification: str | None
    parent_run_id: UUID | None
    created_at: datetime
    updated_at: datetime
    steps: list[StepView] = Field(default_factory=list)
    tool_calls: list[ToolCallView] = Field(default_factory=list)
    failure_message: str | None = None
    document_ids: list[UUID] = Field(default_factory=list)
    clarification_history: list[dict[str, str]] = Field(default_factory=list)


class MCPServerInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=1000)
    token: SecretStr | None = Field(default=None, max_length=4000)
    clear_token: bool = False
    enabled: bool = False
    allowed_tools: list[str] = Field(default_factory=list, max_length=30)
    timeout: int = Field(default=30, ge=5, le=120)
    allow_document_content: bool = False


class MCPServerView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    url: str
    enabled: bool
    allowed_tools: list[str]
    timeout: int
    allow_document_content: bool
    has_token: bool


class AgentConfig(BaseModel):
    model_id: UUID | None = None
    prompt_id: UUID | None = None
    # 仅用于读取集中管理之前的历史任务快照，不再对外返回或保存内联提示词。
    prompt: str = Field(default="", max_length=12000, exclude=True)


class PromptSnapshot(BaseModel):
    id: UUID
    name: str
    version: int
    content: str


class AnalysisConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    default_model_id: UUID | None = None
    knowledge_base_ids: list[UUID] = Field(default_factory=list, max_length=100)
    max_parallel_agents: int = Field(default=2, ge=1, le=3)
    max_tool_calls: int = Field(default=24, ge=1, le=100)
    max_model_calls: int = Field(default=24, ge=6, le=80)
    timeout_seconds: int = Field(default=900, ge=60, le=3600)
    agent_configs: dict[AnalysisRole, AgentConfig] = Field(default_factory=dict)
