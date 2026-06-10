# =====================================================
# 图片生成相关的 Pydantic Schema
# =====================================================

from typing import Optional
from pydantic import BaseModel, Field, field_validator


class ImageGenerationRequest(BaseModel):
    """
    图片生成请求体

    文生图模式：只需填写 prompt 和可选的 size
    图生图模式：额外提供 base64_image（参考图）
    """

    prompt: str = Field(..., min_length=1, max_length=2000, description="提示词")
    model: str = Field(default="agnes-image-2.1-flash", description="模型名称")
    size: str = Field(default="1024x1024", description="图片尺寸，格式: 宽x高")
    response_format: str = Field(default="url", description="响应格式: url 或 b64_json")
    base64_image: Optional[str] = Field(
        default=None,
        description="图生图时的参考图片（base64 格式，不含前缀）",
    )
    # 图片 URL（与 base64_image 二选一，URL 模式下直接传公网链接）
    image_url: Optional[str] = Field(
        default=None,
        description="图生图时的参考图片 URL（公网可访问链接，与 base64_image 二选一）",
    )

    @field_validator("prompt")
    @classmethod
    def prompt_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("prompt 不能为空")
        return v.strip()

    @field_validator("size")
    @classmethod
    def validate_size(cls, v):
        if not v:
            return "1024x1024"
        parts = v.lower().split("x")
        if len(parts) != 2:
            raise ValueError("尺寸格式错误，应为 '宽x高'，如 1024x1024")
        try:
            w, h = int(parts[0]), int(parts[1])
            if w < 256 or h < 256 or w > 4096 or h > 4096:
                raise ValueError("尺寸范围应在 256-4096 之间")
        except ValueError as e:
            raise e
        return v

    @field_validator("response_format")
    @classmethod
    def validate_response_format(cls, v):
        if v not in ("url", "b64_json"):
            return "url"
        return v


class ImageGenerationResponse(BaseModel):
    """图片生成响应体"""
    id: Optional[int] = None                   # 保存到数据库后的记录 ID
    status: str = "success"                     # success / failed / pending
    url: Optional[str] = None                   # 生成结果的 URL
    b64_json: Optional[str] = None              # 如果 response_format=b64_json 则返回 base64
    model: str                                  # 使用的模型
    prompt: str                                 # 提示词
    size: str                                   # 图片尺寸
    created_at: Optional[str] = None            # 创建时间（ISO 格式字符串）
    message: Optional[str] = None               # 出错时的错误信息


class ImageRecordResponse(BaseModel):
    """单张图片记录响应体"""
    id: int
    type: str = "image"
    prompt: str
    model: Optional[str] = None
    params: Optional[dict] = None
    result_url: Optional[str] = None
    status: str
    created_at: Optional[str] = None

    class Config:
        from_attributes = True
