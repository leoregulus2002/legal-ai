export type DocumentKind = 'auto' | 'contract' | 'litigation' | 'judgment' | 'other'
export type Intent =
  | 'auto'
  | 'comprehensive'
  | 'summary'
  | 'contract_review'
  | 'litigation'
  | 'judgment'
  | 'compare'
  | 'question'
export type RunStatus =
  'queued' | 'running' | 'needs_input' | 'completed' | 'partial' | 'failed' | 'cancelled'
export type AgentRole = 'intent' | 'contract' | 'litigation' | 'judgment' | 'research' | 'review'
export interface WorkspaceView {
  id: string
  name: string
  created_at: string
  updated_at: string
}
export interface DocumentView {
  id: string
  workspace_id: string
  filename: string
  mime_type: string
  size: number
  sha256: string
  revision: number
  kind: DocumentKind
  status: 'ready' | 'needs_ocr'
  character_count: number
  created_at: string
}
export interface Span {
  id: string
  kind: string
  index: number
  start: number
  end: number
}
export interface DocumentDetail extends DocumentView {
  text: string
  spans: Span[]
}
export interface DocumentCitation {
  document_id: string
  revision: number
  span_id: string
  quote: string
}
export interface LawCitation {
  source_id: string
  quote: string
}
export interface Finding {
  id: string
  title: string
  severity: 'high' | 'medium' | 'low' | 'info'
  statement_type: 'contract_term' | 'party_claim' | 'evidence_record' | 'court_finding' | 'analysis'
  analysis: string
  suggestion: string
  evidence_status: 'supported' | 'limited' | 'unverified'
  document_citations: DocumentCitation[]
  law_citations: LawCitation[]
  uncertainty: string
}
export interface SourceView {
  id: string
  title: string
  content: string
  source: string
  metadata: Record<string, unknown>
}
export interface Report {
  summary: string
  findings: Finding[]
  timeline: string[]
  missing_materials: string[]
  limitations: string[]
  sources: SourceView[]
  review_summary: string
}
export interface IntentResult {
  primary_intent: Intent
  secondary_intents: Intent[]
  document_kinds: Record<string, DocumentKind>
  agents: string[]
  focus: string[]
  clarification: string | null
  rationale: string
  perspective: string
  jurisdiction: string
  relevant_date: string | null
  depth: 'standard' | 'deep'
  document_ids: string[] | null
  knowledge_base_ids: string[]
  mcp_server_ids: string[]
}
export interface StepView {
  id: string
  name: string
  agent: string
  status: string
  attempt: number
  summary: string
  started_at: string
  finished_at: string | null
}
export interface ToolCallView {
  id: string
  agent: string
  name: string
  status: string
  duration_ms: number
  created_at: string
}
export interface RunView {
  id: string
  workspace_id: string
  status: RunStatus
  failure_message: string | null
  stage: string
  instruction: string
  intent: IntentResult | null
  report: Report | null
  clarification: string | null
  parent_run_id: string | null
  created_at: string
  updated_at: string
  steps: StepView[]
  tool_calls: ToolCallView[]
  document_ids: string[]
  clarification_history: { question: string; answer: string }[]
}
export interface RunInput {
  request_id: string
  instruction: string
  document_ids?: string[]
  model_id?: string
  automatic?: boolean
  intent?: Intent
  perspective?: string
  jurisdiction?: string
  relevant_date?: string | null
  depth?: 'auto' | 'standard' | 'deep'
  knowledge_base_ids?: string[]
  mcp_server_ids?: string[]
  parent_run_id: string | null
}
export interface AgentConfig {
  model_id: string | null
  prompt_id: string | null
}
export interface AnalysisConfig {
  default_model_id: string | null
  knowledge_base_ids: string[]
  max_parallel_agents: number
  max_tool_calls: number
  max_model_calls: number
  timeout_seconds: number
  agent_configs: Partial<Record<AgentRole, AgentConfig>>
}
export interface MCPServerInput {
  name: string
  url: string
  token: string | null
  clear_token: boolean
  enabled: boolean
  allowed_tools: string[]
  timeout: number
  allow_document_content: boolean
}
export interface MCPServerView extends Omit<MCPServerInput, 'token' | 'clear_token'> {
  id: string
  has_token: boolean
}
export interface MCPTool {
  name: string
  description: string
  input_schema: Record<string, unknown>
}
export interface ModelOption {
  id: string
  name: string
  supports_tools: boolean
}
export interface AnalysisOptions {
  models: ModelOption[]
  knowledge_bases: { id: string; name: string }[]
  mcp_servers: MCPServerView[]
  config: AnalysisConfig
}
export const kindOptions = [
  { value: 'auto', label: '自动识别' },
  { value: 'contract', label: '合同' },
  { value: 'litigation', label: '诉讼材料' },
  { value: 'judgment', label: '裁判文书' },
  { value: 'other', label: '其他' },
]
export const intentOptions = [
  { value: 'auto', label: '自动识别意图' },
  { value: 'comprehensive', label: '综合分析' },
  { value: 'summary', label: '摘要' },
  { value: 'contract_review', label: '合同审阅' },
  { value: 'litigation', label: '诉讼分析' },
  { value: 'judgment', label: '裁判分析' },
  { value: 'compare', label: '文书比较' },
  { value: 'question', label: '文书问答' },
]
export const statusLabels: Record<RunStatus, string> = {
  queued: '排队中',
  running: '分析中',
  needs_input: '待澄清',
  completed: '已完成',
  partial: '部分完成',
  failed: '失败',
  cancelled: '已取消',
}
export function isActive(status: RunStatus): boolean {
  return status === 'queued' || status === 'running'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item: unknown) => typeof item === 'string')
}
function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}
function isReport(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.summary === 'string' &&
    typeof value.review_summary === 'string' &&
    isStringArray(value.timeline) &&
    isStringArray(value.missing_materials) &&
    isStringArray(value.limitations) &&
    Array.isArray(value.sources) &&
    value.sources.every(
      (item: unknown) =>
        isRecord(item) &&
        ['id', 'title', 'content', 'source'].every((key) => typeof item[key] === 'string') &&
        isRecord(item.metadata),
    ) &&
    Array.isArray(value.findings) &&
    value.findings.every(
      (item: unknown) =>
        isRecord(item) &&
        ['id', 'title', 'analysis', 'suggestion', 'uncertainty'].every(
          (key) => typeof item[key] === 'string',
        ) &&
        ['high', 'medium', 'low', 'info'].includes(String(item.severity)) &&
        ['contract_term', 'party_claim', 'evidence_record', 'court_finding', 'analysis'].includes(
          String(item.statement_type),
        ) &&
        ['supported', 'limited', 'unverified'].includes(String(item.evidence_status)) &&
        Array.isArray(item.document_citations) &&
        item.document_citations.every(
          (citation: unknown) =>
            isRecord(citation) &&
            ['document_id', 'span_id', 'quote'].every((key) => typeof citation[key] === 'string') &&
            typeof citation.revision === 'number',
        ) &&
        Array.isArray(item.law_citations) &&
        item.law_citations.every(
          (citation: unknown) =>
            isRecord(citation) &&
            typeof citation.source_id === 'string' &&
            typeof citation.quote === 'string',
        ),
    )
  )
}
export function isRunView(value: unknown): value is RunView {
  return (
    isRecord(value) &&
    ['id', 'workspace_id', 'stage', 'instruction', 'created_at', 'updated_at'].every(
      (key) => typeof value[key] === 'string',
    ) &&
    typeof value.status === 'string' &&
    Object.hasOwn(statusLabels, value.status) &&
    isNullableString(value.failure_message) &&
    isNullableString(value.clarification) &&
    isNullableString(value.parent_run_id) &&
    (value.intent === null ||
      (isRecord(value.intent) &&
        typeof value.intent.primary_intent === 'string' &&
        typeof value.intent.perspective === 'string' &&
        typeof value.intent.jurisdiction === 'string')) &&
    (value.report === null || isReport(value.report)) &&
    isStringArray(value.document_ids) &&
    Array.isArray(value.clarification_history) &&
    value.clarification_history.every(
      (item: unknown) =>
        isRecord(item) && typeof item.question === 'string' && typeof item.answer === 'string',
    ) &&
    Array.isArray(value.steps) &&
    value.steps.every(
      (item: unknown) =>
        isRecord(item) &&
        ['id', 'name', 'agent', 'status', 'summary', 'started_at'].every(
          (key) => typeof item[key] === 'string',
        ) &&
        typeof item.attempt === 'number' &&
        isNullableString(item.finished_at),
    ) &&
    Array.isArray(value.tool_calls) &&
    value.tool_calls.every(
      (item: unknown) =>
        isRecord(item) &&
        ['id', 'agent', 'name', 'status', 'created_at'].every(
          (key) => typeof item[key] === 'string',
        ) &&
        typeof item.duration_ms === 'number',
    )
  )
}
