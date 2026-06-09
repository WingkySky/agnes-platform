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
- 当用户要求生成图片或视频时，必须调用对应的工具，不要只是描述如何生成
- 生成提示词时，请将中文描述翻译为详细的英文提示词，以获得更好的生成效果
- 英文提示词应包含：主体、场景、风格、光照、构图、质量要求等细节
- 如果用户的描述不够具体，可以适当补充合理的细节
- 对于普通对话（不需要生成内容），直接回复即可，不要调用工具
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
        """
        # 构建请求体（带工具定义）
        request_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

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

            # 执行每个工具调用
            tool_results = []
            for tc in tool_calls_list:
                func_name = tc["function"]["name"]
                func_args = tc["function"]["arguments"]
                if isinstance(func_args, str):
                    func_args = json.loads(func_args)

                result = await self._execute_tool(func_name, func_args, session_id)
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
        request_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

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

                # 执行工具
                result = await self._execute_tool(func_name, func_args, session_id)
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
    # 【工具执行】—— 根据工具名调用对应的生成服务
    # =====================================================
    async def _execute_tool(
        self, func_name: str, func_args: Dict, session_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        执行工具调用（generate_image / generate_video）。
        返回工具执行结果（包含任务 ID、状态等）。
        """
        if func_name == "generate_image":
            return await self._execute_generate_image(func_args, session_id)
        elif func_name == "generate_video":
            return await self._execute_generate_video(func_args, session_id)
        else:
            return {"status": "error", "message": f"未知工具: {func_name}"}

    async def _execute_generate_image(self, args: Dict, session_id: Optional[int] = None) -> Dict[str, Any]:
        """执行图片生成工具"""
        from app.services.image_poller import image_poller_manager

        prompt = args.get("prompt", "")
        size = args.get("size", "1024x1024")

        if not prompt:
            return {"status": "error", "message": "提示词不能为空"}

        try:
            params = {
                "model": "agnes-image-2.1-flash",
                "size": size,
                "response_format": "url",
                "mode": "text2image",
            }
            task = await image_poller_manager.create_task(
                prompt=prompt,
                params=params,
            )
            logger.info("[Chat] 图片生成任务已创建: task_id=%s, prompt=%s", task.task_id, prompt[:50])

            return {
                "status": "pending",
                "task_id": task.task_id,
                "media_type": "image",
                "prompt": prompt,
                "size": size,
                "message": "图片生成任务已提交，请稍候...",
            }
        except Exception as e:
            logger.error("[Chat] 图片生成失败: %s", e)
            return {"status": "error", "message": f"图片生成失败: {str(e)}"}

    async def _execute_generate_video(self, args: Dict, session_id: Optional[int] = None) -> Dict[str, Any]:
        """执行视频生成工具"""
        prompt = args.get("prompt", "")
        num_frames = args.get("num_frames", 121)
        width = args.get("width", 1152)
        height = args.get("height", 768)

        if not prompt:
            return {"status": "error", "message": "提示词不能为空"}

        # 校验帧数
        valid_frames = [81, 121, 161, 241, 441]
        if num_frames not in valid_frames:
            # 找最接近的有效值
            num_frames = min(valid_frames, key=lambda x: abs(x - num_frames))

        try:
            result = await agnes_client.create_video_task(
                prompt=prompt,
                model="agnes-video-v2.0",
                num_frames=num_frames,
                frame_rate=24,
                width=width,
                height=height,
                mode="text2video",
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
                "mode": "text2video",
            }
            await poller_manager.start_polling(
                task_id=task_id,
                video_id=video_id,
                prompt=prompt,
                params=params,
            )

            logger.info("[Chat] 视频生成任务已创建: task_id=%s, video_id=%s", task_id, video_id)

            return {
                "status": "pending",
                "task_id": task_id,
                "video_id": video_id,
                "media_type": "video",
                "prompt": prompt,
                "num_frames": num_frames,
                "message": "视频生成任务已提交，通常需要 1-3 分钟...",
            }
        except Exception as e:
            logger.error("[Chat] 视频生成失败: %s", e)
            return {"status": "error", "message": f"视频生成失败: {str(e)}"}


# 全局单例
chat_service = ChatService()
