/* =====================================================
 * Chat Store（Pinia）— 聊天状态管理
 *
 * 功能：
 *   - 管理聊天会话列表和当前活跃会话
 *   - 管理消息列表（含流式增量更新）
 *   - 处理 SSE 流式响应事件
 *   - 管理媒体生成任务状态（轮询更新）
 *   - 媒体轮询完成后回写数据库（mediaCallback）
 *   - 与 taskQueue store 集成（聊天生成的媒体注册到队列）
 *   - localStorage 持久化（页面切换后恢复状态）
 * ===================================================== */

import { defineStore } from 'pinia'
import {
  createChatSession,
  getChatSessions,
  getChatSession,
  deleteChatSession,
  getChatMessages,
  sendMessageStream,
  getMediaStatus,
  mediaCallback,
} from '@/api/chat'
import { useTaskQueueStore } from '@/stores/taskQueue'

// 媒体轮询间隔
const MEDIA_POLL_INTERVAL = 3000
// 轮询最大连续失败次数（超过后停止轮询）
const MAX_POLL_FAIL_COUNT = 5
// localStorage 持久化 key
const STORAGE_KEY = 'agnes_chat_state_v1'

export const useChatStore = defineStore('chat', {
  state: () => ({
    // 会话列表
    sessions: [],
    sessionsTotal: 0,
    // 当前活跃会话 ID
    activeSessionId: null,
    // 当前会话的消息列表
    messages: [],
    // 是否正在加载消息
    loadingMessages: false,
    // 是否正在发送消息（等待 AI 回复）
    sending: false,
    // 当前流式回复的临时内容
    streamingContent: '',
    // 当前流式回复中的工具调用信息
    streamingToolCalls: [],
    // 媒体轮询定时器（taskId -> timerId）
    mediaPollTimers: {},
    // 媒体状态缓存（taskId -> status info）
    mediaStatusMap: {},
    // 媒体轮询连续失败计数（taskId -> count）
    mediaPollFailCounts: {},
    // 任务ID -> 消息ID 映射（关键：解决临时 ID / 真实 ID 异步冲突）
    // 消息刚创建时 msg.id 是 Date.now() 临时值；收到 assistant_message 事件后才变为真实 DB ID
    // 但媒体轮询回调需要真实 message_id，因此轮询完成时通过此映射查找当前正确的 message.id
    mediaTaskToMessageId: {},
    // AbortController（用于取消流式请求）
    _abortController: null,
  }),

  getters: {
    // 当前活跃会话
    activeSession(state) {
      return state.sessions.find(s => s.id === state.activeSessionId) || null
    },
    // 是否有活跃会话
    hasActiveSession(state) {
      return state.activeSessionId !== null
    },
  },

  actions: {
    // =====================================================
    // 【会话管理】
    // =====================================================

    /** 加载会话列表 */
    async loadSessions() {
      try {
        const data = await getChatSessions({ page: 1, page_size: 50 })
        this.sessions = data.items || []
        this.sessionsTotal = data.total || 0
      } catch (e) {
        console.error('[Chat] 加载会话列表失败:', e)
      }
    },

    /** 创建新会话 */
    async newSession(title) {
      try {
        const session = await createChatSession({ title })
        this.sessions.unshift(session)
        this.activeSessionId = session.id
        this.messages = []
        this._saveToStorage()
        return session
      } catch (e) {
        console.error('[Chat] 创建会话失败:', e)
        throw e
      }
    },

    /** 切换活跃会话 */
    async switchSession(sessionId) {
      // 取消当前流式请求
      this._abortStream()
      // 停止旧会话的所有媒体轮询，避免切换后继续调用旧 message.id（临时 ID）
      this.stopAllMediaPolls()
      // 清空临时 ID 映射
      this.mediaTaskToMessageId = {}

      this.activeSessionId = sessionId
      this.messages = []
      this.streamingContent = ''
      this.streamingToolCalls = []

      // 加载消息（从数据库恢复，包含 media_items）
      await this.loadMessages(sessionId)
      this._saveToStorage()
    },

    /** 删除会话 */
    async removeSession(sessionId) {
      try {
        await deleteChatSession(sessionId)
        this.sessions = this.sessions.filter(s => s.id !== sessionId)

        // 如果删除的是当前会话，切换到其他会话或清空
        if (this.activeSessionId === sessionId) {
          this.activeSessionId = null
          this.messages = []
          this.streamingContent = ''
          this.streamingToolCalls = []
        }
        this._saveToStorage()
      } catch (e) {
        console.error('[Chat] 删除会话失败:', e)
        throw e
      }
    },

    /** 加载会话消息（从数据库恢复，含 media_items） */
    async loadMessages(sessionId) {
      if (!sessionId) return
      this.loadingMessages = true
      try {
        const data = await getChatMessages(sessionId)
        this.messages = data.items || []

        // 检查是否有进行中的媒体任务，启动轮询
        for (const msg of this.messages) {
          if (msg.media_items && Array.isArray(msg.media_items)) {
            for (const item of msg.media_items) {
              if (item.task_id && (item.status === 'pending' || item.status === 'processing')) {
                this._startMediaPoll(item.task_id, msg.id)
              }
            }
          }
        }
      } catch (e) {
        console.error('[Chat] 加载消息失败:', e)
      } finally {
        this.loadingMessages = false
      }
    },

    // =====================================================
    // 【发送消息】
    // =====================================================

    /** 发送消息并处理流式响应 */
    async sendMessage(content) {
      if (!this.activeSessionId) {
        // 自动创建新会话
        const session = await this.newSession(content.slice(0, 30))
      }

      if (!content.trim()) return

      // 添加用户消息到列表（乐观更新）
      const userMsg = {
        id: Date.now(),
        session_id: this.activeSessionId,
        role: 'user',
        content: content,
        media_items: [],
        created_at: new Date().toISOString(),
      }
      this.messages.push(userMsg)

      // 准备流式接收
      this.sending = true
      this.streamingContent = ''
      this.streamingToolCalls = []

      // 创建 AbortController
      this._abortController = new AbortController()

      // 添加 AI 消息占位（流式更新）
      // 注意：id 先用 Date.now() 临时值，收到 assistant_message SSE 事件后更新为真实 DB ID
      const assistantMsg = {
        id: Date.now() + 1,
        session_id: this.activeSessionId,
        role: 'assistant',
        content: '',
        media_items: [],  // 使用 media_items 数组
        created_at: new Date().toISOString(),
        _streaming: true, // 标记正在流式更新
        _tempId: true,    // 标记 id 是临时值（媒体回写需等待真实 ID）
      }
      this.messages.push(assistantMsg)

      try {
        await sendMessageStream(
          this.activeSessionId,
          content,
          (event) => this._handleSSEEvent(event),
          this._abortController.signal,
        )
      } catch (e) {
        if (e.name === 'AbortError') {
          console.log('[Chat] 流式请求已取消')
        } else {
          console.error('[Chat] 发送消息失败:', e)
          // 更新 AI 消息为错误状态
          const lastMsg = this.messages[this.messages.length - 1]
          if (lastMsg && lastMsg.role === 'assistant') {
            lastMsg.content = `抱歉，发生了错误：${e.message}`
            lastMsg._streaming = false
          }
        }
      } finally {
        this.sending = false
        this._abortController = null
        this._saveToStorage()
      }
    },

    /** 处理 SSE 事件 */
    _handleSSEEvent(event) {
      switch (event.type) {
        case 'user_message':
          // 用户消息已保存到数据库（更新 ID）
          if (this.messages.length >= 2) {
            const userMsg = this.messages[this.messages.length - 2]
            if (userMsg.role === 'user') {
              userMsg.id = event.message.id
            }
          }
          break

        case 'text':
          // AI 文本增量
          this.streamingContent += event.content
          this._updateStreamingMessage()
          break

        case 'tool_call':
          // 工具调用开始
          this.streamingToolCalls.push({
            tool: event.tool,
            args: event.args,
            status: 'calling',
          })
          this._updateStreamingMessage()
          break

        case 'tool_result': {
          // 工具执行结果 — 添加到 media_items 数组
          const tc = this.streamingToolCalls.find(t => t.tool === event.tool)
          if (tc) {
            tc.status = 'done'
            tc.result = event.result
          }

          const lastMsg = this.messages[this.messages.length - 1]
          if (lastMsg && lastMsg.role === 'assistant' && event.result) {
            const result = event.result
            // 只添加有效的媒体项（有 media_type 且非 error）
            if (result.media_type && result.status !== 'error') {
              const mediaItem = {
                type: result.media_type,
                url: result.url || '',
                task_id: result.task_id || result.video_id || '',
                status: result.status || 'pending',
              }
              // 确保 media_items 是数组
              if (!lastMsg.media_items) {
                lastMsg.media_items = []
              }
              lastMsg.media_items.push(mediaItem)

              // 启动媒体轮询
              if (mediaItem.task_id && mediaItem.status === 'pending') {
                this._startMediaPoll(mediaItem.task_id, lastMsg.id)
              }

              // 注册到任务队列（让全局队列也能看到聊天生成的媒体）
              this._registerToTaskQueue(mediaItem, result)
            }
          }
          this._updateStreamingMessage()
          break
        }

        case 'assistant_message': {
          // AI 消息已保存到数据库（更新 ID 和完整信息）
          // 关键修复：更新 id 后移除 _tempId 标记，并同步更新 mediaTaskToMessageId 映射
          if (event.message) {
            const lastMsg = this.messages[this.messages.length - 1]
            if (lastMsg && lastMsg.role === 'assistant') {
              const previousId = lastMsg.id
              lastMsg.id = event.message.id
              lastMsg.content = event.message.content || this.streamingContent
              // 从数据库恢复 media_items（确保与后端一致）
              if (event.message.media_items && event.message.media_items.length) {
                lastMsg.media_items = event.message.media_items
              }
              lastMsg._streaming = false
              lastMsg._tempId = false  // 清除临时 ID 标记

              // 同步更新 mediaTaskToMessageId 映射（轮询完成后的回写需要真实 ID）
              if (lastMsg.media_items && Array.isArray(lastMsg.media_items)) {
                for (const item of lastMsg.media_items) {
                  if (item.task_id) {
                    this.mediaTaskToMessageId[item.task_id] = event.message.id
                  }
                }
              }

              // 对已完成（success / failed）但因临时 ID 未能回写的媒体项，
              // 现在消息 ID 已更新，立即重试回写数据库
              for (const item of lastMsg.media_items || []) {
                if (item.task_id && (item.status === 'success' || item.status === 'failed')) {
                  if (!this._pendingCallbackIds) this._pendingCallbackIds = new Set()
                  if (this._pendingCallbackIds.has(item.task_id)) continue
                  this._pendingCallbackIds.add(item.task_id)
                  // 延迟一点确保响应式更新完成
                  setTimeout(() => {
                    if (item.status === 'success' && item.url) {
                      this._mediaCallbackToDB(event.message.id, item.task_id, item.url, 'success')
                    } else if (item.status === 'failed') {
                      this._mediaCallbackToDB(event.message.id, item.task_id, '', 'failed')
                    }
                  }, 0)
                }
              }
            }
          }
          break
        }

        case 'error': {
          // 错误事件
          const errMsg = this.messages[this.messages.length - 1]
          if (errMsg && errMsg.role === 'assistant') {
            errMsg.content += `\n\n❌ 错误：${event.content}`
            errMsg._streaming = false
          }
          break
        }

        case 'done': {
          // 流结束
          const doneMsg = this.messages[this.messages.length - 1]
          if (doneMsg && doneMsg.role === 'assistant') {
            doneMsg._streaming = false
            if (!doneMsg.content) {
              doneMsg.content = this.streamingContent
            }
          }
          break
        }
      }
    },

    /** 更新流式消息内容 */
    _updateStreamingMessage() {
      const lastMsg = this.messages[this.messages.length - 1]
      if (lastMsg && lastMsg.role === 'assistant' && lastMsg._streaming) {
        lastMsg.content = this.streamingContent
      }
    },

    /** 取消流式请求 */
    _abortStream() {
      if (this._abortController) {
        this._abortController.abort()
        this._abortController = null
      }
      this.sending = false
      // 标记当前流式消息为完成
      const lastMsg = this.messages[this.messages.length - 1]
      if (lastMsg && lastMsg._streaming) {
        lastMsg._streaming = false
      }
    },

    // =====================================================
    // 【媒体轮询】— 轮询完成后回写数据库
    // =====================================================

    /** 启动媒体生成状态轮询 */
    _startMediaPoll(taskId, messageId) {
      if (this.mediaPollTimers[taskId]) return

      // 建立 taskId -> messageId 映射（初始值，收到 assistant_message 后会更新）
      this.mediaTaskToMessageId[taskId] = messageId

      // 重置失败计数
      this.mediaPollFailCounts[taskId] = 0

      const poll = async () => {
        try {
          const data = await getMediaStatus(taskId)
          // 轮询成功，重置失败计数
          this.mediaPollFailCounts[taskId] = 0
          this.mediaStatusMap[taskId] = data

          // 关键修复：总是从 this.messages 中动态查找消息（避免使用闭包捕获的临时 ID）
          const msg = this.messages.find(m => {
            if (!m.media_items) return false
            return m.media_items.some(item => item.task_id === taskId)
          })

          if (msg) {
            const item = msg.media_items.find(i => i.task_id === taskId)
            if (!item) return

            const rawStatus = String(data.status || '').toLowerCase()
            const isSuccess = ['success', 'completed', 'done', 'succeeded', 'finished'].includes(rawStatus)
            const isFailed = ['failed', 'error', 'timeout'].includes(rawStatus)
            const isUnknown = rawStatus === 'unknown'

            if (isSuccess) {
              item.status = 'success'
              item.url = data.result_url || data.video_url || data.url || data.image_url || ''
              this._stopMediaPoll(taskId)

              // 关键修复：只有当消息 ID 是真实数据库 ID（非临时 Date.now()）时才执行回写
              // msg._tempId === true 表示 assistant_message 事件尚未到达，暂不回写
              // （assistant_message 事件到达后会重新检查已完成项并回写）
              if (item.url && !msg._tempId) {
                this._mediaCallbackToDB(msg.id, taskId, item.url, 'success')
              }
              // 同步更新任务队列
              this._updateTaskQueueItem(taskId, 'success', item.url)
            } else if (isFailed) {
              item.status = 'failed'
              this._stopMediaPoll(taskId)
              // 失败状态同样需要真实 message_id 才能回写
              if (!msg._tempId) {
                this._mediaCallbackToDB(msg.id, taskId, '', 'failed')
              }
              // 同步更新任务队列
              this._updateTaskQueueItem(taskId, 'failed', '')
            } else if (isUnknown) {
              // 任务已过期或不存在，停止轮询
              console.warn('[Chat] 任务不存在或已过期，停止轮询: taskId=%s', taskId)
              this._stopMediaPoll(taskId)
              if (item.status !== 'success') {
                item.status = 'failed'
              }
            } else {
              item.status = 'processing'
            }
          }
        } catch (e) {
          // 累加失败计数
          this.mediaPollFailCounts[taskId] = (this.mediaPollFailCounts[taskId] || 0) + 1
          const failCount = this.mediaPollFailCounts[taskId]

          if (failCount >= MAX_POLL_FAIL_COUNT) {
            console.warn('[Chat] 媒体轮询连续失败 %d 次，停止轮询: taskId=%s', failCount, taskId)
            this._stopMediaPoll(taskId)
            // 将消息中的媒体项标记为失败
            const msg = this.messages.find(m => {
              if (!m.media_items) return false
              return m.media_items.some(item => item.task_id === taskId)
            })
            if (msg) {
              const item = msg.media_items.find(i => i.task_id === taskId)
              if (item && item.status !== 'success') {
                item.status = 'failed'
              }
            }
          } else {
            console.warn('[Chat] 媒体状态轮询失败 (%d/%d): taskId=%s, %s',
              failCount, MAX_POLL_FAIL_COUNT, taskId, e.message)
          }
        }
      }

      // 立即执行一次
      poll()
      // 定时轮询
      this.mediaPollTimers[taskId] = setInterval(poll, MEDIA_POLL_INTERVAL)
    },

    /** 停止媒体轮询 */
    _stopMediaPoll(taskId) {
      if (this.mediaPollTimers[taskId]) {
        clearInterval(this.mediaPollTimers[taskId])
        delete this.mediaPollTimers[taskId]
      }
    },

    /** 停止所有媒体轮询 */
    stopAllMediaPolls() {
      for (const taskId of Object.keys(this.mediaPollTimers)) {
        this._stopMediaPoll(taskId)
      }
    },

    /** 媒体回调 — 回写数据库（健壮处理：404/网络异常不再弹错，仅记录） */
    async _mediaCallbackToDB(messageId, taskId, mediaUrl, status) {
      if (!messageId || !taskId) return
      try {
        await mediaCallback({
          message_id: messageId,
          task_id: taskId,
          media_url: mediaUrl,
          status: status,
        })
        console.log('[Chat] 媒体回写成功: msg=%s, task=%s', messageId, taskId)
      } catch (e) {
        // 仅打印警告，不弹出错误
        // 404（消息不存在）通常是因为临时 ID 问题（已通过 _tempId 机制提前避免）
        // 但为了极端情况（如消息被删除）仍能优雅处理，这里只记录
        console.warn('[Chat] 媒体回写跳过: msg=%s, task=%s, reason=%s',
          messageId, taskId, e.message || 'unknown')
      }
    },

    // =====================================================
    // 【任务队列集成】— 聊天生成的媒体注册到全局队列
    // =====================================================

    /** 将聊天生成的媒体任务注册到 taskQueue store（仅注册显示，不启动 taskQueue 自己的轮询） */
    _registerToTaskQueue(mediaItem, toolResult) {
      try {
        const taskQueue = useTaskQueueStore()
        const taskId = mediaItem.task_id
        if (!taskId) return

        // 检查是否已注册（避免重复）
        if (taskQueue.getTaskById(taskId)) return

        // 创建一个任务记录到队列中（仅用于展示）
        // 不启动 taskQueue 自己的轮询，因为 taskQueue 用的是 /api/images/tasks/ 和 /api/videos/ 接口
        // 聊天创建的任务应该通过 chat store 自己的轮询来更新状态
        const taskType = mediaItem.type === 'video' ? 'video' : 'image'
        const task = {
          taskId: taskId,
          type: taskType,
          status: 'processing',
          prompt: toolResult.prompt || '',
          params: {},
          resultUrl: mediaItem.url || null,
          progress: 0,
          errorMessage: '',
          createdAt: Date.now(),
          updatedAt: Date.now(),
          pollIntervalMs: taskType === 'video' ? 5000 : 3000,
          rawResponse: null,
          backendTaskId: taskId,
          // 标记来源为聊天 — taskQueue 恢复时跳过此类任务的轮询
          source: 'chat',
        }
        taskQueue.tasks[taskId] = task
        // 注意：不调用 taskQueue._startPolling(taskId)，避免用错误的 API 轮询
        taskQueue._saveToStorage()
      } catch (e) {
        console.warn('[Chat] 注册任务到队列失败:', e.message)
      }
    },

    /** 同步更新任务队列中的任务状态 */
    _updateTaskQueueItem(taskId, status, resultUrl) {
      try {
        const taskQueue = useTaskQueueStore()
        const task = taskQueue.getTaskById(taskId)
        if (task) {
          task.status = status
          if (resultUrl) {
            task.resultUrl = resultUrl
          }
          task.updatedAt = Date.now()
          if (status === 'success') {
            task.progress = 100
          }
          taskQueue._saveToStorage()
        }
      } catch (e) {
        // 忽略
      }
    },

    // =====================================================
    // 【持久化】— 页面切换后恢复状态
    // =====================================================

    _saveToStorage() {
      if (typeof localStorage === 'undefined') return
      try {
        const data = {
          activeSessionId: this.activeSessionId,
          // 只保存必要的会话信息
          savedAt: Date.now(),
        }
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
      } catch (_) {
        // localStorage 写入失败，静默忽略
      }
    },

    _restoreFromStorage() {
      if (typeof localStorage === 'undefined') return
      try {
        const raw = localStorage.getItem(STORAGE_KEY)
        if (!raw) return
        const data = JSON.parse(raw)
        if (!data) return

        // 恢复活跃会话 ID（消息从数据库重新加载）
        if (data.activeSessionId) {
          this.activeSessionId = data.activeSessionId
        }
      } catch (_) {
        // 解析失败不影响启动
      }
    },

    /** 初始化 — 应用启动时调用 */
    async init() {
      // 从 localStorage 恢复
      this._restoreFromStorage()

      // 加载会话列表
      await this.loadSessions()

      // 如果有活跃会话，从数据库加载消息
      if (this.activeSessionId) {
        await this.loadMessages(this.activeSessionId)
      }
    },
  },
})
