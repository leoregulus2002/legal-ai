<script setup lang="ts">
import { computed, onUnmounted, ref, toRaw } from 'vue'
import {
  NButton,
  NCheckbox,
  NCheckboxGroup,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NInput,
  NPagination,
  NRadio,
  NRadioGroup,
  NSelect,
  NSpin,
  NTag,
  NTree,
  useMessage,
} from 'naive-ui'
import AppIcon from '../../../components/AppIcon.vue'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import { publicLawApi } from '../api'
import PublicLawPreview from '../components/PublicLawPreview.vue'
import PublicLawImportDialog from '../components/PublicLawImportDialog.vue'
import PublicLawVectorProgress from '../components/PublicLawVectorProgress.vue'
import {
  checkedKeys,
  exportDirectory,
  flattenNodes,
  selectedCodes,
  sortOptions,
  statusOptions,
  vectorizationLabels,
  vectorizationOptions,
} from '../types'
import type { PublicLaw, PublicLawQuery } from '../types'
import { usePublicLawSearch } from '../usePublicLawSearch'
import { usePublicLawDownload } from '../usePublicLawDownload'
import { usePublicLawVectorTask } from '../usePublicLawVectorTask'
import '../styles.css'

const {
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
  retry,
  refreshImportStates,
} = usePublicLawSearch()
const showError = useErrorMessage()
const message = useMessage()
const filtersOpen = ref(false)
const advancedOpen = ref(false)
const downloading = ref(false)
const downloadDrawer = ref(false)
const downloadLinks = ref<{ url: string; title: string }[]>([])
const previewLaw = ref<PublicLaw | null>(null)
const importLaws = ref<PublicLaw[]>([])
const vectorQuery = ref<PublicLawQuery | null>(null)
const vectorTask = usePublicLawVectorTask(() => {
  void refreshImportStates()
})
const { task, active: vectorizing, stopping, loading: taskLoading } = vectorTask
const { downloadingId, download } = usePublicLawDownload()
let alive = true
onUnmounted(() => {
  alive = false
})

const categoryKeys = computed(() => checkedKeys(options.value?.categories ?? [], form.flfgCodeId))
const authorityKeys = computed(() => checkedKeys(options.value?.authorities ?? [], form.zdjgCodeId))
const expandedCategoryKeys = computed(() =>
  flattenNodes(options.value?.categories ?? [])
    .filter(
      (node) =>
        node.children.length && node.code_ids.some((code) => form.flfgCodeId.includes(code)),
    )
    .map((node) => node.key),
)
const selectedItems = computed(
  () => result.value?.items.filter((item) => selected.value.includes(item.id)) ?? [],
)
const allSelected = computed(
  () =>
    Boolean(result.value?.items.length) &&
    selectedItems.value.length === result.value?.items.length,
)
const yearOptions = Array.from({ length: new Date().getFullYear() - 1948 }, (_, index) => {
  const year = new Date().getFullYear() - index
  return { label: `${year} 年`, value: year }
})

function selectAll(checked: boolean): void {
  selected.value = checked ? (result.value?.items.map((item) => item.id) ?? []) : []
}

function toggleItem(id: string, checked: boolean): void {
  selected.value = checked
    ? [...new Set([...selected.value, id])]
    : selected.value.filter((value) => value !== id)
}

function statusLabel(item: PublicLaw): string {
  return statusOptions.find((option) => option.value === item.status)?.label ?? '未标注'
}

async function prepareDownloads(): Promise<void> {
  if (!selectedItems.value.length || downloading.value) return
  const items = [...selectedItems.value]
  downloading.value = true
  try {
    const links = await publicLawApi.downloads(items.map((item) => item.id))
    if (!alive) return
    downloadLinks.value = links.map((link, index) => ({
      url: link.url,
      title: `下载文件 ${index + 1}`,
    }))
    downloadDrawer.value = true
  } catch (error: unknown) {
    if (alive) showError(error)
  } finally {
    if (alive) downloading.value = false
  }
}

function exportSelected(): void {
  if (!selectedItems.value.length) return
  exportDirectory(selectedItems.value)
  message.success(`已导出 ${selectedItems.value.length} 条文件目录`)
}

function startVectorization(): void {
  vectorQuery.value = structuredClone(toRaw(applied.value))
}

function closeImport(): void {
  importLaws.value = []
  vectorQuery.value = null
}
</script>

<template>
  <section class="public-law-page" aria-labelledby="public-law-title">
    <header class="public-law-header">
      <div>
        <span class="public-law-eyebrow">PUBLIC LEGAL LIBRARY</span>
        <h1 id="public-law-title">公开法律库</h1>
        <p>检索公开法律法规，查阅官方原文。</p>
      </div>
      <div class="public-law-header-actions">
        <NButton
          type="primary"
          :disabled="vectorizing || taskLoading || loading"
          @click="startVectorization"
        >
          {{ vectorizing ? '向量化进行中' : '一键向量化' }}
        </NButton>
        <span class="public-law-source">
          <AppIcon name="column" :size="20" />
          <span>国家法律法规数据库</span>
        </span>
      </div>
    </header>

    <PublicLawVectorProgress
      v-if="task"
      :task="task"
      :stopping="stopping"
      @stop="vectorTask.stop"
      @refresh="vectorTask.refresh"
    />

    <form class="public-law-search" @submit.prevent="submit()">
      <div class="public-law-search-line">
        <NSelect
          v-model:value="form.searchRange"
          :options="[
            { label: '标题', value: 1 },
            { label: '正文', value: 2 },
          ]"
          aria-label="检索范围"
          class="public-law-scope"
        />
        <NInput
          v-model:value="form.searchContent"
          placeholder="输入法律法规名称或关键词"
          aria-label="搜索公开法律法规"
          :maxlength="500"
          clearable
          size="large"
        />
        <NButton type="primary" size="large" attr-type="submit" :loading="loading"
          ><template #icon><AppIcon name="search" :size="18" /></template>检索</NButton
        >
        <NButton size="large" :aria-expanded="advancedOpen" @click="advancedOpen = !advancedOpen"
          >高级筛选<AppIcon name="chevron-down" :size="14"
        /></NButton>
      </div>
      <div class="public-law-search-meta">
        <NRadioGroup v-model:value="form.searchType" name="public-law-match" aria-label="匹配方式">
          <NRadio :value="1">精确</NRadio><NRadio :value="2">模糊</NRadio>
        </NRadioGroup>
        <span>数据来源于全国人大常委会办公厅维护的国家法律法规数据库</span>
      </div>
      <div v-if="advancedOpen" class="public-law-advanced">
        <fieldset>
          <legend>公布日期</legend>
          <div>
            <input
              v-model="dateRanges.publishedFrom"
              type="date"
              min="1949-01-01"
              max="9999-12-31"
              aria-label="公布开始日期"
            /><span>至</span
            ><input
              v-model="dateRanges.publishedTo"
              type="date"
              min="1949-01-01"
              max="9999-12-31"
              aria-label="公布结束日期"
            />
          </div>
        </fieldset>
        <fieldset>
          <legend>施行日期</legend>
          <div>
            <input
              v-model="dateRanges.effectiveFrom"
              type="date"
              min="1949-01-01"
              max="9999-12-31"
              aria-label="施行开始日期"
            /><span>至</span
            ><input
              v-model="dateRanges.effectiveTo"
              type="date"
              min="1949-01-01"
              max="9999-12-31"
              aria-label="施行结束日期"
            />
          </div>
        </fieldset>
        <NButton type="primary" attr-type="submit" :loading="loading">应用筛选</NButton>
      </div>
    </form>

    <div class="public-law-conditions" aria-label="已应用的检索条件">
      <span>检索条件</span>
      <div class="public-law-chips">
        <NTag
          v-for="chip in chips"
          :key="chip.key"
          closable
          round
          :title="chip.label"
          @close="removeFilter(chip.key)"
          >{{ chip.label }}</NTag
        >
        <span v-if="!chips.length" class="public-law-muted">全部公开法律法规</span>
      </div>
      <NButton text :disabled="!chips.length || loading" @click="clearFilters">清空条件</NButton>
    </div>

    <div class="public-law-layout">
      <aside
        class="public-law-filters"
        :class="{ 'is-open': filtersOpen }"
        aria-label="法律法规筛选"
      >
        <button
          class="public-law-filter-heading"
          :aria-expanded="filtersOpen"
          @click="filtersOpen = !filtersOpen"
        >
          <span><AppIcon name="book" :size="17" />法律法规分类</span
          ><AppIcon class="public-law-mobile-chevron" name="chevron-down" :size="16" />
        </button>
        <div class="public-law-filter-content">
          <div class="public-law-vector-filter">
            <h2>知识库向量状态</h2>
            <NSelect
              v-model:value="form.vectorization"
              :options="vectorizationOptions"
              aria-label="向量化状态筛选"
              @update:value="submit()"
            />
            <p>任一知识库已完成向量化，即视为已向量化。处理中及待重试法规仍可筛选。</p>
          </div>
          <NSpin :show="optionsLoading">
            <NTree
              v-if="options"
              :data="options.categories"
              :checked-keys="categoryKeys"
              checkable
              cascade
              check-strategy="all"
              block-line
              :default-expanded-keys="expandedCategoryKeys"
              :selectable="false"
              @update:checked-keys="
                (keys) => {
                  form.flfgCodeId = selectedCodes(options?.categories ?? [], keys)
                  void submit()
                }
              "
            />
            <NButton v-else text :disabled="optionsLoading" @click="loadOptions"
              >重新加载分类</NButton
            >
          </NSpin>
          <div class="public-law-filter-section">
            <h2>时效性</h2>
            <NCheckboxGroup v-model:value="form.sxx" @update:value="submit()"
              ><NCheckbox
                v-for="option in statusOptions"
                :key="option.value"
                :value="option.value"
                :label="option.label"
            /></NCheckboxGroup>
          </div>
          <div class="public-law-filter-section">
            <h2>制定机关</h2>
            <NTree
              v-if="options"
              :data="options.authorities"
              :checked-keys="authorityKeys"
              checkable
              cascade
              check-strategy="all"
              block-line
              :selectable="false"
              @update:checked-keys="
                (keys) => {
                  form.zdjgCodeId = selectedCodes(options?.authorities ?? [], keys)
                  void submit()
                }
              "
            />
          </div>
          <div class="public-law-filter-section">
            <h2>公布年份</h2>
            <NSelect
              v-model:value="form.gbrqYear"
              :options="yearOptions"
              multiple
              clearable
              filterable
              placeholder="全部年份"
              aria-label="公布年份"
              @update:value="submit()"
            />
          </div>
        </div>
      </aside>

      <div class="public-law-results" aria-label="法律法规检索结果" :aria-busy="loading">
        <div class="public-law-sort">
          <span>排序</span>
          <NButton
            v-for="sort in sortOptions"
            :key="sort.value"
            size="small"
            :type="applied.orderByParam.order === sort.value ? 'primary' : 'default'"
            :secondary="applied.orderByParam.order === sort.value"
            :aria-pressed="applied.orderByParam.order === sort.value"
            :disabled="loading"
            @click="changeSort(sort.value)"
            >{{ sort.label
            }}<span v-if="sort.value !== '-1'" class="public-law-sort-arrow">{{
              applied.orderByParam.order === sort.value && applied.orderByParam.sort === 'ASC'
                ? '↑'
                : '↓'
            }}</span></NButton
          >
        </div>
        <div class="public-law-result-count">
          <span v-if="result && result.total !== null"
            >共 <strong>{{ result.total.toLocaleString('zh-CN') }}</strong> 条结果</span
          ><span v-else-if="result">本页 {{ result.items.length }} 条未向量化法规</span
          ><span v-else aria-live="polite">{{ loading ? '正在检索…' : '' }}</span>
          <NButton text :disabled="loading" @click="retry"
            ><template #icon><AppIcon name="refresh" :size="14" /></template>刷新</NButton
          >
        </div>
        <div class="public-law-batch">
          <NCheckbox
            :checked="allSelected"
            :indeterminate="selected.length > 0 && !allSelected"
            :disabled="!result?.items.length || loading"
            @update:checked="selectAll"
            >本页全选</NCheckbox
          >
          <span v-if="selected.length" class="public-law-muted">已选 {{ selected.length }} 条</span>
          <NButton
            text
            :disabled="!selectedItems.length || loading"
            :loading="downloading"
            @click="prepareDownloads"
            >批量下载文件</NButton
          >
          <NButton text :disabled="!selectedItems.length || loading" @click="exportSelected"
            >批量导出文件目录</NButton
          >
          <NButton
            text
            :disabled="!selectedItems.length || loading || vectorizing || taskLoading"
            @click="importLaws = [...selectedItems]"
            >批量导入知识库并向量化</NButton
          >
        </div>

        <NSpin :show="loading">
          <div class="public-law-result-list">
            <article v-for="item in result?.items ?? []" :key="item.id" class="public-law-result">
              <NCheckbox
                :checked="selected.includes(item.id)"
                :aria-label="`选择${item.title}`"
                @update:checked="(checked) => toggleItem(item.id, checked)"
              />
              <div class="public-law-result-content">
                <div class="public-law-result-title">
                  <h2>
                    <button class="public-law-title-button" @click="previewLaw = item">
                      {{ item.title }}
                    </button>
                  </h2>
                  <span
                    class="public-law-status"
                    :class="`public-law-status--${item.status ?? 'unknown'}`"
                    >{{ statusLabel(item) }}</span
                  >
                </div>
                <dl class="public-law-result-meta">
                  <div>
                    <dt>公布日期：</dt>
                    <dd>{{ item.published_on || '未标注' }}</dd>
                  </div>
                  <div>
                    <dt>施行日期：</dt>
                    <dd>{{ item.effective_on || '未标注' }}</dd>
                  </div>
                  <div>
                    <dt class="public-law-sr-only">分类：</dt>
                    <dd>{{ item.category || '未标注' }}</dd>
                  </div>
                  <div :title="item.authority">
                    <dt class="public-law-sr-only">制定机关：</dt>
                    <dd>{{ item.authority || '未标注' }}</dd>
                  </div>
                </dl>
                <div class="public-law-vector-state">
                  <NTag
                    size="small"
                    :type="
                      item.vectorization_status === 'COMPLETED'
                        ? 'success'
                        : item.vectorization_status === 'PROCESSING' ||
                            item.vectorization_status === 'QUEUED'
                          ? 'info'
                          : 'default'
                    "
                    >{{ vectorizationLabels[item.vectorization_status] }}</NTag
                  >
                  <RouterLink
                    v-for="state in item.imports"
                    :key="state.document_id"
                    :to="`/knowledge/${state.knowledge_base_id}/documents/${state.document_id}`"
                    :title="`${state.knowledge_base_name} · ${vectorizationLabels[state.status]}`"
                    >{{ state.knowledge_base_name }} · {{ vectorizationLabels[state.status]
                    }}<span v-if="state.chunk_count"
                      >（{{ state.embedded_count }}/{{ state.chunk_count }}）</span
                    ></RouterLink
                  >
                </div>
              </div>
              <div class="public-law-row-actions">
                <NButton
                  size="small"
                  :loading="downloadingId === item.id"
                  :disabled="Boolean(downloadingId) && downloadingId !== item.id"
                  :aria-label="`下载${item.title}`"
                  @click="download(item)"
                  >下载</NButton
                >
                <NButton
                  size="small"
                  secondary
                  type="primary"
                  :disabled="vectorizing || taskLoading"
                  @click="importLaws = [item]"
                  >导入并向量化</NButton
                >
              </div>
            </article>
            <NEmpty
              v-if="result && !result.items.length"
              :description="
                result.has_more ? '本批记录均已向量化，可继续查找下一页' : '没有符合条件的法律法规'
              "
              class="public-law-empty"
              ><template #extra
                ><NButton v-if="result.has_more" @click="changePage(result.page + 1)"
                  >继续查找</NButton
                ><NButton v-else @click="clearFilters">清空条件</NButton></template
              ></NEmpty
            >
          </div>
        </NSpin>
        <NPagination
          v-if="result && result.total !== null && result.total > 0"
          :page="result.page"
          :page-size="result.page_size"
          :item-count="result.total"
          :page-sizes="[10, 20, 50]"
          :page-slot="5"
          show-size-picker
          :disabled="loading"
          @update:page="changePage"
          @update:page-size="changePageSize"
        />
        <div v-if="result && result.total === null" class="public-law-cursor-pagination">
          <span>第 {{ result.page }} 页</span>
          <NSelect
            :value="result.page_size"
            :options="[
              { label: '10 条 / 页', value: 10 },
              { label: '20 条 / 页', value: 20 },
              { label: '50 条 / 页', value: 50 },
            ]"
            aria-label="每页条数"
            :disabled="loading"
            @update:value="changePageSize"
          />
          <NButton :disabled="loading || result.page <= 1" @click="changePage(result.page - 1)"
            >上一页</NButton
          ><NButton :disabled="loading || !result.has_more" @click="changePage(result.page + 1)"
            >下一页</NButton
          >
        </div>
        <p class="public-law-footnote">
          法律文本及效力状态以官方公布内容为准。点击法规标题预览原文。
        </p>
      </div>
    </div>
    <NDrawer v-model:show="downloadDrawer" width="min(480px, 100vw)" placement="right">
      <NDrawerContent title="下载官方文件" closable>
        <p class="public-law-download-note">
          文件由国家法律法规数据库提供，下载链接临时有效。请逐项点击保存，链接过期后可重新获取。
        </p>
        <ul class="public-law-downloads">
          <li v-for="(link, index) in downloadLinks" :key="index">
            <a :href="link.url" target="_blank" rel="noopener noreferrer"
              >{{ link.title }}<AppIcon name="arrow-right" :size="15"
            /></a>
          </li>
        </ul>
      </NDrawerContent>
    </NDrawer>
    <PublicLawPreview :law="previewLaw" @close="previewLaw = null" />
    <PublicLawImportDialog
      :laws="importLaws"
      :query="vectorQuery"
      @close="closeImport"
      @started="vectorTask.accept"
    />
  </section>
</template>
