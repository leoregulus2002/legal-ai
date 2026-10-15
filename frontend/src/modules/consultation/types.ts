import type { ModelConfig, Policy, SystemPrompt } from '../system-config/types'

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
}
export interface Turn {
  id: string
  request_id: string
  sequence: number
  user_text: string
  answer: string
  attachment_ids: string[]
  sources: Source[]
  config_snapshot: Record<string, unknown>
  created_at: string
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
    Array.isArray(value.attachment_ids) &&
    value.attachment_ids.every((id: unknown) => typeof id === 'string') &&
    Array.isArray(value.sources) &&
    value.sources.every(isSource) &&
    isRecord(value.config_snapshot) &&
    typeof value.created_at === 'string'
  )
}
