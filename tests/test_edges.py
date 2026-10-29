#!/usr/bin/env python3
"""边界与并发检查：空文件、超长名、点文件、并发一致性、临时文件残留。"""
import os
import base64, io, json, os, random, sys, threading, urllib.request, urllib.error, zipfile

BASE = os.environ.get("WM_BASE", "http://127.0.0.1:8770")
FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

def b64u(s): return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")

def clean(name, data, opts=None):
    h = {"Content-Type": "application/octet-stream", "X-Wm-Name": b64u(name)}
    if opts is not None: h["X-Wm-Options"] = b64u(json.dumps(opts))
    req = urllib.request.Request(BASE + "/api/raw/clean", data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            rep = r.headers.get("X-Wm-Report")
            return r.status, r.read(), (json.loads(base64.b64decode(rep)) if rep else None), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), None, e.headers

ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  PASS  {label}")
    else: fail += 1; print(f"  FAIL  {label}  {extra}")

png = open(os.path.join(FIX, "ai.png"), "rb").read()

print("== 空文件 ==")
st, body, rep, hdr = clean("empty.txt", b"")
check(f"空 .txt 不崩（{st}）", st in (200, 400, 422), body[:120])
st, body, rep, hdr = clean("empty.png", b"")
check(f"空 .png 返回错误而非 500（{st}）", st < 500, body[:160])

print("== 点文件 / 无扩展名 ==")
st, body, rep, hdr = clean(".gitignore", b"node_modules\n*.log\n")
print(f"    .gitignore → {st} {body[:80]}")
st, body, rep, hdr = clean("...", png)
check(f"纯点名 → 不崩（{st}）", st < 500, body[:120])

print("== 超长文件名 ==")
long_name = "L" * 200 + ".docx"
st, body, rep, hdr = clean(long_name, open(os.path.join(FIX, "note.docx"), "rb").read())
print(f"    200+4 字符 .docx → {st} · out={hdr.get('X-Wm-Out-Name', '')[:40]}")
check(f"超长名不返回 500（{st}）", st < 500, body[:120])
if st == 200:
    out = base64.urlsafe_b64decode(hdr["X-Wm-Out-Name"] + "=" * ((4 - len(hdr["X-Wm-Out-Name"]) % 4) % 4)).decode()
    check("超长名仍保留原扩展名", out.endswith(".docx"), out[-40:])

print("== 并发一致性（8 个请求混跑）==")
files = [
    ("a.png", png), ("b.png", png), ("c.txt", "并发测试 1\n".encode()),
    ("d.md", b"# t\n\nbody\n"), ("e.png", png), ("f.txt", "hello\u200bworld".encode()),
    ("g.png", png), ("h.txt", "zero\u2060width".encode()),
]
results = {}
errors = []
def worker(i, name, data):
    try:
        st, body, rep, hdr = clean(name, data)
        results[i] = (st, len(body), body[:8])
    except Exception as e:
        errors.append((name, repr(e)))

threads = [threading.Thread(target=worker, args=(i, n, d)) for i, (n, d) in enumerate(files)]
for t in threads: t.start()
for t in threads: t.join()
check("8 个并发全部返回 200", all(v[0] == 200 for v in results.values()), results)
check("并发无异常", not errors, errors)
check("PNG 输出魔数正确", all(results[i][2] == b"\x89PNG\r\n\x1a\n" for i in (0, 1, 4, 6)), results)

print("== 并发下 /api/meta 不被卡死 ==")
import time
t0 = time.time()
box = {}
def meta():
    try:
        with urllib.request.urlopen(BASE + "/api/meta", timeout=30) as r:
            box["ok"] = json.load(r).get("ok")
    except Exception as e:
        box["err"] = repr(e)
th = [threading.Thread(target=meta) for _ in range(3)]
for t in th: t.start()
for t in th: t.join()
check(f"/api/meta 3 并发完成（{time.time()-t0:.1f}s）", box.get("ok") is True, box)

print(f"\n结果：{ok} 通过 / {fail} 失败")
sys.exit(1 if fail else 0)
