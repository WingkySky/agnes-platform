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
        logger.info("[AgnesAIClient] POST %s body=%s", url, body)
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
    ) -> Dict[str, Any]:
        """
        调用 Agnes AI 生成图片（异步等待，不阻塞其他请求的事件循环）。

        API 调用规范（严格按 Agnes Image 2.1 Flash 文档）：
          - model、prompt、size → 顶层必填参数
          - 图生图：image 放在 extra_body 中（2.1-flash 规范，不在顶层）
          - return_base64: true → 文生图 Base64 输出（顶层参数）
          - extra_body.response_format: "url" | "b64_json" → 输出格式（放顶层会 400）
          - 文生图：不传入 image 字段
          - 图生图：image 放在 extra_body.image 中

        【多图参考改造】：
          - 参数优先级：base64_images / image_urls（新字段，数组）→ base64_image / image_url（旧字段，单值）
          - 所有有效参考图最终会归一化为 data URI 或公网 URL，统一放入 extra_body.image 数组
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

        # 【核心修复】严格按 Agnes Image 2.1 Flash 文档构建请求体
        #   - model、prompt、size → 顶层必填参数
        #   - 图生图：image 放在 extra_body 中（2.1-flash 规范）
        #   - 文生图 Base64 输出：顶层参数 return_base64: true
        #   - response_format → 必须放在 extra_body 中（放顶层会 400）
        body = {
            "model": model,
            "prompt": prompt,
            "size": size,
        }

        if ref_images:
            # 【图生图模式】将参考图数组放在 extra_body 中（agnes-image-2.1-flash 规范）
            # 对每个参考图进行归一化处理：
            #   - 已经是完整 Data URI（data:image/xxx;base64,xxx）→ 直接使用
            #   - 公网 URL（http:// / https://）→ 直接使用
            #   - 纯 base64 字符串 → 补全 Data URI 前缀（默认 image/png）
            normalized = []
            for img in ref_images:
                lowered = img.strip().lower()
                if lowered.startswith("data:"):
                    normalized.append(img.strip())  # 完整 Data URI，直接使用
                elif lowered.startswith("http://") or lowered.startswith("https://"):
                    normalized.append(img.strip())  # 公网 URL
                else:
                    # 纯 base64 → 补上 Data URI 前缀（image/png 兼容性最好）
                    normalized.append(f"data:image/png;base64,{img.strip()}")

            body["extra_body"] = {
                "image": normalized,
                "response_format": response_format,
            }
            logger.info(
                "[图片生成] 图生图模式: model=%s, size=%s, ref_images=%d 张, format=%s, prompt=%s",
                model, size, len(normalized), response_format, prompt[:80],
            )
        elif response_format == "b64_json":
            # 【文生图 + Base64 输出】使用顶层参数 return_base64（文档规范）
            body["return_base64"] = True
            logger.info("[图片生成] 文生图模式(Base64): model=%s, size=%s, prompt=%s",
                        model, size, prompt[:80])
        else:
            # 【文生图 + URL 输出】response_format 放在 extra_body（放顶层会 400）
            body["extra_body"] = {
                "response_format": "url",
            }
            logger.info("[图片生成] 文生图模式(URL): model=%s, size=%s, prompt=%s",
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
        创建视频生成异步任务。

        Agnes Video V2.0 当前文档使用 /videos/generations，并接收
        aspect_ratio、duration、fps。前端仍保留帧数和宽高控制，这里在
        BFF 层转换为官方参数，避免把旧字段透传给上游导致 422。
        """
        url = f"{self.base_url}/video/generations"

        aspect_ratio = self._aspect_ratio(width, height)
        duration = max(1, round(num_frames / frame_rate))

        body = {
            "model": model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "duration": duration,
            "fps": frame_rate,
        }

        if seed is not None:
            body["seed"] = seed

        # ── 图生视频模式 / 关键帧动画处理 ──
        # Agnes Video V2.0 官方规范 (agnes-ai-docs.md / Agnes Video V2.0):
        #   - 文生视频：不传 image/image_end（仅 prompt）
        #   - 图生视频（单张）：extra_body.image = 起始帧图片 URL 或 Data URI Base64
        #   - 图生视频（首尾帧）：extra_body.image + extra_body.image_end
        #   - 纯 base64 字符串必须补全 Data URI 前缀（`data:image/png;base64,xxx`）
        #
        # 前端 image2video 模式：params.image = 单张参考图（base64 或 URL）
        # 前端 keyframes 模式：params.images = 图片数组
        # 统一处理逻辑：收集所有有效图片，第一张 → extra_body.image，第二张及以后 → extra_body.image_end（仅最后一张）

        # 收集有效图片（从 image 字段和 images 数组）
        ref_images_all = []
        if image and image.strip():
            ref_images_all.append(image.strip())
        if images and len(images) > 0:
            for img in images:
                if img and isinstance(img, str) and img.strip():
                    ref_images_all.append(img.strip())

        if ref_images_all and len(ref_images_all) > 0:
            # 对每个参考图进行归一化处理，统一补全 Data URI 前缀或保留原格式：
            #   - 已经是完整 Data URI（data:image/xxx;base64,xxx）→ 直接使用
            #   - 公网 URL（http:// / https://）→ 直接使用
            #   - 纯 base64 字符串 → 补全 Data URI 前缀（默认 image/png）
            normalized = []
            for img in ref_images_all:
                lowered = img.strip().lower()
                if lowered.startswith("data:"):
                    normalized.append(img.strip())  # 完整 Data URI，直接使用
                elif lowered.startswith("http://") or lowered.startswith("https://"):
                    normalized.append(img.strip())  # 公网 URL
                else:
                    # 纯 base64 → 补上 Data URI 前缀（image/png 兼容性最好）
                    normalized.append(f"data:image/png;base64,{img.strip()}")

            # 根据图片张数构造 extra_body（同时传顶层 image/image_end 兼容文档参数表和 curl 示例）：
            #   - 1 张：extra_body = {"image": 第一张} （图生视频，单张起始帧）
            #   - 2+ 张：extra_body = {"image": 第一张, "image_end": 最后一张} （首尾帧图生视频）
            body["extra_body"] = {"image": normalized[0]}
            if len(normalized) >= 2:
                body["extra_body"]["image_end"] = normalized[-1]
            # 同时在顶层也放一份 image 以兼容参数表写法
            body["image"] = normalized[0]
            if len(normalized) >= 2:
                body["image_end"] = normalized[-1]

        logger.info(
            f"[视频生成] 创建任务: prompt={prompt[:60]}...  "
            f"mode={mode}  duration={duration}s  aspect_ratio={aspect_ratio}  fps={frame_rate}"
        )
        return await self._post(url, body)

    # ---------- 视频任务轮询 ----------
    async def poll_video_status(
        self, video_id: Optional[str] = None, task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        查询视频任务状态。优先使用 video_id 走 agnesapi 路径，
        否则回退到 /videos/generations/{task_id}。
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
                data = await self._get(f"{self.base_url}/video/generations/{task_id}")
                return self._normalize_video_status(data)
            except Exception as e:
                raise RuntimeError(f"视频状态查询失败: {e}") from e

        raise RuntimeError("缺少 video_id 和 task_id，无法轮询视频状态")

    @staticmethod
    def _aspect_ratio(width: int, height: int) -> str:
        """
        将前端宽高转换为 Agnes Video 文档要求的 aspect_ratio 字符串。
        常见比例保持为标准写法，其他比例用最大公约数约分。
        """
        import math

        if width <= 0 or height <= 0:
            return "16:9"

        ratio = width / height
        common = {
            "16:9": 16 / 9,
            "9:16": 9 / 16,
            "1:1": 1,
            "4:3": 4 / 3,
            "3:4": 3 / 4,
            "3:2": 3 / 2,
            "2:3": 2 / 3,
        }
        closest, value = min(common.items(), key=lambda item: abs(item[1] - ratio))
        if abs(value - ratio) < 0.03:
            return closest

        divisor = math.gcd(width, height)
        return f"{width // divisor}:{height // divisor}"

    # ---------- 标准化视频状态 ----------
    def _normalize_video_status(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        将 Agnes AI 的视频状态响应标准化，便于上层业务逻辑处理。
        """
        first_item = None
        if isinstance(data.get("data"), list) and data["data"]:
            first_item = data["data"][0]
        elif isinstance(data.get("data"), dict):
            first_item = data["data"]

        raw_status = (
            data.get("status")
            or (isinstance(first_item, dict) and first_item.get("status"))
            or data.get("state")
            or (isinstance(first_item, dict) and first_item.get("state"))
            or "unknown"
        )

        status = str(raw_status).lower()
        if status == "succeeded":
            status = "success"
        elif status in ("pending", "queued", "running"):
            status = "processing"

        if data.get("video_url") or (isinstance(first_item, dict) and first_item.get("url")):
            if status not in ("completed", "success"):
                status = "completed"

        # 视频 URL 提取：按优先级检查多种可能字段
        # Agnes API 实际把视频 URL 存储在 remixed_from_video_id 字段中
        video_url = (
            data.get("video_url")
            or data.get("remixed_from_video_id")  # Agnes API 实际使用的字段
            or (isinstance(first_item, dict) and first_item.get("video_url"))
            or (isinstance(first_item, dict) and first_item.get("remixed_from_video_id"))
            or (isinstance(first_item, dict) and first_item.get("url"))
            or data.get("url")
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
                or (isinstance(first_item, dict) and isinstance(first_item.get("error"), dict) and first_item["error"].get("message"))
                or (isinstance(first_item, dict) and first_item.get("error"))
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
