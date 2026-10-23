export type ToolStatus =
  'preparing' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted'

export interface ToolActivity {
  id: string
  name: string
  status: ToolStatus
  answer_offset: number
  summary: string
  duration_ms: number | null
}

export function isToolActivity(value: unknown): value is ToolActivity {
  if (typeof value !== 'object' || value === null) return false
  const item = value as Record<string, unknown>
  return (
    typeof item.id === 'string' &&
    typeof item.name === 'string' &&
    typeof item.status === 'string' &&
    ['preparing', 'running', 'completed', 'failed', 'cancelled', 'interrupted'].includes(
      item.status,
    ) &&
    typeof item.answer_offset === 'number' &&
    Number.isSafeInteger(item.answer_offset) &&
    item.answer_offset >= 0 &&
    typeof item.summary === 'string' &&
    (item.duration_ms === null ||
      (typeof item.duration_ms === 'number' &&
        Number.isFinite(item.duration_ms) &&
        item.duration_ms >= 0))
  )
}

export function readToolActivities(value: unknown): ToolActivity[] {
  return Array.isArray(value) ? value.filter(isToolActivity) : []
}
