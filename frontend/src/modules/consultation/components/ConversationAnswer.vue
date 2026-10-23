<script setup lang="ts">
import { computed } from 'vue'
import ToolCallRecord from '../../../components/ToolCallRecord.vue'
import type { ToolActivity } from '../../../components/toolActivity'

const props = defineProps<{ text: string; calls: ToolActivity[]; active?: boolean }>()
const segments = computed(() => {
  let offset = 0
  return [...props.calls]
    .sort((left, right) => left.answer_offset - right.answer_offset)
    .map((call) => {
      const end = Math.min(call.answer_offset, props.text.length)
      const text = props.text.slice(offset, end)
      offset = end
      return { call, text }
    })
})
const tail = computed(() => {
  const last = segments.value.at(-1)?.call.answer_offset ?? 0
  return props.text.slice(last)
})
const callingTool = computed(() =>
  props.calls.some((call) => call.status === 'preparing' || call.status === 'running'),
)
</script>

<template>
  <template v-for="segment in segments" :key="segment.call.id">
    <p v-if="segment.text.trim()" class="message-text">{{ segment.text }}</p>
    <ToolCallRecord
      :name="segment.call.name"
      :status="segment.call.status"
      :summary="segment.call.summary"
      :duration-ms="segment.call.duration_ms"
    />
  </template>
  <p v-if="tail.trim() || (active && !callingTool)" class="message-text">
    {{ tail }}<span v-if="active && !callingTool" class="stream-caret" aria-hidden="true" />
  </p>
</template>
