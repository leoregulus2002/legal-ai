export type ImportMode = 'GENERAL' | 'LEGAL'
export type SourceKind = 'OFFICIAL_VERIFIED' | 'USER_UPLOADED' | 'THIRD_PARTY' | 'PENDING_REVIEW'
export type LegalStatus = 'UNKNOWN' | 'NOT_YET_EFFECTIVE' | 'EFFECTIVE' | 'AMENDED' | 'REPEALED'
export type DocumentStatus = 'QUEUED' | 'PROCESSING' | 'FAILED' | 'WITHDRAWN' | 'PUBLISHED'
export type NodeKind =
  | 'PART'
  | 'CHAPTER'
  | 'SECTION'
  | 'ARTICLE'
  | 'PARAGRAPH'
  | 'ITEM'
  | 'SUBITEM'
  | 'SUPPLEMENT'
  | 'ANNEX'
export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}
export interface KnowledgeBase {
  id: string
  name: string
  description: string
  created_at: string
  updated_at: string
}
export interface LegalMetadata {
  title: string
  authority: string
  document_number: string
  promulgated_on: string | null
  effective_on: string | null
  version_label: string
  category: LegalCategory
  region: string
}
export type LegalCategory =
  | 'UNCLASSIFIED'
  | 'CONSTITUTION'
  | 'LAW'
  | 'ADMINISTRATIVE_REGULATION'
  | 'SUPERVISION_REGULATION'
  | 'LOCAL_REGULATION'
  | 'DEPARTMENT_RULE'
  | 'LOCAL_GOVERNMENT_RULE'
  | 'JUDICIAL_INTERPRETATION'
  | 'OTHER'
export const categoryLabels: Record<LegalCategory, string> = {
  UNCLASSIFIED: '未分类',
  CONSTITUTION: '宪法',
  LAW: '法律',
  ADMINISTRATIVE_REGULATION: '行政法规',
  SUPERVISION_REGULATION: '监察法规',
  LOCAL_REGULATION: '地方性法规',
  DEPARTMENT_RULE: '部门规章',
  LOCAL_GOVERNMENT_RULE: '地方政府规章',
  JUDICIAL_INTERPRETATION: '司法解释',
  OTHER: '其他',
}
export interface KnowledgeDocument {
  id: string
  knowledge_base_id: string
  filename: string
  media_type: string
  size: number
  mode: ImportMode
  status: DocumentStatus
  source_kind: SourceKind
  source_url: string
  public_law_id: string | null
  source_metadata: SourceMetadata | null
  source_note: string
  verification_note: string
  legal_status: LegalStatus
  version_confirmed: boolean
  file_hash: string
  content_hash: string | null
  duplicate_of: string | null
  revision: number
  status_message: string
  created_at: string
  updated_at: string
  published_at: string | null
  metadata: LegalMetadata
  processing_stage: string
  failed_stage: string | null
  chunk_count: number
  chunk_total: number
  embedded_count: number
  embedding_status: 'DISABLED' | 'QUEUED' | 'PROCESSING' | 'COMPLETED' | 'FAILED'
  embedding_model_id: string | null
  embedding_dimensions: number | null
  embedding_message: string
}
export interface StructureNode {
  id: string
  kind: NodeKind
  label: string
  number: number | null
  suffix: number
  parent_id: string | null
  start: number
  end: number
}
export interface ParseIssue {
  id: string
  code: string
  severity: 'ERROR' | 'WARNING'
  message: string
  node_id: string | null
  start: number | null
  end: number | null
}
export interface ParseResult {
  parser_version: string
  method: 'RULE' | 'HUMAN' | 'AI_ASSISTED'
  text: string
  spans: { kind: string; index: number; start: number; end: number }[]
  nodes: StructureNode[]
  metadata: LegalMetadata
  metadata_sources: Record<string, 'TEXT' | 'OFFICIAL' | 'HUMAN'>
  anchors: { field: string; start: number; end: number; text: string }[]
  issues: ParseIssue[]
}
export interface SourceMetadata {
  metadata: LegalMetadata
  legal_status: LegalStatus
  source_url: string
  fetched_at: string
}
export interface DocumentDetail {
  document: KnowledgeDocument
  revision: number
  snapshot_state: Record<string, unknown>
  result: ParseResult | null
  publication: Publication | null
}
export interface Publication {
  revision: number
  published_at: string
  embedding_model_id: string | null
  embedding_dimensions: number | null
}
export interface CorrectionInput {
  expected_revision: number
  metadata: LegalMetadata
  nodes: StructureNode[]
  source_kind: SourceKind
  source_url: string
  source_note: string
  verification_note: string
  legal_status: LegalStatus
  version_confirmed: boolean
  reason: string
}
export interface SearchHit {
  document_id: string
  knowledge_base_id: string
  title: string
  filename: string
  content: string
  start: number
  end: number
  node_id: string | null
  revision: number
  source_kind: SourceKind
  legal_status: LegalStatus
  source_url: string
  score: number
  score_type: 'cosine' | 'keyword_coverage'
  fusion_score: number
  bm25_score: number | null
  cosine_score: number | null
  keyword_coverage: number | null
  lexical_rank: number | null
  vector_rank: number | null
}
export interface SearchPage extends Page<SearchHit> {
  retrieval_method: 'hybrid' | 'keyword'
  candidate_limit: number
}
export interface AuditEntry {
  id: string
  action: string
  actor: string
  reason: string
  revision: number | null
  details: Record<string, unknown>
  created_at: string
}
export interface VersionCandidate {
  document: KnowledgeDocument
  match_reasons: string[]
  same_content: boolean
}
export interface Comparison {
  left: KnowledgeDocument
  right: KnowledgeDocument
  same_file: boolean
  same_content: boolean
  metadata_changes: Record<string, [string | null, string | null]>
  diff: string
  truncated: boolean
}
export interface Segment {
  id: string
  sequence: number
  node_id: string | null
  start: number
  end: number
  content: string
}
export const statusLabels: Record<DocumentStatus, string> = {
  QUEUED: '等待处理',
  PROCESSING: '处理中',
  FAILED: '处理失败',
  WITHDRAWN: '已撤回',
  PUBLISHED: '已发布',
}
export const sourceLabels: Record<SourceKind, string> = {
  OFFICIAL_VERIFIED: '官方已核验',
  USER_UPLOADED: '用户上传',
  THIRD_PARTY: '第三方来源',
  PENDING_REVIEW: '来源待核验',
}
export const legalLabels: Record<LegalStatus, string> = {
  UNKNOWN: '效力待确认',
  NOT_YET_EFFECTIVE: '尚未施行',
  EFFECTIVE: '现行有效',
  AMENDED: '已修订',
  REPEALED: '已废止',
}
export const nodeLabels: Record<NodeKind, string> = {
  PART: '编',
  CHAPTER: '章',
  SECTION: '节',
  ARTICLE: '条',
  PARAGRAPH: '款',
  ITEM: '项',
  SUBITEM: '目',
  SUPPLEMENT: '附则',
  ANNEX: '附件',
}
export const stageLabels: Record<string, string> = {
  QUEUED: '等待处理',
  EXTRACTING: '文件解析',
  STRUCTURING: '法律条文结构化',
  VALIDATING: '数据校验',
  CHUNKING: '检索片段准备',
  VECTORIZING: '向量化处理',
  PUBLISHING: '自动发布',
  COMPLETED: '处理完成',
}
export const isProcessing = (doc: KnowledgeDocument): boolean =>
  ['QUEUED', 'PROCESSING'].includes(doc.status) ||
  ['QUEUED', 'PROCESSING'].includes(doc.embedding_status)
