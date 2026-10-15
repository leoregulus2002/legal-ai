<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  NButton,
  NCheckbox,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSelect,
  NSpin,
  useMessage,
} from 'naive-ui'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import { configApi } from '../api'
import { defaultPolicy, type ModelConfig, type PolicyInput, type SystemPrompt } from '../types'

const models = ref<ModelConfig[]>([])
const prompts = ref<SystemPrompt[]>([])
const form = reactive<
  PolicyInput & { knowledge_api_key: string; clear_knowledge_api_key: boolean }
>({ ...defaultPolicy(), knowledge_api_key: '', clear_knowledge_api_key: false })
const ready = ref(false)
const loading = ref(false)
const saving = ref(false)
const keyConfigured = ref(false)
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
function changeModels(ids: string[]): void {
  form.allowed_model_ids = ids
  if (form.default_model_id && !ids.includes(form.default_model_id)) form.default_model_id = null
}
async function load(): Promise<void> {
  loading.value = true
  try {
    const [modelRows, promptRows, policy] = await Promise.all([
      configApi.models(),
      configApi.prompts(),
      configApi.policy(),
    ])
    models.value = modelRows
    prompts.value = promptRows
    Object.assign(form, policy, { knowledge_api_key: '', clear_knowledge_api_key: false })
    keyConfigured.value = policy.has_knowledge_api_key
    ready.value = true
  } catch (error: unknown) {
    showError(error)
  } finally {
    loading.value = false
  }
}
async function save(): Promise<void> {
  saving.value = true
  try {
    const { knowledge_api_key, ...data } = form
    const policy = await configApi.savePolicy(
      knowledge_api_key && !form.clear_knowledge_api_key ? { ...data, knowledge_api_key } : data,
    )
    keyConfigured.value = policy.has_knowledge_api_key
    form.knowledge_api_key = ''
    form.clear_knowledge_api_key = false
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
          <p>运行记忆保存在 Redis，过期后从已完成的聊天历史恢复。</p>
          <div class="form-grid">
            <NFormItem label="保留最近 N 轮"
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
          <p>接口留空视为空库；启用知识库且没有命中时，回复“知识库找不到对应信息”。</p>
          <NFormItem label="检索接口地址"
            ><NInput
              v-model:value="form.knowledge_url"
              placeholder="填写外部知识库 HTTP 检索接口" /></NFormItem
          ><NFormItem :label="keyConfigured ? '知识库 API Key（留空保留）' : '知识库 API Key'"
            ><NInput
              v-model:value="form.knowledge_api_key"
              type="password"
              show-password-on="click"
              autocomplete="new-password"
              :disabled="form.clear_knowledge_api_key"
              placeholder="可选，加密保存" /></NFormItem
          ><NCheckbox v-if="keyConfigured" v-model:checked="form.clear_knowledge_api_key"
            >清除现有知识库密钥</NCheckbox
          >
          <div class="form-grid">
            <NFormItem label="相关度阈值（0–1）"
              ><NInputNumber
                v-model:value="form.knowledge_threshold"
                :min="0"
                :max="1"
                :step="0.05" /></NFormItem
            ><NFormItem label="最多引用资料数"
              ><NInputNumber v-model:value="form.knowledge_limit" :min="1" :max="20" /></NFormItem
            ><NFormItem label="检索超时（秒）"
              ><NInputNumber v-model:value="form.knowledge_timeout" :min="1" :max="120"
            /></NFormItem>
          </div>
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
