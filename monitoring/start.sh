#!/bin/bash
# 启动 Prometheus + Grafana 监控服务

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=========================================="
echo "  MalogBot 监控服务启动脚本"
echo "=========================================="
echo ""

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    echo "错误: Docker 未安装，请先安装 Docker"
    exit 1
fi

# 检查 Docker Compose 是否可用
if ! docker compose version &> /dev/null; then
    echo "错误: Docker Compose 不可用，请升级 Docker"
    exit 1
fi

echo "启动监控服务..."
echo ""

cd "$SCRIPT_DIR"

# 启动服务
docker compose up -d

echo ""
echo "等待服务启动..."
sleep 5

echo ""
echo "=========================================="
echo "  服务已启动!"
echo "=========================================="
echo ""
echo "访问地址:"
echo "  - Prometheus:  http://localhost:9090"
echo "  - Grafana:     http://localhost:3000"
echo ""
echo "Grafana 登录信息:"
echo "  - 用户名: admin"
echo "  - 密码: admin123"
echo ""
echo "确保 MalogBot 应用运行在 localhost:5000"
echo "=========================================="
