#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
上游变更检查（决定「要不要重新构建」）

背景：你的仓库 fork 自 j4Uq/TVBoxOSC，但 j4Uq 那个仓库只有 283 KB —— 它不含安卓源码，
只是「构建壳」。真正的功能代码在 q215613905/TVBoxOS，构建时实时克隆。
所以「跟进上游」= 盯 q215613905/TVBoxOS 的提交，不是盯 j4Uq。

用法：
  python check_upstream.py                # 对比上次记录的 SHA，列出新提交
  python check_upstream.py --mark         # 把当前最新提交记为「已构建」
  python check_upstream.py --state x.json # 指定状态文件
退出码：0 无更新 / 10 有更新（方便 CI 判定）/ 1 出错
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"
REPO = os.environ.get("UPSTREAM_REPO", "q215613905/TVBoxOS")


def api(path):
    req = urllib.request.Request(
        API + path,
        headers={"User-Agent": "taoying-upstream-check", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "upstream-state.json"))
    ap.add_argument("--mark", action="store_true", help="把当前 HEAD 记为已构建")
    ap.add_argument("--max", type=int, default=20)
    a = ap.parse_args()

    commits = api(f"/repos/{REPO}/commits?per_page={a.max}")
    if not commits:
        print("拿不到提交列表")
        return 1
    head = commits[0]["sha"]
    head_msg = commits[0]["commit"]["message"].splitlines()[0]

    state = {}
    if os.path.exists(a.state):
        try:
            state = json.load(open(a.state, encoding="utf-8"))
        except Exception:
            state = {}
    last = state.get("sha", "")

    if a.mark or not last:
        state.update({
            "sha": head,
            "message": head_msg,
            "marked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        with open(a.state, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        print(f"已记录基线：{head[:8]}  {head_msg}")
        return 0

    if head == last:
        print(f"上游无更新（当前 {head[:8]}  {head_msg}）")
        return 0

    new = []
    for c in commits:
        if c["sha"] == last:
            break
        new.append(c)

    print(f"上游有 {len(new)} 个新提交（基线 {last[:8]} → 最新 {head[:8]}）\n")
    for c in new:
        msg = c["commit"]["message"].splitlines()[0]
        date = c["commit"]["committer"]["date"][:16].replace("T", " ")
        author = (c["commit"]["author"] or {}).get("name", "")[:16]
        print(f"  {c['sha'][:8]}  {date}  {author:16s}  {msg}")

    # 粗筛：标题里带这些词的，大概率是「用户能感知」的改动
    KEY = ("修复", "优化", "新增", "支持", "修改", "调整", "fix", "feat", "add", "improve")
    notable = [c for c in new if any(k in c["commit"]["message"] for k in KEY)]
    print(f"\n其中可能影响体验的 {len(notable)} 个：")
    for c in notable[:8]:
        print("  - " + c["commit"]["message"].splitlines()[0])

    print("\n判定：建议重新构建（构建时会自动跟上最新 main）")
    print("构建后执行  python check_upstream.py --mark  记录基线")
    return 10


if __name__ == "__main__":
    sys.exit(main())
