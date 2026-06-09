/* =====================================================
 * 全局 Task Queue Store（任务队列）
 * - 统一管理图片与视频的异步生成任务
 * - 按任务独立轮询状态
 * - localStorage 持久化（刷新页面后继续轮询）
 * - 页面可见性感知（后台降低轮询频率）
 * - 并发上限：每种类型最多 5 个同时生成
 * - 历史任务：最多保留 5 个已完成任务，20 分钟后清理
 * ===================================================== */

import { defineStore } from 'pinia'
import {
  createVideoTask,
  getVideoStatus,
  cancelVideoTask,
} from '@/api/videos'
import {
  createImageTask,
  getImageTaskStatus,
  cancelImageTask,
} from '@/api/images'

// ---------- 常量 ----------
const STORAGE_KEY = 'agnes_task_queue_v1'
const IMAGE_POLL_INTERVAL = 3000      // 图片轮询间隔（毫秒）
const VIDEO_POLL_INTERVAL = 5000      // 视频轮询间隔（毫秒）
const POLL_TIMEOUT = 10 * 60 * 1000  // 轮询超时保护（10 分钟）
const HISTORY_KEEP_COUNT = 5          // 已完成任务保留数量
const HISTORY_KEEP_MS = 20 * 60 * 1000  // 已完成任务保留时长（20 分钟）
const MAX_CONCURRENT = 5              // 每种类型最大并发数
const PROGRESS_DURATION_ESTIMATE = 60000  // 预估进度填充基准（毫秒）

// ---------- 工具函数 ----------
function uid() {
  return 't_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8)
}

function isFinalStatus(status) {
  return ['success', 'failed', 'cancelled'].includes(status)
}

export const useTaskQueueStore = defineStore('taskQueue', {
  state: () => ({
    // 所有任务（按 taskId 索引）
    tasks: {},
    // 任务轮询定时器（taskId -> setInterval id）
    pollTimers: {},
    // 面板是否展开
    panelOpen: false,
    // 当前选中的任务 ID（用于在视图中显示某任务的详情）
    activeTaskId: null,
    // 时间戳标记（每秒递增，驱动耗时/时间显示的响应式刷新）
    _tick: 0,
    // 已初始化标志
    _initialized: false,
  }),

  getters: {
    // 所有任务列表（按创建时间倒序）
    taskList(state) {
      return Object.values(state.tasks).sort(
        (a, b) => b.createdAt - a.createdAt,
      )
    },
    // 进行中的任务数
    runningCount(state) {
      return Object.values(state.tasks).filter(
        (t) => !isFinalStatus(t.status),
      ).length
    },
    runningVideoCount(state) {
      return Object.values(state.tasks).filter(
        (t) => t.type === 'video' && !isFinalStatus(t.status),
      ).length
    },
    runningImageCount(state) {
      return Object.values(state.tasks).filter(
        (t) => t.type === 'image' && !isFinalStatus(t.status),
      ).length
    },
    videoTasks(state, getters) {
      return getters.taskList.filter((t) => t.type === 'video')
    },
    imageTasks(state, getters) {
      return getters.taskList.filter((t) => t.type === 'image')
    },
    getTaskById: (state) => (id) => state.tasks[id] || null,
    activeTask(state) {
      return state.activeTaskId ? state.tasks[state.activeTaskId] : null
    },
    // 根据任务 ID 计算已耗时（秒）— 通过 _tick 实现响应式刷新
    elapsedSec: (state) => (task) => {
      // 读取 _tick 让此 getter 与它建立响应式关联
      state._tick
      if (!task) return 0
      return Math.floor((Date.now() - task.createdAt) / 1000)
    },
  },

  actions: {
    // =====================================================
    // 【初始化】—— 在应用启动时调用一次
    // =====================================================
    init() {
      if (this._initialized) return
      this._initialized = true

      // 1. 从 localStorage 恢复
      this._restoreFromStorage()

      // 2. 注册页面可见性监听
      if (typeof document !== 'undefined') {
        document.addEventListener('visibilitychange', () => {
          this._handleVisibilityChange()
        })
      }

      // 3. 启动所有未完成任务的轮询（跳过聊天来源的任务，由 chat store 自己管理）
      for (const task of Object.values(this.tasks)) {
        if (!isFinalStatus(task.status) && task.source !== 'chat') {
          this._startPolling(task.taskId)
        }
      }

      // 4. 启动时清理一次历史
      this._cleanupOldHistory()

      // 5. 每分钟清理一次过期历史
      setInterval(() => this._cleanupOldHistory(), 60 * 1000)

      // 6. 每秒递增 tick，驱动耗时/时间显示的响应式刷新
      setInterval(() => { this._tick++ }, 1000)
    },

    // =====================================================
    // 【提交任务】
    // =====================================================

    // ------ 图片生成任务
    submitImageTask(params) {
      if (this.runningImageCount >= MAX_CONCURRENT) {
        throw new Error(
          `Maximum ${MAX_CONCURRENT} concurrent image tasks — please wait for some tasks to complete`,
        )
      }
      const taskId = uid()
      const task = {
        taskId,
        type: 'image',
        status: 'queued',
        prompt: params.prompt,
        params: { ...params },
        resultUrl: null,
        progress: 0,
        errorMessage: '',
        createdAt: Date.now(),
        updatedAt: Date.now(),
        pollIntervalMs: IMAGE_POLL_INTERVAL,
        rawResponse: null,
        backendTaskId: null,
      }
      this.tasks[taskId] = task
      // 自动选中为活跃任务（便于立即在预览区展示）
      this.setActiveTask(taskId)

      // 异步创建任务（不 await，立即返回 taskId）
      this._createImageTaskInBackground(taskId, params)
      return taskId
    },

    async _createImageTaskInBackground(taskId, params) {
      const task = this.tasks[taskId]
      if (!task) return
      try {
        task.status = 'pending'
        this._notifyTaskUpdate(taskId)
        const resp = await createImageTask(params)
        task.backendTaskId =
          resp.task_id || resp.id || resp.image_task_id || taskId
        task.rawResponse = resp
        task.status = 'processing'
        this._notifyTaskUpdate(taskId)
        this._startPolling(taskId)
      } catch (err) {
        task.status = 'failed'
        task.errorMessage = err.message || 'Failed to create task'
        task.updatedAt = Date.now()
        this._notifyTaskUpdate(taskId)
        this._saveToStorage()
      }
    },

    // ------ 视频生成任务
    submitVideoTask(params) {
      if (this.runningVideoCount >= MAX_CONCURRENT) {
        throw new Error(
          `Maximum ${MAX_CONCURRENT} concurrent video tasks — please wait for some tasks to complete`,
        )
      }
      const taskId = uid()
      const task = {
        taskId,
        type: 'video',
        status: 'queued',
        prompt: params.prompt,
        params: { ...params },
        resultUrl: null,
        posterUrl: null,
        progress: 0,
        errorMessage: '',
        createdAt: Date.now(),
        updatedAt: Date.now(),
        pollIntervalMs: VIDEO_POLL_INTERVAL,
        rawResponse: null,
        backendTaskId: null,
      }
      this.tasks[taskId] = task
      // 自动选中为活跃任务（便于立即在预览区展示）
      this.setActiveTask(taskId)

      this._createVideoTaskInBackground(taskId, params)
      return taskId
    },

    async _createVideoTaskInBackground(taskId, params) {
      const task = this.tasks[taskId]
      if (!task) return
      try {
        task.status = 'pending'
        this._notifyTaskUpdate(taskId)
        const resp = await createVideoTask(params)
        task.backendTaskId =
          resp.task_id || resp.video_id || resp.id || taskId
        task.rawResponse = resp
        task.status = 'processing'
        this._notifyTaskUpdate(taskId)
        this._startPolling(taskId)
      } catch (err) {
        task.status = 'failed'
        task.errorMessage = err.message || 'Failed to create task'
        task.updatedAt = Date.now()
        this._notifyTaskUpdate(taskId)
        this._saveToStorage()
      }
    },

    // =====================================================
    // 【轮询】
    // =====================================================
    _startPolling(taskId) {
      if (this.pollTimers[taskId]) return
      const task = this.tasks[taskId]
      if (!task) return
      const timerId = setInterval(() => {
        this._doPoll(taskId)
      }, task.pollIntervalMs)
      this.pollTimers[taskId] = timerId

      // 启动时立刻执行一次（提高响应速度）
      this._doPoll(taskId)
    },

    _stopPolling(taskId) {
      const timer = this.pollTimers[taskId]
      if (timer) {
        clearInterval(timer)
        delete this.pollTimers[taskId]
      }
    },

    async _doPoll(taskId) {
      const task = this.tasks[taskId]
      if (!task) return
      // 已结束 → 停止
      if (isFinalStatus(task.status)) {
        this._stopPolling(taskId)
        return
      }
      // 超时保护
      if (Date.now() - task.createdAt > POLL_TIMEOUT) {
        this._markAsFailed(taskId, 'Task timeout (exceeded 10 minutes)')
        return
      }
      const backendId = task.backendTaskId || taskId
      try {
        let data
        if (task.type === 'video') {
          data = await getVideoStatus(backendId)
        } else {
          data = await getImageTaskStatus(backendId)
        }
        task.rawResponse = data
        task.updatedAt = Date.now()

        // 解析状态
        const rawStatus = String(
          data.status || data.state || 'processing',
        ).toLowerCase()
        const isSuccess = ['success', 'completed', 'done', 'succeeded', 'finished'].includes(rawStatus)
        const isFailed = ['failed', 'error', 'timeout'].includes(rawStatus)
        const isCancelled = rawStatus === 'cancelled'

        if (isSuccess) {
          task.status = 'success'
          // 提取结果 URL —— 兼容多种字段名
          const url =
            data.video_url ||
            data.url ||
            data.result_url ||
            data.image_url ||
            (data.data && data.data.video_url) ||
            (data.data && data.data.url) ||
            (data.data && data.data.image_url) ||
            ''
          task.resultUrl = url
          task.progress = 100
          this._stopPolling(taskId)
          this._notifyTaskComplete(task)
          this._saveToStorage()
        } else if (isCancelled) {
          task.status = 'cancelled'
          this._stopPolling(taskId)
          this._saveToStorage()
        } else if (isFailed) {
          task.status = 'failed'
          task.errorMessage = data.message || data.error || 'Generation failed'
          this._stopPolling(taskId)
          this._saveToStorage()
        } else {
          task.status = 'processing'
          // 进度：优先取后端返回的 progress，否则按时间估算
          if (typeof data.progress === 'number') {
            task.progress = Math.min(data.progress, 99)
          } else if (data.progress != null && data.progress !== undefined) {
            const parsed = parseInt(String(data.progress), 10)
            task.progress = isNaN(parsed)
              ? this._estimateProgress(task)
              : Math.min(parsed, 99)
          } else {
            task.progress = this._estimateProgress(task)
          }
          this._saveToStorage()
        }
      } catch (err) {
        // 单次轮询失败，静默继续（不影响整体状态）
        console.warn('[TaskQueue] 轮询失败 taskId=', taskId, err.message)
      }
    },

    // 根据已耗时估算进度（后端不返回进度时的兜底方案）
    _estimateProgress(task) {
      const elapsed = Date.now() - task.createdAt
      const expected = task.type === 'video' ? 3 * PROGRESS_DURATION_ESTIMATE : PROGRESS_DURATION_ESTIMATE
      return Math.min(Math.floor((elapsed / expected) * 100), 85)
    },

    // =====================================================
    // 【取消任务】
    // =====================================================
    async cancelTask(taskId) {
      const task = this.tasks[taskId]
      if (!task) return
      this._stopPolling(taskId)
      task.status = 'cancelled'
      task.updatedAt = Date.now()
      // 尝试通知后端（失败不影响前端状态）
      try {
        if (task.type === 'video' && task.backendTaskId) {
          await cancelVideoTask(task.backendTaskId)
        } else if (task.type === 'image' && task.backendTaskId) {
          await cancelImageTask(task.backendTaskId)
        }
      } catch (_) {}
      this._saveToStorage()
    },

    // =====================================================
    // 【移除任务】（仅移除 UI 显示，不影响历史记录）
    // =====================================================
    removeTask(taskId) {
      this._stopPolling(taskId)
      if (this.activeTaskId === taskId) this.activeTaskId = null
      delete this.tasks[taskId]
      this._saveToStorage()
    },

    // =====================================================
    // 【用原参数重新提交】
    // =====================================================
    retryTask(taskId) {
      const task = this.tasks[taskId]
      if (!task) return null
      if (task.type === 'video') {
        return this.submitVideoTask({ ...task.params })
      } else {
        return this.submitImageTask({ ...task.params })
      }
    },

    // =====================================================
    // 【面板/选中】
    // =====================================================
    setActiveTask(taskId) {
      // 设置当前活跃任务（队列点击、提交任务后都会调用）
      this.activeTaskId = taskId
      // 持久化：刷新/切换页面后仍能记住选中的任务
      this._saveToStorage()
    },
    togglePanel() {
      this.panelOpen = !this.panelOpen
    },
    openPanel() {
      this.panelOpen = true
    },
    closePanel() {
      this.panelOpen = false
    },

    // =====================================================
    // 【内部工具】
    // =====================================================
    _markAsFailed(taskId, message) {
      const task = this.tasks[taskId]
      if (!task) return
      this._stopPolling(taskId)
      task.status = 'failed'
      task.errorMessage = message
      task.updatedAt = Date.now()
      this._saveToStorage()
    },

    _notifyTaskUpdate(taskId) {
      this._saveToStorage()
    },

    _notifyTaskComplete(task) {
      this._cleanupOldHistory()
    },

    _handleVisibilityChange() {
      if (typeof document === 'undefined') return
      const hidden = document.hidden
      for (const task of Object.values(this.tasks)) {
        if (isFinalStatus(task.status)) continue
        this._stopPolling(task.taskId)
        if (hidden) {
          // 页面隐藏时使用更长间隔
          task.pollIntervalMs = task.type === 'video' ? 15000 : 10000
        } else {
          task.pollIntervalMs = task.type === 'video' ? VIDEO_POLL_INTERVAL : IMAGE_POLL_INTERVAL
        }
        this._startPolling(task.taskId)
      }
    },

    _cleanupOldHistory() {
      const done = Object.values(this.tasks)
        .filter((t) => isFinalStatus(t.status))
        .sort((a, b) => b.updatedAt - a.updatedAt)
      if (done.length <= HISTORY_KEEP_COUNT) {
        this._saveToStorage()
        return
      }
      const now = Date.now()
      // 超出保留数量的最旧任务，若已超过 20 分钟则清除
      const toRemove = done.slice(HISTORY_KEEP_COUNT)
      for (const task of toRemove) {
        if (now - task.updatedAt > HISTORY_KEEP_MS) {
          delete this.tasks[task.taskId]
        }
      }
      this._saveToStorage()
    },

    // =====================================================
    // 【持久化】
    // =====================================================
    _saveToStorage() {
      if (typeof localStorage === 'undefined') return
      try {
        const tasksToSave = Object.values(this.tasks).map((t) => ({
          taskId: t.taskId,
          type: t.type,
          status: t.status,
          prompt: t.prompt,
          params: t.params,
          resultUrl: t.resultUrl,
          posterUrl: t.posterUrl,
          progress: t.progress,
          errorMessage: t.errorMessage,
          createdAt: t.createdAt,
          updatedAt: t.updatedAt,
          pollIntervalMs: t.pollIntervalMs,
          backendTaskId: t.backendTaskId,
          source: t.source || null,
        }))
        const data = {
          tasks: tasksToSave,
          // 持久化当前选中的任务 ID，刷新后可恢复选中状态
          activeTaskId: this.activeTaskId,
          savedAt: Date.now(),
        }
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
      } catch (_) {
        // localStorage 写入失败（如隐私模式），静默忽略
      }
    },

    _restoreFromStorage() {
      if (typeof localStorage === 'undefined') return
      try {
        const raw = localStorage.getItem(STORAGE_KEY)
        if (!raw) return
        const data = JSON.parse(raw)
        if (!data || !Array.isArray(data.tasks)) return
        const now = Date.now()
        for (const t of data.tasks) {
          // 超过 1 小时的任务丢弃
          if (now - (t.updatedAt || 0) > 60 * 60 * 1000) continue
          if (!isFinalStatus(t.status)) {
            // 进行中的任务重置为 processing，刷新后继续轮询
            t.status = 'processing'
          }
          this.tasks[t.taskId] = t
        }
        // 恢复 activeTaskId（如果该任务仍然存在）
        if (data.activeTaskId && this.tasks[data.activeTaskId]) {
          this.activeTaskId = data.activeTaskId
        }
      } catch (_) {
        // 解析失败不影响启动
      }
    },
  },
})
