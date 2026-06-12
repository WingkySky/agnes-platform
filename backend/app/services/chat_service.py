# =====================================================
# Chat Service — 聊天服务层
#
# 核心功能：
#   1. 调用 Agnes AI Chat API（agnes-2.0-flash）进行对话
#   2. 通过工具调用（Tool Calling）检测用户生图/生视频意图
#   3. 自动触发图片/视频生成任务
#   4. 支持流式响应（SSE），逐 token 返回给前端
#
# 流程：
#   用户消息 → Agnes Chat API（带 tools 定义）
#     → 如果模型返回 tool_calls：
#         → 执行对应工具（generate_image / generate_video）
#         → 将工具结果回传给模型
#         → 模型生成最终文本回复
#     → 如果模型返回纯文本：
#         → 直接流式返回给前端
# =====================================================

import logging
import json
import re
from typing import AsyncGenerator, Optional, Dict, Any, List

import httpx

from app.core.config import settings
from app.services.agnes_client import agnes_client

logger = logging.getLogger("agnes_platform")


# =====================================================
# 工具定义（告诉 Agnes AI 可以调用哪些工具）
# =====================================================
CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": (
                "当用户明确要求生成、创建、绘制图片时调用此工具。"
                "用户可能说'帮我画一张图'、'生成一张风景图'、'画一个猫咪'等。"
                "请将用户的描述转化为详细的英文图片提示词。"
                "注意：用户上传图片或提供图片链接不代表要生成图片，只有用户明确使用'生成'、'画'、'创建'等动作词时才调用。"
                "如果用户提供了参考图且明确要求基于参考图生成，将 mode 设置为 'image2image'。"
                "如果用户明确说'忽略图片，直接画图'，请将 use_reference_image 设置为 false。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "图片生成的英文提示词，需要详细描述主体、场景、风格、光照、构图等",
                    },
                    "size": {
                        "type": "string",
                        "description": "图片尺寸，如 1024x1024、1024x768、768x1024",
                        "enum": ["1024x1024", "1024x768", "768x1024"],
                    },
                    "mode": {
                        "type": "string",
                        "description": "生成模式：text2image（纯文生图）或 image2image（基于参考图）",
                        "enum": ["text2image", "image2image"],
                    },
                    "use_reference_image": {
                        "type": "boolean",
                        "description": "是否使用用户上传的参考图（有参考图时默认 true；若用户明确说忽略则设为 false）",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_video",
            "description": (
                "当用户明确要求生成、创建视频时调用此工具。"
                "用户可能说'帮我生成一段视频'、'创建一个短视频'、'做个视频'等。"
                "请将用户的描述转化为详细的英文视频提示词。"
                "注意：用户上传图片或提供图片链接不代表要生成视频，只有用户明确使用'生成'、'创建'等动作词时才调用。"
                "如果用户提供了 1 张参考图且明确要求生成视频，将 mode 设置为 'image2video'；"
                "如果用户提供了 2 张或多张参考图且明确要求生成视频，将 mode 设置为 'keyframes' 以制作过渡动画。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "视频生成的英文提示词，需要详细描述主体、动作、场景、镜头运动、光照、风格等",
                    },
                    "num_frames": {
                        "type": "integer",
                        "description": "视频总帧数，必须满足 8n+1（如 81 约3秒, 121 约5秒, 241 约10秒）",
                        "enum": [81, 121, 161, 241, 441],
                    },
                    "width": {
                        "type": "integer",
                        "description": "视频宽度",
                        "default": 1152,
                    },
                    "height": {
                        "type": "integer",
                        "description": "视频高度",
                        "default": 768,
                    },
                    "mode": {
                        "type": "string",
                        "description": "生成模式：text2video（纯文生视频）/ image2video（基于单张参考图动起来）/ keyframes（基于多张参考图做过渡动画）",
                        "enum": ["text2video", "image2video", "keyframes"],
                    },
                },
                "required": ["prompt"],
            },
        },
    },
]

# 系统提示词（引导模型行为）
SYSTEM_PROMPT = """你是 Agnes AI 助手，一个友好、专业的 AI 创作伙伴。

你的核心能力：
1. **日常对话**：可以和用户自由聊天，回答问题
2. **图片生成**：当用户想要生成图片时，使用 generate_image 工具
3. **视频生成**：当用户想要生成视频时，使用 generate_video 工具

重要规则：
# =====================================================
# 【第一层级：严格区分"讨论"与"执行"】
# =====================================================
- 用户上传图片或提供图片链接，**不代表**用户要生成图片！
- 以下情况**绝对不要**调用 generate_image 工具，只回复文字：
  - 用户上传图片并说"帮我描述这张图"、"这张图里有什么"、"帮我写个提示词"、"帮我分析一下"
  - 用户上传图片但没有明确要求生成/画/创建新图片
  - 用户只是分享图片、讨论图片内容、询问图片相关信息
- 只有当用户**明确**使用"生成"、"画"、"创建"、"做一张"、"修改"、"调整"、"改一改"、"换一种"等动作词时，才调用 generate_image 工具
- 如果不确定用户意图，**先确认**再行动，宁可多问一句也不要误触发生图

# =====================================================
# 【第二层级：会话连续性——同一会话内上下文自动继承】
# （这是核心改进：解决"继续修改时 AI 不知道该用图生图"的问题）
# =====================================================
- 【会话内历史图片识别】同一会话中，如果之前已经**成功生成过图片**，那么：
  - 最近一次成功生成的图片 = "当前讨论的图片"
  - 用户说"在这张图的基础上"、"继续修改"、"调整一下"、"改一改"、"换个风格"、
    "再做一张类似的"、"保持构图但改颜色" 等 → 明确意图是**基于最近的图片做图生图**
  - 此时必须调用 generate_image 工具，**mode=image2image**，参考图 = 最近生成的那张图片
  - 不要去做"图片理解/描述"，不要用纯文生图（text2image），不要"先看看图片再说"

- 【会话内历史视频识别】同一会话中，如果之前已经成功生成过视频，类似地，
  用户说"继续调整视频"、"基于刚才的视频再做一版" → generate_video，mode=image2video 或 keyframes

- 【什么情况下不用历史图片】
  - 用户明确说"不用刚才的图，重新画一张" → 用 text2image
  - 用户开启了全新的话题（例如上一条是生成海边风景，现在说"帮我写个会议纪要"）→ 不调用图片工具
  - 用户明确要求纯文字描述/分析 → 只回复文字

# =====================================================
# 【第三层级：工具调用通用规则】
# =====================================================
- 当用户要求生成图片或视频时，必须调用对应的工具，不要只是描述如何生成
- 生成提示词时，请将中文描述翻译为详细的英文提示词，以获得更好的生成效果
- 英文提示词应包含：主体、场景、风格、光照、构图、质量要求等细节
- 如果用户的描述不够具体，可以适当补充合理的细节
- 对于普通对话（不需要生成内容），直接回复即可，不要调用工具
- **引用已生成的图片**：如果对话中之前生成了图片，用户说"用这张图"、"用刚才的图"等，
  请将 mode 设置为对应的参考图模式（image2image / image2video），不要用纯文本模式
- **URL 链接处理**：用户可能提供图片 URL 链接作为参考图。如果用户明确要求基于该链接图片生成新图，
  将 mode 设为 image2image；如果只是讨论链接内容，不要调用工具
- 【严禁输出图片 URL】：不要在回复中输出任何图片 URL、Markdown 图片链接（如 ![xxx](url)）或图片地址。
  生成的图片会在前端自动展示，你只需回复文字内容即可
- 回复使用中文
"""


class ChatService:
    """
    聊天服务：封装 Agnes AI Chat API 调用 + 工具执行逻辑
    """

    def __init__(self):
        self.chat_url = f"{settings.agnes_api_base_url}/chat/completions"
        self.model = "agnes-2.0-flash"

    # =====================================================
    # 【会话标题总结】—— 根据对话内容自动生成有意义的标题
    # =====================================================
    async def summarize_session_title(self, messages) -> str:
        """
        根据对话内容，使用 AI 生成一个简洁、有意义的会话标题。

        Args:
            messages: 消息对象列表（ChatMessage ORM 对象）

        Returns:
            生成的标题字符串（不超过 30 字）
        """
        # 提取对话内容（只用前 5 条，控制上下文长度）
        chat_history = []
        for msg in messages[:5]:
            if msg.role in ("user", "assistant"):
                content = msg.content or ""
                if content.strip():
                    # 截断过长的单条消息
                    if len(content) > 500:
                        content = content[:500] + "..."
                    chat_history.append({
                        "role": msg.role,
                        "content": content,
                    })

        if not chat_history:
            return "新对话"

        # 构造总结标题的请求
        system_prompt = """你是一个对话总结助手。请根据提供的对话内容，生成一个简洁、有意义的中文标题。

要求：
1. 标题必须使用中文
2. 不超过 20 个字符
3. 准确概括对话的核心主题或用户意图
4. 不要加引号、冒号等前缀
5. 只输出标题本身，不要输出任何其他文字、解释或说明"""

        user_prompt = "请根据以下对话生成一个简洁的中文标题（不超过 20 字）：\n\n"
        for item in chat_history:
            role_label = "用户" if item["role"] == "user" else "助手"
            user_prompt += f"{role_label}: {item['content']}\n"
        user_prompt += "\n标题："

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.5,
            "max_tokens": 50,
        }

        try:
            result = await agnes_client._post(self.chat_url, body)
            choice = result.get("choices", [{}])[0]
            message = choice.get("message", {})
            title = message.get("content", "") or ""
            title = title.strip().strip('"').strip("'").strip("`")
            # 去除可能的前缀说明
            if "：" in title and len(title) > 40:
                title = title.split("：")[-1].strip()
            if ":" in title and len(title) > 40:
                title = title.split(":")[-1].strip()
            # 限制长度
            if len(title) > 30:
                title = title[:30]
            return title or "新对话"
        except Exception as e:
            logger.warning("[Chat] 总结标题失败: %s", e)
            # 降级：取第一条用户消息的前 30 字
            first_user = next((m for m in chat_history if m["role"] == "user"), None)
            if first_user and first_user.get("content"):
                return first_user["content"][:30]
            return "新对话"

    # =====================================================
    # 【流式聊天】—— SSE 逐 token 返回
    # =====================================================
    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        session_id: Optional[int] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式聊天接口，通过 SSE 逐块返回结果。

        SSE 事件格式：
        - {"type": "text", "content": "..."} — 文本增量
        - {"type": "tool_call", "tool": "generate_image", "args": {...}} — 工具调用开始
        - {"type": "tool_result", "tool": "generate_image", "result": {...}} — 工具执行结果
        - {"type": "done"} — 结束

        Args:
            messages: 对话历史 [{"role": "user/assistant/system", "content": "..."}]
            session_id: 会话 ID（用于关联生成任务）
            attachments: 可选的用户参考图列表（用于 System Prompt 上下文注入与工具执行）
        """
        # ── 根据附件和会话历史，动态追加 System Prompt 上下文 ──
        # 区分三种类型的附件，对 AI 说明其能力边界：
        #   - image (base64 / image_url): AI 可以"看图"，走多模态注入
        #   - video (video_url): AI 当前无法"看视频"，仅文字告知有视频链接
        #   - document (doc_url): AI 当前无法"读文档"，仅文字告知有文档链接
        # 【新增】：收集会话内历史生成的图片，以文字形式给 AI 一个强信号，
        #           让它知道"最近刚生成了哪些图片"，从而在用户说"继续修改"时
        #           正确判断意图为 image2image。
        attachment_note = ""

        # ── 【新增】从对话历史中提取最近生成的图片（给 AI 一个"上下文地图"） ──
        # 这一步是让 AI 在"本轮没有新上传图片"时仍知道"之前生成过图片"，
        # 从而避免把"继续修改"误判为纯文字或图片理解。
        history_images = self._collect_history_images(messages)
        history_videos = self._collect_history_media(messages, media_type="video")
        has_history_images = len(history_images) > 0
        has_history_videos = len(history_videos) > 0

        # 本轮是否有新图片/视频/文档附件
        has_new_image = False
        has_new_video = False
        has_new_doc = False
        image_count = 0
        video_count = 0
        doc_count = 0

        if attachments:
            image_atts = [a for a in attachments
                          if (a.get("base64_image") and a["base64_image"].startswith("data:image/"))
                          or a.get("image_url")]
            video_atts = [a for a in attachments if a.get("video_url")]
            doc_atts = [a for a in attachments if a.get("doc_url")]

            image_count = len(image_atts)
            video_count = len(video_atts)
            doc_count = len(doc_atts)
            has_new_image = image_count > 0
            has_new_video = video_count > 0
            has_new_doc = doc_count > 0

        note_segments = []

        # ── 历史生成的图片上下文信号（本轮无新图片，但历史有图片时最关键） ──
        if has_history_images and not has_new_image:
            note_segments.append(
                f"【会话历史上下文 · 图片】\n"
                f"- 本会话之前已经成功生成过 {len(history_images)} 张图片\n"
                f"- 最近一张生成的图片 = 用户当前在讨论/修改的默认参考图\n"
                f"- 用户说'在这张图的基础上'、'继续修改'、'调整一下'、'改一改'、'换个风格'等时：\n"
                f"  → 必须调用 generate_image，mode=image2image\n"
                f"  → 不要用纯文生图 text2image\n"
                f"  → 不要去做图片描述/理解\n"
                f"- 参考图不用你传 URL——后端会自动把最近一张历史图片作为 image2image 的参考图\n"
                f"- 如果用户明确说'忽略之前的图，重新画' → 用 text2image\n"
                f"- 【重要】不要回复任何图片 URL 给用户，图片会自动生成并在前端展示"
            )
        elif has_history_images and has_new_image:
            # 本轮有新图片 + 历史也有图片 → 让 AI 知道有两套参考图可用
            note_segments.append(
                f"【会话历史上下文 · 图片】\n"
                f"- 本轮用户上传了 {image_count} 张新图片（多模态方式注入，你可以看到）\n"
                f"- 历史上本会话还生成过 {len(history_images)} 张图片\n"
                f"- 用户说'基于本轮上传的图片' → 用本轮新图片做 image2image\n"
                f"- 用户说'基于之前生成的图片'或'继续修改' → 用历史最近图片做 image2image\n"
                f"- 【重要】不要回复任何图片 URL 给用户，图片会自动生成并在前端展示"
            )

        # 本轮图片上下文
        if has_new_image:
            image_atts_local = [a for a in attachments
                          if (a.get("base64_image") and a["base64_image"].startswith("data:image/"))
                          or a.get("image_url")]
            has_base64 = any(a.get("base64_image") and a["base64_image"].startswith("data:image/") for a in image_atts_local)
            has_url = any(a.get("image_url") for a in image_atts_local)
            if has_base64 and has_url:
                source_label = "上传+链接"
            elif has_url:
                source_label = "链接"
            else:
                source_label = "上传"
            note_segments.append(
                f"【参考图上下文】用户【本轮】提供了 {image_count} 张图片（{source_label}）。\n"
                f"重要提示：\n"
                f"- 提供图片 ≠ 用户要生成图片，请根据用户文字意图判断\n"
                f"- 只有用户明确说'生成'、'画'、'创建'、'修改'、'调整'时才调用 generate_image\n"
                f"- 如果用户只是描述/分析/讨论图片，直接文字回复，不要调用工具\n"
                f"- 如果用户要求基于此图生成新图，将 mode 设为 'image2image'\n"
                f"- 如果用户明确说'忽略这张图'或'只按文字生成'，则设 use_reference_image=false 或 mode='text2image'"
            )

        # 视频上下文（仅文字提示，AI 不能看视频）
        if has_new_video:
            note_segments.append(
                f"【参考视频上下文】用户【本轮】提供了 {video_count} 个视频链接。\n"
                f"重要提示：\n"
                f"- AI 当前无法观看视频内容，视频链接仅供你知道用户在谈论某个视频\n"
                f"- 不要假装描述视频内容，以用户的文字描述为准\n"
                f"- 如果用户要求基于视频风格生成新内容，使用用户文字描述来完成\n"
            )
        elif has_history_videos and not has_new_video:
            note_segments.append(
                f"【会话历史上下文 · 视频】\n"
                f"- 本会话之前生成过 {len(history_videos)} 个视频\n"
                f"- 用户说'基于刚才的视频继续调整'时，调用 generate_video，mode=image2video"
            )

        # 文档上下文（仅文字提示，AI 不能读文档）
        if has_new_doc:
            note_segments.append(
                f"【参考文档上下文】用户【本轮】提供了 {doc_count} 个文档链接。\n"
                f"重要提示：\n"
                f"- AI 当前无法读取文档（PDF / DOC / TXT 等）内容\n"
                f"- 不要假装描述文档内容，以用户的文字描述为准\n"
                f"- 如果用户讨论文档主题，按用户文字进行回复即可\n"
            )

        if note_segments:
            attachment_note = "\n\n" + "\n\n".join(note_segments)
        # 无附件且无历史图片：不注入额外提示

        system_prompt = SYSTEM_PROMPT + attachment_note
        request_messages = [{"role": "system", "content": system_prompt}] + messages

        # ── 将本轮新附件（上传图片 / 链接图片）以多模态格式注入最后一条用户消息 ──
        # 让 AI 模型真正"看到"本轮上传的图片内容，以生成准确的 image2image 提示词
        # 支持 base64 data URI 和 URL 链接两种格式
        # 【重要决策】历史图片不在这里注入多模态内容（否则 AI 会在回复中输出图片链接），
        # 而是改在 _execute_generate_image 工具执行阶段，自动从 messages 的 media_items
        # 中识别最近一张生成的图片作为 image2image 的参考图——这是"后台自动"处理的。
        # 本轮是否有新图片附件
        has_image_attachments = False
        image_parts = []  # 收集本轮新图片附件的多模态 image_url 部分

        if attachments:
            for att in attachments:
                if att.get("base64_image") and att["base64_image"].startswith("data:image/"):
                    image_parts.append({
                        "type": "image_url",
                        "image_url": {"url": att["base64_image"]}
                    })
                    has_image_attachments = True
                elif att.get("image_url"):
                    image_parts.append({
                        "type": "image_url",
                        "image_url": {"url": att["image_url"]}
                    })
                    has_image_attachments = True

        # 如果本轮有新图片附件，将这些图片以多模态内容形式注入到最后一条 user 消息
        # 如果本轮没有新图片附件但历史有图片 → 不在这里处理，改在 _execute_generate_image 中自动处理
        if has_image_attachments and image_parts:
            for i in range(len(request_messages) - 1, -1, -1):
                if request_messages[i]["role"] == "user":
                    original_content = request_messages[i]["content"]
                    multi_content = []
                    # 保留用户原始文本
                    if isinstance(original_content, str) and original_content.strip():
                        multi_content.append({"type": "text", "text": original_content})
                    elif isinstance(original_content, list):
                        for part in original_content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                multi_content.append(part)
                    # 注入本轮新上传/链接图片
                    multi_content.extend(image_parts)
                    if multi_content:
                        request_messages[i] = {
                            "role": "user",
                            "content": multi_content,
                        }
                    break

        body = {
            "model": self.model,
            "messages": request_messages,
            "tools": CHAT_TOOLS,
            "stream": True,
        }

        # 第一次调用：可能返回文本或 tool_calls
        full_content = ""
        tool_calls_list = []

        try:
            async for event in self._stream_chat_api(body):
                if event["type"] == "text":
                    full_content += event["content"]
                    yield json.dumps(event, ensure_ascii=False)
                elif event["type"] == "tool_calls":
                    tool_calls_list = event["calls"]
                    break
                elif event["type"] == "done":
                    async for fallback_event in self._fallback_history_image_edit_stream(
                        messages=messages,
                        session_id=session_id,
                        history_images=history_images,
                    ):
                        yield fallback_event
                    if self._should_fallback_to_history_image_edit(messages, history_images):
                        return
                    yield json.dumps({"type": "done"}, ensure_ascii=False)
                    return
                elif event["type"] == "error":
                    yield json.dumps(event, ensure_ascii=False)
                    yield json.dumps({"type": "done"}, ensure_ascii=False)
                    return
        except Exception as e:
            logger.error("[Chat] 流式调用失败: %s", e)
            yield json.dumps({"type": "error", "content": str(e)}, ensure_ascii=False)
            yield json.dumps({"type": "done"}, ensure_ascii=False)
            return

        # 如果有工具调用，执行工具并继续对话
        if tool_calls_list:
            # 通知前端工具调用开始
            for tc in tool_calls_list:
                yield json.dumps({
                    "type": "tool_call",
                    "tool": tc["function"]["name"],
                    "args": json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"],
                }, ensure_ascii=False)

            # ── 从对话历史中提取最近已完成的图片 URL ──
            # 当用户说"用刚才的图生成视频"时，AI 可能没有附件但需要引用历史图片
            # 这里自动从历史消息中找到最近的已完成图片，下载为 base64 后作为附件传入
            history_images = self._collect_history_images(messages)

            # 执行每个工具调用（传入 attachments 以支持 image2image / image2video / keyframes）
            tool_results = []
            for tc in tool_calls_list:
                func_name = tc["function"]["name"]
                func_args = tc["function"]["arguments"]
                if isinstance(func_args, str):
                    func_args = json.loads(func_args)

                # 合并附件：优先使用本轮用户上传的附件（只取图片类型，视频/文档不参与图生图），其次补充历史图片
                # 过滤：只有 base64_image 或 image_url 的附件才能作为生成工具的参考图
                raw_atts = list(attachments) if attachments else []
                effective_attachments = [
                    a for a in raw_atts
                    if (a.get("base64_image") and a["base64_image"].startswith("data:image/"))
                    or a.get("image_url")
                ]
                if not effective_attachments and raw_atts:
                    logger.info("[Chat] 本轮附件中过滤出 %d 张可用图片（总数 %d），其余为视频/文档链接，不参与图生图参考",
                                len(effective_attachments), len(raw_atts))
                if not effective_attachments and history_images:
                    # 本轮无新图片附件但会话历史中之前生成过图片 → 自动引用最近生成的图片做参考图
                    # 这是"继续修改"场景的核心逻辑：用户不说"上传图片"，但刚生成过图片
                    # 所以默认意图就是"基于刚刚生成的那张图继续改"
                    llm_mode = func_args.get("mode")
                    if func_name == "generate_video":
                        # 视频生成：如果 AI 没显式指定 text2video，自动引用历史图片
                        if llm_mode != "text2video":
                            effective_attachments = history_images[:2]
                            logger.info("[Chat] 自动引用历史图片作为视频生成参考图: %d 张", len(effective_attachments))
                    elif func_name == "generate_image":
                        # 图生图（核心修复！）：
                        # 不看 AI 写了什么 mode，只要它调用了 generate_image 且本轮没新附件
                        # 就自动用最近一张历史图片做 image2image
                        # 理由：用户在同一会话中先生成了图片，现在继续调用生成工具
                        #       其意图默认就是"继续修改那张图"
                        #       AI 可能写 text2image 是因为它没看到历史图片（历史图片不在对话文本中）
                        eff = history_images[-1:]  # 只取最近一张
                        if eff:
                            effective_attachments = eff
                            # 【关键】改写 func_args 的 mode 为 image2image
                            # 因为 AI 看不到历史图片，它写 text2image 是正常的
                            # 后端根据上下文连续性判断应做 image2image，所以强制纠正
                            original_mode = func_args.get("mode", "not_specified")
                            func_args["mode"] = "image2image"
                            func_args["use_reference_image"] = True
                            if original_mode != "image2image":
                                logger.info(
                                    "[Chat] 自动切换为图生图 image2image：AI 请求 mode=%s，"
                                    "但会话历史中最近生成过图片（共 %d 张历史图片），"
                                    "后端根据上下文自动纠正为 image2image 并引用最近一张历史图片",
                                    original_mode, len(history_images)
                                )
                            else:
                                logger.info("[Chat] 使用历史图片作为 image2image 参考图（AI 已正确指定）")

                # 处理历史图片附件：URL 类型直接使用，无需下载
                if effective_attachments:
                    for i, att in enumerate(effective_attachments):
                        if att.get("_is_url"):
                            url = att.get("base64_image", "")
                            # 直接使用 URL 作为 image_url，不再下载为 base64
                            effective_attachments[i] = {
                                "name": att["name"],
                                "base64_image": "",
                                "image_url": url,
                                "size": att["size"],
                                "mime_type": att["mime_type"],
                                "source": "url",
                            }
                    effective_attachments = [a for a in effective_attachments if a is not None]

                result = await self._execute_tool(func_name, func_args, session_id, attachments=effective_attachments if effective_attachments else None, messages=messages)
                tool_results.append({
                    "tool_call_id": tc.get("id", ""),
                    "role": "tool",
                    "name": func_name,
                    "content": json.dumps(result, ensure_ascii=False),
                })

                # 通知前端工具执行结果
                yield json.dumps({
                    "type": "tool_result",
                    "tool": func_name,
                    "result": result,
                }, ensure_ascii=False)

            # 将工具结果回传给模型，获取最终回复
            # 构建包含工具调用的消息历史
            assistant_msg = {
                "role": "assistant",
                "content": full_content or None,
                "tool_calls": tool_calls_list,
            }
            second_messages = request_messages + [assistant_msg] + tool_results

            second_body = {
                "model": self.model,
                "messages": second_messages,
                "stream": True,
            }

            try:
                async for event in self._stream_chat_api(second_body):
                    if event["type"] == "text":
                        yield json.dumps(event, ensure_ascii=False)
                    elif event["type"] == "done":
                        yield json.dumps({"type": "done"}, ensure_ascii=False)
                        return
                    elif event["type"] == "error":
                        yield json.dumps(event, ensure_ascii=False)
                        yield json.dumps({"type": "done"}, ensure_ascii=False)
                        return
            except Exception as e:
                logger.error("[Chat] 二次流式调用失败: %s", e)
                yield json.dumps({"type": "error", "content": str(e)}, ensure_ascii=False)

            yield json.dumps({"type": "done"}, ensure_ascii=False)

    # =====================================================
    # 【非流式聊天】—— 一次性返回完整结果
    # =====================================================
    async def chat(
        self,
        messages: List[Dict[str, str]],
        session_id: Optional[int] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        非流式聊天接口，返回完整结果。

        Returns:
            {
                "content": "AI 回复文本",
                "tool_calls": [...],  # 工具调用列表（如果有）
                "tool_results": [...],  # 工具执行结果（如果有）
            }
        """
        att_count = len(attachments) if attachments else 0
        attachment_note = ""
        if att_count == 1:
            attachment_note = (
                f"\n\n【参考图上下文】用户【本轮】上传了 1 张【新的】参考图片。\n"
                f"重要：请基于本轮参考图生成内容，不要复用历史提示词。\n"
                f"可用于 generate_image.mode='image2image' 或 generate_video.mode='image2video'。"
            )
        elif att_count >= 2:
            attachment_note = (
                f"\n\n【参考图上下文】用户【本轮】上传了 {att_count} 张【新的】参考图片。\n"
                f"重要：请基于本轮参考图生成内容，不要复用历史提示词。\n"
                f"可用于 generate_image.mode='image2image' 或 generate_video.mode='keyframes'。"
            )

        system_prompt = SYSTEM_PROMPT + attachment_note
        request_messages = [{"role": "system", "content": system_prompt}] + messages

        # 将当前附件以多模态格式注入最后一条用户消息（与流式方法一致）
        if attachments:
            for i in range(len(request_messages) - 1, -1, -1):
                if request_messages[i]["role"] == "user":
                    original_content = request_messages[i]["content"]
                    multi_content = []
                    if isinstance(original_content, str) and original_content.strip():
                        multi_content.append({"type": "text", "text": original_content})
                    elif isinstance(original_content, list):
                        for part in original_content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                multi_content.append(part)
                    for att in attachments:
                        if att.get("base64_image"):
                            multi_content.append({
                                "type": "image_url",
                                "image_url": {"url": att["base64_image"]}
                            })
                    if multi_content:
                        request_messages[i] = {
                            "role": "user",
                            "content": multi_content,
                        }
                    break

        body = {
            "model": self.model,
            "messages": request_messages,
            "tools": CHAT_TOOLS,
        }

        # 第一次调用
        result = await agnes_client._post(self.chat_url, body)

        choice = result.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "") or ""
        tool_calls = message.get("tool_calls", [])

        response = {
            "content": content,
            "tool_calls": [],
            "tool_results": [],
        }

        history_images = self._collect_history_images(messages)

        # 如果有工具调用
        if tool_calls:
            # 从对话历史中提取最近已完成的图片

            tool_results = []
            for tc in tool_calls:
                func_name = tc["function"]["name"]
                func_args = tc["function"]["arguments"]
                if isinstance(func_args, str):
                    func_args = json.loads(func_args)

                response["tool_calls"].append({
                    "name": func_name,
                    "args": func_args,
                })

                # 合并附件：优先使用本轮用户上传的附件，其次补充历史图片
                effective_attachments = list(attachments) if attachments else []
                if not effective_attachments and history_images:
                    llm_mode = func_args.get("mode")
                    if func_name == "generate_video":
                        if llm_mode != "text2video" or len(history_images) >= 2:
                            effective_attachments = history_images[:2]
                    elif func_name == "generate_image":
                        if llm_mode == "image2image":
                            effective_attachments = history_images[:1]

                # 将历史图片的 URL 下载为 base64
                if effective_attachments:
                    for i, att in enumerate(effective_attachments):
                        if att.get("_is_url"):
                            url = att.get("base64_image", "")
                            b64 = await self._download_image_as_base64(url)
                            if b64:
                                effective_attachments[i] = {
                                    "name": att["name"],
                                    "base64_image": b64,
                                    "size": att["size"],
                                    "mime_type": att["mime_type"],
                                }
                            else:
                                effective_attachments[i] = None
                    effective_attachments = [a for a in effective_attachments if a is not None and not a.get("_is_url")]

                # 执行工具
                result = await self._execute_tool(func_name, func_args, session_id, attachments=effective_attachments if effective_attachments else None, messages=messages)
                tool_results.append({
                    "tool_call_id": tc.get("id", ""),
                    "role": "tool",
                    "name": func_name,
                    "content": json.dumps(result, ensure_ascii=False),
                })
                response["tool_results"].append({
                    "name": func_name,
                    "result": result,
                })

            # 二次调用获取最终回复
            assistant_msg = {
                "role": "assistant",
                "content": content or None,
                "tool_calls": tool_calls,
            }
            second_messages = request_messages + [assistant_msg] + tool_results

            second_body = {
                "model": self.model,
                "messages": second_messages,
            }

            second_result = await agnes_client._post(self.chat_url, second_body)
            second_choice = second_result.get("choices", [{}])[0]
            second_message = second_choice.get("message", {})
            response["content"] = second_message.get("content", "") or ""
        elif self._should_fallback_to_history_image_edit(messages, history_images):
            func_args = self._build_history_image_edit_args(messages)
            result = await self._execute_generate_image(
                func_args,
                session_id=session_id,
                attachments=[history_images[-1]],
                messages=messages,
            )
            response["content"] = "好的，我会基于刚才生成的图片继续修改。"
            response["tool_calls"].append({
                "name": "generate_image",
                "args": func_args,
                "fallback": "history_image_edit",
            })
            response["tool_results"].append({
                "name": "generate_image",
                "result": result,
            })

        return response

    # =====================================================
    # 【流式 API 调用封装】—— 解析 SSE 事件
    # =====================================================
    async def _stream_chat_api(self, body: Dict[str, Any]) -> AsyncGenerator[Dict, None]:
        """
        调用 Agnes AI Chat API（流式），解析 SSE 事件并 yield 结构化结果。
        """
        headers = {
            "Authorization": f"Bearer {settings.agnes_api_key}",
            "Content-Type": "application/json",
        }

        tool_calls_accum = {}  # 累积 tool_calls（SSE 分块发送）
        current_text = ""

        try:
            async with agnes_client.client.stream(
                "POST",
                self.chat_url,
                json=body,
                headers=headers,
                timeout=httpx.Timeout(120.0, connect=30.0),
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    yield {"type": "error", "content": f"API 错误 (HTTP {response.status_code}): {error_text.decode()[:200]}"}
                    return

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue

                    data_str = line[6:]  # 去掉 "data: " 前缀
                    if data_str == "[DONE]":
                        # 流结束，检查是否有未完成的 tool_calls
                        if tool_calls_accum:
                            yield {
                                "type": "tool_calls",
                                "calls": list(tool_calls_accum.values()),
                            }
                        elif current_text:
                            yield {"type": "done"}
                        else:
                            yield {"type": "done"}
                        return

                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})
                    finish_reason = choices[0].get("finish_reason")

                    # 处理文本内容
                    content = delta.get("content")
                    if content:
                        current_text += content
                        yield {"type": "text", "content": content}

                    # 处理工具调用（SSE 分块发送，需要累积）
                    tc_deltas = delta.get("tool_calls")
                    if tc_deltas:
                        for tc_delta in tc_deltas:
                            idx = tc_delta.get("index", 0)
                            if idx not in tool_calls_accum:
                                tool_calls_accum[idx] = {
                                    "id": tc_delta.get("id", ""),
                                    "type": "function",
                                    "function": {
                                        "name": "",
                                        "arguments": "",
                                    },
                                }
                            if tc_delta.get("id"):
                                tool_calls_accum[idx]["id"] = tc_delta["id"]
                            fn = tc_delta.get("function", {})
                            if fn.get("name"):
                                tool_calls_accum[idx]["function"]["name"] += fn["name"]
                            if fn.get("arguments"):
                                tool_calls_accum[idx]["function"]["arguments"] += fn["arguments"]

                    # 流结束信号
                    if finish_reason == "tool_calls":
                        yield {
                            "type": "tool_calls",
                            "calls": list(tool_calls_accum.values()),
                        }
                        return
                    elif finish_reason == "stop":
                        yield {"type": "done"}
                        return

        except Exception as e:
            logger.error("[Chat] 流式 API 调用异常: %s", e)
            yield {"type": "error", "content": f"聊天服务异常: {str(e)}"}

    # =====================================================
    # 【历史图片收集】—— 从对话历史中提取最近生成的图片
    # =====================================================
    def _collect_history_images(self, messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """
        从对话历史中提取最近已完成的图片 URL，返回附件格式列表。

        用于当用户说"用刚才的图生成视频"或"继续修改图片"时，
        自动将历史图片作为参考图传入工具。
        按时间倒序遍历，优先取最近生成的图片。

        Returns:
            附件列表 [{"name": ..., "base64_image": ..., "size": 0, "mime_type": "image/png"}, ...]
        """
        return self._collect_history_media(messages, media_type="image")

    # =====================================================
    # 【历史图片编辑兜底】—— 模型未调用工具时由后端补救
    # =====================================================
    def _latest_user_text(self, messages: List[Dict[str, Any]]) -> str:
        """取最近一条用户文本，兼容纯文本与多模态 content。"""
        for msg in reversed(messages):
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts = [
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                return "\n".join(parts).strip()
        return ""

    def _should_fallback_to_history_image_edit(
        self,
        messages: List[Dict[str, Any]],
        history_images: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """
        判断是否应当把"继续修改刚才那张图"兜底为图生图。

        这个判断只在模型没有返回 tool_calls 时使用，避免模型把明确的编辑意图
        当成图片理解或纯文生图。显式要求重画/不用上一张图/只分析图片时不触发。
        """
        if not history_images:
            return False

        text = self._latest_user_text(messages)
        if not text:
            return False

        negative_pattern = (
            r"(不用|不要|忽略|别用).{0,8}(刚才|上一张|这张|原图|参考图|之前)|"
            r"(重新|从头|另起).{0,8}(画|生成|做|创建)|"
            r"(描述|分析|看一下|识别|理解|有什么|提示词|prompt)"
        )
        if re.search(negative_pattern, text, flags=re.IGNORECASE):
            return False

        reference_pattern = r"(这张图|这张|刚才|上一张|原图|参考图|它|当前图|图片)"
        edit_pattern = (
            r"(基础上|基于|继续|修改|调整|改|改成|改为|换成|换个|添加|加上|增加|"
            r"去掉|移除|删除|保留|保持|变成|做一版|再来一张|类似|让|戴|穿|拿|牵|拖|"
            r"站|坐|走|跑|看着|面向|背对|风格|背景|颜色|人物|情侣|帽子|衣服|猫|狗|元素|细节)"
        )
        explicit_reference_edit = re.search(reference_pattern, text) and re.search(edit_pattern, text)
        short_followup_edit = len(text) <= 80 and re.search(edit_pattern, text)
        return bool(explicit_reference_edit or short_followup_edit)

    def _build_history_image_edit_args(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """构造兜底图生图参数，保留用户原话作为编辑指令。"""
        instruction = self._latest_user_text(messages)
        prompt = (
            "Edit the provided reference image according to this instruction: "
            f"{instruction}. Preserve the original composition, main subjects, perspective, "
            "lighting consistency, and overall visual quality unless the instruction says otherwise."
        )
        return {
            "prompt": prompt,
            "size": "1024x1024",
            "mode": "image2image",
            "use_reference_image": True,
        }

    async def _fallback_history_image_edit_stream(
        self,
        messages: List[Dict[str, Any]],
        session_id: Optional[int],
        history_images: List[Dict[str, Any]],
    ) -> AsyncGenerator[str, None]:
        """流式接口中模型未调用工具时，补发一次基于历史图的 image2image。"""
        if not self._should_fallback_to_history_image_edit(messages, history_images):
            return

        func_args = self._build_history_image_edit_args(messages)
        logger.info("[Chat] 模型未触发工具，后端根据历史图片编辑意图兜底调用 image2image")
        yield json.dumps({
            "type": "tool_call",
            "tool": "generate_image",
            "args": func_args,
            "fallback": "history_image_edit",
        }, ensure_ascii=False)

        result = await self._execute_generate_image(
            func_args,
            session_id=session_id,
            attachments=[history_images[-1]],
            messages=messages,
        )
        yield json.dumps({
            "type": "tool_result",
            "tool": "generate_image",
            "result": result,
            "fallback": "history_image_edit",
        }, ensure_ascii=False)
        yield json.dumps({
            "type": "text",
            "content": "好的，我会基于刚才生成的图片继续修改。",
        }, ensure_ascii=False)
        yield json.dumps({"type": "done"}, ensure_ascii=False)

    # =====================================================
    # 【通用历史媒体收集】—— 从对话历史中提取 image / video URL
    # =====================================================
    def _collect_history_media(self, messages: List[Dict[str, str]], media_type: str = "image") -> List[Dict[str, Any]]:
        """
        通用的历史媒体收集函数。从 assistant 消息的媒体上下文中提取已完成的图片/视频 URL。

        提取策略：
        1) 从 routes/chat.py 注入的格式 "类型: image, 状态: 已完成, URL: https://..." 中提取
        2) 从 messages 的 media_items 结构化数据（若存在）中提取
        3) 最多取最近 2 个，避免上下文过载

        Args:
            messages: 对话历史
            media_type: "image" / "video"

        Returns:
            附件列表 [{"name": ..., "base64_image": URL, "size": 0, "mime_type": ..., "_is_url": True}, ...]
        """
        import re
        results = []

        # 倒序遍历消息，找到最近的已完成媒体
        for msg in reversed(messages):
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            found_in_this_msg = []

            # 策略 1：文本上下文格式
            pattern = rf"类型: {media_type}, 状态: 已完成, URL: (https?://\S+)"
            for url in re.findall(pattern, content):
                url = url.rstrip("]").rstrip(",")
                found_in_this_msg.append(url)

            # 策略 2：结构化 media_items（更可靠）
            media_items = msg.get("media_items")
            if media_items and isinstance(media_items, list):
                for item in media_items:
                    if (item.get("type") == media_type
                            and item.get("status") in ("success", "completed", "done")
                            and item.get("url")):
                        found_in_this_msg.append(item["url"])

            # 去重后加入结果
            seen = set()
            for url in found_in_this_msg:
                if url not in seen:
                    seen.add(url)
                    if media_type == "image":
                        results.append({
                            "name": f"history_{media_type}.png",
                            "base64_image": url,  # 存 URL，下游统一处理
                            "image_url": url,      # 同时存 image_url 以便直接使用
                            "size": 0,
                            "mime_type": "image/png",
                            "_is_url": True,
                        })
                    else:
                        results.append({
                            "name": f"history_{media_type}.mp4",
                            "base64_image": url,
                            "image_url": url,
                            "size": 0,
                            "mime_type": "video/mp4",
                            "_is_url": True,
                        })

            if len(results) >= 2:
                break

        results.reverse()
        return results

    async def _download_image_as_base64(self, url: str) -> Optional[str]:
        """
        下载远程图片并转为 base64 data URI 格式。
        如果 URL 已经是 base64 格式则直接返回。
        """
        if url.startswith("data:"):
            return url
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    import base64
                    content_type = resp.headers.get("content-type", "image/png")
                    b64 = base64.b64encode(resp.content).decode("utf-8")
                    return f"data:{content_type};base64,{b64}"
        except Exception as e:
            logger.warning("[Chat] 下载历史图片失败: %s, url=%s", e, url[:100])
        return None

    # =====================================================
    # 【工具执行】—— 根据工具名调用对应的生成服务
    # =====================================================
    async def _execute_tool(
        self,
        func_name: str,
        func_args: Dict,
        session_id: Optional[int] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        执行工具调用（generate_image / generate_video）。
        返回工具执行结果（包含任务 ID、状态等）。

        【新增】messages 参数用于在"继续修改"场景下，
        从会话历史中找到最近生成的图片，作为 image2image 参考图。
        """
        if func_name == "generate_image":
            return await self._execute_generate_image(func_args, session_id, attachments, messages=messages)
        elif func_name == "generate_video":
            return await self._execute_generate_video(func_args, session_id, attachments)
        else:
            return {"status": "error", "message": f"未知工具: {func_name}"}

    async def _execute_generate_image(
        self,
        args: Dict,
        session_id: Optional[int] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        执行图片生成工具（支持 text2image 与 image2image 两种模式）。

        策略（改进版）：
        - 显式 use_reference_image=False 或 mode=text2image → 文生图
        - 显式 use_reference_image=True 或 mode=image2image + 有参考图 → 图生图
        - 模型未指定 mode + 本轮有参考图 → 自动走 image2image
        - 【新增】模型未指定 mode + 本轮无参考图 + 会话历史最近生成过图片
          → 自动走 image2image，以历史最近一张图片为参考图（"继续修改"场景）
        - 其他情况 → 文生图

        参考图支持两种来源：
        - base64_image：用户上传的图片（data URI 格式）
        - image_url：用户提供的公网图片链接
        - 【新增】会话历史中最近生成的图片 URL
        """
        from app.services.image_poller import image_poller_manager

        prompt = args.get("prompt", "")
        size = args.get("size", "1024x1024")

        if not prompt:
            return {"status": "error", "message": "提示词不能为空"}

        # ── 解析 LLM 指定的模式参数
        llm_mode = args.get("mode")
        use_ref = args.get("use_reference_image")
        att_count = len(attachments) if attachments else 0

        # ── 【新增】从会话历史中查最近生成的图片（当本轮没有附件时作为备选参考图）
        history_images = []
        effective_attachments = attachments if att_count > 0 else None
        if att_count == 0 and messages:
            history_images = self._collect_history_images(messages)
            if history_images:
                # 【改造点】之前只取一张，现在取全部历史图片（最新 8 张）作为参考图
                effective_attachments = history_images[-8:]
                logger.info(
                    "[Chat] generate_image: 本轮无附件，使用会话历史 %d 张图片作为参考图（最多保留 8 张）",
                    len(effective_attachments),
                )

        # ── 决策最终模式（基于 effective_attachments 而不是原始 attachments）
        eff_count = len(effective_attachments) if effective_attachments else 0

        # 【核心修复】本轮没有新附件但有历史图片 → 强制用 image2image
        # 理由：AI 看不到历史图片（我们不把它注入对话文本，避免输出链接），
        #       所以 AI 写 mode=text2image 是正常的盲操作。但根据上下文连续性，
        #       用户在"先生成图 → 再说改一下"的场景下，意图显然是图生图。
        # 只有当 AI 显式写了 use_reference_image=False（说"不用刚才的图"）时才尊重它的选择
        if att_count == 0 and history_images and use_ref is not False:
            final_mode = "image2image"
            use_image = True
            # 确保 effective_attachments 已在上面的逻辑中设置（应该已设置为 history_images[-1:]）
            logger.info(
                "[Chat] generate_image: 本轮无新附件 + 有 %d 张历史生成图片 + AI 未明确禁止参考图 "
                "→ 强制模式 image2image（忽略 AI 请求的 mode=%s，因为 AI 看不到历史图片）",
                len(history_images), llm_mode
            )
        # AI 显式说"不用刚才的图，重新画" → 尊重用户意图
        elif use_ref is False:
            final_mode = "text2image"
            use_image = False
            effective_attachments = None
            logger.info("[Chat] generate_image: AI 明确禁用参考图，使用纯文生图 text2image")
        elif llm_mode == "image2image" or use_ref is True:
            final_mode = "image2image"
            use_image = True if eff_count > 0 else False
            if not use_image:
                logger.info("[Chat] generate_image: AI 请求 image2image 但没有可用参考图，降级为 text2image")
                final_mode = "text2image"
            else:
                logger.info("[Chat] generate_image: AI 请求 image2image，使用参考图（本轮上传或历史生成）")
        else:
            # LLM 未指定 mode（或指定了 text2image 但不影响上面的逻辑）
            if eff_count > 0:
                final_mode = "image2image"
                use_image = True
                logger.info("[Chat] generate_image: 存在有效参考图，自动切换为 image2image 模式")
            else:
                final_mode = "text2image"
                use_image = False
                logger.info("[Chat] generate_image: 无参考图，使用纯文生图 text2image")

        try:
            params = {
                "model": "agnes-image-2.1-flash",
                "size": size,
                "response_format": "url",
                "mode": final_mode,
            }

            if use_image and effective_attachments and len(effective_attachments) > 0:
                # ── 【改造点】之前只取第一张，现在遍历全部附件收集为多图数组
                b64_list: List[str] = []
                url_list: List[str] = []

                for ref in effective_attachments:
                    img_url = ref.get("image_url")
                    b64_img = ref.get("base64_image")

                    # 优先使用 image_url（公网 URL 体积小、稳定）
                    if img_url and isinstance(img_url, str) and img_url.strip():
                        url_list.append(img_url)
                        continue

                    # base64_image 字段里如果已经是 URL（历史图片兼容写法）
                    if b64_img and isinstance(b64_img, str) and b64_img.strip():
                        if b64_img.startswith("http") or b64_img.startswith("data:image/"):
                            b64_list.append(b64_img)
                            continue
                        # 兜底：纯 base64 字符串（没有前缀）
                        b64_list.append(b64_img)

                # 注入到 params（给 image_poller → agnes_client.create_image 使用）
                if b64_list:
                    params["base64_images"] = b64_list
                if url_list:
                    params["image_urls"] = url_list

                logger.info(
                    "[Chat] 图生图参考图汇总: base64=%d 张, url=%d 张, 总计=%d 张",
                    len(b64_list), len(url_list), len(b64_list) + len(url_list),
                )

            task = await image_poller_manager.create_task(
                prompt=prompt,
                params=params,
            )
            logger.info("[Chat] 图片生成任务已创建: task_id=%s, mode=%s, prompt=%s",
                        task.task_id, final_mode, prompt[:50])

            return {
                "status": "pending",
                "task_id": task.task_id,
                "media_type": "image",
                "prompt": prompt,
                "size": size,
                "mode": final_mode,
                "message": "图片生成任务已提交，请稍候...",
            }
        except Exception as e:
            logger.error("[Chat] 图片生成失败: %s", e)
            return {"status": "error", "message": f"图片生成失败: {str(e)}"}

    async def _execute_generate_video(
        self,
        args: Dict,
        session_id: Optional[int] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        执行视频生成工具（支持 text2video / image2video / keyframes 三种模式）。

        策略（Task 6 / FR-6 / FR-7）：
        - LLM 显式 mode=keyframes 且附件≥2 → keyframes
        - LLM 显式 mode=image2video 且附件≥1 → image2video
        - LLM 显式 mode=text2video 或未指定+无附件 → text2video
        - LLM 显式 text2video 但有 1 张参考图 → 自动纠正为 image2video 并记日志
        - LLM 显式 text2video 但有 ≥2 张参考图 → 自动纠正为 keyframes 并记日志
        """
        prompt = args.get("prompt", "")
        num_frames = args.get("num_frames", 121)
        width = args.get("width", 1152)
        height = args.get("height", 768)

        if not prompt:
            return {"status": "error", "message": "提示词不能为空"}

        # 校验帧数
        valid_frames = [81, 121, 161, 241, 441]
        if num_frames not in valid_frames:
            num_frames = min(valid_frames, key=lambda x: abs(x - num_frames))

        llm_mode = args.get("mode")
        att_count = len(attachments) if attachments else 0

        # ── 模式决策
        if llm_mode == "keyframes":
            final_mode = "keyframes" if att_count >= 2 else ("image2video" if att_count == 1 else "text2video")
        elif llm_mode == "image2video":
            final_mode = "image2video" if att_count >= 1 else "text2video"
        elif llm_mode == "text2video":
            # LLM 明确选择纯文本，但后端根据参考图纠正（FR-7）
            if att_count >= 2:
                final_mode = "keyframes"
                logger.info("[Chat] generate_video: LLM 选择 text2video，但存在 %d 张参考图，自动纠正为 keyframes", att_count)
            elif att_count == 1:
                final_mode = "image2video"
                logger.info("[Chat] generate_video: LLM 选择 text2video，但存在 1 张参考图，自动纠正为 image2video")
            else:
                final_mode = "text2video"
        else:
            # LLM 未指定 mode：根据附件数推断
            if att_count >= 2:
                final_mode = "keyframes"
                logger.info("[Chat] generate_video: 存在 %d 张参考图，自动选择 keyframes 模式", att_count)
            elif att_count == 1:
                final_mode = "image2video"
                logger.info("[Chat] generate_video: 存在 1 张参考图，自动选择 image2video 模式")
            else:
                final_mode = "text2video"

        # ── 根据 final_mode 准备调用参数
        image_param = None
        images_param = None
        if final_mode == "image2video":
            ref = attachments[0]
            # 优先使用 base64，其次使用 URL
            image_param = ref.get("base64_image") or ref.get("image_url")
        elif final_mode == "keyframes":
            images_param = [a.get("base64_image") or a.get("image_url") for a in attachments if a.get("base64_image") or a.get("image_url")]

        try:
            result = await agnes_client.create_video_task(
                prompt=prompt,
                model="agnes-video-v2.0",
                num_frames=num_frames,
                frame_rate=24,
                width=width,
                height=height,
                mode=final_mode,
                image=image_param,
                images=images_param,
            )

            video_id = result.get("video_id") or (
                result.get("data", {}).get("video_id") if isinstance(result.get("data"), dict) else None
            )
            task_id = (
                result.get("task_id")
                or result.get("id")
                or (result.get("data", {}).get("task_id") if isinstance(result.get("data"), dict) else None)
            )

            # 启动后台轮询
            from app.services.video_poller import poller_manager
            params = {
                "model": "agnes-video-v2.0",
                "num_frames": num_frames,
                "frame_rate": 24,
                "width": width,
                "height": height,
                "mode": final_mode,
            }
            await poller_manager.start_polling(
                task_id=task_id,
                video_id=video_id,
                prompt=prompt,
                params=params,
            )

            logger.info("[Chat] 视频生成任务已创建: task_id=%s, video_id=%s, mode=%s", task_id, video_id, final_mode)

            return {
                "status": "pending",
                "task_id": task_id,
                "video_id": video_id,
                "media_type": "video",
                "prompt": prompt,
                "num_frames": num_frames,
                "mode": final_mode,
                "message": "视频生成任务已提交，通常需要 1-3 分钟...",
            }
        except Exception as e:
            logger.error("[Chat] 视频生成失败: %s", e)
            return {"status": "error", "message": f"视频生成失败: {str(e)}"}


# 全局单例
chat_service = ChatService()
