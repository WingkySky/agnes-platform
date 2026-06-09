<!-- =====================================================
     图片生成视图 ImageView（已接入全局任务队列 Store）
     模式：
       - 文生图 (text2image)
       - 图生图 (image2image)
     关键交互：
       - 左侧「生成图片」按钮始终可用（受并发数限制）
       - 提交后自动选中新任务作为预览对象
       - 右侧预览区显示「当前选中任务」（队列点击可切换）
       - 正在进行的任务可在预览区内点击「中止」
     ===================================================== -->

<template>
  <div class="image-view">
    <h2 class="page-title">🎨 图片生成</h2>
    <p class="page-desc">
      根据文字描述或参考图生成 AI 图片。支持同时提交多个任务，点击右下「队列」可随时切换查看不同任务的状态。
    </p>

    <el-row :gutter="24">
      <!-- 左侧：参数区 -->
      <el-col :xs="24" :md="11">
        <el-card shadow="never">
          <template #header>
          <div class="card-header">
            <span>生成参数</span>
          </div>
          </template>

          <!-- 模式切换 -->
          <el-tabs v-model="mode" class="mode-tabs">
              <el-tab-pane name="text2image">
                <template #label>
                  <span>📝 文生图</span>
                  <span class="tab-sub">仅输入提示词，AI 从零生成图片</span>
                </template>
              </el-tab-pane>
              <el-tab-pane name="image2image">
                <template #label>
                  <span>🖼 图生图</span>
                  <span class="tab-sub">上传参考图 + 提示词，AI 基于参考图创作</span>
                </template>
              </el-tab-pane>
          </el-tabs>

          <!-- 图生图时的上传区 -->
          <ImageUploader
            v-if="mode === 'image2image'"
            :optional="false"
            @change="handleImageChange"
            @clear="handleImageClear"
          />

          <!-- Prompt 输入 -->
          <el-form label-position="top" class="param-form">
            <el-form-item label="提示词 (Prompt)">
              <el-input
              v-model="prompt"
              type="textarea"
              :rows="4"
              placeholder="请输入图片描述，例如：一只坐在月球上的小猫，超现实主义风格，高细节"
              maxlength="2000"
              show-word-limit
            />
            </el-form-item>

            <!-- 预设风格 -->
            <PromptTemplates
              :templates="IMAGE_TEMPLATES"
              @select="appendStylePrompt"
            />

            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="尺寸">
                  <el-select v-model="size">
                    <el-option v-for="s in IMAGE_SIZES" :key="s" :label="s" :value="s" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="模型">
                  <el-select v-model="model">
                    <el-option v-for="m in IMAGE_MODELS" :key="m" :label="m" :value="m" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>

            <!-- 生成按钮：始终可用（受并发数限制） -->
            <el-button
              type="primary"
              size="large"
              class="generate-btn"
              :disabled="!canSubmit"
              @click="handleGenerate">
              <el-icon><MagicStick /></el-icon>
              <span>✨ 生成图片（加入队列）</span>
            </el-button>

            <div class="queue-hint">
              当前进行中: {{ queue.runningImageCount }} / 5 · 已提交任务: {{ taskCount }}
            </div>
          </el-form>
        </el-card>
      </el-col>

      <!-- 右侧：预览/结果区（显示 "当前选中任务"） -->
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
            <span v-if="resultUrl" class="header-actions">
              <el-button size="small" @click="downloadImage">
              <el-icon><Download /></el-icon>
              下载
              </el-button>
              <el-button size="small" type="primary" link @click="copyImageUrl">
              <el-icon><Link /></el-icon>
              复制链接
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
            <img v-if="resultUrl" :src="resultUrl" class="result-img" alt="generated" />
            <img v-else-if="activeTask.imageB64" :src="'data:image/png;base64,' + activeTask.imageB64" class="result-img" />
            <div class="result-meta">
              <div class="meta-row">
              <span class="meta-label">提示词：</span>
              <span class="meta-value">{{ activeTask.prompt }}</span>
              </div>
              <div class="meta-row">
              <span class="meta-label">尺寸：</span>
              <span class="meta-value">{{ size }}</span>
              </div>
            </div>
          </div>

          <!-- 情况 C：任务失败 -->
          <div v-else-if="activeTask && activeTask.status === 'failed'" class="result-failed">
            <el-icon :size="48" color="#ff7b7b"><CircleCloseFilled /></el-icon>
            <div class="failed-text">图片生成失败</div>
            <div class="failed-sub">{{ activeTask.errorMessage || '未知错误，请重试' }}</div>
            <el-button type="primary" size="small" class="retry-btn" @click="retryActiveTask">
              使用相同参数重试
            </el-button>
          </div>

          <!-- 情况 D：已取消 -->
          <div v-else-if="activeTask && activeTask.status === 'cancelled'" class="result-failed">
            <el-icon :size="48" color="#ffb86b"><CircleCloseFilled /></el-icon>
            <div class="failed-text">任务已取消</div>
            <div class="failed-sub">该任务已停止，可重新提交新任务</div>
          </div>

          <!-- 情况 E：选中的是视频任务，不匹配当前视图 -->
          <div v-else-if="activeTaskIsOtherType" class="empty-state">
            <el-icon :size="48"><VideoPlay /></el-icon>
            <p class="empty-text">当前选中的是视频任务</p>
            <p class="empty-sub">请点击右下「队列」切换到图片任务，或前往视频生成页查看该任务</p>
          </div>

          <!-- 情况 F：没有选中的任务 -->
          <div v-else class="empty-state">
            <el-icon :size="48"><PictureFilled /></el-icon>
            <p class="empty-text">尚未选择任务预览</p>
            <p class="empty-sub">提交新图片任务后，或点击右下「队列」中任一任务条目，此处将显示对应任务的状态和结果</p>
          </div>
        </el-card>

        <!-- 使用技巧 -->
        <div class="tips-card">
          <div class="tip-title">💡 使用技巧</div>
          <ul>
            <li>可同时提交多个图片任务（最多 5 个并发），无需等待当前任务完成</li>
            <li>点击右下「队列」可随时查看、切换、中止任意任务</li>
            <li>任务完成后在队列中保留约 20 分钟，超过可在「生成历史」查看</li>
          </ul>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  MagicStick, Download, Link, PictureFilled, Loading, CircleCloseFilled, VideoPlay
} from '@element-plus/icons-vue'
import PromptTemplates from '@/components/PromptTemplates.vue'
import ImageUploader from '@/components/ImageUploader.vue'
import { useTaskQueueStore } from '@/stores/taskQueue'

const IMAGE_TEMPLATES = [
  { label: '超现实主义', prompt: '，超现实主义风格，梦幻，高细节' },
  { label: '电影感', prompt: '，电影感，戏剧性光照，宽银幕' },
  { label: '动漫风格', prompt: '，日式动漫风格，鲜艳色彩，细腻线条' },
  { label: '油画风格', prompt: '，古典油画风格，厚重笔触，文艺复兴质感' },
  { label: '写实摄影', prompt: '，专业摄影，8K 超高清，自然光照' },
  { label: '赛博朋克', prompt: '，赛博朋克，霓虹光，未来都市感' },
  { label: '水墨风格', prompt: '，中国水墨风格，留白艺术，意境悠远' },
]

const IMAGE_SIZES = [
  '1024x1024',
  '1280x720',
  '720x1280',
  '1536x1024',
  '1024x1536',
  '1792x1024',
  '1024x1792',
]

const IMAGE_MODELS = [
  'agnes-image-2.1-flash',
  'agnes-image-2.1-pro',
  'agnes-image-2.0',
]

// ---------- 表单参数 ----------
const mode = ref('text2image')
const prompt = ref('')
const size = ref('1024x1024')
const model = ref('agnes-image-2.1-flash')
const referenceFile = ref(null)

// ---------- 使用全局 Store 管理任务 ----------
const queue = useTaskQueueStore()

// 当前预览的任务 = Store 中的 activeTask，但仅当其是图片类型
const activeTask = computed(() => {
  if (!queue.activeTaskId) return null
  const task = queue.tasks[queue.activeTaskId]
  if (!task) return null
  return task.type === 'image' ? task : null
})

// 选中任务是否为视频类型（在图片视图中不显示预览，仅提示）
const activeTaskIsOtherType = computed(() => {
  if (!queue.activeTaskId) return false
  const task = queue.tasks[queue.activeTaskId]
  return task && task.type !== 'image'
})

// 当前任务是否在运行
const taskRunning = computed(() => {
  if (!activeTask.value) return false
  return ['pending', 'queued', 'processing'].includes(activeTask.value.status)
})

// 进度、耗时（通过 queue._tick 驱动每秒响应式刷新）
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

// 结果 URL
const resultUrl = computed(() => {
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

const progressColor = '#ff8c42'

// 任务总数
const taskCount = computed(() => {
  if (!queue.tasks) return 0
  return Object.keys(queue.tasks).length
})

// 能否提交：提示词不为空 + 未达并发上限
const canSubmit = computed(() => {
  if (!prompt.value.trim()) return false
  if (queue.runningImageCount >= 5) return false
  return true
})

function appendStylePrompt(t) {
  if (!prompt.value.trim().endsWith(t)) {
    prompt.value = prompt.value.trim() + t
  }
}

function handleImageChange(file) {
  referenceFile.value = file
}
function handleImageClear() {
  referenceFile.value = null
}

// ---------- 提交任务 ----------
async function handleGenerate() {
  if (!prompt.value.trim()) {
    ElMessage.warning('请先填写提示词')
    return
  }
  if (mode.value === 'image2image' && !referenceFile.value) {
    ElMessage.warning('请先上传参考图')
    return
  }
  if (queue.runningImageCount >= 5) {
    ElMessage.warning('已达 5 个图片并发上限，请等待任务完成')
    return
  }

  const params = {
    prompt: prompt.value.trim(),
    model: model.value,
    size: size.value,
    mode: mode.value,
  }
  if (mode.value === 'image2image' && referenceFile.value) {
    params.base64_image = referenceFile.value.base64
  }

  try {
    const taskId = await queue.submitImageTask(params)
    queue.setActiveTask(taskId)  // 提交后自动选中新任务 → 预览区立即显示
    ElMessage.success('图片任务已提交，可点击右下「队列」查看所有任务')
  } catch (e) {
    console.error('[ImageView] 提交任务失败：', e)
    ElMessage.error('创建图片任务失败：' + (e.message || '未知错误'))
  }
}

// ---------- 中止当前任务 ----------
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

// ---------- 下载 / 复制 ----------
async function downloadImage() {
  if (!resultUrl.value) {
    ElMessage.warning('图片链接为空，无法下载')
    return
  }
  try {
    ElMessage.info('正在准备下载…')
    const response = await fetch(resultUrl.value, { mode: 'cors' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const blob = await response.blob()
    const blobUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = blobUrl
    a.download = `agnes-image-${Date.now()}.png`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    setTimeout(() => URL.revokeObjectURL(blobUrl), 1000)
    ElMessage.success('已开始下载图片')
  } catch (err) {
    console.warn('[ImageView] fetch 下载失败：', err)
    ElMessage.warning('跨域下载受限，已在新标签页打开。请右键图片选择「另存为」')
    window.open(resultUrl.value, '_blank', 'noopener,noreferrer')
  }
}

function copyImageUrl() {
  if (!resultUrl.value) {
    ElMessage.warning('图片链接为空')
    return
  }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(resultUrl.value)
      .then(() => ElMessage.success('图片链接已复制'))
      .catch(() => ElMessage.error('复制失败，请手动复制'))
  } else {
    const ta = document.createElement('textarea')
    ta.value = resultUrl.value
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    ElMessage.success('图片链接已复制')
  }
}
</script>

<style scoped>
.image-view { color: #e8eef7; }
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
  background: rgba(255, 140, 66, 0.2);
  color: #ffa56b;
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
.mode-tabs { margin-bottom: 12px; }
.param-form { margin-top: 12px; }
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
.result-img {
  width: 100%;
  max-height: 520px;
  object-fit: contain;
  border-radius: 12px;
  background: #000;
  display: block;
}
.result-meta {
  margin-top: 16px;
  padding: 12px;
  background: rgba(15, 24, 42, 0.4);
  border-radius: 8px;
  text-align: left;
}
.meta-row { font-size: 13px; padding: 4px 0; color: #d5e3f7; }
.meta-label { color: #8ba3c9; margin-right: 6px; }
.meta-value { word-break: break-word; }

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
</style>
