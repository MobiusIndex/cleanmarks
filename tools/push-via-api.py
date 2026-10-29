#!/usr/bin/env python3
"""用 GitHub 的 Git Data API 推送本地 HEAD（当 `git push` 过不了代理时用）。

背景：这台机器上 `git push` / `git ls-remote` 走 HTTP 代理会卡死（CONNECT 要 20–30 秒，
之后 POST 阶段无限等待），而 `api.github.com` 走同一个代理很快。所以改成用 API
把本地提交原样写上去——blob 是内容寻址的，推完两边 SHA 完全一致。

用法（在仓库根目录）：

    python tools/push-via-api.py

需要：`~/.git-credentials` 里有一条可用的 github.com 凭据；环境变量
`HTTPS_PROXY`（默认 http://127.0.0.1:7890）能连通 api.github.com。
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or "http://127.0.0.1:7890"


def run(*args: str) -> bytes:
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def runstr(*args: str) -> str:
    return run(*args).decode().strip()


def main() -> int:
    remote = runstr("remote", "get-url", "origin")
    m = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?$", remote)
    if not m:
        print("origin 不是 github 地址:", remote)
        return 1
    owner, name = m.group(1), m.group(2)

    cred = Path.home() / ".git-credentials"
    tok_m = re.search(r"https://[^:]+:([^@]+)@github\.com", cred.read_text())
    if not tok_m:
        print("~/.git-credentials 里没有 github.com 凭据")
        return 1
    token = tok_m.group(1)

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))

    def api(path: str, method: str = "GET", body: dict | None = None):
        req = urllib.request.Request(
            f"https://api.github.com/repos/{owner}/{name}" + path, method=method,
            data=json.dumps(body).encode() if body else None,
            headers={"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "Content-Type": "application/json"})
        try:
            with opener.open(req, timeout=90) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    head = runstr("rev-parse", "HEAD")
    message = runstr("log", "-1", "--pretty=%B").rstrip()
    author = runstr("log", "-1", "--pretty=%an%x00%ae%x00%aI").split("\x00")
    committer = runstr("log", "-1", "--pretty=%cn%x00%ce%x00%cI").split("\x00")

    st, refs = api("/git/ref/heads/main")
    parent = None
    if st == 200:
        parent = refs["object"]["sha"]
        if parent == head:
            print("远端已经是这个提交，无需推送:", head[:7])
            return 0
    else:
        # 空仓库不接受 POST /git/blobs（409），先建一个初始提交当父提交
        st, boot = api("/contents/README.md", "PUT", {
            "message": "chore: 初始化仓库",
            "content": base64.b64encode(b"# init").decode()})
        if st not in (200, 201):
            print("初始化失败:", st, boot.get("message"))
            return 1
        parent = boot["commit"]["sha"]

    tree_items = []
    for line in run("ls-tree", "-r", "-z", head).split(b"\x00"):
        if not line:
            continue
        meta, path = line.split(b"\t", 1)
        mode, _kind, sha = meta.decode().split()
        blob = run("cat-file", "blob", sha)
        st, res = api("/git/blobs", "POST", {
            "content": base64.b64encode(blob).decode("ascii"), "encoding": "base64"})
        if st not in (200, 201):
            print("blob 失败", path.decode(), st, res.get("message"))
            return 1
        tree_items.append({"path": path.decode("utf-8"), "mode": mode,
                           "type": "blob", "sha": res["sha"]})
        print("  ok", path.decode("utf-8"))

    st, tree = api("/git/trees", "POST", {"tree": tree_items})
    if st not in (200, 201):
        print("建 tree 失败:", st, tree.get("message"))
        return 1
    st, commit = api("/git/commits", "POST", {
        "message": message, "tree": tree["sha"], "parents": [parent],
        "author": {"name": author[0], "email": author[1], "date": author[2]},
        "committer": {"name": committer[0], "email": committer[1], "date": committer[2]}})
    if st not in (200, 201):
        print("建 commit 失败:", st, commit.get("message"))
        return 1
    st, upd = api("/git/refs/heads/main", "PATCH", {"sha": commit["sha"], "force": False})
    if st not in (200, 201):
        print("更新 main 失败:", st, upd.get("message"))
        return 1
    print(f"已推送 {head[:7]} → https://github.com/{owner}/{name}/commit/{commit['sha']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
