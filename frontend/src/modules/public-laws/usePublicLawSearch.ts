import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useErrorMessage } from '../../composables/useErrorMessage'
import { publicLawApi } from './api'
import { applyImportStates, defaultQuery, filterLabel, statusOptions } from './types'
import type { PublicLawPage, PublicLawQuery, SortField } from './types'

type FilterKey =
  | 'searchContent'
  | 'flfgCodeId'
  | 'zdjgCodeId'
  | 'sxx'
  | 'gbrqYear'
  | 'gbrq'
  | 'sxrq'
  | 'vectorization'

export function usePublicLawSearch() {
  const message = useMessage()
  const showError = useErrorMessage()
  const form = reactive(defaultQuery())
  const applied = ref(defaultQuery())
  const options = ref<Awaited<ReturnType<typeof publicLawApi.options>>>()
  const result = ref<PublicLawPage>()
  const loading = ref(false)
  const optionsLoading = ref(false)
  const selected = ref<string[]>([])
  const dateRanges = reactive({
    publishedFrom: '',
    publishedTo: '',
    effectiveFrom: '',
    effectiveTo: '',
  })
  let sequence = 0
  let alive = true
  let effectiveSearchType: 1 | 2 = form.searchType
  let statusTimer: ReturnType<typeof setTimeout> | undefined
  let statusSequence = 0
  let statusFailures = 0
  const cursors = new Map<number, string | null>([[1, null]])

  const chips = computed(() => {
    const query = applied.value
    const values: { key: FilterKey; label: string }[] = []
    if (query.searchContent)
      values.push({
        key: 'searchContent',
        label: `${query.searchRange === 1 ? '标题' : '正文'}：${query.searchContent}`,
      })
    if (query.flfgCodeId.length)
      values.push({
        key: 'flfgCodeId',
        label: `分类：${filterLabel(options.value?.categories ?? [], query.flfgCodeId) || '已选法律分类'}`,
      })
    if (query.zdjgCodeId.length)
      values.push({
        key: 'zdjgCodeId',
        label: `制定机关：${filterLabel(options.value?.authorities ?? [], query.zdjgCodeId) || '已选机关'}`,
      })
    if (query.sxx.length)
      values.push({
        key: 'sxx',
        label: `时效性：${statusOptions
          .filter((option) => query.sxx.includes(option.value))
          .map((option) => option.label)
          .join('、')}`,
      })
    if (query.gbrqYear.length)
      values.push({ key: 'gbrqYear', label: `公布年份：${query.gbrqYear.join('、')}` })
    if (query.gbrq.length)
      values.push({ key: 'gbrq', label: `公布日期：${query.gbrq.join(' 至 ')}` })
    if (query.sxrq.length)
      values.push({ key: 'sxrq', label: `施行日期：${query.sxrq.join(' 至 ')}` })
    if (query.vectorization === 'not_vectorized')
      values.push({ key: 'vectorization', label: '向量状态：未向量化' })
    return values
  })

  function scheduleStatusRefresh(delay = 3000): void {
    clearTimeout(statusTimer)
    if (
      alive &&
      statusFailures < 3 &&
      result.value?.items.some((item) =>
        item.imports.some((state) => ['QUEUED', 'PROCESSING'].includes(state.status)),
      )
    ) {
      statusTimer = setTimeout(() => {
        void refreshImportStates()
      }, delay)
    }
  }

  async function refreshImportStates(): Promise<void> {
    const request = sequence
    const stateRequest = ++statusSequence
    const page = result.value
    if (!page?.items.length || loading.value) return
    try {
      const states = await publicLawApi.importStatus(page.items.map((item) => item.id))
      if (!alive || request !== sequence || stateRequest !== statusSequence) return
      statusFailures = 0
      applyImportStates(page.items, states)
      if (
        applied.value.vectorization === 'not_vectorized' &&
        page.items.some((item) => item.vectorization_status === 'COMPLETED')
      ) {
        await fetchPage({ ...applied.value, cursor: null, pageNum: 1 }, true)
        return
      }
      scheduleStatusRefresh()
    } catch (error: unknown) {
      if (alive && request === sequence && stateRequest === statusSequence) {
        statusFailures++
        if (statusFailures === 1) showError(error)
        scheduleStatusRefresh(Math.min(3000 * 2 ** statusFailures, 15000))
      }
    }
  }

  async function fetchPage(query: PublicLawQuery, continueSearch = false): Promise<void> {
    const request = ++sequence
    statusFailures = 0
    clearTimeout(statusTimer)
    if (query.pageNum === 1) {
      cursors.clear()
      cursors.set(1, null)
    }
    const snapshot: PublicLawQuery = {
      ...query,
      sxrq: [...query.sxrq],
      gbrq: [...query.gbrq],
      sxx: [...query.sxx],
      gbrqYear: [...query.gbrqYear],
      flfgCodeId: [...query.flfgCodeId],
      zdjgCodeId: [...query.zdjgCodeId],
      orderByParam: { ...query.orderByParam },
    }
    if (!continueSearch) effectiveSearchType = snapshot.searchType
    const requestSearchType = effectiveSearchType
    applied.value = snapshot
    loading.value = true
    result.value = undefined
    selected.value = []
    try {
      const data = await publicLawApi.search({
        ...snapshot,
        searchType: requestSearchType,
      })
      if (!alive || request !== sequence) return
      result.value = data
      if (data.next_cursor) cursors.set(data.page + 1, data.next_cursor)
      scheduleStatusRefresh()
      effectiveSearchType = data.search_type
      if (requestSearchType === 1 && data.search_type === 2 && snapshot.searchContent) {
        message.info('没有精确匹配结果，公开法律库已切换为模糊检索')
      }
    } catch (error: unknown) {
      if (alive && request === sequence) showError(error)
    } finally {
      if (alive && request === sequence) loading.value = false
    }
  }

  async function submit(): Promise<void> {
    const ranges = [
      [dateRanges.publishedFrom, dateRanges.publishedTo],
      [dateRanges.effectiveFrom, dateRanges.effectiveTo],
    ]
    for (const [from, to] of ranges) {
      if (Boolean(from) !== Boolean(to)) {
        message.warning('请选择完整的开始和结束日期')
        return
      }
      if (from && to && from > to) {
        message.warning('开始日期不能晚于结束日期')
        return
      }
    }
    form.gbrq = dateRanges.publishedFrom ? [dateRanges.publishedFrom, dateRanges.publishedTo] : []
    form.sxrq = dateRanges.effectiveFrom ? [dateRanges.effectiveFrom, dateRanges.effectiveTo] : []
    await fetchPage({ ...form, searchContent: form.searchContent.trim(), cursor: null, pageNum: 1 })
  }

  async function loadOptions(): Promise<void> {
    optionsLoading.value = true
    try {
      const data = await publicLawApi.options()
      if (alive) options.value = data
    } catch (error: unknown) {
      if (alive) showError(error)
    } finally {
      if (alive) optionsLoading.value = false
    }
  }

  function changeSort(order: SortField): void {
    const current = applied.value.orderByParam
    const sort =
      order === '-1'
        ? ''
        : current.order === order
          ? current.sort === 'DESC'
            ? 'ASC'
            : 'DESC'
          : ['flfg_code_id', 'zdjg_code_id'].includes(order)
            ? 'ASC'
            : 'DESC'
    form.orderByParam = { order, sort }
    void fetchPage(
      { ...applied.value, orderByParam: { order, sort }, cursor: null, pageNum: 1 },
      true,
    )
  }

  function removeFilter(key: FilterKey): void {
    const next = {
      ...applied.value,
      [key]: key === 'searchContent' ? '' : key === 'vectorization' ? 'all' : [],
      cursor: null,
      pageNum: 1,
    }
    Object.assign(form, next)
    dateRanges.publishedFrom = next.gbrq[0] ?? ''
    dateRanges.publishedTo = next.gbrq[1] ?? ''
    dateRanges.effectiveFrom = next.sxrq[0] ?? ''
    dateRanges.effectiveTo = next.sxrq[1] ?? ''
    void fetchPage(next)
  }

  function clearFilters(): void {
    const next = { ...defaultQuery(), flfgCodeId: [], pageSize: applied.value.pageSize }
    Object.assign(form, next)
    Object.assign(dateRanges, {
      publishedFrom: '',
      publishedTo: '',
      effectiveFrom: '',
      effectiveTo: '',
    })
    void fetchPage(next)
  }

  function changePage(pageNum: number): void {
    const cursor = applied.value.vectorization === 'not_vectorized' ? cursors.get(pageNum) : null
    if (cursor === undefined) return
    void fetchPage({ ...applied.value, cursor, pageNum }, true)
  }

  function changePageSize(pageSize: number): void {
    if (pageSize !== 10 && pageSize !== 20 && pageSize !== 50) return
    form.pageSize = pageSize
    void fetchPage({ ...applied.value, pageSize, cursor: null, pageNum: 1 }, true)
  }

  onMounted(() => {
    void loadOptions()
    void fetchPage(form)
  })
  onUnmounted(() => {
    alive = false
    sequence++
    clearTimeout(statusTimer)
  })

  return {
    form,
    applied,
    options,
    result,
    loading,
    optionsLoading,
    selected,
    dateRanges,
    chips,
    submit,
    loadOptions,
    changeSort,
    removeFilter,
    clearFilters,
    changePage,
    changePageSize,
    refreshImportStates,
    retry: () =>
      fetchPage(
        applied.value.vectorization === 'not_vectorized'
          ? { ...applied.value, cursor: null, pageNum: 1 }
          : applied.value,
        true,
      ),
  }
}
