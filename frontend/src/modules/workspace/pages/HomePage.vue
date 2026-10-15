<script setup lang="ts">
import { onMounted } from 'vue'
import workspaceHero from '../../../assets/legal-workspace-hero.png'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import FeatureEntry from '../components/FeatureEntry.vue'
import ServiceStatus from '../components/ServiceStatus.vue'
import { useHealthStore } from '../store'
import { workspaceFeatures } from '../features'

const health = useHealthStore()
const showError = useErrorMessage()

async function refreshHealth(): Promise<void> {
  try {
    await health.refresh()
  } catch (error: unknown) {
    showError(error)
  }
}

onMounted(() => {
  void refreshHealth()
})
</script>

<template>
  <div class="workspace-page">
    <div class="workspace-heading-row">
      <div class="page-intro">
        <h2>工作台</h2>
        <p>你的法律智能工作空间。</p>
      </div>
      <ServiceStatus :status="health.status" @refresh="refreshHealth" />
    </div>
    <section class="workspace-hero" aria-labelledby="platform-heading">
      <div class="hero-copy">
        <span class="hero-rule" aria-hidden="true" />
        <h1 id="platform-heading"><span>法律 AI</span><span>智能体平台</span></h1>
        <p class="hero-description">连接法律知识与智能能力，让专业工作更从容。</p>
        <p class="hero-note">从法律咨询开始，连接你的专业知识。</p>
      </div>
      <img
        class="hero-art"
        :src="workspaceHero"
        alt="深蓝色法典书籍与司法建筑立柱的静物配图"
        width="1600"
        height="480"
        decoding="async"
        fetchpriority="high"
      />
    </section>
    <section class="workspace-section" aria-labelledby="workspace-heading">
      <div class="section-heading">
        <h2 id="workspace-heading">探索平台能力</h2>
        <span aria-hidden="true" />
      </div>
      <p class="section-description">从咨询到文书，为专业工作预留清晰入口。</p>
      <div class="feature-grid">
        <FeatureEntry
          v-for="(feature, index) in workspaceFeatures"
          :key="feature.id"
          :feature="feature"
          :featured="index === 0"
          :order="index + 1"
        />
      </div>
    </section>
    <footer class="workspace-note">平台功能正在逐步建设中。</footer>
  </div>
</template>
