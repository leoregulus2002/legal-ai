<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { NButton, NForm, NFormItem, NInputNumber, NSelect, NSpin, useMessage } from 'naive-ui'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import { knowledgeApi } from '../../knowledge/api'
import type { KnowledgeBase } from '../../knowledge/types'
import { configApi } from '../api'
import { defaultPolicy, type ModelConfig, type PolicyInput, type SystemPrompt } from '../types'

const models = ref<ModelConfig[]>([])
const prompts = ref<SystemPrompt[]>([])
const knowledgeBases = ref<KnowledgeBase[]>([])
const form = reactive<PolicyInput>(defaultPolicy())
const ready = ref(false)
const loading = ref(false)
const saving = ref(false)
const showError = useErrorMessage()
const message = useMessage()
const modelOptions = computed(() =>
  models.value
    .filter((m) => m.enabled && m.model_type === 'chat')
    .map((m) => ({ label: m.name, value: m.id })),
)
const defaultModelOptions = computed(() =>
  modelOptions.value.filter((m) => form.allowed_model_ids.includes(m.value)),
)
const promptOptions = computed(() =>
  prompts.value
    .filter((p) => p.enabled)
    .map((p) => ({ label: `${p.name} · v${p.version}`, value: p.id })),
)
const knowledgeOptions = computed(() => [
  ...knowledgeBases.value.map((base) => ({ label: base.name, value: base.id })),
  ...form.knowledge_base_ids
    .filter((id) => !knowledgeBases.value.some((base) => base.id === id))
    .map((id) => ({ label: '已删除的知识库（请移除）', value: id })),
])
async function loadKnowledgeBases(): Promise<KnowledgeBase[]> {
  const rows: KnowledgeBase[] = []
  for (let page = 1; ; page++) {
    const result = await knowledgeApi.bases('', page, 100)
    rows.push(...result.items)
    if (rows.length >= result.total || result.items.length < 100) return rows
  }
}
function changeModels(ids: string[]): void {
  form.allowed_model_ids = ids
  if (form.default_model_id && !ids.includes(form.default_model_id)) form.default_model_id = null
}
async function load(): Promise<void> {
  loading.value = true
  try {
    const [modelRows, promptRows, policy, bases] = await Promise.all([
      configApi.models(),
      configApi.prompts(),
      configApi.policy(),
      loadKnowledgeBases(),
    ])
    models.value = modelRows
    prompts.value = promptRows
    knowledgeBases.value = bases
    Object.assign(form, policy)
    ready.value = true
  } catch (error: unknown) {
    showError(error)
  } finally {
    loading.value = false
  }
}
async function save(): Promise<void> {
  if (saving.value || loading.value || !ready.value) return
  saving.value = true
  try {
    const policy = await configApi.savePolicy(form)
    Object.assign(form, policy)
    message.success('法律咨询配置已保存')
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
        <h1>法律咨询模型</h1>
        <p>选择咨询可用模型，管理提示词、记忆和知识库接入策略。</p>
      </div>
      <NButton :loading="loading" @click="load">刷新配置</NButton>
    </div>
    <NSpin :show="loading"
      ><NForm v-if="ready" label-placement="top" class="policy-form" @submit.prevent="save">
        <section class="form-section">
          <h2>对话模型与提示词</h2>
          <p>模型来自模型配置目录。<RouterLink to="/settings/models">管理全部模型</RouterLink></p>
          <NFormItem label="法律咨询可用模型"
            ><NSelect
              :value="form.allowed_model_ids"
              multiple
              :options="modelOptions"
              placeholder="选择已启用的对话模型"
              @update:value="changeModels"
          /></NFormItem>
          <div class="form-grid">
            <NFormItem label="默认模型"
              ><NSelect
                v-model:value="form.default_model_id"
                :options="defaultModelOptions"
                clearable
                placeholder="选择默认模型" /></NFormItem
            ><NFormItem label="默认系统提示词（可选）"
              ><NSelect
                v-model:value="form.default_prompt_id"
                :options="promptOptions"
                clearable
                placeholder="不使用系统提示词"
            /></NFormItem>
          </div>
        </section>
        <section class="form-section">
          <h2>会话记忆</h2>
          <p>
            每累计完成 N 轮对话，在下一次回答前压缩一次，按 N、2N、3N……轮分批合并到摘要。
            两次压缩之间保留完整原文。运行记忆过期后从聊天历史恢复。
          </p>
          <div class="form-grid">
            <NFormItem label="上下文压缩间隔（N 轮）"
              ><NInputNumber v-model:value="form.recent_turns" :min="1" :max="30" /></NFormItem
            ><NFormItem label="摘要字数上限"
              ><NInputNumber
                v-model:value="form.summary_chars"
                :min="200"
                :max="8000"
                :step="100" /></NFormItem
            ><NFormItem label="关键词数量上限"
              ><NInputNumber v-model:value="form.keyword_count" :min="1" :max="30" /></NFormItem
            ><NFormItem label="记忆有效期（天，使用后续期）"
              ><NInputNumber v-model:value="form.memory_ttl_days" :min="1" :max="90"
            /></NFormItem>
          </div>
        </section>
        <section class="form-section">
          <h2>知识库接入</h2>
          <p>
            添加已有的内部知识库，法律对话仅检索所选库中已发布的资料。
            <RouterLink to="/knowledge">管理内部知识库</RouterLink>
          </p>
          <NFormItem label="添加内部知识库"
            ><NSelect
              v-model:value="form.knowledge_base_ids"
              multiple
              filterable
              clearable
              :max="100"
              :max-tag-count="3"
              :options="knowledgeOptions"
              placeholder="选择一个或多个内部知识库"
            />
          </NFormItem>
          <p v-if="!knowledgeBases.length">还没有内部知识库，可先前往知识库页面创建并发布资料。</p>
          <div class="form-grid">
            <NFormItem label="最低向量相似度（0–1）"
              ><NInputNumber
                v-model:value="form.knowledge_vector_threshold"
                :min="0"
                :max="1"
                :step="0.05" /></NFormItem
            ><NFormItem label="最低关键词覆盖率（0–1）"
              ><NInputNumber
                v-model:value="form.knowledge_keyword_threshold"
                :min="0"
                :max="1"
                :step="0.05" /></NFormItem
            ><NFormItem label="最多引用资料数"
              ><NInputNumber v-model:value="form.knowledge_limit" :min="1" :max="20"
            /></NFormItem>
          </div>
          <p>
            内部知识库合并关键词和语义检索结果；暂无可用向量索引时使用关键词检索。两类门槛分别控制候选范围，最终按融合排名选择引用。
          </p>
        </section>
        <section class="form-section">
          <h2>附件与生成</h2>
          <div class="form-grid">
            <NFormItem label="每条消息附件数"
              ><NInputNumber v-model:value="form.max_attachments" :min="1" :max="10" /></NFormItem
            ><NFormItem label="单文件上限（MiB）"
              ><NInputNumber v-model:value="form.max_file_mb" :min="1" :max="25" /></NFormItem
            ><NFormItem label="每条消息总大小（MiB）"
              ><NInputNumber v-model:value="form.max_total_mb" :min="1" :max="50" /></NFormItem
            ><NFormItem label="生成总超时（秒）"
              ><NInputNumber v-model:value="form.request_timeout" :min="30" :max="900"
            /></NFormItem>
          </div>
        </section>
        <div class="form-actions">
          <NButton type="primary" attr-type="submit" :loading="saving" :disabled="loading"
            >保存法律咨询配置</NButton
          >
        </div>
      </NForm></NSpin
    >
  </section>
</template>
