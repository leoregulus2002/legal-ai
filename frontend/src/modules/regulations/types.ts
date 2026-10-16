import type { LegalMetadata, LegalStatus, SourceKind, StructureNode } from '../knowledge/types'

export interface Regulation {
  document_id: string
  knowledge_base_id: string
  knowledge_base_name: string
  revision: number
  metadata: LegalMetadata
  legal_status: LegalStatus
  source_kind: SourceKind
  version_confirmed: boolean
  source_url: string
  updated_at: string
  excerpt: string
  node_id: string | null
  article_label: string
  matched_articles: number
}
export interface RegulationPage {
  items: Regulation[]
  total: number
  page: number
  page_size: number
  highlight: string
}
export interface RegulationDetail {
  regulation: Regulation
  text: string
  nodes: StructureNode[]
}
export interface RegulationOptions {
  knowledge_bases: { id: string; name: string }[]
  authorities: string[]
  regions: string[]
  document_count: number
}
export const scopeOptions = [
  { label: '全部范围', value: 'all' },
  { label: '法规名称', value: 'title' },
  { label: '正文内容', value: 'body' },
  { label: '文号', value: 'number' },
]
export const sortOptions = [
  { label: '相关程度', value: 'relevance' },
  { label: '公布日期 · 从新到旧', value: 'promulgated_desc' },
  { label: '公布日期 · 从旧到新', value: 'promulgated_asc' },
  { label: '施行日期 · 从新到旧', value: 'effective_desc' },
  { label: '施行日期 · 从旧到新', value: 'effective_asc' },
]
