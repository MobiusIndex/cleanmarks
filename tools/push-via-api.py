#!/usr/bin/env python3
"""用 GitHub 的 Git Data API 推送本地提交（当 `git push` 过不了代理时用）。

为什么不用 `git push`：这台机器上 git 的 HTTP 栈过代理会卡死（CONNECT 要 20–30 秒，
之后 POST 阶段无限等待），而 `api.github.com` 走同一个代理很快。所以改成用 API 把
本地提交原样写上去——blob 是内容寻址的，推完两边 SHA 完全一致。

    python tools/push-via-api.py                # 推到当前分支（新分支会自动创建）
    python tools/push-via-api.py --to main      # 推到 main
    python tools/push-via-api.py --ff-main      # 推到当前分支，并把 main 快进到同一个提交
    python tools/push-via-api.py --tag v2.0.1   # 顺便在提交上打一个 tag

需要：`~/.git-credentials` 里有一条可用的 github.com 凭据；环境变量
`HTTPS_PROXY`（默认 http://127.0.0.1:7890）能连通 api.github.com。
"""
from __future__ import annotations

import argparse
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
    ap = argparse.ArgumentParser(description="用 Git Data API 推送本地 HEAD")
    ap.add_argument("--to", help="目标分支（默认当前分支）")
    ap.add_argument("--ff-main", action="store_true", help="推送分支后把 main 快进到同一提交")
    ap.add_argument("--tag", help="在本次提交上打一个 tag")
    args = ap.parse_args()

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
    branch = args.to or runstr("rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        print("当前不在任何分支上（detached HEAD），用 --to 指定分支")
        return 1
    message = runstr("log", "-1", "--pretty=%B").rstrip()
    author = runstr("log", "-1", "--pretty=%an%x00%ae%x00%aI").split("\x00")
    committer = runstr("log", "-1", "--pretty=%cn%x00%ce%x00%cI").split("\x00")

    # 父提交：优先用目标分支的远端 tip；新分支则从 main 分叉
    st, ref = api(f"/git/ref/heads/{branch}")
    parent = ref["object"]["sha"] if st == 200 else None
    if parent is None:
        st_main, main_ref = api("/git/ref/heads/main")
        parent = main_ref["object"]["sha"] if st_main == 200 else None
        print(f"新分支 {branch}，从 main 的 {parent[:7] if parent else '(空仓库)'} 分叉")
    if parent == head:
        print(f"远端 {branch} 已经是这个提交，无需推送:", head[:7])
        return 0

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
    print(f"已上传 {len(tree_items)} 个 blob")

    st, tree = api("/git/trees", "POST", {"tree": tree_items})
    if st not in (200, 201):
        print("建 tree 失败:", st, tree.get("message"))
        return 1

    parents = [parent] if parent else []
    st, commit = api("/git/commits", "POST", {
        "message": message, "tree": tree["sha"], "parents": parents,
        "author": {"name": author[0], "email": author[1], "date": author[2]},
        "committer": {"name": committer[0], "email": committer[1], "date": committer[2]}})
    if st not in (200, 201):
        print("建 commit 失败:", st, commit.get("message"))
        return 1
    sha = commit["sha"]

    # 分支：存在就 PATCH（只允许快进），不存在就新建
    if st == 200:
        st2, upd = api(f"/git/refs/heads/{branch}", "PATCH", {"sha": sha, "force": False})
    else:
        st2, upd = api("/git/refs", "POST", {"ref": f"refs/heads/{branch}", "sha": sha})
    if st2 not in (200, 201):
        print(f"更新分支 {branch} 失败:", st2, upd.get("message"))
        return 1
    print(f"已推送 {head[:7]} → 分支 {branch} ({sha[:7]})")

    if args.ff_main and branch != "main":
        st3, mg = api("/git/refs/heads/main", "PATCH", {"sha": sha, "force": False})
        if st3 in (200, 201):
            print(f"main 已快进到 {sha[:7]}")
        else:
            print(f"main 快进失败（可能不是快进）:", st3, mg.get("message"))
            return 1

    if args.tag:
        st4, tg = api("/git/refs", "POST", {"ref": f"refs/tags/{args.tag}", "sha": sha})
        print(f"tag {args.tag}:", st4, tg.get("message", "ok"))

    print(f"https://github.com/{owner}/{name}/commit/{sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
