#!/usr/bin/env python3
"""最小 OpenAI 兼容 mock，用于验证 Layer B 链路（不含真实模型）。"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8788
HITS = []


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("[mock]", fmt % args, flush=True)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
        prompt = (data.get("messages") or [{}])[0].get("content", "")
        body = prompt.split("---")[-1].strip()
        HITS.append({"model": data.get("model"), "prompt_len": len(prompt)})
        content = f"REWRITTEN<<{body}>>"
        payload = {
            "id": "mock-1",
            "object": "chat.completion",
            "model": data.get("model"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
        }
        out = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        out = json.dumps({"hits": len(HITS), "last": HITS[-1] if HITS else None}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


print(f"mock OpenAI-compatible on 0.0.0.0:{PORT}", flush=True)
ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
