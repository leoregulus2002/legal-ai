<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
  NButton,
  NCheckbox,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NModal,
  NSelect,
  NSpin,
  NSwitch,
  NTag,
  useDialog,
  useMessage,
} from 'naive-ui'
import { analysisApi } from '../api'
import { configApi } from '../../system-config/api'
import type { SystemPrompt } from '../../system-config/types'
import type {
  AgentRole,
  AnalysisConfig,
  MCPServerInput,
  MCPServerView,
  MCPTool,
  ModelOption,
} from '../types'
import { useAnalysisError } from '../useAnalysisError'
import '../styles.css'
const message = useMessage()
const dialog = useDialog()
const showError = useAnalysisError()
const config = ref<AnalysisConfig | null>(null)
const models = ref<ModelOption[]>([])
const prompts = ref<SystemPrompt[]>([])
const knowledgeBases = ref<{ id: string; name: string }[]>([])
const servers = ref<MCPServerView[]>([])
const loading = ref(false)
const saving = ref(false)
const serverSaving = ref(false)
const discovering = ref(false)
const deleting = ref<string | null>(null)
const serverModal = ref(false)
const serverId = ref<string | null>(null)
const hasToken = ref(false)
const tools = ref<MCPTool[]>([])
const discovered = ref(false)
const serverForm = reactive<MCPServerInput>(emptyServer())
const roles: { value: AgentRole; label: string }[] = [
  { value: 'intent', label: '意图识别与任务规划' },
  { value: 'contract', label: '合同分析' },
  { value: 'litigation', label: '诉讼分析' },
  { value: 'judgment', label: '裁判分析' },
  { value: 'research', label: '法律研究' },
  { value: 'review', label: '报告复核' },
]
const promptOptions = computed(() =>
  prompts.value.map((prompt) => ({
    value: prompt.id,
    label: `${prompt.name} · v${prompt.version}${prompt.enabled ? '' : ' · 已停用'}`,
    disabled: !prompt.enabled,
  })),
)
const modelOptions = computed(() =>
  models.value.map((model) => ({
    value: model.id,
    label: `${model.name}${model.supports_tools ? ' · 支持工具' : ' · 无工具调用'}`,
    disabled: !model.supports_tools,
  })),
)
const allowedOptions = computed(() => [
  ...tools.value.map((tool) => ({
    value: tool.name,
    label: tool.description ? `${tool.name} · ${tool.description}` : tool.name,
  })),
  ...serverForm.allowed_tools
    .filter((name) => !tools.value.some((tool) => tool.name === name))
    .map((name) => ({ value: name, label: `${name}（已授权）` })),
])
let alive = true
let editorGeneration = 0
function emptyServer(): MCPServerInput {
  return {
    name: '',
    url: '',
    token: null,
    clear_token: false,
    enabled: false,
    allowed_tools: [],
    timeout: 30,
    allow_document_content: false,
  }
}
async function load(): Promise<void> {
  if (loading.value || saving.value || serverSaving.value) return
  loading.value = true
  try {
    const [settings, available, rows, systemPrompts] = await Promise.all([
      analysisApi.config(),
      analysisApi.options(),
      analysisApi.servers(),
      configApi.prompts(),
    ])
    if (!alive) return
    for (const role of roles)
      settings.agent_configs[role.value] ??= { model_id: null, prompt_id: null }
    config.value = settings
    models.value = available.models
    prompts.value = systemPrompts
    knowledgeBases.value = available.knowledge_bases
    servers.value = rows
  } catch (error: unknown) {
    if (alive) showError(error)
  } finally {
    if (alive) loading.value = false
  }
}
async function save(): Promise<void> {
  if (!config.value || saving.value || loading.value) return
  for (const role of roles) {
    const promptId = config.value.agent_configs[role.value]?.prompt_id
    if (!prompts.value.some((prompt) => prompt.id === promptId && prompt.enabled)) {
      message.warning(`请为${role.label}选择已启用的系统提示词`)
      return
    }
  }
  if (
    Object.values(config.value.agent_configs).some(
      (role) =>
        role.model_id &&
        !models.value.some((model) => model.id === role.model_id && model.supports_tools),
    )
  ) {
    message.warning('请为各角色选择支持工具调用的模型，或跟随任务模型')
    return
  }
  const limits = [
    [config.value.max_parallel_agents, 1, 3],
    [config.value.max_tool_calls, 1, 100],
    [config.value.max_model_calls, 6, 80],
    [config.value.timeout_seconds, 60, 3600],
  ]
  if (
    limits.some(
      ([value, min, max]) =>
        value === undefined ||
        min === undefined ||
        max === undefined ||
        !Number.isInteger(value) ||
        value < min ||
        value > max,
    )
  ) {
    message.warning('请在允许范围内填写完整的执行预算')
    return
  }
  saving.value = true
  try {
    const row = await analysisApi.saveConfig(config.value)
    if (!alive) return
    for (const role of roles) row.agent_configs[role.value] ??= { model_id: null, prompt_id: null }
    config.value = row
    message.success('文书分析配置已保存')
  } catch (error: unknown) {
    if (alive) showError(error)
  } finally {
    if (alive) saving.value = false
  }
}
function editServer(server?: MCPServerView): void {
  ++editorGeneration
  serverId.value = server?.id ?? null
  hasToken.value = server?.has_token ?? false
  tools.value = []
  discovered.value = false
  Object.assign(
    serverForm,
    server
      ? {
          name: server.name,
          url: server.url,
          enabled: server.enabled,
          allowed_tools: [...server.allowed_tools],
          timeout: server.timeout,
          allow_document_content: server.allow_document_content,
          token: null,
          clear_token: false,
        }
      : emptyServer(),
  )
  serverModal.value = true
}
async function saveServer(): Promise<void> {
  if (serverSaving.value || discovering.value) return
  if (!serverForm.name.trim() || !serverForm.url.trim()) {
    message.warning('请填写服务名称与地址')
    return
  }
  if (!Number.isInteger(serverForm.timeout) || serverForm.timeout < 5 || serverForm.timeout > 120) {
    message.warning('工具超时应为 5 至 120 秒')
    return
  }
  serverSaving.value = true
  const generation = editorGeneration
  try {
    const row = await analysisApi.saveServer(
      {
        ...serverForm,
        name: serverForm.name.trim(),
        url: serverForm.url.trim(),
        token: serverForm.token || null,
      },
      serverId.value ?? undefined,
    )
    if (!alive) return
    servers.value = [row, ...servers.value.filter((item) => item.id !== row.id)]
    if (generation === editorGeneration) {
      serverId.value = row.id
      hasToken.value = row.has_token
      serverForm.token = null
      serverForm.clear_token = false
      message.success('MCP 服务已保存')
    }
  } catch (error: unknown) {
    if (alive) showError(error)
  } finally {
    if (alive) serverSaving.value = false
  }
}
async function discoverTools(): Promise<void> {
  const id = serverId.value
  if (!id || discovering.value || serverSaving.value) return
  discovering.value = true
  const generation = editorGeneration
  try {
    const rows = await analysisApi.discover(id)
    if (!alive || generation !== editorGeneration) return
    tools.value = rows
    discovered.value = true
    message.success(`已发现 ${rows.length} 个工具，请选择允许的工具后保存`)
  } catch (error: unknown) {
    if (alive && generation === editorGeneration) showError(error)
  } finally {
    if (alive) discovering.value = false
  }
}
function deleteServer(server: MCPServerView): void {
  if (deleting.value) return
  dialog.warning({
    title: '删除 MCP 服务',
    content: `确认删除“${server.name}”及其工具授权配置？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      deleting.value = server.id
      try {
        await analysisApi.deleteServer(server.id)
        if (alive) servers.value = servers.value.filter((item) => item.id !== server.id)
      } catch (error: unknown) {
        if (alive) showError(error)
        return false
      } finally {
        if (alive) deleting.value = null
      }
    },
  })
}
onMounted(() => {
  void load()
})
onBeforeUnmount(() => {
  alive = false
  ++editorGeneration
})
</script>
<template>
  <section class="config-page document-analysis-settings">
    <div class="module-heading">
      <div>
        <span class="eyebrow">系统配置</span>
        <h1>文书分析配置</h1>
        <p>管理分析预算、角色模型与外部工具授权。</p>
      </div>
      <NButton :loading="loading" :disabled="saving || serverSaving" @click="load"
        >刷新配置</NButton
      >
    </div>
    <NSpin :show="loading"
      ><NForm
        v-if="config"
        label-placement="top"
        class="policy-form"
        :disabled="saving"
        @submit.prevent="save"
        ><section class="form-section">
          <h2>自动分析</h2>
          <p class="analysis-muted">
            对话中无需选择意图、立场或工具。AI 会从这里允许的能力中按需使用。
          </p>
          <div class="form-grid">
            <NFormItem label="默认分析模型"
              ><NSelect
                v-model:value="config.default_model_id"
                clearable
                :options="modelOptions"
                placeholder="自动使用已配置的可用模型"
            /></NFormItem>
            <NFormItem label="可用知识库"
              ><NSelect
                v-model:value="config.knowledge_base_ids"
                multiple
                clearable
                :options="knowledgeBases.map((base) => ({ label: base.name, value: base.id }))"
                placeholder="未指定时沿用法律咨询的知识库"
            /></NFormItem>
          </div>
        </section>
        <section class="form-section">
          <h2>执行预算</h2>
          <div class="form-grid">
            <NFormItem label="并行分析角色数"
              ><NInputNumber
                v-model:value="config.max_parallel_agents"
                :min="1"
                :max="3"
                :precision="0"
                :show-button="true"
                :update-value-on-input="false" /></NFormItem
            ><NFormItem label="工具调用上限"
              ><NInputNumber
                v-model:value="config.max_tool_calls"
                :min="1"
                :max="100"
                :precision="0"
                :update-value-on-input="false" /></NFormItem
            ><NFormItem label="模型调用上限"
              ><NInputNumber
                v-model:value="config.max_model_calls"
                :min="6"
                :max="80"
                :precision="0"
                :update-value-on-input="false" /></NFormItem
            ><NFormItem label="任务超时（秒）"
              ><NInputNumber
                v-model:value="config.timeout_seconds"
                :min="60"
                :max="3600"
                :precision="0"
                :update-value-on-input="false"
            /></NFormItem>
          </div>
        </section>
        <section class="form-section">
          <h2>角色模型与提示词</h2>
          <p>
            未指定角色模型时使用默认分析模型。<RouterLink to="/settings/models"
              >管理模型</RouterLink
            >
            · <RouterLink to="/settings/prompts">管理系统提示词</RouterLink>
          </p>
          <div v-for="role in roles" :key="role.value" class="analysis-role-config">
            <template v-if="config.agent_configs[role.value]"
              ><h3>{{ role.label }}</h3>
              <NFormItem label="模型"
                ><NSelect
                  v-model:value="config.agent_configs[role.value]!.model_id"
                  clearable
                  :options="modelOptions"
                  placeholder="跟随任务模型" /></NFormItem
              ><NFormItem label="系统提示词" required
                ><NSelect
                  v-model:value="config.agent_configs[role.value]!.prompt_id"
                  filterable
                  :options="promptOptions"
                  placeholder="选择该角色的系统提示词"
              /></NFormItem>
              <details
                v-if="config.agent_configs[role.value]!.prompt_id"
                class="analysis-role-prompt-preview"
              >
                <summary>查看当前提示词</summary>
                <p>
                  {{
                    prompts.find(
                      (prompt) => prompt.id === config!.agent_configs[role.value]!.prompt_id,
                    )?.content
                  }}
                </p>
              </details>
            </template>
          </div>
        </section>
        <div class="form-actions">
          <NButton type="primary" attr-type="submit" :loading="saving">保存分析配置</NButton>
        </div></NForm
      ></NSpin
    >
    <section class="form-section analysis-mcp-section">
      <div class="analysis-panel-heading">
        <div>
          <h2>外部工具 · MCP</h2>
          <p class="analysis-muted">
            配置并授权一次后，AI 会在对话中按需调用。启用服务前请确认工具和文书内容授权。
          </p>
        </div>
        <NButton :disabled="loading" @click="editServer()">添加服务</NButton>
      </div>
      <NEmpty v-if="!servers.length" description="尚未配置 MCP 服务" />
      <article v-for="server in servers" :key="server.id" class="analysis-server-row">
        <div>
          <h3>
            {{ server.name }}
            <NTag size="small" :type="server.enabled ? 'success' : 'default'">{{
              server.enabled ? '已启用' : '已停用'
            }}</NTag>
          </h3>
          <p class="analysis-muted">
            已授权 {{ server.allowed_tools.length }} 个工具 ·
            {{
              server.allow_document_content ? '允许发送文书内容' : '未授权文书内容，分析时不启用'
            }}
            ·
            {{ server.has_token ? '已保存凭据' : '未配置凭据' }}
          </p>
        </div>
        <div class="analysis-actions">
          <NButton size="small" @click="editServer(server)">配置</NButton
          ><NButton
            size="small"
            type="error"
            :disabled="!!deleting"
            :loading="deleting === server.id"
            @click="deleteServer(server)"
            >删除</NButton
          >
        </div>
      </article>
    </section>
    <NModal
      v-model:show="serverModal"
      preset="card"
      :title="serverId ? '配置 MCP 服务' : '添加 MCP 服务'"
      style="width: min(700px, 94vw)"
      :mask-closable="!serverSaving && !discovering"
      :close-on-esc="!serverSaving && !discovering"
      :closable="!serverSaving && !discovering"
      @after-leave="serverForm.token = null"
      ><NForm
        label-placement="top"
        :disabled="serverSaving || discovering"
        @submit.prevent="saveServer"
        ><div class="analysis-form-grid">
          <NFormItem label="服务名称"
            ><NInput v-model:value="serverForm.name" :maxlength="100" /></NFormItem
          ><NFormItem label="工具超时（秒）"
            ><NInputNumber v-model:value="serverForm.timeout" :min="5" :max="120" :precision="0"
          /></NFormItem>
        </div>
        <NFormItem label="MCP 地址"
          ><NInput
            v-model:value="serverForm.url"
            :maxlength="1000"
            placeholder="https://…" /></NFormItem
        ><NFormItem :label="hasToken ? '更新凭据（已保存，留空保留）' : '访问凭据（可选）'"
          ><NInput
            v-model:value="serverForm.token"
            type="password"
            show-password-on="click"
            :maxlength="4000"
            autocomplete="new-password"
            :disabled="serverForm.clear_token" /></NFormItem
        ><NCheckbox v-if="hasToken" v-model:checked="serverForm.clear_token"
          >清空已保存的凭据</NCheckbox
        ><NFormItem label="启用服务"><NSwitch v-model:value="serverForm.enabled" /></NFormItem
        ><NCheckbox v-model:checked="serverForm.allow_document_content"
          >明确允许将所选文书内容发送给此 MCP 服务</NCheckbox
        >
        <p class="analysis-muted">
          仅在理解此服务的数据处理方式后开启。未勾选时，此服务不会在文书分析中启用。
        </p>
        <div class="analysis-panel-heading">
          <h3>工具授权</h3>
          <NButton
            :disabled="!serverId || serverSaving"
            :loading="discovering"
            @click="discoverTools"
            >发现工具</NButton
          >
        </div>
        <p class="analysis-muted">发现工具使用已保存的地址与凭据，修改后请先保存服务。</p>
        <p v-if="!serverId" class="analysis-muted">请先保存服务，再发现工具。</p>
        <NSelect
          v-model:value="serverForm.allowed_tools"
          multiple
          clearable
          filterable
          :max="30"
          :options="allowedOptions"
          placeholder="选择允许调用的工具"
        />
        <p v-if="discovered && !tools.length" class="analysis-muted">此服务未返回可用工具。</p>
        <details v-for="tool in tools" :key="tool.name" class="analysis-law">
          <summary>{{ tool.name }}</summary>
          <p>{{ tool.description }}</p>
          <pre class="analysis-tool-schema">{{ JSON.stringify(tool.input_schema, null, 2) }}</pre>
        </details>
        <div class="analysis-actions analysis-settings-actions">
          <NButton :disabled="serverSaving || discovering" @click="serverModal = false"
            >关闭</NButton
          ><NButton
            type="primary"
            attr-type="submit"
            :loading="serverSaving"
            :disabled="discovering"
            >保存服务与授权</NButton
          >
        </div></NForm
      ></NModal
    >
  </section>
</template>
