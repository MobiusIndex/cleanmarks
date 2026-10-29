#!/bin/sh
# 容器入口：默认只起界面服务；WATERMARKS_EMBEDDED=1 时在同一个容器里
# 先把引擎拉起来（单容器 / Docker 模式），界面再连 127.0.0.1。
#
#   split 模式（compose.yaml）：引擎是独立容器 wr-core，这里只跑界面
#   all-in-one （compose.allinone.yaml / docker run）：两个进程都在本容器内
set -eu

WEB_PORT="${WATERMARKS_WEB_PORT:-8770}"
ENGINE_PORT="${WATERMARKS_EMBEDDED_PORT:-8765}"

if [ "${WATERMARKS_EMBEDDED:-0}" = "1" ]; then
    echo "[entrypoint] 启动内置引擎：127.0.0.1:${ENGINE_PORT}"
    python3 /app/scripts/server.py --host 127.0.0.1 --port "${ENGINE_PORT}" &
    ENGINE_PID=$!

    # 等引擎能应答再放行界面，否则首屏会误报「引擎未连接」
    i=0
    while [ "$i" -lt 90 ]; do
        if python3 - "$ENGINE_PORT" <<'PY' 2>/dev/null
import sys, urllib.request
urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=2).read()
PY
        then
            echo "[entrypoint] 引擎就绪"
            break
        fi
        i=$((i + 1))
        sleep 1
    done
    if [ "$i" -ge 90 ]; then
        echo "[entrypoint] 引擎在 90 秒内没起来，界面照常启动（会显示引擎未连接）" >&2
    fi

    # 容器收到 SIGTERM 时把引擎一起带走
    trap 'kill "$ENGINE_PID" 2>/dev/null || true' TERM INT
fi

exec python3 /app/server.py --port "${WEB_PORT}" "$@"
