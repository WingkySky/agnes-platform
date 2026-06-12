<!-- =====================================================
     ImageUploader 图片上传组件（多图版）
     - 支持拖拽上传 / 选择文件 / 粘贴图片 URL
     - 将本地文件转换为 base64（不含 data:image/... 前缀
     - 事件：@change(fileInfoList)        // 返回数组
             @clear
     fileInfo 格式:
       {
         name: 'xxx.png',
         base64: '...',    // 不带前缀的纯 base64 字符串
         previewUrl: 'data:image/png;base64,...',
         size: 1024000,
         source: 'file' | 'url'
       }
     ===================================================== -->

<template>
  <div class="image-uploader">
    <!-- 标题 -->
    <div class="section-title">
      {{ t('params.refImage') }}{{ optional ? '（' + t('common.optional') + '）' : '' }}
      <span class="sub-hint">（已上传 {{ fileList.length }} 张，支持多选）</span>
    </div>

    <!-- 已上传预览：网格 -->
    <div v-if="fileList.length > 0" class="file-grid">
      <div
        v-for="(file, idx) in fileList"
        :key="idx"
        class="file-card"
      >
        <img
          :src="file.previewUrl"
          class="file-preview-img"
          :alt="file.name"
          @click="openPreview(file.previewUrl)"
        />
        <div class="file-meta">
          <div class="file-name" :title="file.name">{{ truncateName(file.name, 22) }}</div>
          <div v-if="file.size" class="file-size">{{ formatSize(file.size) }}</div>
          <div class="file-source">{{ file.source === 'url' ? 'URL' : t('common.local') }}</div>
        </div>
        <el-button
          size="small"
          type="danger"
          plain
          @click="removeFile(idx)"
          class="del-btn"
        >
          <el-icon><Delete /></el-icon>
          {{ t('params.remove') }}
        </el-button>
      </div>
    </div>

    <!-- 模式切换（当没有图片时显示操作区） -->
    <div v-if="fileList.length === 0" class="mode-switch">
      <el-radio-group v-model="mode" size="small">
        <el-radio-button value="file">{{ t('params.uploadLocal') }}</el-radio-button>
        <el-radio-button value="url">{{ t('params.pasteUrl') }}</el-radio-button>
      </el-radio-group>
    </div>

    <!-- 上传区（文件模式） -->
    <div
      v-if="mode === 'file'"
      class="upload-zone"
      @dragover.prevent="isDragOver = true"
      @dragleave.prevent="isDragOver = false"
      @drop.prevent="handleDrop"
      @click="$refs.fileInput.click()"
      :class="{ 'drag-over': isDragOver }"
    >
      <el-icon :size="36" class="upload-icon"><UploadFilled /></el-icon>
      <div class="upload-hint">{{ t('params.uploadHint') }}</div>
      <div class="upload-desc">{{ t('params.uploadDesc').replace('{n}', maxSizeMB) }}</div>
      <input
        ref="fileInput"
        type="file"
        accept="image/*"
        multiple
        class="hidden-input"
        @change="handleFilesChange"
      />
    </div>

    <!-- URL 模式 -->
    <div v-if="mode === 'url'" class="url-zone">
      <el-input
        v-model="urlInput"
        :placeholder="t('params.urlPlaceholder')"
        @keydown.enter="handleUrlConfirm"
      >
        <template #append>
          <el-button @click="handleUrlConfirm">{{ t('common.confirm') }}</el-button>
        </template>
      </el-input>
      <div class="url-hint">{{ t('params.urlHint') }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, UploadFilled } from '@element-plus/icons-vue'
import { useI18n } from '@/i18n'

const { t } = useI18n()

const props = defineProps({
  maxSizeMB: { type: Number, default: 10 },
  optional: { type: Boolean, default: false },
})

const emit = defineEmits(['change', 'clear'])

const mode = ref('file')
const urlInput = ref('')
const fileList = ref([])          // 多图数组
const isDragOver = ref(false)
const fileInput = ref(null)

// =====================================================
// 对外暴露（父组件调用）
// =====================================================
defineExpose({
  getFiles: () => fileList.value,          // 返回数组
  clearFiles: () => {
    fileList.value = []
    emit('clear')
    emit('change', null)
  },
})

// =====================================================
// 工具函数
// =====================================================
function formatSize(bytes) {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(2) + ' MB'
}

function truncateName(name, max) {
  if (!name) return ''
  if (name.length <= max) return name
  return name.slice(0, max - 3) + '...'
}

function validateFile(file) {
  const maxBytes = props.maxSizeMB * 1024 * 1024
  if (file.size > maxBytes) {
    ElMessage.error(t('params.imageTooLarge').replace('{n}', props.maxSizeMB))
    return false
  }
  if (!file.type || !file.type.startsWith('image/')) {
    ElMessage.error(t('params.imageInvalid'))
    return false
  }
  return true
}

// File -> base64（返回 { name, base64(纯), previewUrl, size, source }
function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const fullBase64 = reader.result
      const pureBase64 = fullBase64.split(';base64,')[1]
      resolve({
        name: file.name,
        base64: pureBase64,
        previewUrl: fullBase64,
        size: file.size,
        source: 'file',
      })
    }
    reader.onerror = () => reject(new Error('read_failed'))
    reader.readAsDataURL(file)
  })
}

function emitChange() {
  emit('change', fileList.value.length ? fileList.value : null)
}

// =====================================================
// 文件多选
// =====================================================
async function handleFilesChange(e) {
  const input = e.target
  const files = Array.from(input.files || [])
  if (files.length === 0) return

  let added = 0
  for (const file of files) {
    if (!validateFile(file)) continue
    try {
      const info = await fileToBase64(file)
      fileList.value.push(info)
      added++
    } catch (err) {
      ElMessage.error(t('params.imageParseFailed'))
    }
  }
  if (added > 0) {
    ElMessage.success(
      `已添加 ${added} 张图片（共 ${fileList.value.length} 张）`
    )
  }
  emitChange()
  // 清空 input，允许重复选择同一文件
  if (input) input.value = ''
}

// =====================================================
// 拖拽
// =====================================================
async function handleDrop(e) {
  isDragOver.value = false
  const files = Array.from(e.dataTransfer?.files || [])
  if (files.length === 0) return

  const results = []
  for (const file of files) {
    if (!validateFile(file)) continue
    try {
      const info = await fileToBase64(file)
      results.push(info)
    } catch {
      ElMessage.error(t('params.imageParseFailed'))
    }
  }
  if (results.length > 0) {
    fileList.value.push(...results)
    ElMessage.success(
      `已添加 ${results.length} 张图片（共 ${fileList.value.length} 张）`
    )
    emitChange()
  }
}

// =====================================================
// URL 模式
// =====================================================
function handleUrlConfirm() {
  const url = urlInput.value.trim()
  if (!url) return
  if (!/^https?:\/\//i.test(url)) {
    ElMessage.error(t('params.urlInvalid'))
    return
  }
  fileList.value.push({
    name: url.split('/').pop() || 'image',
    base64: null,
    previewUrl: url,
    size: null,
    source: 'url',
    url,
  })
  urlInput.value = ''
  ElMessage.success(`已添加 URL 图片（共 ${fileList.value.length} 张）`)
  emitChange()
}

// =====================================================
// 单张删除
// =====================================================
function removeFile(index) {
  const name = fileList.value[index]?.name
  fileList.value.splice(index, 1)
  if (name) ElMessage.info(`已移除: ${name}`)
  emitChange()
}

// =====================================================
// 预览大图（浏览器原生）
// =====================================================
function openPreview(url) {
  if (!url) return
  try {
    const w = window.open()
    if (w) {
      w.document.write(
        `<img src="${url}" style="max-width:100%;display:block;margin:auto;">`
      )
    }
  } catch (e) {
    console.warn('[ImageUploader] 预览打开失败', e)
  }
}
</script>

<style scoped>
.image-uploader {
  margin-bottom: 16px;
}
.section-title {
  font-size: 13px;
  color: #a0b4d6;
  margin-bottom: 10px;
  font-weight: 500;
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.sub-hint {
  font-size: 12px;
  color: #6b84aa;
  font-weight: normal;
}
.mode-switch {
  margin-bottom: 12px;
}
.hidden-input { display: none; }

/* 文件上传区样式 */
.upload-zone {
  border: 2px dashed rgba(120, 170, 255, 0.3);
  border-radius: 12px;
  padding: 32px;
  text-align: center;
  background: rgba(15, 24, 42, 0.4);
  cursor: pointer;
  transition: all 0.2s ease;
}
.upload-zone:hover,
.upload-zone.drag-over {
  border-color: #6b9cff;
  background: rgba(90, 134, 255, 0.08);
}
.upload-icon { color: #6b9cff; margin-bottom: 8px; }
.upload-hint { color: #d5e3f7; font-weight: 500; margin-bottom: 4px; }
.upload-desc { color: #6b84aa; font-size: 12px; }

/* 网格预览 */
.file-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
  margin-top: 12px;
  margin-bottom: 12px;
}
.file-card {
  border: 1px solid var(--border-color, rgba(120, 170, 255, 0.2));
  border-radius: 8px;
  padding: 8px;
  background: rgba(15, 24, 42, 0.4);
  display: flex;
  flex-direction: column;
  align-items: stretch;
}
.file-preview-img {
  width: 100%;
  height: 120px;
  object-fit: cover;
  border-radius: 4px;
  cursor: zoom-in;
}
.file-meta { margin-top: 6px; font-size: 12px; text-align: center; color: #a0b4d6; }
.file-name { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #d5e3f7; }
.file-size { color: #6b84aa; }
.file-source { color: #6b9cff; font-size: 11px; }
.del-btn { margin-top: 6px; }

/* URL 区 */
.url-zone {
  background: rgba(15, 24, 42, 0.4);
  padding: 16px;
  border-radius: 12px;
  border: 1px solid rgba(120, 170, 255, 0.2);
}
.url-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #6b84aa;
}
</style>
