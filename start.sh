#!/usr/bin/env bash
# 水印清理工具 —— 一键启动（Linux / macOS / WSL）
#
#   ./start.sh                两容器模式（默认，compose.yaml）启动并打开浏览器
#   ./start.sh allinone       单容器模式（compose.allinone.yaml）
#   ./start.sh logs           跟踪日志
#   ./start.sh stop           停止
#   ./start.sh status         查看状态
#   ./start.sh rebuild        重新构建并启动（上游镜像更新后用）
#
# 端口/绑定地址等从 .env 读（见 .env.example），也可以用环境变量覆盖。

set -euo pipefail
cd "$(dirname "$0")"

# 读 .env（存在的话），这样脚本和 compose 用的是同一份配置
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

PORT="${WM_PORT:-8770}"
BIND="${WM_BIND:-127.0.0.1}"
URL="http://127.0.0.1:${PORT}"
MODE="${WM_MODE:-split}"
COMPOSE_FILE="compose.yaml"
[ "$MODE" = "allinone" ] && COMPOSE_FILE="compose.allinone.yaml"

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

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

wait_ready() {
  echo "等待服务就绪..."
  for _ in $(seq 1 60); do
    if curl -fsS "${URL}/api/health" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  return 1
}

case "${1:-up}" in
  up|allinone)
    if [ "${1:-up}" = "allinone" ]; then
      MODE=allinone
      COMPOSE_FILE=compose.allinone.yaml
    fi
    need docker
    wait_docker
    echo "模式：${MODE}（${COMPOSE_FILE}）  监听：${BIND}:${PORT}"
    compose up -d --build
    if wait_ready; then
      echo "已就绪：$URL"
      open_browser
    else
      echo "服务未在预期时间内就绪，请查看日志：./start.sh logs" >&2
      exit 1
    fi
    ;;
  logs)
    compose logs -f web
    ;;
  stop)
    # 两种模式都停，避免切换模式时残留
    docker compose -f compose.yaml down 2>/dev/null || true
    docker compose -f compose.allinone.yaml down 2>/dev/null || true
    echo "已停止"
    ;;
  status)
    compose ps
    ;;
  rebuild)
    need docker
    wait_docker
    compose build --no-cache web
    compose up -d
    echo "已重建：$URL"
    ;;
  *)
    echo "用法: $0 [up|allinone|logs|stop|status|rebuild]" >&2
    exit 2
    ;;
esac
