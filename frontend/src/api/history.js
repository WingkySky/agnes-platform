/* =====================================================
 * 生成历史记录相关 API 封装
 * ===================================================== */

import client from './client'

/**
 * 获取历史列表
 * @param {Object} opts
 * @param {string} [opts.type]  - image / video / all
 * @param {number} [opts.page]
 * @param {number} [opts.page_size]
 */
export function getHistoryList({ type = 'all', page = 1, page_size = 50 } = {}) {
  return client.get('/api/history', { params: { type, page, page_size } })
}

/**
 * 删除单条历史记录
 * @param {number} id
 */
export function deleteHistoryRecord(id) {
  return client.delete(`/api/history/${id}`)
}

/**
 * 批量删除多条历史记录
 * @param {Array<number>} ids - 要删除的记录 ID 列表
 */
export function batchDeleteHistory(ids) {
  return client.post('/api/history/batch-delete', { ids })
}

/**
 * 获取前端配置（模型列表 / 尺寸选项等）
 */
export function getPlatformConfig() {
  return client.get('/api/config')
}
