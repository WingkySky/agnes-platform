<!-- =====================================================
     图片生成视图 ImageView（已接入全局任务队列 Store）
     模式：
       - 文生图 (text2image)
       - 图生图 (image2image)
     - 所有 UI 文案通过 i18n.t() 调用实现多语言
     ===================================================== -->

<template>
  <div class="image-view">
    <h2 class="page-title">🎨 {{ t('view.imageTitle') }}</h2>
    <p class="page-desc">{{ t('view.imageDesc') }}</p>

    <el-row :gutter="24">
      <!-- 左侧：参数区 -->
      <el-col :xs="24" :md="11">
        <el-card shadow="never">
          <template #header>
          <div class="card-header">
            <span>{{ t('params.title') }}</span>
          </div>
          </template>

          <!-- 模式切换：图标 + 标题 + 短副标签 -->
          <el-tabs v-model="mode" class="mode-tabs">
              <el-tab-pane name="text2image">
                <template #label>
                  <span class="mode-label">
                    <span class="mode-icon">✍️</span>
                    <span class="mode-text">
                      <span class="mode-title">{{ t('params.mode.text2image') }}</span>
                      <span class="mode-sub">{{ t('params.mode.textOnly') }}</span>
                    </span>
                  </span>
                </template>
              </el-tab-pane>
              <el-tab-pane name="image2image">
                <template #label>
                  <span class="mode-label">
                    <span class="mode-icon">🖼️</span>
                    <span class="mode-text">
                      <span class="mode-title">{{ t('params.mode.image2image') }}</span>
                      <span class="mode-sub">{{ t('params.mode.imageOnly') }}</span>
                    </span>
                  </span>
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
            <el-form-item :label="t('params.prompt')">
              <el-input
              v-model="prompt"
              type="textarea"
              :rows="4"
              :placeholder="t('params.promptPlaceholder')"
              maxlength="2000"
              show-word-limit
            />
            </el-form-item>

            <!-- 预设风格 -->
            <PromptTemplates
              :templates="imageTemplates"
              @select="appendStylePrompt"
            />

            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item :label="t('params.size')">
                  <el-select v-model="size">
                    <el-option v-for="s in IMAGE_SIZES" :key="s" :label="s" :value="s" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item :label="t('params.model')">
                  <el-select v-model="model">
                    <el-option v-for="m in IMAGE_MODELS" :key="m" :label="m" :value="m" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>

            <!-- 生成按钮 -->
            <el-button
              type="primary"
              size="large"
              class="generate-btn"
              :disabled="!canSubmit"
              @click="handleGenerate">
              <el-icon><MagicStick /></el-icon>
              <span>{{ t('generate.imageBtn') }}</span>
            </el-button>

            <div class="queue-hint">
              {{ t('generate.running') }}: {{ queue.runningImageCount }} / 5 · {{ t('generate.submitted') }}: {{ taskCount }}
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
              <span>{{ t('preview.resultTitle') }}</span>
              <span v-if="activeTask" class="task-pill" :class="'status-' + activeTask.status">
                {{ statusLabel }}
              </span>
            </div>
            <span v-if="resultUrl" class="header-actions">
              <el-button size="small" @click="downloadImage">
              <el-icon><Download /></el-icon>
              {{ t('preview.download') }}
              </el-button>
              <el-button size="small" type="primary" link @click="copyImageUrl">
              <el-icon><Link /></el-icon>
              {{ t('preview.copyLink') }}
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
            <img v-if="resultUrl" :src="resultUrl" class="result-img" alt="generated" />
            <img v-else-if="activeTask.imageB64" :src="'data:image/png;base64,' + activeTask.imageB64" class="result-img" />
            <div class="result-meta">
              <div class="meta-row">
              <span class="meta-label">{{ t('params.prompt') }}：</span>
              <span class="meta-value">{{ activeTask.prompt }}</span>
              </div>
              <div class="meta-row">
              <span class="meta-label">{{ t('params.size') }}：</span>
              <span class="meta-value">{{ size }}</span>
              </div>
            </div>
          </div>

          <!-- 情况 C：任务失败 -->
          <div v-else-if="activeTask && activeTask.status === 'failed'" class="result-failed">
            <el-icon :size="48" color="#ff7b7b"><CircleCloseFilled /></el-icon>
            <div class="failed-text">{{ t('status.imageGenerateFailed') }}</div>
            <div class="failed-sub">{{ activeTask.errorMessage || '' }}</div>
            <el-button type="primary" size="small" class="retry-btn" @click="retryActiveTask">
              {{ t('status.retryWithSame') }}
            </el-button>
          </div>

          <!-- 情况 D：已取消 -->
          <div v-else-if="activeTask && activeTask.status === 'cancelled'" class="result-failed">
            <el-icon :size="48" color="#ffb86b"><CircleCloseFilled /></el-icon>
            <div class="failed-text">{{ t('status.cancelled') }}</div>
            <div class="failed-sub">{{ t('preview.wrongTypeHint') }}</div>
          </div>

          <!-- 情况 E：选中的是视频任务，不匹配当前视图 -->
          <div v-else-if="activeTaskIsOtherType" class="empty-state">
            <el-icon :size="48"><VideoPlay /></el-icon>
            <p class="empty-text">{{ t('preview.wrongTypeImage') }}</p>
            <p class="empty-sub">{{ t('preview.switchPageHint') }}</p>
          </div>

          <!-- 情况 F：没有选中的任务 -->
          <div v-else class="empty-state">
            <el-icon :size="48"><PictureFilled /></el-icon>
            <p class="empty-text">{{ t('preview.notSelectable') }}</p>
            <p class="empty-sub">{{ t('preview.emptyHint') }}</p>
          </div>
        </el-card>

        <!-- 使用技巧 -->
        <div class="tips-card">
          <div class="tip-title">{{ t('tips.title') }}</div>
          <ul>
            <li>{{ t('tips.concurrentImage') }}</li>
            <li>{{ t('tips.queueSwitch') }}</li>
            <li>{{ t('tips.historyKeep') }}</li>
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
import { useI18n } from '@/i18n'

const { t } = useI18n()

// 预设风格：不同语言下显示不同的 label（prompt 本身保持原样，不随语言变化）
// 注意：这里用 computed 动态读取当前语言下的显示名，避免语言切换后不同步
const imageTemplates = computed(() => ([
  { label: t('presets.surrealism'), prompt: '，超现实主义风格，梦幻，高细节' },
  { label: t('presets.cinematic'), prompt: '，电影感，戏剧性光照，宽银幕' },
  { label: t('presets.anime'), prompt: '，日式动漫风格，鲜艳色彩，细腻线条' },
  { label: t('presets.oilPainting'), prompt: '，古典油画风格，厚重笔触，文艺复兴质感' },
  { label: t('presets.realisticPhoto'), prompt: '，专业摄影，8K 超高清，自然光照' },
  { label: t('presets.cyberpunk'), prompt: '，赛博朋克，霓虹光，未来都市感' },
  { label: t('presets.inkStyle'), prompt: '，中国水墨风格，留白艺术，意境悠远' },
]))

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
const referenceFileList = ref([])   // 【多图】数组

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

// 结果 URL
const resultUrl = computed(() => {
  if (!activeTask.value) return ''
  return activeTask.value.resultUrl || activeTask.value.url || ''
})

// 状态标签（使用 i18n 显示本地化名称）
const statusLabel = computed(() => {
  if (!activeTask.value) return ''
  const s = activeTask.value.status
  const key = `status.${s}`
  const localized = t(key)
  // 若翻译值与 key 相同（未翻译），则原样返回
  return localized === key ? s : localized
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

function appendStylePrompt(tpl) {
  if (!prompt.value.trim().endsWith(tpl)) {
    prompt.value = prompt.value.trim() + tpl
  }
}

function handleImageChange(fileList) {
  // fileList 为数组（可能为 null 表示清空）
  referenceFileList.value = Array.isArray(fileList) ? fileList : (fileList ? [fileList] : [])
}
function handleImageClear() {
  referenceFileList.value = []
}

// ---------- 提交任务 ----------
async function handleGenerate() {
  if (!prompt.value.trim()) {
    ElMessage.warning(t('message.pleaseFillPrompt'))
    return
  }
  if (mode.value === 'image2image' && referenceFileList.value.length === 0) {
    ElMessage.warning(t('message.pleaseUploadRefImage'))
    return
  }
  if (queue.runningImageCount >= 5) {
    ElMessage.warning(t('generate.concurrentImageLimit'))
    return
  }

  const params = {
    prompt: prompt.value.trim(),
    model: model.value,
    size: size.value,
    mode: mode.value,
  }
  // 【多图】图生图时：区分为 base64_images 与 image_urls
  if (mode.value === 'image2image' && referenceFileList.value.length > 0) {
    const b64Imgs = referenceFileList.value
      .filter(f => f.source === 'file' && f.base64)
      .map(f => f.base64)
    const urlImgs = referenceFileList.value
      .filter(f => f.source === 'url' && f.url)
      .map(f => f.url)
    if (b64Imgs.length) params.base64_images = b64Imgs
    if (urlImgs.length) params.image_urls = urlImgs
  }

  try {
    const taskId = await queue.submitImageTask(params)
    queue.setActiveTask(taskId)
    ElMessage.success(t('generate.imageSubmitted'))
  } catch (e) {
    console.error('[ImageView] 提交任务失败：', e)
    ElMessage.error(t('generate.createTaskFailed') + (e.message || ''))
  }
}

// ---------- 中止当前任务 ----------
function cancelActiveTask() {
  if (!queue.activeTaskId) return
  queue.cancelTask(queue.activeTaskId)
  ElMessage.info(t('status.taskCancelled'))
}

// ---------- 重试当前任务 ----------
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

// ---------- 下载 / 复制 ----------
async function downloadImage() {
  if (!resultUrl.value) {
    ElMessage.warning(t('preview.imageEmpty'))
    return
  }
  try {
    // 通过后端代理下载，设置 Content-Disposition: attachment 强制浏览器保存文件
    const baseURL = import.meta.env.VITE_API_BASE_URL || ''
    const downloadUrl = `${baseURL}/api/download?url=${encodeURIComponent(resultUrl.value)}&type=image`
    const a = document.createElement('a')
    a.href = downloadUrl
    a.download = ''  // 让后端 Content-Disposition 控制文件名
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    ElMessage.success(t('preview.download'))
  } catch (err) {
    console.warn('[ImageView] 下载失败：', err)
    ElMessage.warning(t('preview.corsWarning'))
  }
}

function copyImageUrl() {
  if (!resultUrl.value) {
    ElMessage.warning(t('preview.imageEmpty'))
    return
  }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(resultUrl.value)
      .then(() => ElMessage.success(t('preview.copySuccess')))
      .catch(() => ElMessage.error(t('preview.copyFailed')))
  } else {
    const ta = document.createElement('textarea')
    ta.value = resultUrl.value
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    ElMessage.success(t('preview.copySuccess'))
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
/* 模式切换：图标 + 标题 + 短副标签 */
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
.meta-label { color: #8ba3c9; margin-right: 8px; }
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
