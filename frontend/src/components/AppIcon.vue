<script setup lang="ts">
export type IconName =
  | 'home'
  | 'chat'
  | 'search'
  | 'book'
  | 'document'
  | 'refresh'
  | 'settings'
  | 'menu'
  | 'lock'
  | 'column'
  | 'arrow-right'
  | 'arrow-left'
  | 'chevron-right'
  | 'close'
  | 'plus'
  | 'arrow-up'
  | 'chevron-down'
  | 'copy'

defineProps<{ name: IconName; size?: number }>()

const paths: Record<IconName, string[]> = {
  home: ['m3 10 9-7 9 7', 'M5 9v12h5v-7h4v7h5V9'],
  chat: ['M5 4h14a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H9l-6 4V6a2 2 0 0 1 2-2Z'],
  search: ['M21 21l-5.5-5.5', 'M17 9a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z'],
  book: ['M12 5v16', 'M12 5C9 2 5 2 2 3v17c4-1 7-1 10 1 3-2 6-2 10-1V3c-3-1-7-1-10 2Z'],
  document: [
    'M14 2H5a1 1 0 0 0-1 1v18a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V8Z',
    'M14 2v6h6',
    'M8 13h8',
    'M8 17h6',
  ],
  refresh: ['M20 4v6h-6', 'M4 20v-6h6', 'M20 10a8 8 0 0 0-14-5', 'M4 14a8 8 0 0 0 14 5'],
  settings: [
    'm9 3 6 0 1 3 3 1 2 5-2 2v3l-5 2-2-2-3 0-2 2-5-2v-3l-2-2 2-5 3-1Z',
    'M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',
  ],
  menu: ['M3 6h18', 'M3 12h18', 'M3 18h18'],
  lock: ['M6 10h12v11H6Z', 'M8 10V6a4 4 0 0 1 8 0v4', 'M12 14v3'],
  column: ['M5 2h14', 'M3 5h18', 'M5 8h14', 'M6 8v11', 'M12 8v11', 'M18 8v11', 'M3 22h18'],
  'arrow-right': ['M4 12h16', 'm14 6 6 6-6 6'],
  'arrow-left': ['M20 12H4', 'm10 6-6 6 6 6'],
  'chevron-right': ['m9 5 7 7-7 7'],
  close: ['m6 6 12 12', 'M18 6 6 18'],
  plus: ['M12 5v14', 'M5 12h14'],
  'arrow-up': ['M12 20V4', 'm5 11 7-7 7 7'],
  'chevron-down': ['m6 9 6 6 6-6'],
  copy: ['M9 9h11v12H9Z', 'M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1'],
}
</script>

<template>
  <svg
    :width="size ?? 20"
    :height="size ?? 20"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.65"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path v-for="(path, index) in paths[name]" :key="index" :d="path" />
  </svg>
</template>
