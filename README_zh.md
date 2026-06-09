# 🎨 Agnes AI Platform · 图片与视频生成平台

**前端（Vue 3 + Vite）**  | **后端（FastAPI + 异步）**  | **SQLite / PostgreSQL**  | **Agnes AI API 集成**  | **自动轮询**

**🌐 Language / 语言**

[English](README.md) | [**中文** ](README_zh.md)

**一个基于 Agnes Image 2.1 Flash 和 Agnes Video V2.0 API 的全栈 Web 应用 —— 拥有精美的 Element Plus 界面、异步后端与持久化生成历史。**

这不是一个简单的演示项目。它是一个生产就绪的平台，采用 **Vue 3 + Vite 前端** 与 **FastAPI 后端**（BFF 层）清晰分离的架构。后端负责 API Key 安全、异步任务轮询与数据库持久化 —— 因此你的 API Key 永远不会暴露到浏览器。

专为追求完整可用平台的开发者而设计 —— 零重度前端框架锁入，无 OpenAI SDK 依赖。

## ✨ 功能特性

### 当前支持

| 模式 | 说明 | 路由页面 |
|---|---|---|
| 🖼️ **文生图** | 根据文本提示词生成图片（同步或异步任务模式） | `ImageView.vue` |
| 🖼️ **图生图** | 根据输入图片与提示词修改现有图片 | `ImageView.vue` |
| 🎬 **文生视频** | 根据文本提示词生成视频（异步 + 自动轮询） | `VideoView.vue` |
| 🎬 **图生视频** | 根据输入图片生成视频 —— 支持单图、多图与关键帧动画模式 | `VideoView.vue` |
| 📜 **生成历史** | 持久化历史记录，支持类型筛选、详情查看、批量删除、缩略图预览 | `HistoryView.vue` |

### 架构亮点

- **全栈分离** —— Vue 3 前端 ↔ FastAPI BFF 层 ↔ Agnes AI 官方 API

- **API Key 安全** —— Key 仅存储于服务端，永不暴露到浏览器

- **异步优先的后端** —— FastAPI + httpx.AsyncClient + SQLAlchemy AsyncSession —— 图片与视频任务互不阻塞

- **独立的异步任务管理器** —— `image_poller` 与 `video_poller` 运行在各自独立的 asyncio.Task 中，拥有各自的生命周期与清理逻辑

- **视频流代理** —— 解决 Google Storage 托管视频的 CORS 问题，支持 Range 请求实现拖动进度播放

- **视频缩略图 / GIF 预览** —— 服务端基于 ffmpeg 的帧提取，用于历史列表可视化

- **零重度前端框架锁入** —— Vue 3 Composition API、Vite、Element Plus、Pinia、Vue Router、Axios —— 标准、成熟的技术栈

## 🏗️ 技术栈

| 层级 | 技术 |
|---|---|
| 前端 | Vue 3（Composition API）+ Vite + Vue Router + Pinia + Axios + Element Plus |
| 后端 | Python 3.10+ · FastAPI · SQLAlchemy（同步 + 异步）· httpx（异步 HTTP 客户端） |
| 数据库 | SQLite（默认）/ PostgreSQL（可选，通过 `DATABASE_URL` 切换） |
| AI 服务 | Agnes AI（`https://apihub.agnes-ai.com/v1`） |
| 系统依赖 | `ffmpeg`（用于视频缩略图与 GIF 预览） |

### 架构示意图

```
┌─────────────────────────────────────────────────────────────┐
│                    用户浏览器（Chrome/Safari...）              │
│  ┌──────────────────────────┐   ┌─────────────────────────┐ │
│  │   Vue 3 SPA (frontend)   │   │  生成结果 / 历史界面    │ │
│  │  - 图片/视频生成页面     │   │  - 下载 / 预览 / 复制   │ │
│  │  - 历史页面              │   └─────────────────────────┘ │
│  │  - Element Plus UI       │                                 │
│  └──────────────────────────┘                                 │
└────────────┬─────────────────────────────────────────────────┘
             │ HTTP / JSON（Vite 开发代理或生产静态文件）
             ▼
┌─────────────────────────────────────────────────────────────┐
│                BFF 层 —— FastAPI（backend）                   │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  路由：/api/images, /api/videos, /api/history, ...      │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  服务：agnes_client（Agnes AI API 封装）                 │ │
│  │        video_poller（视频异步任务轮询器）                 │ │
│  │        image_poller（图片异步任务轮询器）                 │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  SQLAlchemy → SQLite / PostgreSQL（历史记录持久化）        │ │
│  └─────────────────────────────────────────────────────────┘ │
└────────────┬─────────────────────────────────────────────────┘
             │ HTTP / JSON（带 Bearer Token）
             ▼
┌─────────────────────────────────────────────────────────────┐
│               Agnes AI 官方 API（apihub.agnes-ai.com）         │
└─────────────────────────────────────────────────────────────┘
```

## 📦 项目结构

```
agnes-platform/
├── README.md                          # 项目文档（英文）
├── README_zh.md                       # 项目文档（中文）— 本文件
├── API.md                             # REST API 接口文档
├── .gitignore
│
├── frontend/                          # 前端（Vue 3 + Vite）
│   ├── package.json                   # NPM 依赖
│   ├── vite.config.js                 # Vite 配置（代理 /api → 后端:8000）
│   ├── index.html
│   ├── .env.example                   # 前端环境变量模板
│   └── src/
│       ├── main.js                    # 入口 —— 挂载 Element Plus / Router / Pinia
│       ├── App.vue                    # 根组件
│       ├── router/index.js            # 路由配置
│       ├── stores/                    # Pinia 全局状态
│       │   └── taskQueue.js
│       ├── api/                       # axios 封装与接口请求
│       │   ├── client.js
│       │   ├── images.js
│       │   ├── videos.js
│       │   └── history.js
│       ├── components/                # 可复用组件
│       │   ├── ImageUploader.vue
│       │   ├── PromptTemplates.vue
│       │   ├── TaskCard.vue
│       │   └── TaskQueuePanel.vue
│       ├── views/                     # 页面级组件
│       │   ├── ImageView.vue
│       │   ├── VideoView.vue
│       │   └── HistoryView.vue
│       └── assets/                    # CSS 样式与静态资源
│           └── main.css
│
└── backend/                           # 后端（FastAPI）
    ├── requirements.txt               # Python 依赖
    ├── start.sh                       # 一键启动脚本
    ├── stop.sh                        # 服务停止脚本
    ├── .env.example                   # 后端环境变量模板
    └── app/
        ├── main.py                    # FastAPI 入口 —— 路由注册、CORS、lifespan
        ├── core/                      # 核心配置
        │   ├── config.py              # pydantic-settings 环境变量加载
        │   └── database.py            # SQLAlchemy engine / session / Base（同步 + 异步）
        ├── models/                    # ORM 模型
        │   └── generation.py          # Generation 模型（历史记录）
        ├── schemas/                   # Pydantic 请求 / 响应 Schema
        │   ├── common.py
        │   ├── images.py
        │   └── videos.py
        ├── services/                  # 业务服务层
        │   ├── agnes_client.py        # Agnes AI API 客户端（httpx.AsyncClient 连接池）
        │   ├── image_poller.py        # 图片异步任务轮询器
        │   └── video_poller.py        # 视频异步任务轮询器（独立）
        └── routes/                    # API 路由
            ├── images.py              # POST /api/images/tasks, GET /api/images/tasks/{id}
            ├── videos.py              # POST /api/videos, GET /api/videos/{id}, 流代理
            ├── history.py             # GET/DELETE/batch /api/history, 缩略图 + 预览
            └── config.py              # 配置接口
```

## 🚀 快速开始

3 分钟内启动并运行：

### 步骤 0：前置条件

| 工具 | 最低版本 | 用途 |
|---|---|---|
| **Python** | 3.10+（推荐 3.11+） | 后端运行时，asyncio 特性 |
| **Node.js** | 18+（推荐 20+ LTS） | Vite 与 npm install |
| **ffmpeg** | 任意较新版本 | **必需** —— 视频缩略图与 GIF 预览生成 |
| **Agnes AI API Key** | — | 从 [platform.agnes-ai.com](https://platform.agnes-ai.com/) 获取 |

### 步骤 1：安装系统依赖（ffmpeg）

**ffmpeg 是视频缩略图与 GIF 预览功能所必需的。** 没有安装 ffmpeg 时，历史页面仍可正常工作，但缩略图提取会优雅降级（不崩溃）。

```bash
# macOS（通过 Homebrew）
brew install ffmpeg

# Ubuntu / Debian
sudo apt update && sudo apt install -y ffmpeg

# CentOS / RHEL
sudo yum install -y ffmpeg

# Windows（通过 Chocolatey）
choco install ffmpeg

# 验证安装
ffmpeg -version
```

### 步骤 2：安装后端依赖并配置

```bash
cd backend

#（推荐）创建并激活虚拟环境
python -m venv .venv
source .venv/bin/activate          # macOS / Linux
# Windows: .venv\Scripts\activate

# 安装 Python 依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 AGNES_API_KEY
```

### 步骤 3：启动后端

```bash
# 在 backend/ 目录下

# 选项 A —— 使用启动脚本（推荐，自动检测端口与 venv）
chmod +x start.sh
./start.sh

# 选项 B —— 手动启动
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

验证后端：
- **健康检查**：http://localhost:8000/health
- **API 文档（Swagger UI）**：http://localhost:8000/docs

### 步骤 4：安装并启动前端

在**新的终端窗口**中：

```bash
cd frontend

# 安装依赖
npm install

#（可选）配置前端环境变量（开发模式下通常无需修改）
cp .env.example .env

# 启动开发服务器（默认 5173 端口，Vite 自动代理 /api → 后端:8000）
npm run dev
```

访问 http://localhost:5173 即可使用平台。

✨ **完成！** 你现在拥有一个完整可用的全栈图片与视频生成平台。

---

## 📖 完整使用参考

### 图片生成（文生图 / 图生图）

在 Web UI 中访问 **图片** 页面（`/images`）。

| 参数 | 说明 | 默认值 |
|---|---|---|
| **提示词（Prompt）** | 所需图片的文本描述 | **必填** |
| **模式** | `text2image`（文生图）或 `image2image`（图生图） | `text2image` |
| **图片**（图生图模式） | 上传本地图片（自动转换为 base64） | 无 |
| **模型** | Agnes AI 图片模型 | `agnes-image-2.1-flash` |
| **尺寸** | 输出图片尺寸 —— `1024x1024`、`512x512`、`1024x512`、`512x1024` | `1024x1024` |
| **响应格式** | `url`（下载链接）或 `b64_json`（内联 base64） | `url` |

**后端支持两种执行模式：**
- **异步任务模式**（推荐）：POST `/api/images/tasks` → 立即返回 `task_id`，轮询 GET `/api/images/tasks/{task_id}` 获取状态。非阻塞，适合队列化处理。
- **同步模式**（向后兼容）：POST `/api/images/generations` → 阻塞直到完成，直接返回 URL。

### 视频生成（文生视频 / 图生视频 / 关键帧动画）

在 Web UI 中访问 **视频** 页面（`/videos`）。

| 参数 | 说明 | 默认值 |
|---|---|---|
| **提示词（Prompt）** | 所需视频的文本描述 | **必填** |
| **模式** | `text2video`、`image2video` 或 `keyframes` | `text2video` |
| **图片**（图生视频 / 关键帧模式） | 上传本地图片或提供公网 URL | 无 |
| **模型** | Agnes AI 视频模型 | `agnes-video-v2.0` |
| **num_frames** | 总帧数 —— 必须满足 `8n+1`（如 33、49、81、121、241、441） | `121` |
| **frame_rate** | 帧率（1–60） | `24` |
| **width / height** | 视频分辨率（像素） | `1152 / 768` |
| **negative_prompt** | 需要避免的内容描述 | 无 |
| **seed** | 随机种子（用于可重复性） | 随机 |

**按帧数估算时长**（24 fps 下）：

| num_frames | 大致时长 |
|---|---|
| 33 | ~1.4 秒 |
| 81 | ~3.4 秒 |
| 121 | ~5.0 秒 |
| 241 | ~10.0 秒 |
| 441 | ~18.4 秒 |

⚠️ **注意：** Agnes Video API 的图生视频与关键帧模式需要图片为**公网可访问的 URL**。

### 生成历史

在 Web UI 中访问 **历史** 页面（`/history`）。

- 按类型筛选：**全部 / 图片 / 视频**
- 查看详情：点击任意记录可查看提示词、参数、结果 URL
- 单条删除或通过复选框选择进行批量删除
- 视频记录显示自动提取的**缩略图**与鼠标悬停时的 **GIF 预览**

## 📋 API 详情

### 图片 API（后端 → Agnes AI）

- **基础地址**：`https://apihub.agnes-ai.com/v1`
- **接口**：`POST /images/generations`
- **模型**：`agnes-image-2.1-flash`
- **鉴权**：通过 `Authorization: Bearer $AGNES_API_KEY` 传递 Bearer token
- **格式**：兼容 OpenAI API 格式

### 视频 API（后端 → Agnes AI）

- **基础地址**：`https://apihub.agnes-ai.com/v1`
- **轮询地址**：`https://apihub.agnes-ai.com/agnesapi`
- **模型**：`agnes-video-v2.0`
- **流程**：
    1. `POST /videos` → 创建异步任务，返回 `task_id` / `video_id`
    2. `GET /agnesapi?video_id=...`（或 `GET /videos/{task_id}`）→ 轮询完成状态
    3. 状态变化：`in_progress` → `completed`
    4. 从返回的 URL 下载视频
- **鉴权**：通过 `Authorization: Bearer $AGNES_API_KEY` 传递 Bearer token

### 前端 ↔ 后端 API

完整接口文档见 [API.md](API.md)。快速一览：

| 方法 | 接口 | 说明 |
|---|---|---|
| `POST` | `/api/images/tasks` | 创建图片异步任务 |
| `GET` | `/api/images/tasks/{task_id}` | 轮询图片任务状态 |
| `POST` | `/api/videos` | 创建视频异步任务 |
| `GET` | `/api/videos/{task_id}` | 轮询视频任务状态 |
| `GET` | `/api/videos/{task_id}/stream` | 代理播放视频流（支持 CORS + Range） |
| `GET` | `/api/history` | 分页获取生成历史列表 |
| `DELETE` | `/api/history/{id}` | 删除单条历史记录 |
| `POST` | `/api/history/batch-delete` | 批量删除记录 |
| `GET` | `/api/history/video/{id}/thumbnail` | 视频首帧缩略图（JPEG） |
| `GET` | `/api/history/video/{id}/preview` | 视频预览 GIF |

## 🛠️ 架构概览

```
frontend/src/views/ImageView.vue
frontend/src/views/VideoView.vue   }  Vue 3 SPA（UI 层）
frontend/src/views/HistoryView.vue

         │ HTTP / JSON（axios）
         ▼

backend/app/routes/images.py
backend/app/routes/videos.py        }  FastAPI 路由层
backend/app/routes/history.py

         │ async/await
         ▼

backend/app/services/agnes_client.py       }  业务服务层
backend/app/services/image_poller.py       }  （httpx.AsyncClient 连接池，
backend/app/services/video_poller.py       }   独立的 asyncio.Tasks）

         │ async/await
         ▼

backend/app/core/database.py        }  SQLAlchemy 2.0 —— AsyncSession + 同步回退
backend/app/models/generation.py    }  ORM 模型 —— 历史记录持久化

         │ async/await
         ▼

SQLite（默认，零配置）               }  持久化层
PostgreSQL（可选，通过 DATABASE_URL 切换）
```

- **UI 层（`frontend/src/views/*.vue`）** —— 使用 Element Plus 的 Vue 3 组件。用户交互通过 axios 调用 BFF 层 API。
- **路由层（`backend/app/routes/*.py`）** —— FastAPI 异步接口。校验输入、调用服务、返回结构化 JSON 响应。
- **服务层（`backend/app/services/*.py`）** —— `agnes_client` 是共享的 httpx.AsyncClient 连接池。`image_poller` 与 `video_poller` 是**独立**的管理器，各自拥有自己的 asyncio.Task 生命周期、轮询逻辑与清理机制 —— 它们从不互相阻塞。
- **持久化层（`backend/app/core/database.py` + `models/generation.py`）** —— SQLAlchemy 2.0，同时支持同步与异步 Session。默认使用 SQLite（零配置），通过修改 `DATABASE_URL` 即可切换到 PostgreSQL。

## 💡 切换到 PostgreSQL（可选）

平台默认使用 SQLite —— 零配置开箱即用。如需切换到 PostgreSQL：

1. 安装驱动：`pip install psycopg2-binary`
2. 在 `backend/.env` 中设置：
   ```
   DATABASE_URL=postgresql://username:password@localhost:5432/agnes_platform
   ```
3. 重启后端 —— SQLAlchemy 会自动处理其余部分

## 📦 依赖一览

### 前端（NPM）

| 包 | 用途 |
|---|---|
| `vue` | 核心框架（Composition API） |
| `vue-router` | SPA 路由 |
| `pinia` | 全局状态管理 |
| `axios` | HTTP 客户端，用于 API 调用 |
| `element-plus` | UI 组件库（深色主题） |
| `@element-plus/icons-vue` | 图标集 |
| `vite`（开发依赖） | 构建工具与开发服务器 |
| `@vitejs/plugin-vue`（开发依赖） | Vite 的 Vue 3 支持 |

### 后端（Python）

| 包 | 用途 |
|---|---|
| `fastapi` | 异步优先的 Web 框架 |
| `uvicorn[standard]` | ASGI 服务器 |
| `pydantic-settings` | `.env` + 环境变量加载 |
| `python-dotenv` | `.env` 文件解析（由 pydantic-settings 使用） |
| `SQLAlchemy` | ORM + 异步数据库 Session |
| `httpx` | 异步 HTTP 客户端（连接池化调用 Agnes AI） |
| `aiosqlite` | 异步 SQLite 驱动（SQLite 的 AsyncSession 必需） |
| `greenlet` | SQLAlchemy 异步内部协程切换所需 |
| `aiofiles` | 保留给未来的异步文件操作 |

### 系统级

| 工具 | 用途 |
|---|---|
| `ffmpeg` | **视频缩略图与 GIF 预览所必需** —— 提取首帧并生成约 3 秒的预览 GIF。未安装时历史页面优雅降级，不崩溃。 |

## ❓ 常见问题

**Q：为什么需要 BFF 层？直接在浏览器调用 Agnes AI 不行吗？**

A：纯前端架构有两个致命问题：(1) API Key 暴露在浏览器 JavaScript 中，易被窃取。(2) 无法实现持久化历史记录或服务端任务管理。通过 BFF 层，API Key 始终留在服务端 —— 安全性显著提升。

**Q：视频生成需要多长时间？**

A：通常 2–6 分钟。平台在后台自动轮询，前端显示实时进度。你可以先导航到其他页面，稍后通过历史页面查看结果。

**Q：生成的图片/视频存在哪里？**

A：媒体文件由 Agnes AI 托管并以公开 URL 的形式返回。你的本地 SQLite 数据库存储了提示词、参数与结果 URL 作为历史记录。

**Q：可以部署到生产环境吗？**

A：可以。构建前端（`npm run build` → `frontend/dist/`）并以静态文件方式提供（Nginx / Caddy）。将后端部署到任何支持 ASGI 的主机上（Uvicorn 配合 Nginx、Fly.io、Railway 等）。设置 `FRONTEND_ORIGINS` 为你的生产域名，设置 `DATABASE_URL` 为你的生产数据库即可。

## 📜 许可证

MIT © Agnes AI Platform

[图片生成](https://github.com/topics/image-generation) [视频生成](https://github.com/topics/video-generation) [agnes-ai](https://github.com/topics/agnes-ai)
