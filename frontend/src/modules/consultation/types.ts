import type { ModelConfig, Policy, SystemPrompt } from '../system-config/types'
import { isGeneratedFile, type GeneratedFile } from '../files/types'
import type { ToolActivity } from '../../components/toolActivity'

export interface Conversation {
  id: string
  title: string
  history_version: number
  updated_at: string
}
export interface Attachment {
  id: string
  name: string
  mime_type: string
  size: number
  bound: boolean
}
export interface Source {
  id: string
  title: string
  content: string
  source: string
  score: number
  score_type?: 'cosine' | 'keyword_coverage' | null
  fusion_score?: number | null
  bm25_score?: number | null
  cosine_score?: number | null
  keyword_coverage?: number | null
  lexical_rank?: number | null
  vector_rank?: number | null
  retrieval_method?: 'hybrid' | 'keyword' | 'external' | null
}
export interface Turn {
  id: string
  request_id: string
  sequence: number
  user_text: string
  answer: string
  reasoning?: string
  attachment_ids: string[]
  sources: Source[]
  config_snapshot: Record<string, unknown>
  created_at: string
  files?: GeneratedFile[]
}
export interface StoppedTurn {
  request_id: string
  conversation_id: string
  after_sequence: number
  user_text: string
  answer: string
  reasoning: string
  attachments: Attachment[]
  sources: Source[]
  model_name: string
  tool_calls?: ToolActivity[]
}
export interface ConsultationOptions {
  models: ModelConfig[]
  prompts: SystemPrompt[]
  policy: Policy
}
export interface GenerateInput {
  request_id: string
  model_id: string
  prompt_id?: string | null
  text: string
  attachment_ids: string[]
  knowledge_enabled: boolean
}

export interface ContextUsageInput {
  conversation_id: string | null
  model_id: string
  text: string
  attachment_ids: string[]
  knowledge_enabled: boolean
}

export interface ContextUsage {
  used_tokens: number | null
  context_tokens: number
  max_output_tokens: number
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
export function isSource(value: unknown): value is Source {
  return (
    isRecord(value) &&
    typeof value.id === 'string' &&
    typeof value.title === 'string' &&
    typeof value.content === 'string' &&
    typeof value.source === 'string' &&
    typeof value.score === 'number'
  )
}
export function isTurn(value: unknown): value is Turn {
  return (
    isRecord(value) &&
    typeof value.id === 'string' &&
    typeof value.request_id === 'string' &&
    typeof value.sequence === 'number' &&
    typeof value.user_text === 'string' &&
    typeof value.answer === 'string' &&
    (value.reasoning === undefined || typeof value.reasoning === 'string') &&
    Array.isArray(value.attachment_ids) &&
    value.attachment_ids.every((id: unknown) => typeof id === 'string') &&
    Array.isArray(value.sources) &&
    value.sources.every(isSource) &&
    isRecord(value.config_snapshot) &&
    typeof value.created_at === 'string' &&
    (value.files === undefined ||
      (Array.isArray(value.files) && value.files.every(isGeneratedFile)))
  )
}
