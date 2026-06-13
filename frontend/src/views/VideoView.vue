<!-- =====================================================
     视频生成视图 VideoView（已接入全局任务队列 Store）
     模式：
       - 文生视频 (text2video)
       - 图生视频 (image2video)
       - 关键帧动画 (keyframes)
     - 所有 UI 文案通过 i18n.t() 调用实现多语言
     ===================================================== -->

<template>
  <div class="video-view">
    <h2 class="page-title">🎬 {{ t('view.videoTitle') }}</h2>
    <p class="page-desc">{{ t('view.videoDesc') }}</p>

    <el-row :gutter="24">
      <!-- 左侧：参数 -->
      <el-col :xs="24" :md="11">
        <el-card shadow="never">
          <template #header>
          <div class="card-header"><span>{{ t('params.title') }}</span></div>
          </template>

          <!-- 模式切换：三选一，图标 + 标题 + 短副标签，一眼分辨 -->
          <el-tabs v-model="mode" class="mode-tabs">
              <el-tab-pane name="text2video">
                <template #label>
                  <span class="mode-label">
                    <span class="mode-icon">✍️</span>
                    <span class="mode-text">
                      <span class="mode-title">{{ t('params.mode.text2video') }}</span>
                      <span class="mode-sub">{{ t('params.mode.textOnly') }}</span>
                    </span>
                  </span>
                </template>
              </el-tab-pane>
              <el-tab-pane name="image2video">
                <template #label>
                  <span class="mode-label">
                    <span class="mode-icon">🖼</span>
                    <span class="mode-text">
                      <span class="mode-title">{{ t('params.mode.image2video') }}</span>
                      <span class="mode-sub">{{ t('params.mode.imageOnly') }}</span>
                    </span>
                  </span>
                </template>
              </el-tab-pane>
              <el-tab-pane name="keyframes">
                <template #label>
                  <span class="mode-label">
                    <span class="mode-icon">🎞️</span>
                    <span class="mode-text">
                      <span class="mode-title">{{ t('params.mode.keyframes') }}</span>
                      <span class="mode-sub">{{ t('params.mode.keyframesHint') }}</span>
                    </span>
                  </span>
                </template>
              </el-tab-pane>
          </el-tabs>

          <!-- 单图上传 -->
          <ImageUploader
            v-if="mode === 'image2video'"
            @change="handleImageChange"
            @clear="handleImageClear"
          />

          <!-- 多图上传 -->
          <div v-if="mode === 'keyframes'" class="multi-upload">
            <div class="section-title">{{ t('params.uploadKeyframes') }}</div>
            <ImageUploader
              v-for="(_, idx) in keyframes"
              :key="idx"
              :optional="false"
              @change="(f) => handleKeyframeChange(idx, f)"
              @clear="() => handleKeyframeClear(idx)"
            />
            <el-button plain size="small" @click="addKeyframe">
              {{ t('params.addKeyframe') }}
            </el-button>
          </div>

          <el-form label-position="top">
            <el-form-item :label="t('params.prompt')">
              <el-input v-model="prompt" type="textarea" :rows="4"
                :placeholder="t('params.videoPromptPlaceholder')" maxlength="2000" show-word-limit />
            </el-form-item>

            <el-form-item :label="t('params.negativePrompt')">
              <el-input v-model="negativePrompt" type="textarea" :rows="2"
                :placeholder="t('params.negativePromptPlaceholder')" />
            </el-form-item>

            <PromptTemplates :templates="videoTemplates" @select="appendStylePrompt" />

            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item :label="t('params.totalFrames')">
                  <el-select v-model="numFrames">
                    <el-option v-for="n in FRAME_OPTIONS" :key="n" :label="n + ' ' + t('params.framesUnit')" :value="n" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item :label="t('params.frameRate')">
                  <el-input-number v-model="frameRate" :min="1" :max="60" />
                </el-form-item>
              </el-col>
            </el-row>

            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item :label="t('params.width')">
                  <el-input-number v-model="width" :min="512" :max="2048" :step="64" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item :label="t('params.height')">
                  <el-input-number v-model="height" :min="512" :max="2048" :step="64" />
                </el-form-item>
              </el-col>
            </el-row>

            <el-row :gutter="16">
              <el-col :span="24">
                <el-form-item :label="t('params.randomSeed')">
                  <el-input v-model="seed" :placeholder="t('params.seedPlaceholder')" />
                </el-form-item>
              </el-col>
            </el-row>

            <!-- 生成按钮 -->
            <el-button
              type="primary"
              size="large"
              class="generate-btn"
              :disabled="!canSubmit"
              @click="startGenerate">
              <el-icon><VideoPlay /></el-icon>
              <span>{{ t('generate.videoBtn') }}</span>
            </el-button>

            <div class="queue-hint">
              {{ t('generate.running') }}: {{ queue.runningVideoCount }} / 5 · {{ t('generate.submitted') }}: {{ queue.tasks && Object.keys(queue.tasks).length }}
            </div>
          </el-form>
        </el-card>
      </el-col>

      <!-- 右侧：预览/结果区（显示 "当前选中任务" 的状态） -->
      <el-col :xs="24" :md="13">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <div class="header-title">
                <span>{{ t('preview.resultTitle') }}</span>
                <span v-if="activeTask" class="task-pill" :class="'status-' + activeTask.status">
                  {{ statusLabel }}
                </span>
              </div>
              <span v-if="videoUrl" class="header-actions">
                <el-button size="small" @click="downloadVideo">
                  <el-icon><Download /></el-icon>
                  {{ t('preview.download') }}
                </el-button>
              </span>
            </div>
          </template>

          <!-- 情况 A：有选中任务且正在进行中 -->
          <div v-if="activeTask && taskRunning" class="result-loading">
            <div class="task-id-row">{{ t('status.taskId') }}: {{ activeTask.taskId }}</div>
            <el-progress
              :percentage="taskProgress"
              :stroke-width="12"
              :color="progressColor" />
            <div class="loading-text">{{ statusLabel }} ...</div>
            <div class="loading-sub">{{ t('status.elapsedSeconds') }} {{ taskElapsedSec }} {{ t('common.seconds') }}</div>
            <div class="prompt-row">{{ activeTask.prompt }}</div>
            <el-button
              type="danger"
              size="small"
              class="cancel-btn-inline"
              @click="cancelActiveTask">
              <el-icon><CircleCloseFilled /></el-icon>
              {{ t('status.cancelTask') }}
            </el-button>
          </div>

          <!-- 情况 B：有选中任务且已成功 -->
          <div v-else-if="activeTask && activeTask.status === 'success'" class="result-wrap">
            <div class="video-container">
              <video
                v-if="videoUrl"
                ref="videoEl"
                :src="videoUrl"
                :poster="posterUrl"
                controls
                playsinline
                preload="metadata"
                class="result-video"
                @loadeddata="capturePoster"
                @loadedmetadata="onVideoLoaded"
                @error="handleVideoError"
                @canplay="onVideoCanPlay"
              ></video>
              <div v-else class="video-placeholder">
                <el-icon :size="48" color="#ffd166"><VideoPlay /></el-icon>
                <div class="placeholder-title">{{ t('preview.videoUrlEmptyTitle') }}</div>
                <div class="placeholder-sub">{{ t('preview.videoEmpty') }}</div>
              </div>
            </div>

            <!-- 操作区 -->
            <div class="action-row">
              <el-button type="primary" size="small" @click="downloadVideo">
                <el-icon><Download /></el-icon>
                {{ t('preview.download') }}
              </el-button>
              <el-button size="small" @click="copyVideoUrl">
                <el-icon><CopyDocument /></el-icon>
                {{ t('preview.copyLink') }}
              </el-button>
              <el-button size="small" @click="openInNewTab">
                <el-icon><VideoPlay /></el-icon>
                {{ t('preview.openNewTab') }}
              </el-button>
            </div>

            <!-- 元信息 -->
            <div class="result-meta">
              <div class="meta-row">{{ t('params.prompt') }}: {{ activeTask.prompt }}</div>
              <div class="meta-row">{{ t('status.label') }}: <span class="tag-success">{{ t('status.success') }}</span> · {{ t('status.elapsedSeconds') }} {{ taskElapsedSec }} {{ t('common.seconds') }}</div>
              <div v-if="activeTask.taskId" class="meta-row">{{ t('status.taskId') }}: {{ activeTask.taskId }}</div>
            </div>
          </div>

          <!-- 情况 C：任务失败 -->
          <div v-else-if="activeTask && activeTask.status === 'failed'" class="result-failed">
            <el-icon :size="48" color="#ff7b7b"><CircleCloseFilled /></el-icon>
            <div class="failed-text">{{ t('status.videoGenerateFailed') }}</div>
            <div class="failed-sub">{{ activeTask.errorMessage || '' }}</div>
            <el-button type="primary" size="small" class="retry-btn" @click="retryActiveTask">
              {{ t('status.retryWithSame') }}
            </el-button>
          </div>

          <!-- 情况 D：任务已取消 -->
          <div v-else-if="activeTask && activeTask.status === 'cancelled'" class="result-failed">
            <el-icon :size="48" color="#ffb86b"><CircleCloseFilled /></el-icon>
            <div class="failed-text">{{ t('status.cancelled') }}</div>
            <div class="failed-sub">{{ t('preview.wrongTypeHint') }}</div>
          </div>

          <!-- 情况 E：选中的是图片任务，不匹配当前视图 -->
          <div v-else-if="activeTaskIsOtherType" class="empty-state">
            <el-icon :size="48"><MagicStick /></el-icon>
            <p class="empty-text">{{ t('preview.wrongTypeVideo') }}</p>
            <p class="empty-sub">{{ t('preview.switchPageHint') }}</p>
          </div>

          <!-- 情况 F：没有选中的任务 -->
          <div v-else class="empty-state">
            <el-icon :size="48"><VideoCameraFilled /></el-icon>
            <p class="empty-text">{{ t('preview.notSelectable') }}</p>
            <p class="empty-sub">{{ t('preview.emptyHint') }}</p>
          </div>
        </el-card>

        <div class="tips-card">
          <div class="tip-title">{{ t('tips.title') }}</div>
          <ul>
            <li>{{ t('tips.concurrentVideo') }}</li>
            <li>{{ t('tips.queueSwitch') }}</li>
            <li>{{ t('tips.historyKeep') }}</li>
          </ul>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import {
  VideoPlay, Download, CopyDocument, CircleCloseFilled, VideoCameraFilled, Loading, MagicStick
} from '@element-plus/icons-vue'
import PromptTemplates from '@/components/PromptTemplates.vue'
import ImageUploader from '@/components/ImageUploader.vue'
import { useTaskQueueStore } from '@/stores/taskQueue'
import { useI18n } from '@/i18n'

const { t } = useI18n()

const videoTemplates = computed(() => ([
  { label: t('presets.cinematicShot'), prompt: '，电影镜头感，缓慢平移，平滑 dolly-in，戏剧性光影' },
  { label: t('presets.slowMotion'), prompt: '，慢动作，细腻细节，优雅节奏' },
  { label: t('presets.handheldFollow'), prompt: '，手持跟拍，真实感，纪实' },
  { label: t('presets.neonNight'), prompt: '，霓虹夜景，水面反光，都市感' },
  { label: t('presets.aerialShot'), prompt: '，航拍大远景，缓慢扫镜，史诗感' },
  { label: t('presets.smoothTransition'), prompt: '，丝滑电影感过渡，电影级调色' }
]))

const FRAME_OPTIONS = [9, 33, 49, 81, 121, 161, 241, 441]

// ---------- 表单参数 ----------
const mode = ref('text2video')
const prompt = ref('')
const negativePrompt = ref('')
const numFrames = ref(121)
const frameRate = ref(24)
const width = ref(1152)
const height = ref(768)
const seed = ref('')
const referenceFile = ref(null)
const keyframes = ref([null])

// ---------- 视频播放状态 ----------
const videoEl = ref(null)
const posterUrl = ref('')

// ---------- 使用全局 Store 管理任务 ----------
const queue = useTaskQueueStore()

// 当前预览的任务 = Store 中的 activeTask，但仅当其是视频类型
const activeTask = computed(() => {
  if (!queue.activeTaskId) return null
  const task = queue.tasks[queue.activeTaskId]
  if (!task) return null
  return task.type === 'video' ? task : null
})

// 选中任务是否为图片类型
const activeTaskIsOtherType = computed(() => {
  if (!queue.activeTaskId) return false
  const task = queue.tasks[queue.activeTaskId]
  return task && task.type !== 'video'
})

// 选中任务是否正在进行中
const taskRunning = computed(() => {
  if (!activeTask.value) return false
  return ['pending', 'queued', 'processing'].includes(activeTask.value.status)
})

// 进度、耗时
const taskProgress = computed(() => {
  if (!activeTask.value) return 0
  return Math.min(activeTask.value.progress || 0, 99)
})
const taskElapsedSec = computed(() => {
  if (!activeTask.value) return 0
  const created = activeTask.value.createdAt || 0
  if (!created) return 0
  queue._tick
  return Math.floor((Date.now() - created) / 1000)
})

// 视频 URL：代理地址
const videoUrl = computed(() => {
  if (!activeTask.value) return ''
  const backendTaskId = activeTask.value.backendTaskId || activeTask.value.taskId
  const status = activeTask.value.status
  if (backendTaskId && status === 'success') {
    const proxyUrl = `/api/videos/${backendTaskId}/stream`
    return proxyUrl
  }
  return ''
})

// 原始直链 URL（下载、复制链接）
const rawVideoUrl = computed(() => {
  if (!activeTask.value) return ''
  return activeTask.value.resultUrl || activeTask.value.url || ''
})

// 状态标签（使用 i18n 显示本地化名称）
const statusLabel = computed(() => {
  if (!activeTask.value) return ''
  const s = activeTask.value.status
  const key = `status.${s}`
  const localized = t(key)
  return localized === key ? s : localized
})

const progressColor = '#6b9cff'

// 能否提交
const canSubmit = computed(() => {
  if (!prompt.value.trim()) return false
  if (queue.runningVideoCount >= 5) return false
  return true
})

function appendStylePrompt(tpl) {
  if (!prompt.value.trim().endsWith(tpl)) {
    prompt.value = prompt.value.trim() + tpl
  }
}

// ---------- 关键帧管理 ----------
function addKeyframe() {
  if (keyframes.value.length < 6) {
    keyframes.value.push(null)
  } else {
    ElMessage.warning(t('message.maxKeyframes'))
  }
}
function handleImageChange(files) {
  if (!files || !files.length) {
    referenceFile.value = null
    return
  }
  // ImageUploader emit 的是数组，image2video 只需取第一张
  referenceFile.value = files[0]
}
function handleImageClear() {
  referenceFile.value = null
}
function handleKeyframeChange(idx, files) {
  if (!files || !files.length) {
    keyframes.value[idx] = null
    return
  }
  // ImageUploader emit 的是数组，取第一张
  keyframes.value[idx] = files[0]
}
function handleKeyframeClear(idx) {
  keyframes.value[idx] = null
}

// ---------- 开始生成 ----------
async function startGenerate() {
  if (!prompt.value.trim()) {
    ElMessage.warning(t('message.pleaseFillPrompt'))
    return
  }
  if (mode.value === 'image2video' && !referenceFile.value) {
    ElMessage.warning(t('message.pleaseUploadRefImage'))
    return
  }
  if (queue.runningVideoCount >= 5) {
    ElMessage.warning(t('generate.concurrentVideoLimit'))
    return
  }

  const params = {
    prompt: prompt.value.trim(),
    negative_prompt: negativePrompt.value.trim() || undefined,
    model: 'agnes-video-v2.0',
    num_frames: numFrames.value,
    frame_rate: frameRate.value,
    width: width.value,
    height: height.value,
    mode: mode.value,
    seed: seed.value ? Number(seed.value) : undefined,
  }
  if (mode.value === 'image2video' && referenceFile.value) {
    // 优先使用 previewUrl（完整 Data URI，含前缀），避免后端手动补 base64 padding
    // fallback 到 base64 或 url
    params.image = referenceFile.value.previewUrl || referenceFile.value.base64 || referenceFile.value.url
  }
  if (mode.value === 'keyframes') {
    // 关键帧动画：过滤空卡片和无效图片，确保仅保留有效 base64/URL
    // 问题场景：用户添加了多个卡片但某些卡片没上传图片
    const imgs = keyframes.value
      .filter(Boolean)                              // 过滤 null/undefined 空卡片
      .map(f => (f.previewUrl || f.base64 || f.url || '').trim()) // 优先用完整 Data URI
      .filter(img => img.length > 0)               // 过滤空字符串
    if (imgs.length === 0) {
      ElMessage.warning(t('message.pleaseUploadKeyframeImages'))
      return
    }
    params.images = imgs
  }

  try {
    const taskId = await queue.submitVideoTask(params)
    queue.setActiveTask(taskId)
    ElMessage.success(t('generate.videoSubmitted'))
  } catch (e) {
    console.error('[VideoView] 提交任务失败：', e)
    ElMessage.error(t('generate.createTaskFailed') + (e.message || ''))
  }
}

// ---------- 中止/重试 ----------
function cancelActiveTask() {
  if (!queue.activeTaskId) return
  queue.cancelTask(queue.activeTaskId)
  ElMessage.info(t('status.taskCancelled'))
}

function retryActiveTask() {
  if (!activeTask.value) return
  const taskId = queue.retryTask(activeTask.value.taskId)
  if (taskId) {
    queue.setActiveTask(taskId)
    ElMessage.success(t('status.taskResubmitted'))
  } else {
    ElMessage.warning(t('status.retryFailed'))
  }
}

// ---------- 下载 / 复制 / 新标签页 ----------
async function downloadVideo() {
  const url = rawVideoUrl.value || videoUrl.value
  if (!url) {
    ElMessage.warning(t('preview.videoEmpty'))
    return
  }
  try {
    // 通过后端代理下载，设置 Content-Disposition: attachment 强制浏览器保存文件
    const baseURL = import.meta.env.VITE_API_BASE_URL || ''
    const downloadUrl = `${baseURL}/api/download?url=${encodeURIComponent(url)}&type=video`
    const a = document.createElement('a')
    a.href = downloadUrl
    a.download = ''  // 让后端 Content-Disposition 控制文件名
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    ElMessage.success(t('preview.download'))
  } catch (err) {
    console.warn('[VideoView] 下载失败：', err)
    ElMessage.warning(t('preview.videoCorsWarning'))
  }
}

function copyVideoUrl() {
  const url = rawVideoUrl.value || videoUrl.value
  if (!url) {
    ElMessage.warning(t('preview.imageUrlEmpty'))
    return
  }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(url)
      .then(() => ElMessage.success(t('preview.copySuccess')))
      .catch(() => ElMessage.error(t('preview.copyFailed')))
  } else {
    const ta = document.createElement('textarea')
    ta.value = url
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    ElMessage.success(t('preview.copySuccess'))
  }
}

function openInNewTab() {
  const url = rawVideoUrl.value || videoUrl.value
  if (!url) {
    ElMessage.warning(t('preview.videoEmpty'))
    return
  }
  window.open(url, '_blank', 'noopener,noreferrer')
  ElMessage.success(t('preview.openNewTab'))
}

// ---------- 视频事件 ----------
function capturePoster() {
  const el = videoEl.value
  if (!el || !el.videoWidth) return
  try {
    const canvas = document.createElement('canvas')
    const scale = Math.min(1, 720 / el.videoWidth)
    canvas.width = Math.floor(el.videoWidth * scale)
    canvas.height = Math.floor(el.videoHeight * scale)
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.drawImage(el, 0, 0, canvas.width, canvas.height)
    posterUrl.value = canvas.toDataURL('image/jpeg', 0.82)
  } catch (e) {
    console.warn('[VideoView] canvas 截图失败：', e)
  }
}
function onVideoLoaded() { }
function onVideoCanPlay() { }
function handleVideoError(e) {
  console.error('[VideoView] 视频播放失败：', e)
  ElMessage.error(t('preview.videoLoadFailed'))
}
</script>

<style scoped>
.video-view { color: #e8eef7; }
.page-title { margin: 0 0 4px 0; }
.page-desc { color: #8ba3c9; font-size: 14px; margin-bottom: 20px; line-height: 1.6; }
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}
.header-title {
  display: flex;
  align-items: center;
  gap: 10px;
}
.task-pill {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 500;
}
.task-pill.status-queued,
.task-pill.status-pending,
.task-pill.status-processing {
  background: rgba(107, 156, 255, 0.2);
  color: #8ba3c9;
}
.task-pill.status-success {
  background: rgba(46, 184, 128, 0.2);
  color: #2ee58c;
}
.task-pill.status-failed {
  background: rgba(255, 123, 123, 0.2);
  color: #ff9b9b;
}
.task-pill.status-cancelled {
  background: rgba(255, 184, 107, 0.2);
  color: #ffb86b;
}
.tab-sub { font-size: 12px; color: #8ba3c9; margin-left: 6px; }
/* 模式切换：图标 + 标题 + 短副标签，三行结构，让三个功能一眼可辨 */
.mode-tabs :deep(.el-tabs__nav) {
  width: 100%;
  display: flex;
  justify-content: space-between;
  border-bottom: 1px solid rgba(107, 126, 156, 0.2);
}
.mode-tabs :deep(.el-tabs__item) {
  flex: 1;
  min-width: 0;
  text-align: center;
  padding: 14px 16px;
  height: auto;
  line-height: 1.4;
}
.mode-tabs :deep(.el-tabs__active-bar) {
  height: 3px;
  background: linear-gradient(90deg, #6b9cff, #8bb0ff);
  border-radius: 3px 3px 0 0;
}
.mode-tabs .mode-label {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
}
.mode-tabs .mode-icon {
  font-size: 22px;
  flex-shrink: 0;
}
.mode-tabs .mode-text {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  text-align: left;
  line-height: 1.3;
}
.mode-tabs .mode-title {
  font-size: 15px;
  font-weight: 600;
  color: #d5e3f7;
  white-space: nowrap;
}
.mode-tabs :deep(.is-active) .mode-title,
.mode-tabs :deep(.is-active) .mode-icon {
  color: #8bb0ff;
}
.mode-tabs .mode-sub {
  font-size: 12px;
  color: #8ba3c9;
  margin-top: 2px;
  white-space: nowrap;
}
.generate-btn {
  width: 100%;
  height: 48px;
  font-size: 16px;
  font-weight: 600;
  margin-top: 8px;
}
.queue-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #8ba3c9;
  text-align: center;
}
.section-title {
  font-size: 13px;
  color: #a0b4d6;
  margin: 12px 0 10px;
  font-weight: 500;
}

/* 结果区 */
.result-loading {
  padding: 50px 20px;
  text-align: center;
}
.task-id-row {
  font-size: 12px;
  color: #6b84aa;
  margin-bottom: 16px;
  font-family: monospace;
}
.loading-text {
  margin-top: 16px;
  font-size: 16px;
  color: #d5e3f7;
}
.loading-sub {
  margin-top: 6px;
  font-size: 12px;
  color: #8ba3c9;
}
.prompt-row {
  margin-top: 16px;
  padding: 10px 14px;
  background: rgba(15, 24, 42, 0.4);
  border-radius: 8px;
  font-size: 13px;
  color: #a0b4d6;
  text-align: left;
  word-break: break-word;
  max-height: 80px;
  overflow: auto;
}
.cancel-btn-inline { margin-top: 20px; }
.result-wrap { text-align: center; }

.video-container {
  position: relative;
  width: 100%;
  background: #000;
  border-radius: 12px;
  overflow: hidden;
}
.video-placeholder {
  padding: 60px 20px;
  text-align: center;
  color: #ffd166;
  background: linear-gradient(135deg, #2a1a0a 0%, #1a1a2e 100%);
  border-radius: 12px;
}
.placeholder-title { margin-top: 16px; font-size: 16px; font-weight: 600; }
.placeholder-sub { margin-top: 8px; font-size: 13px; color: #8ba3c9; }

.result-video {
  width: 100%;
  max-height: 500px;
  border-radius: 12px;
  background: #000;
  display: block;
}

.action-row {
  display: flex;
  gap: 10px;
  margin-top: 14px;
  justify-content: center;
  flex-wrap: wrap;
}

.result-meta {
  margin-top: 16px;
  padding: 12px;
  background: rgba(15, 24, 42, 0.4);
  border-radius: 8px;
  text-align: left;
}
.meta-row { font-size: 13px; padding: 4px 0; color: #d5e3f7; word-break: break-word; }
.tag-success {
  display: inline-block;
  padding: 2px 8px;
  background: rgba(46, 184, 128, 0.2);
  color: #2ee58c;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.result-failed {
  padding: 60px 20px;
  text-align: center;
  color: #ff9b9b;
}
.failed-text { margin-top: 16px; font-size: 16px; color: #ffb5b5; }
.failed-sub { font-size: 12px; color: #8ba3c9; margin-top: 6px; }
.retry-btn { margin-top: 20px; }

.empty-state {
  padding: 80px 20px;
  text-align: center;
  color: #6b84aa;
}
.empty-text { margin-top: 16px; font-size: 14px; }
.empty-sub { margin-top: 8px; font-size: 12px; color: #8ba3c9; line-height: 1.6; }

.tips-card {
  margin-top: 16px;
  padding: 16px 20px;
  background: rgba(15, 24, 42, 0.5);
  border: 1px solid rgba(120, 170, 255, 0.15);
  border-radius: 12px;
  font-size: 13px;
  color: #a0b4d6;
}
.tip-title { font-weight: 600; color: #d5e3f7; margin-bottom: 8px; }
.tips-card ul { margin: 0; padding-left: 20px; line-height: 1.8; }
.multi-upload .el-button { margin-top: 8px; }
</style>
