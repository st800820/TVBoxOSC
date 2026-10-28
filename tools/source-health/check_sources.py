#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
涛影订阅源健康巡检

用途：定期判断「当前内置源还能不能用」，为换源/发版提供依据。

检测维度（客观、可自动化）：
  1. 配置本身：能否拉取、能否解析、站点/直播/解析数量
  2. spider jar：配置里 spider 字段指向的 jar 是否 200、大小是否正常
  3. 直播源：每个 lives[].url 能否拉到、里面能解析出多少个频道
  4. 解析接口：parses[] 里的 jx 地址是否还活着（只测域名可达，不测能否解出视频）
  5. 站点：type 为 0/1 且 api 直接是 http 的站点直接测；csp_xxx 这类内置爬虫无法脱离 App 测，只统计数量

用法：
  python check_sources.py                          # 用自带 0821.json 备份
  python check_sources.py --config https://...json # 指定线上配置
  python check_sources.py --json out.json          # 输出机器可读结果，供 CI 判定
退出码：0 健康；1 有严重问题（关键配置拉不到 / 直播全挂）
"""

import argparse
import json
import os
import re
import ssl
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import urllib.request

UA = "Mozilla/5.0 (Linux; Android 9) AppleWebKit/537.36 Chrome/101 Mobile Safari/537.36"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
TIMEOUT = 12


def get(url, limit=200_000):
    """返回 (状态码, 字节数, 正文前 limit 字节, 耗时秒)。失败返回 (0, 0, b'', 耗时)。"""
    t = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as r:
            data = r.read(limit)
            return r.status, len(data), data, time.time() - t
    except Exception:
        return 0, 0, b"", time.time() - t


def resolve(base, rel):
    if not rel:
        return rel
    if rel.startswith("http://") or rel.startswith("https://"):
        return rel
    if base and rel.startswith("./"):
        return base.rsplit("/", 1)[0] + "/" + rel[2:]
    return rel


def check_live(item, base):
    url = resolve(base, item.get("url", ""))
    code, size, body, dt = get(url)
    channels = 0
    if code == 200 and body:
        text = body.decode("utf-8", "ignore")
        channels = len(re.findall(r"#EXTINF", text))
        if channels == 0 and "\n" in text and "," in text:
            # 纯 txt 格式（频道名,url）粗略计数
            channels = len([l for l in text.splitlines() if l.count(",") >= 1 and not l.startswith("#")])
    hint = ""
    if code == 200 and channels == 0 and body:
        hint = body[:60].decode("utf-8", "ignore").replace("\n", " ")[:60]
    return {
        "name": item.get("name", ""),
        "url": url,
        "code": code,
        "channels": channels,
        "hint": hint,
        "sec": round(dt, 2),
        "ok": code == 200 and channels > 0,
    }


def check_parse(item):
    url = item.get("url", "")
    if not url or url == "Demo" or not url.startswith("http"):
        return {"name": item.get("name", ""), "url": url, "code": -1, "note": "内置/不适用", "ok": None}
    # 只探域名存活：请求根路径，返回任何 <500 都算活着
    root = "/".join(url.split("/")[:3]) + "/"
    code, _size, _body, dt = get(root)
    return {"name": item.get("name", ""), "url": url, "code": code, "sec": round(dt, 2), "ok": code != 0}


def check_site(item):
    api = str(item.get("api", ""))
    if api.startswith("csp_"):
        return None  # 内置爬虫，无法脱离 App 测
    if not api.startswith("http"):
        return None
    code, _s, _b, dt = get(api)
    return {"key": item.get("key", ""), "name": item.get("name", ""), "api": api[:60], "code": code,
            "sec": round(dt, 2), "ok": code == 200}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="")
    ap.add_argument("--base", default="https://gh-proxy.com/https://raw.githubusercontent.com/gaotianliuyun/gao/master/0821.json",
                    help="本地模式下用于解析相对路径的配置地址")
    ap.add_argument("--json", default="")
    ap.add_argument("--workers", type=int, default=10)
    a = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    local = os.path.join(here, "..", "..", "04_源码与参考", "订阅源备份", "0821.json")
    src = a.config

    if src and os.path.exists(src):
        # 支持直接指本地文件（CI 里用仓库内的 taoying/config.json，避免依赖外网）
        cfg = json.load(open(src, encoding="utf-8"))
        base = a.base
        print(f"配置来源：本地文件 {src}")
    elif src:
        code, size, body, dt = get(src, 4_000_000)
        if code != 200:
            print(f"[FATAL] 配置拉不到：{src}（HTTP {code}）")
            return 1
        cfg = json.loads(body.decode("utf-8", "ignore"))
        base = src
        print(f"配置来源：{src}")
        print(f"  拉取 {code} {size/1024:.1f} KB {dt:.2f}s")
    else:
        cfg = json.load(open(local, encoding="utf-8"))
        base = a.base
        print(f"配置来源：本地备份 {os.path.normpath(local)}（未联网校验配置本身）")

    sites = cfg.get("sites") or []
    lives = cfg.get("lives") or []
    parses = cfg.get("parses") or []
    spider_raw = cfg.get("spider") or ""
    spider = resolve(base if not src else src, spider_raw.split(";")[0])

    print(f"\n结构：sites {len(sites)} / lives {len(lives)} / parses {len(parses)}")

    # 1) spider jar
    print("\n=== spider jar ===")
    if spider:
        scode, ssize, _b, sdt = get(spider)
        print(f"  {spider[:90]}")
        print(f"  -> HTTP {scode}  {ssize/1024:.0f} KB  {sdt:.2f}s  {'OK' if scode == 200 and ssize > 10_000 else '异常'}")
    else:
        print("  配置里没有 spider 字段")

    # 2) 直播源
    print("\n=== 直播源 ===")
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        live_res = list(ex.map(lambda x: check_live(x, base or ""), lives))
    for r in sorted(live_res, key=lambda x: (not x["ok"], x["name"])):
        flag = "OK  " if r["ok"] else "挂  "
        extra = ("  <- " + r.get("hint", "")) if r.get("hint") else ""
        print(f"  {flag} {r['name'][:18]:20s} 频道 {r['channels']:4d}  HTTP {r['code']:3d}  {r['sec']:5.1f}s  {r['url'][:58]}{extra}")
    live_ok = sum(1 for r in live_res if r["ok"])

    # 3) 解析接口
    print("\n=== 解析接口 ===")
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        parse_res = list(ex.map(check_parse, parses))
    for r in parse_res:
        if r["ok"] is None:
            print(f"  --   {r['name'][:16]:18s} {r['note']}")
        else:
            print(f"  {'OK  ' if r['ok'] else '挂  '} {r['name'][:16]:18s} HTTP {r['code']:3d}  {r.get('sec', 0):5.1f}s  {r['url'][:55]}")
    parse_ok = sum(1 for r in parse_res if r["ok"] is True)
    parse_total = sum(1 for r in parse_res if r["ok"] is not None)

    # 4) 可直测的站点
    print("\n=== 站点（仅 type=0/1 的直连接口，csp 内置爬虫无法脱离 App 测）===")
    direct = [s for s in sites if str(s.get("api", "")).startswith("http")]
    csp = len(sites) - len(direct)
    print(f"  内置爬虫站点 {csp} 个（需真机验证）；直连接口 {len(direct)} 个")
    if direct:
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            site_res = [r for r in ex.map(check_site, direct) if r]
        for r in site_res:
            print(f"  {'OK  ' if r['ok'] else '挂  '} {r['name'][:16]:18s} HTTP {r['code']:3d}  {r['sec']:5.1f}s")
        site_ok = sum(1 for r in site_res if r["ok"])
    else:
        site_res, site_ok = [], 0

    # 5) 结论
    print("\n=== 结论 ===")
    print(f"  直播 {live_ok}/{len(lives)} 可用 | 解析 {parse_ok}/{parse_total} 可用 | 直连站点 {site_ok}/{len(site_res)} 可用")
    healthy = True
    if lives and live_ok == 0:
        print("  [严重] 直播源全部失效 → 需要换源")
        healthy = False
    elif lives and live_ok < max(2, len(lives) // 3):
        print("  [严重] 直播源可用不足 1/3 → 必须补源或换源")
        healthy = False
    elif lives and live_ok < len(lives) * 2 // 3:
        print("  [警告] 直播源可用数量偏少（<2/3）→ 建议补备用源")
    if parse_total and parse_ok == 0:
        print("  [严重] 解析接口全部失效 → 视频解析会失败")
        healthy = False

    if a.json:
        out = {
            "config": src or "local",
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "sites": {"total": len(sites), "csp": csp, "direct": len(site_res), "direct_ok": site_ok},
            "lives": {"total": len(lives), "ok": live_ok, "detail": live_res},
            "parses": {"total": parse_total, "ok": parse_ok, "detail": parse_res},
            "healthy": healthy,
        }
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"  结果已写入 {a.json}")

    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
