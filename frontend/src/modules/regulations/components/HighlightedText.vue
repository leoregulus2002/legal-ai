<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ text: string; query: string }>()
const pieces = computed(() => {
  if (!props.query) return [{ text: props.text, hit: false }]
  const parts: { text: string; hit: boolean }[] = []
  const escaped = props.query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const expression = new RegExp(escaped, 'giu')
  let start = 0
  for (const match of props.text.matchAll(expression)) {
    const index = match.index
    if (index > start) parts.push({ text: props.text.slice(start, index), hit: false })
    parts.push({ text: match[0], hit: true })
    start = index + match[0].length
  }
  if (start < props.text.length) parts.push({ text: props.text.slice(start), hit: false })
  return parts
})
</script>
<template>
  <template v-for="(part, index) in pieces" :key="index"
    ><mark v-if="part.hit">{{ part.text }}</mark
    ><template v-else>{{ part.text }}</template></template
  >
</template>
