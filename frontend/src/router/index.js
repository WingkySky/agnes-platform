/* =====================================================
 * Vue Router 路由配置
 * 三个页面：图片生成 / 视频生成 / 生成历史
 * - 标题随 i18n 语言变化动态更新
 * ===================================================== */

import { createRouter, createWebHistory } from 'vue-router'
import { useI18n } from '@/i18n'

const routes = [
  {
    path: '/',
    redirect: '/chat'
  },
  {
    path: '/chat',
    name: 'chat',
    component: () => import('@/views/ChatView.vue'),
    meta: { titleKey: 'router.chat' }
  },
  {
    path: '/images',
    name: 'images',
    component: () => import('@/views/ImageView.vue'),
    meta: { titleKey: 'router.images' }
  },
  {
    path: '/videos',
    name: 'videos',
    component: () => import('@/views/VideoView.vue'),
    meta: { titleKey: 'router.videos' }
  },
  {
    path: '/history',
    name: 'history',
    component: () => import('@/views/HistoryView.vue'),
    meta: { titleKey: 'router.history' }
  },
  // 兜底路由
  {
    path: '/:pathMatch(.*)*',
    redirect: '/chat'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 动态设置页面标题（使用当前 i18n 语言的文案）
router.afterEach((to) => {
  const key = to.meta?.titleKey
  if (key) {
    const { t } = useI18n()
    const title = t(key)
    document.title = `${title} · Agnes AI Platform`
  }
})

export default router
