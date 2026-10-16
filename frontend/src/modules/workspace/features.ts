import type { IconName } from '../../components/AppIcon.vue'

export interface WorkspaceFeature {
  id: string
  title: string
  description: string
  icon: IconName
  to?: string
}

export const workspaceFeatures: readonly WorkspaceFeature[] = [
  {
    id: 'chat',
    title: 'AI 法律咨询',
    description: '多轮对话，辅助理解法律问题。',
    icon: 'chat',
    to: '/consultation',
  },
  {
    id: 'search',
    title: '法律法规检索',
    description: '查找法条、核对版本与原文引用。',
    icon: 'search',
    to: '/regulations',
  },
  {
    id: 'knowledge',
    title: '法律知识库',
    description: '管理资料、法律版本与解析审核。',
    icon: 'book',
    to: '/knowledge',
  },
  {
    id: 'documents',
    title: '法律文书分析',
    description: '合同审阅与法律文书处理。',
    icon: 'document',
  },
]
