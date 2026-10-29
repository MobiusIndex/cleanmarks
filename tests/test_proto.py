#!/usr/bin/env python3
"""协议层检查：短包、keep-alive 错位、跨站 Origin、选项语义。"""
import base64, json, socket, sys, urllib.request, urllib.error

HOST, PORT = "127.0.0.1", 8770
ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label}  {extra}")


def b64u(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def raw(request: bytes, read_bytes=4096) -> bytes:
    s = socket.create_connection((HOST, PORT), timeout=15)
    s.sendall(request)
    buf = b""
    try:
        while len(buf) < read_bytes:
            part = s.recv(4096)
            if not part:
                break
            buf += part
            if b"\r\n\r\n" in buf and (b"Content-Length: 0" in buf or len(buf) > 200):
                break
    except socket.timeout:
        pass
    finally:
        s.close()
    return buf


print("== 短包（声明 100 只发 5）==")
sock = socket.create_connection((HOST, PORT), timeout=20)
sock.sendall(
    b"POST /api/raw/clean HTTP/1.1\r\nHost: 127.0.0.1:8770\r\n"
    b"X-Wm-Name: " + b64u("short.txt").encode() + b"\r\n"
    b"Content-Type: application/octet-stream\r\nContent-Length: 100\r\n\r\nhello"
)
sock.shutdown(socket.SHUT_WR)
try:
    reply = sock.recv(65536).decode("latin-1")
except (socket.timeout, ConnectionResetError):
    reply = ""
sock.close()
status = reply.split(" ")[1] if reply.startswith("HTTP/") else "?"
check(f"短包被拒（{status}）", status == "400", reply[:120])
check("短包没有返回文件", "X-Wm-Out-Name" not in reply)

print("== keep-alive 错位 ==")
bad = raw(
    b"POST /api/raw/clean HTTP/1.1\r\nHost: 127.0.0.1:8770\r\n"
    b"X-Wm-Name: " + b64u("x.unknownext").encode() + b"\r\n"
    b"Content-Type: application/octet-stream\r\nContent-Length: 4\r\n\r\nBODY"
)
st = bad.split(b" ")[1] if bad.startswith(b"HTTP/") else b"?"
check(f"错误响应带 Connection: close（{st.decode()}）",
      b"connection: close" in bad.lower(), bad[:200])
check("错误响应后连接不会复用错位字节", b"501" not in bad)

print("== 跨站 Origin ==")
req = urllib.request.Request(
    "http://127.0.0.1:8770/api/raw/clean",
    data=b"hello", method="POST",
    headers={"Content-Type": "application/octet-stream",
             "X-Wm-Name": b64u("t.txt"), "Origin": "http://evil.example"},
)
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        code, body = r.status, r.read()
except urllib.error.HTTPError as e:
    code, body = e.code, e.read()
check(f"陌生 Origin 被拒（{code}）", code == 403, body[:80])

req = urllib.request.Request(
    "http://127.0.0.1:8770/api/raw/clean",
    data=b"hello", method="POST",
    headers={"Content-Type": "application/octet-stream",
             "X-Wm-Name": b64u("t.txt"), "Origin": "http://127.0.0.1:8770"},
)
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        code = r.status
except urllib.error.HTTPError as e:
    code = e.code
check(f"同源请求放行（{code}）", code == 200, code)

print("== normalize_spaces 选项语义 ==")


def clean_text(text: str, opts: dict) -> str:
    req = urllib.request.Request(
        "http://127.0.0.1:8770/api/raw/clean", data=text.encode(), method="POST",
        headers={"Content-Type": "application/octet-stream",
                 "X-Wm-Name": b64u("sp.txt"),
                 "X-Wm-Options": b64u(json.dumps(opts))},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


spaced = "a\u00a0b\u2002c"          # NBSP + EN SPACE：引擎的 normalize_spaces 只管同形字
check("默认把空格同形字换成普通空格", clean_text(spaced, {}) == "a b c", repr(clean_text(spaced, {})))
check("normalize_spaces=0 保留原样", clean_text(spaced, {"normalize_spaces": 0}) == spaced,
      repr(clean_text(spaced, {"normalize_spaces": 0})))
check("normalize_spaces=false 保留原样", clean_text(spaced, {"normalize_spaces": False}) == spaced,
      repr(clean_text(spaced, {"normalize_spaces": False})))

print("== 存活探针 ==")
with urllib.request.urlopen("http://127.0.0.1:8770/api/ping", timeout=10) as r:
    ping = json.load(r)
check("/api/ping 本地回 200", ping.get("ok") is True and ping.get("web_version"), ping)

print("== 未配置 LLM 时 inspect 不受坏 X-Wm-Llm 影响 ==")
req = urllib.request.Request(
    "http://127.0.0.1:8770/api/raw/inspect", data=b"hello", method="POST",
    headers={"Content-Type": "application/octet-stream", "X-Wm-Name": b64u("i.txt"),
             "X-Wm-Llm": "!!!not-base64!!!"},
)
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        code = r.status
except urllib.error.HTTPError as e:
    code = e.code
check(f"坏 LLM 头不影响 inspect（{code}）", code == 200, code)

print(f"\n结果：{ok} 通过 / {fail} 失败")
sys.exit(1 if fail else 0)
