# =====================================================
# 聊天路由（全异步 + SSE 流式响应）
#
# POST   /api/chat/sessions              - 创建新会话
# GET    /api/chat/sessions              - 获取会话列表
# GET    /api/chat/sessions/{id}         - 获取会话详情（含消息）
# DELETE /api/chat/sessions/{id}         - 删除会话
# POST   /api/chat/sessions/{id}/messages - 发送消息（SSE 流式响应）
# GET    /api/chat/sessions/{id}/messages - 获取会话消息列表
# GET    /api/chat/media-status/{task_id} - 查询媒体生成状态
#
# 关键设计：
#   - 发送消息使用 SSE（Server-Sent Events）流式返回 AI 回复
#   - 工具调用（生图/生视频）结果通过 SSE 事件实时推送
#   - 消息持久化到数据库，刷新页面后可恢复历史
# =====================================================

import logging
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc

from app.core.database import get_async_db
from app.core.config import settings
from app.models.chat import ChatSession, ChatMessage
from app.services.chat_service import chat_service
from app.services.image_poller import image_poller_manager
from app.services.video_poller import poller_manager as video_poller_manager

logger = logging.getLogger("agnes_platform")
router = APIRouter()


# =====================================================
# 请求/响应 Schema
# =====================================================

class CreateSessionRequest(BaseModel):
    """创建会话请求"""
    title: Optional[str] = Field(default=None, description="会话标题（可选，默认取首条消息前 30 字）")


class SendMessageRequest(BaseModel):
    """发送消息请求"""
    content: str = Field(..., min_length=1, description="消息内容")


class SessionResponse(BaseModel):
    """会话响应"""
    id: int
    title: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class MessageResponse(BaseModel):
    """消息响应"""
    id: int
    session_id: int
    role: str
    content: str
    media_type: Optional[str] = None
    media_url: Optional[str] = None
    media_task_id: Optional[str] = None
    media_status: Optional[str] = None
    created_at: Optional[str] = None


# =====================================================
# 会话管理接口
# =====================================================

@router.post("/chat/sessions", summary="创建新聊天会话")
async def create_session(
    req: CreateSessionRequest = None,
    db: AsyncSession = Depends(get_async_db),
):
    """创建一个新的聊天会话"""
    session = ChatSession(
        title=req.title if req and req.title else "新对话",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    logger.info("[Chat] 创建会话: id=%s, title=%s", session.id, session.title)
    return session.to_dict()


@router.get("/chat/sessions", summary="获取会话列表")
async def list_sessions(
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_async_db),
):
    """获取会话列表，按更新时间倒序"""
    # 总数
    from sqlalchemy import func
    count_result = await db.execute(select(func.count()).select_from(ChatSession))
    total = count_result.scalar_one() or 0

    # 分页查询
    stmt = (
        select(ChatSession)
        .order_by(desc(ChatSession.updated_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [s.to_dict() for s in sessions],
    }


@router.get("/chat/sessions/{session_id}", summary="获取会话详情（含消息）")
async def get_session(
    session_id: int,
    db: AsyncSession = Depends(get_async_db),
):
    """获取会话详情，包含所有消息"""
    result = await db.execute(
        select(ChatSession).filter(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    return session.to_dict(include_messages=True)


@router.delete("/chat/sessions/{session_id}", summary="删除会话")
async def delete_session(
    session_id: int,
    db: AsyncSession = Depends(get_async_db),
):
    """删除会话及其所有消息"""
    result = await db.execute(
        select(ChatSession).filter(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    await db.delete(session)
    await db.commit()
    logger.info("[Chat] 删除会话: id=%s", session_id)
    return {"success": True, "message": f"会话 {session_id} 已删除"}


# =====================================================
# 消息接口
# =====================================================

@router.get("/chat/sessions/{session_id}/messages", summary="获取会话消息列表")
async def get_messages(
    session_id: int,
    db: AsyncSession = Depends(get_async_db),
):
    """获取指定会话的所有消息"""
    # 检查会话是否存在
    result = await db.execute(
        select(ChatSession).filter(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 查询消息
    result = await db.execute(
        select(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id)
    )
    messages = result.scalars().all()
    return {"items": [m.to_dict() for m in messages]}


@router.post("/chat/sessions/{session_id}/messages", summary="发送消息（SSE 流式响应）")
async def send_message(
    session_id: int,
    req: SendMessageRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """
    发送消息并获取 AI 流式回复（SSE）。

    SSE 事件格式（每行以 "data: " 开头）：
    - {"type": "user_message", "message": {...}} — 用户消息已保存
    - {"type": "text", "content": "..."} — AI 文本增量
    - {"type": "tool_call", "tool": "generate_image", "args": {...}} — 工具调用
    - {"type": "tool_result", "tool": "generate_image", "result": {...}} — 工具结果
    - {"type": "assistant_message", "message": {...}} — AI 消息已保存
    - {"type": "done"} — 结束
    """
    # API Key 检查
    if not settings.agnes_api_key or settings.agnes_api_key.startswith("sk-your"):
        raise HTTPException(
            status_code=401,
            detail="Agnes AI API Key 未配置，请在 backend/.env 中设置 AGNES_API_KEY",
        )

    # 检查会话是否存在
    result = await db.execute(
        select(ChatSession).filter(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 保存用户消息
    user_msg = ChatMessage(
        session_id=session_id,
        role="user",
        content=req.content,
    )
    db.add(user_msg)

    # 更新会话标题（如果是第一条消息）
    if session.title == "新对话":
        session.title = req.content[:30] + ("..." if len(req.content) > 30 else "")

    # 更新会话时间
    session.updated_at = __import__("datetime").datetime.utcnow()
    await db.commit()
    await db.refresh(user_msg)

    # 获取历史消息（用于构建上下文）
    result = await db.execute(
        select(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id)
    )
    all_messages = result.scalars().all()

    # 构建对话历史（只取 role 和 content，过滤掉系统消息）
    chat_history = []
    for msg in all_messages:
        if msg.role in ("user", "assistant"):
            chat_history.append({"role": msg.role, "content": msg.content or ""})

    # SSE 流式生成器
    async def event_generator():
        """SSE 事件生成器"""
        # 先发送用户消息确认
        yield f"data: {json.dumps({'type': 'user_message', 'message': user_msg.to_dict()}, ensure_ascii=False)}\n\n"

        # 收集 AI 回复内容
        assistant_content = ""
        media_type = None
        media_url = None
        media_task_id = None
        media_status = None
        tool_calls_info = []

        try:
            async for chunk in chat_service.chat_stream(chat_history, session_id):
                yield f"data: {chunk}\n\n"

                # 解析事件，收集信息用于保存
                try:
                    event = json.loads(chunk)
                    if event.get("type") == "text":
                        assistant_content += event.get("content", "")
                    elif event.get("type") == "tool_result":
                        result_data = event.get("result", {})
                        media_type = result_data.get("media_type")
                        media_task_id = result_data.get("task_id") or result_data.get("video_id")
                        media_status = result_data.get("status")
                        tool_calls_info.append({
                            "tool": event.get("tool"),
                            "result": result_data,
                        })
                except (json.JSONDecodeError, KeyError):
                    pass

        except Exception as e:
            logger.error("[Chat] SSE 生成异常: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

        # 保存 AI 回复到数据库
        try:
            assistant_msg = ChatMessage(
                session_id=session_id,
                role="assistant",
                content=assistant_content,
                media_type=media_type,
                media_url=media_url,
                media_task_id=media_task_id,
                media_status=media_status or ("pending" if media_type else None),
                tool_calls=tool_calls_info if tool_calls_info else None,
            )
            db_new = None
            try:
                # 使用新的 db session（因为当前请求的 session 可能已关闭）
                async with get_async_db() as db_new:
                    db_new.add(assistant_msg)
                    # 更新会话时间
                    session_result = await db_new.execute(
                        select(ChatSession).filter(ChatSession.id == session_id)
                    )
                    session_obj = session_result.scalar_one_or_none()
                    if session_obj:
                        session_obj.updated_at = __import__("datetime").datetime.utcnow()
                    await db_new.commit()
                    await db_new.refresh(assistant_msg)
            except Exception as db_err:
                logger.warning("[Chat] 保存 AI 回复失败: %s", db_err)

            # 发送保存确认
            yield f"data: {json.dumps({'type': 'assistant_message', 'message': assistant_msg.to_dict()}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error("[Chat] 保存 AI 回复异常: %s", e)

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =====================================================
# 媒体生成状态查询
# =====================================================

@router.get("/chat/media-status/{task_id}", summary="查询媒体生成状态")
async def get_media_status(task_id: str):
    """
    查询图片/视频生成任务的状态。
    前端轮询此接口获取生成进度和结果 URL。
    """
    # 先尝试图片任务
    image_task = await image_poller_manager.get_status(task_id)
    if image_task:
        return image_task.to_dict()

    # 再尝试视频任务
    video_task = await video_poller_manager.get_status(task_id=task_id)
    if not video_task:
        video_task = await video_poller_manager.get_status(video_id=task_id)
    if video_task:
        return video_task.to_dict()

    # 最后查数据库
    try:
        async with get_async_db() as db:
            from app.models.generation import Generation
            result = await db.execute(
                select(Generation).filter(Generation.task_id == task_id)
            )
            record = result.scalar_one_or_none()
            if record:
                return {
                    "task_id": task_id,
                    "status": record.status,
                    "result_url": record.result_url,
                    "type": record.type,
                }
    except Exception as e:
        logger.warning("[Chat] 数据库查询媒体状态失败: %s", e)

    raise HTTPException(status_code=404, detail=f"未找到任务（ID: {task_id}）")
