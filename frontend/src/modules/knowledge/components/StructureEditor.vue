<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { NButton, NInput, NModal, NPagination, NPopconfirm, NSelect, useMessage } from 'naive-ui'
import type { NodeKind, StructureNode } from '../types'
import { nodeLabels } from '../types'
const props = defineProps<{ modelValue: StructureNode[]; text: string; disabled: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: StructureNode[]] }>()
const message = useMessage()
const page = ref(1)
const visible = computed(() => props.modelValue.slice((page.value - 1) * 20, page.value * 20))
const chars = computed(() => Array.from(props.text))
const open = ref(false)
const editing = ref<string | null>(null)
const form = reactive({
  kind: 'ARTICLE' as NodeKind,
  label: '',
  number: '',
  suffix: '0',
  parent_id: null as string | null,
  start: '0',
  end: '1',
})
const kinds = Object.entries(nodeLabels).map(([value, label]) => ({ value, label }))
const parents = computed(() =>
  props.modelValue
    .filter((node) => node.id !== editing.value)
    .map((node) => ({
      value: node.id,
      label: `${nodeLabels[node.kind]} · ${node.label || node.id} [${node.start}, ${node.end})`,
    })),
)
const preview = computed(() =>
  chars.value
    .slice(Number(form.start), Math.min(Number(form.end), Number(form.start) + 2000))
    .join(''),
)
function edit(node?: StructureNode): void {
  editing.value = node?.id ?? null
  Object.assign(form, {
    kind: node?.kind ?? 'ARTICLE',
    label: node?.label ?? '',
    number: node?.number?.toString() ?? '',
    suffix: String(node?.suffix ?? 0),
    parent_id: node?.parent_id ?? null,
    start: String(node?.start ?? 0),
    end: String(node?.end ?? 1),
  })
  open.value = true
}
function save(): void {
  const start = Number(form.start),
    end = Number(form.end),
    suffix = Number(form.suffix)
  const number = form.number.trim() ? Number(form.number) : null
  if (
    !/^\d+$/.test(form.start) ||
    !/^\d+$/.test(form.end) ||
    !Number.isSafeInteger(start) ||
    !Number.isSafeInteger(end) ||
    start < 0 ||
    end <= start ||
    end > chars.value.length
  ) {
    message.warning('请输入有效的原文起止位置')
    return
  }
  if (
    !Number.isSafeInteger(suffix) ||
    suffix < 0 ||
    suffix > 10000 ||
    (number !== null && (!Number.isSafeInteger(number) || number < 1 || number > 100000))
  ) {
    message.warning('请填写有效的条文编号与增补编号')
    return
  }
  if (form.label && !chars.value.slice(start, end).join('').startsWith(form.label)) {
    message.warning('节点标签需与起始位置的原文完全一致')
    return
  }
  const node: StructureNode = {
    id: editing.value ?? `manual-${crypto.randomUUID()}`,
    kind: form.kind,
    label: form.label,
    number,
    suffix,
    parent_id: form.parent_id,
    start,
    end,
  }
  const nodes = editing.value
    ? props.modelValue.map((value) => (value.id === editing.value ? node : value))
    : [...props.modelValue, node]
  emit(
    'update:modelValue',
    nodes.sort((left, right) => left.start - right.start || right.end - left.end),
  )
  open.value = false
}
function remove(node: StructureNode): void {
  if (props.modelValue.some((value) => value.parent_id === node.id)) {
    message.warning('请先调整此节点下级的归属')
    return
  }
  const remaining = props.modelValue.filter((value) => value.id !== node.id)
  page.value = Math.min(page.value, Math.max(1, Math.ceil(remaining.length / 20)))
  emit('update:modelValue', remaining)
}
</script>
<template>
  <section>
    <div class="kb-section-heading">
      <div>
        <h3>原文结构</h3>
        <p class="kb-muted">{{ modelValue.length }} 个节点 · 修改边界与归属，原文保持留存</p>
      </div>
      <NButton :disabled="disabled" @click="edit()">添加节点</NButton>
    </div>
    <div class="kb-table-wrap">
      <table class="kb-structure-table">
        <thead>
          <tr>
            <th>层级 / 标签</th>
            <th>原文区间</th>
            <th>归属</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="node in visible" :key="node.id">
            <td>
              <strong>{{ nodeLabels[node.kind] }}</strong> {{ node.label || '原文段落'
              }}<small>{{ node.id }}</small>
            </td>
            <td>[{{ node.start }}, {{ node.end }})</td>
            <td>
              {{
                modelValue.find((parent) => parent.id === node.parent_id)?.label ||
                node.parent_id ||
                '文档根节点'
              }}
            </td>
            <td>
              <NButton size="small" text :disabled="disabled" @click="edit(node)">调整</NButton
              ><NPopconfirm @positive-click="remove(node)"
                ><template #trigger
                  ><NButton size="small" text type="error" :disabled="disabled"
                    >移除标注</NButton
                  ></template
                >仅移除此结构标注，原文内容保留。</NPopconfirm
              >
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <NPagination
      v-if="modelValue.length > 20"
      v-model:page="page"
      :page-size="20"
      :item-count="modelValue.length"
    />
    <NModal
      v-model:show="open"
      preset="card"
      :title="editing ? '调整原文结构' : '添加原文标注'"
      class="kb-modal"
      ><div class="kb-form">
        <div class="kb-form-grid">
          <label>层级<NSelect v-model:value="form.kind" :options="kinds" /></label
          ><label>编号<NInput v-model:value="form.number" placeholder="如 12；款可留空" /></label
          ><label
            >增补编号（第十条之一）<NInput
              v-model:value="form.suffix"
              placeholder="无增补填 0" /></label
          ><label
            >原文标签<NInput
              v-model:value="form.label"
              placeholder="须与原文开头一致，可留空" /></label
          ><label>开始位置（含）<NInput v-model:value="form.start" /></label
          ><label>结束位置（不含）<NInput v-model:value="form.end" /></label>
        </div>
        <label
          >上级归属<NSelect
            v-model:value="form.parent_id"
            :options="parents"
            clearable
            filterable
            placeholder="文档根节点"
        /></label>
        <p class="kb-muted">
          位置按 Unicode 字符计数；全文共 {{ chars.length }} 字符。父节点区间应覆盖下级。
        </p>
        <pre class="kb-source-preview">{{ preview }}</pre>
        <NButton type="primary" @click="save">应用标注调整</NButton>
      </div></NModal
    >
  </section>
</template>
