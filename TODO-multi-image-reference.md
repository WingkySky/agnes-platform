# 多图参考图生图（Multi-Image Reference for Image-to-Image）改造计划

> 版本：1.0
> 日期：2026-06-12
> 目标：让聊天 / 独立生图页面能上传「多张参考图」一起送入 Agnes API（`extra_body.image: [...]` 数组），实现多图合成效果。
> Agnes 官方能力：Agnes Image 2.0 / 2.1 Flash 原生支持 `extra_body.image` 为「图像 URL 数组」，每张图作为参考图一起传入。
> 手动测试结论：聊天里手动粘贴多张图，Agnes 实际能够进行多图合成。当前代码瓶颈是我们自己在「取附件 → 调 API」的链路上硬编码只取 1 张。

---

## 0. 改造范围总览

| # | 文件 | 改动类型 | 核心变更 |
|---|------|----------|----------|
| 1 | `backend/app/schemas/images.py` | Schema 扩展 | 新增 `base64_images` / `image_urls` 数组字段，保留旧字段做兼容 |
| 2 | `backend/app/services/agnes_client.py` | 客户端扩展 | `create_image()` 支持多图数组，统一打包进 `extra_body.image` |
| 3 | `backend/app/services/chat_service.py` | 工具执行层 | `_execute_generate_image` 遍历全部附件，不再只取第一张 |
| 4 | `backend/app/routes/images.py` | API 路由层 | 异步任务 + 同步接口透传多图数组参数 |
| 5 | `frontend/src/components/ImageUploader.vue` | 组件重写 | 单图 → 多图：多选文件 / 多 URL / 网格预览 / 逐个删除 |
| 6 | `frontend/src/views/ChatView.vue` | 页面适配 | 聊天上传区默认使用多图版 `ImageUploader` |
| 7 | `frontend/src/views/ImageView.vue` | 页面适配 | 独立生图页 `fileInfo` → `fileInfoList`，提交时提交数组 |

**向后兼容**：所有旧字段保留。旧前端 / 旧代码调用 → 自动合并到数组 → 旧逻辑完全不受影响。

---

## 1. 当前问题定位（需要替换的代码段落）

### 1.1 瓶颈一：chat_service 只取第一张附件

文件：`backend/app/services/chat_service.py`
方法：`_execute_generate_image`
位置：约 L1252–L1265（搜索 `ref = effective_attachments[0]`）

```python
# ── 当前代码（单图） ──
ref_images = attachments[:1]   # 只取 1 张
# ...
ref = effective_attachments[0] # 只取第一张
if ref.get("image_url"):
    params["image_url"] = ref["image_url"]
elif ref.get("base64_image") and ref["base64_image"].startswith("data:image/"):
    params["base64_image"] = ref["base64_image"]
```

### 1.2 瓶颈二：agnes_client 只支持单图参数

文件：`backend/app/services/agnes_client.py`
方法：`create_image`
位置：约 L131–L203

```python
# ── 当前方法签名 ──
async def create_image(
    self,
    prompt: str,
    model: str = "agnes-image-2.1-flash",
    size: str = "1024x1024",
    response_format: str = "url",
    base64_image: Optional[str] = None,   # ← 单字符串
    image_url: Optional[str] = None,       # ← 单字符串
    quality: str = "standard",
) -> Dict[str, Any]:

# ── 当前 extra_body 构造 ──
ref_image = base64_image or image_url
if ref_image:
    extra["image"] = [image_value]  # 虽然是数组，但只有 1 个元素
```

### 1.3 瓶颈三：images Schema 只有单图字段

文件：`backend/app/schemas/images.py`
位置：约 L21–L29

```python
# ── 当前字段 ──
base64_image: Optional[str] = Field(default=None, description="参考图片 (base64, 可选)")
image_url: Optional[str]     = Field(default=None, description="参考图片 URL (可选)")
```

### 1.4 瓶颈四：ImageUploader 组件是单图设计

文件：`frontend/src/components/ImageUploader.vue`
数据结构：`const currentFile = ref(null)`（单个对象）
上传 input：`<input type="file" accept="image/*">`（无 `multiple`）

---

## 2. 详细改造步骤

### 2.1 Schema 层：`backend/app/schemas/images.py`

**目标**：新增多图数组字段，同时保留旧字段并提供合并方法。

**完整修改内容**：

```python
# =================== 文件顶部（import 区） ===================
# 确保存在：
from typing import List, Optional

# =================== ImageGenerationRequest 类 ===================
class ImageGenerationRequest(BaseModel):
    """图片生成请求体（支持 text2image 和 image2image）"""

    prompt: str = Field(..., min_length=1, max_length=2000, description="用于图片生成的提示词")
    model: str = Field(default="agnes-image-2.1-flash", description="图片模型名称")
    size: str = Field(default="1024x1024", description="图片尺寸 (宽x高)")
    response_format: str = Field(default="url", description="返回格式 (url 或 b64_json)")
    quality: Optional[str] = Field(default="standard", description="图片质量 (standard/hd)")

    # ── 新字段：多图参考（推荐使用） ──
    base64_images: Optional[List[str]] = Field(
        default=None,
        description="图生图时的多张参考图片(base64 data URI 或纯 base64 字符串), 支持多张",
    )
    image_urls: Optional[List[str]] = Field(
        default=None,
        description="图生图时的多张参考图片 URL(公网可访问), 支持多张",
    )

    # ── 旧字段：单图参考（保留以保持向后兼容，内部会自动合并到数组） ──
    base64_image: Optional[str] = Field(
        default=None,
        description="【旧字段，兼容用】单张参考图片 base64；新代码请使用 base64_images",
    )
    image_url: Optional[str] = Field(
        default=None,
        description="【旧字段，兼容用】单张参考图片 URL；新代码请使用 image_urls",
    )

    @property
    def all_reference_images(self) -> List[str]:
        """
        合并新旧字段，返回统一的参考图列表（每个元素是 data URI 或公网 URL）。
        优先级：新字段数组 > 旧字段单值。
        """
        result: List[str] = []
        # 新字段优先
        if self.base64_images:
            for img in self.base64_images:
                if img and isinstance(img, str) and img.strip():
                    result.append(img)
        if self.image_urls:
            for url in self.image_urls:
                if url and isinstance(url, str) and url.strip():
                    result.append(url)
        # 如果新字段为空，回退到旧字段
        if not result:
            if self.base64_image and self.base64_image.strip():
                result.append(self.base64_image)
            if self.image_url and self.image_url.strip():
                result.append(self.image_url)
        return result

    @property
    def is_image_to_image(self) -> bool:
        """是否为图生图（只要有任何参考图即判定为 yes）"""
        return len(self.all_reference_images) > 0
```

---

### 2.2 API 客户端：`backend/app/services/agnes_client.py`

**目标**：`create_image()` 能接收多图数组，并打包进 `extra_body.image`。

**修改内容**：

```python
# =================== 方法签名（替换原签名） ===================
async def create_image(
    self,
    prompt: str,
    model: str = "agnes-image-2.1-flash",
    size: str = "1024x1024",
    response_format: str = "url",
    base64_image: Optional[str] = None,      # 保留：向后兼容（单图）
    image_url: Optional[str] = None,          # 保留：向后兼容（单图）
    base64_images: Optional[List[str]] = None,  # 【新增】多图 base64 数组
    image_urls: Optional[List[str]] = None,     # 【新增】多图 URL 数组
    quality: str = "standard",
) -> Dict[str, Any]:

# =================== 参数校验区（在已有 size 校验后追加） ===================
    # 参数: 参考图（【新】多图数组优先，然后回退到旧字段）
    ref_images: List[str] = []
    if base64_images:
        for img in base64_images:
            if img and isinstance(img, str) and img.strip():
                ref_images.append(img)
    if image_urls:
        for url in image_urls:
            if url and isinstance(url, str) and url.strip():
                ref_images.append(url)
    # 如果新字段没提供，回退到旧字段
    if not ref_images and base64_image and base64_image.strip():
        ref_images.append(base64_image)
    if not ref_images and image_url and image_url.strip():
        ref_images.append(image_url)

# =================== extra_body 构造（替换原单图逻辑） ===================
    if ref_images:
        # 统一规范化：data URI / URL → 原封不动；纯 base64 → 补 data:image/png;base64, 前缀
        normalized = []
        for img in ref_images:
            if img.startswith("data:") or img.startswith("http://") or img.startswith("https://"):
                normalized.append(img)
            else:
                normalized.append(f"data:image/png;base64,{img}")

        extra = {
            "image": normalized,                    # 【关键】这里是数组，Agnes API 原生支持
            "response_format": response_format,
        }
        # 日志：明确打出参考图张数，方便排查
        logger.info(
            "[图片生成] 图生图模式: model=%s, size=%s, ref_images=%d 张, prompt=%s",
            model, size, len(normalized), prompt[:80]
        )
    elif response_format == "b64_json":
        body["return_base64"] = True
        logger.info("[图片生成] 文生图模式(b64_json): model=%s, size=%s, prompt=%s",
                    model, size, prompt[:80])
    else:
        logger.info("[图片生成] 文生图模式: model=%s, size=%s, prompt=%s",
                    model, size, prompt[:80])
```

---

### 2.3 工具执行层：`backend/app/services/chat_service.py`

**目标**：`_execute_generate_image` 不再只取第一张附件，而是收集全部附件为数组。

**替换位置**：`_execute_generate_image` 中搜索 `ref = effective_attachments[0]` 这一段。

**替换内容**：

```python
    # =================== 收集参考图（替换原单图逻辑） ===================
    # 旧代码（删除）:
    #   ref = effective_attachments[0]
    #   if ref.get("image_url"):
    #       params["image_url"] = ref["image_url"]
    #   elif ref.get("base64_image") and ref["base64_image"].startswith("data:image/"):
    #       params["base64_image"] = ref["base64_image"]

    # ── 新代码：遍历全部附件，收集为数组 ──
    b64_list: List[str] = []
    url_list: List[str] = []

    for ref in effective_attachments:
        img_url = ref.get("image_url")
        b64_img = ref.get("base64_image")

        # 本次上传的图：优先走 image_url（公网 URL 体积小、稳定）
        if img_url and isinstance(img_url, str) and img_url.strip():
            url_list.append(img_url)
            continue

        # 历史对话中的图（已经是 URL 或 data URI）
        if b64_img and isinstance(b64_img, str) and b64_img.strip():
            if b64_img.startswith("data:image/") or b64_img.startswith("http"):
                b64_list.append(b64_img)
                continue

        # 兜底：纯 base64 字符串（没有前缀）
        if b64_img and isinstance(b64_img, str) and b64_img.strip():
            b64_list.append(b64_img)

    # 注入到 create_image 的新参数（与 2.2 中扩展的签名对齐）
    if b64_list:
        params["base64_images"] = b64_list
    if url_list:
        params["image_urls"] = url_list

    # 日志：明确打出「共收集 N 张参考图」，方便验证
    logger.info(
        "[Chat] 图生图参考图汇总: base64=%d 张, url=%d 张, 总计=%d 张",
        len(b64_list), len(url_list), len(b64_list) + len(url_list)
    )
```

**同时注意**：`_execute_generate_image` 上方可能有 `ref_images = attachments[:1]` 之类的代码，如果有，把 `[:1]` 删掉，改为使用全量 `attachments`。

---

### 2.4 API 路由层：`backend/app/routes/images.py`

**目标**：异步任务 + 同步接口都能把多图数组传给 `agnes_client.create_image`。

**修改点一**：异步任务处理函数 `create_image_task_async`（约 L58–L75）

```python
# 在「# 参数: 图生图模式」之后，把原单图逻辑替换为：
if req.is_image_to_image:
    ref_imgs = req.all_reference_images            # 这里拿到的就是合并后的数组
    b64_imgs = [img for img in ref_imgs if not img.startswith("http")]
    url_imgs = [img for img in ref_imgs if img.startswith("http")]
    if b64_imgs:
        params["base64_images"] = b64_imgs
    if url_imgs:
        params["image_urls"] = url_imgs
    logger.info("[图片API] 异步图生图任务: ref_images=%d 张, size=%s, model=%s",
                len(ref_imgs), req.size, req.model)
```

**修改点二**：同步生成接口 `create_image_generation`（约 L162–L171）

```python
if req.is_image_to_image:
    ref_imgs = req.all_reference_images
    params["base64_images"] = [img for img in ref_imgs if not img.startswith("http")] or None
    params["image_urls"]    = [img for img in ref_imgs if img.startswith("http")] or None
    # 过滤掉 None
    params = {k: v for k, v in params.items() if v is not None}
    logger.info("[图片API] 同步图生图请求: ref_images=%d 张", len(ref_imgs))
```

---

### 2.5 前端组件：`frontend/src/components/ImageUploader.vue`

**目标**：从「单图上传」改造成「多图上传 + 网格预览 + 逐个删除」。

**完整改造要点**（按区块替换）：

```vue
<!-- =================== (A) 数据结构 =================== -->
<!-- 旧（删除）: const currentFile = ref<FileInfo | null>(null) -->
<!-- 新： -->
const fileList = ref<FileInfo[]>([])       // 数组！
const urlInput = ref('')

// 对外暴露只读属性（供父组件用）
defineExpose({
  getFiles: () => fileList.value,           // 返回数组
  clearFiles: () => { fileList.value = []; emit('change', null) },
})

<!-- =================== (B) 文件选择 input =================== -->
<!-- 旧：<input type="file" accept="image/*" @change="handleFileChange"> -->
<!-- 新：加 multiple -->
<input
  ref="fileInput"
  type="file"
  accept="image/*"
  multiple                                  <!-- 允许选多张 -->
  class="hidden-input"
  @change="handleFilesChange"
/>

<!-- =================== (C) handleFileChange → handleFilesChange =================== -->
async function handleFilesChange(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (files.length === 0) return

  let added = 0
  for (const file of files) {
    if (!validateFile(file)) continue
    try {
      const info = await fileToBase64(file)
      fileList.value.push(info)                 <!-- push 追加 -->
      added++
    } catch (err) {
      ElMessage.error(`${file.name} 读取失败`)
    }
  }
  if (added > 0) {
    ElMessage.success(`已添加 ${added} 张图片 (共 ${fileList.value.length} 张)`)
  }
  emitChange()
  if (input) input.value = ''                  <!-- 清空 input, 允许再次选同文件 -->
}

<!-- =================== (D) handleUrlConfirm =================== -->
<!-- 旧逻辑（覆盖 currentFile）改为 push 追加 -->
function handleUrlConfirm() {
  const url = urlInput.value.trim()
  if (!url) return
  if (!/^https?:\/\//i.test(url)) {
    ElMessage.error('URL 格式错误, 请输入 http(s):// 开头的 URL')
    return
  }
  fileList.value.push({
    name: url.split('/').pop() || 'image',
    base64: null,
    previewUrl: url,
    size: null,
    source: 'url' as FileSource,
    url,
  })
  urlInput.value = ''
  ElMessage.success(`已添加 URL 图片 (共 ${fileList.value.length} 张)`)
  emitChange()
}

<!-- =================== (E) 新增：单张删除 =================== -->
function removeFile(index: number) {
  const name = fileList.value[index]?.name
  fileList.value.splice(index, 1)
  if (name) ElMessage.info(`已移除: ${name}`)
  emitChange()
}

function emitChange() {
  emit('change', fileList.value.length ? fileList.value : null)
}

<!-- =================== (F) 预览渲染：改为 v-for 网格 =================== -->
<!-- 旧：<div v-if="currentFile" class="file-preview"> 单张 -->
<!-- 新：网格 -->
<div v-if="fileList.length > 0" class="file-grid">
  <div v-for="(file, idx) in fileList" :key="idx" class="file-card">
    <img :src="file.previewUrl" class="file-preview-img" @click="openPreview(file.previewUrl)" />
    <div class="file-meta">
      <div class="file-name" :title="file.name">{{ truncateName(file.name, 22) }}</div>
      <div v-if="file.size" class="file-size">{{ formatSize(file.size) }}</div>
      <div class="file-source">{{ file.source === 'url' ? 'URL' : '本地' }}</div>
    </div>
    <el-button size="small" type="danger" plain @click="removeFile(idx)" class="del-btn">
      删除
    </el-button>
  </div>
</div>
```

**还需要加一点 CSS（追加到 `</style>` 之前）**：

```css
.file-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.file-card {
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 8px;
  padding: 8px;
  background: var(--bg-muted, #f9fafb);
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
.file-meta { margin-top: 6px; font-size: 12px; text-align: center; }
.file-name { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-size { color: var(--text-muted, #6b7280); }
.file-source { color: var(--primary, #2563eb); font-size: 11px; }
.del-btn { margin-top: 6px; }
```

---

### 2.6 页面适配：`frontend/src/views/ImageView.vue`

**目标**：独立生图页面的 `fileInfo`（单对象）改为 `fileInfoList`（数组），提交时提交多图数组。

**关键修改**：

```js
// ① 替换 data：
//   旧: const fileInfo = ref<FileInfo | null>(null)
//   新:
const fileInfoList = ref<FileInfo[]>([])

// ② 替换 ImageUploader 的事件接收：
//   旧: <ImageUploader ref="uploader" @change="(f) => fileInfo = f" />
//   新:
//   <ImageUploader ref="uploader" @change="handleFileListChange" />
function handleFileListChange(list) {
  fileInfoList.value = Array.isArray(list) ? list : (list ? [list] : [])
}

// ③ 替换 handleGenerate 的参数构造：
//   旧: payload.base64_image = fileInfo.value.base64
//   新:
if (fileInfoList.value.length > 0) {
  const b64Imgs = fileInfoList.value
    .filter(f => f.source === 'file' && f.base64)
    .map(f => f.base64 as string)
  const urlImgs = fileInfoList.value
    .filter(f => f.source === 'url' && f.url)
    .map(f => f.url as string)
  if (b64Imgs.length) payload.base64_images = b64Imgs
  if (urlImgs.length) payload.image_urls = urlImgs
}

// ④ isImageToImage 判断：
//   旧: const isImageToImage = computed(() => !!fileInfo.value)
//   新:
const isImageToImage = computed(() => fileInfoList.value.length > 0)
```

---

### 2.7 页面适配：`frontend/src/views/ChatView.vue`

**目标**：聊天框的图片上传逻辑，确认传入的是附件数组（Schema 已经天然支持 attachments 数组，这里只要确认 `ImageUploader` 是多图版即可）。

关键点检查：
- `const attachments = ref<Attachment[]>([])` 已经是数组 ✓
- 把 `ImageUploader` 替换为新的多图版后，`handleImageUploaded(fileInfo)` 的逻辑改为：

```js
function handleImageUploaded(fileOrList) {
  const list = Array.isArray(fileOrList) ? fileOrList : (fileOrList ? [fileOrList] : [])
  for (const f of list) {
    if (attachments.value.length >= MAX_ATTACHMENTS) {
      ElMessage.warning(`最多上传 ${MAX_ATTACHMENTS} 个附件`)
      break
    }
    attachments.value.push({
      id: `att-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      type: 'image',
      name: f.name || 'image',
      base64_image: f.base64 || null,
      image_url: f.url || null,
    })
  }
}
```

---

## 3. 测试验证清单

执行改造后，按以下场景逐一验证：

| # | 场景 | 预期结果 | 验证点 |
|---|------|----------|--------|
| 1 | 文生图（不传任何图） | 正常文生图 | response_format / size 正常 |
| 2 | 图生图（1 张本地图） | 正常图生图 | 服务端日志 `ref_images=1 张` |
| 3 | 图生图（2–5 张本地图） | 多图合成效果 | 服务端日志 `ref_images=N 张` |
| 4 | 图生图（图片 URL） | 正常图生图 | 正确走 `image_urls` 分支 |
| 5 | 图生图（本地图 + URL 混合） | 都能合成 | b64 + url 两类都被收集 |
| 6 | 聊天里「之前对话里的图」作为参考 | 多图合成 | 历史图 URL 被正确收集 |
| 7 | 旧字段调用（base64_image） | 向后兼容 | 旧前端 / curl 调用正常工作 |
| 8 | 独立生图页 + 多图 | 正常工作 | 与聊天链路独立验证 |
| 9 | 删除单张图后再生成 | 删除生效 | `fileList` 真正被修改 |
| 10 | 超过 MAX_ATTACHMENTS 限制 | 有友好提示 | 不会 crash |

**日志 grep 命令**（在 `backend/logs/` 或 stdout 里）：

```bash
# 观察日志确认张数是否正确
tail -f backend.log | grep -E "(图生图|ref_images|image_to_image|Agnes AI 生成图片)"
```

---

## 4. 向后兼容矩阵

| 调用方式 | 是否继续生效 | 说明 |
|----------|-------------|------|
| 旧前端 → `base64_image: "..."` | ✅ | Schema 的 `all_reference_images` 会自动合并旧字段 |
| 旧前端 → `image_url: "https://..."` | ✅ | 同上 |
| 旧代码 → `agnes_client.create_image(base64_image="...")` | ✅ | 方法签名保留旧参数，内部合并到数组 |
| 旧代码 → `agnes_client.create_image(image_url="...")` | ✅ | 同上 |
| 新代码 → `agnes_client.create_image(base64_images=[...])` | ✅ | 新参数优先，被打包进 `extra_body.image` |
| curl 直连 `/api/images/generate`（旧字段） | ✅ | 同样走兼容逻辑 |

---

## 5. 实施顺序建议（从上到下依次执行）

```
第 1 步: backend/app/schemas/images.py          ← 最基础，Schema 改好后面层才能编译
第 2 步: backend/app/services/agnes_client.py    ← 客户端能接收数组
第 3 步: backend/app/services/chat_service.py    ← 工具执行层能传数组
第 4 步: backend/app/routes/images.py            ← API 层能透传数组
第 5 步: frontend/src/components/ImageUploader.vue ← 前端 UI 改好
第 6 步: frontend/src/views/ImageView.vue        ← 独立生图页适配
第 7 步: frontend/src/views/ChatView.vue         ← 聊天页适配
```

**为什么这样排**：后端 1–4 步可以先单独完成，不影响前端（旧前端照旧能用），前端 5–7 步再锦上添花。

---

## 6. 备注提醒

- ⚠️ **不要删除原有功能备注**：每个文件中关于「System Prompt」「ref = effective_attachments[0]」等原有中文注释，在改造时用新版逻辑替换即可，保留/改写相关备注。
- 📝 **日志打张数**：每个调用点都 `logger.info(... ref_images=%d 张)`，方便你上线后即时看到是否传对了。
- 🧪 **先在聊天里测**：聊天里手动粘贴多张图已经能用，说明 Agnes API 没问题；改造后在独立生图页也能达到同样效果。
- 🔒 **文件大小限制**：`MAX_FILE_SIZE = 10 * 1024 * 1024`（10MB）已经存在，多图场景下每张图单独校验，不要改这个值。
- 📦 **API 请求体大小**：多张 base64 图会让请求体变大，Agnes API 对 body size 没有特别限制，但如果是 5 张以上高清图，建议提供 URL 方式而非 base64。

---

> 实施完成后，可以删除本文档，或保留在项目里作为历史记录。
