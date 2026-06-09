# =====================================================
# ChatSession 模型 — 聊天会话
# ChatMessage 模型 — 聊天消息（支持文本、图片、视频等富媒体内容）
#
# 设计说明：
#   - 每个会话包含多条消息，通过 session_id 关联
#   - 消息角色：user（用户）、assistant（AI 助手）、system（系统）
#   - 消息可携带媒体内容（生成的图片/视频），通过 media_type 和 media_url 字段存储
#   - 支持流式响应的增量内容拼接（content 字段逐步追加）
# =====================================================

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class ChatSession(Base):
    """
    聊天会话

    字段说明:
    - id: 主键
    - title: 会话标题（自动取首条用户消息的前 30 字符）
    - created_at: 创建时间
    - updated_at: 更新时间（最后一条消息的时间）
    """
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=True, default="新对话")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联消息（一对多）
    messages = relationship(
        "ChatMessage",
        back_populates="session",
        order_by="ChatMessage.id",
        cascade="all, delete-orphan",
    )

    def to_dict(self, include_messages=False):
        """便捷转换为字典"""
        result = {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_messages:
            result["messages"] = [m.to_dict() for m in self.messages]
        return result


class ChatMessage(Base):
    """
    聊天消息

    字段说明:
    - id: 主键
    - session_id: 所属会话 ID
    - role: 消息角色（user / assistant / system）
    - content: 文本内容
    - media_type: 媒体类型（image / video / None）
    - media_url: 媒体资源 URL（图片/视频的访问地址）
    - media_task_id: 媒体生成任务 ID（用于轮询生成状态）
    - media_status: 媒体生成状态（pending / processing / success / failed）
    - tool_calls: 工具调用信息（JSON 格式，记录 AI 发起的工具调用）
    - created_at: 创建时间
    """
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user / assistant / system
    content = Column(Text, nullable=True, default="")
    # 媒体相关字段（当 AI 调用生图/生视频工具时使用）
    media_type = Column(String(20), nullable=True)  # image / video / None
    media_url = Column(Text, nullable=True)  # 媒体资源 URL
    media_task_id = Column(String(200), nullable=True)  # 生成任务 ID
    media_status = Column(String(20), nullable=True)  # pending / processing / success / failed
    # 工具调用信息
    tool_calls = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关联会话
    session = relationship("ChatSession", back_populates="messages")

    def to_dict(self):
        """便捷转换为字典"""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content or "",
            "media_type": self.media_type,
            "media_url": self.media_url,
            "media_task_id": self.media_task_id,
            "media_status": self.media_status,
            "tool_calls": self.tool_calls,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
