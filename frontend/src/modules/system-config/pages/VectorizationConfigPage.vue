<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { NButton, NForm, NFormItem, NInputNumber, NSpin, useMessage } from 'naive-ui'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import { configApi } from '../api'
import type { VectorizationSettings } from '../types'

const form = reactive<VectorizationSettings>({ concurrency: 1 })
const ready = ref(false)
const loading = ref(false)
const saving = ref(false)
const message = useMessage()
const showError = useErrorMessage()

async function load(): Promise<void> {
  if (loading.value || saving.value) return
  loading.value = true
  try {
    Object.assign(form, await configApi.vectorization())
    ready.value = true
  } catch (error: unknown) {
    showError(error)
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  if (!ready.value || loading.value || saving.value) return
  if (!Number.isInteger(form.concurrency) || form.concurrency < 1 || form.concurrency > 10) {
    message.warning('并发数请输入 1–10 的整数')
    return
  }
  saving.value = true
  try {
    Object.assign(form, await configApi.saveVectorization(form))
    message.success('自动向量化配置已保存，将用于后续新任务')
  } catch (error: unknown) {
    showError(error)
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="config-page">
    <div class="module-heading">
      <div>
        <span class="eyebrow">系统配置</span>
        <h1>自动向量化</h1>
        <p>统一设置公开法律库自动向量化的并发数，后续新任务共用。</p>
      </div>
      <NButton :loading="loading" :disabled="saving" @click="load">刷新配置</NButton>
    </div>
    <NSpin :show="loading">
      <NForm v-if="ready" label-placement="top" class="policy-form" @submit.prevent="save">
        <section class="form-section">
          <h2>解析与向量化并发</h2>
          <p>
            并发数表示同时解析和向量化的法规数量，范围为 1–10，默认 1。
            官网详情获取与原件下载固定串行执行，可与解析、分片和向量化同时进行，已完成的法规自动跳过。
          </p>
          <NFormItem label="同时解析和向量化的法规数">
            <NInputNumber
              :value="form.concurrency"
              :min="1"
              :max="10"
              :precision="0"
              :disabled="loading || saving"
              @update:value="(value) => (form.concurrency = value ?? 1)"
            />
          </NFormItem>
          <p>保存后用于新启动的任务；正在运行的任务保留启动时的并发数。</p>
          <div class="form-actions">
            <NButton type="primary" attr-type="submit" :loading="saving" :disabled="loading">
              保存配置
            </NButton>
          </div>
        </section>
      </NForm>
    </NSpin>
  </section>
</template>
