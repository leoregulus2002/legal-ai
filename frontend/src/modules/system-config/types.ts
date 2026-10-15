export interface ModelInput {
  name: string
  model_type: 'chat' | 'embedding' | 'other'
  protocol: 'chat_completions' | 'responses'
  base_url: string
  model_name: string
  api_key?: string
  clear_api_key?: boolean
  enabled: boolean
  supports_images: boolean
  supports_pdf: boolean
  supports_json_mode: boolean
  context_tokens: number
  max_output_tokens: number
  token_parameter: 'max_tokens' | 'max_completion_tokens'
  temperature: number | null
}

export interface ModelConfig extends Omit<ModelInput, 'api_key' | 'clear_api_key'> {
  id: string
  has_api_key: boolean
}

export interface PromptInput {
  name: string
  content: string
  enabled: boolean
}
export interface SystemPrompt extends PromptInput {
  id: string
  version: number
}
export interface PromptVersion {
  version: number
  name: string
  content: string
}

export interface Policy {
  allowed_model_ids: string[]
  default_model_id: string | null
  default_prompt_id: string | null
  recent_turns: number
  summary_chars: number
  keyword_count: number
  memory_ttl_days: number
  knowledge_url: string
  knowledge_threshold: number
  knowledge_limit: number
  knowledge_timeout: number
  request_timeout: number
  max_attachments: number
  max_file_mb: number
  max_total_mb: number
}
export interface PolicyInput extends Policy {
  knowledge_api_key?: string
  clear_knowledge_api_key?: boolean
}
export interface PolicyView extends Policy {
  has_knowledge_api_key: boolean
}

export const defaultPolicy = (): Policy => ({
  allowed_model_ids: [],
  default_model_id: null,
  default_prompt_id: null,
  recent_turns: 6,
  summary_chars: 2000,
  keyword_count: 12,
  memory_ttl_days: 7,
  knowledge_url: '',
  knowledge_threshold: 0.7,
  knowledge_limit: 5,
  knowledge_timeout: 15,
  request_timeout: 300,
  max_attachments: 5,
  max_file_mb: 10,
  max_total_mb: 20,
})
