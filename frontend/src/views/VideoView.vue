<!-- =====================================================
     视频生成视图 VideoView
     模式：
       - 文生视频 (text2video)
       - 图生视频 (image2video)
       - 关键帧动画 (keyframes)
     ===================================================== -->

<template>
  <div class="video-view">
    <h2 class="page-title">🎬 视频生成</h2>
    <p class="page-desc">
      根据文字描述或参考图生成短视频。通常需要 2-5 分钟完成，请耐心等待。</p>

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
              v-if="!runningTask"
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

      <!-- 右侧：结果 -->
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

          <!-- 运行中 -->
          <div v-if="runningTask && status !== 'success' && status !== 'failed'" class="result-loading">
            <el-progress
              :percentage="progressPercent"
              :stroke-width="12"
              :color="progressColor" />
            <div class="loading-text">{{ statusText }}</div>
            <div class="loading-sub">已耗时 {{ elapsedSec }}秒 · 每 5 秒查询一次状态</div>
            <div v-if="currentTaskId" class="loading-sub">Task ID: {{ currentTaskId }}</div>
            <div v-if="errorMessage" class="error-msg">{{ errorMessage }}</div>
          </div>

          <!-- 成功（只要 status === 'success' 就显示，即使 video_url 为空也展示原始响应供排查 -->
          <div v-else-if="status === 'success'" class="result-wrap">
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
                <div class="placeholder-sub">后端返回的视频链接为空，请查看下方「原始响应」或刷新重试</div>
              </div>
              <div v-if="videoLoading" class="video-loading-overlay">
                <el-icon :size="28" class="spinner"><Loading /></el-icon>
                <div>视频加载中…</div>
              </div>
              <div v-if="videoLoadFailed" class="video-error-overlay">
                <el-icon :size="28" color="#ff7b7b"><CircleCloseFilled /></el-icon>
                <div>视频播放失败（可能是跨域/格式问题），请尝试「下载」或「新标签页打开」</div>
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
              <div class="meta-row">提示词：{{ prompt }}</div>
              <div class="meta-row">分辨率：{{ width }}×{{ height }} · {{ numFrames }}帧 · {{ frameRate }}fps</div>
              <div class="meta-row">状态：<span class="tag-success">success</span> · 进度 {{ progress }}% · 耗时 {{ elapsedSec }}s</div>
              <div v-if="currentTaskId" class="meta-row">Task ID：{{ currentTaskId }}</div>
              <div class="meta-row url-row">
                <span class="url-label">视频链接：</span>
                <span class="url-value">{{ videoUrl || '(空)' }}</span>
              </div>
            </div>

            <!-- 原始响应（折叠/调试用） -->
            <div class="debug-panel" @click="showRawDebug = !showRawDebug">
              <div class="debug-header">
                <span>🔍 原始响应（点击展开/收起）</span>
                <span class="debug-toggle">{{ showRawDebug ? '▼' : '▶' }}</span>
              </div>
              <pre v-if="showRawDebug" class="debug-content">{{ rawResponse || '(暂无)' }}</pre>
            </div>
          </div>

          <!-- 失败 -->
          <div v-else-if="status === 'failed'" class="result-failed">
            <el-icon :size="48" color="#ff7b7b"><CircleCloseFilled /></el-icon>
            <div class="failed-text">视频生成失败</div>
            <div class="failed-sub">{{ errorMessage || '请检查 API 或稍后重试' }}</div>
            <div v-if="rawResponse" class="debug-panel" @click="showRawDebug = !showRawDebug">
              <div class="debug-header"><span>🔍 原始响应</span><span class="debug-toggle">{{ showRawDebug ? '▼' : '▶' }}</span></div>
              <pre v-if="showRawDebug" class="debug-content">{{ rawResponse }}</pre>
            </div>
          </div>

          <!-- 空状态 -->
          <div v-else class="empty-state">
            <el-icon :size="48"><VideoCameraFilled /></el-icon>
            <p class="empty-text">点击左侧配置参数，开始创作你的 AI 视频</p>
          </div>
        </el-card>

        <div class="tips-card">
          <div class="tip-title">💡 视频生成提示</div>
          <ul>
            <li>帧数越多，视频越长：9帧 = 约 0.3 秒；121帧 = 约 5 秒；441帧 = 约 18 秒</li>
            <li>建议帧率 24 或 30 fps</li>
            <li>图生视频/关键帧模式下参考图需为公开可访问 URL</li>
            <li>生成过程可随时中止，但已生成部分无法恢复</li>
          </ul>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import {
  VideoPlay, Download, CopyDocument, CircleCloseFilled, VideoCameraFilled, Loading
} from '@element-plus/icons-vue'
import PromptTemplates from '@/components/PromptTemplates.vue'
import ImageUploader from '@/components/ImageUploader.vue'
import {
  createVideoTask,
  getVideoStatus,
  cancelVideoTask
} from '@/api/videos'

const VIDEO_TEMPLATES = [
  { label: '电影镜头', prompt: '，电影镜头感，缓慢平移，平滑 dolly-in，戏剧性光影' },
  { label: '慢动作', prompt: '，慢动作，细腻细节，优雅节奏' },
  { label: '手持跟拍', prompt: '，手持跟拍，真实感，纪实' },
  { label: '霓虹夜景', prompt: '，霓虹夜景，水面反光，都市感' },
  { label: '航拍', prompt: '，航拍大远景，缓慢扫镜，史诗感' },
  { label: '丝滑过渡', prompt: '，丝滑电影感过渡，电影级调色' }
]

const FRAME_OPTIONS = [9, 33, 49, 81, 121, 161, 241, 441]

// ---------- 状态 ----------
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

// 任务状态
const runningTask = ref(false)
const status = ref('')                 // pending / processing / success / failed / cancelled
const videoUrl = ref('')               // 视频 URL
const posterUrl = ref('')              // 首帧缩略图
const videoEl = ref(null)              // video 元素引用
const errorMessage = ref('')
const progress = ref(0)
const startTime = ref(0)
const elapsedSec = ref(0)
const currentTaskId = ref('')          // 当前任务 ID（调试用）
const rawResponse = ref('')            // 原始响应字符串（调试用）
const showRawDebug = ref(false)        // 是否展开调试面板
const videoLoading = ref(false)        // 视频加载中
const videoLoadFailed = ref(false)     // 视频加载失败

let pollTimer = null

const canSubmit = computed(() => prompt.value.trim().length > 0)
const statusText = computed(() => {
  if (status.value === 'processing') return 'AI 正在绘制视频中...'
  if (status.value === 'pending') return '排队中...'
  if (status.value === 'success') return '生成完成'
  return '创建任务中...'
})
const progressPercent = computed(() => Math.min(progress.value, 99))
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

// ---------- 开始生成 ----------
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

  // 重置所有状态
  runningTask.value = true
  status.value = 'pending'
  videoUrl.value = ''
  posterUrl.value = ''
  errorMessage.value = ''
  progress.value = 0
  startTime.value = Date.now()
  currentTaskId.value = ''
  rawResponse.value = ''
  videoLoading.value = false
  videoLoadFailed.value = false

  let taskId = null

  try {
    console.log('[VideoView] 开始创建视频任务，参数：', params)
    const task = await createVideoTask(params)
    console.log('[VideoView] 后端创建任务响应：', task)

    // 尝试多种字段名获取 taskId/videoId（兼容前后端不同版本
    taskId = task.task_id || task.id || task.video_id || task.videoId
    currentTaskId.value = taskId || '(未返回)'
    rawResponse.value = JSON.stringify(task, null, 2)

    if (!taskId) {
      throw new Error('后端未返回有效的 task_id，请检查「原始响应」面板')
    }

    // 轮询状态
    let pollCount = 0
    const doPoll = async () => {
      pollCount++
      try {
        const data = await getVideoStatus(taskId)
        rawResponse.value = JSON.stringify(data, null, 2)

        // 兼容多种 status 值：success / completed / done / succeeded
        const rawStatus = String(data.status || 'processing').toLowerCase()
        const isSuccess = ['success', 'completed', 'done', 'succeeded', 'finished'].includes(rawStatus)
        const isFailed = ['failed', 'error', 'cancelled', 'timeout'].includes(rawStatus)

        if (isSuccess) status.value = 'success'
        else if (isFailed) status.value = 'failed'
        else status.value = rawStatus

        // 进度：兼容数字 / 字符串 / null
        if (typeof data.progress === 'number') {
          progress.value = data.progress
        } else if (data.progress !== null && data.progress !== undefined) {
          const parsed = parseInt(String(data.progress), 10)
          progress.value = isNaN(parsed) ? 0 : parsed
        } else {
          const elapsed = (Date.now() - startTime.value) / 1000
          progress.value = Math.min(Math.floor((elapsed / 180) * 100), 85)
        }
        elapsedSec.value = Math.floor((Date.now() - startTime.value) / 1000)
        errorMessage.value = data.message || data.error || ''

        // 成功：尝试多种字段名获取视频 URL
        if (status.value === 'success') {
          const url = data.video_url
            || data.url
            || data.result_url
            || data.videoUrl
            || data.output_url
            || (data.data && (data.data.video_url || data.data.url))
            || ''
          videoUrl.value = url
          console.log('[VideoView] 任务成功，视频 URL：', url)

          // 设置视频加载状态
          if (url) {
            videoLoading.value = true
            videoLoadFailed.value = false
          }

          runningTask.value = false
          clearInterval(pollTimer)
          ElMessage.success('视频生成完成！')
          return
        }

        // 失败：显示错误信息
        if (status.value === 'failed') {
          errorMessage.value = data.message || data.error || '未知错误'
          runningTask.value = false
          clearInterval(pollTimer)
          ElMessage.error('视频生成失败：' + (errorMessage.value || '未知错误'))
          return
        }

        // 处理中：控制台记录
        if (pollCount % 6 === 0) {
          console.log(`[VideoView] 轮询 #${pollCount}：status=${status.value}, progress=${progress.value}`)
        }
      } catch (e) {
        // 单次轮询失败，记录但继续
        console.warn('[VideoView] 本次轮询失败：', e.message || e)
        // 不终止轮询，等待下一次
      }
    }
    // 启动轮询（每 5 秒一次
    pollTimer = setInterval(doPoll, 5000)
    doPoll() // 立即执行一次
  } catch (e) {
    console.error('[VideoView] 创建任务失败：', e)
    runningTask.value = false
    status.value = 'failed'
    errorMessage.value = e.message || '创建任务失败，请检查网络与 API'
    ElMessage.error('创建视频任务失败：' + errorMessage.value)
  }
}

function cancelTask() {
  if (!runningTask.value) return
  clearInterval(pollTimer)
  runningTask.value = false
  status.value = 'cancelled'
  ElMessage.info('已中止任务')
}

// ---------- 通用工具：复制文本到剪贴板（兼容非安全上下文 ----------
function copyToClipboard(text) {
  if (!text) return Promise.resolve()
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text)
  }
  // 降级方案：textarea + execCommand
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
  console.log('[VideoView] 点击复制链接，当前 videoUrl：', videoUrl.value)
  if (!videoUrl.value) {
    ElMessage.warning('视频链接为空，请先查看「原始响应」面板了解数据结构')
    return
  }
  copyToClipboard(videoUrl.value)
    .then(() => ElMessage.success('视频链接已复制到剪贴板'))
    .catch(() => ElMessage.error('复制失败，请手动选择链接文本复制'))
}

// ---------- 下载视频 ----------
async function downloadVideo() {
  console.log('[VideoView] 点击下载，URL：', videoUrl.value)
  if (!videoUrl.value) {
    ElMessage.warning('视频链接为空，无法下载')
    return
  }
  try {
    ElMessage.info('正在准备下载，请稍候…')
    const response = await fetch(videoUrl.value, { mode: 'cors' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const blob = await response.blob()
    console.log('[VideoView] fetch 成功，blob 大小：', blob.size, '字节，type：', blob.type)
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

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
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

/* 视频容器 + 状态蒙层（加载/失败 */
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

/* 操作按钮行 */
.action-row {
  display: flex;
  gap: 10px;
  margin-top: 14px;
  justify-content: center;
  flex-wrap: wrap;
}

/* 元信息 */
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

/* 调试面板 */
.debug-panel {
  margin-top: 16px;
  border: 1px dashed rgba(107, 156, 255, 0.3);
  border-radius: 8px;
  background: rgba(10, 20, 40, 0.5);
  cursor: pointer;
  text-align: left;
}
.debug-header {
  padding: 10px 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  color: #8ba3c9;
  font-weight: 500;
}
.debug-toggle { font-size: 10px; color: #6b84aa; }
.debug-content {
  margin: 0;
  padding: 12px 14px;
  border-top: 1px dashed rgba(107, 156, 255, 0.2);
  background: rgba(5, 10, 20, 0.4);
  font-family: 'Menlo', 'Consolas', monospace;
  font-size: 11px;
  color: #a0b4d6;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 300px;
  overflow-y: auto;
}

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
