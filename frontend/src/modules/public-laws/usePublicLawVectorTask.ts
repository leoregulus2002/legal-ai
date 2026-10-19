import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useErrorMessage } from '../../composables/useErrorMessage'
import { publicLawApi } from './api'
import type { VectorTask } from './types'

export function usePublicLawVectorTask(onChanged: () => void) {
  const task = ref<VectorTask | null>(null)
  const stopping = ref(false)
  const loading = ref(true)
  const message = useMessage()
  const showError = useErrorMessage()
  const active = computed(() =>
    Boolean(task.value && ['RUNNING', 'STOPPING'].includes(task.value.status)),
  )
  let alive = true
  let refreshing = false
  let failures = 0
  let sequence = 0
  let timer: ReturnType<typeof setTimeout> | undefined

  function accept(value: VectorTask): void {
    sequence++
    clearTimeout(timer)
    const previous = task.value
    task.value = value
    failures = 0
    // 单条失败保留在处理记录中；自动提示只通知任务状态变化，避免轮询持续弹错。
    if (previous?.id === value.id && previous.status !== value.status) {
      if (value.status === 'STOPPED') message.info('任务已停止，已完成的向量已保留')
      if (value.status === 'COMPLETED') {
        if (value.failed) message.warning('法规处理结束，部分法规未完成，可在处理记录中查看原因')
        else message.success('法规处理结束')
      }
      if (value.status === 'FAILED') message.error('任务已中断，请在处理记录中查看原因后重试')
      onChanged()
    } else if (previous?.completed !== value.completed) onChanged()
    if (active.value)
      timer = setTimeout(() => {
        void refresh()
      }, 2000)
  }

  async function refresh(): Promise<void> {
    if (refreshing) return
    refreshing = true
    const request = ++sequence
    clearTimeout(timer)
    try {
      const value = await publicLawApi.latestTask()
      if (!alive || request !== sequence) return
      if (value) accept(value)
      else task.value = null
    } catch (error: unknown) {
      if (!alive || request !== sequence) return
      if (failures === 0) showError(error)
      failures++
      if (failures < 3)
        timer = setTimeout(() => {
          void refresh()
        }, 5000)
    } finally {
      refreshing = false
      if (alive) loading.value = false
    }
  }

  async function stop(): Promise<void> {
    if (!task.value || stopping.value || task.value.status !== 'RUNNING') return
    clearTimeout(timer)
    const request = ++sequence
    stopping.value = true
    try {
      const value = await publicLawApi.stopTask(task.value.id)
      if (alive && request === sequence) accept(value)
    } catch (error: unknown) {
      if (alive) showError(error)
    } finally {
      if (alive) {
        stopping.value = false
        if (active.value) {
          clearTimeout(timer)
          timer = setTimeout(() => {
            void refresh()
          }, 2000)
        }
      }
    }
  }

  onMounted(() => {
    void refresh()
  })
  onUnmounted(() => {
    alive = false
    clearTimeout(timer)
  })
  return { task, active, stopping, loading, refresh, stop, accept }
}
