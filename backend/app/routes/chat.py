# =====================================================
# 聊天路由（全异步 + SSE 流式响应）
#
# POST   /api/chat/sessions              - 创建新会话
# GET    /api/chat/sessions              - 获取会话列表
# GET    /api/chat/sessions/{id}         - 获取会话详情（含消息）
# DELETE /api/chat/sessions/{id}         - 删除会话
# POST   /api/chat/sessions/{id}/messages - 发送消息（SSE 流式响应）
# GET    /api/chat/sessions/{id}/messages - 获取会话消息列表
# POST   /api/chat/media-callback        - 媒体生成完成回调（更新消息中的 media_items）
# GET    /api/chat/media-status/{task_id} - 查询媒体生成状态
#
# 关键设计：
#   - 发送消息使用 SSE（Server-Sent Events）流式返回 AI 回复
#   - 工具调用（生图/生视频）结果通过 SSE 事件实时推送
#   - 消息持久化到数据库，刷新页面后可恢复历史
#   - 媒体项使用 media_items JSON 数组，支持多图/多视频
#   - 媒体生成完成后，前端通过回调接口更新消息的 media_items
# =====================================================

import logging
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc, func

from app.core.database import get_async_db, async_session
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


class UpdateSessionRequest(BaseModel):
    """修改会话标题请求"""
    title: str = Field(..., min_length=1, max_length=200, description="新的会话标题")


class SendMessageRequest(BaseModel):
    """发送消息请求
    - content: 消息文本（可为空字符串，此时以附件为主）
    - attachments: 可选的参考图列表（单张 ≤ 5MB，总数 ≤ 10）
    """
    content: str = Field(default="", description="消息内容（可为空字符串）")
    attachments: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="参考图列表，每项: {name, base64_image, size, mime_type"
    )


class MediaCallbackRequest(BaseModel):
    """媒体生成完成回调请求"""
    message_id: int = Field(..., description="消息 ID")
    task_id: str = Field(..., description="生成任务 ID")
    media_url: str = Field(..., description="生成完成的资源 URL")
    status: str = Field(default="success", description="状态：success / failed")


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


@router.put("/chat/sessions/{session_id}", summary="修改会话标题")
async def update_session(
    session_id: int,
    req: UpdateSessionRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """修改会话的标题"""
    result = await db.execute(
        select(ChatSession).filter(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    session.title = req.title[:200]
    session.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(session)
    logger.info("[Chat] 修改会话标题: id=%s, title=%s", session_id, session.title)
    return session.to_dict()


@router.post("/chat/sessions/{session_id}/summarize", summary="AI 自动总结会话主题")
async def summarize_session(
    session_id: int,
    db: AsyncSession = Depends(get_async_db),
):
    """使用 AI 分析对话内容，自动生成一个有意义的会话标题"""
    # 检查会话是否存在
    result = await db.execute(
        select(ChatSession).filter(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 获取会话的前几条消息（用于总结主题）
    result = await db.execute(
        select(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id)
        .limit(10)
    )
    messages = result.scalars().all()

    if not messages:
        raise HTTPException(status_code=400, detail="会话没有消息，无法总结主题")

    # 调用 AI 服务生成标题
    try:
        summary_title = await chat_service.summarize_session_title(messages)
    except Exception as e:
        logger.warning("[Chat] AI 总结标题失败，使用降级方案: %s", e)
        # 降级方案：取第一条用户消息的前 30 字
        first_user_msg = next((m for m in messages if m.role == "user"), None)
        summary_title = (first_user_msg.content[:30] + "..." if first_user_msg and first_user_msg.content and len(first_user_msg.content) > 30
                         else (first_user_msg.content if first_user_msg else "新对话"))

    # 更新会话标题
    session.title = summary_title[:200]
    session.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(session)
    logger.info("[Chat] 自动总结会话标题: id=%s, title=%s", session_id, session.title)
    return session.to_dict()


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

    # 对每条消息，检查 media_items 中 pending 状态的任务是否已完成
    # 如果已完成，更新 media_items 中的 url 和 status
    for msg in messages:
        if msg.media_items:
            updated = False
            for item in msg.media_items:
                if item.get("status") in ("pending", "processing") and item.get("task_id"):
                    # 查询任务状态
                    task_id = item["task_id"]
                    result_url = None
                    new_status = None

                    # 尝试图片任务
                    img_task = await image_poller_manager.get_status(task_id)
                    if img_task:
                        d = img_task.to_dict()
                        if d.get("status") in ("success", "completed", "done"):
                            result_url = d.get("result_url") or d.get("url")
                            new_status = "success"
                        elif d.get("status") in ("failed", "error"):
                            new_status = "failed"

                    # 尝试视频任务
                    if not result_url and not new_status:
                        vid_task = await video_poller_manager.get_status(task_id=task_id)
                        if not vid_task:
                            vid_task = await video_poller_manager.get_status(video_id=task_id)
                        if vid_task:
                            d = vid_task.to_dict()
                            if d.get("status") in ("success", "completed", "done"):
                                result_url = d.get("video_url") or d.get("url")
                                new_status = "success"
                            elif d.get("status") in ("failed", "error"):
                                new_status = "failed"

                    # 回退查数据库
                    if not result_url and not new_status:
                        try:
                            from app.models.generation import Generation
                            gen_result = await db.execute(
                                select(Generation).filter(Generation.task_id == task_id)
                            )
                            gen_record = gen_result.scalar_one_or_none()
                            if gen_record:
                                if gen_record.status == "success":
                                    result_url = gen_record.result_url
                                    new_status = "success"
                                elif gen_record.status == "failed":
                                    new_status = "failed"
                        except Exception:
                            pass

                    # 更新 media_item
                    if result_url or new_status:
                        if result_url:
                            item["url"] = result_url
                        if new_status:
                            item["status"] = new_status
                        updated = True

            # 如果有更新，写回数据库
            if updated:
                msg.media_items = list(msg.media_items)  # 触发 SQLAlchemy 检测变更
                await db.commit()

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

    # ── 附件校验与清洗（Task 2） ──
    # 如果用户提供了 attachments，进行大小/数量/格式校验
    MAX_ATTACHMENTS = 10
    MAX_SIZE_PER_FILE = 5 * 1024 * 1024  # 5MB

    validated_attachments = []
    if req.attachments:
        if len(req.attachments) > MAX_ATTACHMENTS:
            raise HTTPException(
                status_code=400,
                detail=f"最多上传 {MAX_ATTACHMENTS} 张参考图，当前 {len(req.attachments)} 张"
            )
        for att in req.attachments:
            try:
                size = int(att.get("size", 0))
            except (TypeError, ValueError):
                size = 0
            if size > MAX_SIZE_PER_FILE:
                raise HTTPException(
                    status_code=413,
                    detail=f"单张参考图大小超过 5MB 限制: {att.get('name', 'unknown')}"
                )
            base64_image = att.get("base64_image", "")
            if not base64_image or not isinstance(base64_image, str) or not base64_image.startswith("data:image/"):
                # 非法的 base64 或非图片 mime —— 跳过并记录警告，不阻塞整个请求
                logger.warning("[Chat] 忽略非法的附件: name=%s mime=%s",
                               att.get("name"), att.get("mime_type"))
                continue
            validated_attachments.append({
                "name": att.get("name", "image.png"),
                "base64_image": base64_image,
                "size": size,
                "mime_type": att.get("mime_type", "image/png"),
            })

    # 允许 content 为空但有附件（用户可以"只甩一张图说画图"）
    if not req.content.strip() and not validated_attachments:
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    # 保存用户消息（同时保存 attachments）
    user_msg = ChatMessage(
        session_id=session_id,
        role="user",
        content=req.content,
        attachments=validated_attachments if validated_attachments else [],
    )
    db.add(user_msg)

    # 注意：不再简单截断用户消息作为标题
    # 改为在 AI 回复完成后，由 AI 自动总结对话主题生成有意义的标题
    # 更新会话时间
    session.updated_at = datetime.utcnow()
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
        """
        SSE 事件生成器。

        关键设计（参考 AgnesAI-main 的可靠性模式）：
          - 流式开始前就创建 assistant 消息（占位）并写入数据库，
            这样即使客户端中途断开/切换页面，已生成的内容也不会丢失。
          - 每收到一个 text / tool_result 事件就增量更新数据库，
            保证切换页面后从数据库能恢复最新状态。
          - 使用 async_session() 创建独立的数据库连接，
            避免与外层请求 db 的事务边界冲突。
        """
        # 先发送用户消息确认
        yield f"data: {json.dumps({'type': 'user_message', 'message': user_msg.to_dict()}, ensure_ascii=False)}\n\n"

        # 收集 AI 回复内容
        assistant_content = ""
        # 收集所有媒体项（支持多个）
        media_items = []
        tool_calls_info = []

        # ── 流式开始前：先在数据库里创建一条 assistant 消息（占位） ──
        #    这样即使客户端中途断开，已经推送给用户的内容也能被恢复。
        assistant_msg_id = None
        try:
            async with async_session() as db_write:
                assistant_msg = ChatMessage(
                    session_id=session_id,
                    role="assistant",
                    content="",
                    media_items=[],
                    tool_calls=None,
                )
                db_write.add(assistant_msg)
                # 同时更新会话时间
                session_result_w = await db_write.execute(
                    select(ChatSession).filter(ChatSession.id == session_id)
                )
                session_obj_w = session_result_w.scalar_one_or_none()
                if session_obj_w:
                    session_obj_w.updated_at = datetime.utcnow()
                await db_write.commit()
                await db_write.refresh(assistant_msg)
                assistant_msg_id = assistant_msg.id
        except Exception as e:
            logger.error("[Chat] 创建 assistant 占位消息失败: %s", e)

        # 发送刚创建的 assistant_message_created（含真实 DB ID）
        # 这样前端一上来就拿到真实 message_id，media_callback 随时可以回写
        if assistant_msg_id:
            try:
                async with async_session() as db_read:
                    first_msg = await db_read.get(ChatMessage, assistant_msg_id)
                    if first_msg:
                        yield f"data: {json.dumps({'type': 'assistant_message_created', 'message': first_msg.to_dict()}, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.warning("[Chat] 读取刚创建的 assistant 消息失败: %s", e)

        # ── 流式生成主循环 ──
        try:
            async for chunk in chat_service.chat_stream(
                chat_history,
                session_id,
                attachments=validated_attachments if validated_attachments else None,
            ):
                yield f"data: {chunk}\n\n"

                # 解析事件，收集信息并增量写入数据库
                try:
                    event = json.loads(chunk)
                    changed = False
                    if event.get("type") == "text":
                        assistant_content += event.get("content", "")
                        changed = True
                    elif event.get("type") == "tool_result":
                        result_data = event.get("result", {})
                        tool_name = event.get("tool", "")
                        if result_data.get("media_type") and result_data.get("status") != "error":
                            media_item = {
                                "type": result_data.get("media_type"),
                                "url": result_data.get("url", ""),
                                "task_id": result_data.get("task_id") or result_data.get("video_id", ""),
                                "status": result_data.get("status", "pending"),
                            }
                            # 避免重复添加同一个 task_id
                            if not any(m.get("task_id") == media_item["task_id"] for m in media_items):
                                media_items.append(media_item)
                        tool_calls_info.append({
                            "tool": tool_name,
                            "result": result_data,
                        })
                        changed = True

                    # 增量更新数据库（只有当有变化且 assistant_msg_id 存在时才更新）
                    if changed and assistant_msg_id:
                        try:
                            async with async_session() as db_upd:
                                msg_upd = await db_upd.get(ChatMessage, assistant_msg_id)
                                if msg_upd:
                                    msg_upd.content = assistant_content
                                    msg_upd.media_items = list(media_items) if media_items else []
                                    msg_upd.tool_calls = tool_calls_info if tool_calls_info else None
                                    session_result_upd = await db_upd.execute(
                                        select(ChatSession).filter(ChatSession.id == session_id)
                                    )
                                    session_obj_upd = session_result_upd.scalar_one_or_none()
                                    if session_obj_upd:
                                        session_obj_upd.updated_at = datetime.utcnow()
                                    await db_upd.commit()
                        except Exception as inner_e:
                            logger.warning("[Chat] 增量更新消息失败: %s", inner_e)
                except (json.JSONDecodeError, KeyError):
                    pass

        except Exception as e:
            logger.error("[Chat] SSE 生成异常: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

        # ── 流结束：发送最终的 assistant_message 事件（供前端更新最终状态） ──
        if assistant_msg_id:
            try:
                async with async_session() as db_final:
                    final_msg = await db_final.get(ChatMessage, assistant_msg_id)
                    if final_msg:
                        yield f"data: {json.dumps({'type': 'assistant_message', 'message': final_msg.to_dict()}, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.error("[Chat] 读取最终 AI 消息失败: %s", e)

        # ── 自动总结会话标题（如果是新对话的第一轮） ──
        #    参考 ChatGPT/Claude 的行为：对话完成后，AI 自动生成一个有意义的标题
        #    这个过程在后台进行，不阻塞用户的对话体验
        try:
            async with async_session() as db_title:
                session_for_title = await db_title.get(ChatSession, session_id)
                if session_for_title and session_for_title.title == "新对话":
                    # 收集会话的前几条消息（用户 + AI 的回复）用于总结
                    msgs_for_title_result = await db_title.execute(
                        select(ChatMessage)
                        .filter(ChatMessage.session_id == session_id)
                        .order_by(ChatMessage.id)
                        .limit(6)
                    )
                    msgs_for_title = msgs_for_title_result.scalars().all()

                    if msgs_for_title:
                        # 调用 AI 生成标题
                        auto_title = await chat_service.summarize_session_title(msgs_for_title)
                        if auto_title and auto_title != "新对话":
                            session_for_title.title = auto_title[:200]
                            session_for_title.updated_at = datetime.utcnow()
                            await db_title.commit()
                            logger.info("[Chat] 自动总结会话标题: id=%s, title=%s", session_id, auto_title)
                            # 通过 SSE 发送标题更新事件，通知前端刷新
                            yield f"data: {json.dumps({'type': 'title_updated', 'title': auto_title}, ensure_ascii=False)}\n\n"
        except Exception as e:
            # 自动总结失败不影响主流程，只记录日志
            logger.warning("[Chat] 自动总结会话标题失败: %s", e)

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
# 媒体回调接口 — 前端轮询到结果后调用此接口更新消息
# =====================================================

@router.post("/chat/media-callback", summary="媒体生成完成回调")
async def media_callback(
    req: MediaCallbackRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """
    前端检测到媒体生成完成后，调用此接口更新消息中的 media_items。
    这样刷新页面后也能看到已生成的媒体资源。
    """
    result = await db.execute(
        select(ChatMessage).filter(ChatMessage.id == req.message_id)
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")

    # 更新 media_items 中对应 task_id 的项
    if msg.media_items:
        updated = False
        for item in msg.media_items:
            if item.get("task_id") == req.task_id:
                item["url"] = req.media_url
                item["status"] = req.status
                updated = True
                break

        if updated:
            # 触发 SQLAlchemy 检测 JSON 字段变更
            msg.media_items = list(msg.media_items)
            await db.commit()
            logger.info("[Chat] 媒体回调更新: message_id=%s, task_id=%s, status=%s",
                        req.message_id, req.task_id, req.status)
            return {"success": True, "message": "媒体状态已更新"}

    return {"success": False, "message": "未找到对应的媒体项"}


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
        async with async_session() as db:
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

    # 任务不在内存中也不在数据库中，返回 unknown 状态而非 404
    # 前端收到 unknown 后会停止轮询，避免无限 404 循环
    return {
        "task_id": task_id,
        "status": "unknown",
        "message": "任务已过期或不存在，请停止轮询",
    }
