#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
涛影直播源生成器

数据来源：Guovin/iptv-api（25k star，每天自动采集 + 测速筛选）
  官方输出：gd/output/ipv4/result.m3u、gd/output/ipv6/result.m3u、gd/output/epg/epg.gz

本脚本做三件事：
  1. 合并 IPv4 + IPv6 两路结果
  2. 只保留「央视 / CETV / 卫视 / 地方台」，剔除境外与港澳台频道
  3. 同一频道最多保留前 2 条线路（官方已按可用性和速度排序），输出 m3u + txt

用法：
  python make_live.py                    # 直连（GitHub Actions 里用）
  python make_live.py --proxy https://gh.74259136.xyz/   # 本地/大陆环境走代理
"""

import argparse
import os
import re
import sys
import urllib.request

RAW = "https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/"
SRC_IPV4 = RAW + "ipv4/result.m3u"
SRC_IPV6 = RAW + "ipv6/result.m3u"
EPG = "https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/epg/epg.gz"

# 明确排除：境外、港澳台、境外版央视
BLOCK = ("TVBS", "凤凰", "中天", "东森", "三立", "民视", "翡翠", "无线", "NOW", "HOY",
         "VIU", "KBS", "NHK", "MBC", "SBS", "CCTV+", "CGTN", "BBC", "CNN", "DW",
         "ALJAZEERA", "CNBC", "Bloomberg", "美亚", "东森", "华视", "台视", "中视",
         "八大", "龙华", "靖天", "爱尔达", "公视", "客家", "原民")

# 省/直辖市/自治区名，用于识别地方台
PROVINCE = ("北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", "江苏",
            "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西",
            "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏",
            "新疆", "深圳", "厦门", "青岛", "大连", "宁波", "苏州", "无锡", "杭州", "南京",
            "武汉", "成都", "西安", "广州", "济南", "沈阳", "哈尔滨", "长春", "郑州", "长沙",
            "合肥", "福州", "昆明", "贵阳", "兰州", "太原", "石家庄", "南昌", "南宁", "海口")


def fetch(url, proxy="", timeout=60):
    target = (proxy + url) if proxy else url
    req = urllib.request.Request(target, headers={"User-Agent": "taoying-live/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def parse_m3u(text):
    """返回 [(tvg_id, name, logo, group, url)]"""
    out, cur = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF"):
            tvg_id = (re.search(r'tvg-id="([^"]*)"', line) or [None, ""])[1]
            name = (re.search(r'tvg-name="([^"]*)"', line) or [None, ""])[1]
            logo = (re.search(r'tvg-logo="([^"]*)"', line) or [None, ""])[1]
            group = (re.search(r'group-title="([^"]*)"', line) or [None, ""])[1]
            title = line.split(",")[-1].strip()
            cur = (tvg_id or title, name or title, logo, group)
        elif line.startswith("http") and cur:
            out.append(cur + (line,))
            cur = None
    return out


def keep(name, group):
    up = name.upper()
    if any(b in up for b in (b.upper() for b in BLOCK)):
        return False
    if "更新时间" in group or "更新时间" in name:
        return False
    if re.search(r"CCTV-?\d|CCTV-?5\+|CETV", up):
        return True
    if "卫视" in name:
        return True
    if any(p in name for p in PROVINCE):
        return True
    if any(k in name for k in ("新闻综合", "公共频道", "都市", "影视", "生活", "经济", "科教",
                               "少儿", "体育", "文艺", "纪实", "法制", "农业", "综合")):
        return True
    return False


def cctv_rank(name):
    m = re.search(r"CCTV-?\s*(\d+)(\+)?", name.upper())
    if m:
        return (0, int(m.group(1)), 1 if m.group(2) else 0)
    if "CETV" in name.upper():
        return (1, 0, 0)
    if "卫视" in name:
        return (2, 0, 0)
    return (3, 0, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy", default="")
    ap.add_argument("--outdir", default="live")
    ap.add_argument("--per-channel", type=int, default=2)
    ap.add_argument("--epg-proxy", action="store_true", help="EPG 地址也套代理（给客户端用）")
    a = ap.parse_args()

    items = []
    for label, url in (("ipv4", SRC_IPV4), ("ipv6", SRC_IPV6)):
        try:
            txt = fetch(url, a.proxy)
            got = parse_m3u(txt)
            print(f"{label}: {len(got)} 条")
            items += got
        except Exception as e:
            print(f"{label}: 拉取失败 {e}")

    if not items:
        print("没有拿到任何源，中止")
        return 1

    # 去重 + 过滤 + 每频道限量
    seen_urls = set()
    per = {}
    kept = []
    for tvg_id, name, logo, group, url in items:
        if not keep(name, group):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        key = tvg_id or name
        if per.get(key, 0) >= a.per_channel:
            continue
        per[key] = per.get(key, 0) + 1
        kept.append((tvg_id, name, logo, group, url))

    kept.sort(key=lambda x: (cctv_rank(x[1]), x[1]))
    print(f"过滤后: {len(kept)} 条 / {len(per)} 个频道")

    os.makedirs(a.outdir, exist_ok=True)
    epg_url = (a.proxy + EPG) if (a.proxy and a.epg_proxy) else EPG

    m3u = [f'#EXTM3U x-tvg-url="{epg_url}"']
    for tvg_id, name, logo, group, url in kept:
        g = group if group and "更新时间" not in group else "直播"
        m3u.append(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{tvg_id}" tvg-logo="{logo}" group-title="{g}",{name}')
        m3u.append(url)
    m3u_path = os.path.join(a.outdir, "taoying-live.m3u")
    with open(m3u_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(m3u) + "\n")

    # TVBox txt 格式：分组,#genre# 然后 频道名,url
    lines, last_group = [], None
    for tvg_id, name, logo, group, url in kept:
        g = group if group and "更新时间" not in group else "直播"
        if g != last_group:
            lines.append(f"{g},#genre#")
            last_group = g
        lines.append(f"{name},{url}")
    txt_path = os.path.join(a.outdir, "taoying-live.txt")
    with open(txt_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    print(f"输出: {m3u_path} ({os.path.getsize(m3u_path)//1024} KB), {txt_path} ({os.path.getsize(txt_path)//1024} KB)")
    from collections import Counter
    c = Counter()
    for _i, n, _l, _g, _u in kept:
        c[cctv_rank(n)[0]] += 1
    print(f"央视 {c[0]} / CETV {c[1]} / 卫视 {c[2]} / 地方 {c[3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
