# =====================================================
# 图片异步任务轮询管理器（全异步 + 并发安全）
# 职责：
#   1. 保存所有进行中图片任务状态（内存缓存）
#   2. 后台异步调用 Agnes AI 生成图片（不阻塞请求返回）
#   3. 完成后异步写入数据库（AsyncSession，不阻塞事件循环）
#   4. 定时清理过期缓存，防止内存泄漏
#
# 关键设计：
#   - 与视频任务完全独立，互不干扰
#   - 使用 asyncio.Lock 保护 _tasks 字典，并发读写安全
#   - 图片生成使用 Agnes AI 的同步接口，包装为独立 asyncio.Task
#   - LRU 式清理：已完成/失败任务超过 TTL 后自动移除
# =====================================================

import asyncio
import logging
import time
import uuid
from typing import Dict, Optional, List

from app.services.agnes_client import agnes_client
from app.models.generation import Generation
from app.core.database import new_async_session

logger = logging.getLogger("agnes_platform")

# ---------- 清理参数 ----------
CLEANUP_INTERVAL_SEC = 300   # 每 5 分钟扫描一次过期缓存
CLEANUP_TTL_SEC = 3600        # 已完成任务保留 1 小时后清除


# =====================================================
# 单个图片任务状态对象
# =====================================================
class ImageTask:
    """单个图片任务的状态缓存"""

    def __init__(
        self,
        task_id: str,
        prompt: str,
        params: Dict,
    ):
        self.task_id = task_id
        self.prompt = prompt
        self.params = params or {}
        self.status = "queued"   # queued / processing / success / failed / cancelled
        self.progress = 0
        self.result_url: Optional[str] = None
        self.image_b64: Optional[str] = None
        self.error_message: Optional[str] = None
        self.created_at = time.time()
        self.last_updated = self.created_at
        self._gen_task: Optional[asyncio.Task] = None
        self._cancelled = False

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "progress": self.progress,
            "result_url": self.result_url,
            "url": self.result_url,   # 兼容字段
            "image_b64": self.image_b64,
            "message": self.error_message,
            "elapsed_sec": int(time.time() - self.created_at),
        }


# =====================================================
# 图片任务管理器（全局单例）
# =====================================================
class ImagePollerManager:
    """
    管理所有进行中的图片任务：
    - 与视频任务完全独立，互不干扰
    - 使用 asyncio.Lock 确保并发读写安全
    - LRU TTL 自动清理，避免内存泄漏
    """

    def __init__(self):
        self._tasks: Dict[str, ImageTask] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._started = False

    # ---------- 启动后台清理协程 ----------
    async def start(self):
        """启动后台周期性清理协程（在应用启动时调用一次）"""
        if self._started:
            return
        self._started = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("[图片任务器] 已启动，清理周期 %ss", CLEANUP_INTERVAL_SEC)

    # ---------- 创建任务 ----------
    async def create_task(
        self,
        prompt: str,
        params: Dict,
    ) -> ImageTask:
        """
        创建图片生成任务，立即返回 ImageTask，
        实际生成在后台异步进行（不阻塞请求）。
        """
        task_id = f"img_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        task = ImageTask(task_id=task_id, prompt=prompt, params=params)
        task.status = "pending"

        async with self._lock:
            self._tasks[task_id] = task

        # 启动后台生成协程（独立 asyncio.Task，不阻塞创建请求）
        task._gen_task = asyncio.create_task(self._gen_loop(task_id, task))
        logger.info("[图片任务器] 已创建任务: task_id=%s prompt=%s", task_id, prompt[:50])
        return task

    # ---------- 获取任务状态 ----------
    async def get_status(self, task_id: str) -> Optional[ImageTask]:
        """根据 task_id 查找任务状态（并发安全读取）"""
        async with self._lock:
            return self._tasks.get(task_id)

    # ---------- 取消任务 ----------
    async def cancel(self, task_id: str):
        """取消指定图片任务"""
        task = None
        async with self._lock:
            task = self._tasks.get(task_id)

        if task and not task._cancelled:
            task._cancelled = True
            task.status = "cancelled"
            if task._gen_task and not task._gen_task.done():
                task._gen_task.cancel()
            logger.info("[图片任务器] 任务已取消: task_id=%s", task_id)

    # ---------- 生成主循环 ----------
    async def _gen_loop(self, task_id: str, task: ImageTask):
        """
        后台生成协程：调用 Agnes AI 生成图片，
        完成/失败后更新状态并写入数据库。
        """
        try:
            task.status = "processing"
            task.progress = 10
            task.last_updated = time.time()

            # 调用 Agnes AI 生成图片（await，不阻塞事件循环）
            result = await agnes_client.create_image(
                prompt=task.prompt,
                model=task.params.get("model", "agnes-image-2.1-flash"),
                size=task.params.get("size", "1024x1024"),
                response_format=task.params.get("response_format", "url"),
                # 【多图参考改造点】新字段优先，回退到旧字段以保持兼容
                base64_image=task.params.get("base64_image"),
                image_url=task.params.get("image_url"),
                base64_images=task.params.get("base64_images"),
                image_urls=task.params.get("image_urls"),
                quality=task.params.get("quality", "standard"),
            )

            # 解析结果
            output_url = None
            output_b64 = None

            # 兼容多种返回结构
            if isinstance(result, dict):
                data = result.get("data")
                if isinstance(data, list) and len(data) > 0:
                    output_url = data[0].get("url")
                    output_b64 = data[0].get("b64_json")
                if not output_url and isinstance(result.get("url"), str):
                    output_url = result["url"]
                if not output_url and result.get("image"):
                    output_url = result["image"]

            # 更新进度
            task.progress = 80
            task.last_updated = time.time()

            # 检查是否有有效结果
            if not output_url and not output_b64:
                task.status = "failed"
                task.error_message = "Agnes AI 返回异常，未找到图片数据"
                logger.warning("[图片任务器] 无结果数据: task_id=%s", task_id)
                await self._persist_result(task)
                return

            task.status = "success"
            task.progress = 100
            task.result_url = output_url
            task.image_b64 = output_b64
            task.last_updated = time.time()

            logger.info(
                "[图片任务器] 任务完成: task_id=%s url=%s",
                task_id,
                output_url[:100] if output_url else "(base64)",
            )

            await self._persist_result(task)

        except asyncio.CancelledError:
            task.status = "cancelled"
            logger.info("[图片任务器] 任务被取消: task_id=%s", task_id)

        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            task.last_updated = time.time()
            logger.error(
                "[图片任务器] 任务失败: task_id=%s error=%s",
                task_id,
                str(e),
                exc_info=True,
            )
            try:
                await self._persist_result(task)
            except Exception as persist_err:
                logger.error("[图片任务器] 写入数据库失败: %s", persist_err)

    # ---------- 异步写入数据库 ----------
    async def _persist_result(self, task: ImageTask):
        """
        图片任务完成/失败后，异步写入数据库。
        使用 AsyncSession，完全异步 I/O，不阻塞事件循环。
        """
        try:
            async with new_async_session() as session:
                record = Generation(
                    type="image",
                    prompt=task.prompt,
                    model=task.params.get("model", "agnes-image-2.1-flash"),
                    params={
                        k: v for k, v in task.params.items()
                        # 不保存大的 base64 / URL 数组，避免数据库膨胀
                        if k not in ("base64_image", "image_url", "base64_images", "image_urls")
                    },
                    mode=task.params.get("mode"),
                    result_url=task.result_url or "(base64)",
                    status=task.status,
                    task_id=task.task_id,
                )
                session.add(record)
                await session.commit()
            logger.info("[图片任务器] 记录已异步写入数据库: status=%s", task.status)
        except Exception as e:
            logger.error("[图片任务器] 数据库写入失败: %s", e)

    # ---------- 后台清理协程 ----------
    async def _cleanup_loop(self):
        """定期清理已完成/失败/取消且超过 TTL 的任务"""
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL_SEC)
            try:
                now = time.time()
                removed: List[str] = []
                async with self._lock:
                    for key, t in list(self._tasks.items()):
                        if t.status in ("success", "failed", "cancelled") and (
                            now - t.last_updated > CLEANUP_TTL_SEC
                        ):
                            removed.append(key)
                    for key in removed:
                        del self._tasks[key]

                if removed:
                    logger.info("[图片任务器] 已清理 %s 个过期任务缓存", len(removed))
            except Exception as e:
                logger.error("[图片任务器] 清理协程异常: %s", e)

    # ---------- 优雅关闭 ----------
    async def shutdown(self):
        """服务关闭时：取消所有进行中的生成任务"""
        async with self._lock:
            for key, task in self._tasks.items():
                if task._gen_task and not task._gen_task.done():
                    task._gen_task.cancel()

        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()

        self._started = False
        logger.info("[图片任务器] 已关闭所有后台任务")


# 全局单例
image_poller_manager = ImagePollerManager()
