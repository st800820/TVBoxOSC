#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从抓包得到的超大源池里，给央视 + 31 省级卫视挑出「实测最快」的线路

输入：
  05_工具脚本/iptv-local/deliverables/iptv_all.m3u   （3.2 万条，来自超级直播的配置订阅）
  live/taoying-live.m3u                              （当前在用的源，一起参与比速）

输出：
  live/taoying-pool.txt   精选线路池（每台最多 3 条，按实测 TTFB 排序）
  live/pool-report.md     每个台的候选数 / 可用数 / 最快值

用法：
  python build_pool.py --pool ../../05_工具脚本/iptv-local/deliverables/iptv_all.m3u
"""

import argparse
import os
import re
import ssl
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_live import category, norm_sat, PROV_ORDER, PROV31  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 9) Chrome/101 Mobile Safari/537.36"}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# 每台从大池子里抽多少条去测（越大越准，越慢）
SAMPLE_PER_CHANNEL = 12
# 每台最终保留几条
KEEP_PER_CHANNEL = 3


def parse_m3u(text):
    out, name, group = [], None, ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF"):
            m = line.split(",", 1)
            name = m[-1].strip() if len(m) > 1 else ""
            g = line.find('group-title="')
            group = line[g + 13:line.find('"', g + 13)] if g >= 0 else ""
        elif line.startswith("http") and name:
            out.append((name, group, line))
            name = None
    return out


def probe(url):
    """返回 (ok, ms, kb)"""
    t = time.time()
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=6, context=CTX)
        b = r.read(4000)
        ms = (time.time() - t) * 1000
        ok = r.status == 200 and (b[:7] == b"#EXTM3U" or b[:1] == b"\x47")
        return ok, ms, len(b) // 1024
    except Exception:
        return False, (time.time() - t) * 1000, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="../../05_工具脚本/iptv-local/deliverables/iptv_all.m3u")
    ap.add_argument("--current", default="../../live/taoying-live.m3u")
    ap.add_argument("--outdir", default="../../live")
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args()

    buckets = defaultdict(list)          # norm_key -> [(name, group, url)]
    src_stat = defaultdict(int)

    def add(path, tag):
        if not os.path.exists(path):
            print(f"  跳过（不存在）: {path}")
            return
        items = parse_m3u(open(path, encoding="utf-8", errors="ignore").read())
        n = 0
        for name, group, url in items:
            cat = category(name)
            if cat is None:
                continue
            if cat[1] == "央视":
                # 只要 CCTV1-17 和 CCTV5+，剔除 4K/8K/风云足球等子频道
                mm = re.match(r"CCTV[-\s]*(\d+)(\+)?", name.upper())
                if not mm:
                    continue
                num = int(mm.group(1))
                if num > 17:
                    continue
                key = "CCTV" + str(num) + (mm.group(2) or "")
            else:
                key = norm_sat(name)
            if key in ("东方", "东南"):
                key = "上海" if key == "东方" else "福建"
            buckets[key].append((name, cat[1], url))
            n += 1
        src_stat[tag] = n
        print(f"  {tag}: {len(items)} 条 → 命中央视/卫视 {n} 条")

    print("== 读取源 ==")
    add(a.pool, "抓包大池")
    add(a.current, "当前在用")

    print(f"\n== 频道 {len(buckets)} 个，开始抽样测速（每台最多 {SAMPLE_PER_CHANNEL} 条）==")
    picked = {}
    total_probe = 0
    for key, items in buckets.items():
        # 去重后取前 N 条
        seen, uniq = set(), []
        for it in items:
            if it[2] in seen:
                continue
            seen.add(it[2])
            uniq.append(it)
        picked[key] = uniq[:SAMPLE_PER_CHANNEL]
        total_probe += len(picked[key])
    print(f"  待测 {total_probe} 条，并发 {a.workers}")

    t0 = time.time()
    results = {}
    jobs = [(k, it) for k, lst in picked.items() for it in lst]
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(probe, it[2]): (k, it) for k, it in jobs}
        for f in futs:
            pass
        for f, (k, it) in futs.items():
            ok, ms, kb = f.result()
            if ok:
                results.setdefault(k, []).append((ms, it[0], it[1], it[2]))
    print(f"  测速完成，用时 {time.time()-t0:.0f}s")

    # 排序 + 取前 N
    final = {}
    for k, lst in results.items():
        lst.sort(key=lambda x: x[0])
        final[k] = lst[:KEEP_PER_CHANNEL]

    order = {p: i for i, p in enumerate(PROV_ORDER)}
    ALIAS = {"东方": "上海", "东南": "福建"}

    def sort_key(k):
        if k.startswith("CCTV"):
            m = re.search(r"(\d+)", k)
            return (0, int(m.group(1)) if m else 99)
        return (1, order.get(ALIAS.get(k, k), 99))

    keys = sorted(final.keys(), key=sort_key)
    print(f"\n== 有可用线路的频道 {len(keys)} 个 ==")

    # 统一显示名：CCTV1 → CCTV-1，北京 → 北京卫视
    def disp(k):
        if k.startswith("CCTV"):
            n = k[4:]
            return "CCTV-" + n
        return k + "卫视"

    os.makedirs(a.outdir, exist_ok=True)

    # 输出 txt（TVBox 格式，按分组）
    lines, last = [], None
    for k in keys:
        grp = "央视" if k.startswith("CCTV") else "卫视"
        if grp != last:
            lines.append(f"{grp},#genre#")
            last = grp
        for ms, name, g, url in final[k]:
            lines.append(f"{disp(k)},{url}")

    out_txt = os.path.join(a.outdir, "taoying-pool.txt")
    with open(out_txt, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  写出 {out_txt}（{len(lines)} 行）")

    # 输出 m3u（App 直接读这个）
    m3u = ["#EXTM3U"]
    for k in keys:
        grp = "央视" if k.startswith("CCTV") else "卫视"
        d = disp(k)
        for ms, name, g, url in final[k]:
            m3u.append(f'#EXTINF:-1 tvg-id="{d}" tvg-name="{d}" group-title="{grp}",{d}')
            m3u.append(url)
    out_m3u = os.path.join(a.outdir, "taoying-live.m3u")
    with open(out_m3u, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(m3u) + "\n")
    print(f"  写出 {out_m3u}（{len(m3u)//2} 个频道条目）")

    # 报告
    rep = ["# 精选线路池报告", "",
           f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
           f"- 源：抓包大池 {src_stat.get('抓包大池',0)} 条 + 当前在用 {src_stat.get('当前在用',0)} 条",
           f"- 频道 {len(buckets)} → 有可用线路 {len(keys)}",
           "",
           "| 频道 | 候选 | 可用 | 最快(ms) |", "|---|---|---|---|"]
    for k in keys:
        cand = len(picked.get(k, []))
        ok = len(results.get(k, []))
        rep.append(f"| {k} | {cand} | {ok} | {int(final[k][0][0])} |")
    miss = [p for p in PROV31 if p not in final and p not in ("东方", "东南")]
    if miss:
        rep += ["", f"**无可用线路的省级卫视**：{'、'.join(miss)}"]
    open(os.path.join(a.outdir, "pool-report.md"), "w", encoding="utf-8").write("\n".join(rep) + "\n")
    print(f"  写出 pool-report.md")

    # 覆盖统计
    have_sat = {k for k in keys if not k.startswith("CCTV")}
    print(f"  央视 {len([k for k in keys if k.startswith('CCTV')])} 个 / 卫视 {len(have_sat)} 个")


if __name__ == "__main__":
    sys.exit(main())
