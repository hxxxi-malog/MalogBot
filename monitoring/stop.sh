#!/bin/bash
# 停止 Prometheus + Grafana 监控服务

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "停止监控服务..."

cd "$SCRIPT_DIR"
docker compose down

echo "监控服务已停止"
