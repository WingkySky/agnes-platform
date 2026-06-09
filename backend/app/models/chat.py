# =====================================================
# ChatSession 模型 — 聊天会话
# ChatMessage 模型 — 聊天消息（支持文本、图片、视频等富媒体内容）
#
# 设计说明：
#   - 每个会话包含多条消息，通过 session_id 关联
#   - 消息角色：user（用户）、assistant（AI 助手）、system（系统）
#   - 消息可携带多个媒体内容（图片/视频），通过 media_items JSON 数组存储
#   - 每个媒体项包含：type、url、task_id、status
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
    - media_items: 媒体项列表（JSON 数组），每项格式：
        {
          "type": "image" | "video",
          "url": "https://...",       # 生成完成后的资源 URL
          "task_id": "img_xxx",       # 生成任务 ID（用于轮询状态）
          "status": "pending" | "processing" | "success" | "failed"
        }
    - tool_calls: 工具调用信息（JSON 格式，记录 AI 发起的工具调用）
    - created_at: 创建时间
    """
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user / assistant / system
    content = Column(Text, nullable=True, default="")
    # 媒体项列表（支持多图/多视频）
    media_items = Column(JSON, nullable=True, default=list)
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
            "media_items": self.media_items or [],
            "tool_calls": self.tool_calls,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
