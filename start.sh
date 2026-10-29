#!/usr/bin/env bash
# 水印清理工具 —— 一键启动（Linux / macOS）
#
#   ./start.sh            启动并打开浏览器
#   ./start.sh logs       跟踪日志
#   ./start.sh stop       停止
#   ./start.sh status     查看状态
#   ./start.sh rebuild    重新构建并启动（上游镜像更新后用）

set -euo pipefail
cd "$(dirname "$0")"

PORT=8770
URL="http://127.0.0.1:${PORT}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "错误：找不到 $1" >&2
    echo "请先安装 Docker：https://docs.docker.com/get-docker/" >&2
    exit 1
  }
}

wait_docker() {
  echo "等待 Docker 守护进程..."
  local i=0
  until docker info >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -gt 60 ]; then
      echo "错误：Docker 未就绪。请确认 Docker Desktop / dockerd 已启动。" >&2
      exit 1
    fi
    sleep 3
  done
}

open_browser() {
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 &
  elif command -v open >/dev/null 2>&1; then open "$URL" >/dev/null 2>&1 &
  else echo "请手动在浏览器打开 $URL"; fi
}

case "${1:-up}" in
  up)
    need docker
    wait_docker
    echo "构建并启动..."
    docker compose up -d --build
    echo "等待服务就绪..."
    for _ in $(seq 1 40); do
      if curl -fsS "${URL}/api/health" >/dev/null 2>&1; then break; fi
      sleep 2
    done
    if curl -fsS "${URL}/api/health" >/dev/null 2>&1; then
      echo "已就绪：$URL"
      open_browser
    else
      echo "服务未在预期时间内就绪，请查看日志：docker compose logs -f web" >&2
      exit 1
    fi
    ;;
  logs)
    docker compose logs -f web
    ;;
  stop)
    docker compose down
    echo "已停止"
    ;;
  status)
    docker compose ps
    ;;
  rebuild)
    need docker
    wait_docker
    docker compose build --no-cache web
    docker compose up -d
    echo "已重建：$URL"
    ;;
  *)
    echo "用法: $0 [up|logs|stop|status|rebuild]" >&2
    exit 2
    ;;
esac