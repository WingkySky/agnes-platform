# =====================================================
# Agnes AI API 客户端封装（异步 + 连接池
# 负责：
#   1. 构建带鉴权的 HTTP 请求（通过持久化 httpx.AsyncClient 发送，复用连接）
#   2. 图片生成（异步同步等待，不阻塞其他请求）
#   3. 视频任务创建 + 轮询（异步）
#
# 关键设计：
#   - 使用单一持久化的 httpx.AsyncClient（连接池），避免每次请求新建 TCP 连接
#   - start() 在应用启动时调用，shutdown() 在关闭时释放
#   - 所有 API 方法均为 async，配合 FastAPI 异步路由，图片/视频任务互不阻塞
# =====================================================

import logging
from typing import List, Optional, Dict, Any

import httpx

from app.core.config import settings

logger = logging.getLogger("agnes_platform")


# =====================================================
# AgnesAIClient - Agnes AI API 客户端
# =====================================================
class AgnesAIClient:
    """
    Agnes AI 官方 API 的统一调用封装。
    使用单一持久化 httpx.AsyncClient（内部维护 HTTP 连接池），
    多个并发请求复用底层 TCP 连接，显著降低延迟。
    """

    def __init__(self):
        self.api_key = settings.agnes_api_key
        self.base_url = settings.agnes_api_base_url
        self.poll_url = settings.agnes_api_poll_url
        self.poll_interval = settings.video_poll_interval_sec
        self.poll_timeout = settings.video_poll_timeout_sec

        # 通用 HTTP Headers（鉴权）
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # ---------- 持久化的 httpx.AsyncClient（连接池）
        # 连接池限制：默认 100 个并发连接
        # 超时：单请求 120s，允许 AI 生成较长时间
        self._client: Optional[httpx.AsyncClient] = None

    # ---------- 生命周期 ----------
    async def start(self):
        """
        应用启动时初始化 HTTP 客户端（连接池）。
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=30.0),
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                http2=False,
            )
            logger.info("[AgnesAIClient] HTTP 连接池已初始化")

    async def shutdown(self):
        """
        应用关闭时释放 HTTP 客户端连接。
        """
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            logger.info("[AgnesAIClient] HTTP 连接池已释放")

    # ---------- 获取当前 client（懒初始化保护）----------
    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            # 兜底：如果 start() 未被调用，则临时创建一个（不推荐）
            logger.warning("[AgnesAIClient] client 未初始化，正在临时创建")
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=30.0),
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            )
        return self._client

    # =====================================================
    # 【第一层：基础 HTTP 工具】
    # =====================================================
    async def _post(self, url: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """
        发送 POST 请求到 Agnes AI API（使用连接池）
        """
        response = await self.client.post(url, json=body, headers=self._headers)
        return self._parse_response(response)

    async def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        发送 GET 请求到 Agnes AI API（使用连接池）
        """
        response = await self.client.get(url, params=params or {}, headers=self._headers)
        return self._parse_response(response)

    def _parse_response(self, response: httpx.Response) -> Dict[str, Any]:
        """
        统一处理响应：解析 JSON，处理错误（同步解析，不阻塞 I/O）
        """
        try:
            data = response.json()
        except Exception:
            text = response.text
            raise RuntimeError(
                f"Agnes AI 返回非 JSON 响应 (HTTP {response.status_code}): {text[:200]}"
            )

        if not response.is_success:
            message = (
                data.get("error", {}).get("message")
                or data.get("message")
                or data.get("detail")
                or str(data)
            )
            raise RuntimeError(f"Agnes AI API 错误 (HTTP {response.status_code}): {message}")

        return data

    # =====================================================
    # 【第二层：API 方法】
    # =====================================================

    # ---------- 图片生成 ----------
    async def create_image(
        self,
        prompt: str,
        model: str = "agnes-image-2.1-flash",
        size: str = "1024x1024",
        response_format: str = "url",
        base64_image: Optional[str] = None,           # 保留：向后兼容（单图）
        image_url: Optional[str] = None,               # 保留：向后兼容（单图）
        base64_images: Optional[List[str]] = None,     # 【新增】多图 base64 数组
        image_urls: Optional[List[str]] = None,        # 【新增】多图 URL 数组
        quality: str = "standard",
    ) -> Dict[str, Any]:
        """
        调用 Agnes AI 生成图片（异步等待，不阻塞其他请求的事件循环）。

        图生图 API 规范（Agnes Image 官方文档）：
          - agnes-image-2.1-flash 支持文生图和图生图（推荐）
          - agnes-image-2.0-flash 支持快速图像生成
          - extra_body.image 为数组，值支持公网 URL 或 data URI（data:image/xxx;base64,...）
          - image 必须放在 extra_body 中，不能放顶层
          - response_format 必须放在 extra_body 中，放根级会 400
          - 图生图不需要传 tags: ["img2img"]
          - 文生图不要传 extra_body（否则会报 UnsupportedParamsError）
          - quality、n、size 等参数放在请求体顶层

        【多图参考改造】：
          - 参数优先级：base64_images / image_urls（新）→ base64_image / image_url（旧）
          - 最终会把所有有效参考图打包进 extra_body.image 数组，交给 Agnes 官方多图合成能力
        """
        url = f"{self.base_url}/images/generations"

        # ── 收集参考图（新字段优先，回退到旧字段） ──
        ref_images: List[str] = []
        if base64_images:
            for img in base64_images:
                if img and isinstance(img, str) and img.strip():
                    ref_images.append(img)
        if image_urls:
            for u in image_urls:
                if u and isinstance(u, str) and u.strip():
                    ref_images.append(u)
        # 如果新字段为空，回退到旧字段（与之前的单图行为一致）
        if not ref_images and base64_image and base64_image.strip():
            ref_images.append(base64_image)
        if not ref_images and image_url and image_url.strip():
            ref_images.append(image_url)

        body = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "n": 1,
        }

        if ref_images:
            # 图生图：构建 extra_body（image 为数组）
            # 处理图片数据：data URI / URL / 纯 base64（补前缀）
            normalized = []
            for img in ref_images:
                if img.startswith("data:"):
                    # 已经是完整的 Data URI，直接使用
                    normalized.append(img)
                elif img.startswith("http://") or img.startswith("https://"):
                    # 公网 URL，直接传入（Agnes API 原生支持）
                    normalized.append(img)
                else:
                    # 纯 base64，补上 Data URI 前缀
                    normalized.append(f"data:image/png;base64,{img}")

            # extra_body 结构：image 为参考图数组，response_format 指定输出格式
            # 注意：image 和 response_format 都必须放在 extra_body 中，不能放顶层
            extra = {
                "image": normalized,
                "response_format": response_format,
            }

            body["extra_body"] = extra
            logger.info(
                "[图片生成] 图生图模式: model=%s, size=%s, ref_images=%d 张, prompt=%s",
                model, size, len(normalized), prompt[:80],
            )
        elif response_format == "b64_json":
            # 文生图的 b64_json 输出使用 return_base64（不传 extra_body）
            body["return_base64"] = True
            logger.info("[图片生成] 文生图模式(b64_json): model=%s, size=%s, prompt=%s",
                        model, size, prompt[:80])
        else:
            logger.info("[图片生成] 文生图模式: model=%s, size=%s, prompt=%s",
                        model, size, prompt[:80])

        return await self._post(url, body)

    # ---------- 视频任务创建 ----------
    async def create_video_task(
        self,
        prompt: str,
        model: str = "agnes-video-v2.0",
        num_frames: int = 121,
        frame_rate: int = 24,
        width: int = 1152,
        height: int = 768,
        negative_prompt: Optional[str] = None,
        mode: str = "text2video",
        image: Optional[str] = None,
        images: Optional[list] = None,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        创建视频生成异步任务，返回 {video_id, task_id, ...}
        该方法异步等待创建响应，不会阻塞其他并发请求。
        """
        url = f"{self.base_url}/videos"

        body = {
            "model": model,
            "prompt": prompt,
            "num_frames": num_frames,
            "frame_rate": frame_rate,
            "width": width,
            "height": height,
        }

        if negative_prompt:
            body["negative_prompt"] = negative_prompt
        if seed is not None:
            body["seed"] = seed

        # 图生视频模式：单张参考图放在顶层 image 字段
        if mode == "image2video" and image:
            body["image"] = image

        # 关键帧动画模式：多张图片和 mode 必须放在 extra_body 中
        # Agnes AI API 要求关键帧的 image 数组和 mode 放在 extra_body 嵌套对象内，
        # 放在顶层会导致 400 错误
        # 注：图生图的 image 同样放在 extra_body.image 数组中（见 create_image 方法）
        if mode == "keyframes" and images and len(images) > 0:
            # 过滤空值/None，确保仅保留有效图片
            valid_images = [img for img in images if img and isinstance(img, str) and img.strip()]
            if valid_images:
                body["extra_body"] = {
                    "image": valid_images,   # 关键帧图片数组
                    "mode": "keyframes",     # 显式声明关键帧模式
                }

        logger.info(
            f"[视频生成] 创建任务: prompt={prompt[:60]}...  "
            f"mode={mode}  frames={num_frames}  resolution={width}x{height}"
        )
        return await self._post(url, body)

    # ---------- 视频任务轮询 ----------
    async def poll_video_status(
        self, video_id: Optional[str] = None, task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        查询视频任务状态。优先使用 video_id 走 agnesapi 路径，
        否则回退到 /videos/{task_id}。
        """
        if video_id:
            try:
                data = await self._get(
                    self.poll_url,
                    params={"video_id": video_id, "model_name": "agnes-video-v2.0"},
                )
                return self._normalize_video_status(data)
            except Exception as e:
                logger.warning(f"[视频轮询] agnesapi 路径失败，尝试回退: {e}")

        if task_id:
            try:
                data = await self._get(f"{self.base_url}/videos/{task_id}")
                return self._normalize_video_status(data)
            except Exception as e:
                raise RuntimeError(f"视频状态查询失败: {e}") from e

        raise RuntimeError("缺少 video_id 和 task_id，无法轮询视频状态")

    # ---------- 标准化视频状态 ----------
    def _normalize_video_status(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        将 Agnes AI 的视频状态响应标准化，便于上层业务逻辑处理。
        """
        raw_status = (
            data.get("status")
            or (isinstance(data.get("data"), dict) and data["data"].get("status"))
            or data.get("state")
            or (isinstance(data.get("data"), dict) and data["data"].get("state"))
            or "unknown"
        )

        status = str(raw_status).lower()

        if data.get("video_url") or (
            isinstance(data.get("data"), dict) and data["data"].get("video_url")
        ):
            if status not in ("completed", "success"):
                status = "completed"

        # 视频 URL 提取：按优先级检查多种可能字段
        # Agnes API 实际把视频 URL 存储在 remixed_from_video_id 字段中
        video_url = (
            data.get("video_url")
            or data.get("remixed_from_video_id")  # Agnes API 实际使用的字段
            or (isinstance(data.get("data"), dict) and data["data"].get("video_url"))
            or (isinstance(data.get("data"), dict) and data["data"].get("remixed_from_video_id"))
            or (isinstance(data.get("data"), dict) and data["data"].get("url"))
            or data.get("url")
            or (
                isinstance(data.get("data"), list)
                and len(data.get("data", [])) > 0
                and data["data"][0].get("url")
            )
            or None
        )

        # 确保提取到的值是有效的 URL（以 http 开头），否则丢弃
        if video_url and isinstance(video_url, str) and not video_url.startswith("http"):
            video_url = None

        progress = data.get("progress")
        if not isinstance(progress, (int, float)):
            progress = None

        error_msg = None
        if status in ("failed", "error"):
            error_msg = (
                (isinstance(data.get("error"), dict) and data["error"].get("message"))
                or data.get("error_message")
                or data.get("message")
                or "未知错误"
            )

        return {
            "status": status,
            "video_url": video_url,
            "progress": progress,
            "error": error_msg,
            "raw": data,
        }


# 全局单例客户端实例
agnes_client = AgnesAIClient()
