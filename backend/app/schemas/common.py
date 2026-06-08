# =====================================================
# 通用 / 历史记录相关的 Pydantic Schema
# =====================================================

from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    service: str


class ConfigResponse(BaseModel):
    """前端可用配置（不含敏感信息）"""

    # 支持的图片尺寸
    image_sizes: List[str] = Field(
        default=["1024x768", "1024x1024", "768x1024", "512x512"],
        description="支持的图片尺寸选项",
    )

    # 图片模型
    image_models: List[str] = Field(
        default=["agnes-image-2.1-flash"],
        description="支持的图片生成模型",
    )

    # 视频模型
    video_models: List[str] = Field(
        default=["agnes-video-v2.0"],
        description="支持的视频生成模型",
    )

    # 视频帧数选项（需满足 8n+1 规则）
    video_num_frames: List[int] = Field(
        default=[9, 33, 49, 81, 121, 161, 241, 441],
        description="支持的视频帧数选项（需满足 8n+1）",
    )

    # 默认帧率
    default_frame_rate: int = 24

    # 默认分辨率
    default_video_width: int = 1152
    default_video_height: int = 768

    # 上传限制
    max_upload_size_mb: int = 10


# =====================================================
# 历史记录相关 Schema
# =====================================================

class GenerationRecord(BaseModel):
    """生成记录响应体"""
    id: int
    type: str                      # 'image' | 'video'
    prompt: str
    model: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    result_url: Optional[str] = None
    status: str
    task_id: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True    # Pydantic v2 对应原来的 orm_mode


class HistoryListResponse(BaseModel):
    """历史列表响应体（支持分页）"""
    total: int
    page: int
    page_size: int
    items: List[GenerationRecord]


class DeleteResponse(BaseModel):
    """删除操作响应"""
    success: bool
    message: str


# =====================================================
# 批量删除相关 Schema
# =====================================================

class BatchDeleteRequest(BaseModel):
    """批量删除请求体（接收记录 ID 列表）"""
    ids: List[int] = Field(..., description="要删除的记录 ID 列表")


class BatchDeleteResponse(BaseModel):
    """批量删除操作响应"""
    success: bool
    message: str
    deleted_count: int = Field(description="实际成功删除的记录数量")
    failed_ids: List[int] = Field(default_factory=list, description="删除失败的记录 ID 列表")
