#!/usr/bin/env python3
"""_split_clean_response 的边界用例（直接 import 本地 server.py）。"""
import base64
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "wm_server", Path(__file__).resolve().parents[1] / "server.py")
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)

ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label}  {extra}")


def parse(payload: bytes):
    d = Path(tempfile.mkdtemp())
    src = d / "resp.json"
    src.write_bytes(payload)
    out = d / "out.bin"
    path, report = srv._split_clean_response(src, out)
    return path.read_bytes(), report


print("== 常规 ==")
raw = b"hello world"
body = json.dumps({"ok": True, "kind": "image",
                   "cleaned": base64.b64encode(raw).decode(),
                   "report": {"actions": ["drop chunk tEXt"], "bytes_in": 11}}).encode()
data, rep = parse(body)
check("内容一致", data == raw, data[:40])
check("report 取到", rep.get("actions") == ["drop chunk tEXt"], rep)

print("== 空 cleaned ==")
body = json.dumps({"ok": True, "kind": "text", "cleaned": "",
                   "report": {"stats": {"removed_count": 0}}}).encode()
data, rep = parse(body)
check("内容为空", data == b"", data)
check("report 仍取到", rep.get("stats", {}).get("removed_count") == 0, rep)

print("== report 里含 cleaned 字样与引号 ==")
body = json.dumps({"ok": True, "kind": "text", "cleaned": base64.b64encode(b"xy").decode(),
                   "report": {"actions": ['he said "cleaned" and \'quoted\'',
                                          "drop chunk tEXt"]}}).encode()
data, rep = parse(body)
check("内容正确", data == b"xy", data)
check("report 完整", len(rep.get("actions", [])) == 2, rep)

print("== base64 带 padding ==")
raw = b"a" * 100
body = json.dumps({"ok": True, "kind": "image", "cleaned": base64.b64encode(raw).decode(),
                   "report": {"bytes_out": 100}}).encode()
data, rep = parse(body)
check("长度一致", len(data) == 100, len(data))
check("内容一致", data == raw)

print("== 报告里含非 ASCII ==")
body = json.dumps({"ok": True, "kind": "text", "cleaned": base64.b64encode(b"x").decode(),
                   "report": {"actions": ["移除 frontmatter key: ai_generated"]}},
                  ensure_ascii=False).encode()
data, rep = parse(body)
check("中文动作保真", rep.get("actions", [""])[0].startswith("移除"), rep)

print("== 字段顺序被换（report 在前）==")
body = (b'{"report": {"actions": ["x"]}, "cleaned": "'
        + base64.b64encode(b"z") + b'", "ok": true}')
try:
    data, rep = parse(body)
    print("    解析结果:", data[:20], rep)
    check("仍能正确取到内容", data == b"z", data[:20])
    check("仍能正确取到 report", rep.get("actions") == ["x"], rep)
except Exception as e:
    check("顺序变化时抛错（可控）", isinstance(e, srv.UpstreamError), repr(e))

print(f"\n结果：{ok} 通过 / {fail} 失败")
sys.exit(1 if fail else 0)
