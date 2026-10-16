<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NEmpty, NInput, NPagination, NSelect, NSpin, NTag, useMessage } from 'naive-ui'
import AppIcon from '../../../components/AppIcon.vue'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import { categoryLabels, legalLabels, sourceLabels } from '../../knowledge/types'
import { regulationApi } from '../api'
import { citation } from '../citation'
import HighlightedText from '../components/HighlightedText.vue'
import type { Regulation, RegulationOptions, RegulationPage } from '../types'
import { scopeOptions, sortOptions } from '../types'
import '../styles.css'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const showError = useErrorMessage()
const defaults = {
  q: '',
  scope: 'all',
  match: 'contains',
  knowledge_base_id: '',
  category: '',
  authority: '',
  region: '',
  legal_status: '',
  promulgated_from: '',
  promulgated_to: '',
  effective_from: '',
  effective_to: '',
  sort: 'relevance',
  page: '1',
}
type Form = typeof defaults
const form = reactive<Form>({ ...defaults })
const options = ref<RegulationOptions>()
const result = ref<RegulationPage>()
const loading = ref(false)
const unavailable = ref(false)
const filtersOpen = ref(false)
const copying = ref<string | null>(null)
let sequence = 0
let alive = true
const selectOptions = (values: Record<string, string>, label: string) => [
  { value: '', label },
  ...Object.entries(values).map(([value, text]) => ({ value, label: text })),
]
const baseOptions = computed(() => [
  { value: '', label: '全部知识库' },
  ...(options.value?.knowledge_bases.map((base) => ({ value: base.id, label: base.name })) ?? []),
])
const valueOptions = (values: string[] | undefined, label: string) => [
  { value: '', label },
  ...(values ?? []).map((value) => ({ value, label: value })),
]
const activeFilterCount = computed(
  () =>
    Object.keys(defaults).filter(
      (key) => !['q', 'scope', 'match', 'sort', 'page'].includes(key) && form[key as keyof Form],
    ).length,
)

function readQuery(): Form {
  const parsed = { ...defaults }
  for (const key of Object.keys(defaults) as (keyof Form)[]) {
    const value = route.query[key]
    if (typeof value === 'string') parsed[key] = value
  }
  if (!scopeOptions.some((option) => option.value === parsed.scope)) parsed.scope = 'all'
  if (!['contains', 'exact'].includes(parsed.match)) parsed.match = 'contains'
  if (!sortOptions.some((option) => option.value === parsed.sort)) parsed.sort = 'relevance'
  if (!/^\d+$/.test(parsed.page) || +parsed.page < 1 || +parsed.page > 100000) parsed.page = '1'
  return parsed
}

async function load(): Promise<void> {
  const request = ++sequence
  const parsed = readQuery()
  Object.assign(form, parsed)
  loading.value = true
  unavailable.value = false
  result.value = undefined
  try {
    const page = await regulationApi.search(parsed)
    if (request === sequence) result.value = page
  } catch (error: unknown) {
    if (request === sequence) {
      unavailable.value = true
      showError(error)
    }
  } finally {
    if (request === sequence) loading.value = false
  }
}

async function submit(page = 1): Promise<void> {
  for (const [lower, upper] of [
    [form.promulgated_from, form.promulgated_to],
    [form.effective_from, form.effective_to],
  ]) {
    if (lower && upper && lower > upper) {
      message.warning('开始日期不能晚于结束日期')
      return
    }
  }
  const query: Record<string, string> = { ...form, q: form.q.trim(), page: String(page) }
  for (const key of Object.keys(query)) if (!query[key]) delete query[key]
  const target = { path: '/regulations', query }
  if (router.resolve(target).fullPath === route.fullPath) await load()
  else await router.push(target)
}

async function resetFilters(): Promise<void> {
  Object.assign(form, defaults)
  await submit()
}

function reload(): void {
  void load()
  void loadOptions()
}

function detailLink(item: Regulation) {
  return {
    name: 'regulation-detail',
    params: { documentId: item.document_id },
    query: {
      revision: String(item.revision),
      node: item.node_id || undefined,
      q: result.value?.highlight || undefined,
      returnTo: route.fullPath,
    },
  }
}

async function copy(item: Regulation): Promise<void> {
  const request = sequence
  copying.value = item.document_id
  try {
    const detail = await regulationApi.detail(item.document_id)
    if (request !== sequence) return
    if (detail.regulation.revision !== item.revision) {
      message.warning('资料已更新，请重新检索后复制引用')
      return
    }
    await navigator.clipboard.writeText(citation(detail, item.node_id))
    if (request === sequence) message.success('引用已复制')
  } catch {
    if (request === sequence) message.error('暂时无法复制，请打开原文后重试')
  } finally {
    copying.value = null
  }
}

async function loadOptions(): Promise<void> {
  try {
    const data = await regulationApi.options()
    if (alive) options.value = data
  } catch (error: unknown) {
    if (alive) showError(error)
  }
}

watch(
  () => route.query,
  () => {
    void load()
  },
  { immediate: true },
)
onMounted(() => {
  void loadOptions()
})
onUnmounted(() => {
  alive = false
  sequence++
})
</script>

<template>
  <section class="reg-page">
    <header class="reg-header">
      <div>
        <span class="reg-eyebrow">法律资料 · 原文检索</span>
        <h1>法律法规检索</h1>
        <p>查找条文，核对版本，让每一次引用都有出处。</p>
      </div>
      <div v-if="options" class="reg-coverage">
        <strong>{{ options.document_count }}</strong
        ><span>份已发布法规资料 · {{ options.knowledge_bases.length }} 个知识库</span>
      </div>
    </header>
    <form class="reg-search-box" @submit.prevent="submit()">
      <div class="reg-search-line">
        <NSelect
          v-model:value="form.scope"
          :options="scopeOptions"
          aria-label="检索范围"
          class="reg-scope"
        />
        <NInput
          v-model:value="form.q"
          :maxlength="500"
          placeholder="输入法规名称、关键词、文号，或“民法典第五百七十七条”"
          aria-label="搜索法律法规"
          clearable
        />
        <NButton type="primary" attr-type="submit" :loading="loading"
          ><template #icon><AppIcon name="search" :size="17" /></template>检索</NButton
        >
      </div>
      <div class="reg-search-meta">
        <NSelect
          v-model:value="form.match"
          :options="[
            { label: '包含匹配', value: 'contains' },
            { label: '精确匹配', value: 'exact' },
          ]"
          aria-label="匹配方式"
        />
        <span>{{
          form.match === 'exact'
            ? '名称、文号完整匹配；正文按完整条文匹配'
            : '支持连续关键词匹配与法规名称加条号定位'
        }}</span>
      </div>
    </form>
    <p class="reg-scope-note">
      检索范围为内部知识库已审核发布的法律资料；效力状态与来源核验以资料记录为准。
    </p>
    <div class="reg-search-layout">
      <aside class="reg-filters" :class="{ 'is-open': filtersOpen }">
        <button
          class="reg-filter-heading"
          :aria-expanded="filtersOpen"
          @click="filtersOpen = !filtersOpen"
        >
          <strong
            >筛选条件<span v-if="activeFilterCount"> · {{ activeFilterCount }}</span></strong
          ><AppIcon name="chevron-down" :size="16" />
        </button>
        <form class="reg-filter-fields" @submit.prevent="submit()">
          <label
            >知识库<NSelect
              v-model:value="form.knowledge_base_id"
              :options="baseOptions"
              filterable
          /></label>
          <label
            >法规类别<NSelect
              v-model:value="form.category"
              :options="selectOptions(categoryLabels, '全部类别')"
          /></label>
          <label
            >制定机关<NSelect
              v-model:value="form.authority"
              :options="valueOptions(options?.authorities, '全部机关')"
              filterable
          /></label>
          <label
            >适用地区<NSelect
              v-model:value="form.region"
              :options="valueOptions(options?.regions, '全部地区')"
              filterable
          /></label>
          <label
            >效力状态<NSelect
              v-model:value="form.legal_status"
              :options="selectOptions(legalLabels, '全部状态')"
          /></label>
          <fieldset>
            <legend>公布日期</legend>
            <input v-model="form.promulgated_from" type="date" aria-label="公布起始日期" /><span
              >至</span
            ><input v-model="form.promulgated_to" type="date" aria-label="公布截止日期" />
          </fieldset>
          <fieldset>
            <legend>施行日期</legend>
            <input v-model="form.effective_from" type="date" aria-label="施行起始日期" /><span
              >至</span
            ><input v-model="form.effective_to" type="date" aria-label="施行截止日期" />
          </fieldset>
          <NButton attr-type="submit" :loading="loading" type="primary" secondary>应用筛选</NButton>
          <NButton quaternary @click="resetFilters">重置条件</NButton>
        </form>
      </aside>
      <div class="reg-results">
        <div class="reg-result-toolbar">
          <span>{{
            loading ? '正在检索…' : result ? `共 ${result.total} 份法规资料` : '法规资料'
          }}</span>
          <NSelect
            v-model:value="form.sort"
            :options="sortOptions"
            aria-label="结果排序"
            @update:value="submit()"
          />
        </div>
        <NSpin :show="loading">
          <article v-for="item in result?.items" :key="item.document_id" class="reg-result">
            <div class="reg-tags">
              <NTag
                size="small"
                :bordered="false"
                :type="item.legal_status === 'EFFECTIVE' ? 'success' : 'default'"
                >{{ legalLabels[item.legal_status] }}</NTag
              ><span
                >{{ categoryLabels[item.metadata.category] }} ·
                {{ item.metadata.region || '地区未标注' }}</span
              >
            </div>
            <h2>
              <RouterLink :to="detailLink(item)"
                ><HighlightedText :text="item.metadata.title" :query="result?.highlight || ''"
              /></RouterLink>
            </h2>
            <p class="reg-result-info">
              {{ item.metadata.authority || '制定机关未提供'
              }}<span>公布 {{ item.metadata.promulgated_on || '未提供' }}</span
              ><span>施行 {{ item.metadata.effective_on || '未提供' }}</span>
            </p>
            <p v-if="item.metadata.document_number" class="reg-document-number">
              <HighlightedText
                :text="item.metadata.document_number"
                :query="result?.highlight || ''"
              />
            </p>
            <p class="reg-excerpt">
              <HighlightedText :text="item.excerpt" :query="result?.highlight || ''" />
            </p>
            <div class="reg-result-footer">
              <div>
                <span>{{ item.metadata.version_label || '版本未提供' }}</span
                ><span>{{ sourceLabels[item.source_kind] }} · {{ item.knowledge_base_name }}</span>
              </div>
              <div class="reg-result-actions">
                <span v-if="item.matched_articles">命中 {{ item.matched_articles }} 条</span
                ><NButton
                  text
                  :loading="copying === item.document_id"
                  :disabled="copying !== null"
                  @click="copy(item)"
                  ><template #icon><AppIcon name="copy" :size="14" /></template
                  >{{ item.node_id ? '复制本条' : '复制引用' }}</NButton
                ><RouterLink :to="detailLink(item)"
                  >{{ item.article_label || '查看全文' }} <AppIcon name="arrow-right" :size="14"
                /></RouterLink>
              </div>
            </div>
          </article>
          <NEmpty
            v-if="!loading && !result?.items.length"
            class="reg-empty"
            :description="
              unavailable
                ? '暂无可显示的结果'
                : options?.document_count === 0
                  ? '尚无已审核发布的法规资料'
                  : '没有找到符合条件的法规资料'
            "
          >
            <template #extra
              ><NButton v-if="unavailable" @click="reload">重新加载</NButton
              ><RouterLink v-else-if="options?.document_count === 0" to="/knowledge"
                >前往知识库管理资料</RouterLink
              ><NButton v-else @click="resetFilters">清除条件</NButton></template
            >
          </NEmpty>
          <div v-if="loading" class="reg-loading-space" />
        </NSpin>
        <NPagination
          v-if="result && result.total > result.page_size"
          :page="result.page"
          :page-size="result.page_size"
          :item-count="result.total"
          :page-slot="5"
          @update:page="submit"
        />
      </div>
    </div>
  </section>
</template>
