#!/usr/bin/env python3
"""纯函数单测：报告头裁剪、主机判定、文件名、格式判定。直接 import server.py。"""
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402

ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label}  {extra}")


print("== 报告头裁剪 ==")
small = {"kind": "image", "bytes_in": 10, "bytes_out": 5, "findings": ["a"]}
packed = server._pack_report(small)
check("小报告原样打包", json.loads(base64.b64decode(packed)) == small)

big = {
    "kind": "container",
    "findings": [f"finding-{i}-" + "x" * 60 for i in range(400)],
    "post_findings": [f"post-{i}-" + "y" * 60 for i in range(400)],
    "actions": [f"action-{i}-" + "z" * 60 for i in range(400)],
    "bytes_in": 1,
}
big_packed = server._pack_report(big)
decoded = json.loads(base64.b64decode(big_packed))
check(f"大报告裁到 {server.REPORT_HEADER_LIMIT} 字节内（{len(big_packed)}）",
      len(big_packed) <= server.REPORT_HEADER_LIMIT, len(big_packed))
check("裁剪后仍能解码且带 truncated 标记", decoded.get("truncated") is True)
check("裁剪保留关键字段", decoded.get("kind") == "container" and decoded.get("bytes_in") == 1)

print("== 主机判定（决定要不要把密钥重发到网关） ==")
for host, want in [
    ("api.openai.com", False),
    ("open.bigmodel.cn", False),
    ("generativelanguage.googleapis.com", False),
    ("host.docker.internal", True),
    ("localhost", True),
    ("ollama", True),
    ("192.168.1.9", True),
    ("172.17.0.1", True),
    ("8.8.8.8", False),
    ("", False),
]:
    check(f"{host or '(空)'} → {want}", server._is_local_host(host) is want)

print("== 文件名 ==")
long_name = "L" * 200 + ".docx"
check("超长名保留扩展名", server._safe_filename(long_name).endswith(".docx"),
      server._safe_filename(long_name)[-12:])
check("去掉路径", server._safe_filename("../../etc/passwd") == "passwd")
check("去掉控制字符", "\r" not in server._safe_filename("a\r\nb.png"))
check("空名兜底", server._safe_filename("") == "file")

print("== 文本兜底判定 ==")
check("普通文本", server._plausible_text(b"hello world\n", 12) is True)
check("含 NUL 的二进制", server._plausible_text(b"ab\x00cd", 5) is False)
check("超过 32MB 不猜", server._plausible_text(b"hello", 40 * 1024 * 1024) is False)
check("控制字符过多", server._plausible_text(bytes(range(1, 32)) * 3, 93) is False)

print("== 格式判定 ==")
for name, want in [("a.png", "image"), ("b.wav", "av"), ("c.docx", "container"),
                   ("d.txt", "text"), ("e.unknownext", "unknown"), (".gitignore", "unknown")]:
    check(f"{name} → {want}", server._classify(name) == want, server._classify(name))

print(f"\n结果：{ok} 通过 / {fail} 失败")
sys.exit(1 if fail else 0)
