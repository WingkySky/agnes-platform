<!-- =====================================================
     ChatView.vue — AI 聊天界面
     功能：
     - 左侧：会话列表（新建/切换/删除）
     - 右侧：聊天消息区 + 输入框
     - 支持流式文本回复（逐字显示）
     - 支持图片/视频生成（工具调用，内嵌展示）
     - 支持多图/多视频展示（media_items 数组）
     - 页面切换后状态保持（从数据库恢复）
     - 自动滚动到最新消息
     ===================================================== -->

<template>
  <div class="chat-view">
    <!-- 左侧：会话列表 -->
    <aside class="chat-sidebar">
      <div class="sidebar-header">
        <h3>{{ t('chat.title') }}</h3>
        <el-button type="primary" size="small" @click="handleNewSession" :icon="Plus" circle />
      </div>

      <div class="session-list">
        <div
          v-for="session in chatStore.sessions"
          :key="session.id"
          class="session-item"
          :class="{ active: session.id === chatStore.activeSessionId }"
          @click="handleSwitchSession(session.id)"
        >
          <div class="session-info">
            <span class="session-title">{{ session.title || t('chat.newChat') }}</span>
            <span class="session-time">{{ formatTime(session.updated_at) }}</span>
          </div>
          <div class="session-actions">
            <!-- AI 总结标题按钮 -->
            <el-button
              class="session-action-btn"
              :icon="MagicStick"
              size="small"
              text
              :title="t('chat.autoSummarize')"
              @click.stop="handleAutoSummarize(session.id)"
            />
            <!-- 编辑标题按钮 -->
            <el-button
              class="session-action-btn"
              :icon="Edit"
              size="small"
              text
              :title="t('chat.renameSession')"
              @click.stop="handleRenameSession(session)"
            />
            <!-- 删除按钮 -->
            <el-button
              class="session-action-btn"
              :icon="Delete"
              size="small"
              text
              :title="t('chat.deleteSession')"
              @click.stop="handleDeleteSession(session.id)"
            />
          </div>
        </div>

        <div v-if="chatStore.sessions.length === 0" class="session-empty">
          <p>{{ t('chat.noSessions') }}</p>
        </div>
      </div>
    </aside>

    <!-- 右侧：聊天区（拖拽覆盖整个区域） -->
    <main
      class="chat-main"
      @dragover.prevent="onDragOver"
      @dragenter.prevent="onDragEnter"
      @dragleave.prevent="onDragLeave"
      @drop.prevent="onDrop"
    >
      <!-- 拖拽覆盖提示（覆盖整个聊天区域，包括输入栏） -->
      <div v-if="isDragging" class="drag-overlay">
        <div class="drag-overlay-content">
          <el-icon :size="56"><Picture /></el-icon>
          <p>释放以添加图片</p>
        </div>
      </div>
      <!-- 重命名会话对话框 -->
      <el-dialog
        v-model="renameDialogVisible"
        :title="t('chat.renameSession')"
        width="400px"
        :close-on-click-modal="false"
      >
        <el-input
          v-model="renameInput"
          :placeholder="t('chat.enterNewTitle')"
          maxlength="200"
          show-word-limit
          @keyup.enter="confirmRename"
        />
        <template #footer>
          <el-button @click="renameDialogVisible = false">{{ t('common.cancel') }}</el-button>
          <el-button type="primary" :disabled="!renameInput.trim()" @click="confirmRename">
            {{ t('common.confirm') }}
          </el-button>
        </template>
      </el-dialog>
      <!-- 无会话时的欢迎页 -->
      <div v-if="!chatStore.hasActiveSession" class="chat-welcome">
        <div class="welcome-icon">💬</div>
        <h2>{{ t('chat.welcomeTitle') }}</h2>
        <p>{{ t('chat.welcomeDesc') }}</p>
        <div class="welcome-actions">
          <el-button type="primary" @click="handleNewSession">
            {{ t('chat.startChat') }}
          </el-button>
        </div>
        <div class="welcome-tips">
          <div class="tip-item" v-for="tip in quickTips" :key="tip" @click="handleQuickTip(tip)">
            <el-icon><ChatDotRound /></el-icon>
            <span>{{ tip }}</span>
          </div>
        </div>
      </div>

      <!-- 聊天区域（拖拽覆盖整个区域，包括输入栏） -->
      <template v-else>
        <!-- 消息列表 -->
        <div
          class="chat-messages"
          ref="messagesRef"
        >
          <div
            v-for="msg in chatStore.messages"
            :key="msg.id"
            class="message-item"
            :class="[`message-${msg.role}`]"
          >
            <!-- 用户消息 -->
            <div v-if="msg.role === 'user'" class="message-bubble user-bubble">
              <div class="message-avatar user-avatar">
                <el-icon :size="18"><User /></el-icon>
              </div>
              <div class="message-content">
                <!-- 用户上传的参考图附件 -->
                <div v-if="msg.attachments && msg.attachments.length > 0" class="attachments-preview">
                  <el-image
                    v-for="(att, idx) in msg.attachments"
                    :key="'att-' + idx"
                    :src="att.url || att.base64 || att.base64_image"
                    :preview-src-list="getAttachmentPreviewList(msg.attachments)"
                    :initial-index="idx"
                    fit="cover"
                    class="attachment-thumb"
                    :preview-teleported="true"
                  >
                    <template #error>
                      <div class="attachment-thumb-fallback">
                        <el-icon><WarningFilled /></el-icon>
                      </div>
                    </template>
                  </el-image>
                </div>
                <p v-if="msg.content">{{ msg.content }}</p>
              </div>
            </div>

            <!-- AI 消息 -->
            <div v-else-if="msg.role === 'assistant'" class="message-bubble assistant-bubble">
              <div class="message-avatar assistant-avatar">
                <el-icon :size="18"><Monitor /></el-icon>
              </div>
              <div class="message-content">
                <!-- 文本内容 -->
                <div v-if="msg.content" class="message-text" v-html="renderMarkdown(msg.content)"></div>

                <!-- 流式输入光标 -->
                <span v-if="msg._streaming" class="streaming-cursor">▊</span>

                <!-- 工具调用提示（流式阶段显示） -->
                <div v-for="tc in getToolCallsForMessage(msg)" :key="tc.tool + tc.args?.prompt" class="tool-call-badge">
                  <el-icon v-if="tc.tool === 'generate_image'"><Picture /></el-icon>
                  <el-icon v-else-if="tc.tool === 'generate_video'"><VideoPlay /></el-icon>
                  <span>{{ tc.tool === 'generate_image' ? t('chat.generatingImage') : t('chat.generatingVideo') }}</span>
                  <el-icon v-if="tc.status === 'calling'" class="is-loading"><Loading /></el-icon>
                  <el-icon v-else-if="tc.status === 'done'" class="tool-done"><Check /></el-icon>
                </div>

                <!-- 媒体内容（遍历 media_items 数组，支持多图/多视频） -->
                <template v-if="msg.media_items && msg.media_items.length > 0">
                  <div
                    v-for="(item, idx) in msg.media_items"
                    :key="item.task_id || idx"
                    class="media-container"
                  >
                    <!-- 图片 -->
                    <template v-if="item.type === 'image'">
                      <!-- 图片已生成完成 -->
                      <el-image
                        v-if="item.url && item.status === 'success'"
                        :src="item.url"
                        :preview-src-list="getAllImageUrls(msg.media_items)"
                        :initial-index="getImageIndex(msg.media_items, idx)"
                        fit="contain"
                        class="media-image"
                        :preview-teleported="true"
                      >
                        <template #error>
                          <div class="media-loading">
                            <el-icon class="is-loading"><Loading /></el-icon>
                            <span>{{ t('chat.mediaLoading') }}</span>
                          </div>
                        </template>
                      </el-image>
                      <!-- 图片生成中 -->
                      <div v-else-if="item.status === 'pending' || item.status === 'processing'" class="media-generating">
                        <el-icon class="is-loading"><Loading /></el-icon>
                        <span>{{ t('chat.imageGenerating') }}</span>
                      </div>
                      <!-- 图片生成失败 -->
                      <div v-else-if="item.status === 'failed'" class="media-failed">
                        <el-icon><WarningFilled /></el-icon>
                        <span>{{ t('chat.mediaFailed') }}</span>
                      </div>
                    </template>

                    <!-- 视频 -->
                    <template v-if="item.type === 'video'">
                      <!-- 视频已生成完成 -->
                      <video
                        v-if="item.url && item.status === 'success'"
                        :src="getVideoProxyUrl(item.url, item.task_id)"
                        controls
                        class="media-video"
                        @error="onVideoError"
                      >
                        {{ t('chat.videoNotSupported') }}
                      </video>
                      <!-- 视频生成中 -->
                      <div v-else-if="item.status === 'pending' || item.status === 'processing'" class="media-generating">
                        <el-icon class="is-loading"><Loading /></el-icon>
                        <span>{{ t('chat.videoGenerating') }}</span>
                      </div>
                      <!-- 视频生成失败 -->
                      <div v-else-if="item.status === 'failed'" class="media-failed">
                        <el-icon><WarningFilled /></el-icon>
                        <span>{{ t('chat.mediaFailed') }}</span>
                      </div>
                    </template>
                  </div>
                </template>
              </div>
            </div>
          </div>

          <!-- 加载中 -->
          <div v-if="chatStore.loadingMessages" class="chat-loading">
            <el-icon class="is-loading"><Loading /></el-icon>
            <span>{{ t('common.loading') }}</span>
          </div>
        </div>

        <!-- 输入区 -->
        <div class="chat-input-area">
          <!-- 待发送附件预览 -->
          <div v-if="pendingAttachments.length > 0" class="pending-attachments">
            <div
              v-for="(att, idx) in pendingAttachments"
              :key="'pending-' + idx"
              class="pending-attachment"
            >
              <img :src="att.base64" :alt="att.name" class="pending-attachment-thumb" />
              <el-button
                type="danger"
                size="small"
                circle
                icon="Close"
                class="pending-attachment-remove"
                @click="removePendingAttachment(idx)"
              />
            </div>
          </div>

          <div class="input-wrapper">
            <!-- 上传按钮（加号图标） -->
            <el-button
              :icon="Plus"
              class="upload-btn"
              :disabled="chatStore.sending"
              @click="$refs.fileInput.click()"
              title="上传参考图"
            />
            <input
              ref="fileInput"
              type="file"
              accept="image/*"
              multiple
              class="hidden-file-input"
              @change="onAttachmentSelected"
            />

            <el-input
              v-model="inputText"
              type="textarea"
              :rows="2"
              :placeholder="t('chat.inputPlaceholder')"
              :disabled="chatStore.sending"
              @keydown.enter.exact="handleEnter"
              resize="none"
              class="chat-input"
            />
            <el-button
              type="primary"
              :icon="Promotion"
              :loading="chatStore.sending"
              :disabled="!canSend"
              @click="handleSend"
              class="send-btn"
            />
          </div>
          <p class="input-hint">{{ t('chat.inputHint') }} · 可上传参考图进行图生图/图生视频</p>
        </div>
      </template>
    </main>
  </div>
</template>

<script setup>
// 组件名称（供 keep-alive 缓存识别）
defineOptions({ name: 'ChatView' })

import { ref, onMounted, onActivated, nextTick, watch, computed } from 'vue'
import {
  Plus, Delete, User, Monitor, Picture, VideoPlay,
  Loading, Check, WarningFilled, Promotion, ChatDotRound,
  Edit, MagicStick, Close,
} from '@element-plus/icons-vue'
import { useI18n } from '@/i18n'
import { useChatStore } from '@/stores/chat'
import { ElMessageBox, ElMessage } from 'element-plus'

const { t } = useI18n()
const chatStore = useChatStore()

// 输入框文本
const inputText = ref('')
// 消息列表 DOM 引用
const messagesRef = ref(null)
// 隐藏的文件上传 input（用于触发文件选择）
const fileInput = ref(null)
// 待发送的附件列表（未发送消息时本地缓存）
const pendingAttachments = ref([])
// 拖拽状态
const isDragging = ref(false)
// 是否允许发送（有文本 或 有待发附件）
const canSend = computed(() => inputText.value.trim().length > 0 || pendingAttachments.value.length > 0)
// 最大附件数与单文件大小限制（对应后端 Task 2 的校验）
const MAX_ATTACHMENTS = 10
const MAX_FILE_SIZE = 5 * 1024 * 1024 // 5MB

// 重命名会话相关
const renameDialogVisible = ref(false)
const renameInput = ref('')
const renamingSessionId = ref(null)

// 快捷提示
const quickTips = computed(() => [
  t('chat.tipImage'),
  t('chat.tipVideo'),
  t('chat.tipChat'),
])

// =====================================================
// 生命周期
// =====================================================
onMounted(async () => {
  // 使用 init() 初始化（从 localStorage 恢复 + 从数据库加载消息）
  await chatStore.init()
})

// 配合 keep-alive：从其他标签页切回时恢复滚动位置（保留在后台累积的流式内容可见）
onActivated(() => {
  scrollToBottom()
})

// 监听消息变化，自动滚动到底部
watch(
  () => chatStore.messages.length,
  () => scrollToBottom(),
)
watch(
  () => chatStore.streamingContent,
  () => scrollToBottom(),
)

// =====================================================
// 交互处理
// =====================================================

/** 新建会话 */
async function handleNewSession() {
  try {
    await chatStore.newSession()
  } catch (e) {
    ElMessage.error(t('chat.createFailed'))
  }
}

/** 切换会话 */
async function handleSwitchSession(sessionId) {
  if (sessionId === chatStore.activeSessionId) return
  try {
    await chatStore.switchSession(sessionId)
  } catch (e) {
    ElMessage.error(t('chat.switchFailed'))
  }
}

/** 删除会话 */
async function handleDeleteSession(sessionId) {
  try {
    await ElMessageBox.confirm(t('chat.confirmDelete'), t('common.confirm'), {
      type: 'warning',
    })
    await chatStore.removeSession(sessionId)
    ElMessage.success(t('chat.deleted'))
  } catch (_) {
    // 取消删除
  }
}

/** 重命名会话 - 打开对话框 */
function handleRenameSession(session) {
  renamingSessionId.value = session.id
  renameInput.value = session.title || ''
  renameDialogVisible.value = true
}

/** 重命名会话 - 确认修改 */
async function confirmRename() {
  const newTitle = renameInput.value.trim()
  if (!newTitle) {
    ElMessage.warning(t('chat.titleNotEmpty'))
    return
  }
  try {
    await chatStore.updateSessionTitle(renamingSessionId.value, newTitle)
    ElMessage.success(t('chat.renameSuccess'))
    renameDialogVisible.value = false
    renameInput.value = ''
    renamingSessionId.value = null
  } catch (e) {
    ElMessage.error(e.message || t('chat.renameFailed'))
  }
}

/** AI 自动总结会话标题 */
async function handleAutoSummarize(sessionId) {
  try {
    ElMessage.info(t('chat.summarizing'))
    const updated = await chatStore.autoSummarizeSession(sessionId)
    ElMessage.success(t('chat.summarizeSuccess') + ': ' + updated.title)
  } catch (e) {
    ElMessage.error(e.message || t('chat.summarizeFailed'))
  }
}

/** 发送消息（支持附件） */
async function handleSend() {
  const content = inputText.value.trim()
  const attachments = pendingAttachments.value
  if (!content && attachments.length === 0) return
  if (chatStore.sending) return

  inputText.value = ''
  pendingAttachments.value = []
  try {
    await chatStore.sendMessage(content, attachments)
  } catch (e) {
    ElMessage.error(e.message || t('chat.sendFailed'))
  }
}

/** 回车发送（Shift+Enter 换行） */
function handleEnter(e) {
  if (e.shiftKey) return // Shift+Enter 换行
  e.preventDefault()
  handleSend()
}

// =====================================================
// 附件（图片）上传相关
// =====================================================
/** 读取图片文件为 base64（data URL） */
function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

/** 从 data URL 提取 MIME 类型 */
function extractMime(dataUrl) {
  const m = dataUrl.match(/^data:([^;]+);/)
  return m ? m[1] : 'image/png'
}

/** 文件选择回调：校验大小/数量，转为 base64 加入待发队列 */
async function onAttachmentSelected(event) {
  const files = Array.from(event.target.files || [])
  // 重置 input value，便于重复选择同一文件触发 change
  event.target.value = ''
  if (files.length === 0) return

  const remainingSlot = MAX_ATTACHMENTS - pendingAttachments.value.length
  if (remainingSlot <= 0) {
    ElMessage.warning(`最多上传 ${MAX_ATTACHMENTS} 张图片`)
    return
  }

  const accepted = files.slice(0, remainingSlot)
  const results = []
  for (const file of accepted) {
    if (!file.type.startsWith('image/')) {
      ElMessage.warning(`不支持的文件类型：${file.name}`)
      continue
    }
    if (file.size > MAX_FILE_SIZE) {
      ElMessage.warning(`图片 ${file.name} 超过 5MB`)
      continue
    }
    try {
      const dataUrl = await readFileAsDataURL(file)
      results.push({
        name: file.name,
        base64: dataUrl,
        size: file.size,
        mime_type: extractMime(dataUrl),
      })
    } catch (err) {
      console.error('[Chat] 读取文件失败:', err)
      ElMessage.error(`读取 ${file.name} 失败`)
    }
  }

  pendingAttachments.value.push(...results)
}

/** 移除某个待发送的附件 */
function removePendingAttachment(idx) {
  pendingAttachments.value.splice(idx, 1)
}

// =====================================================
// 拖拽文件上传
// =====================================================
// 拖拽计数器：解决 dragleave 子元素冒泡导致覆盖层闪烁的问题
let dragCounter = 0

/** 拖拽进入 */
function onDragOver(e) {
  if (!isDragging.value) {
    isDragging.value = true
  }
}

/** 拖拽进入时计数+1 */
function onDragEnter(e) {
  dragCounter++
  isDragging.value = true
}

/** 拖拽离开时计数-1，归零才关闭覆盖层 */
function onDragLeave(e) {
  dragCounter--
  if (dragCounter <= 0) {
    dragCounter = 0
    isDragging.value = false
  }
}

/** 拖拽释放：处理文件 */
async function onDrop(e) {
  isDragging.value = false
  dragCounter = 0
  const files = Array.from(e.dataTransfer?.files || [])
  if (files.length === 0) return

  const remainingSlot = MAX_ATTACHMENTS - pendingAttachments.value.length
  if (remainingSlot <= 0) {
    ElMessage.warning(`最多上传 ${MAX_ATTACHMENTS} 张图片`)
    return
  }

  const accepted = files.slice(0, remainingSlot)
  const results = []
  for (const file of accepted) {
    if (!file.type.startsWith('image/')) {
      ElMessage.warning(`不支持的文件类型：${file.name}`)
      continue
    }
    if (file.size > MAX_FILE_SIZE) {
      ElMessage.warning(`图片 ${file.name} 超过 5MB`)
      continue
    }
    try {
      const dataUrl = await readFileAsDataURL(file)
      results.push({
        name: file.name,
        base64: dataUrl,
        size: file.size,
        mime_type: extractMime(dataUrl),
      })
    } catch (err) {
      console.error('[Chat] 读取拖拽文件失败:', err)
      ElMessage.error(`读取 ${file.name} 失败`)
    }
  }
  pendingAttachments.value.push(...results)
}

/** 获取附件预览列表（用于 el-image 组预览） */
function getAttachmentPreviewList(attachments) {
  if (!attachments || attachments.length === 0) return []
  return attachments.map((a) => a.url || a.base64 || a.base64_image)
}

/** 快捷提示点击 */
async function handleQuickTip(tip) {
  if (!chatStore.hasActiveSession) {
    await chatStore.newSession()
  }
  inputText.value = tip
  handleSend()
}

/** 滚动到底部 */
async function scrollToBottom() {
  await nextTick()
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

// =====================================================
// 工具函数
// =====================================================

/** 格式化时间 */
function formatTime(isoStr) {
  if (!isoStr) return ''
  const d = new Date(isoStr)
  const now = new Date()
  const isToday = d.toDateString() === now.toDateString()
  if (isToday) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

/** 简易 Markdown 渲染（支持代码块、加粗、换行） */
function renderMarkdown(text) {
  if (!text) return ''
  let html = text
    // 转义 HTML
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    // 代码块
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="lang-$1">$2</code></pre>')
    // 行内代码
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // 加粗
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // 换行
    .replace(/\n/g, '<br>')
  return html
}

/** 获取消息的工具调用信息 */
function getToolCallsForMessage(msg) {
  if (!msg._streaming) return []
  return chatStore.streamingToolCalls
}

/** 获取视频代理 URL */
function getVideoProxyUrl(url, taskId) {
  if (!url) return ''
  // 如果是 Google Storage 等跨域 URL，使用后端代理
  if (taskId && (url.includes('storage.googleapis.com') || url.includes('google'))) {
    const baseURL = import.meta.env.VITE_API_BASE_URL || ''
    return `${baseURL}/api/videos/${taskId}/stream`
  }
  return url
}

/** 视频加载失败 */
function onVideoError(e) {
  console.warn('[Chat] 视频加载失败')
}

/** 获取消息中所有图片 URL（用于图片预览） */
function getAllImageUrls(mediaItems) {
  if (!mediaItems) return []
  return mediaItems
    .filter(item => item.type === 'image' && item.url && item.status === 'success')
    .map(item => item.url)
}

/** 获取当前图片在预览列表中的索引 */
function getImageIndex(mediaItems, currentIdx) {
  if (!mediaItems) return 0
  const imageItems = mediaItems.filter(item => item.type === 'image' && item.url && item.status === 'success')
  const currentItem = mediaItems[currentIdx]
  const idx = imageItems.indexOf(currentItem)
  return idx >= 0 ? idx : 0
}
</script>

<style scoped>
/* =====================================================
 * 聊天界面样式（深色主题，与项目整体风格一致）
 * ===================================================== */

.chat-view {
  display: flex;
  height: calc(100vh - 160px);
  min-height: 500px;
  gap: 0;
  background: rgba(15, 22, 38, 0.4);
  border-radius: 16px;
  border: 1px solid rgba(100, 150, 220, 0.15);
  overflow: hidden;
}

/* ---- 左侧边栏 ---- */
.chat-sidebar {
  width: 260px;
  min-width: 260px;
  background: rgba(10, 16, 30, 0.6);
  border-right: 1px solid rgba(100, 150, 220, 0.12);
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 16px 12px;
  border-bottom: 1px solid rgba(100, 150, 220, 0.1);
}

.sidebar-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #c9d6e8;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  margin-bottom: 2px;
}

.session-item:hover {
  background: rgba(120, 170, 255, 0.08);
}

.session-item.active {
  background: linear-gradient(135deg, rgba(80, 140, 255, 0.2) 0%, rgba(160, 120, 255, 0.2) 100%);
  border: 1px solid rgba(100, 150, 220, 0.2);
}

.session-info {
  flex: 1;
  min-width: 0;
}

.session-title {
  display: block;
  font-size: 13px;
  color: #d0dce8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-time {
  display: block;
  font-size: 11px;
  color: #6b84aa;
  margin-top: 2px;
}

.session-delete {
  opacity: 0;
  transition: opacity 0.2s;
  color: #8ba3c9 !important;
}

.session-actions {
  display: flex;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.2s;
}

.session-item:hover .session-actions {
  opacity: 1;
}

.session-action-btn {
  color: #8ba3c9 !important;
}

.session-action-btn:hover {
  color: #a0d4ff !important;
}

.session-empty {
  text-align: center;
  padding: 40px 16px;
  color: #6b84aa;
  font-size: 13px;
}

/* ---- 右侧主区域 ---- */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  position: relative;
}

/* 拖拽覆盖层（覆盖整个聊天区域，类似豆包风格） */
.drag-overlay {
  position: absolute;
  inset: 0;
  background: rgba(10, 20, 40, 0.88);
  border: 2px dashed rgba(100, 180, 255, 0.6);
  border-radius: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  pointer-events: none;
  backdrop-filter: blur(4px);
}

.drag-overlay-content {
  text-align: center;
  color: #a0d4ff;
  animation: dragPulse 1.5s ease-in-out infinite;
}

.drag-overlay-content p {
  margin: 16px 0 0;
  font-size: 18px;
  font-weight: 500;
  letter-spacing: 1px;
}

@keyframes dragPulse {
  0%, 100% { opacity: 0.8; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.05); }
}

/* ---- 欢迎页 ---- */
.chat-welcome {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  text-align: center;
}

.welcome-icon {
  font-size: 56px;
  margin-bottom: 20px;
  filter: drop-shadow(0 0 20px rgba(120, 180, 255, 0.4));
}

.chat-welcome h2 {
  font-size: 22px;
  font-weight: 600;
  color: #d0dce8;
  margin: 0 0 8px;
}

.chat-welcome p {
  color: #8ba3c9;
  font-size: 14px;
  margin: 0 0 24px;
  max-width: 400px;
}

.welcome-actions {
  margin-bottom: 32px;
}

.welcome-tips {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: 400px;
  width: 100%;
}

.tip-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: rgba(20, 30, 50, 0.5);
  border: 1px solid rgba(100, 150, 220, 0.15);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s ease;
  color: #a0b4d6;
  font-size: 13px;
  text-align: left;
}

.tip-item:hover {
  background: rgba(120, 170, 255, 0.1);
  border-color: rgba(100, 150, 220, 0.3);
  color: #d0dce8;
}

/* ---- 消息列表 ---- */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.message-item {
  max-width: 85%;
}

.message-user {
  align-self: flex-end;
}

.message-assistant {
  align-self: flex-start;
}

.message-bubble {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.message-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.user-avatar {
  background: linear-gradient(135deg, #508cff 0%, #a078ff 100%);
  color: #fff;
  order: 2;
}

.assistant-avatar {
  background: linear-gradient(135deg, #1a3a5c 0%, #2a1a4c 100%);
  color: #a0d4ff;
  border: 1px solid rgba(100, 150, 220, 0.2);
}

.message-content {
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}

.user-bubble .message-content {
  background: linear-gradient(135deg, rgba(80, 140, 255, 0.3) 0%, rgba(160, 120, 255, 0.3) 100%);
  color: #e8eef7;
  border: 1px solid rgba(100, 150, 220, 0.2);
  order: 1;
}

.assistant-bubble .message-content {
  background: rgba(20, 30, 50, 0.5);
  color: #d0dce8;
  border: 1px solid rgba(100, 150, 220, 0.1);
}

.message-text {
  white-space: pre-wrap;
}

.message-text :deep(code) {
  background: rgba(100, 150, 220, 0.15);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 13px;
  color: #a0d4ff;
}

.message-text :deep(pre) {
  background: rgba(10, 16, 30, 0.8);
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 8px 0;
}

.message-text :deep(pre code) {
  background: none;
  padding: 0;
}

/* 流式光标 */
.streaming-cursor {
  display: inline-block;
  animation: blink 1s infinite;
  color: #a0d4ff;
  font-size: 14px;
  margin-left: 2px;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

/* 工具调用提示 */
.tool-call-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: rgba(100, 150, 220, 0.12);
  border-radius: 6px;
  font-size: 12px;
  color: #a0d4ff;
  margin-top: 6px;
  margin-right: 6px;
}

.tool-done {
  color: #67c23a;
}

/* 媒体容器 */
.media-container {
  margin-top: 10px;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid rgba(100, 150, 220, 0.15);
}

.media-image {
  max-width: 400px;
  max-height: 400px;
  display: block;
}

.media-video {
  max-width: 480px;
  max-height: 360px;
  display: block;
}

.media-loading,
.media-generating,
.media-failed {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  color: #8ba3c9;
  font-size: 13px;
}

.media-generating {
  color: #a0d4ff;
}

.media-failed {
  color: #f56c6c;
}

/* 加载中 */
.chat-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #8ba3c9;
  font-size: 13px;
  padding: 16px;
  justify-content: center;
}

/* ---- 输入区 ---- */
.chat-input-area {
  padding: 16px 24px 12px;
  border-top: 1px solid rgba(100, 150, 220, 0.1);
  background: rgba(10, 16, 30, 0.3);
}

.input-wrapper {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.input-wrapper :deep(.el-textarea__inner) {
  background: rgba(20, 30, 50, 0.6);
  border: 1px solid rgba(100, 150, 220, 0.2);
  color: #d0dce8;
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 14px;
  resize: none;
}

.input-wrapper :deep(.el-textarea__inner):focus {
  border-color: rgba(100, 150, 220, 0.4);
  box-shadow: 0 0 0 2px rgba(80, 140, 255, 0.1);
}

.input-wrapper :deep(.el-textarea__inner)::placeholder {
  color: #6b84aa;
}

.send-btn {
  height: 40px;
  width: 40px;
  border-radius: 10px;
  flex-shrink: 0;
}

/* --- 附件上传相关样式 --- */

/** 图片上传按钮 */
.upload-btn {
  height: 40px;
  width: 40px;
  border-radius: 10px;
  flex-shrink: 0;
}

/** 隐藏的原生 file input */
.hidden-file-input {
  display: none;
}

/** 聊天输入框（显式加 class，便于与其他输入区分） */
.chat-input {
  flex: 1;
}

/** 待发送附件预览容器（位于输入框上方） */
.pending-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

/** 单个待发送附件 */
.pending-attachment {
  position: relative;
  width: 72px;
  height: 72px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid rgba(100, 150, 220, 0.25);
  background: rgba(20, 30, 50, 0.4);
}

.pending-attachment-thumb {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.pending-attachment-remove {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 20px !important;
  height: 20px !important;
  padding: 0 !important;
  font-size: 12px;
}

/** 用户消息气泡中的附件缩略图 */
.attachments-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.attachment-thumb {
  width: 80px;
  height: 80px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid rgba(100, 150, 220, 0.3);
}

.attachment-thumb-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 100, 100, 0.1);
  color: #ff8080;
}

.input-hint {
  margin: 6px 0 0;
  font-size: 11px;
  color: #5a7399;
}

/* ---- 响应式 ---- */
@media (max-width: 768px) {
  .chat-sidebar {
    width: 200px;
    min-width: 200px;
  }

  .chat-messages {
    padding: 12px 16px;
  }

  .chat-input-area {
    padding: 12px 16px 8px;
  }

  .media-image {
    max-width: 280px;
  }

  .media-video {
    max-width: 320px;
  }
}
</style>
