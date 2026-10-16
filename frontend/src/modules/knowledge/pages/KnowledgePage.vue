<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import {
  NButton,
  NEmpty,
  NInput,
  NModal,
  NPagination,
  NPopconfirm,
  NSpin,
  useMessage,
} from 'naive-ui'
import { RouterLink } from 'vue-router'
import AppIcon from '../../../components/AppIcon.vue'
import { useErrorMessage } from '../../../composables/useErrorMessage'
import { knowledgeApi } from '../api'
import type { KnowledgeBase } from '../types'
import '../styles.css'
const items = ref<KnowledgeBase[]>([])
const total = ref(0)
const page = ref(1)
const query = ref('')
const loading = ref(false)
const saving = ref(false)
const deleting = ref<string | null>(null)
const open = ref(false)
const editing = ref<string>()
const form = reactive({ name: '', description: '' })
const showError = useErrorMessage()
const message = useMessage()
async function load(): Promise<void> {
  loading.value = true
  try {
    const result = await knowledgeApi.bases(query.value, page.value)
    items.value = result.items
    total.value = result.total
  } catch (error: unknown) {
    showError(error)
  } finally {
    loading.value = false
  }
}
async function submitQuery(): Promise<void> {
  page.value = 1
  await load()
}
function edit(base?: KnowledgeBase): void {
  editing.value = base?.id
  form.name = base?.name ?? ''
  form.description = base?.description ?? ''
  open.value = true
}
async function save(): Promise<void> {
  if (!form.name.trim()) {
    message.warning('请填写知识库名称')
    return
  }
  saving.value = true
  try {
    await knowledgeApi.saveBase(
      { name: form.name.trim(), description: form.description },
      editing.value,
    )
    open.value = false
    await load()
    message.success('知识库已保存')
  } catch (error: unknown) {
    showError(error)
  } finally {
    saving.value = false
  }
}
async function remove(base: KnowledgeBase): Promise<void> {
  deleting.value = base.id
  try {
    await knowledgeApi.deleteBase(base.id)
    if (items.value.length === 1 && page.value > 1) page.value--
    await load()
    message.success('知识库已删除，正式索引已移除')
  } catch (error: unknown) {
    showError(error)
  } finally {
    deleting.value = null
  }
}
onMounted(load)
</script>
<template>
  <section class="kb-page">
    <header class="kb-heading">
      <div>
        <span class="kb-eyebrow">KNOWLEDGE LIBRARY</span>
        <h1>法律知识库</h1>
        <p>保留原件，核对条文，让每一份资料都有据可查。</p>
      </div>
      <NButton type="primary" @click="edit()"
        ><template #icon><AppIcon name="plus" /></template>创建知识库</NButton
      >
    </header>
    <form class="kb-toolbar" @submit.prevent="submitQuery">
      <NInput
        v-model:value="query"
        clearable
        placeholder="按知识库名称查找"
        :maxlength="200"
      /><NButton attr-type="submit" :loading="loading">查询</NButton
      ><span class="kb-muted">共 {{ total }} 个知识库</span>
    </form>
    <NSpin :show="loading"
      ><NEmpty
        v-if="!items.length && !loading"
        description="创建知识库，开始整理专业资料"
        class="kb-empty"
        ><template #extra><NButton @click="edit()">创建知识库</NButton></template></NEmpty
      >
      <div class="kb-base-grid">
        <article v-for="base in items" :key="base.id" class="kb-base-card">
          <div class="kb-card-top">
            <AppIcon name="book" :size="26" /><span class="kb-eyebrow">资料与法律版本</span>
          </div>
          <RouterLink :to="`/knowledge/${base.id}`"
            ><h2>{{ base.name }}</h2></RouterLink
          >
          <p>{{ base.description || '为专业资料建立清晰、可追溯的归档。' }}</p>
          <div class="kb-card-footer">
            <RouterLink :to="`/knowledge/${base.id}`" class="kb-link"
              >进入知识库 <AppIcon name="arrow-right" :size="16"
            /></RouterLink>
            <div>
              <NButton text size="small" @click="edit(base)">编辑</NButton
              ><NPopconfirm @positive-click="remove(base)"
                ><template #trigger
                  ><NButton text size="small" type="error" :loading="deleting === base.id"
                    >删除</NButton
                  ></template
                >删除“{{ base.name }}”及其正式搜索索引？原件和操作记录将保留。</NPopconfirm
              >
            </div>
          </div>
        </article>
      </div>
    </NSpin>
    <NPagination
      v-if="total > 12"
      v-model:page="page"
      :page-size="12"
      :item-count="total"
      @update:page="load"
    />
    <NModal
      v-model:show="open"
      preset="card"
      :title="editing ? '编辑知识库' : '创建知识库'"
      class="kb-modal"
      ><div class="kb-form">
        <label
          >知识库名称<NInput
            v-model:value="form.name"
            :maxlength="120"
            placeholder="例如：劳动与社会保障" /></label
        ><label
          >说明<NInput
            v-model:value="form.description"
            type="textarea"
            :maxlength="2000"
            :rows="4"
            placeholder="说明收录范围与使用目的" /></label
        ><NButton type="primary" :loading="saving" @click="save">保存知识库</NButton>
      </div></NModal
    >
  </section>
</template>
