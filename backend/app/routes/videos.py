# =====================================================
# 视频生成路由（全异步）
# POST /api/videos                    - 创建视频生成任务（立即返回 task_id，后台异步轮询
# GET  /api/videos/{id}               - 查询视频任务状态（前端定时轮询此接口
# GET  /api/videos/{id}/stream        - 视频流代理（支持 Range + CORS，解决 Google Storage 跨域问题）
# DELETE /api/videos/{id}             - 中止视频任务
#
# 关键设计：
#   - 视频创建后立即返回 task_id，不阻塞后续请求
#   - 视频轮询在独立的 asyncio.Task 中进行，不影响图片生成任务
#   - 图片/视频/历史三个路由模块**互不阻塞**
# =====================================================

import logging
import httpx

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_async_db
from app.core.config import settings
from app.models.generation import Generation
from app.schemas.videos import (
    VideoGenerationRequest,
    VideoTaskCreatedResponse,
    VideoStatusResponse,
)
from app.services.agnes_client import agnes_client
from app.services.video_poller import poller_manager

logger = logging.getLogger("agnes_platform")
router = APIRouter()


@router.post("/videos", response_model=VideoTaskCreatedResponse, summary="创建视频生成任务")
async def create_video_task(req: VideoGenerationRequest):
    """
    创建视频生成异步任务。
    返回 task_id/video_id，前端可立即释放，不阻塞用户操作。
    实际视频生成轮询在后台独立 asyncio.Task 中运行，不影响其他请求。
    """
    if not settings.agnes_api_key or settings.agnes_api_key.startswith("sk-your"):
        raise HTTPException(
            status_code=401,
            detail="Agnes AI API Key 未配置，请在 backend/.env 中设置 AGNES_API_KEY",
        )

    try:
        result = await agnes_client.create_video_task(
            prompt=req.prompt,
            model=req.model,
            num_frames=req.num_frames,
            frame_rate=req.frame_rate,
            width=req.width,
            height=req.height,
            negative_prompt=req.negative_prompt,
            mode=req.mode,
            image=req.image,
            images=req.images,
            seed=req.seed,
        )
    except Exception as e:
        logger.error("[视频生成] 创建任务失败: %s", e)
        raise HTTPException(status_code=502, detail=str(e))

    result_data = result.get("data")
    if isinstance(result_data, list) and result_data:
        first_result = result_data[0]
    elif isinstance(result_data, dict):
        first_result = result_data
    else:
        first_result = {}

    video_id = result.get("video_id") or (
        first_result.get("video_id") if isinstance(first_result, dict) else None
    )
    task_id = (
        result.get("task_id")
        or result.get("id")
        or (first_result.get("task_id") if isinstance(first_result, dict) else None)
        or (first_result.get("id") if isinstance(first_result, dict) else None)
    )

    if not video_id and not task_id:
        raise HTTPException(
            status_code=502,
            detail=f"Agnes AI 返回的数据中未找到 video_id 或 task_id: {str(result)[:200]}",
        )

    logger.info("[视频生成] 任务创建成功: video_id=%s task_id=%s", video_id, task_id)

    # 启动后台轮询协程（独立 Task，不阻塞当前请求返回）
    params = {
        "model": req.model,
        "num_frames": req.num_frames,
        "frame_rate": req.frame_rate,
        "width": req.width,
        "height": req.height,
        "negative_prompt": req.negative_prompt,
        "mode": req.mode,
        "seed": req.seed,
    }
    await poller_manager.start_polling(
        task_id=task_id,
        video_id=video_id,
        prompt=req.prompt,
        params=params,
    )

    return VideoTaskCreatedResponse(
        task_id=task_id,
        video_id=video_id,
        status="pending",
        prompt=req.prompt,
        model=req.model,
        num_frames=req.num_frames,
        frame_rate=req.frame_rate,
        width=req.width,
        height=req.height,
        mode=req.mode,
        message="任务已创建，请轮询 GET /api/videos/{task_id} 获取最新状态",
    )


@router.get("/videos/{task_id}", response_model=VideoStatusResponse, summary="查询视频任务状态")
async def get_video_status(task_id: str, db: AsyncSession = Depends(get_async_db)):
    """
    查询视频任务状态。
    优先从后端内存缓存获取（实时状态），缓存中不存在则回退查询数据库。
    """
    # 方式 1：从内存缓存查询（并发安全
    cached_task = await poller_manager.get_status(task_id=task_id)
    if not cached_task:
        cached_task = await poller_manager.get_status(video_id=task_id)

    if cached_task:
        return VideoStatusResponse(
            task_id=cached_task.task_id,
            video_id=cached_task.video_id,
            status=cached_task.status,
            progress=cached_task.progress,
            video_url=cached_task.video_url,
            message=cached_task.error_message,
            elapsed_sec=cached_task.to_dict()["elapsed_sec"],
        )

    # 方式 2：从数据库查询已完成的记录（异步查询，不阻塞事件循环）
    result = await db.execute(
        select(Generation).filter(
            (Generation.task_id == task_id) & (Generation.type == "video")
        )
    )
    record = result.scalar_one_or_none()

    if record:
        return VideoStatusResponse(
            task_id=record.task_id,
            status=record.status,
            progress=100 if record.status == "success" else 0,
            video_url=record.result_url,
            message=None if record.status == "success" else "任务已完成",
            elapsed_sec=0,
        )

    raise HTTPException(
        status_code=404,
        detail=f"未找到视频任务（ID: {task_id}），可能尚未创建或已过期",
    )


@router.delete("/videos/{task_id}", summary="中止视频任务")
async def cancel_video_task(task_id: str):
    """
    中止指定视频任务的后台轮询（仅停止本地轮询，不保证服务端已终止）。
    """
    await poller_manager.cancel(task_id=task_id)
    return {"success": True, "message": f"已尝试中止任务 {task_id}"}


# =====================================================
# 视频流代理接口
# 用途：解决视频生成页面直接播放 Google Storage 视频时的 CORS 问题
# 通过 task_id 查找视频 URL，后端代理转发视频流
# =====================================================


async def _find_video_url_by_task_id(task_id: str, db: AsyncSession) -> str:
    """
    根据 task_id 查找视频 URL。
    优先从内存缓存获取（进行中的任务），回退查询数据库（已完成的任务）。
    """
    # 方式 1：从内存缓存查询
    cached_task = await poller_manager.get_status(task_id=task_id)
    if not cached_task:
        cached_task = await poller_manager.get_status(video_id=task_id)

    if cached_task and cached_task.video_url:
        return cached_task.video_url

    # 方式 2：从数据库查询
    result = await db.execute(
        select(Generation).filter(
            (Generation.task_id == task_id) & (Generation.type == "video")
        )
    )
    record = result.scalar_one_or_none()
    if record and record.result_url:
        return record.result_url

    return ""


@router.get("/videos/{task_id}/stream", summary="视频流代理（支持 Range + CORS）")
async def stream_video_by_task(request: Request, task_id: str, db: AsyncSession = Depends(get_async_db)):
    """
    通过 task_id 代理播放视频资源，解决 CORS 和 Range 请求问题。
    逻辑与 /api/history/video/{id}/stream 一致。
    """
    # 查找视频 URL
    video_url = await _find_video_url_by_task_id(task_id, db)
    if not video_url:
        raise HTTPException(status_code=404, detail="未找到对应的视频资源")

    range_header = request.headers.get("range", None)

    # 先通过 HEAD 请求获取视频元信息
    content_type = "video/mp4"
    total_size = 0
    head_ok = False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            head_resp = await client.head(video_url, follow_redirects=True)
            if head_resp.status_code < 400:
                head_ok = True
                content_type = head_resp.headers.get("content-type", "video/mp4")
                content_length_hdr = head_resp.headers.get("content-length")
                content_range_hdr = head_resp.headers.get("content-range")
                if content_length_hdr:
                    total_size = int(content_length_hdr)
                elif content_range_hdr:
                    parts = content_range_hdr.split("/")
                    if len(parts) == 2 and parts[1] != "*":
                        total_size = int(parts[1])
    except Exception:
        pass

    # HEAD 失败时：直接流式转发完整视频
    if not head_ok or total_size == 0:
        async def fallback_stream():
            """HEAD 失败时的回退：直接流式转发完整视频"""
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream("GET", video_url, headers={"User-Agent": "Agnes-Platform-VideoProxy"}, follow_redirects=True) as response:
                    async for chunk in response.aiter_bytes():
                        yield chunk

        return StreamingResponse(
            fallback_stream(),
            media_type=content_type,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
                "Accept-Ranges": "bytes",
                "Content-Type": content_type,
                "Cache-Control": "no-cache",
            },
            status_code=200,
        )

    # 解析 Range 请求
    start = 0
    end = total_size - 1

    if range_header:
        try:
            range_spec = range_header.replace("bytes=", "").strip()
            range_parts = range_spec.split("-")
            start = int(range_parts[0]) if range_parts[0] else 0
            end = int(range_parts[1]) if len(range_parts) > 1 and range_parts[1] else total_size - 1
            start = max(0, min(start, total_size - 1))
            end = max(start, min(end, total_size - 1))
        except (ValueError, IndexError):
            start = 0
            end = total_size - 1

    # 构造转发给上游的 Range 请求头
    req_headers = {"User-Agent": "Agnes-Platform-VideoProxy"}
    if range_header:
        req_headers["Range"] = f"bytes={start}-{end}"

    resp_content_length = end - start + 1

    # 创建异步流生成器
    async def video_stream():
        """异步生成器：流式转发视频数据"""
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("GET", video_url, headers=req_headers, follow_redirects=True) as response:
                async for chunk in response.aiter_bytes():
                    yield chunk

    # 响应头设置
    response_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
        "Accept-Ranges": "bytes",
        "Content-Type": content_type,
    }

    # 根据 Range 请求返回 206 或 200
    if range_header:
        response_headers["Content-Length"] = str(resp_content_length)
        response_headers["Content-Range"] = f"bytes {start}-{end}/{total_size}"
        status_code = 206
    else:
        response_headers["Content-Length"] = str(total_size)
        status_code = 200

    return StreamingResponse(
        video_stream(),
        media_type=content_type,
        headers=response_headers,
        status_code=status_code,
    )
