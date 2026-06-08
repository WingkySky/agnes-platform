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
from typing import Optional, Dict, Any

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
        base64_image: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        调用 Agnes AI 生成图片（异步等待，不阻塞其他请求的事件循环）。
        - 文生图：不提供 base64_image
        - 图生图：提供 base64_image（参考图）
        """
        url = f"{self.base_url}/images/generations"

        body = {
            "model": model,
            "prompt": prompt,
            "size": size,
        }

        if base64_image:
            cleaned_image = base64_image
            if ";base64," in cleaned_image:
                cleaned_image = cleaned_image.split(";base64,", 1)[1]
            # 图生图：直接在 body 中添加 image 参数
            body["image"] = [cleaned_image]
            body["response_format"] = response_format
        elif response_format == "b64_json":
            body["return_base64"] = True

        logger.info(f"[图片生成] 调用 Agnes AI: prompt={prompt[:60]}...  size={size}")
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

        if mode == "image2video" and image:
            body["image"] = image
        elif mode == "keyframes" and images and len(images) > 0:
            body["extra_body"] = {
                "image": images,
                "mode": "keyframes",
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

        video_url = (
            data.get("video_url")
            or (isinstance(data.get("data"), dict) and data["data"].get("video_url"))
            or (isinstance(data.get("data"), dict) and data["data"].get("url"))
            or data.get("url")
            or (
                isinstance(data.get("data"), list)
                and len(data.get("data", [])) > 0
                and data["data"][0].get("url")
            )
            or None
        )

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
