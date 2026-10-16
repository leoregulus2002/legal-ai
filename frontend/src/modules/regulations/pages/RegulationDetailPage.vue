<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { NButton, NEmpty, NInput, NSpin, NTag, useMessage } from 'naive-ui'
import AppIcon from '../../../components/AppIcon.vue'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import { categoryLabels, legalLabels, sourceLabels } from '../../knowledge/types'
import type { StructureNode } from '../../knowledge/types'
import { regulationApi } from '../api'
import { citation, safeSource } from '../citation'
import HighlightedText from '../components/HighlightedText.vue'
import type { RegulationDetail } from '../types'
import '../styles.css'

const route = useRoute()
const message = useMessage()
const showError = useErrorMessage()
const detail = ref<RegulationDetail>()
const loading = ref(false)
const copying = ref(false)
const search = ref('')
const activeMatch = ref(-1)
const matchCount = ref(0)
const activeNode = ref('')
const content = ref<HTMLElement>()
const directorySearch = ref('')
let sequence = 0
const regulation = computed(() => detail.value?.regulation)
const source = computed(() => safeSource(regulation.value?.source_url || ''))
const returnTo = computed(() => {
  const target = route.query.returnTo
  return typeof target === 'string' &&
    (target === '/regulations' || target.startsWith('/regulations?'))
    ? target
    : '/regulations'
})
const structural = computed(() =>
  (detail.value?.nodes ?? [])
    .filter((node) => !['PARAGRAPH', 'ITEM', 'SUBITEM'].includes(node.kind))
    .sort((a, b) => a.start - b.start || b.end - a.end),
)
const directory = computed(() =>
  structural.value.filter((node) => node.label.includes(directorySearch.value.trim())),
)
const sections = computed(() => {
  if (!detail.value) return []
  const points = Array.from(detail.value.text)
  const positions = new Map<number, StructureNode>()
  for (const node of structural.value) positions.set(node.start, node)
  const starts = [...new Set([0, ...positions.keys()])].sort((a, b) => a - b)
  return starts.map((start, index) => ({
    key: start,
    node: positions.get(start),
    text: points.slice(start, starts[index + 1] ?? points.length).join(''),
  }))
})

function jump(id: string): void {
  const target = [...(content.value?.querySelectorAll<HTMLElement>('[data-node]') ?? [])].find(
    (element) => element.dataset.node === id,
  )
  if (target) {
    activeNode.value = id
    target.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

async function refreshMatches(): Promise<void> {
  activeMatch.value = -1
  await nextTick()
  const marks = content.value?.querySelectorAll('mark')
  matchCount.value = marks?.length ?? 0
  if (matchCount.value) moveMatch(1)
}

function moveMatch(direction: number): void {
  const marks = content.value?.querySelectorAll('mark')
  if (!marks?.length) return
  marks.forEach((mark) => mark.classList.remove('reg-active-match'))
  activeMatch.value = (activeMatch.value + direction + marks.length) % marks.length
  const mark = marks[activeMatch.value]
  mark?.classList.add('reg-active-match')
  mark?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

async function load(): Promise<void> {
  const request = ++sequence
  detail.value = undefined
  loading.value = true
  activeNode.value = ''
  matchCount.value = 0
  activeMatch.value = -1
  try {
    const data = await regulationApi.detail(String(route.params.documentId))
    if (request !== sequence) return
    detail.value = data
    const revision = typeof route.query.revision === 'string' ? route.query.revision : ''
    const changed = revision !== '' && revision !== String(data.regulation.revision)
    if (changed) message.info('资料已更新，当前展示最新发布版本')
    search.value = typeof route.query.q === 'string' ? route.query.q : ''
    loading.value = false
    await nextTick()
    await refreshMatches()
    if (!changed && typeof route.query.node === 'string') jump(route.query.node)
  } catch (error: unknown) {
    if (request === sequence) showError(error)
  } finally {
    if (request === sequence) loading.value = false
  }
}

async function copy(nodeId?: string): Promise<void> {
  if (!detail.value) return
  const snapshot = detail.value.regulation
  const request = sequence
  copying.value = true
  try {
    const latest = await regulationApi.detail(snapshot.document_id)
    if (request !== sequence) return
    if (latest.regulation.revision !== snapshot.revision) {
      message.warning('资料已更新，请重新加载后复制引用')
      return
    }
    await navigator.clipboard.writeText(citation(latest, nodeId))
    if (request === sequence) message.success('引用已复制')
  } catch {
    if (request === sequence) message.error('暂时无法复制，请重新加载或检查剪贴板权限')
  } finally {
    copying.value = false
  }
}

watch(search, () => {
  void refreshMatches()
})
watch(
  () => route.fullPath,
  () => {
    void load()
  },
  { immediate: true },
)
onUnmounted(() => {
  sequence++
})
</script>

<template>
  <section class="reg-page">
    <RouterLink :to="returnTo" class="reg-back"
      ><AppIcon name="arrow-left" :size="15" /> 返回检索结果</RouterLink
    >
    <NSpin :show="loading">
      <template v-if="detail && regulation">
        <header class="reg-reading-header">
          <div class="reg-tags">
            <NTag
              size="small"
              :bordered="false"
              :type="regulation.legal_status === 'EFFECTIVE' ? 'success' : 'default'"
              >{{ legalLabels[regulation.legal_status] }}</NTag
            ><span
              >{{ categoryLabels[regulation.metadata.category] }} ·
              {{ regulation.metadata.region || '地区未标注' }}</span
            >
          </div>
          <h1>{{ regulation.metadata.title }}</h1>
          <p class="reg-version">
            {{ regulation.metadata.version_label || '版本说明未提供'
            }}<span>{{ regulation.version_confirmed ? '版本已人工确认' : '版本待核对' }}</span>
          </p>
          <dl class="reg-metadata">
            <div>
              <dt>制定机关</dt>
              <dd>{{ regulation.metadata.authority || '未提供' }}</dd>
            </div>
            <div>
              <dt>文号</dt>
              <dd>{{ regulation.metadata.document_number || '未提供' }}</dd>
            </div>
            <div>
              <dt>公布日期</dt>
              <dd>{{ regulation.metadata.promulgated_on || '未提供' }}</dd>
            </div>
            <div>
              <dt>施行日期</dt>
              <dd>{{ regulation.metadata.effective_on || '未提供' }}</dd>
            </div>
            <div>
              <dt>资料来源</dt>
              <dd>{{ regulation.knowledge_base_name }}</dd>
            </div>
            <div>
              <dt>资料更新时间</dt>
              <dd>{{ new Date(regulation.updated_at).toLocaleString('zh-CN') }}</dd>
            </div>
          </dl>
          <div class="reg-source-bar">
            <span>{{ sourceLabels[regulation.source_kind] }}</span
            ><a v-if="source" :href="source" target="_blank" rel="noopener noreferrer"
              >{{
                regulation.source_kind === 'OFFICIAL_VERIFIED' ? '查看官方原文' : '查看来源链接'
              }}
              ↗</a
            ><span v-else>未提供有效来源链接</span
            ><NButton secondary :loading="copying" @click="copy()"
              ><template #icon><AppIcon name="copy" :size="15" /></template>复制全文引用</NButton
            >
          </div>
        </header>
        <div class="reg-reading-layout">
          <aside class="reg-directory">
            <h2>正文目录</h2>
            <NInput
              v-model:value="directorySearch"
              placeholder="查找条号或章节"
              aria-label="筛选正文目录"
              clearable
              :maxlength="100"
            />
            <nav aria-label="法规正文目录">
              <button
                v-for="node in directory"
                :key="node.id"
                :class="{
                  'is-active': activeNode === node.id,
                  'reg-directory-article': node.kind === 'ARTICLE',
                }"
                :aria-current="activeNode === node.id ? 'location' : undefined"
                @click="jump(node.id)"
              >
                {{ node.label }}
              </button>
              <p v-if="!directory.length">没有匹配的目录项</p>
            </nav>
          </aside>
          <div class="reg-reading-main">
            <div class="reg-find-bar">
              <NInput
                v-model:value="search"
                placeholder="在本篇原文中查找"
                aria-label="文内搜索"
                :maxlength="500"
                clearable
                @keydown.enter.prevent="moveMatch(1)"
              /><span aria-live="polite">{{
                matchCount ? `${activeMatch + 1} / ${matchCount}` : search ? '0 处命中' : '文内查找'
              }}</span
              ><NButton
                size="small"
                :disabled="!matchCount"
                aria-label="上一个匹配"
                @click="moveMatch(-1)"
                >上一处</NButton
              ><NButton
                size="small"
                :disabled="!matchCount"
                aria-label="下一个匹配"
                @click="moveMatch(1)"
                >下一处</NButton
              >
            </div>
            <div ref="content" class="reg-original">
              <section
                v-for="part in sections"
                :key="part.key"
                class="reg-text-section"
                :class="{ 'is-target': part.node?.id === activeNode }"
                :data-node="part.node?.id"
              >
                <div v-if="part.node?.kind === 'ARTICLE'" class="reg-article-tools">
                  <NButton text size="small" :disabled="copying" @click="copy(part.node.id)"
                    ><AppIcon name="copy" :size="13" /> 复制本条</NButton
                  >
                </div>
                <p><HighlightedText :text="part.text" :query="search" /></p>
              </section>
            </div>
          </div>
        </div>
      </template>
      <NEmpty v-else-if="!loading" description="暂无可显示的法规资料" class="reg-empty"
        ><template #extra><NButton @click="load">重新加载</NButton></template></NEmpty
      >
      <div v-if="loading" class="reg-loading-space" />
    </NSpin>
  </section>
</template>
