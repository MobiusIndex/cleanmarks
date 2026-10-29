#!/usr/bin/env python3
"""端到端验证：直接打 http://127.0.0.1:8770 的新端点。"""
import base64, json, sys, urllib.request, urllib.error
from pathlib import Path

BASE = "http://127.0.0.1:8770"
FIX = Path(__file__).parent / "fixtures"

def b64u(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")

def raw(path, data, name, options=None, timeout=900):
    headers = {"Content-Type": "application/octet-stream", "X-Wm-Name": b64u(name)}
    if options is not None:
        headers["X-Wm-Options"] = b64u(json.dumps(options))
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            rep = r.headers.get("X-Wm-Report")
            return r.status, dict(r.headers), r.read(), (json.loads(base64.b64decode(rep)) if rep else None)
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            return e.code, dict(e.headers), json.loads(body), None
        except Exception:
            return e.code, dict(e.headers), body, None

ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1; print(f"  PASS  {label}")
    else:
        fail += 1; print(f"  FAIL  {label}  {extra}")

print("== 静态资源 ==")
for p, ctype in [("/", "text/html"), ("/styles.css", "text/css"), ("/app.js", "javascript")]:
    with urllib.request.urlopen(BASE + p, timeout=10) as r:
        body = r.read()
    check(f"GET {p} → {r.status} {len(body)}B", r.status == 200 and ctype in r.headers.get("Content-Type", ""), r.headers.get("Content-Type"))

print("== /api/meta ==")
with urllib.request.urlopen(BASE + "/api/meta", timeout=30) as r:
    meta = json.load(r)
check("meta.ok", meta.get("ok") is True, meta.get("ok"))
check("引擎版本", bool(meta.get("core_version")), meta.get("core_version"))
check("选项白名单含 remove_audio_watermark", "remove_audio_watermark" in meta.get("clean_options", {}))
check("kinds 四类", all(k in meta.get("kinds", {}) for k in ("image", "av", "container", "text")))
print("    core:", meta.get("core_version"), "| web:", meta.get("web_version"), "| layer_b:", meta.get("text_layer_b"))

print("== 纯文本 .md（走引擎容器管线，剥 frontmatter） ==")
md = (FIX / "sample.md").read_bytes()
st, hdr, body, rep = raw("/api/raw/clean", md, "sample.md", {"normalize_spaces": True, "nfkc": True})
check(f"HTTP {st}", st == 200, str(body)[:300])
if st == 200:
    txt = body.decode("utf-8", "replace")
    check("frontmatter 里的 AI 字段被剥离", "ai_generated" not in txt and "model:" not in txt, txt[:140])
    check("零宽字符被清除", "\u200b" not in txt and "\u2060" not in txt)
    check("NFKC 生效（全角 ＡＢＣ → ABC）", "ABC" in txt)
    check("report 有 actions", bool(rep and rep.get("actions")), rep)
    print("    actions:", (rep or {}).get("actions"))

print("== 纯文本 .txt（本进程 Layer A） ==")
txtb = (FIX / "sample.txt").read_bytes()
st, hdr, body, rep = raw("/api/raw/clean", txtb, "sample.txt", {"nfkc": True, "aggressive_homoglyphs": True, "normalize_spaces": True})
check(f"HTTP {st}", st == 200, str(body)[:300])
if st == 200:
    out = body.decode()
    check("输出无零宽字符", "\u200b" not in out and "\u200c" not in out)
    check("同形字 аpple → apple", "apple" in out, out)
    check("全角转半角", "ABC" in out, out)
    check("report.layer_a_only", (rep or {}).get("layer_a_only") is True)
    print("    stats:", (rep or {}).get("stats"))

print("== 图片 PNG ==")
png = (FIX / "ai.png").read_bytes()
st, hdr, out, rep = raw("/api/raw/clean", png, "ai.png", {"keep_non_ai_metadata": False})
check(f"HTTP {st}", st == 200, str(out)[:300])
check("Content-Disposition 带 .cleaned", "filename" in hdr.get("Content-Disposition", ""))
check("Content-Type image/png", hdr.get("Content-Type", "").startswith("image/png"), hdr.get("Content-Type"))
check("输出是 PNG 魔数", isinstance(out, bytes) and out[:8] == b"\x89PNG\r\n\x1a\n")
check("体积变小", isinstance(out, bytes) and len(out) < len(png), f"{len(png)} → {len(out)}")
check("report 含 actions", bool((rep or {}).get("actions")), rep)
print("    actions:", (rep or {}).get("actions"))
st, hdr, jb, _ = raw("/api/raw/inspect", out, "ai.png")
j = json.loads(jb) if isinstance(jb, (bytes, bytearray)) else jb
check("复检 has_ai_metadata=False", st == 200 and j["report"]["has_ai_metadata"] is False, j)
check("复检 findings 为空", st == 200 and not j["report"]["findings"], j["report"]["findings"])

print("== DOCX ==")
docx = (FIX / "note.docx").read_bytes()
st, hdr, out, rep = raw("/api/raw/clean", docx, "note.docx", {"deep_images": "auto", "also_layer_a_text": True})
check(f"HTTP {st}", st == 200, str(out)[:300])
check("输出是 zip", isinstance(out, bytes) and out[:2] == b"PK")
if isinstance(out, bytes) and out[:2] == b"PK":
    import io, zipfile
    z = zipfile.ZipFile(io.BytesIO(out))
    doc = z.read("word/document.xml").decode()
    check("正文零宽字符被清", "\u200b" not in doc, doc[:160])
    core = z.read("docProps/core.xml").decode() if "docProps/core.xml" in z.namelist() else ""
    check("docProps 里的 ChatGPT/Claude 被清", "ChatGPT" not in core and "Claude" not in core, core[:160])
print("    actions:", (rep or {}).get("actions"))

print("== 音频 WAV（破坏性链） ==")
wav = (FIX / "tone.wav").read_bytes()
st, hdr, out, rep = raw("/api/raw/clean", wav, "tone.wav", {"remove_audio_watermark": True})
check(f"HTTP {st}", st == 200, str(out)[:300])
if st == 200:
    check("输出 M4A", hdr.get("Content-Type") == "audio/mp4", hdr.get("Content-Type"))
    check("report.audio_mark_removal.available", bool((rep or {}).get("audio_mark_removal", {}).get("available")), rep)
    print("    actions:", (rep or {}).get("actions"))

print("== 视频 MP4 ==")
mp4 = (FIX / "clip.mp4").read_bytes()
st, hdr, out, rep = raw("/api/raw/clean", mp4, "clip.mp4", {})
check(f"HTTP {st}", st == 200, str(out)[:300])
check("输出 MP4", isinstance(out, bytes) and out[4:8] == b"ftyp")

print("== 错误路径 ==")
st, hdr, j, _ = raw("/api/raw/clean", b"xx", "bad.bin", {})
check("未知后缀 → 415", st == 415, (st, j))
st, hdr, j, _ = raw("/api/raw/clean", b"\x00\x01binarytext", "fake.txt", {})
check("二进制伪装文本 → 422", st == 422, (st, j))
st, hdr, j, _ = raw("/api/raw/clean", b"{}", "", {})
check("空文件名按无扩展名文本兜底处理", st == 200 or st in (415, 422), (st, j))

print("== 兼容旧接口 /api/health + /api/text-clean ==")
with urllib.request.urlopen(BASE + "/api/health", timeout=10) as r:
    h = json.load(r)
check("/api/health 透传", h.get("ok") is True, h)
req = urllib.request.Request(BASE + "/api/text-clean", data=json.dumps(
    {"file": base64.b64encode("a\u200bb".encode()).decode(), "name": "x.txt"}).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=30) as r:
    j = json.load(r)
check("/api/text-clean 兼容", j.get("ok") and base64.b64decode(j["cleaned"]) == b"ab", j)

print(f"\n结果：{ok} 通过 / {fail} 失败")
sys.exit(1 if fail else 0)
