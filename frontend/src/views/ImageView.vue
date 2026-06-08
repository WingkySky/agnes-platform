<!-- =====================================================
     图片生成视图 ImageView（已接入全局任务队列 Store）
     模式：
       - 文生图 (text2image)
       - 图生图 (image2image)
     特性：
       - 任务提交到全局 Store（切换 tab 不丢失状态）
       - 轮询由 Store 统一管理
       - 可同时并发生成多个图片任务（最多 5 个）
     ===================================================== -->

<template>
  <div class="image-view">
    <h2 class="page-title">🎨 图片生成</h2>
    <p class="page-desc">根据文字描述或参考图生成 AI 图片。支持多种尺寸，可同时提交多个任务，在右下「队列」中查看进度。</p>

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
              <el-tab-pane label="📝 文生图" name="text2image">
                <span class="tab-sub">仅输入提示词，AI 从零生成图片</span>
              </el-tab-pane>
              <el-tab-pane label="🖼 图生图" name="image2image">
                <span class="tab-sub">上传参考图 + 提示词，AI 基于参考图创作</span>
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

            <!-- 生成按钮（使用 Store 中的图片任务并发数判断） -->
            <el-button
              type="primary"
              size="large"
              class="generate-btn"
              :disabled="!canSubmit"
              @click="handleGenerate"
            >
              <el-icon><MagicStick /></el-icon>
              <span>✨ 生成图片（加入队列）</span>
            </el-button>
            <div class="queue-hint">
              当前进行中: {{ queue.runningImageCount }} / 5
            </div>
          </el-form>
        </el-card>
      </el-col>

      <!-- 右侧：结果区（从 Store 读取当前任务状态） -->
      <el-col :xs="24" :md="13">
        <el-card shadow="never">
          <template #header>
          <div class="card-header">
            <span>生成结果</span>
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

          <!-- 加载中（从 Store 读取） -->
          <div v-if="activeTask && taskRunning" class="result-loading">
            <el-progress
              :percentage="taskProgress"
              :stroke-width="12"
              :color="progressColor" />
            <div class="loading-text">AI 正在精心绘制...</div>
            <div class="loading-sub">已耗时 {{ taskElapsedSec }} 秒 · 队列后台持续轮询</div>
            <div v-if="activeTask.errorMessage" class="error-msg">{{ activeTask.errorMessage }}</div>
          </div>

          <!-- 成功（从 Store 读取） -->
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
              <div class="meta-row">
              <span class="meta-label">状态：</span>
              <span class="tag-success">success</span>
              </div>
            </div>
          </div>

          <!-- 失败（从 Store 读取） -->
          <div v-else-if="activeTask && activeTask.status === 'failed'" class="result-failed">
            <el-icon :size="48" color="#ff7b7b"><CircleCloseFilled /></el-icon>
            <div class="failed-text">图片生成失败</div>
            <div class="failed-sub">{{ activeTask.errorMessage || '请检查 API 或稍后重试' }}</div>
            <el-button type="primary" size="small" class="retry-btn" @click="handleGenerate">
              重新生成
            </el-button>
          </div>

          <!-- 取消（从 Store 读取） -->
          <div v-else-if="activeTask && activeTask.status === 'cancelled'" class="result-failed">
            <el-icon :size="48" color="#ffb86b"><CircleCloseFilled /></el-icon>
            <div class="failed-text">任务已取消</div>
            <div class="failed-sub">点击右下「队列」查看历史任务</div>
          </div>

          <!-- 空状态 -->
          <div v-else class="empty-state">
            <el-icon :size="48"><PictureFilled /></el-icon>
            <p class="empty-text">填写左侧参数，点击「生成图片」开始创作</p>
            <p class="empty-sub">生成后可切换到其他页面继续创作，状态不丢失</p>
          </div>
        </el-card>

        <!-- 近期生成提示 -->
        <div class="tips-card">
          <div class="tipstitle">💡 使用技巧</div>
          <ul>
            <li>提示词越具体，效果越好，可以包含主题、风格、光照、构图</li>
            <li>图生图模式下，参考图会影响整体风格与构图</li>
            <li>可同时提交多个图片任务（最多 5 个并发），点击右下「队列」查看所有任务</li>
            <li>任务完成后 20 分钟内仍可在队列中查看，之后自动清理（数据库历史保留）</li>
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
  MagicStick, Download, Link, PictureFilled, Loading, CircleCloseFilled
} from '@element-plus/icons-vue'
import PromptTemplates from '@/components/PromptTemplates.vue'
import ImageUploader from '@/components/ImageUploader.vue'
// ---------- 全局 Store 替换本地状态 ----------
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

// 当前在本视图中激活的任务 ID
const activeTaskId = ref('')

// 计算属性：从 Store 读取对应任务
const activeTask = computed(() => {
  if (!activeTaskId.value) return null
  return queue.tasks[activeTaskId.value] || null
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

// 从 Store 读取的图片结果 URL
const resultUrl = computed(() => {
  if (!activeTask.value) return ''
  return activeTask.value.resultUrl || activeTask.value.url || ''
})

const progressColor = '#ff8c42'

const canSubmit = computed(() => {
  if (!prompt.value.trim()) return false
  if (mode.value === 'image2image' && !referenceFile.value) return false
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

// ---------- 开始生成（提交到 Store，不阻塞本地） ----------
async function handleGenerate() {
  if (!canSubmit.value) {
    if (!prompt.value.trim()) {
      ElMessage.warning('请先填写提示词')
    } else if (mode.value === 'image2image' && !referenceFile.value) {
      ElMessage.warning('请先上传参考图')
    }
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
    console.log('[ImageView] 提交到任务队列，参数：', params)
    const taskId = await queue.submitImageTask(params)
    activeTaskId.value = taskId
    ElMessage.success('图片任务已提交，可点击右下「队列」查看进度')
  } catch (e) {
    console.error('[ImageView] 提交任务失败：', e)
    ElMessage.error('创建图片任务失败：' + (e.message || '未知错误'))
  }
}

// ---------- 下载图片 ----------
async function downloadImage() {
  if (!resultUrl.value) {
    ElMessage.warning('图片链接为空，无法下载')
    return
  }
  try {
    ElMessage.info('正在准备下载，请稍候…')
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
    console.warn('[ImageView] fetch 下载失败，回退为新标签页打开：', err)
    ElMessage.warning('跨域下载受限，已在新标签页打开。请右键图片选择「另存为」')
    window.open(resultUrl.value, '_blank', 'noopener,noreferrer')
  }
}

// ---------- 复制链接 ----------
function copyImageUrl() {
  if (!resultUrl.value) {
    ElMessage.warning('图片链接为空')
    return
  }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(resultUrl.value)
      .then(() => ElMessage.success('图片链接已复制到剪贴板'))
      .catch(() => ElMessage.error('复制失败，请手动复制'))
  } else {
    const ta = document.createElement('textarea')
    ta.value = resultUrl.value
    ta.style.position = 'fixed'
    ta.style.left = '-9999px'
    ta.style.top = '0'
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand('copy')
      ElMessage.success('图片链接已复制到剪贴板')
    } catch (e) {
      ElMessage.error('复制失败，请手动复制')
    }
    document.body.removeChild(ta)
  }
}
</script>

<style scoped>
.image-view { color: #e8eef7; }
.page-title { margin: 0 0 4px 0; }
.page-desc { color: #8ba3c9; font-size: 14px; margin-bottom: 20px; }
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
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
.result-img {
  width: 100%;
  max-height: 500px;
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
.meta-value { word-break: break-all; }
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
.tipstitle { font-weight: 600; color: #d5e3f7; margin-bottom: 8px; }
.tips-card ul { margin: 0; padding-left: 20px; line-height: 1.8; }
</style>
