import type { VectorizationRequestMode } from '../system-config/types'

export interface FilterNode extends Record<string, unknown> {
  key: string
  label: string
  code_ids: number[]
  children: FilterNode[]
}

export interface PublicLawOptions {
  categories: FilterNode[]
  authorities: FilterNode[]
}

export type SortField = '-1' | 'flfg_code_id' | 'zdjg_code_id' | 'sxx' | 'gbrq' | 'sxrq' | '_score'

export interface PublicLawQuery {
  searchRange: 1 | 2
  sxrq: string[]
  gbrq: string[]
  searchType: 1 | 2
  sxx: number[]
  gbrqYear: number[]
  flfgCodeId: number[]
  zdjgCodeId: number[]
  searchContent: string
  orderByParam: { order: SortField; sort: '' | 'ASC' | 'DESC' }
  pageNum: number
  pageSize: 10 | 20 | 50
  vectorization: 'all' | 'not_vectorized'
  cursor: string | null
}

export type VectorizationStatus =
  'NOT_IMPORTED' | 'DISABLED' | 'QUEUED' | 'PROCESSING' | 'COMPLETED' | 'FAILED'

export interface PublicLawImportState {
  law_id: string
  document_id: string
  knowledge_base_id: string
  knowledge_base_name: string
  status: VectorizationStatus
  embedded_count: number
  chunk_count: number
}

export interface PublicLawImportResult {
  state: PublicLawImportState
  action: 'IMPORTED' | 'RETRIED' | 'EXISTING'
}

export interface VectorTaskItem {
  id: string
  law_id: string
  title: string
  status: 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'SKIPPED' | 'FAILED' | 'STOPPED'
  document_id: string | null
  error_message: string | null
  stage: string | null
  embedded_count: number
  chunk_count: number
}

export interface VectorTask {
  id: string
  status: 'RUNNING' | 'STOPPING' | 'STOPPED' | 'COMPLETED' | 'FAILED'
  knowledge_base_id: string
  request_mode: VectorizationRequestMode
  concurrency: number
  total: number | null
  discovered: number
  completed: number
  skipped: number
  failed: number
  current: VectorTaskItem | null
  current_items: VectorTaskItem[]
  stage: string | null
  embedded_count: number
  chunk_count: number
  recent: VectorTaskItem[]
  created_at: string
  finished_at: string | null
}

export interface PublicLaw {
  id: string
  title: string
  published_on: string | null
  effective_on: string | null
  status: number | null
  category: string
  authority: string
  source_url: string
  vectorization_status: VectorizationStatus
  imports: PublicLawImportState[]
}

export type PublicLawFormat = 'docx' | 'pdf'

export interface PublicLawDetail extends PublicLaw {
  preview_formats: PublicLawFormat[]
}

export interface PublicLawPage {
  items: PublicLaw[]
  total: number | null
  page: number
  page_size: number
  search_type: 1 | 2
  next_cursor: string | null
  has_more: boolean
}

export const vectorizationOptions = [
  { label: '全部向量状态', value: 'all' },
  { label: '未向量化', value: 'not_vectorized' },
]

export const vectorizationLabels: Record<VectorizationStatus, string> = {
  NOT_IMPORTED: '未导入知识库',
  DISABLED: '未向量化',
  QUEUED: '等待处理',
  PROCESSING: '处理中',
  COMPLETED: '已向量化',
  FAILED: '待重试',
}

export function applyImportStates(items: PublicLaw[], states: PublicLawImportState[]): void {
  const priorities: Record<VectorizationStatus, number> = {
    COMPLETED: 0,
    PROCESSING: 1,
    QUEUED: 2,
    FAILED: 3,
    DISABLED: 4,
    NOT_IMPORTED: 5,
  }
  for (const item of items) {
    item.imports = states
      .filter((state) => state.law_id === item.id)
      .sort((a, b) => priorities[a.status] - priorities[b.status])
    item.vectorization_status = item.imports[0]?.status ?? 'NOT_IMPORTED'
  }
}

export const statusOptions = [
  { label: '尚未生效', value: 4 },
  { label: '有效', value: 3 },
  { label: '已修改', value: 2 },
  { label: '已废止', value: 1 },
]

export const sortOptions: { label: string; value: SortField }[] = [
  { label: '默认排序', value: '-1' },
  { label: '法律法规分类', value: 'flfg_code_id' },
  { label: '制定机关', value: 'zdjg_code_id' },
  { label: '时效性', value: 'sxx' },
  { label: '公布日期', value: 'gbrq' },
  { label: '施行日期', value: 'sxrq' },
]

export function defaultQuery(): PublicLawQuery {
  return {
    searchRange: 1,
    sxrq: [],
    gbrq: [],
    searchType: 2,
    sxx: [],
    gbrqYear: [],
    flfgCodeId: [102, 110, 120, 130, 140, 150, 155, 160, 170],
    zdjgCodeId: [],
    searchContent: '',
    orderByParam: { order: '-1', sort: '' },
    pageNum: 1,
    pageSize: 20,
    vectorization: 'all',
    cursor: null,
  }
}

export function flattenNodes(nodes: FilterNode[]): FilterNode[] {
  return nodes.flatMap((node) => [node, ...flattenNodes(node.children)])
}

export function checkedKeys(nodes: FilterNode[], codes: number[]): string[] {
  return flattenNodes(nodes)
    .filter(
      (node) => node.code_ids.length > 0 && node.code_ids.every((code) => codes.includes(code)),
    )
    .map((node) => node.key)
}

export function selectedCodes(nodes: FilterNode[], keys: (string | number)[]): number[] {
  return [
    ...new Set(
      flattenNodes(nodes)
        .filter((node) => keys.includes(node.key))
        .flatMap((node) => node.code_ids),
    ),
  ]
}

export function filterLabel(nodes: FilterNode[], codes: number[]): string {
  const labels: string[] = []
  for (const node of nodes) {
    if (node.code_ids.length && node.code_ids.every((code) => codes.includes(code))) {
      labels.push(node.label)
    } else if (node.children.length) {
      const label = filterLabel(node.children, codes)
      if (label) labels.push(label)
    }
  }
  return labels.join('、')
}

export function exportDirectory(items: PublicLaw[]): void {
  const cell = (value: string): string => {
    const safe = /^\s*[=+\-@]/.test(value) ? `'${value}` : value
    return `"${safe.replaceAll('"', '""')}"`
  }
  const rows = [
    ['标题', '时效性', '公布日期', '施行日期', '法律法规分类', '制定机关', '官方原文'],
    ...items.map((item) => [
      item.title,
      statusOptions.find((option) => option.value === item.status)?.label ?? '未标注',
      item.published_on ?? '',
      item.effective_on ?? '',
      item.category,
      item.authority,
      item.source_url,
    ]),
  ]
  const url = URL.createObjectURL(
    new Blob(['\uFEFF' + rows.map((row) => row.map(cell).join(',')).join('\r\n')], {
      type: 'text/csv;charset=utf-8',
    }),
  )
  const link = document.createElement('a')
  link.href = url
  link.download = '公开法律库文件目录.csv'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
