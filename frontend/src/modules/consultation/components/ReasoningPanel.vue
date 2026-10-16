<script setup lang="ts">
defineProps<{ content: string; active?: boolean }>()
</script>

<template>
  <details class="reasoning-panel" :open="active">
    <summary>{{ active ? '思考中…' : '思考过程' }}</summary>
    <p>{{ content }}</p>
  </details>
</template>

<style scoped>
.reasoning-panel {
  margin-top: 0.8rem;
  padding: 0.65rem 0.85rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--muted);
  background: var(--surface);
  font-size: 0.82rem;
}
.reasoning-panel summary {
  cursor: pointer;
  color: var(--bronze);
}
.reasoning-panel p {
  max-height: 22rem;
  margin: 0.6rem 0 0;
  overflow-y: auto;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  line-height: 1.8;
}
</style>
