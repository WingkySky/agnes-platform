<!-- =====================================================
     TaskQueuePanel 悬浮面板
     - 固定在右下角的悬浮按钮 + 展开面板
     - 显示当前任务队列（进行中/已完成/失败）
     - 每个任务用 TaskCard 组件展示
     - 支持 Tab 切换：全部 / 进行中 / 已完成
     - 由 App.vue 全局挂载，路由切换时不会销毁
     ===================================================== -->

<template>
  <div class="task-queue-panel" :class="{ 'is-open': queue.panelOpen }">
    <!-- 展开的面板内容 -->
    <transition name="panel-slide">
      <div v-show="queue.panelOpen" class="panel-content">
        <!-- 头部 -->
        <div class="panel-header">
          <div class="panel-title">
            <span class="title-icon">⚡</span>
            <span>生成队列</span>
            <span v-if="queue.runningCount > 0" class="running-badge">
              {{ queue.runningCount }} 个进行中
            </span>
          </div>
          <button class="close-btn" @click="queue.closePanel()" title="收起">
            ✕
          </button>
        </div>

        <!-- Tab 切换 -->
        <div class="panel-tabs">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            class="tab-btn"
            :class="{ active: activeTab === tab.key }"
            @click="activeTab = tab.key"
          >
            {{ tab.label }}
            <span v-if="getTabCount(tab.key) > 0" class="tab-count">
              {{ getTabCount(tab.key) }}
            </span>
          </button>
        </div>

        <!-- 任务列表 -->
        <div class="panel-list" ref="listRef">
          <template v-if="filteredTasks.length === 0">
            <div class="empty-state">
              <div class="empty-icon">✨</div>
              <div class="empty-text">暂无{{ activeTabLabel }}任务</div>
            </div>
          </template>
          <template v-else>
            <TaskCard
              v-for="task in filteredTasks"
              :key="task.taskId"
              :task="task"
              :is-active="queue.activeTaskId === task.taskId"
              compact
              @select="handleSelectTask(task.taskId)"
            />
          </template>
        </div>

        <!-- 底部提示 -->
        <div class="panel-footer">
          <span>任务状态实时更新 · 切换页面不丢失</span>
        </div>
      </div>
    </transition>

    <!-- 悬浮按钮（收起状态显示） -->
    <button
      class="floating-btn"
      :class="{ 'has-running': queue.runningCount > 0 }"
      @click="queue.togglePanel()"
      :title="queue.panelOpen ? '收起队列' : '查看生成队列'"
    >
      <span class="btn-icon">⚡</span>
      <span v-if="!queue.panelOpen" class="btn-text">
        队列
      </span>
      <span v-if="queue.runningCount > 0 && !queue.panelOpen" class="btn-badge">
        {{ queue.runningCount }}
      </span>
    </button>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import TaskCard from './TaskCard.vue'
import { useTaskQueueStore } from '@/stores/taskQueue'

const queue = useTaskQueueStore()
const activeTab = ref('all')

const tabs = [
  { key: 'all', label: '全部' },
  { key: 'running', label: '进行中' },
  { key: 'done', label: '已完成' },
]

const activeTabLabel = computed(() => {
  const t = tabs.find(tab => tab.key === activeTab.value)
  return t ? t.label : ''
})

const filteredTasks = computed(() => {
  const tasks = queue.taskList
  switch (activeTab.value) {
    case 'running':
      return tasks.filter(t => ['queued', 'pending', 'processing'].includes(t.status))
    case 'done':
      return tasks.filter(t => ['success', 'failed', 'cancelled'].includes(t.status))
    default:
      return tasks
  }
})

function getTabCount(key) {
  switch (key) {
    case 'running': return queue.runningCount
    case 'done':
      return queue.taskList.filter(
        t => ['success', 'failed', 'cancelled'].includes(t.status)
      ).length
    default: return queue.taskList.length
  }
}

function handleSelectTask(taskId) {
  queue.setActiveTask(taskId)
}

onMounted(() => {
  // 页面加载时初始化（持久化恢复等）
})
</script>

<style scoped>
.task-queue-panel {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 12px;
}

/* 悬浮按钮 */
.floating-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 18px;
  background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
  color: white;
  border: none;
  border-radius: 50px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 6px 24px rgba(59, 130, 246, 0.4), 0 2px 8px rgba(0, 0, 0, 0.3);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
}

.floating-btn:hover {
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 8px 32px rgba(59, 130, 246, 0.5), 0 4px 12px rgba(0, 0, 0, 0.4);
}

.floating-btn:active {
  transform: translateY(0) scale(0.98);
}

.floating-btn.has-running {
  animation: glow-pulse 2s ease-in-out infinite;
}

@keyframes glow-pulse {
  0%, 100% { box-shadow: 0 6px 24px rgba(59, 130, 246, 0.4); }
  50% { box-shadow: 0 6px 32px rgba(139, 92, 246, 0.6); }
}

.btn-icon {
  font-size: 18px;
}

.btn-badge {
  position: absolute;
  top: -6px;
  right: -6px;
  min-width: 22px;
  height: 22px;
  padding: 0 6px;
  background: #ef4444;
  color: white;
  border-radius: 11px;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 8px rgba(239, 68, 68, 0.4);
}

/* 展开面板 */
.panel-content {
  width: 380px;
  max-height: 500px;
  background: rgba(15, 23, 42, 0.95);
  border: 1px solid rgba(120, 170, 255, 0.2);
  border-radius: 16px;
  overflow: hidden;
  backdrop-filter: blur(16px);
  box-shadow: 0 12px 48px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(120, 170, 255, 0.1);
  display: flex;
  flex-direction: column;
}

.panel-slide-enter-active,
.panel-slide-leave-active {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.panel-slide-enter-from,
.panel-slide-leave-to {
  opacity: 0;
  transform: translateY(20px) scale(0.95);
}

/* 面板头部 */
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-bottom: 1px solid rgba(120, 170, 255, 0.15);
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #e2e8f0;
}

.title-icon {
  font-size: 18px;
}

.running-badge {
  font-size: 11px;
  padding: 2px 8px;
  background: rgba(96, 165, 250, 0.2);
  color: #93c5fd;
  border-radius: 10px;
  font-weight: 500;
}

.close-btn {
  background: transparent;
  border: none;
  color: #8ba3c9;
  font-size: 14px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  transition: all 0.2s ease;
}

.close-btn:hover {
  background: rgba(248, 113, 113, 0.15);
  color: #f87171;
}

/* Tab 切换 */
.panel-tabs {
  display: flex;
  gap: 4px;
  padding: 8px 12px;
  background: rgba(15, 23, 42, 0.6);
  border-bottom: 1px solid rgba(120, 170, 255, 0.1);
}

.tab-btn {
  flex: 1;
  padding: 8px 12px;
  background: transparent;
  border: none;
  color: #8ba3c9;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  transition: all 0.2s ease;
}

.tab-btn:hover {
  background: rgba(120, 170, 255, 0.08);
  color: #d5e3f7;
}

.tab-btn.active {
  background: rgba(59, 130, 246, 0.2);
  color: #93c5fd;
}

.tab-count {
  font-size: 11px;
  padding: 1px 6px;
  background: rgba(120, 170, 255, 0.15);
  border-radius: 10px;
  min-width: 18px;
  text-align: center;
}

/* 任务列表 */
.panel-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 120px;
  max-height: 320px;
}

.panel-list::-webkit-scrollbar {
  width: 6px;
}

.panel-list::-webkit-scrollbar-track {
  background: transparent;
}

.panel-list::-webkit-scrollbar-thumb {
  background: rgba(120, 170, 255, 0.2);
  border-radius: 3px;
}

.panel-list::-webkit-scrollbar-thumb:hover {
  background: rgba(120, 170, 255, 0.3);
}

/* 空状态 */
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  color: #6b84aa;
}

.empty-icon {
  font-size: 32px;
  opacity: 0.6;
  margin-bottom: 8px;
}

.empty-text {
  font-size: 13px;
}

/* 底部 */
.panel-footer {
  padding: 10px 18px;
  text-align: center;
  font-size: 11px;
  color: #6b84aa;
  border-top: 1px solid rgba(120, 170, 255, 0.1);
  background: rgba(10, 15, 30, 0.5);
}

/* 响应式：小屏幕时缩小面板 */
@media (max-width: 600px) {
  .task-queue-panel {
    bottom: 16px;
    right: 16px;
  }
  .panel-content {
    width: calc(100vw - 32px);
    max-width: 380px;
  }
}
</style>
