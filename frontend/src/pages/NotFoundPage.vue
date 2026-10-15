<script setup lang="ts">
import { NButton } from 'naive-ui'
import AppIcon from '../components/AppIcon.vue'
</script>

<template>
  <section class="not-found" aria-labelledby="not-found-heading">
    <AppIcon class="not-found-symbol" name="column" :size="36" />
    <span class="not-found-code" aria-hidden="true">404</span>
    <h1 id="not-found-heading">页面未找到</h1>
    <p>这个页面不存在，或地址已发生变化。</p>
    <RouterLink v-slot="{ href, navigate }" to="/" custom
      ><NButton tag="a" :href="href" type="primary" @click="navigate"
        ><template #icon><AppIcon name="arrow-left" :size="17" /></template>返回工作台</NButton
      ></RouterLink
    >
  </section>
</template>
