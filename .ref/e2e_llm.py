#!/usr/bin/env python3
"""验证 Layer B（AI 接口）链路：探活 + 文本清理。"""
import base64, json, urllib.request, urllib.error
from pathlib import Path

BASE = "http://127.0.0.1:8770"
LLM_BASE = "http://host.docker.internal:8791/v1"   # 故意用解析不了的域名，测回退
MODEL = "mock-model"


def b64u(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def post_json(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def clean(name, data, llm=None, options=None):
    headers = {"Content-Type": "application/octet-stream", "X-Wm-Name": b64u(name)}
    if options is not None:
        headers["X-Wm-Options"] = b64u(json.dumps(options))
    if llm is not None:
        headers["X-Wm-Llm"] = b64u(json.dumps(llm))
    req = urllib.request.Request(BASE + "/api/raw/clean", data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            rep = r.headers.get("X-Wm-Report")
            return r.status, r.read(), (json.loads(base64.b64decode(rep)) if rep else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), None


ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1; print(f"  PASS  {label}")
    else:
        fail += 1; print(f"  FAIL  {label}  {extra}")


llm = {
    "enabled": True, "backend": "openai-compatible", "base_url": LLM_BASE,
    "model": MODEL, "api_key": "sk-test-secret", "strategy": "paraphrase@0.8",
    "lang": "English", "original_lang": "Chinese", "timeout": 30,
}

print("== /api/llm/test ==")
st, j = post_json("/api/llm/test", llm)
print("   ", json.dumps(j, ensure_ascii=False)[:300])
check("探活成功", st == 200 and j.get("ok") is True, j)
check("返回延迟", isinstance(j.get("latency_ms"), int), j)
check("端点拼接正确", (j.get("endpoint") or "").endswith("/v1/chat/completions"), j.get("endpoint"))

print("== 文本清理 + Layer B ==")
txt = "这是一段测试文本，用于验证 Layer B 改写链路是否打通。\n"
st, body, rep = clean("a.txt", txt.encode(), llm)
check(f"HTTP {st}", st == 200, body[:300])
if st == 200:
    out = body.decode()
    check("输出经过模型改写", "REWRITTEN<<" in out, out[:200])
    check("原文被送进模型", "这是一段测试文本" in out, out[:200])
    check("report.layer_b 存在", bool(rep and rep.get("layer_b")), rep)
    check("layer_b 记录了模型", (rep or {}).get("layer_b", {}).get("model") == MODEL, rep)
    check("layer_b 记录了策略", (rep or {}).get("layer_b", {}).get("strategy") == ["paraphrase@0.8"], rep)
    check("layer_a_only 变为 False", (rep or {}).get("layer_a_only") is False, rep)
    print("    layer_b:", json.dumps((rep or {}).get("layer_b"), ensure_ascii=False)[:300])

print("== 未配置 LLM 时行为不变 ==")
st, body, rep = clean("b.txt", "Hello\u200bWorld".encode(), None, {"normalize_spaces": True})
check(f"HTTP {st}", st == 200, body[:200])
check("仍然只做 Layer A", (rep or {}).get("layer_a_only") is True, rep)
check("零宽字符已清", b"\xe2\x80\x8b" not in body, body[:60])

print("== 错误处理 ==")
st, body, rep = clean("c.txt", txt.encode(), {**llm, "base_url": "http://127.0.0.1:9/v1", "timeout": 10})
check(f"连不上 → 4xx/5xx（{st}）", st >= 400, st)
check("错误信息不含密钥", b"sk-test-secret" not in body, body[:200])
st, body, rep = clean("d.txt", txt.encode(), {**llm, "model": ""})
check(f"缺模型名 → 400（{st}）", st == 400, (st, body[:120]))
st, body, rep = clean("e.txt", txt.encode(), {**llm, "strategy": "bogus@2"})
check(f"非法策略 → 400（{st}）", st == 400, (st, body[:160]))
st, body, rep = clean("f.txt", txt.encode(), {**llm, "strategy": "mlm@0.5"})
check(f"mlm 战术 → 400（{st}）", st == 400, (st, body[:160]))

print(f"\n结果：{ok} 通过 / {fail} 失败")
raise SystemExit(1 if fail else 0)
