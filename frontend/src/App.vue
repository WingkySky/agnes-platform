<!-- =====================================================
     Agnes AI Platform 根组件
     - 提供主布局（左侧导航 + 右侧内容）
     - 通过路由切换图片 / 视频 / 历史三个页面
     ===================================================== -->

<template>
  <div class="app-root">
    <!-- 顶部栏 -->
    <header class="app-header">
      <div class="app-brand">
        <span class="brand-icon">✨</span>
        <div class="brand-text">
          <h1>Agnes AI Platform</h1>
          <p class="brand-sub">图片 & 视频生成平台</p>
        </div>
      </div>

      <nav class="app-nav">
        <router-link to="/images" class="nav-item" active-class="active">
          <el-icon><Picture /></el-icon>
          <span>图片生成</span>
        </router-link>
        <router-link to="/videos" class="nav-item" active-class="active">
          <el-icon><VideoPlay /></el-icon>
          <span>视频生成</span>
        </router-link>
        <router-link to="/history" class="nav-item" active-class="active">
          <el-icon><Clock /></el-icon>
          <span>生成历史</span>
        </router-link>
      </nav>

      <div class="app-version">
        v1.0 · Vue 3 + FastAPI
      </div>
    </header>

    <!-- 主内容区 -->
    <main class="app-main">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>

    <!-- 全局任务队列悬浮面板（路由切换时不销毁） -->
    <TaskQueuePanel />

    <!-- 页脚 -->
    <footer class="app-footer">
      <span>© Agnes AI Platform · 基于 Vue 3 + FastAPI 构建</span>
    </footer>
  </div>
</template>

<script setup>
import { Picture, VideoPlay, Clock } from '@element-plus/icons-vue'
import TaskQueuePanel from './components/TaskQueuePanel.vue'
</script>

<style scoped>
/* =====================================================
 * 全局布局样式（沿用原项目深色主题设计风格）
 * ===================================================== */
.app-root {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: linear-gradient(135deg, #0b0f1a 0%, #101827 50%, #0b0f1a 100%);
  color: #e8eef7;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Microsoft YaHei", sans-serif;
}

/* ---- 顶部栏 ---- */
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 32px;
  background: rgba(15, 22, 38, 0.75);
  border-bottom: 1px solid rgba(100, 150, 220, 0.18);
  backdrop-filter: blur(12px);
  position: sticky;
  top: 0;
  z-index: 100;
}

.app-brand {
  display: flex;
  align-items: center;
  gap: 14px;
}

.brand-icon {
  font-size: 36px;
  filter: drop-shadow(0 0 12px rgba(120, 180, 255, 0.45));
}

.brand-text h1 {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  background: linear-gradient(90deg, #a0d4ff 0%, #c9b3ff 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: 0.5px;
}

.brand-sub {
  margin: 4px 0 0;
  font-size: 12px;
  color: #8ba3c9;
}

/* ---- 导航 ---- */
.app-nav {
  display: flex;
  gap: 8px;
  background: rgba(20, 30, 50, 0.55);
  padding: 6px;
  border-radius: 12px;
  border: 1px solid rgba(100, 150, 220, 0.12);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  color: #a0b4d6;
  text-decoration: none;
  border-radius: 8px;
  font-size: 14px;
  transition: all 0.2s ease;
}

.nav-item:hover {
  color: #fff;
  background: rgba(120, 170, 255, 0.08);
}

.nav-item.active {
  color: #fff;
  background: linear-gradient(135deg, rgba(80, 140, 255, 0.3) 0%, rgba(160, 120, 255, 0.3) 100%);
  box-shadow: 0 0 20px rgba(100, 150, 255, 0.18);
}

.app-version {
  font-size: 12px;
  color: #6b84aa;
}

/* ---- 主内容 ---- */
.app-main {
  flex: 1;
  padding: 28px 32px;
  max-width: 1600px;
  width: 100%;
  margin: 0 auto;
  box-sizing: border-box;
}

/* ---- 页脚 ---- */
.app-footer {
  padding: 20px 32px;
  text-align: center;
  font-size: 12px;
  color: #6b84aa;
  border-top: 1px solid rgba(100, 150, 220, 0.1);
}

/* ---- 过渡动画 ---- */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* ---- 响应式 ---- */
@media (max-width: 900px) {
  .app-header {
    flex-direction: column;
    gap: 16px;
    padding: 16px;
  }
  .app-main {
    padding: 16px;
  }
}
</style>
