<!-- =====================================================
     视频生成视图 VideoView（已接入全局任务队列 Store）
     模式：
       - 文生视频 (text2video)
       - 图生图 (image2video)
       - 关键帧动画 (keyframes)
     关键交互：
       - 左侧「生成视频」按钮始终可用（受并发数限制）
       - 提交后自动选中新任务作为预览对象
       - 右侧预览区显示「当前选中任务」（队列点击可切换）
       - 正在进行的任务可在预览区内点击「中止」
     ===================================================== -->

<template>
  <div class="video-view">
    <h2 class="page-title">🎬 视频生成</h2>
    <p class="page-desc">
      根据文字描述或参考图生成短视频。支持同时提交多个任务，点击右下「队列」可随时切换查看不同任务的状态。
    </p>

    <el-row :gutter="24">
      <!-- 左侧：参数 -->
      <el-col :xs="24" :md="11">
        <el-card shadow="never">
          <template #header>
          <div class="card-header"><span>生成参数</span></div>
          </template>

          <!-- 模式切换 -->
          <el-tabs v-model="mode">
              <el-tab-pane name="text2video">
                <template #label>
                  <span>📝 文生视频</span>
                  <span class="tab-sub">仅提示词</span>
                </template>
              </el-tab-pane>
              <el-tab-pane name="image2video">
                <template #label>
                  <span>🖼 图生视频</span>
                  <span class="tab-sub">参考图 + 提示词</span>
                </template>
              </el-tab-pane>
              <el-tab-pane name="keyframes">
                <template #label>
                  <span>🎞 关键帧动画</span>
                  <span class="tab-sub">多张关键帧 + 提示词</span>
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
            <div class="section-title">上传关键帧</div>
            <ImageUploader
              v-for="(_, idx) in keyframes"
              :key="idx"
              :optional="false"
              @change="(f) => handleKeyframeChange(idx, f)"
              @clear="() => handleKeyframeClear(idx)"
            />
            <el-button plain size="small" @click="addKeyframe">+ 再添加一张关键帧</el-button>
          </div>

          <el-form label-position="top">
            <el-form-item label="提示词">
              <el-input v-model="prompt" type="textarea" :rows="4" placeholder="描述视频内容与动态，例如：一位身穿飘逸长袍的剑客，在雨夜都市穿行，电影镜头感" maxlength="2000" show-word-limit />
            </el-form-item>

            <el-form-item label="负向提示词 (可选)">
              <el-input v-model="negativePrompt" type="textarea" :rows="2" placeholder="描述不希望出现的元素（可选）" />
            </el-form-item>

            <PromptTemplates :templates="VIDEO_TEMPLATES" @select="appendStylePrompt" />

            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="总帧数">
                  <el-select v-model="numFrames">
                    <el-option v-for="n in FRAME_OPTIONS" :key="n" :label="n + '帧'" :value="n" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="帧率 (fps)">
                  <el-input-number v-model="frameRate" :min="1" :max="60" />
                </el-form-item>
              </el-col>
            </el-row>

            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="宽度">
                  <el-input-number v-model="width" :min="512" :max="2048" :step="64" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="高度">
                  <el-input-number v-model="height" :min="512" :max="2048" :step="64" />
                </el-form-item>
              </el-col>
            </el-row>

            <el-row :gutter="16">
              <el-col :span="24">
                <el-form-item label="随机种子 (可选)">
                  <el-input v-model="seed" placeholder="留空自动生成" />
                </el-form-item>
              </el-col>
            </el-row>

            <!-- 生成按钮：始终可用（不受当前是否有进行中任务限制） -->
            <el-button
              type="primary"
              size="large"
              class="generate-btn"
              :disabled="!canSubmit"
              @click="startGenerate">
              <el-icon><VideoPlay /></el-icon>
              <span>✨ 生成视频（加入队列）</span>
            </el-button>

            <div class="queue-hint">
              当前进行中: {{ queue.runningVideoCount }} / 5 · 已提交任务: {{ queue.tasks && Object.keys(queue.tasks).length }}
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
                <span>生成结果</span>
                <span v-if="activeTask" class="task-pill" :class="'status-' + activeTask.status">
                  {{ statusLabel }}
                </span>
              </div>
              <span v-if="videoUrl" class="header-actions">
                <el-button size="small" @click="downloadVideo">
                  <el-icon><Download /></el-icon>
                  下载
                </el-button>
              </span>
            </div>
          </template>

          <!-- 情况 A：有选中任务且正在进行中 -->
          <div v-if="activeTask && taskRunning" class="result-loading">
            <div class="task-id-row">任务 ID: {{ activeTask.taskId }}</div>
            <el-progress
              :percentage="taskProgress"
              :stroke-width="12"
              :color="progressColor" />
            <div class="loading-text">{{ statusLabel }}中...</div>
            <div class="loading-sub">已耗时 {{ taskElapsedSec }} 秒</div>
            <div class="prompt-row">{{ activeTask.prompt }}</div>
            <el-button
              type="danger"
              size="small"
              class="cancel-btn-inline"
              @click="cancelActiveTask">
              <el-icon><CircleCloseFilled /></el-icon>
              中止此任务
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
              />
              <div v-else class="video-placeholder">
                <el-icon :size="48" color="#ffd166"><VideoPlay /></el-icon>
                <div class="placeholder-title">视频 URL 为空</div>
                <div class="placeholder-sub">后端返回的视频链接为空</div>
              </div>
            </div>

            <!-- 操作区 -->
            <div class="action-row">
              <el-button type="primary" size="small" @click="downloadVideo">
                <el-icon><Download /></el-icon>
                下载视频
              </el-button>
              <el-button size="small" @click="copyVideoUrl">
                <el-icon><CopyDocument /></el-icon>
                复制链接
              </el-button>
              <el-button size="small" @click="openInNewTab">
                <el-icon><VideoPlay /></el-icon>
                新标签页打开
              </el-button>
            </div>

            <!-- 元信息 -->
            <div class="result-meta">
              <div class="meta-row">提示词：{{ activeTask.prompt }}</div>
              <div class="meta-row">状态：<span class="tag-success">success</span> · 耗时 {{ taskElapsedSec }}s</div>
              <div v-if="activeTask.taskId" class="meta-row">Task ID：{{ activeTask.taskId }}</div>
            </div>
          </div>

          <!-- 情况 C：任务失败 -->
          <div v-else-if="activeTask && activeTask.status === 'failed'" class="result-failed">
            <el-icon :size="48" color="#ff7b7b"><CircleCloseFilled /></el-icon>
            <div class="failed-text">视频生成失败</div>
            <div class="failed-sub">{{ activeTask.errorMessage || '未知错误，请重试' }}</div>
            <el-button type="primary" size="small" class="retry-btn" @click="retryActiveTask">
              使用相同参数重试
            </el-button>
          </div>

          <!-- 情况 D：任务已取消 -->
          <div v-else-if="activeTask && activeTask.status === 'cancelled'" class="result-failed">
            <el-icon :size="48" color="#ffb86b"><CircleCloseFilled /></el-icon>
            <div class="failed-text">任务已取消</div>
            <div class="failed-sub">该任务已停止生成，可重新提交新任务</div>
          </div>

          <!-- 情况 E：选中的是图片任务，不匹配当前视图 -->
          <div v-else-if="activeTaskIsOtherType" class="empty-state">
            <el-icon :size="48"><MagicStick /></el-icon>
            <p class="empty-text">当前选中的是图片任务</p>
            <p class="empty-sub">请点击右下「队列」切换到视频任务，或前往图片生成页查看该任务</p>
          </div>

          <!-- 情况 F：没有选中的任务 -->
          <div v-else class="empty-state">
            <el-icon :size="48"><VideoCameraFilled /></el-icon>
            <p class="empty-text">尚未选择任务预览</p>
            <p class="empty-sub">提交新视频任务后，或点击右下「队列」中任一任务条目，此处将显示对应任务的状态和结果</p>
          </div>
        </el-card>

        <div class="tips-card">
          <div class="tip-title">💡 提示</div>
          <ul>
            <li>可同时提交多个视频任务（最多 5 个并发），无需等待当前任务完成</li>
            <li>点击右下「队列」可随时查看、切换、中止任意任务</li>
            <li>生成的视频在队列中保留约 20 分钟，超过可在「生成历史」查看</li>
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

const VIDEO_TEMPLATES = [
  { label: '电影镜头', prompt: '，电影镜头感，缓慢平移，平滑 dolly-in，戏剧性光影' },
  { label: '慢动作', prompt: '，慢动作，细腻细节，优雅节奏' },
  { label: '手持跟拍', prompt: '，手持跟拍，真实感，纪实' },
  { label: '霓虹夜景', prompt: '，霓虹夜景，水面反光，都市感' },
  { label: '航拍', prompt: '，航拍大远景，缓慢扫镜，史诗感' },
  { label: '丝滑过渡', prompt: '，丝滑电影感过渡，电影级调色' }
]

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
// （避免在视频视图中误显示图片任务）
const activeTask = computed(() => {
  if (!queue.activeTaskId) return null
  const task = queue.tasks[queue.activeTaskId]
  if (!task) return null
  return task.type === 'video' ? task : null
})

// 选中任务是否为图片类型（在视频视图中不显示预览，仅提示）
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

// 从 Store 读取的进度和耗时（通过 queue._tick 驱动每秒响应式刷新）
const taskProgress = computed(() => {
  if (!activeTask.value) return 0
  return Math.min(activeTask.value.progress || 0, 99)
})
const taskElapsedSec = computed(() => {
  if (!activeTask.value) return 0
  const created = activeTask.value.createdAt || 0
  if (!created) return 0
  // 读取 queue._tick 让此 computed 随 tick 刷新
  queue._tick
  return Math.floor((Date.now() - created) / 1000)
})

// 视频 URL：使用后端代理接口，解决 Google Storage CORS 问题
const videoUrl = computed(() => {
  if (!activeTask.value) return ''
  // 优先使用后端代理接口播放视频（通过 task_id 代理，避免 CORS）
  const backendTaskId = activeTask.value.backendTaskId || activeTask.value.taskId
  if (backendTaskId && activeTask.value.status === 'success') {
    return `/api/videos/${backendTaskId}/stream`
  }
  // 任务未完成时返回空（不使用直链）
  return ''
})

// 原始直链 URL（用于下载、复制链接等操作）
const rawVideoUrl = computed(() => {
  if (!activeTask.value) return ''
  return activeTask.value.resultUrl || activeTask.value.url || ''
})

// 状态标签（中文化）
const statusLabel = computed(() => {
  if (!activeTask.value) return ''
  const s = activeTask.value.status
  const map = {
    queued: '排队',
    pending: '等待中',
    processing: '生成',
    success: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return map[s] || s
})

const progressColor = '#6b9cff'

// 能否提交：只要提示词不为空 + 未达并发上限
const canSubmit = computed(() => {
  if (!prompt.value.trim()) return false
  if (queue.runningVideoCount >= 5) return false
  return true
})

function appendStylePrompt(t) {
  if (!prompt.value.trim().endsWith(t)) {
    prompt.value = prompt.value.trim() + t
  }
}

// ---------- 关键帧管理 ----------
function addKeyframe() {
  if (keyframes.value.length < 6) {
    keyframes.value.push(null)
  } else {
    ElMessage.warning('最多添加 6 张关键帧')
  }
}
function handleImageChange(file) {
  referenceFile.value = file
}
function handleImageClear() {
  referenceFile.value = null
}
function handleKeyframeChange(idx, file) {
  keyframes.value[idx] = file
}
function handleKeyframeClear(idx) {
  keyframes.value[idx] = null
}

// ---------- 开始生成（提交到队列，不阻塞） ----------
async function startGenerate() {
  if (!prompt.value.trim()) {
    ElMessage.warning('请先填写提示词')
    return
  }
  if (mode.value === 'image2video' && !referenceFile.value) {
    ElMessage.warning('请先上传参考图')
    return
  }
  if (queue.runningVideoCount >= 5) {
    ElMessage.warning('已达 5 个视频并发上限，请等待任务完成')
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
    params.image = referenceFile.value.base64 || referenceFile.value.url
  }
  if (mode.value === 'keyframes') {
    const imgs = keyframes.value.filter(Boolean).map(f => f.base64 || f.url)
    if (imgs.length > 0) params.images = imgs
  }

  try {
    console.log('[VideoView] 提交视频任务，参数：', params)
    const taskId = await queue.submitVideoTask(params)
    queue.setActiveTask(taskId)  // 提交后自动选中新任务 → 预览区立即显示
    ElMessage.success('视频任务已提交，可点击右下「队列」查看所有任务')
  } catch (e) {
    console.error('[VideoView] 提交任务失败：', e)
    ElMessage.error('创建视频任务失败：' + (e.message || '未知错误'))
  }
}

// ---------- 中止当前选中任务 ----------
function cancelActiveTask() {
  if (!queue.activeTaskId) return
  queue.cancelTask(queue.activeTaskId)
  ElMessage.info('已请求中止该任务')
}

// ---------- 重试当前任务 ----------
function retryActiveTask() {
  if (!activeTask.value) return
  const taskId = queue.retryTask(activeTask.value.taskId)
  if (taskId) {
    queue.setActiveTask(taskId)
    ElMessage.success('已重新提交任务')
  } else {
    ElMessage.warning('重试失败，请重新手动填写参数')
  }
}

// ---------- 下载/复制/新标签页 ----------
async function downloadVideo() {
  const url = videoUrl.value || rawVideoUrl.value
  if (!url) {
    ElMessage.warning('视频链接为空，无法下载')
    return
  }
  try {
    ElMessage.info('正在准备下载…')
    const response = await fetch(url)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const blob = await response.blob()
    const blobUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = blobUrl
    a.download = `agnes-video-${Date.now()}.mp4`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    setTimeout(() => URL.revokeObjectURL(blobUrl), 1000)
    ElMessage.success('已开始下载视频')
  } catch (err) {
    console.warn('[VideoView] fetch 下载失败：', err)
    // 回退：用原始直链在新标签页打开
    const fallbackUrl = rawVideoUrl.value || url
    ElMessage.warning('下载受限，已在新标签页打开。请右键视频选择「另存为」')
    window.open(fallbackUrl, '_blank', 'noopener,noreferrer')
  }
}

function copyVideoUrl() {
  // 复制原始直链（代理 URL 不适合分享）
  const url = rawVideoUrl.value || videoUrl.value
  if (!url) {
    ElMessage.warning('视频链接为空')
    return
  }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(url)
      .then(() => ElMessage.success('视频链接已复制'))
      .catch(() => ElMessage.error('复制失败，请手动复制'))
  } else {
    const ta = document.createElement('textarea')
    ta.value = url
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    ElMessage.success('视频链接已复制')
  }
}

function openInNewTab() {
  // 新标签页使用原始直链（直链可直接播放，不受 CORS 限制）
  const url = rawVideoUrl.value || videoUrl.value
  if (!url) {
    ElMessage.warning('视频链接为空，无法打开')
    return
  }
  window.open(url, '_blank', 'noopener,noreferrer')
  ElMessage.success('已在新标签页打开')
}

// ---------- 视频事件 ----------
function capturePoster() {
  const el = videoEl.value
  if (!el || !el.videoWidth) return
  try {
    const canvas = document.createElement('canvas')
    const scale = Math.min(1, 640 / el.videoWidth)
    canvas.width = Math.floor(el.videoWidth * scale)
    canvas.height = Math.floor(el.videoHeight * scale)
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.drawImage(el, 0, 0, canvas.width, canvas.height)
    posterUrl.value = canvas.toDataURL('image/jpeg', 0.82)
  } catch (e) {
    // 走代理后一般不会 CORS 失败，但保留兜底
    console.warn('[VideoView] canvas 截图失败：', e)
  }
}
function onVideoLoaded() { console.log('[VideoView] 视频元数据已加载') }
function onVideoCanPlay() { console.log('[VideoView] 视频可播放') }
function handleVideoError(e) {
  console.error('[VideoView] 视频播放失败：', e)
  ElMessage.error('视频加载失败，请尝试「下载」或「新标签页打开」')
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
.cancel-btn-inline {
  margin-top: 20px;
}
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
