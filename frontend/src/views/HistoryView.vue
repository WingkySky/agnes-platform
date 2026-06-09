<!-- =====================================================
     历史记录视图 HistoryView
     - 筛选：全部 / 图片 / 视频
     - 分页加载
     - 点击卡片弹出详情（可预览、下载、删除）
     ===================================================== -->

<template>
  <div class="history-view">
    <h2 class="page-title">📜 生成历史</h2>
    <p class="page-desc">查看你在本平台生成过的所有图片与视频。可按类型筛选。</p>

    <!-- 筛选 Tab -->
    <div class="filter-wrap">
      <el-radio-group v-model="filterType" @change="loadList(true)">
        <el-radio-button value="all">全部 ({{ imageCount + videoCount }})</el-radio-button>
        <el-radio-button value="image">图片 ({{ imageCount }})</el-radio-button>
        <el-radio-button value="video">视频 ({{ videoCount }})</el-radio-button>
      </el-radio-group>
      <div class="filter-actions">
        <el-button type="primary" :icon="Refresh" :loading="loading" @click="loadList(true)">
          刷新
        </el-button>
        <!-- 编辑模式切换按钮 -->
        <el-button
          :type="editMode ? 'warning' : 'default'"
          :icon="editMode ? 'Close' : 'Edit'"
          @click="toggleEditMode">
          {{ editMode ? '退出编辑' : '编辑' }}
        </el-button>
      </div>
    </div>

    <!-- 编辑模式操作栏（全选 + 批量删除） -->
    <div v-if="editMode && list.length > 0" class="edit-toolbar">
      <div class="edit-left">
        <el-checkbox
          v-model="isAllSelected"
          :indeterminate="isIndeterminate"
          @change="toggleSelectAll">
          全选当前页
        </el-checkbox>
        <span class="selection-info">
          已选 <b class="selection-count">{{ selectedIds.length }}</b> 条
        </span>
      </div>
      <div class="edit-right">
        <el-button
          type="danger"
          :icon="Delete"
          :disabled="selectedIds.length === 0"
          :loading="batchDeleting"
          @click="confirmBatchDelete">
          删除选中 ({{ selectedIds.length }})
        </el-button>
      </div>
    </div>

    <!-- 加载中 -->
    <div v-if="loading && list.length === 0" class="loading-state">
      <el-icon :size="32" class="spinner"><Loading /></el-icon>
      <div>加载中...</div>
    </div>

    <!-- 空状态 -->
    <div v-else-if="list.length === 0" class="empty-state">
      <el-icon :size="48"><Document /></el-icon>
      <p class="empty-text">暂无历史记录，去「图片生成」或「视频生成」页面试试吧～</p>
    </div>

    <!-- 卡片网格 -->
    <div v-else class="history-grid">
      <div
        v-for="item in list"
        :key="item.id"
        class="history-card"
        :class="{ 'is-selected': selectedIds.includes(item.id) }"
        @click="handleCardClick(item)">
        <!-- 编辑模式下的选择框 -->
        <div v-if="editMode" class="card-checkbox" @click.stop="toggleSelect(item.id)">
          <el-checkbox :model-value="selectedIds.includes(item.id)" />
        </div>
        <div class="card-preview">
          <img
            v-if="item.type === 'image'"
            :src="item.result_url"
            alt="history thumbnail"
            loading="lazy"
          />
          <!-- 视频卡片：首帧缩略图 + 悬停 GIF 预览 -->
          <div
            v-else-if="item.type === 'video'"
            class="video-thumb"
            @mouseenter="onVideoCardHover(item)"
            @mouseleave="onVideoCardLeave(item)"
          >
            <!-- 首帧缩略图（静态） -->
            <img
              v-if="videoThumbnails[item.id]"
              :src="videoThumbnails[item.id]"
              alt="video thumbnail"
              class="video-thumb-img"
              loading="lazy"
            />
            <!-- 缩略图加载失败时的占位 -->
            <div v-else class="video-thumb-placeholder">
              <el-icon :size="44" class="play-icon"><VideoPlay /></el-icon>
              <span class="video-thumb-label">点击播放</span>
            </div>
            <!-- 悬停时的 GIF 预览 -->
            <img
              v-if="hoveredVideoId === item.id && videoPreviews[item.id]"
              :src="videoPreviews[item.id]"
              alt="video preview"
              class="video-preview-gif"
            />
            <!-- 播放图标蒙层 -->
            <div class="video-play-overlay">
              <el-icon :size="32"><VideoPlay /></el-icon>
            </div>
          </div>
          <div class="type-badge" :class="item.type">
            {{ item.type === 'image' ? '图片' : '视频' }}
          </div>
        </div>
        <div class="card-meta">
          <div class="card-prompt">{{ truncate(item.prompt, 80) }}</div>
          <div class="card-time">{{ formatTime(item.created_at) }}</div>
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <div v-if="list.length > 0" class="pagination-wrap">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :page-sizes="[12, 24, 48, 100]"
        :total="totalCount"
        layout="total, sizes, prev, pager, next"
        background
        @size-change="handleSizeChange"
        @current-change="handlePageChange"
      />
    </div>

    <!-- 详情弹窗 -->
    <el-dialog
      v-model="detailVisible"
      :title="detailItem ? (detailItem.type === 'image' ? '图片详情' : '视频详情') : '详情'"
      width="70%"
      top="5vh"
      destroy-on-close>
      <div v-if="detailItem" class="detail-content">
        <div class="detail-media">
          <img v-if="detailItem.type === 'image'" :src="detailItem.result_url" />
          <div v-else class="detail-video-wrap">
            <video
              v-if="detailItem.result_url"
              ref="detailVideoEl"
              :src="getVideoStreamUrl(detailItem)"
              :poster="detailPoster"
              controls
              playsinline
              preload="metadata"
              class="detail-video"
              @loadeddata="captureDetailPoster"
              @canplay="onDetailVideoCanPlay"
              @error="onDetailVideoError"
              @abort="onDetailVideoAbort"
            />
            <div v-else class="detail-video-empty">
              <el-icon :size="36" color="#ff9b9b"><CircleCloseFilled /></el-icon>
              <div>此记录无有效视频链接</div>
            </div>
            <div v-if="detailVideoLoading" class="detail-video-status">
              <el-icon :size="24" class="spinner"><Loading /></el-icon>
              <span>视频加载中…</span>
            </div>
            <div v-if="detailVideoFailed" class="detail-video-status error">
              <el-icon :size="24"><CircleCloseFilled /></el-icon>
              <span>视频无法播放，请尝试「下载」或「新标签页打开」</span>
            </div>
          </div>
        </div>
        <div class="detail-info">
          <div class="info-row"><span class="label">提示词：</span><span>{{ detailItem.prompt }}</span></div>
          <div class="info-row"><span class="label">类型：</span><span>{{ detailItem.type === 'image' ? '图片' : '视频' }}</span></div>
          <div class="info-row" v-if="detailItem.model"><span class="label">模型：</span><span>{{ detailItem.model }}</span></div>
          <div class="info-row"><span class="label">状态：</span><span>{{ detailItem.status || 'success' }}</span></div>
          <div class="info-row"><span class="label">创建时间：</span><span>{{ detailItem.created_at }}</span></div>
          <div class="info-row url-row">
            <span class="label">链接：</span>
            <span class="url-value">{{ detailItem.result_url }}</span>
            <el-button size="small" link type="primary" @click="copyLink(detailItem.result_url)">复制链接</el-button>
            <el-button size="small" link type="primary" @click="downloadDetail">下载</el-button>
            <el-button size="small" link type="primary" @click="openInNewTab">新标签页打开</el-button>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button type="danger" :icon="Delete" @click="confirmDelete">删除此记录</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="deleteVisible"
      title="确认删除"
      width="400px">
      <div>确定要删除这条记录吗？此操作不可撤销。</div>
      <template #footer>
        <el-button @click="deleteVisible = false">取消</el-button>
        <el-button type="danger" @click="doDelete">确认删除</el-button>
      </template>
    </el-dialog>

    <!-- 批量删除确认弹窗 -->
    <el-dialog
      v-model="batchDeleteVisible"
      title="确认批量删除"
      width="460px">
      <div>
        确定要删除已选中的 <b style="color:#ff9b9b">{{ selectedIds.length }}</b> 条记录吗？此操作不可撤销。
      </div>
      <template #footer>
        <el-button @click="batchDeleteVisible = false">取消</el-button>
        <el-button type="danger" :loading="batchDeleting" @click="doBatchDelete">
          确认删除 ({{ selectedIds.length }})
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Loading, Document, Delete, VideoPlay, CircleCloseFilled, Edit, Close } from '@element-plus/icons-vue'
import { getHistoryList, deleteHistoryRecord, batchDeleteHistory } from '@/api/history'

const list = ref([])
const loading = ref(false)
const totalCount = ref(0)
const imageCount = ref(0)
const videoCount = ref(0)
const page = ref(1)
const pageSize = ref(12)
const filterType = ref('all')

const detailVisible = ref(false)
const deleteVisible = ref(false)
const detailItem = ref(null)
const detailVideoEl = ref(null)     // 详情弹窗中的 video 元素
const detailPoster = ref('')         // 详情弹窗的视频首帧缩略图
const detailVideoLoading = ref(false) // 视频加载中状态
const detailVideoFailed = ref(false)  // 视频加载失败状态

// ---------- 视频缩略图 & 预览相关状态 ----------
const videoThumbnails = reactive({})  // 视频首帧缩略图 URL 映射 { id: url }
const videoPreviews = reactive({})    // 视频 GIF 预览 URL 映射 { id: url }
const hoveredVideoId = ref(null)      // 当前鼠标悬停的视频卡片 ID
const thumbnailLoading = reactive({}) // 缩略图加载中状态 { id: boolean }
const previewLoading = reactive({})   // 预览 GIF 加载中状态 { id: boolean }
const thumbnailFailed = reactive({})  // 缩略图加载失败 { id: boolean }

// ---------- 编辑 / 多选删除相关状态 ----------
const editMode = ref(false)              // 是否进入编辑模式
const selectedIds = ref([])              // 当前已选中的记录 ID 列表
const batchDeleteVisible = ref(false)    // 批量删除确认弹窗
const batchDeleting = ref(false)         // 批量删除加载状态

// 计算属性：当前页是否全选 / 是否半选
const isAllSelected = computed(() => {
  if (!list.value.length) return false
  return list.value.every(item => selectedIds.value.includes(item.id))
})
const isIndeterminate = computed(() => {
  if (!list.value.length) return false
  const pageIds = list.value.map(item => item.id)
  const selectedOnPage = pageIds.filter(id => selectedIds.value.includes(id))
  return selectedOnPage.length > 0 && selectedOnPage.length < pageIds.length
})

/**
 * 获取视频播放 URL：优先使用后端代理接口，解决 CORS 和 Range 请求问题
 */
function getVideoStreamUrl(item) {
  if (item.type !== 'video' || !item.result_url) return ''
  // 使用后端代理接口播放视频
  return `/api/history/video/${item.id}/stream`
}

// ---------- 视频缩略图 & 预览方法 ----------

/**
 * 生成简单的哈希值（用于缓存破坏）
 */
function simpleHash(str) {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i)
    hash = ((hash << 5) - hash) + char
    hash |= 0 // 转为 32 位整数
  }
  return Math.abs(hash).toString(36)
}

/**
 * 加载视频首帧缩略图
 */
async function loadVideoThumbnail(item) {
  if (videoThumbnails[item.id] || thumbnailLoading[item.id] || thumbnailFailed[item.id]) return
  thumbnailLoading[item.id] = true
  try {
    // URL 中加入视频链接哈希作为缓存破坏参数，避免删除旧记录后新记录复用 ID 时命中浏览器缓存
    const urlHash = item.result_url ? simpleHash(item.result_url) : 'nourl'
    const url = `/api/history/video/${item.id}/thumbnail?v=${urlHash}`
    // 用 Image 对象预加载，验证图片是否可用
    await new Promise((resolve, reject) => {
      const img = new Image()
      img.onload = resolve
      img.onerror = reject
      img.src = url
    })
    videoThumbnails[item.id] = url
  } catch (e) {
    console.warn('[History] 视频缩略图加载失败 id=' + item.id, e)
    thumbnailFailed[item.id] = true
  } finally {
    thumbnailLoading[item.id] = false
  }
}

/**
 * 加载视频 GIF 预览
 */
async function loadVideoPreview(item) {
  if (videoPreviews[item.id] || previewLoading[item.id]) return
  previewLoading[item.id] = true
  try {
    // URL 中加入视频链接哈希作为缓存破坏参数
    const urlHash = item.result_url ? simpleHash(item.result_url) : 'nourl'
    const url = `/api/history/video/${item.id}/preview?v=${urlHash}`
    // 用 Image 对象预加载 GIF
    await new Promise((resolve, reject) => {
      const img = new Image()
      img.onload = resolve
      img.onerror = reject
      img.src = url
    })
    videoPreviews[item.id] = url
  } catch (e) {
    console.warn('[History] 视频预览 GIF 加载失败 id=' + item.id, e)
  } finally {
    previewLoading[item.id] = false
  }
}

/**
 * 鼠标悬停视频卡片：显示 GIF 预览
 */
function onVideoCardHover(item) {
  hoveredVideoId.value = item.id
  // 延迟加载 GIF 预览（避免一进入页面就加载所有 GIF）
  loadVideoPreview(item)
}

/**
 * 鼠标离开视频卡片：隐藏 GIF 预览
 */
function onVideoCardLeave(item) {
  hoveredVideoId.value = null
}

// 打开详情弹窗时重置视频状态
watch(detailVisible, (val) => {
  if (val) {
    detailPoster.value = ''
    detailVideoLoading.value = detailItem.value?.type === 'video' && !!detailItem.value?.result_url
    detailVideoFailed.value = false
  }
})

// ---------- 加载列表 ----------
async function loadList(resetPage = false) {
  if (resetPage) page.value = 1
  loading.value = true
  try {
    const data = await getHistoryList({
      type: filterType.value,
      page: page.value,
      page_size: pageSize.value
    })
    list.value = data.items || []
    totalCount.value = data.total || list.value.length
    // 使用后端返回的全局类型计数（不受筛选条件和分页影响）
    imageCount.value = data.total_image_count ?? 0
    videoCount.value = data.total_video_count ?? 0
    // 自动加载视频首帧缩略图（不阻塞列表渲染）
    list.value.filter(i => i.type === 'video').forEach(item => {
      loadVideoThumbnail(item)
    })
  } catch (e) {
    console.error('[History] 加载失败：', e)
  } finally {
    loading.value = false
  }
}

function handlePageChange(p) {
  page.value = p
  loadList()
}
function handleSizeChange(size) {
  pageSize.value = size
  page.value = 1
  loadList()
}

// ---------- 详情操作 ----------
function showDetail(item) {
  detailItem.value = item
  detailPoster.value = ''
  detailVideoLoading.value = item.type === 'video' && !!item.result_url
  detailVideoFailed.value = false
  detailVisible.value = true
}

// ---------- 编辑 / 多选删除方法 ----------
/**
 * 切换编辑模式
 */
function toggleEditMode() {
  editMode.value = !editMode.value
  if (!editMode.value) {
    // 退出编辑模式时清空已选
    selectedIds.value = []
  }
}

/**
 * 卡片点击：编辑模式下切换选择，否则打开详情
 */
function handleCardClick(item) {
  if (editMode.value) {
    toggleSelect(item.id)
  } else {
    showDetail(item)
  }
}

/**
 * 切换单条记录的选中状态
 */
function toggleSelect(id) {
  const idx = selectedIds.value.indexOf(id)
  if (idx >= 0) {
    selectedIds.value.splice(idx, 1)
  } else {
    selectedIds.value.push(id)
  }
}

/**
 * 切换全选当前页
 */
function toggleSelectAll(val) {
  if (val) {
    // 全选：将当前页所有 ID 合并到 selectedIds
    const pageIds = list.value.map(item => item.id)
    const newSet = new Set(selectedIds.value)
    pageIds.forEach(id => newSet.add(id))
    selectedIds.value = Array.from(newSet)
  } else {
    // 取消全选：从 selectedIds 中移除当前页所有 ID
    const pageIds = new Set(list.value.map(item => item.id))
    selectedIds.value = selectedIds.value.filter(id => !pageIds.has(id))
  }
}

/**
 * 打开批量删除确认弹窗
 */
function confirmBatchDelete() {
  if (selectedIds.value.length === 0) {
    ElMessage.warning('请至少选择一条记录')
    return
  }
  batchDeleteVisible.value = true
}

/**
 * 执行批量删除
 */
async function doBatchDelete() {
  if (selectedIds.value.length === 0) return
  batchDeleting.value = true
  try {
    const res = await batchDeleteHistory(selectedIds.value)
    const deletedCount = res?.deleted_count ?? selectedIds.value.length
    ElMessage.success(`已成功删除 ${deletedCount} 条记录`)
    batchDeleteVisible.value = false
    selectedIds.value = []
    // 删除后重新加载列表
    loadList()
  } catch (e) {
    // 错误已在拦截器弹出
  } finally {
    batchDeleting.value = false
  }
}

// ---------- 详情其它操作 ----------

/**
 * 通用复制文本到剪贴板（兼容非安全上下文降级方案）
 */
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
  try { ok = document.execCommand('copy') } catch (e) { ok = false }
  document.body.removeChild(ta)
  return ok ? Promise.resolve() : Promise.reject(new Error('copy failed'))
}

function copyLink(url) {
  if (!url) {
    ElMessage.warning('此记录无有效链接')
    return
  }
  copyToClipboard(url)
    .then(() => ElMessage.success('链接已复制到剪贴板'))
    .catch(() => ElMessage.error('复制失败，请手动选择链接文本复制'))
}

/**
 * 下载资源：优先 fetch + Blob 下载（同源/带 CORS 头），失败回退为新标签页打开
 */
async function downloadDetail() {
  if (!detailItem.value?.result_url) {
    ElMessage.warning('此记录无有效资源链接')
    return
  }
  const url = detailItem.value.result_url
  const type = detailItem.value.type
  try {
    ElMessage.info('正在准备下载，请稍候…')
    const response = await fetch(url, { mode: 'cors' })
    if (!response.ok) throw new Error('HTTP ' + response.status)
    const blob = await response.blob()
    const blobUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = blobUrl
    a.download = 'agnes-' + type + '-' + (detailItem.value.id || Date.now())
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    setTimeout(() => URL.revokeObjectURL(blobUrl), 1000)
    ElMessage.success('已开始下载')
  } catch (err) {
    console.warn('[History] fetch 下载失败，回退为新标签页打开：', err)
    ElMessage.warning('跨域下载受限，已在新标签页打开。请右键并选择「另存为」。')
    window.open(url, '_blank', 'noopener,noreferrer')
  }
}

/**
 * 在新标签页直接打开资源链接
 */
function openInNewTab() {
  if (!detailItem.value?.result_url) {
    ElMessage.warning('此记录无有效资源链接')
    return
  }
  window.open(detailItem.value.result_url, '_blank', 'noopener,noreferrer')
  ElMessage.success('已在新标签页打开')
}

/**
 * 详情弹窗中视频 loadeddata：canvas 截取首帧作为 poster
 */
function captureDetailPoster() {
  const el = detailVideoEl.value
  if (!el || !el.videoWidth || detailPoster.value) return
  try {
    const canvas = document.createElement('canvas')
    const scale = Math.min(1, 720 / el.videoWidth)
    canvas.width = Math.floor(el.videoWidth * scale)
    canvas.height = Math.floor(el.videoHeight * scale)
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.drawImage(el, 0, 0, canvas.width, canvas.height)
    detailPoster.value = canvas.toDataURL('image/jpeg', 0.82)
  } catch (e) {
    console.warn('[History] canvas 截图失败（可能跨域污染）：', e)
  }
}

/**
 * 视频可以播放时清除加载状态
 */
function onDetailVideoCanPlay() {
  detailVideoLoading.value = false
  detailVideoFailed.value = false
}

/**
 * 视频加载失败
 */
function onDetailVideoError(e) {
  console.error('[History] 视频加载/播放失败：', e)
  detailVideoLoading.value = false
  detailVideoFailed.value = true
  ElMessage.error('视频加载失败，请尝试「下载」或「新标签页打开」')
}

/**
 * 视频加载被中止（通常是 Range 请求 206 失败或跨域问题）
 */
function onDetailVideoAbort() {
  console.warn('[History] 视频加载被中止，尝试重新加载')
  detailVideoLoading.value = false
  detailVideoFailed.value = true
  ElMessage.warning('视频播放受限，请尝试「下载」或「新标签页打开」')
}

function confirmDelete() {
  deleteVisible.value = true
}
async function doDelete() {
  if (!detailItem.value) return
  try {
    await deleteHistoryRecord(detailItem.value.id)
    ElMessage.success('已删除')
    deleteVisible.value = false
    detailVisible.value = false
    loadList()
  } catch (e) {
    // 错误已在拦截器弹出
  }
}

// ---------- 工具函数 ----------
function truncate(text, max) {
  if (!text) return ''
  return text.length > max ? text.slice(0, max) + '…' : text
}
function formatTime(t) {
  if (!t) return ''
  const d = new Date(t)
  if (isNaN(d.getTime())) return String(t).slice(0, 19)
  return d.toLocaleString()
}

onMounted(() => loadList())
</script>

<style scoped>
.history-view { color: #e8eef7; }

.filter-wrap {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding: 12px 16px;
  background: rgba(15, 24, 42, 0.5);
  border-radius: 10px;
  border: 1px solid rgba(120, 170, 255, 0.15);
}

/* 右侧动作按钮区域（刷新 + 编辑） */
.filter-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

/* 编辑模式工具条 */
.edit-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  margin-bottom: 16px;
  background: rgba(60, 30, 30, 0.45);
  border: 1px solid rgba(255, 155, 155, 0.25);
  border-radius: 10px;
}
.edit-left {
  display: flex;
  align-items: center;
  gap: 16px;
  color: #d5e3f7;
}
.selection-info {
  font-size: 13px;
  color: #8ba3c9;
}
.selection-count {
  color: #ff9b9b;
  font-size: 15px;
}
.edit-right {
  display: flex;
  gap: 10px;
}

.loading-state, .empty-state {
  padding: 80px 20px;
  text-align: center;
  color: #6b84aa;
}
.spinner { animation: spin 1.2s linear infinite; color: #6b9cff; }
@keyframes spin { to { transform: rotate(360deg); } }
.empty-text { margin-top: 16px; font-size: 14px; }

.history-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 18px;
}
.history-card {
  background: rgba(15, 24, 42, 0.7);
  border: 1px solid rgba(120, 170, 255, 0.15);
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
}
/* 编辑模式选中状态 */
.history-card.is-selected {
  border-color: rgba(255, 155, 155, 0.75);
  box-shadow: 0 0 0 2px rgba(255, 155, 155, 0.4), 0 8px 24px rgba(100, 150, 255, 0.2);
  transform: translateY(-2px);
}
/* 卡片左上角的选择框 */
.card-checkbox {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 2;
  padding: 6px 8px;
  background: rgba(15, 24, 42, 0.7);
  border-radius: 8px;
  border: 1px solid rgba(120, 170, 255, 0.2);
  cursor: pointer;
}
.history-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 32px rgba(100, 150, 255, 0.25);
  border-color: rgba(120, 170, 255, 0.4);
}
/* 编辑模式下的 hover 去掉位移，避免与选中效果冲突 */
.history-card.is-selected:hover {
  transform: translateY(-2px);
}
.card-preview {
  position: relative;
  width: 100%;
  aspect-ratio: 4/3;
  background: #0a1220;
  overflow: hidden;
}
.card-preview img,
.card-preview video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
/* 视频卡片：首帧缩略图 + 悬停 GIF 预览 */
.video-thumb {
  width: 100%;
  height: 100%;
  position: relative;
  background: linear-gradient(135deg, #1a2744 0%, #0f1a30 100%);
  overflow: hidden;
}
/* 首帧缩略图 */
.video-thumb-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: opacity 0.3s ease;
}
/* 缩略图加载失败时的占位 */
.video-thumb-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #8ba3c9;
}
.video-thumb-placeholder .play-icon {
  color: #6b9cff;
  filter: drop-shadow(0 4px 12px rgba(107, 156, 255, 0.4));
}
.video-thumb-label {
  font-size: 13px;
  font-weight: 500;
}
/* 悬停时的 GIF 预览层 */
.video-preview-gif {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  z-index: 1;
}
/* 播放图标蒙层 */
.video-play-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.25);
  z-index: 2;
  transition: opacity 0.2s ease;
  color: rgba(255, 255, 255, 0.85);
}
.video-play-overlay .el-icon {
  filter: drop-shadow(0 2px 8px rgba(0, 0, 0, 0.5));
}
/* 悬停时隐藏播放蒙层，显示 GIF */
.video-thumb:hover .video-play-overlay {
  opacity: 0;
}
.video-thumb:hover .video-thumb-img {
  opacity: 0;
}
.type-badge {
  position: absolute;
  top: 10px;
  left: 10px;
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
  background: rgba(15, 24, 42, 0.75);
  backdrop-filter: blur(4px);
}
.type-badge.image { color: #8bb4ff; border: 1px solid rgba(139, 180, 255, 0.5); }
.type-badge.video { color: #c4a7ff; border: 1px solid rgba(196, 167, 255, 0.5); }
.card-meta { padding: 12px 14px; }
.card-prompt {
  font-size: 13px;
  color: #d5e3f7;
  line-height: 1.5;
  min-height: 40px;
  overflow: hidden;
}
.card-time {
  margin-top: 8px;
  font-size: 12px;
  color: #6b84aa;
}

.pagination-wrap {
  margin-top: 24px;
  text-align: center;
}

/* 详情弹窗 */
.detail-content { display: flex; gap: 24px; flex-direction: column; align-items: center; }
.detail-media { width: 100%; text-align: center; }
.detail-media img {
  max-width: 100%;
  max-height: 400px;
  border-radius: 10px;
  object-fit: contain;
}
.detail-media video {
  max-width: 100%;
  max-height: 400px;
  border-radius: 10px;
  background: #000;
}
.detail-info {
  width: 100%;
  background: rgba(15, 24, 42, 0.5);
  padding: 16px;
  border-radius: 10px;
}
.info-row { padding: 6px 0; font-size: 13px; line-height: 1.6; color: #d5e3f7; }
.label { color: #8ba3c9; margin-right: 8px; font-weight: 500; }
.url-row {
  margin-top: 8px;
  padding: 12px !important;
  background: rgba(10, 20, 40, 0.6);
  border: 1px solid rgba(120, 170, 255, 0.15);
  border-radius: 8px;
  word-break: break-all;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.url-row .url-value {
  color: #d5e3f7;
  font-family: monospace;
  font-size: 12px;
  max-width: 100%;
  flex: 1;
  min-width: 200px;
}
.detail-video {
  max-width: 100%;
  max-height: 400px;
  border-radius: 10px;
  background: #000;
}

/* 视频容器（包含状态蒙层） */
.detail-video-wrap {
  position: relative;
  width: 100%;
  max-width: 100%;
}

/* 无链接时的占位提示 */
.detail-video-empty {
  padding: 40px 20px;
  background: #0a1220;
  border-radius: 10px;
  text-align: center;
  color: #8ba3c9;
  font-size: 13px;
}
.detail-video-empty div { margin-top: 10px; }

/* 视频状态蒙层（加载中/失败） */
.detail-video-status {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: rgba(0, 0, 0, 0.72);
  border-radius: 10px;
  color: #d5e3f7;
  font-size: 13px;
  pointer-events: none;
}
.detail-video-status.error {
  color: #ff9b9b;
}

/* 旋转加载图标 */
.spinner {
  display: inline-block;
  animation: spin 1.2s linear infinite;
  color: #6b9cff;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
