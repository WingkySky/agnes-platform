<!-- =====================================================
     视频生成视图 VideoView（已接入全局任务队列 Store）
     模式：
       - 文生视频 (text2video)
       - 图生视频 (image2video)
       - 关键帧动画 (keyframes)
     特性：
       - 任务提交到全局 Store（切换 tab 不丢失状态）
       - 轮询由 Store 统一管理（每个任务独立轮询）
       - 结果从 Store 读取，刷新持久化
     ===================================================== -->

<template>
  <div class="video-view">
    <h2 class="page-title">🎬 视频生成</h2>
    <p class="page-desc">
      根据文字描述或参考图生成短视频。通常需要 2-5 分钟完成，可点击右下「队列」查看所有任务状态。</p>

    <el-row :gutter="24">
      <!-- 左侧：参数 -->
      <el-col :xs="24" :md="11">
        <el-card shadow="never">
          <template #header>
          <div class="card-header"><span>生成参数</span></div>
          </template>

          <!-- 模式切换 -->
          <el-tabs v-model="mode">
              <el-tab-pane label="📝 文生视频" name="text2video">
                <span class="tab-sub">仅提示词</span>
              </el-tab-pane>
              <el-tab-pane label="🖼 图生视频" name="image2video">
                <span class="tab-sub">参考图 + 提示词</span>
              </el-tab-pane>
              <el-tab-pane label="🎞 关键帧动画" name="keyframes">
                <span class="tab-sub">多张关键帧 + 提示词</span>
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

            <el-button
              v-if="!activeTask || taskDone"
              type="primary" size="large"
              class="generate-btn"
              :disabled="!canSubmit"
              @click="startGenerate">
              <el-icon><VideoPlay /></el-icon>
              <span>✨ 生成视频</span>
            </el-button>

            <el-button
              v-else
              type="danger" size="large"
              class="generate-btn"
              @click="cancelTask">
              <el-icon><CircleCloseFilled /></el-icon>
              <span>中止任务</span>
            </el-button>
          </el-form>
        </el-card>
      </el-col>

      <!-- 右侧：结果（从 Store 读取当前任务状态） -->
      <el-col :xs="24" :md="13">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>生成结果</span>
              <span v-if="videoUrl" class="header-actions">
                <el-button size="small" @click="downloadVideo">
                  <el-icon><Download /></el-icon>
                  下载
                </el-button>
              </span>
            </div>
          </template>

          <!-- 运行中（从 Store 读取） -->
          <div v-if="activeTask && taskRunning" class="result-loading">
            <el-progress
              :percentage="taskProgress"
              :stroke-width="12"
              :color="progressColor" />
            <div class="loading-text">{{ statusText }}</div>
            <div class="loading-sub">已耗时 {{ taskElapsedSec }}秒 · 队列后台持续轮询</div>
            <div v-if="activeTaskId" class="loading-sub">Task ID: {{ activeTaskId }}</div>
            <div v-if="activeTask.errorMessage" class="error-msg">{{ activeTask.errorMessage }}</div>
          </div>

          <!-- 成功（从 Store 读取） -->
          <div v-else-if="activeTask && activeTask.status === 'success'" class="result-wrap">
            <!-- 视频播放区 -->
            <div class="video-container">
              <video
                v-if="videoUrl"
                ref="videoEl"
                :src="videoUrl"
                :poster="posterUrl"
                controls
                playsinline
                preload="metadata"
                crossorigin="anonymous"
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
              <div v-if="videoLoading" class="video-loading-overlay">
                <el-icon :size="28" class="spinner"><Loading /></el-icon>
                <div>视频加载中…</div>
              </div>
              <div v-if="videoLoadFailed" class="video-error-overlay">
                <el-icon :size="28" color="#ff7b7b"><CircleCloseFilled /></el-icon>
                <div>视频播放失败，请尝试「下载」或「新标签页打开」</div>
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
              <div class="meta-row">分辨率：{{ width }}×{{ height }} · {{ numFrames }}帧 · {{ frameRate }}fps</div>
              <div class="meta-row">状态：<span class="tag-success">success</span> · 进度 {{ taskProgress }}% · 耗时 {{ taskElapsedSec }}s</div>
              <div v-if="activeTaskId" class="meta-row">Task ID：{{ activeTaskId }}</div>
              <div class="meta-row url-row">
                <span class="url-label">视频链接：</span>
                <span class="url-value">{{ videoUrl || '(空)' }}</span>
              </div>
            </div>
          </div>

          <!-- 失败（从 Store 读取） -->
          <div v-else-if="activeTask && activeTask.status === 'failed'" class="result-failed">
            <el-icon :size="48" color="#ff7b7b"><CircleCloseFilled /></el-icon>
            <div class="failed-text">视频生成失败</div>
            <div class="failed-sub">{{ activeTask.errorMessage || '请检查 API 或稍后重试' }}</div>
          </div>

          <!-- 取消（从 Store 读取） -->
          <div v-else-if="activeTask && activeTask.status === 'cancelled'" class="result-failed">
            <el-icon :size="48" color="#ffb86b"><CircleCloseFilled /></el-icon>
            <div class="failed-text">任务已取消</div>
            <div class="failed-sub">点击右下「队列」查看历史任务</div>
          </div>

          <!-- 空状态 -->
          <div v-else class="empty-state">
            <el-icon :size="48"><VideoCameraFilled /></el-icon>
            <p class="empty-text">点击左侧配置参数，开始创作你的 AI 视频</p>
            <p class="empty-sub">生成后可切换到其他页面继续创作，状态不丢失</p>
          </div>
        </el-card>

        <div class="tips-card">
          <div class="tip-title">💡 视频生成提示</div>
          <ul>
            <li>帧数越多，视频越长：9帧 = 约 0.3 秒；121帧 = 约 5 秒；441帧 = 约 18 秒</li>
            <li>建议帧率 24 或 30 fps</li>
            <li>生成过程可切换到其他页面，点击右下「队列」查看所有任务</li>
            <li>任务支持自动重试与手动取消，避免重复提交相同请求</li>
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
  VideoPlay, Download, CopyDocument, CircleCloseFilled, VideoCameraFilled, Loading
} from '@element-plus/icons-vue'
import PromptTemplates from '@/components/PromptTemplates.vue'
import ImageUploader from '@/components/ImageUploader.vue'
// ---------- 全局 Store 替换本地轮询 ----------
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

// ---------- 表单参数（保留本地） ----------
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

// ---------- 视频播放状态（保留本地） ----------
const videoEl = ref(null)
const posterUrl = ref('')
const videoLoading = ref(false)
const videoLoadFailed = ref(false)

// ---------- 使用全局 Store 管理任务 ----------
const queue = useTaskQueueStore()

// 当前在本视图中激活的任务 ID（记录上次提交的任务）
const activeTaskId = ref('')

// 计算属性：从 Store 读取对应任务
const activeTask = computed(() => {
  if (!activeTaskId.value) return null
  return queue.tasks[activeTaskId.value] || null
})

// 任务完成/失败了
const taskDone = computed(() => {
  if (!activeTask.value) return true
  return ['success', 'failed', 'cancelled'].includes(activeTask.value.status)
})

// 任务还在运行中
const taskRunning = computed(() => {
  if (!activeTask.value) return false
  return ['pending', 'queued', 'processing'].includes(activeTask.value.status)
})

// 从 Store 读取的进度和耗时
const taskProgress = computed(() => {
  if (!activeTask.value) return 0
  return Math.min(activeTask.value.progress || 0, 99)
})
const taskElapsedSec = computed(() => {
  if (!activeTask.value) return 0
  const created = activeTask.value.createdAt || 0
  if (!created) return 0
  return Math.floor((Date.now() - created) / 1000)
})

// 从 Store 读取视频 URL
const videoUrl = computed(() => {
  if (!activeTask.value) return ''
  return activeTask.value.resultUrl || activeTask.value.url || ''
})

const canSubmit = computed(() => prompt.value.trim().length > 0)
const statusText = computed(() => {
  if (!activeTask.value) return '创建任务中...'
  const s = activeTask.value.status
  if (s === 'processing') return 'AI 正在绘制视频中...'
  if (s === 'pending' || s === 'queued') return '排队中...'
  if (s === 'success') return '生成完成'
  return '任务处理中...'
})
const progressColor = '#6b9cff'

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

// ---------- 开始生成（提交到 Store，不阻塞本地） ----------
async function startGenerate() {
  if (!canSubmit.value) {
    ElMessage.warning('请先填写提示词')
    return
  }
  if (mode.value === 'image2video' && !referenceFile.value) {
    ElMessage.warning('请先上传参考图')
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
    seed: seed.value ? Number(seed.value) : undefined
  }
  if (mode.value === 'image2video' && referenceFile.value) {
    params.image = referenceFile.value.base64 || referenceFile.value.url
  }
  if (mode.value === 'keyframes') {
    const imgs = keyframes.value.filter(Boolean).map(f => f.base64 || f.url)
    if (imgs.length > 0) params.images = imgs
  }

  // 重置播放状态
  posterUrl.value = ''
  videoLoading.value = false
  videoLoadFailed.value = false

  try {
    console.log('[VideoView] 提交到任务队列，参数：', params)
    // 核心：submitVideoTask 返回 taskId，由 Store 统一管理轮询
    const taskId = await queue.submitVideoTask(params)
    activeTaskId.value = taskId
    ElMessage.success('视频任务已提交，可点击右下「队列」查看进度')
  } catch (e) {
    console.error('[VideoView] 提交任务失败：', e)
    ElMessage.error('创建视频任务失败：' + (e.message || '未知错误'))
  }
}

// ---------- 取消任务（调用 Store） ----------
function cancelTask() {
  if (!activeTaskId.value) return
  queue.cancelTask(activeTaskId.value)
  ElMessage.info('已请求中止任务')
}

// ---------- 通用工具：复制文本到剪贴板 ----------
function copyToClipboard(text) {
  if (!text) return Promise.resolve()
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text)
  }
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.left = '-9999px'
  ta.style.top = '0'
  document.body.appendChild(ta)
  ta.select()
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch (e) {
    ok = false
  }
  document.body.removeChild(ta)
  return ok ? Promise.resolve() : Promise.reject(new Error('copy failed'))
}

// ---------- 复制链接 ----------
function copyVideoUrl() {
  if (!videoUrl.value) {
    ElMessage.warning('视频链接为空')
    return
  }
  copyToClipboard(videoUrl.value)
    .then(() => ElMessage.success('视频链接已复制到剪贴板'))
    .catch(() => ElMessage.error('复制失败，请手动复制'))
}

// ---------- 下载视频 ----------
async function downloadVideo() {
  if (!videoUrl.value) {
    ElMessage.warning('视频链接为空，无法下载')
    return
  }
  try {
    ElMessage.info('正在准备下载，请稍候…')
    const response = await fetch(videoUrl.value, { mode: 'cors' })
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
    console.warn('[VideoView] fetch 下载失败，回退为新标签页打开：', err)
    ElMessage.warning('跨域下载受限，已在新标签页打开。请右键视频选择「另存为」')
    window.open(videoUrl.value, '_blank', 'noopener,noreferrer')
  }
}

// ---------- 新标签页打开 ----------
function openInNewTab() {
  if (!videoUrl.value) {
    ElMessage.warning('视频链接为空，无法打开')
    return
  }
  window.open(videoUrl.value, '_blank', 'noopener,noreferrer')
  ElMessage.success('已在新标签页打开')
}

// ---------- 视频事件处理 ----------
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
    if (posterUrl.value) return
    posterUrl.value = canvas.toDataURL('image/jpeg', 0.82)
  } catch (e) {
    console.warn('[VideoView] canvas 截图失败（可能跨域污染）：', e)
  }
}

function onVideoLoaded() {
  console.log('[VideoView] 视频元数据已加载')
}

function onVideoCanPlay() {
  console.log('[VideoView] 视频可以播放')
  videoLoading.value = false
  videoLoadFailed.value = false
}

function handleVideoError(e) {
  console.error('[VideoView] 视频加载/播放失败：', e)
  videoLoading.value = false
  videoLoadFailed.value = true
  ElMessage.error('视频加载失败，请尝试「下载」或「新标签页打开」')
}
</script>

<style scoped>
.video-view { color: #e8eef7; }
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}
.tab-sub { font-size: 12px; color: #8ba3c9; margin-left: 6px; }
.generate-btn {
  width: 100%;
  height: 48px;
  font-size: 16px;
  font-weight: 600;
  margin-top: 8px;
}
.section-title {
  font-size: 13px;
  color: #a0b4d6;
  margin: 12px 0 10px;
  font-weight: 500;
}

.result-loading {
  padding: 60px 20px;
  text-align: center;
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
.error-msg {
  margin-top: 16px;
  color: #ff9b9b;
  font-size: 13px;
}
.result-wrap { text-align: center; }

.video-container {
  position: relative;
  width: 100%;
  background: #000;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0,0,0,0.35);
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

.video-loading-overlay, .video-error-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0,0,0,0.7);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 14px;
  gap: 12px;
}
.video-error-overlay { color: #ff9b9b; }
.spinner { animation: spin 1.2s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

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
  background: rgba(15,24,42,0.4);
  border-radius: 8px;
  text-align: left;
}
.meta-row { font-size: 13px; padding: 4px 0; color: #d5e3f7; }
.tag-success {
  display: inline-block;
  padding: 2px 8px;
  background: rgba(46, 184, 128, 0.2);
  color: #2ee58c;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  margin: 0 4px;
}
.url-row {
  margin-top: 8px;
  padding: 12px !important;
  background: rgba(10, 20, 40, 0.6);
  border: 1px solid rgba(120, 170, 255, 0.15);
  border-radius: 8px;
  word-break: break-all;
}
.url-label { color: #8ba3c9; margin-right: 6px; font-weight: 500; }
.url-value { color: #d5e3f7; font-family: monospace; font-size: 12px; }

.result-failed {
  padding: 60px 20px;
  text-align: center;
  color: #ff9b9b;
}
.failed-text { margin-top: 16px; font-size: 16px; color: #ffb5b5; }
.failed-sub { font-size: 12px; color: #8ba3c9; margin-top: 6px; }

.empty-state {
  padding: 80px 20px;
  text-align: center;
  color: #6b84aa;
}
.empty-text { margin-top: 16px; font-size: 14px; }
.empty-sub { margin-top: 8px; font-size: 12px; color: #8ba3c9; }

.tips-card {
  margin-top: 16px;
  padding: 16px 20px;
  background: rgba(15, 24, 42, 0.5);
  border: 1px solid rgba(120, 170, 255, 0.15);
  border-radius: 12px;
  font-size: 13px;
  color: #a0b4d6;
}
.tips-title { font-weight: 600; color: #d5e3f7; margin-bottom: 8px; }
.tips-card ul { margin: 0; padding-left: 20px; line-height: 1.8; }
.multi-upload .el-button { margin-top: 8px; }
</style>
