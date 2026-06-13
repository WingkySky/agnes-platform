/* =====================================================
 * axios 通用请求客户端封装
 * - 统一 baseURL
 * - 统一超时
 * - 统一错误处理（将后端消息转发给用户）
 * ===================================================== */

import axios from 'axios'
import { ElMessage } from 'element-plus'

// 使用 Vite 代理（开发环境）或 VITE_API_BASE_URL（生产环境）
const baseURL = import.meta.env.VITE_API_BASE_URL || ''

const client = axios.create({
  baseURL,
  timeout: 300000, // 5 分钟超时（图片生成可能需要较长时间）
  headers: {
    'Content-Type': 'application/json'
  }
})

// ---------- 请求拦截 ----------
client.interceptors.request.use(
  (config) => {
    return config
  },
  (error) => Promise.reject(error)
)

// ---------- 响应拦截 ----------
client.interceptors.response.use(
  (response) => {
    // 直接返回 data，简化组件写法
    return response.data
  },
  (error) => {
    // 统一错误提示（非静默失败时）
    let message = '请求失败，请稍后重试'

    if (error.code === 'ECONNABORTED') {
      message = '请求超时，请检查网络或稍后重试'
    } else if (error.response) {
      // 服务端返回了错误
      const data = error.response.data
      message =
        (data && (data.detail || data.message)) ||
        `请求失败（HTTP ${error.response.status}）`
    } else if (error.message) {
      message = error.message
    }

    // 只在非静默模式下弹提示
    if (!error.config?.silent) {
      ElMessage({
        type: 'error',
        message,
        duration: 4000,
        showClose: true
      })
    }

    return Promise.reject(new Error(message))
  }
)

export default client
