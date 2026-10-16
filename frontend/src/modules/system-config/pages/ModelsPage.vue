<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  NButton,
  NCheckbox,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NModal,
  NRadioButton,
  NRadioGroup,
  NSelect,
  NSpin,
  NSwitch,
  NTag,
  useMessage,
} from 'naive-ui'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import { configApi } from '../api'
import type { ModelConfig, ModelInput } from '../types'

const models = ref<ModelConfig[]>([])
const loading = ref(false)
const saving = ref(false)
const open = ref(false)
const editing = ref<string>()
const keyConfigured = ref(false)
const message = useMessage()
const showError = useErrorMessage()
type ModelForm = Omit<ModelInput, 'context_tokens' | 'max_output_tokens' | 'clear_api_key'> & {
  api_key: string
  context_tokens: string
  max_output_tokens: string
}
const keyAction = ref<'keep' | 'replace' | 'clear'>('replace')
const defaults = (): ModelForm => ({
  name: '',
  model_type: 'chat',
  protocol: 'chat_completions',
  base_url: '',
  model_name: '',
  enabled: true,
  supports_images: false,
  supports_pdf: false,
  supports_json_mode: false,
  context_tokens: '32000',
  max_output_tokens: '4096',
  token_parameter: 'max_tokens',
  temperature: null,
  api_key: '',
  embedding_dimensions: null,
  embedding_batch_size: 8,
  embedding_timeout: 90,
  embedding_query_instruction: '',
})
const form = reactive<ModelForm>(defaults())
const isEmbedding = computed(() => form.model_type === 'embedding')
const endpointPlaceholder = computed(() =>
  !isEmbedding.value
    ? '填写供应商 Base URL，例如 https://供应商地址/v1'
    : form.protocol === 'dashscope_embeddings'
      ? '填写 DashScope Base URL 或完整文本向量接口地址'
      : '填写供应商 Base URL 或完整 /embeddings 地址',
)
const protocolLabels: Record<ModelInput['protocol'], string> = {
  chat_completions: 'Chat Completions',
  responses: 'Responses',
  openai_embeddings: 'OpenAI 兼容 Embeddings',
  dashscope_embeddings: 'DashScope 原生文本向量',
}
const protocols = computed(() =>
  isEmbedding.value
    ? [
        { label: 'OpenAI 兼容 Embeddings', value: 'openai_embeddings' },
        { label: 'DashScope 原生文本向量', value: 'dashscope_embeddings' },
      ]
    : [
        { label: 'OpenAI 兼容 Chat Completions', value: 'chat_completions' },
        { label: 'OpenAI Responses', value: 'responses' },
      ],
)
function protocolLabel(model: ModelConfig): string {
  if (
    model.model_type === 'embedding' &&
    ['chat_completions', 'responses'].includes(model.protocol)
  )
    return protocolLabels.openai_embeddings
  return protocolLabels[model.protocol]
}

const types = [
  { label: '对话模型', value: 'chat' },
  { label: 'Embedding 模型', value: 'embedding' },
  { label: '其他模型', value: 'other' },
]

async function load(): Promise<void> {
  loading.value = true
  try {
    models.value = await configApi.models()
  } catch (error: unknown) {
    showError(error)
  } finally {
    loading.value = false
  }
}
function edit(model?: ModelConfig): void {
  editing.value = model?.id
  keyConfigured.value = model?.has_api_key ?? false
  keyAction.value = keyConfigured.value ? 'keep' : 'replace'
  Object.assign(form, defaults())
  if (model) {
    const { id, has_api_key, ...values } = model
    editing.value = id
    keyConfigured.value = has_api_key
    Object.assign(form, values, {
      protocol:
        model.model_type === 'embedding' &&
        ['chat_completions', 'responses'].includes(model.protocol)
          ? 'openai_embeddings'
          : model.protocol,
      context_tokens: String(model.context_tokens),
      max_output_tokens: String(model.max_output_tokens),
    })
  }
  open.value = true
}
async function save(): Promise<void> {
  if (saving.value) return
  if (!form.name.trim() || !form.base_url.trim() || !form.model_name.trim()) {
    message.warning('请填写名称、接口地址和模型标识')
    return
  }
  try {
    const address = form.base_url.trim()
    const endpoint = new URL(address)
    if (
      !/^https?:\/\//i.test(address) ||
      !['http:', 'https:'].includes(endpoint.protocol) ||
      !endpoint.hostname ||
      endpoint.username ||
      endpoint.password ||
      address.includes('?') ||
      address.includes('#')
    ) {
      message.warning('请输入不含凭据或查询参数的 HTTP(S) 地址')
      return
    }
  } catch {
    message.warning('请输入有效的 HTTP(S) 接口地址')
    return
  }
  const contextTokens = Number(form.context_tokens.trim())
  const outputTokens = Number(form.max_output_tokens.trim())
  const minimumInputTokens = isEmbedding.value ? 1 : 1024
  if (
    !/^\d+$/.test(form.context_tokens.trim()) ||
    !Number.isSafeInteger(contextTokens) ||
    contextTokens < minimumInputTokens ||
    contextTokens > 4_000_000
  ) {
    message.warning(
      `${isEmbedding.value ? '单条输入上限' : '上下文窗口'}请输入 ${minimumInputTokens.toLocaleString()}～4,000,000 之间的整数`,
    )
    return
  }
  if (
    !isEmbedding.value &&
    (!/^\d+$/.test(form.max_output_tokens.trim()) ||
      !Number.isSafeInteger(outputTokens) ||
      outputTokens < 128 ||
      outputTokens > 200_000)
  ) {
    message.warning('最大输出 Token 请输入 128～200,000 之间的整数')
    return
  }
  if (!isEmbedding.value && outputTokens >= contextTokens) {
    message.warning('最大输出 Token 必须小于上下文窗口，请调大上下文窗口或调小输出上限')
    return
  }
  if (isEmbedding.value) {
    if (
      !Number.isSafeInteger(form.embedding_batch_size) ||
      form.embedding_batch_size < 1 ||
      form.embedding_batch_size > 32
    ) {
      message.warning('每批文本数量请输入 1～32 的整数')
      return
    }
    if (
      !Number.isSafeInteger(form.embedding_timeout) ||
      form.embedding_timeout < 1 ||
      form.embedding_timeout > 300
    ) {
      message.warning('请求超时请输入 1～300 秒之间的整数')
      return
    }
    if (
      form.embedding_dimensions !== null &&
      (!Number.isSafeInteger(form.embedding_dimensions) ||
        form.embedding_dimensions < 1 ||
        form.embedding_dimensions > 4096)
    ) {
      message.warning('向量维度请输入 1～4096 的整数，或留空使用模型默认值')
      return
    }
  }
  if (keyAction.value === 'replace' && keyConfigured.value && !form.api_key.trim()) {
    message.warning('请输入要替换的 API Key，或选择保留现有密钥')
    return
  }
  saving.value = true
  try {
    const { api_key, ...values } = form
    const data: ModelInput = {
      ...values,
      name: form.name.trim(),
      base_url: form.base_url.trim(),
      model_name: form.model_name.trim(),
      context_tokens: contextTokens,
      max_output_tokens: isEmbedding.value ? 0 : outputTokens,
      supports_images: isEmbedding.value ? false : values.supports_images,
      supports_pdf: isEmbedding.value ? false : values.supports_pdf,
      supports_json_mode: isEmbedding.value ? false : values.supports_json_mode,
      temperature: isEmbedding.value ? null : values.temperature,
      embedding_dimensions: isEmbedding.value ? values.embedding_dimensions : null,
      embedding_batch_size: isEmbedding.value ? values.embedding_batch_size : 8,
      embedding_timeout: isEmbedding.value ? values.embedding_timeout : 90,
      embedding_query_instruction:
        isEmbedding.value && values.protocol === 'dashscope_embeddings'
          ? values.embedding_query_instruction
          : '',
      clear_api_key: keyConfigured.value && keyAction.value === 'clear',
    }
    if (keyAction.value === 'replace' && api_key.trim()) data.api_key = api_key.trim()
    await configApi.saveModel(data, editing.value)
    form.api_key = ''
    open.value = false
    message.success('模型配置已保存')
    await load()
  } catch (error: unknown) {
    showError(error)
  } finally {
    saving.value = false
  }
}
watch(
  () => form.model_type,
  (kind) => {
    if (kind === 'embedding' && ['chat_completions', 'responses'].includes(form.protocol)) {
      form.protocol = 'openai_embeddings'
      form.max_output_tokens = '0'
    } else if (
      kind !== 'embedding' &&
      ['openai_embeddings', 'dashscope_embeddings'].includes(form.protocol)
    ) {
      form.protocol = 'chat_completions'
      if (Number(form.max_output_tokens) < 128) form.max_output_tokens = '4096'
    }
  },
)
watch(keyAction, () => {
  form.api_key = ''
})
onMounted(() => {
  void load()
})
</script>

<template>
  <section class="config-page">
    <div class="module-heading">
      <div>
        <span class="eyebrow">系统配置</span>
        <h1>模型配置</h1>
        <p>管理平台全部模型，再为法律咨询选择可用的对话模型。</p>
      </div>
      <NButton type="primary" @click="edit()">新增模型</NButton>
    </div>
    <NSpin :show="loading">
      <NEmpty v-if="!loading && !models.length" description="尚未配置模型" class="module-empty" />
      <div class="config-list">
        <article v-for="model in models" :key="model.id" class="config-row">
          <div>
            <div class="row-title">
              <h3>{{ model.name }}</h3>
              <NTag :type="model.enabled ? 'success' : 'default'" size="small">{{
                model.enabled ? '已启用' : '已停用'
              }}</NTag>
            </div>
            <p>
              {{ model.model_name }} ·
              {{ protocolLabel(model) }}
            </p>
            <div class="row-tags">
              <NTag size="small">{{
                model.model_type === 'chat'
                  ? '对话'
                  : model.model_type === 'embedding'
                    ? '文本向量'
                    : '其他'
              }}</NTag
              ><NTag v-if="model.supports_images" size="small">图片</NTag
              ><NTag v-if="model.supports_pdf" size="small">PDF</NTag
              ><NTag
                v-if="model.model_type === 'embedding' && model.embedding_dimensions"
                size="small"
                >{{ model.embedding_dimensions }} 维</NTag
              ><span>{{ model.has_api_key ? '已设置密钥' : '未设置密钥' }}</span>
            </div>
          </div>
          <NButton secondary @click="edit(model)">编辑</NButton>
        </article>
      </div>
    </NSpin>
    <NModal
      v-model:show="open"
      preset="card"
      :title="editing ? '编辑模型' : '新增模型'"
      class="config-modal model-config-modal"
      :mask-closable="!saving"
      :close-on-esc="!saving"
      :closable="!saving"
      :content-style="{ overflowY: 'auto', minHeight: '0' }"
      @after-leave="form.api_key = ''"
    >
      <NForm label-placement="top" :show-feedback="false" :disabled="saving" @submit.prevent="save">
        <section class="model-form-section" aria-labelledby="model-basic-title">
          <div class="model-section-heading">
            <h2 id="model-basic-title">基础信息</h2>
            <div class="model-enabled">
              <span>启用模型</span><NSwitch v-model:value="form.enabled" />
            </div>
          </div>
          <div class="form-grid">
            <NFormItem label="显示名称" required>
              <NInput v-model:value="form.name" maxlength="100" placeholder="填写模型显示名称" />
            </NFormItem>
            <NFormItem label="模型类型">
              <NSelect v-model:value="form.model_type" :options="types" />
            </NFormItem>
          </div>
        </section>
        <section class="model-form-section" aria-labelledby="model-connection-title">
          <div class="model-section-heading"><h2 id="model-connection-title">接口与密钥</h2></div>
          <div class="form-grid">
            <NFormItem label="接口协议">
              <NSelect v-model:value="form.protocol" :options="protocols" />
            </NFormItem>
            <NFormItem label="供应商模型标识" required>
              <NInput
                v-model:value="form.model_name"
                maxlength="200"
                placeholder="填写实际模型标识"
              />
            </NFormItem>
          </div>
          <NFormItem label="接口地址" required>
            <div class="model-field">
              <NInput
                v-model:value="form.base_url"
                maxlength="1000"
                :placeholder="endpointPlaceholder"
              />
              <p v-if="form.protocol === 'dashscope_embeddings'" class="model-field-hint">
                支持百炼业务空间域名、/api/v1 原生地址、/compatible-mode/v1
                兼容地址或完整文本向量接口地址。百炼兼容地址会按当前协议解析为原生调用路径，请使用同地域的
                API Key。
              </p>
              <p v-else-if="isEmbedding" class="model-field-hint">
                支持供应商 Base URL 或完整 /embeddings 地址。百炼官方域名支持直接填写 /api/v1 或
                /compatible-mode/v1，系统会使用 OpenAI 兼容调用路径。
              </p>
              <p v-else class="model-field-hint">包含供应商要求的版本路径，例如 /v1。</p>
            </div>
          </NFormItem>
          <div class="model-key-panel">
            <div class="model-section-heading">
              <span class="model-key-label">API Key</span>
              <NTag size="small" :type="keyConfigured ? 'success' : 'default'">
                {{ keyConfigured ? '已设置密钥' : '未设置密钥' }}
              </NTag>
            </div>
            <NRadioGroup
              v-if="keyConfigured"
              v-model:value="keyAction"
              name="model-key-action"
              aria-label="密钥操作"
              size="small"
              :disabled="saving"
            >
              <NRadioButton value="keep">保留现有</NRadioButton>
              <NRadioButton value="replace">替换密钥</NRadioButton>
              <NRadioButton value="clear">清除密钥</NRadioButton>
            </NRadioGroup>
            <NFormItem v-if="keyAction === 'replace'" label="新密钥" :show-label="false">
              <NInput
                v-model:value="form.api_key"
                type="password"
                show-password-on="click"
                autocomplete="new-password"
                maxlength="2000"
                :aria-label="keyConfigured ? '替换 API Key' : 'API Key'"
                :placeholder="keyConfigured ? '输入新的 API Key' : '输入 API Key，无鉴权模型可留空'"
              />
            </NFormItem>
            <p class="model-field-hint">
              {{
                keyAction === 'clear'
                  ? '保存后将移除现有密钥。需要鉴权的接口须重新设置密钥才能使用。'
                  : keyAction === 'keep'
                    ? '保存其他配置时继续使用现有密钥，无需重复输入。'
                    : '密钥加密保存，保存后不回显。'
              }}
            </p>
          </div>
        </section>
        <section
          v-if="isEmbedding"
          class="model-form-section"
          aria-labelledby="model-embedding-title"
        >
          <div class="model-section-heading">
            <h2 id="model-embedding-title">文本向量参数</h2>
          </div>
          <div class="form-grid">
            <NFormItem label="单条输入上限（Token）" required
              ><div class="model-field">
                <NInput
                  v-model:value="form.context_tokens"
                  inputmode="numeric"
                  placeholder="按模型要求填写输入上限"
                />
                <p class="model-field-hint">
                  按供应商模型限制填写。输入长度会在请求前进行保守估算。
                </p>
              </div></NFormItem
            >
            <NFormItem label="输出向量维度"
              ><div class="model-field">
                <NInputNumber
                  v-model:value="form.embedding_dimensions"
                  :min="1"
                  :max="4096"
                  :precision="0"
                  clearable
                  placeholder="留空使用模型默认维度"
                />
                <p class="model-field-hint">按模型支持的维度填写；不支持维度参数的模型请留空。</p>
              </div></NFormItem
            >
            <NFormItem label="每批文本数量" required
              ><div class="model-field">
                <NInputNumber
                  v-model:value="form.embedding_batch_size"
                  :min="1"
                  :max="32"
                  :precision="0"
                />
                <p class="model-field-hint">按供应商的批量限制填写，最多 32 条。</p>
              </div></NFormItem
            >
            <NFormItem label="请求超时（秒）" required>
              <div class="model-field">
                <NInputNumber
                  v-model:value="form.embedding_timeout"
                  :min="1"
                  :max="300"
                  :precision="0"
                />
                <p class="model-field-hint">可填写 1～300 秒。</p>
              </div>
            </NFormItem>
          </div>
          <NFormItem v-if="form.protocol === 'dashscope_embeddings'" label="检索指令（可选）"
            ><div class="model-field">
              <NInput
                v-model:value="form.embedding_query_instruction"
                type="textarea"
                :maxlength="2000"
                placeholder="留空使用模型默认检索行为"
              />
              <p class="model-field-hint">仅在 query 检索时发送；入库固定使用 document 类型。</p>
            </div></NFormItem
          >
          <p class="model-field-hint">
            更改协议、模型、维度或检索指令后，请重新向量化相关文档，避免混用已有向量。
          </p>
        </section>
        <section v-else class="model-form-section" aria-labelledby="model-generation-title">
          <div class="model-section-heading"><h2 id="model-generation-title">生成参数</h2></div>
          <div class="form-grid">
            <NFormItem label="上下文窗口（Token）" required>
              <div class="model-field">
                <NInput
                  v-model:value="form.context_tokens"
                  inputmode="numeric"
                  placeholder="32000"
                />
                <p class="model-field-hint">输入与输出的总预算，1,024～4,000,000。</p>
              </div>
            </NFormItem>
            <NFormItem label="最大输出 Token" required>
              <div class="model-field">
                <NInput
                  v-model:value="form.max_output_tokens"
                  inputmode="numeric"
                  placeholder="4096"
                />
                <p class="model-field-hint">128～200,000，必须小于上下文窗口。</p>
              </div>
            </NFormItem>
          </div>
          <NFormItem label="输出上限参数（按供应商要求选择）">
            <div class="model-field">
              <NSelect
                v-if="form.protocol === 'chat_completions'"
                v-model:value="form.token_parameter"
                :options="[
                  { label: 'max_tokens', value: 'max_tokens' },
                  { label: 'max_completion_tokens', value: 'max_completion_tokens' },
                ]"
              />
              <NSelect
                v-else
                value="max_output_tokens"
                :options="[{ label: 'max_output_tokens', value: 'max_output_tokens' }]"
                disabled
              />
              <p class="model-field-hint">
                {{
                  form.protocol === 'responses'
                    ? 'Responses 协议固定使用 max_output_tokens，无需选择；切换为 Chat Completions 可选择其他参数名。'
                    : '选择供应商支持的参数名；切换协议会保留此选择。'
                }}
              </p>
            </div>
          </NFormItem>
          <NFormItem label="Temperature">
            <div class="model-field">
              <NInputNumber
                v-model:value="form.temperature"
                :min="0"
                :max="2"
                :step="0.1"
                placeholder="留空使用模型默认值"
                clearable
              />
            </div>
          </NFormItem>
          <NFormItem label="模型能力">
            <div class="model-capabilities">
              <NCheckbox v-model:checked="form.supports_images">图片</NCheckbox>
              <NCheckbox v-model:checked="form.supports_pdf">PDF</NCheckbox>
              <NCheckbox v-model:checked="form.supports_json_mode">JSON 模式</NCheckbox>
            </div>
          </NFormItem>
        </section>
      </NForm>
      <template #footer>
        <div class="model-modal-actions">
          <NButton :disabled="saving" @click="open = false">取消</NButton>
          <NButton type="primary" :loading="saving" @click="save">保存配置</NButton>
        </div>
      </template>
    </NModal>
  </section>
</template>

<style scoped>
.config-modal.model-config-modal {
  width: min(760px, calc(100vw - 32px)) !important;
  overflow: hidden;
}
.model-config-modal :deep(.n-card-header),
.model-config-modal :deep(.n-card__footer) {
  flex-shrink: 0;
}
.model-config-modal :deep(.n-card__footer) {
  border-top: 1px solid var(--line);
  padding-top: 16px;
}
.model-form-section + .model-form-section {
  margin-top: 24px;
  padding-top: 24px;
  border-top: 1px solid var(--line);
}
.model-section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}
.model-section-heading h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}
.model-enabled {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--muted);
}
.model-form-section :deep(.n-form-item) {
  margin-bottom: 16px;
}
.model-form-section .form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: start;
  column-gap: 20px;
}
.model-form-section :deep(.n-form-item-blank) {
  align-items: flex-start;
}
.model-field,
.model-field :deep(.n-input-number) {
  width: 100%;
  min-width: 0;
}
.model-field-hint {
  margin: 7px 0 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.7;
  overflow-wrap: anywhere;
}
.model-key-panel {
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--bronze-soft);
}
.model-key-panel .model-section-heading {
  margin-bottom: 12px;
}
.model-key-label {
  font-size: 14px;
  font-weight: 500;
}
.model-key-panel :deep(.n-form-item) {
  margin: 12px 0 0;
}
.model-key-panel :deep(.n-radio-group) + .model-field-hint {
  margin-top: 12px;
}
.model-capabilities {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 20px;
}
.model-modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
@media (max-width: 620px) {
  .model-form-section .form-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
