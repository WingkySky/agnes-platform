/* =====================================================
 * 图片生成相关 API 封装
 * - 支持异步任务模式（类似视频生成）
 * - createImageTask      : 创建异步任务，返回 task_id
 * - getImageTaskStatus   : 轮询任务状态
 * - cancelImageTask      : 取消任务
 * - 兼容旧的 createImage / getImageRecord 接口（同步模式，保留兼容）
 * ===================================================== */

import client from './client'

/**
 * 创建图片异步生成任务（推荐使用）
 * @param {Object} params
 * @param {string} params.prompt        - 提示词
 * @param {string} params.model         - 模型名
 * @param {string} params.size          - 尺寸，如 1024x1024
 * @param {string} params.response_format - url / b64_json
 * @param {string} [params.base64_image]- 图生图时的参考图（base64，不带前缀）
 * @returns {Promise<{task_id: string, id: string, status: string, ...}>}
 */
export function createImageTask(params) {
  return client.post('/api/images/tasks', params)
}

/**
 * 查询图片任务状态（轮询用）
 * @param {string} taskId
 * @returns {Promise<{
 *   status: string,
 *   progress: number,
 *   result_url?: string,
 *   url?: string,
 *   message?: string
 * }>}
 */
export function getImageTaskStatus(taskId) {
  return client.get(`/api/images/tasks/${taskId}`, { silent: true })
}

/**
 * 取消图片生成任务
 * @param {string} taskId
 */
export function cancelImageTask(taskId) {
  return client.delete(`/api/images/tasks/${taskId}`)
}

/* ============ 以下为兼容旧代码的接口（同步模式） ============ */

/**
 * 同步生成图片（阻塞式，不推荐新代码使用）
 * @param {Object} params
 */
export function createImage(params) {
  return client.post('/api/images/generations', params)
}

/**
 * 获取单张图片生成记录
 * @param {number} id
 */
export function getImageRecord(id) {
  return client.get(`/api/images/${id}`)
}
