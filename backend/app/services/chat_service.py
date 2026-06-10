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
                "当用户想要生成、创建、绘制图片时调用此工具。"
                "用户可能说'帮我画一张图'、'生成一张风景图'、'画一个猫咪'等。"
                "请将用户的描述转化为详细的英文图片提示词。"
                "重要：如果用户提供了 1 张或多张参考图片（对话上下文中有 attachments），"
                "请考虑将 mode 设置为 'image2image' 以进行风格迁移或基于参考图的创作。"
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
                "当用户想要生成、创建视频时调用此工具。"
                "用户可能说'帮我生成一段视频'、'创建一个短视频'、'做个视频'等。"
                "请将用户的描述转化为详细的英文视频提示词。"
                "重要：如果用户提供了 1 张参考图，请考虑将 mode 设置为 'image2video'；"
                "如果用户提供了 2 张或多张参考图，请将 mode 设置为 'keyframes' 以制作过渡动画。"
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
- **区分"讨论"与"执行"**：
  - 如果用户只是在讨论、设计、优化提示词（如"帮我写个提示词"、"这个描述怎么样"），直接用文字回复，**不要**调用任何工具
  - 只有当用户明确要求"生成"、"画"、"创建"图片或视频时，才调用对应的工具
  - 如果不确定用户意图，先确认再行动
- 当用户要求生成图片或视频时，必须调用对应的工具，不要只是描述如何生成
- 生成提示词时，请将中文描述翻译为详细的英文提示词，以获得更好的生成效果
- 英文提示词应包含：主体、场景、风格、光照、构图、质量要求等细节
- 如果用户的描述不够具体，可以适当补充合理的细节
- 对于普通对话（不需要生成内容），直接回复即可，不要调用工具
- **引用已生成的图片**：如果对话中之前生成了图片，用户说"用这张图"、"用刚才的图"等，请将 mode 设置为对应的参考图模式（image2image / image2video），不要用纯文本模式
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
        # ── 根据附件数量动态追加 System Prompt 上下文 ──
        # 告知模型当前存在参考图，引导其合理选择 mode / keyframes 等工具参数
        # 关键改进：明确区分"本轮附件"与"历史附件"，防止 AI 复用旧提示词
        attachment_note = ""
        att_count = len(attachments) if attachments else 0
        if att_count == 1:
            attachment_note = (
                f"\n\n【参考图上下文】用户【本轮】上传了 1 张【新的】参考图片（附件）。\n"
                f"重要提示：\n"
                f"- 请基于【本轮】上传的参考图生成内容，不要复用之前对话中的旧提示词\n"
                f"- 如果之前的对话中也有参考图，本轮的参考图是【全新的、不同的】图片\n"
                f"- 生成提示词时，请根据本轮参考图的视觉内容重新描述\n"
                f"可用模式：\n"
                f"- 图片生成：将 generate_image.mode 设置为 'image2image' 以基于参考图创作（风格迁移、参考构图等）\n"
                f"- 视频生成：将 generate_video.mode 设置为 'image2video' 以让这张图动起来\n"
                f"如果用户明确说'忽略这张图'或'只按文字生成'，则设 use_reference_image=false 或 mode='text2image'。"
            )
        elif att_count >= 2:
            attachment_note = (
                f"\n\n【参考图上下文】用户【本轮】上传了 {att_count} 张【新的】参考图片（附件）。\n"
                f"重要提示：\n"
                f"- 请基于【本轮】上传的参考图生成内容，不要复用之前对话中的旧提示词\n"
                f"- 如果之前的对话中也有参考图，本轮的参考图是【全新的、不同的】图片\n"
                f"- 生成提示词时，请根据本轮参考图的视觉内容重新描述\n"
                f"可用模式：\n"
                f"- 图片生成：将 generate_image.mode 设置为 'image2image'（默认取第 1 张作为参考）\n"
                f"- 视频生成：将 generate_video.mode 设置为 'keyframes'，以把多张参考图作为关键帧制作过渡动画"
            )
        # att_count == 0: 不注入

        system_prompt = SYSTEM_PROMPT + attachment_note
        request_messages = [{"role": "system", "content": system_prompt}] + messages

        # ── 将当前附件以多模态格式注入最后一条用户消息 ──
        # 让 AI 模型真正"看到"图片内容，而不是仅靠 system prompt 文字描述猜测
        # 这样 AI 能根据图片实际内容生成准确的提示词，避免复用历史提示词
        if attachments:
            for i in range(len(request_messages) - 1, -1, -1):
                if request_messages[i]["role"] == "user":
                    original_content = request_messages[i]["content"]
                    # 构建多模态消息内容（文本 + 图片）
                    multi_content = []
                    if isinstance(original_content, str) and original_content.strip():
                        multi_content.append({"type": "text", "text": original_content})
                    elif isinstance(original_content, list):
                        # 已经是多模态格式，保留原有文本部分
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

                # 合并附件：优先使用本轮用户上传的附件，其次补充历史图片
                effective_attachments = list(attachments) if attachments else []
                if not effective_attachments and history_images:
                    # 本轮无附件但有历史图片：根据工具类型和 mode 参数决定是否自动引用
                    llm_mode = func_args.get("mode")
                    if func_name == "generate_video":
                        # 视频生成：如果 AI 没指定 text2video，且有历史图片，自动引用最近的图片
                        if llm_mode != "text2video" or len(history_images) >= 2:
                            effective_attachments = history_images[:2]  # 最多取 2 张
                            if llm_mode != "text2video":
                                logger.info("[Chat] 自动引用历史图片作为视频生成参考图: %d 张", len(effective_attachments))
                    elif func_name == "generate_image":
                        # 图片生成：如果 AI 指定了 image2image，自动引用最近的图片
                        if llm_mode == "image2image":
                            effective_attachments = history_images[:1]
                            logger.info("[Chat] 自动引用历史图片作为图生图参考图")

                # 将历史图片的 URL 下载为 base64（工具执行需要 base64 格式）
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
                                # 下载失败，移除此附件
                                effective_attachments[i] = None
                    effective_attachments = [a for a in effective_attachments if a is not None and not a.get("_is_url")]

                result = await self._execute_tool(func_name, func_args, session_id, attachments=effective_attachments if effective_attachments else None)
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

        # 如果有工具调用
        if tool_calls:
            # 从对话历史中提取最近已完成的图片
            history_images = self._collect_history_images(messages)

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
                result = await self._execute_tool(func_name, func_args, session_id, attachments=effective_attachments if effective_attachments else None)
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

        用于当用户说"用刚才的图生成视频"时，自动将历史图片作为参考图传入工具。
        按时间倒序遍历，优先取最近生成的图片。

        Returns:
            附件列表 [{"name": ..., "base64_image": ..., "size": 0, "mime_type": "image/png"}, ...]
        """
        import re
        history_images = []

        # 倒序遍历消息，找到最近的已完成图片
        for msg in reversed(messages):
            content = msg.get("content", "")
            if msg.get("role") != "assistant":
                continue

            # 从注入的媒体上下文中提取图片 URL
            # 格式: [本轮生成的媒体内容]\n  [1] 类型: image, 状态: 已完成, URL: https://...
            pattern = r"类型: image, 状态: 已完成, URL: (https?://\S+)"
            matches = re.findall(pattern, content)

            for url in matches:
                url = url.rstrip("]")  # 清理可能残留的括号
                history_images.append({
                    "name": "history_image.png",
                    "base64_image": url,  # 先存 URL，后续在 _download_image_as_base64 中处理
                    "size": 0,
                    "mime_type": "image/png",
                    "_is_url": True,  # 标记这是 URL 而非 base64
                })

            if len(history_images) >= 2:
                break  # 最多取 2 张

        # 反转回正序（最近的在最后）
        history_images.reverse()
        return history_images

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
    ) -> Dict[str, Any]:
        """
        执行工具调用（generate_image / generate_video）。
        返回工具执行结果（包含任务 ID、状态等）。
        """
        if func_name == "generate_image":
            return await self._execute_generate_image(func_args, session_id, attachments)
        elif func_name == "generate_video":
            return await self._execute_generate_video(func_args, session_id, attachments)
        else:
            return {"status": "error", "message": f"未知工具: {func_name}"}

    async def _execute_generate_image(
        self,
        args: Dict,
        session_id: Optional[int] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        执行图片生成工具（支持 text2image 与 image2image 两种模式。

        策略（Task 5 / FR-5）
        - 显式 use_reference_image=False 或 mode=text2image → 文生图
        - 显式 use_reference_image=True 或 mode=image2image + 有参考图 → 图生图
        - 模型未指定 mode 但存在参考图 → 自动走 image2image 并打日志
        - 模型未指定 mode 且无参考图 → 文生图
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

        # ── 决策最终模式
        # 1) 显式拒绝使用参考图
        if use_ref is False or llm_mode == "text2image":
            final_mode = "text2image"
            use_image = False
        elif use_ref is True or llm_mode == "image2image":
            final_mode = "image2image"
            use_image = True if att_count > 0 else False
            if not use_image:
                logger.info("[Chat] generate_image: 模型要求 image2image，但用户未上传参考图，降级为 text2image")
                final_mode = "text2image"
        else:
            # LLM 未指定：根据是否存在参考图自动纠正模式
            if att_count > 0:
                final_mode = "image2image"
                use_image = True
                logger.info("[Chat] generate_image: 存在参考图，自动切换为 image2image 模式")
            else:
                final_mode = "text2image"
                use_image = False

        try:
            params = {
                "model": "agnes-image-2.1-flash",
                "size": size,
                "response_format": "url",
                "mode": final_mode,
            }

            if use_image and attachments and len(attachments) > 0:
                # image_poller._gen_loop 会从 params.base64_image 取值
                ref_b64 = attachments[0].get("base64_image")
                params["base64_image"] = ref_b64

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
            image_param = attachments[0].get("base64_image")
        elif final_mode == "keyframes":
            images_param = [a.get("base64_image") for a in attachments if a.get("base64_image")]

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
