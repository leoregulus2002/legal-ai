import { legalLabels, sourceLabels } from '../knowledge/types'
import type { RegulationDetail } from './types'

export function safeSource(value: string): string | undefined {
  try {
    const url = new URL(value)
    if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password)
      return url.href
  } catch {
    /* 缺失或无效的来源不提供跳转。 */
  }
  return undefined
}

export function citation(detail: RegulationDetail, nodeId?: string | null): string {
  const { regulation, text, nodes } = detail
  const node = nodes.find((item) => item.id === nodeId && item.kind === 'ARTICLE')
  const content = node ? Array.from(text).slice(node.start, node.end).join('') : text
  const meta = regulation.metadata
  return [
    `《${meta.title}》${node?.label ?? ''}`,
    content.trim(),
    `版本：${meta.version_label || '未提供'}；${legalLabels[regulation.legal_status]}`,
    `来源：${sourceLabels[regulation.source_kind]}；${safeSource(regulation.source_url) || '未提供有效来源链接'}`,
  ].join('\n\n')
}
