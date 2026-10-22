<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { NButton, NEmpty, NSelect, NSpin, NTag } from 'naive-ui'
import type { DocumentDetail, DocumentView } from '../types'
const props = defineProps<{
  documents: DocumentView[]
  selected: string | null
  detail: DocumentDetail | null
  loading: boolean
  downloading: boolean
  highlight: string | null
}>()
defineEmits<{ select: [id: string]; download: [] }>()
const container = ref<HTMLElement | null>(null)
const isHistorical = computed(
  () => !!props.detail && !props.documents.some((item) => item.id === props.detail?.id),
)
const documentOptions = computed(() => {
  const options = props.documents.map((item) => ({ label: item.filename, value: item.id }))
  if (props.selected && !props.documents.some((item) => item.id === props.selected))
    options.push({
      value: props.selected,
      label:
        props.detail?.id === props.selected
          ? `${props.detail.filename}（历史文书）`
          : props.loading
            ? '正在读取历史文书…'
            : '历史文书',
    })
  return options
})
const segments = computed(() => {
  if (!props.detail) return []
  const chars = Array.from(props.detail.text)
  const spans = [...props.detail.spans].sort((a, b) => a.start - b.start)
  const rows: { id: string; text: string }[] = []
  let cursor = 0
  for (const span of spans) {
    if (span.start < cursor || span.end <= span.start || span.start >= chars.length) continue
    if (span.start > cursor)
      rows.push({ id: `gap-${cursor}`, text: chars.slice(cursor, span.start).join('') })
    rows.push({ id: span.id, text: chars.slice(span.start, span.end).join('') })
    cursor = span.end
  }
  if (cursor < chars.length) rows.push({ id: `gap-${cursor}`, text: chars.slice(cursor).join('') })
  return rows
})
watch(
  () => [props.detail?.id, props.highlight],
  async () => {
    await nextTick()
    const element = Array.from(
      container.value?.querySelectorAll<HTMLElement>('[data-span]') ?? [],
    ).find((row) => row.dataset.span === props.highlight)
    element?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  },
)
</script>
<template>
  <section class="analysis-panel analysis-original">
    <div class="analysis-panel-heading">
      <h2>文书原文</h2>
      <NButton size="small" :disabled="!detail" :loading="downloading" @click="$emit('download')"
        >下载原件</NButton
      >
    </div>
    <NSelect
      :value="selected"
      :options="documentOptions"
      placeholder="选择文书阅读"
      aria-label="选择原文文书"
      @update:value="(value: string) => $emit('select', value)"
    />
    <NSpin :show="loading"
      ><div ref="container" class="analysis-original-content">
        <template v-if="detail"
          ><p class="analysis-muted">
            第 {{ detail.revision }} 版 · {{ detail.character_count.toLocaleString() }} 字符
            <NTag v-if="isHistorical" size="small">历史文书</NTag>
            <NTag v-if="detail.status === 'needs_ocr'" size="small" type="warning">需 OCR</NTag>
          </p>
          <NEmpty v-if="!detail.text" description="暂无可读取的文本，请下载原件查看" />
          <p
            v-for="segment in segments"
            :key="segment.id"
            :data-span="segment.id"
            class="analysis-original-span"
            :class="{ 'is-highlighted': highlight === segment.id }"
          >
            {{ segment.text }}
          </p></template
        ><NEmpty v-else description="上传或选择文书后，在这里阅读原文" /></div
    ></NSpin>
  </section>
</template>
