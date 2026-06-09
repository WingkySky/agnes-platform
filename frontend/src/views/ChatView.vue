<!-- =====================================================
     ChatView.vue — AI 聊天界面
     功能：
     - 左侧：会话列表（新建/切换/删除）
     - 右侧：聊天消息区 + 输入框
     - 支持流式文本回复（逐字显示）
     - 支持图片/视频生成（工具调用，内嵌展示）
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
          <el-button
            class="session-delete"
            :icon="Delete"
            size="small"
            text
            @click.stop="handleDeleteSession(session.id)"
          />
        </div>

        <div v-if="chatStore.sessions.length === 0" class="session-empty">
          <p>{{ t('chat.noSessions') }}</p>
        </div>
      </div>
    </aside>

    <!-- 右侧：聊天区 -->
    <main class="chat-main">
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

      <!-- 聊天消息区 -->
      <template v-else>
        <!-- 消息列表 -->
        <div class="chat-messages" ref="messagesRef">
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
                <p>{{ msg.content }}</p>
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

                <!-- 工具调用提示 -->
                <div v-for="tc in getToolCallsForMessage(msg)" :key="tc.tool" class="tool-call-badge">
                  <el-icon v-if="tc.tool === 'generate_image'"><Picture /></el-icon>
                  <el-icon v-else-if="tc.tool === 'generate_video'"><VideoPlay /></el-icon>
                  <span>{{ tc.tool === 'generate_image' ? t('chat.generatingImage') : t('chat.generatingVideo') }}</span>
                  <el-icon v-if="tc.status === 'calling'" class="is-loading"><Loading /></el-icon>
                  <el-icon v-else-if="tc.status === 'done'" class="tool-done"><Check /></el-icon>
                </div>

                <!-- 媒体内容（图片） -->
                <div v-if="msg.media_type === 'image' && msg.media_url" class="media-container">
                  <el-image
                    :src="msg.media_url"
                    :preview-src-list="[msg.media_url]"
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
                </div>

                <!-- 媒体内容（视频） -->
                <div v-if="msg.media_type === 'video' && msg.media_url" class="media-container">
                  <video
                    :src="getVideoProxyUrl(msg.media_url, msg.media_task_id)"
                    controls
                    class="media-video"
                    @error="onVideoError"
                  >
                    {{ t('chat.videoNotSupported') }}
                  </video>
                </div>

                <!-- 媒体生成中 -->
                <div v-if="msg.media_type && msg.media_status === 'pending' && !msg.media_url" class="media-generating">
                  <el-icon class="is-loading"><Loading /></el-icon>
                  <span>{{ msg.media_type === 'image' ? t('chat.imageGenerating') : t('chat.videoGenerating') }}</span>
                </div>

                <!-- 媒体生成失败 -->
                <div v-if="msg.media_type && msg.media_status === 'failed'" class="media-failed">
                  <el-icon><WarningFilled /></el-icon>
                  <span>{{ t('chat.mediaFailed') }}</span>
                </div>
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
          <div class="input-wrapper">
            <el-input
              v-model="inputText"
              type="textarea"
              :rows="2"
              :placeholder="t('chat.inputPlaceholder')"
              :disabled="chatStore.sending"
              @keydown.enter.exact="handleEnter"
              resize="none"
            />
            <el-button
              type="primary"
              :icon="Promotion"
              :loading="chatStore.sending"
              :disabled="!inputText.trim()"
              @click="handleSend"
              class="send-btn"
            />
          </div>
          <p class="input-hint">{{ t('chat.inputHint') }}</p>
        </div>
      </template>
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch, computed } from 'vue'
import {
  Plus, Delete, User, Monitor, Picture, VideoPlay,
  Loading, Check, WarningFilled, Promotion, ChatDotRound,
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
  await chatStore.loadSessions()
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

/** 发送消息 */
async function handleSend() {
  const content = inputText.value.trim()
  if (!content || chatStore.sending) return

  inputText.value = ''
  try {
    await chatStore.sendMessage(content)
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

.session-item:hover .session-delete {
  opacity: 1;
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
