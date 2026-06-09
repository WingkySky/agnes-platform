/* =====================================================
 * 聊天相关 API 封装
 * - 会话管理（创建/列表/删除/详情）
 * - 消息发送（SSE 流式响应）
 * - 消息历史查询
 * - 媒体生成状态查询
 * ===================================================== */

import client from './client'

// =====================================================
// 会话管理
// =====================================================

/**
 * 创建新聊天会话
 * @param {Object} [params]
 * @param {string} [params.title] - 会话标题（可选）
 * @returns {Promise<{id: number, title: string, ...}>}
 */
export function createChatSession(params = {}) {
  return client.post('/api/chat/sessions', params)
}

/**
 * 获取会话列表
 * @param {Object} [opts]
 * @param {number} [opts.page]
 * @param {number} [opts.page_size]
 */
export function getChatSessions({ page = 1, page_size = 20 } = {}) {
  return client.get('/api/chat/sessions', { params: { page, page_size } })
}

/**
 * 获取会话详情（含消息）
 * @param {number} sessionId
 */
export function getChatSession(sessionId) {
  return client.get(`/api/chat/sessions/${sessionId}`)
}

/**
 * 删除会话
 * @param {number} sessionId
 */
export function deleteChatSession(sessionId) {
  return client.delete(`/api/chat/sessions/${sessionId}`)
}

// =====================================================
// 消息
// =====================================================

/**
 * 获取会话消息列表
 * @param {number} sessionId
 */
export function getChatMessages(sessionId) {
  return client.get(`/api/chat/sessions/${sessionId}/messages`)
}

/**
 * 发送消息（SSE 流式响应）
 * 注意：此接口返回 SSE 流，需要使用 EventSource 或 fetch + ReadableStream 处理
 * 不使用 axios，直接用 fetch API 处理 SSE
 *
 * @param {number} sessionId
 * @param {string} content - 消息内容
 * @param {Function} onEvent - 事件回调 (event: {type, ...}) => void
 * @param {AbortSignal} [signal] - 可选的 AbortSignal，用于取消请求
 * @returns {Promise<void>}
 */
export async function sendMessageStream(sessionId, content, onEvent, signal) {
  const baseURL = import.meta.env.VITE_API_BASE_URL || ''
  const url = `${baseURL}/api/chat/sessions/${sessionId}/messages`

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ content }),
    signal,
  })

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}))
    throw new Error(errorData.detail || `请求失败 (HTTP ${response.status})`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // 解析 SSE 事件（以双换行分隔）
      const lines = buffer.split('\n')
      buffer = lines.pop() || '' // 保留未完成的行

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed || !trimmed.startsWith('data: ')) continue

        const dataStr = trimmed.slice(6) // 去掉 "data: " 前缀
        if (dataStr === '[DONE]') {
          onEvent({ type: 'done' })
          return
        }

        try {
          const event = JSON.parse(dataStr)
          onEvent(event)
        } catch (e) {
          // 解析失败的行忽略
          console.warn('[Chat] SSE 解析失败:', dataStr)
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

// =====================================================
// 媒体生成状态
// =====================================================

/**
 * 查询媒体生成状态（图片/视频）
 * @param {string} taskId
 */
export function getMediaStatus(taskId) {
  return client.get(`/api/chat/media-status/${taskId}`, { silent: true })
}
