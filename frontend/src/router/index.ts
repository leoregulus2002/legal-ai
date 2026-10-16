import { createRouter, createWebHistory } from 'vue-router'
import AppLayout from '../layouts/AppLayout.vue'

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'home',
          component: () => import('../modules/workspace/pages/HomePage.vue'),
          meta: { title: '工作台' },
        },
        {
          path: 'consultation',
          name: 'consultation',
          component: () => import('../modules/consultation/pages/ConsultationPage.vue'),
          meta: { title: 'AI 法律对话' },
        },
        {
          path: 'public-laws',
          name: 'public-laws',
          component: () => import('../modules/public-laws/pages/PublicLawLibraryPage.vue'),
          meta: { title: '公开法律库' },
        },
        {
          path: 'regulations',
          name: 'regulations',
          component: () => import('../modules/regulations/pages/RegulationSearchPage.vue'),
          meta: { title: '法律法规检索' },
        },
        {
          path: 'regulations/:documentId',
          name: 'regulation-detail',
          component: () => import('../modules/regulations/pages/RegulationDetailPage.vue'),
          meta: { title: '法规原文' },
        },
        {
          path: 'knowledge',
          name: 'knowledge',
          component: () => import('../modules/knowledge/pages/KnowledgePage.vue'),
          meta: { title: '法律知识库' },
        },
        {
          path: 'knowledge/:baseId',
          name: 'knowledge-base',
          component: () => import('../modules/knowledge/pages/KnowledgeBasePage.vue'),
          meta: { title: '文档管理' },
        },
        {
          path: 'knowledge/:baseId/documents/:documentId',
          name: 'knowledge-document',
          component: () => import('../modules/knowledge/pages/DocumentPage.vue'),
          meta: { title: '文档解析与审核' },
        },
        {
          path: 'settings/models',
          name: 'model-config',
          component: () => import('../modules/system-config/pages/ModelsPage.vue'),
          meta: { title: '模型配置' },
        },
        {
          path: 'settings/prompts',
          name: 'prompt-config',
          component: () => import('../modules/system-config/pages/PromptsPage.vue'),
          meta: { title: '系统提示词' },
        },
        {
          path: 'settings/consultation',
          name: 'consultation-config',
          component: () => import('../modules/system-config/pages/ConsultationConfigPage.vue'),
          meta: { title: '法律咨询模型' },
        },
        {
          path: ':pathMatch(.*)*',
          name: 'not-found',
          component: () => import('../pages/NotFoundPage.vue'),
          meta: { title: '页面未找到' },
        },
      ],
    },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  document.title = `${String(to.meta.title ?? '工作台')} · legal-ai`
})
