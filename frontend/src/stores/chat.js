/* =====================================================
 * Chat Store（Pinia）— 聊天状态管理
 *
 * 功能：
 *   - 管理聊天会话列表和当前活跃会话
 *   - 管理消息列表（含流式增量更新）
 *   - 处理 SSE 流式响应事件
 *   - 管理媒体生成任务状态（轮询更新）
 *   - 自动滚动到底部
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
} from '@/api/chat'

// 媒体轮询间隔
const MEDIA_POLL_INTERVAL = 3000

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

      this.activeSessionId = sessionId
      this.messages = []
      this.streamingContent = ''
      this.streamingToolCalls = []

      // 加载消息
      await this.loadMessages(sessionId)
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
      } catch (e) {
        console.error('[Chat] 删除会话失败:', e)
        throw e
      }
    },

    /** 加载会话消息 */
    async loadMessages(sessionId) {
      if (!sessionId) return
      this.loadingMessages = true
      try {
        const data = await getChatMessages(sessionId)
        this.messages = data.items || []

        // 检查是否有进行中的媒体任务，启动轮询
        for (const msg of this.messages) {
          if (msg.media_task_id && msg.media_status === 'pending') {
            this._startMediaPoll(msg.media_task_id)
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
        media_type: null,
        media_url: null,
        media_task_id: null,
        media_status: null,
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
      const assistantMsg = {
        id: Date.now() + 1,
        session_id: this.activeSessionId,
        role: 'assistant',
        content: '',
        media_type: null,
        media_url: null,
        media_task_id: null,
        media_status: null,
        created_at: new Date().toISOString(),
        _streaming: true, // 标记正在流式更新
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

        case 'tool_result':
          // 工具执行结果
          const tc = this.streamingToolCalls.find(t => t.tool === event.tool)
          if (tc) {
            tc.status = 'done'
            tc.result = event.result
          }
          // 如果有媒体任务，更新 AI 消息的媒体信息
          const lastMsg = this.messages[this.messages.length - 1]
          if (lastMsg && lastMsg.role === 'assistant' && event.result) {
            lastMsg.media_type = event.result.media_type
            lastMsg.media_task_id = event.result.task_id || event.result.video_id
            lastMsg.media_status = event.result.status
            // 启动媒体轮询
            if (lastMsg.media_task_id && event.result.status === 'pending') {
              this._startMediaPoll(lastMsg.media_task_id)
            }
          }
          this._updateStreamingMessage()
          break

        case 'assistant_message':
          // AI 消息已保存到数据库（更新 ID 和完整信息）
          if (event.message) {
            const lastMsg = this.messages[this.messages.length - 1]
            if (lastMsg && lastMsg.role === 'assistant') {
              lastMsg.id = event.message.id
              lastMsg.content = event.message.content || this.streamingContent
              lastMsg.media_type = event.message.media_type
              lastMsg.media_url = event.message.media_url
              lastMsg.media_task_id = event.message.media_task_id
              lastMsg.media_status = event.message.media_status
              lastMsg._streaming = false
            }
          }
          break

        case 'error':
          // 错误事件
          const errMsg = this.messages[this.messages.length - 1]
          if (errMsg && errMsg.role === 'assistant') {
            errMsg.content += `\n\n❌ 错误：${event.content}`
            errMsg._streaming = false
          }
          break

        case 'done':
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
    // 【媒体轮询】
    // =====================================================

    /** 启动媒体生成状态轮询 */
    _startMediaPoll(taskId) {
      if (this.mediaPollTimers[taskId]) return

      const poll = async () => {
        try {
          const data = await getMediaStatus(taskId)
          this.mediaStatusMap[taskId] = data

          // 更新消息中的媒体信息
          const msg = this.messages.find(m => m.media_task_id === taskId)
          if (msg) {
            const rawStatus = String(data.status || '').toLowerCase()
            const isSuccess = ['success', 'completed', 'done'].includes(rawStatus)
            const isFailed = ['failed', 'error'].includes(rawStatus)

            if (isSuccess) {
              msg.media_status = 'success'
              msg.media_url = data.result_url || data.video_url || data.url || ''
              this._stopMediaPoll(taskId)
            } else if (isFailed) {
              msg.media_status = 'failed'
              this._stopMediaPoll(taskId)
            } else {
              msg.media_status = 'processing'
            }
          }
        } catch (e) {
          // 单次轮询失败不影响
          console.warn('[Chat] 媒体状态轮询失败:', taskId, e.message)
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
  },
})
