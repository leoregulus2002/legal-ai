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
