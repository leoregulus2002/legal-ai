<script setup lang="ts">
import AppIcon from '../../../components/AppIcon.vue'
import { RouterLink } from 'vue-router'
import type { WorkspaceFeature } from '../features'

defineProps<{ feature: WorkspaceFeature; featured: boolean; order: number }>()
</script>

<template>
  <component
    :is="feature.to ? RouterLink : 'article'"
    :to="feature.to"
    class="feature-entry"
    :class="{ 'is-featured': featured }"
    :aria-disabled="feature.to ? undefined : true"
    :aria-labelledby="`feature-${feature.id}-title`"
  >
    <span class="feature-icon"><AppIcon :name="feature.icon" :size="featured ? 30 : 27" /></span>
    <span v-if="featured" class="feature-index" aria-hidden="true">{{
      String(order).padStart(2, '0')
    }}</span>
    <div class="feature-copy">
      <h3 :id="`feature-${feature.id}-title`">{{ feature.title }}</h3>
      <p>{{ feature.description }}</p>
    </div>
    <div class="feature-footer">
      <span class="feature-availability"
        ><AppIcon :name="feature.to ? 'arrow-right' : 'lock'" :size="13" /><span>{{
          feature.to ? '开始咨询' : '即将开放'
        }}</span></span
      ><AppIcon v-if="featured" class="feature-direction" name="arrow-right" :size="21" />
    </div>
    <AppIcon v-if="featured" class="feature-watermark" name="column" :size="170" />
  </component>
</template>
