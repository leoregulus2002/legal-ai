export interface GeneratedFile {
  id: string
  name: string
  mime_type: string
  size: number
  created_at: string
}

export function isGeneratedFile(value: unknown): value is GeneratedFile {
  if (typeof value !== 'object' || value === null) return false
  const file = value as Record<string, unknown>
  return (
    typeof file.id === 'string' &&
    typeof file.name === 'string' &&
    typeof file.mime_type === 'string' &&
    typeof file.size === 'number' &&
    Number.isSafeInteger(file.size) &&
    file.size >= 0 &&
    typeof file.created_at === 'string'
  )
}
