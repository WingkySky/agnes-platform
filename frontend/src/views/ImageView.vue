<!-- =====================================================
     图片生成视图 ImageView
     模式：
       - 文生图 (text2image)
       - 图生图 (image2image)
     ===================================================== -->

<template>
  <div class="image-view">
    <h2 class="page-title">🎨 图片生成</h2>
    <p class="page-desc">根据文字描述或参考图生成 AI 图片。支持多种尺寸，可作为参考图再创作。</p>

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

            <!-- 生成按钮 -->
            <el-button
              type="primary"
              size="large"
              class="generate-btn"
              :disabled="loading || !canSubmit"
              :loading="loading"
              @click="handleGenerate"
            >
              <el-icon><MagicStick /></el-icon>
              <span>{{ loading ? '正在生成...' : '✨ 生成图片' }}</span>
            </el-button>
          </el-form>
        </el-card>
      </el-col>

      <!-- 右侧：结果区 -->
      <el-col :xs="24" :md="13">
        <el-card shadow="never">
          <template #header>
          <div class="card-header">
            <span>生成结果</span>
            <span v-if="result" class="header-actions">
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

          <!-- 加载中 -->
          <div v-if="loading" class="result-loading">
            <el-icon :size="40" class="spinner"><Loading /></el-icon>
            <div class="loading-text">AI 正在精心绘制...</div>
            <div class="loading-sub">通常需要 15-60 秒，请耐心等待</div>
          </div>

          <!-- 结果展示 -->
          <div v-else-if="result" class="result-wrap">
            <img v-if="result.url" :src="result.url" class="result-img" alt="generated" />
            <img v-else-if="result.b64_json" :src="'data:image/png;base64,' + result.b64_json" class="result-img" />
            <div class="result-meta">
              <div class="meta-row">
              <span class="meta-label">提示词：</span>
              <span class="meta-value">{{ result.prompt }}</span>
              </div>
              <div class="meta-row">
              <span class="meta-label">尺寸：</span>
              <span class="meta-value">{{ result.size }}</span>
              </div>
            </div>
          </div>

          <!-- 空状态 -->
          <div v-else class="empty-state">
            <el-icon :size="48"><PictureFilled /></el-icon>
            <p class="empty-text">填写左侧参数，点击「生成图片」开始创作</p>
          </div>
        </el-card>

        <!-- 近期生成提示 -->
        <div class="tips-card">
          <div class="tipstitle">💡 使用技巧</div>
          <ul>
            <li>提示词越具体，效果越好，可以包含主题、风格、光照、构图</li>
            <li>图生图模式下，参考图会影响整体风格与构图</li>
            <li>若生成结果不满意，可以调整 Prompt 或更换风格重新生成</li>
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
  MagicStick, Download, Link, PictureFilled, Loading
} from '@element-plus/icons-vue'
import PromptTemplates from '@/components/PromptTemplates.vue'
import ImageUploader from '@/components/ImageUploader.vue'
import { createImage } from '@/api/images'

// ============ 常量 ============
const IMAGE_SIZES = ['1024x1024', '1024x768', '768x1024', '512x512']
const IMAGE_MODELS = ['agnes-image-2.1-flash']
const IMAGE_TEMPLATES = [
  { label: '电影感', prompt: '，电影级构图，戏剧化光影，浅景深，胶片颗粒，专业调色，8K 高清' },
  { label: '赛博朋克', prompt: '，赛博朋克风格，霓虹灯光，高对比度，未来感' },
  { label: '极简主义', prompt: '，极简主义，干净构图，留白，柔和色彩' },
  { label: '超写实', prompt: '，超写实照片，极致细节，自然光线，高质感' },
  { label: '水彩油画', prompt: '，水彩与油画质感，柔和笔触，艺术性' },
  { label: '3D 渲染', prompt: '，3D 渲染，工作室光照，光滑表面，物理渲染' },
  { label: '动漫插画', prompt: '，日系动漫风格，鲜艳色彩，干净线条' },
  { label: '复古胶片', prompt: '，复古胶片，暖色调，胶片颗粒' }
]

// ============ 状态 ============
const mode = ref('text2image')
const prompt = ref('')
const size = ref('1024x1024')
const model = ref('agnes-image-2.1-flash')
const referenceFile = ref(null) // { base64 / url
const loading = ref(false)
const result = ref(null)

// ============ 计算 ============
const canSubmit = computed(() => prompt.value.trim().length > 0)

// ============ 事件 ============
function appendStylePrompt(styleText) {
  // 追加风格描述（追加到 prompt 末尾
  if (!prompt.value.trim().endsWith(styleText)) {
    prompt.value = prompt.value.trim() + styleText
  }
}

function handleImageChange(file) {
  // 保存参考图信息
  referenceFile.value = file
}
function handleImageClear() {
  referenceFile.value = null
}

// ============ 生成 ============
async function handleGenerate() {
  if (!canSubmit.value) {
    ElMessage.warning('请先填写提示词')
    return
  }
  loading.value = true
  result.value = null

  try {
    const params = {
      prompt: prompt.value.trim(),
      model: model.value,
      size: size.value,
      response_format: 'url'
    }
    // 图生图模式：附加 base64_image
    if (mode.value === 'image2image' && referenceFile.value) {
      params.base64_image = referenceFile.value.base64 || referenceFile.value.url
    }

    const data = await createImage(params)
    result.value = {
      url: data.url || null,
      b64_json: data.b64_json,
      prompt: data.prompt || prompt.value,
      size: data.size || size.value
    }
    ElMessage.success('图片生成成功！')
  } catch (err) {
    result.value = null
    // 显示错误信息
    const errorMsg = err?.response?.data?.detail || err?.message || '图片生成失败，请稍后重试'
    ElMessage.error(errorMsg)
    console.error('[图片生成错误]', err)
  } finally {
    loading.value = false
  }
}

// ============ 结果操作 ============
function downloadImage() {
  if (!result.value?.url) return
  const a = document.createElement('a')
  a.href = result.value.url
  a.download = `agnes-image-${Date.now()}.png`
  a.target = '_blank'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  ElMessage.success('已开始下载')
}

function copyImageUrl() {
  if (!result.value?.url) return
  navigator.clipboard?.writeText(result.value.url)
    .then(() => ElMessage.success('链接已复制到剪贴板'))
    .catch(() => {
      // 降级方案
      const ta = document.createElement('textarea')
      ta.value = result.value.url
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      ElMessage.success('链接已复制')
    })
}
</script>

<style scoped>
.image-view { color: #e8eef7; }
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}
.header-actions .el-button { margin-left: 8px; }
.mode-tabs { margin-bottom: 16px 0 20px; }
.tab-sub { font-size: 12px; color: #8ba3c9; margin-left: 6px; }

.param-form { margin-top: 16px; }
.generate-btn {
  width: 100%;
  height: 48px;
  font-size: 16px;
  font-weight: 600;
  margin-top: 8px;
}

/* 结果区 */
.result-loading {
  padding: 80px 20px;
  text-align: center;
  color: #a0b4d6;
}
.spinner { animation: spin 1.2s linear infinite; color: #6b9cff; }
@keyframes spin { to { transform: rotate(360deg); } }
.loading-text { margin-top: 16px; font-size: 16px; color: #d5e3f7; }
.loading-sub { margin-top: 6px; font-size: 12px; }

.result-wrap { text-align: center; }
.result-img {
  width: 100%;
  max-height: 600px;
  object-fit: contain;
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
}
.result-meta { margin-top: 16px; padding: 12px; background: rgba(15, 24, 42, 0.4); border-radius: 8px; text-align: left;
}
.meta-row { font-size: 13px; padding: 4px 0; }
.meta-label { color: #8ba3c9; }

.empty-state {
  padding: 80px 20px;
  text-align: center;
  color: #6b84aa;
}
.empty-text { margin-top: 16px; font-size: 14px;
}

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
</style>
