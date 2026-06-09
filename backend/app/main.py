# =====================================================
# Agnes AI Platform - 后端入口（全异步架构）
#
# 架构概览：
#   ┌──────────────────────────────────────────┐
#   │  FastAPI 应用层                           │
#   │  - lifespan：启动/关闭时初始化/释放资源   │
#   │  - 路由：images / videos / history / config│
#   │  - CORS 中间件：允许前端跨域              │
#   └────────────────────┬─────────────────────┘
#                        │ HTTP (async)
#   ┌────────────────────▼─────────────────────┐
#   │  Service 层（业务逻辑）                    │
#   │  - agnes_client：httpx.AsyncClient（连接池）│
#   │  - video_poller：独立 asyncio.Task 轮询   │
#   └────────────────────┬─────────────────────┘
#                        │ async/await
#   ┌────────────────────▼─────────────────────┐
#   │  Database 层                              │
#   │  - 异步 SQLAlchemy 2.0 engine + AsyncSession │
#   │  - SQLite / PostgreSQL（可切换）           │
#   └──────────────────────────────────────────┘
#
# 异步特性：
#   - 图片生成：await 等待 Agnes AI，不阻塞事件循环
#   - 视频生成：创建任务后立即返回，后台独立 Task 轮询
#   - 数据库：所有数据库操作均为 AsyncSession + await
#   - HTTP：httpx.AsyncClient 持久化连接池
#   - 图片与视频任务互不干扰，独立调度
# =====================================================

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import Base, engine, async_engine
from app.routes import images, videos, history as history_route, config as config_route, chat as chat_route
from app.services.video_poller import poller_manager
from app.services.image_poller import image_poller_manager
from app.services.agnes_client import agnes_client

# ---------- 日志配置 ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agnes_platform")


# =====================================================
# 数据库初始化（同步 + 异步表创建）
# =====================================================
# 使用同步 metadata 先创建表（SQLite 不支持 DDL 并发）
Base.metadata.create_all(bind=engine)
logger.info("✓ 数据库表已初始化")


# =====================================================
# Lifespan 上下文管理器（替代 deprecated startup/shutdown）
# =====================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理：
    - 启动：初始化异步资源（HTTP 连接池、后台任务轮询器）
    - 关闭：优雅释放所有异步资源
    """
    # ---------- 【启动阶段】----------
    if not settings.agnes_api_key or settings.agnes_api_key.startswith("sk-your"):
        logger.warning("⚠️ AGNES_API_KEY 未配置！请编辑 backend/.env，填入你的 Agnes AI API Key 后重启服务。")
    else:
        logger.info("✓ Agnes AI API Key 已加载")

    # 初始化 httpx.AsyncClient（持久化连接池）
    await agnes_client.start()
    logger.info("✓ HTTP 连接池已就绪")

    # 启动视频轮询器后台清理协程
    await poller_manager.start()
    logger.info("✓ 视频任务轮询器已就绪")

    # 启动图片任务器后台清理协程
    await image_poller_manager.start()
    logger.info("✓ 图片任务器已就绪")

    logger.info("🚀 Agnes AI Platform（全异步架构）后端服务已启动")

    yield  # 应用在此期间运行

    # ---------- 【关闭阶段】----------
    logger.info("👋 正在优雅关闭服务...")

    # 1. 取消所有视频轮询任务
    await poller_manager.shutdown()
    logger.info("✓ 视频轮询器已关闭")

    # 2. 取消所有图片生成任务
    await image_poller_manager.shutdown()
    logger.info("✓ 图片任务器已关闭")

    # 3. 关闭 HTTP 连接池
    await agnes_client.shutdown()
    logger.info("✓ HTTP 连接池已关闭")

    # 3. 关闭异步数据库引擎
    await async_engine.dispose()
    logger.info("✓ 数据库连接已释放")

    logger.info("👋 服务已完全关闭")


# =====================================================
# FastAPI 应用实例
# =====================================================
app = FastAPI(
    title="Agnes AI Platform",
    description="图片与视频生成平台 BFF 服务 — 全异步架构，图片/视频任务互不阻塞",
    version="2.0.0",
    lifespan=lifespan,
)

# ---------- CORS 中间件 ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 全局异常处理 ----------
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """
    捕获所有未处理异常，返回统一格式的 JSON 响应，避免将原始堆栈暴露给前端。
    """
    logger.error("未处理的异常: %s", str(exc), exc_info=True)

    status_code = getattr(exc, "status_code", 500)
    detail = getattr(exc, "detail", str(exc)) if hasattr(exc, "detail") else "服务器内部错误，请稍后重试"

    return JSONResponse(
        status_code=status_code,
        content={"status": "error", "message": detail},
    )


# ---------- 注册路由 ----------
app.include_router(config_route.router, prefix="/api", tags=["配置"])
app.include_router(images.router, prefix="/api", tags=["图片生成"])
app.include_router(videos.router, prefix="/api", tags=["视频生成"])
app.include_router(history_route.router, prefix="/api", tags=["生成历史"])
app.include_router(chat_route.router, prefix="/api", tags=["AI 聊天"])


# ---------- 健康检查 ----------
@app.get("/health", summary="健康检查")
async def health_check():
    return {"status": "ok", "service": "agnes-ai-platform"}


@app.get("/", summary="根路径 — 返回服务信息")
async def root():
    return {
        "name": "Agnes AI Platform BFF",
        "version": "2.0.0",
        "architecture": "async (FastAPI + httpx.AsyncClient + SQLAlchemy async)",
        "docs": "/docs",
        "health": "/health",
    }
