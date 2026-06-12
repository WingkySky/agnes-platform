# =====================================================
# 图片生成路由（支持异步任务模式）
# POST /api/images/generations - 同步生成（向后兼容）
# POST /api/images/tasks       - 创建异步任务（推荐，返回 task_id）
# GET  /api/images/tasks/{id}  - 查询异步任务状态
# DELETE /api/images/tasks/{id}- 取消异步任务
# GET  /api/images/{id}        - 获取单张图片历史记录
#
# 关键设计：
#   - 异步任务模式下，创建后立即返回 task_id，不阻塞用户
#   - 与视频任务完全独立，互不干扰
# =====================================================

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_async_db
from app.core.config import settings
from app.models.generation import Generation
from app.schemas.images import ImageGenerationRequest, ImageGenerationResponse, ImageRecordResponse
from app.services.agnes_client import agnes_client
from app.services.image_poller import image_poller_manager

logger = logging.getLogger("agnes_platform")
router = APIRouter()


# =====================================================
# 【异步任务模式】—— 推荐使用
# =====================================================
@router.post("/images/tasks", summary="创建图片异步生成任务")
async def create_image_task_async(req: ImageGenerationRequest):
    """
    创建图片异步生成任务，立即返回 task_id。
    实际生成在后台独立 asyncio.Task 中进行，不阻塞其他请求。
    """
    # API Key 检查
    if not settings.agnes_api_key or settings.agnes_api_key.startswith("sk-your"):
        raise HTTPException(
            status_code=401,
            detail="Agnes AI API Key 未配置，请在 backend/.env 中设置 AGNES_API_KEY",
        )

    # 参数校验（确保 size 格式正确）
    try:
        size = req.size or "1024x1024"
        if "x" in size.lower():
            parts = size.lower().split("x")
            int(parts[0])
            int(parts[1])
    except Exception:
        raise HTTPException(status_code=400, detail="尺寸格式错误，应为 '宽x高'，如 '1024x1024'")

    # 【多图参考改造点】合并 all_reference_images，区分 URL 和 base64
    params = {
        "model": req.model,
        "size": size,
        "response_format": req.response_format,
        "mode": "image2image" if req.is_image_to_image else "text2image",
    }

    if req.is_image_to_image:
        # 这里已经是合并后的统一数组（新旧字段都已合并）
        ref_imgs = req.all_reference_images
        b64_imgs = [img for img in ref_imgs if not img.startswith("http")]
        url_imgs = [img for img in ref_imgs if img.startswith("http")]
        if b64_imgs:
            params["base64_images"] = b64_imgs
        if url_imgs:
            params["image_urls"] = url_imgs
        logger.info(
            "[图片API] 异步图生图任务创建: ref_images=%d 张 (b64=%d, url=%d), size=%s, model=%s",
            len(ref_imgs), len(b64_imgs), len(url_imgs), size, req.model,
        )

    task = await image_poller_manager.create_task(
        prompt=req.prompt,
        params=params,
    )

    logger.info("[图片生成] 异步任务已创建: task_id=%s", task.task_id)

    return {
        "task_id": task.task_id,
        "id": task.task_id,
        "status": "pending",
        "prompt": req.prompt,
        "model": req.model,
        "size": size,
        "created_at": datetime.utcnow().isoformat(),
        "message": "任务已创建，请使用 GET /api/images/tasks/{task_id} 轮询状态",
    }


@router.get("/images/tasks/{task_id}", summary="查询图片异步任务状态")
async def get_image_task_status(task_id: str):
    """查询图片任务状态，前端用于轮询"""
    task = await image_poller_manager.get_status(task_id)
    if not task:
        # 不在缓存中，尝试从数据库查询已完成的任务
        try:
            async with get_async_db() as session:
                result = await session.execute(
                    select(Generation).filter(
                        Generation.task_id == task_id,
                        Generation.type == "image",
                    )
                )
                record = result.scalar_one_or_none()
                if record:
                    return {
                        "task_id": task_id,
                        "status": record.status,
                        "progress": 100 if record.status == "success" else 0,
                        "result_url": record.result_url,
                        "url": record.result_url,
                        "elapsed_sec": 0,
                    }
        except Exception as e:
            logger.warning("[图片生成] 数据库查询失败: %s", e)

        raise HTTPException(
            status_code=404,
            detail=f"未找到任务（ID: {task_id}），可能已过期或不存在",
        )

    return task.to_dict()


@router.delete("/images/tasks/{task_id}", summary="取消图片异步任务")
async def cancel_image_task(task_id: str):
    """取消指定图片任务（停止后台生成）"""
    await image_poller_manager.cancel(task_id)
    return {
        "success": True,
        "task_id": task_id,
        "status": "cancelled",
        "message": f"已尝试取消任务 {task_id}",
    }


# =====================================================
# 【同步模式】—— 向后兼容
# =====================================================
@router.post("/images/generations", response_model=ImageGenerationResponse, summary="同步生成图片（向后兼容）")
async def create_image_generation(req: ImageGenerationRequest, db: AsyncSession = Depends(get_async_db)):
    """
    同步图片生成接口（保留以向后兼容）。
    新代码建议使用异步任务模式（POST /images/tasks）。
    """
    if not settings.agnes_api_key or settings.agnes_api_key.startswith("sk-your"):
        raise HTTPException(
            status_code=401,
            detail="Agnes AI API Key 未配置，请在 backend/.env 中设置 AGNES_API_KEY",
        )

    # 参考图大小校验（多图：每张图单独校验大小
    if req.is_image_to_image:
        # 汇总所有 base64 图的总大小（近似：每张单独校验
        total_bytes = 0
        for img in req.all_reference_images:
            if not img.startswith("http"):
                # base64 图（含前缀或纯 base64）
                pure_b64 = img.split(",")[-1] if "," in img else img
                total_bytes += len(pure_b64) * 3 / 4
        if total_bytes > settings.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"参考图总大小过大，最大允许 {settings.max_upload_size_mb}MB",
            )

    # 调用 Agnes AI
    # 【多图参考改造点】新字段优先，回退到旧字段以保持兼容
    try:
        ref_imgs = req.all_reference_images
        b64_imgs = [img for img in ref_imgs if not img.startswith("http")]
        url_imgs = [img for img in ref_imgs if img.startswith("http")]
        result = await agnes_client.create_image(
            prompt=req.prompt,
            model=req.model,
            size=req.size,
            response_format=req.response_format,
            base64_images=b64_imgs or None,
            image_urls=url_imgs or None,
            quality="standard",
        )
        if ref_imgs:
            logger.info(
                "[图片API] 同步图生图请求完成: ref_images=%d 张 (b64=%d, url=%d)",
                len(ref_imgs), len(b64_imgs), len(url_imgs),
            )
    except Exception as e:
        logger.error("[图片生成] Agnes AI 调用失败: %s", e)
        raise HTTPException(status_code=502, detail=str(e))

    # 解析结果
    output_url = None
    output_b64 = None
    try:
        data = result.get("data", [])
        if isinstance(data, list) and len(data) > 0:
            output_url = data[0].get("url")
            output_b64 = data[0].get("b64_json")
        if not output_url and isinstance(result.get("url"), str):
            output_url = result["url"]
        if not output_url and result.get("image"):
            output_url = result["image"]
    except Exception as e:
        logger.error("[图片生成] 结果解析异常: %s", e)

    if not output_url and not output_b64:
        raise HTTPException(
            status_code=502,
            detail=f"Agnes AI 返回异常，未找到图片数据: {str(result)[:200]}",
        )

    # 写入数据库
    record_id = None
    try:
        params = {
            "size": req.size,
            "response_format": req.response_format,
            "mode": "image2image" if req.is_image_to_image else "text2image",
        }
        record = Generation(
            type="image",
            prompt=req.prompt,
            model=req.model,
            params=params,
            mode=params["mode"],
            result_url=output_url or "(base64)",
            status="success",
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        record_id = record.id
        logger.info("[图片生成] 同步模式记录已写入: id=%s", record_id)
    except Exception as e:
        logger.warning("[图片生成] 写入历史失败: %s", e)

    return ImageGenerationResponse(
        id=record_id,
        status="success",
        url=output_url,
        b64_json=output_b64,
        model=req.model,
        prompt=req.prompt,
        size=req.size,
        created_at=datetime.utcnow().isoformat(),
    )


@router.get("/images/{image_id}", response_model=ImageRecordResponse, summary="获取单张图片记录")
async def get_image_record(image_id: int, db: AsyncSession = Depends(get_async_db)):
    """根据 ID 获取单张图片生成历史记录"""
    result = await db.execute(
        select(Generation).filter(
            Generation.id == image_id,
            Generation.type == "image",
        )
    )
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="未找到对应图片记录")

    return ImageRecordResponse(
        id=record.id,
        type="image",
        prompt=record.prompt,
        model=record.model,
        params=record.params,
        result_url=record.result_url,
        status=record.status,
        created_at=record.created_at.isoformat() if record.created_at else None,
    )
