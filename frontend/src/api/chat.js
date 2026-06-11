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

/**
 * 修改会话标题
 * @param {number} sessionId
 * @param {string} title - 新的会话标题
 */
export function updateChatSession(sessionId, title) {
  return client.put(`/api/chat/sessions/${sessionId}`, { title })
}

/**
 * 使用 AI 自动总结会话主题（生成新标题）
 * @param {number} sessionId
 */
export function summarizeChatSession(sessionId) {
  return client.post(`/api/chat/sessions/${sessionId}/summarize`)
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
 * @param {string} content - 消息文本内容
 * @param {Array<{name:string, base64:string, size:number, mime_type:string}>} [attachments] - 可选附件列表
 * @param {Function} onEvent - 事件回调 (event: {type, ...}) => void
 * @param {AbortSignal} [signal] - 可选的 AbortSignal，用于取消请求
 * @returns {Promise<void>}
 */
export async function sendMessageStream(sessionId, content, attachments, onEvent, signal) {
  const baseURL = import.meta.env.VITE_API_BASE_URL || ''
  const url = `${baseURL}/api/chat/sessions/${sessionId}/messages`

  // =====================================================
  // 构造请求体（支持 base64 上传 / image_url / video_url / doc_url 四种格式）
  // 新增：自动从文本识别的 URL 会携带 _link_type 标注
  //   _link_type=image     → image_url（AI 可看图）
  //   _link_type=video     → video_url（作为参考记录，AI 当前不看视频）
  //   _link_type=document  → doc_url（作为参考记录，AI 当前不读文档）
  //   _link_type=webpage   → 不进入 attachments，仅保留在文本中
  // =====================================================
  const body = { content }
  if (attachments && attachments.length > 0) {
    body.attachments = attachments.map((a) => {
      // 视频链接
      if (a._link_type === 'video' && a.url) {
        return {
          name: a.name || 'video',
          video_url: a.url,
          size: 0,
          mime_type: 'video/url',
          source: 'url',
          _link_type: 'video',
        }
      }
      // 文档链接
      if (a._link_type === 'document' && a.url) {
        return {
          name: a.name || 'document',
          doc_url: a.url,
          size: 0,
          mime_type: 'application/url',
          source: 'url',
          _link_type: 'document',
        }
      }
      // 图片 URL 链接（手动添加或自动识别的 image 类型）
      if ((a.source === 'url' || a._link_type === 'image') && a.url) {
        return {
          name: a.name || 'url_image',
          image_url: a.url,
          size: 0,
          mime_type: 'image/url',
          source: 'url',
          _link_type: 'image',
        }
      }
      // base64 上传图片：传 base64_image 字段
      return {
        name: a.name || 'image.png',
        base64_image: a.base64,
        size: a.size || 0,
        mime_type: a.mime_type || 'image/png',
      }
    })
  }

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
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
// 媒体生成状态 & 回调
// =====================================================

/**
 * 查询媒体生成状态（图片/视频）
 * @param {string} taskId
 */
export function getMediaStatus(taskId) {
  return client.get(`/api/chat/media-status/${taskId}`, { silent: true })
}

/**
 * 媒体生成完成回调 — 前端轮询到结果后调用此接口更新数据库中的 media_items
 * @param {Object} params
 * @param {number} params.message_id - 消息 ID
 * @param {string} params.task_id - 生成任务 ID
 * @param {string} params.media_url - 生成完成的资源 URL
 * @param {string} [params.status='success'] - 状态：success / failed
 */
export function mediaCallback({ message_id, task_id, media_url, status = 'success' }) {
  return client.post('/api/chat/media-callback',
    { message_id, task_id, media_url, status },
    { silent: true }  // 静默模式：即使后端返回错误也不弹窗（由上层处理）
  )
}
