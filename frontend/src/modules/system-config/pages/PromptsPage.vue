<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import {
  NButton,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NPopconfirm,
  NSpin,
  NSwitch,
  NTag,
  useMessage,
} from 'naive-ui'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import { configApi } from '../api'
import type { PromptInput, PromptVersion, SystemPrompt } from '../types'

const prompts = ref<SystemPrompt[]>([])
const versions = ref<PromptVersion[]>([])
const loading = ref(false)
const saving = ref(false)
const deleting = ref<string>()
const open = ref(false)
const historyOpen = ref(false)
const editing = ref<string>()
const form = reactive<PromptInput>({ name: '', content: '', enabled: true })
const message = useMessage()
const showError = useErrorMessage()
async function load(): Promise<void> {
  loading.value = true
  try {
    prompts.value = await configApi.prompts()
  } catch (error: unknown) {
    showError(error)
  } finally {
    loading.value = false
  }
}
function edit(prompt?: SystemPrompt): void {
  editing.value = prompt?.id
  Object.assign(form, { name: '', content: '', enabled: true }, prompt ?? {})
  open.value = true
}
async function save(): Promise<void> {
  if (!form.name.trim() || !form.content.trim()) {
    message.warning('请填写名称和系统提示词正文')
    return
  }
  saving.value = true
  try {
    await configApi.savePrompt(form, editing.value)
    open.value = false
    message.success('系统提示词已保存')
    await load()
  } catch (error: unknown) {
    showError(error)
  } finally {
    saving.value = false
  }
}
async function history(id: string): Promise<void> {
  try {
    versions.value = await configApi.versions(id)
    historyOpen.value = true
  } catch (error: unknown) {
    showError(error)
  }
}
async function remove(prompt: SystemPrompt): Promise<boolean> {
  if (deleting.value) return false
  deleting.value = prompt.id
  try {
    await configApi.deletePrompt(prompt.id)
    prompts.value = prompts.value.filter((row) => row.id !== prompt.id)
    message.success('系统提示词已删除')
    return true
  } catch (error: unknown) {
    showError(error)
    return false
  } finally {
    deleting.value = undefined
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
        <h1>系统提示词</h1>
        <p>设定回答方式与工作边界，每次编辑保留独立版本。</p>
      </div>
      <NButton type="primary" @click="edit()">新增提示词</NButton>
    </div>
    <NSpin :show="loading"
      ><NEmpty
        v-if="!loading && !prompts.length"
        description="尚未配置系统提示词"
        class="module-empty"
      />
      <div class="config-list">
        <article v-for="prompt in prompts" :key="prompt.id" class="config-row">
          <div>
            <div class="row-title">
              <h3>{{ prompt.name }}</h3>
              <NTag size="small">v{{ prompt.version }}</NTag
              ><NTag size="small" :type="prompt.enabled ? 'success' : 'default'">{{
                prompt.enabled ? '已启用' : '已停用'
              }}</NTag>
            </div>
            <p class="prompt-preview">{{ prompt.content }}</p>
          </div>
          <div class="row-actions">
            <NButton quaternary :disabled="!!deleting" @click="history(prompt.id)">版本</NButton
            ><NButton secondary :disabled="!!deleting" @click="edit(prompt)">编辑</NButton>
            <NPopconfirm
              :positive-button-props="{ loading: deleting === prompt.id }"
              :negative-button-props="{ disabled: !!deleting }"
              @positive-click="remove(prompt)"
            >
              <template #trigger>
                <NButton
                  secondary
                  type="error"
                  :loading="deleting === prompt.id"
                  :disabled="!!deleting"
                  :aria-label="`删除系统提示词 ${prompt.name}`"
                  >删除</NButton
                >
              </template>
              删除“{{
                prompt.name
              }}”及其全部版本？如为默认提示词，将自动清空默认项。历史对话不受影响。
            </NPopconfirm>
          </div>
        </article>
      </div></NSpin
    >
    <NModal
      v-model:show="open"
      preset="card"
      :title="editing ? '编辑系统提示词' : '新增系统提示词'"
      class="config-modal"
      :mask-closable="!saving"
      ><NForm label-placement="top" @submit.prevent="save"
        ><NFormItem label="名称"
          ><NInput
            v-model:value="form.name"
            maxlength="100"
            placeholder="为提示词命名" /></NFormItem
        ><NFormItem label="系统提示词正文"
          ><NInput
            v-model:value="form.content"
            type="textarea"
            :autosize="{ minRows: 10, maxRows: 20 }"
            maxlength="30000"
            show-count
            placeholder="填写角色、回答要求、适用范围和引用规则" /></NFormItem
        ><NFormItem label="启用"><NSwitch v-model:value="form.enabled" /></NFormItem>
        <div class="form-actions">
          <NButton :disabled="saving" @click="open = false">取消</NButton
          ><NButton type="primary" attr-type="submit" :loading="saving">保存新版本</NButton>
        </div></NForm
      ></NModal
    >
    <NModal v-model:show="historyOpen" preset="card" title="提示词版本" class="config-modal"
      ><article v-for="version in versions" :key="version.version" class="prompt-version">
        <h3>{{ version.name }} · v{{ version.version }}</h3>
        <pre>{{ version.content }}</pre>
      </article></NModal
    >
  </section>
</template>
