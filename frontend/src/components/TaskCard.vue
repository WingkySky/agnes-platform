<!-- =====================================================
     TaskCard 组件
     - 展示单个任务的状态（排队中/生成中/成功/失败/已取消）
     - 展示进度条、提示词、耗时、错误信息
     - 支持操作：取消/重试/移除/查看详情
     - 通过 `task` prop 接收任务对象（由 taskQueue store 提供）
     ===================================================== -->

<template>
  <div
    class="task-card"
    :class="[
      `status-${task.status}`,
      { 'is-active': isActive, 'is-compact': compact }
    ]"
    @click="$emit('select', task.taskId)"
  >
    <!-- 左侧图标 -->
    <div class="task-icon" :class="task.type">
      <span v-if="task.type === 'video'">🎬</span>
      <span v-else>🖼️</span>
    </div>

    <!-- 中间内容区 -->
    <div class="task-body">
      <div class="task-header">
        <span class="task-status-badge" :class="task.status">
          {{ statusLabel }}
        </span>
        <span class="task-type-label">
          {{ task.type === 'video' ? '视频' : '图片' }}
        </span>
        <span class="task-time">{{ formatTime(task.createdAt) }}</span>
      </div>

      <!-- 提示词 -->
      <div class="task-prompt">{{ truncate(task.prompt, 80) }}</div>

      <!-- 进度条（仅进行中任务） -->
      <div v-if="isRunning" class="task-progress">
        <div class="progress-track">
          <div
            class="progress-fill"
            :style="{ width: task.progress + '%' }"
          ></div>
        </div>
        <span class="progress-text">{{ task.progress }}% · {{ elapsedSec }}s</span>
      </div>

      <!-- 成功状态：展示结果缩略图 -->
      <div v-else-if="task.status === 'success' && task.resultUrl" class="task-success">
        <span class="success-icon">✓</span>
        <span class="success-text">生成完成 · {{ formatTime(task.updatedAt) }}</span>
      </div>

      <!-- 失败状态：展示错误信息 -->
      <div v-else-if="task.status === 'failed'" class="task-failed">
        <span class="failed-icon">✗</span>
        <span class="failed-text">{{ task.errorMessage || '生成失败' }}</span>
      </div>

      <!-- 已取消 -->
      <div v-else-if="task.status === 'cancelled'" class="task-cancelled">
        <span class="cancelled-icon">⊘</span>
        <span class="cancelled-text">任务已取消</span>
      </div>

      <!-- 排队中 -->
      <div v-else-if="task.status === 'queued'" class="task-queued">
        <span class="queued-text">等待创建任务...</span>
      </div>
    </div>

    <!-- 右侧操作区 -->
    <div class="task-actions" @click.stop>
      <button
        v-if="isRunning"
        class="action-btn cancel-btn"
        title="取消任务"
        @click="handleCancel"
      >
        取消
      </button>
      <button
        v-if="task.status === 'failed' || task.status === 'cancelled'"
        class="action-btn retry-btn"
        title="重试"
        @click="handleRetry"
      >
        重试
      </button>
      <button
        class="action-btn remove-btn"
        title="从队列移除"
        @click="handleRemove"
      >
        移除
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useTaskQueueStore } from '@/stores/taskQueue'

const props = defineProps({
  task: {
    type: Object,
    required: true,
  },
  isActive: {
    type: Boolean,
    default: false,
  },
  compact: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['select'])

const queue = useTaskQueueStore()

const isRunning = computed(() => {
  return ['queued', 'pending', 'processing'].includes(props.task.status)
})

const statusLabel = computed(() => {
  switch (props.task.status) {
    case 'queued': return '排队中'
    case 'pending': return '创建中'
    case 'processing': return '生成中'
    case 'success': return '完成'
    case 'failed': return '失败'
    case 'cancelled': return '已取消'
    default: return props.task.status
  }
})

const elapsedSec = computed(() => {
  return Math.floor((Date.now() - props.task.createdAt) / 1000)
})

function truncate(text, max) {
  if (!text) return ''
  return text.length > max ? text.slice(0, max) + '...' : text
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

async function handleCancel() {
  await queue.cancelTask(props.task.taskId)
}

function handleRetry() {
  queue.retryTask(props.task.taskId)
}

function handleRemove() {
  queue.removeTask(props.task.taskId)
}
</script>

<style scoped>
.task-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 12px;
  background: rgba(20, 30, 50, 0.6);
  border: 1px solid rgba(120, 170, 255, 0.15);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
}

.task-card:hover {
  background: rgba(30, 45, 70, 0.8);
  border-color: rgba(120, 170, 255, 0.3);
}

.task-card.is-active {
  background: rgba(50, 80, 130, 0.4);
  border-color: rgba(120, 180, 255, 0.5);
}

.task-card.status-success {
  border-left: 3px solid #4ade80;
}
.task-card.status-failed {
  border-left: 3px solid #f87171;
}
.task-card.status-cancelled {
  border-left: 3px solid #a1a1aa;
}
.task-card.status-processing,
.task-card.status-pending,
.task-card.status-queued {
  border-left: 3px solid #60a5fa;
}

.task-icon {
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  font-size: 18px;
}
.task-icon.video { background: rgba(96, 165, 250, 0.15); }
.task-icon.image { background: rgba(244, 114, 182, 0.15); }

.task-body {
  flex: 1;
  min-width: 0;
}

.task-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.task-status-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 10px;
}
.task-status-badge.queued,
.task-status-badge.pending,
.task-status-badge.processing {
  background: rgba(96, 165, 250, 0.2);
  color: #93c5fd;
}
.task-status-badge.success {
  background: rgba(74, 222, 128, 0.2);
  color: #86efac;
}
.task-status-badge.failed {
  background: rgba(248, 113, 113, 0.2);
  color: #fca5a5;
}
.task-status-badge.cancelled {
  background: rgba(161, 161, 170, 0.2);
  color: #d4d4d8;
}

.task-type-label {
  font-size: 11px;
  color: #8ba3c9;
}
.task-time {
  font-size: 11px;
  color: #6b84aa;
  margin-left: auto;
}

.task-prompt {
  font-size: 13px;
  color: #d5e3f7;
  line-height: 1.5;
  margin: 2px 0 6px;
  word-break: break-word;
}

.task-progress {
  display: flex;
  align-items: center;
  gap: 10px;
}
.progress-track {
  flex: 1;
  height: 4px;
  background: rgba(107, 132, 170, 0.2);
  border-radius: 2px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #60a5fa, #a78bfa);
  border-radius: 2px;
  transition: width 0.3s ease;
  animation: pulse-shimmer 2s ease-in-out infinite;
}
@keyframes pulse-shimmer {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}
.progress-text {
  font-size: 11px;
  color: #93c5fd;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
  min-width: 60px;
  text-align: right;
}

.task-success,
.task-failed,
.task-cancelled,
.task-queued {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  margin-top: 4px;
}
.task-success { color: #86efac; }
.task-failed { color: #fca5a5; }
.task-cancelled { color: #d4d4d8; }
.task-queued { color: #93c5fd; }

.task-actions {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex-shrink: 0;
}
.action-btn {
  background: transparent;
  border: 1px solid rgba(120, 170, 255, 0.2);
  color: #8ba3c9;
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.action-btn:hover {
  background: rgba(120, 170, 255, 0.1);
  color: #d5e3f7;
}
.cancel-btn:hover {
  background: rgba(248, 113, 113, 0.15);
  border-color: rgba(248, 113, 113, 0.4);
  color: #fca5a5;
}
.retry-btn:hover {
  background: rgba(74, 222, 128, 0.15);
  border-color: rgba(74, 222, 128, 0.4);
  color: #86efac;
}

/* 紧凑模式（用于队列面板） */
.task-card.is-compact {
  padding: 8px 10px;
}
.task-card.is-compact .task-icon {
  width: 32px;
  height: 32px;
  font-size: 16px;
}
.task-card.is-compact .task-prompt {
  font-size: 12px;
}
</style>
