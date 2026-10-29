#!/usr/bin/env python3
"""本地模型中转：把容器够不到的服务暴露到 Docker 网关。

场景：Docker 跑在 WSL 里，容器和 WSL 宿主之间只隔着 docker 网关。像 Ollama
这种默认只监听 127.0.0.1 的服务，容器直接连不上；这个脚本在 WSL 里起一个
转发（监听 0.0.0.0），容器再把 Base URL 指向它就行。

    # WSL 里执行：把容器要用的 11434（Ollama）转出来
    python3 llm-relay.py --listen 8788 --target 11434

    # 界面里填
    Base URL: http://host.docker.internal:8788/v1
    模型名:   Ollama 里拉好的模型名

关于 Windows 上的 LM Studio：WSL 与 Windows 不共享 loopback，这台机器上
容器也到不了 Windows 的局域网地址（实测超时），所以 Windows 侧的模型服务
容器用不了。要么把模型服务跑在 WSL 里（Ollama 装 WSL、或用
`OLLAMA_HOST=0.0.0.0` 让它监听全网卡），要么用云端 API。

    python3 llm-relay.py --help
"""

from __future__ import annotations

import argparse
import http.client
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TARGET_HOST = "127.0.0.1"
TARGET_PORT = 0
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}


class Relay(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "llm-relay"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[relay] {self.address_string()} {fmt % args}", flush=True)

    def _fail(self, code: int, msg: str) -> None:
        body = msg.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.close_connection = True
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _forward(self, method: str) -> None:
        # 精确比较会漏掉 "gzip, chunked" 这种组合写法
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            self._fail(411, "relay does not support chunked transfer encoding")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._fail(400, "invalid Content-Length")
            return
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        # absolute-form 请求行（"POST http://evil/ HTTP/1.1"）只转发路径部分
        target = self.path
        if "://" in target:
            parts = urllib.parse.urlsplit(target)
            target = parts.path + (("?" + parts.query) if parts.query else "")
        conn = http.client.HTTPConnection(TARGET_HOST, TARGET_PORT, timeout=600)
        sent = False
        try:
            conn.request(method, target, body=body, headers=headers)
            resp = conn.getresponse()
            payload = resp.read()
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() in HOP_BY_HOP:
                    continue
                self.send_header(k, v)
            if method == "HEAD":
                # HEAD 没有响应体，但要如实转发上游声明的长度（原来写成 0 是错的）
                self.send_header("Content-Length", resp.getheader("Content-Length") or "0")
            else:
                self.send_header("Content-Length", str(len(payload)))
            sent = True
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(payload)
        except Exception as e:  # noqa: BLE001
            if sent:
                # 响应头已经发出去了，再发一个 502 会污染响应流，只能断开
                print(f"[relay] 转发中断：{e}", flush=True)
                self.close_connection = True
            else:
                self._fail(502, f"转发失败：{e}")
        finally:
            conn.close()

    def do_GET(self) -> None:  # noqa: N802
        self._forward("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._forward("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._forward("DELETE")

    def do_HEAD(self) -> None:  # noqa: N802
        self._forward("HEAD")


def main() -> int:
    global TARGET_HOST, TARGET_PORT
    p = argparse.ArgumentParser(description="把容器里的请求转发到本机（Windows）上的模型服务")
    p.add_argument("--listen", type=int, default=8788, help="本脚本监听的端口（容器连这个）")
    p.add_argument("--target", type=int, default=1234, help="模型服务端口（LM Studio 默认 1234）")
    p.add_argument("--target-host", default="127.0.0.1", help="模型服务地址，默认本机")
    args = p.parse_args()
    TARGET_HOST = args.target_host
    TARGET_PORT = args.target

    srv = ThreadingHTTPServer(("0.0.0.0", args.listen), Relay)
    srv.daemon_threads = True
    print(f"中转已启动: 0.0.0.0:{args.listen} → {TARGET_HOST}:{TARGET_PORT}", flush=True)
    print(f"界面里填 Base URL: http://host.docker.internal:{args.listen}/v1", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
