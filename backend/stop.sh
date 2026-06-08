#!/bin/bash
# =====================================================
# Agnes AI Platform 后端停止脚本
# =====================================================

echo "========================================"
echo "  Agnes AI Platform - 停止后端服务"
echo "========================================"

# 首先检查 8000 端口是否有进程
PORT=8000
if lsof -ti:$PORT >/dev/null 2>&1; then
    PIDS=$(lsof -ti:$PORT)
    echo "🔍 发现端口 $PORT 被占用，正在停止..."
    kill $PIDS 2>/dev/null
    sleep 1
    # 如果还在运行，强制停止
    if lsof -ti:$PORT >/dev/null 2>&1; then
        kill -9 $(lsof -ti:$PORT) 2>/dev/null
        sleep 1
    fi
    echo "✅ 端口 $PORT 已释放"
fi

# 查找并停止所有 uvicorn/agnes 相关进程（兜底）
PIDS=$(ps aux | grep -E "(uvicorn.*agnes|python.*uvicorn.*app.main)" | grep -v grep | awk '{print $2}')

if [ -n "$PIDS" ]; then
    echo ""
    echo "🔍 清理其他相关进程:"
    for PID in $PIDS; do
        if ps -p $PID >/dev/null 2>&1; then
            kill $PID 2>/dev/null
            echo "   已停止 PID $PID"
        fi
    done
    sleep 1
    
    # 检查是否还有残留进程
    REMAINING_PIDS=$(ps aux | grep -E "(uvicorn.*agnes|python.*uvicorn.*app.main)" | grep -v grep | awk '{print $2}')
    if [ -n "$REMAINING_PIDS" ]; then
        echo ""
        echo "⚠️  强制停止残留进程..."
        kill -9 $REMAINING_PIDS 2>/dev/null
    fi
fi

echo ""
echo "✅ 后端服务已停止"
echo "========================================"
