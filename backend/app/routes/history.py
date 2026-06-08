# =====================================================
# 生成历史记录路由（全异步）
# GET    /api/history           - 获取历史列表（分页 + 按类型筛选）
# DELETE /api/history/{id}      - 删除单条记录
# DELETE /api/history/batch     - 批量删除多条记录（按 ID 列表）
# GET    /api/history/video/{id}/stream    - 视频流代理（支持 Range 请求 + CORS）
# GET    /api/history/video/{id}/thumbnail - 视频首帧缩略图提取
# GET    /api/history/video/{id}/preview   - 视频预览片段（悬停 GIF 效果）
# =====================================================

import logging
import os
import hashlib
import tempfile
import asyncio
import httpx
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import StreamingResponse, Response as FastAPIResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc, func

from app.core.database import get_async_db
from app.models.generation import Generation
from app.schemas.common import (
    HistoryListResponse,
    GenerationRecord,
    DeleteResponse,
    BatchDeleteRequest,
    BatchDeleteResponse,
)

logger = logging.getLogger("agnes_platform")
router = APIRouter()


@router.get("/history", response_model=HistoryListResponse, summary="获取生成历史列表")
async def get_history(
    type: Optional[str] = Query(None, description="筛选类型: image / video / all（默认）"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_async_db),
):
    """
    分页获取生成历史记录（异步查询，不阻塞事件循环），按创建时间倒序排列。
    """
    stmt = select(Generation)

    if type and type.lower() in ("image", "video"):
        stmt = stmt.filter(Generation.type == type.lower())

    # 总数查询
    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one() or 0

    # 分页 + 倒序查询
    stmt = stmt.order_by(desc(Generation.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    items = result.scalars().all()

    # 转换为响应对象
    records = []
    for item in items:
        records.append(GenerationRecord(
            id=item.id,
            type=item.type,
            prompt=item.prompt,
            model=item.model,
            params=item.params,
            result_url=item.result_url,
            status=item.status,
            task_id=item.task_id,
            created_at=item.created_at,
        ))

    return HistoryListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=records,
    )


@router.delete("/history/{record_id}", response_model=DeleteResponse, summary="删除单条历史记录")
async def delete_history_record(record_id: int, db: AsyncSession = Depends(get_async_db)):
    """
    根据 ID 删除一条生成历史记录（异步操作，不阻塞事件循环）。
    """
    result = await db.execute(
        select(Generation).filter(Generation.id == record_id)
    )
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="未找到对应记录")

    try:
        await db.delete(record)
        await db.commit()
        logger.info("[历史记录] 已异步删除: id=%s", record_id)
        return DeleteResponse(success=True, message=f"已删除记录 ID={record_id}")
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")


@router.post("/history/batch-delete", response_model=BatchDeleteResponse, summary="批量删除历史记录")
async def batch_delete_history(
    body: BatchDeleteRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """
    根据 ID 列表批量删除多条生成历史记录（异步事务操作）。
    即使部分 ID 不存在，也会尽量删除能查到的记录。
    """
    ids = body.ids or []
    if not ids:
        raise HTTPException(status_code=400, detail="请提供至少一个要删除的记录 ID")

    # 去重
    unique_ids = list(set(ids))

    try:
        # 查询所有待删除记录
        result = await db.execute(
            select(Generation).filter(Generation.id.in_(unique_ids))
        )
        records = result.scalars().all()

        deleted_ids = []
        for record in records:
            deleted_ids.append(record.id)
            await db.delete(record)

        await db.commit()

        # 计算失败（未找到）的 ID
        failed_ids = [rid for rid in unique_ids if rid not in deleted_ids]

        logger.info(
            "[历史记录] 批量删除完成：请求 %d 条，成功 %d 条，失败 %d 条",
            len(unique_ids),
            len(deleted_ids),
            len(failed_ids),
        )

        return BatchDeleteResponse(
            success=True,
            message=f"已删除 {len(deleted_ids)} 条记录",
            deleted_count=len(deleted_ids),
            failed_ids=failed_ids,
        )
    except Exception as e:
        await db.rollback()
        logger.exception("[历史记录] 批量删除失败: %s", e)
        raise HTTPException(status_code=500, detail=f"批量删除失败: {e}")


# =====================================================
# 视频流代理接口
# 用途：解决前端直接播放 Google Storage 视频时的 CORS 和 Range 请求问题
# =====================================================


@router.get("/history/video/{record_id}/stream", summary="视频流代理（支持 Range + CORS）")
async def stream_video(request: Request, record_id: int, db: AsyncSession = Depends(get_async_db)):
    """
    代理播放历史视频资源。

    当前端直接访问 Google Storage 视频 URL 时，会遇到：
    1. CORS 缺少 Access-Control-Allow-Origin 头
    2. Range 请求返回 206 但浏览器解析失败

    本接口通过后端转发视频流，自动处理：
    - 添加 CORS 响应头（Allow-Origin、Accept-Ranges、Content-Type 等）
    - 支持 HTTP Range 请求（用于视频拖动/seek）
    - 正确返回 Content-Range / Content-Length，确保浏览器可正常播放和拖动
    - 以流式传输避免大文件内存占用
    """
    # 查询视频记录
    result = await db.execute(
        select(Generation).filter(Generation.id == record_id)
    )
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="未找到对应视频记录")

    if record.type != "video":
        raise HTTPException(status_code=400, detail="该记录不是视频类型")

    if not record.result_url:
        raise HTTPException(status_code=404, detail="视频资源链接不存在")

    video_url = record.result_url
    range_header = request.headers.get("range", None)

    # 先通过 HEAD 请求获取视频元信息（总大小、内容类型）
    # 如果 HEAD 失败（某些存储服务不支持 HEAD），则回退为直接流式转发完整视频
    content_type = "video/mp4"
    total_size = 0
    head_ok = False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            head_resp = await client.head(video_url, follow_redirects=True)
            if head_resp.status_code < 400:
                head_ok = True
                content_type = head_resp.headers.get("content-type", "video/mp4")
                # 从 Content-Length 或 Content-Range 获取文件总大小
                content_length_hdr = head_resp.headers.get("content-length")
                content_range_hdr = head_resp.headers.get("content-range")
                if content_length_hdr:
                    total_size = int(content_length_hdr)
                elif content_range_hdr:
                    # Content-Range: bytes 0-1023/10240 → 取 / 后面的总大小
                    parts = content_range_hdr.split("/")
                    if len(parts) == 2 and parts[1] != "*":
                        total_size = int(parts[1])
    except Exception:
        pass  # HEAD 失败，回退为完整流转发

    # HEAD 请求失败时：直接流式转发完整视频，不处理 Range
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

    # 解析 Range 请求，计算起止字节位置
    start = 0
    end = total_size - 1

    if range_header:
        # Range: bytes=0-1023 或 bytes=0-
        try:
            range_spec = range_header.replace("bytes=", "").strip()
            range_parts = range_spec.split("-")
            start = int(range_parts[0]) if range_parts[0] else 0
            end = int(range_parts[1]) if len(range_parts) > 1 and range_parts[1] else total_size - 1
            # 边界保护
            start = max(0, min(start, total_size - 1))
            end = max(start, min(end, total_size - 1))
        except (ValueError, IndexError):
            start = 0
            end = total_size - 1

    # 构造转发给上游的 Range 请求头
    req_headers = {"User-Agent": "Agnes-Platform-VideoProxy"}
    if range_header:
        req_headers["Range"] = f"bytes={start}-{end}"

    # 本次响应的内容长度
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

    # 根据 Range 请求返回 206 或 200，并设置对应的 Content-Length / Content-Range
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


# =====================================================
# 视频缩略图 & 预览接口
# 用途：提取视频首帧作为缩略图，提取多帧生成 GIF 预览
# 缓存策略：使用文件系统缓存，避免重复提取
# =====================================================

# 缩略图缓存目录
THUMBNAIL_CACHE_DIR = os.path.join(tempfile.gettempdir(), "agnes_thumbnails")
os.makedirs(THUMBNAIL_CACHE_DIR, exist_ok=True)


def _get_cache_path(record_id: int, suffix: str, video_url: str = "") -> str:
    """
    根据记录 ID 和视频 URL 生成缓存文件路径。
    文件名包含视频 URL 的哈希值，避免删除旧记录后新记录复用相同 ID 时命中旧缓存。
    """
    url_hash = hashlib.md5(video_url.encode()).hexdigest()[:8] if video_url else "nourl"
    filename = f"video_{record_id}_{url_hash}{suffix}"
    return os.path.join(THUMBNAIL_CACHE_DIR, filename)


async def _download_video_partial(video_url: str, output_path: str, max_bytes: int = 5 * 1024 * 1024) -> bool:
    """
    下载视频的前 N 字节到临时文件（用于 ffmpeg 提取帧）。
    大多数视频的 moov atom 在文件头部，5MB 足够提取首帧。
    返回是否下载成功。
    """
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            async with client.stream("GET", video_url, headers={"Range": "bytes=0-" + str(max_bytes - 1)}) as response:
                # 某些服务器不支持 Range，返回 200；支持则返回 206
                if response.status_code not in (200, 206):
                    return False
                with open(output_path, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)
                        if f.tell() >= max_bytes:
                            break
        return os.path.getsize(output_path) > 0
    except Exception as e:
        logger.warning("[缩略图] 下载视频片段失败: %s", e)
        return False


async def _extract_frame_with_ffmpeg(input_path: str, output_path: str, time_offset: str = "0") -> bool:
    """
    使用 ffmpeg 从视频中提取指定时间点的帧。
    time_offset 格式：如 "0"（首帧）、"1"（第1秒）等。
    返回是否提取成功。
    """
    try:
        cmd = [
            "ffmpeg", "-y",
            "-ss", time_offset,
            "-i", input_path,
            "-vframes", "1",
            "-q:v", "4",
            "-vf", "scale=480:-2",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        if proc.returncode != 0:
            logger.warning("[缩略图] ffmpeg 提取帧失败 (offset=%s): %s", time_offset, stderr.decode(errors="ignore")[:200])
            return False
        return os.path.getsize(output_path) > 0
    except asyncio.TimeoutError:
        logger.warning("[缩略图] ffmpeg 超时")
        return False
    except Exception as e:
        logger.warning("[缩略图] ffmpeg 异常: %s", e)
        return False


async def _extract_gif_with_ffmpeg(input_path: str, output_path: str, duration: float = 3.0) -> bool:
    """
    使用 ffmpeg 从视频中提取前 N 秒生成 GIF 预览。
    返回是否生成成功。
    """
    try:
        cmd = [
            "ffmpeg", "-y",
            "-t", str(duration),
            "-i", input_path,
            "-vf", "fps=6,scale=320:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
            "-loop", "0",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        if proc.returncode != 0:
            logger.warning("[缩略图] ffmpeg 生成 GIF 失败: %s", stderr.decode(errors="ignore")[:200])
            return False
        return os.path.getsize(output_path) > 0
    except asyncio.TimeoutError:
        logger.warning("[缩略图] ffmpeg GIF 生成超时")
        return False
    except Exception as e:
        logger.warning("[缩略图] ffmpeg GIF 异常: %s", e)
        return False


@router.get("/history/video/{record_id}/thumbnail", summary="视频首帧缩略图")
async def get_video_thumbnail(record_id: int, db: AsyncSession = Depends(get_async_db)):
    """
    提取视频首帧作为缩略图（JPEG 格式）。
    使用文件缓存，同一视频只提取一次。
    """
    # 查询视频记录
    result = await db.execute(
        select(Generation).filter(Generation.id == record_id)
    )
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="未找到对应视频记录")

    if record.type != "video":
        raise HTTPException(status_code=400, detail="该记录不是视频类型")

    if not record.result_url:
        raise HTTPException(status_code=404, detail="视频资源链接不存在")

    # 检查缓存（缓存路径包含视频 URL 哈希，避免旧记录缓存误命中）
    cache_path = _get_cache_path(record_id, "_thumb.jpg", record.result_url)
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        return FileResponse(
            cache_path,
            media_type="image/jpeg",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=86400",
            },
        )

    # 下载视频片段并提取首帧
    tmp_video = os.path.join(tempfile.gettempdir(), f"agnes_vtmp_{record_id}.mp4")
    try:
        download_ok = await _download_video_partial(record.result_url, tmp_video)
        if not download_ok:
            raise HTTPException(status_code=500, detail="下载视频片段失败，无法提取缩略图")

        extract_ok = await _extract_frame_with_ffmpeg(tmp_video, cache_path, time_offset="0")
        if not extract_ok:
            # 首帧提取失败时，尝试第 0.5 秒
            extract_ok = await _extract_frame_with_ffmpeg(tmp_video, cache_path, time_offset="0.5")

        if not extract_ok or not os.path.exists(cache_path):
            raise HTTPException(status_code=500, detail="提取视频首帧失败")

        return FileResponse(
            cache_path,
            media_type="image/jpeg",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=86400",
            },
        )
    finally:
        # 清理临时视频文件
        if os.path.exists(tmp_video):
            os.remove(tmp_video)


@router.get("/history/video/{record_id}/preview", summary="视频预览 GIF（悬停效果）")
async def get_video_preview(record_id: int, db: AsyncSession = Depends(get_async_db)):
    """
    生成视频前 3 秒的 GIF 预览，用于鼠标悬停时的动态效果。
    使用文件缓存，同一视频只生成一次。
    """
    # 查询视频记录
    result = await db.execute(
        select(Generation).filter(Generation.id == record_id)
    )
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="未找到对应视频记录")

    if record.type != "video":
        raise HTTPException(status_code=400, detail="该记录不是视频类型")

    if not record.result_url:
        raise HTTPException(status_code=404, detail="视频资源链接不存在")

    # 检查缓存（缓存路径包含视频 URL 哈希，避免旧记录缓存误命中）
    cache_path = _get_cache_path(record_id, "_preview.gif", record.result_url)
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        return FileResponse(
            cache_path,
            media_type="image/gif",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=86400",
            },
        )

    # 下载视频片段并生成 GIF
    tmp_video = os.path.join(tempfile.gettempdir(), f"agnes_vtmp_{record_id}_preview.mp4")
    try:
        download_ok = await _download_video_partial(record.result_url, tmp_video, max_bytes=10 * 1024 * 1024)
        if not download_ok:
            raise HTTPException(status_code=500, detail="下载视频片段失败，无法生成预览")

        gif_ok = await _extract_gif_with_ffmpeg(tmp_video, cache_path, duration=3.0)
        if not gif_ok or not os.path.exists(cache_path):
            raise HTTPException(status_code=500, detail="生成视频预览 GIF 失败")

        return FileResponse(
            cache_path,
            media_type="image/gif",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=86400",
            },
        )
    finally:
        # 清理临时视频文件
        if os.path.exists(tmp_video):
            os.remove(tmp_video)
