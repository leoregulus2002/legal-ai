<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
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
})
const form = reactive<ModelForm>(defaults())
const protocols = [
  { label: 'OpenAI 兼容 Chat Completions', value: 'chat_completions' },
  { label: 'OpenAI Responses', value: 'responses' },
]
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
  const contextTokens = Number(form.context_tokens.trim())
  const outputTokens = Number(form.max_output_tokens.trim())
  if (
    !/^\d+$/.test(form.context_tokens.trim()) ||
    !Number.isSafeInteger(contextTokens) ||
    contextTokens < 1024 ||
    contextTokens > 4_000_000
  ) {
    message.warning('上下文窗口请输入 1,024～4,000,000 之间的整数')
    return
  }
  if (
    !/^\d+$/.test(form.max_output_tokens.trim()) ||
    !Number.isSafeInteger(outputTokens) ||
    outputTokens < 128 ||
    outputTokens > 200_000
  ) {
    message.warning('最大输出 Token 请输入 128～200,000 之间的整数')
    return
  }
  if (outputTokens >= contextTokens) {
    message.warning('最大输出 Token 必须小于上下文窗口，请调大上下文窗口或调小输出上限')
    return
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
      max_output_tokens: outputTokens,
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
              {{ model.protocol === 'responses' ? 'Responses' : 'Chat Completions' }}
            </p>
            <div class="row-tags">
              <NTag size="small">{{ model.model_type === 'chat' ? '对话' : model.model_type }}</NTag
              ><NTag v-if="model.supports_images" size="small">图片</NTag
              ><NTag v-if="model.supports_pdf" size="small">PDF</NTag
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
              <NInput v-model:value="form.name" maxlength="100" placeholder="例如：法律咨询模型" />
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
                placeholder="https://供应商地址/v1"
              />
              <p class="model-field-hint">包含供应商要求的版本路径，例如 /v1。</p>
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
        <section class="model-form-section" aria-labelledby="model-generation-title">
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
</style>
