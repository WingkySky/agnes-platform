#!/bin/bash
# =====================================================
# Agnes AI Platform 后端启动脚本
# =====================================================

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo "  Agnes AI Platform - 后端启动"
echo "========================================"

# 检查 .env 文件是否存在
if [ ! -f ".env" ]; then
    echo "⚠️  警告: .env 文件不存在！"
    echo "   请从 .env.example 复制一份并配置 AGNES_API_KEY"
    echo ""
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "✅ 已创建 .env 文件，请编辑并填入你的 API Key"
    fi
    echo ""
fi

# 检查 8000 端口是否被占用
PORT=8000
if lsof -ti:$PORT >/dev/null 2>&1; then
    echo "⚠️  端口 $PORT 已被占用，正在清理..."
    PID=$(lsof -ti:$PORT)
    kill $PID 2>/dev/null
    sleep 1
    # 如果还在占用，强制杀死
    if lsof -ti:$PORT >/dev/null 2>&1; then
        kill -9 $(lsof -ti:$PORT) 2>/dev/null
        sleep 1
    fi
    echo "✅ 端口已释放"
    echo ""
fi

# 检查虚拟环境是否存在
if [ -d ".venv" ]; then
    echo "📦 激活虚拟环境..."
    source .venv/bin/activate
else
    echo "⚠️  虚拟环境 .venv 不存在，将使用系统 Python"
    echo "   如需创建虚拟环境，运行: python -m venv .venv"
fi

# 检查 requirements 是否安装
echo ""
echo "📋 检查依赖..."
python -c "import fastapi" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "⚠️  依赖未安装，正在安装..."
    pip install -r requirements.txt
fi

echo ""
echo "🚀 启动后端服务 (端口 $PORT)..."
echo "   API 文档: http://localhost:$PORT/docs"
echo "   健康检查: http://localhost:$PORT/health"
echo ""
echo "按 Ctrl+C 停止服务"
echo "========================================"
echo ""

# 启动 uvicorn
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --reload
