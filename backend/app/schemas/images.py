# =====================================================
# 图片生成相关的 Pydantic Schema
# =====================================================

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class ImageGenerationRequest(BaseModel):
    """
    图片生成请求体（支持 text2image 与 image2image）

    - 文生图模式：只需填写 prompt 和可选的 size
    - 图生图模式：提供 base64_images / image_urls（多图，推荐），或旧字段 base64_image / image_url（兼容）
    """

    prompt: str = Field(..., min_length=1, max_length=2000, description="提示词")
    model: str = Field(default="agnes-image-2.1-flash", description="模型名称")
    size: str = Field(default="1024x1024", description="图片尺寸，格式: 宽x高")
    response_format: str = Field(default="url", description="响应格式: url 或 b64_json")
    quality: Optional[str] = Field(default="standard", description="图片质量 (standard/hd)")

    # ── 前端兼容字段：mode（自动转换为 is_image_to_image） ──
    mode: Optional[str] = Field(default=None, description="【前端兼容】'text2image' 或 'image2image'")

    # ── 新字段：多图参考（推荐使用） ──
    base64_images: Optional[List[str]] = Field(
        default=None,
        description="图生图时的多张参考图片(base64 data URI 或纯 base64 字符串)，支持多张",
    )
    image_urls: Optional[List[str]] = Field(
        default=None,
        description="图生图时的多张参考图片 URL（公网可访问链接），支持多张",
    )

    # ── 旧字段：单图参考（保留以保持向后兼容，内部会自动合并到数组） ──
    base64_image: Optional[str] = Field(
        default=None,
        description="【旧字段，兼容用】单张参考图片 base64；新代码请使用 base64_images",
    )
    image_url: Optional[str] = Field(
        default=None,
        description="【旧字段，兼容用】单张参考图片 URL；新代码请使用 image_urls",
    )

    @property
    def all_reference_images(self) -> List[str]:
        """
        合并新旧字段，返回统一的参考图列表（每个元素是 data URI 或公网 URL）。
        优先级：新字段数组 > 旧字段单值。
        """
        result: List[str] = []
        # 新字段优先
        if self.base64_images:
            for img in self.base64_images:
                if img and isinstance(img, str) and img.strip():
                    result.append(img)
        if self.image_urls:
            for url in self.image_urls:
                if url and isinstance(url, str) and url.strip():
                    result.append(url)
        # 如果新字段为空，回退到旧字段
        if not result:
            if self.base64_image and self.base64_image.strip():
                result.append(self.base64_image)
            if self.image_url and self.image_url.strip():
                result.append(self.image_url)
        return result

    @property
    def is_image_to_image(self) -> bool:
        """是否为图生图（参考图存在 或 mode 显式为 image2image）"""
        if self.mode:
            if self.mode == "image2image" and len(self.all_reference_images) > 0:
                return True
            if self.mode == "text2image":
                return False
        return len(self.all_reference_images) > 0

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
