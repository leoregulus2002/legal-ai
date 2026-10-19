<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { NButton } from 'naive-ui'
import AppIcon from '../components/AppIcon.vue'
import { workspaceFeatures } from '../modules/workspace/features'

const route = useRoute()
const menuOpen = ref(false)
watch(
  () => route.fullPath,
  () => {
    menuOpen.value = false
  },
)
</script>

<template>
  <div class="app-shell" @keydown.esc="menuOpen = false">
    <a class="skip-link" href="#main-content">跳转到主要内容</a>
    <button
      v-if="menuOpen"
      class="sidebar-backdrop"
      aria-label="关闭导航"
      @click="menuOpen = false"
    />
    <aside
      id="primary-sidebar"
      class="sidebar"
      :class="{ 'is-open': menuOpen }"
      aria-label="主导航"
    >
      <div class="sidebar-brand-row">
        <RouterLink class="brand" to="/" @click="menuOpen = false">
          <AppIcon class="brand-symbol" name="column" :size="36" />
          <span class="brand-copy"><strong>legal-ai</strong><span>法律智能工作台</span></span>
        </RouterLink>
        <NButton
          class="sidebar-close"
          quaternary
          circle
          aria-label="关闭导航"
          @click="menuOpen = false"
          ><AppIcon name="close" :size="18"
        /></NButton>
      </div>
      <p class="nav-section-label">工作空间</p>
      <nav class="navigation">
        <RouterLink
          to="/"
          class="nav-item"
          :class="{ 'is-active': route.name === 'home' }"
          :aria-current="route.name === 'home' ? 'page' : undefined"
        >
          <AppIcon name="home" :size="20" /><span>工作台</span>
        </RouterLink>
        <template v-for="feature in workspaceFeatures" :key="feature.id">
          <RouterLink
            v-if="feature.to"
            :to="feature.to"
            class="nav-item"
            :class="{
              'is-active': route.path === feature.to || route.path.startsWith(feature.to + '/'),
            }"
            :aria-current="
              route.path === feature.to || route.path.startsWith(feature.to + '/')
                ? 'page'
                : undefined
            "
            ><AppIcon :name="feature.icon" :size="20" /><span>{{ feature.title }}</span></RouterLink
          >
          <button v-else class="nav-item" disabled :aria-label="`${feature.title}，即将开放`">
            <AppIcon :name="feature.icon" :size="20" /><span>{{ feature.title }}</span
            ><AppIcon class="nav-lock" name="lock" :size="13" />
          </button>
        </template>
      </nav>
      <p class="nav-section-label settings-section-label">系统配置</p>
      <nav class="navigation" aria-label="系统配置">
        <RouterLink
          to="/settings/prompts"
          class="nav-item"
          :class="{ 'is-active': route.name === 'prompt-config' }"
          :aria-current="route.name === 'prompt-config' ? 'page' : undefined"
          ><AppIcon name="document" :size="20" /><span>系统提示词</span></RouterLink
        >
        <RouterLink
          to="/settings/models"
          class="nav-item"
          :class="{ 'is-active': route.name === 'model-config' }"
          :aria-current="route.name === 'model-config' ? 'page' : undefined"
          ><AppIcon name="settings" :size="20" /><span>模型配置</span></RouterLink
        >
        <RouterLink
          to="/settings/vectorization"
          class="nav-item"
          :class="{ 'is-active': route.name === 'vectorization-config' }"
          :aria-current="route.name === 'vectorization-config' ? 'page' : undefined"
          ><AppIcon name="refresh" :size="20" /><span>自动向量化</span></RouterLink
        >
        <RouterLink
          to="/settings/consultation"
          class="nav-item"
          :class="{ 'is-active': route.name === 'consultation-config' }"
          :aria-current="route.name === 'consultation-config' ? 'page' : undefined"
          ><AppIcon name="chat" :size="20" /><span>法律咨询模型</span></RouterLink
        >
      </nav>
      <div class="sidebar-note">
        <span class="sidebar-note-rule" />
        <p>法律智能工作台</p>
        <span>咨询与模型管理</span>
      </div>
    </aside>
    <div class="main-shell">
      <header class="topbar">
        <div class="topbar-navigation">
          <NButton
            class="menu-toggle"
            quaternary
            aria-label="切换导航"
            aria-controls="primary-sidebar"
            :aria-expanded="menuOpen"
            @click="menuOpen = !menuOpen"
            ><AppIcon name="menu" :size="21"
          /></NButton>
          <nav class="breadcrumbs" aria-label="面包屑">
            <RouterLink to="/">工作台</RouterLink
            ><span class="breadcrumb-divider" aria-hidden="true">/</span
            ><span aria-current="page">{{
              route.name === 'home' ? '概览' : (route.meta.title ?? '页面')
            }}</span>
          </nav>
        </div>
        <span class="environment-label">法律智能工作空间</span>
      </header>
      <main
        id="main-content"
        class="page-content"
        :class="{ 'page-content--conversation': route.name === 'consultation' }"
        tabindex="-1"
      >
        <RouterView :key="route.path" />
      </main>
    </div>
  </div>
</template>
