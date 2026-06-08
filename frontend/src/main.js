/* =====================================================
 * Agnes AI Platform 前端入口
 * - 挂载 Vue 应用
 * - 初始化 Element Plus（中文语言 + 深色主题 CSS 变量）
 * - 初始化 Vue Router 与 Pinia
 * ===================================================== */

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import './assets/main.css'
import { useTaskQueueStore } from './stores/taskQueue'

// 创建 Vue 应用
const app = createApp(App)

// 全局注册所有 Element Plus 图标组件
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

// 注册插件
app.use(createPinia())
app.use(router)
app.use(ElementPlus, {
  locale: zhCn,
  // 全局 size 默认值
  size: 'default'
})

// 确保 body 使用深色主题类（Element Plus 会根据 class="dark" 应用深色变量）
document.documentElement.classList.add('dark')

app.mount('#app')

// 初始化全局任务队列 Store（恢复历史任务 + 启动后台轮询）
const taskQueue = useTaskQueueStore()
taskQueue.init()
