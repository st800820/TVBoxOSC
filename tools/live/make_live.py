#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
涛影直播源生成器

数据来源：Guovin/iptv-api（每天自动采集 + 测速筛选）
  官方输出：gd/output/ipv4/result.m3u、gd/output/ipv6/result.m3u

本脚本做四件事：
  1. 合并 IPv4 + IPv6 两路结果，**IPv6 线路排在前面**（支持的网络上更快）
  2. 只保留「央视」+「31 个省级卫视」，体育/电影/地方城市台全部剔除
  3. 同一频道保留前 N 条线路（默认 3：2 条 v6 + 1 条 v4 兜底）
  4. 不写 x-tvg-url —— 让 App 用自带的 51zmt 按频道接口（每次几 KB，
     而不是每个台都去下 922KB 的全量 xmltv）

用法：
  python make_live.py                                      # 直连（Actions 里用）
  python make_live.py --proxy https://gh.74259136.xyz/     # 大陆环境走代理
"""

import argparse
import os
import re
import sys
import urllib.request

RAW = "https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/"
SRC_IPV4 = RAW + "ipv4/result.m3u"
SRC_IPV6 = RAW + "ipv6/result.m3u"

# 明确排除：境外、港澳台、境外版央视
BLOCK = ("TVBS", "凤凰", "中天", "东森", "三立", "民视", "翡翠", "无线", "NOW", "HOY",
         "VIU", "KBS", "NHK", "MBC", "SBS", "CCTV+", "CGTN", "BBC", "CNN", "DW",
         "ALJAZEERA", "CNBC", "BLOOMBERG", "美亚", "华视", "台视", "中视",
         "八大", "龙华", "靖天", "爱尔达", "公视", "客家", "原民", "香港", "澳门")

# 31 个省级卫视（含别名：上海=东方卫视，福建=东南卫视）
# 省级卫视之外的一律剔除：深圳/厦门/延边/兵团/三沙/康巴/安多/南方/嘉佳卡通 等
SATELLITE = {
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
    "上海", "东方", "江苏", "浙江", "安徽", "福建", "东南", "江西", "山东",
    "河南", "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州",
    "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
}

# 卫视排序按行政区划习惯顺序
PROV_ORDER = ["北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
              "上海", "东方", "江苏", "浙江", "安徽", "福建", "东南", "江西", "山东",
              "河南", "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州",
              "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆"]


# 31 个省级（东方=上海，东南=福建 合并计一个）
PROV31 = [p for p in PROV_ORDER if p not in ("东方", "东南")]


def fetch(url, proxy="", timeout=60):
    target = (proxy + url) if proxy else url
    req = urllib.request.Request(target, headers={"User-Agent": "taoying-live/2.0"})
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


def norm_sat(name):
    """把「湖南卫视高清」之类归一成「湖南」"""
    n = re.sub(r"[（(].*?[)）]", "", name)
    n = re.sub(r"(高清|标清|超清|蓝光|4K|8K|FHD|UHD|HD|SD)", "", n, flags=re.I)
    n = re.sub(r"[\s\-_·|/]+", "", n)
    return n.replace("卫视", "").replace("频道", "")


def category(name):
    """只返回 (0,'央视') 或 (1,'卫视')，其余 None"""
    up = name.upper()
    if any(b in up for b in BLOCK):
        return None
    if re.search(r"CCTV-?\s*\d", up):
        return (0, "央视")
    if "卫视" in name and norm_sat(name) in SATELLITE:
        return (1, "卫视")
    return None


def channel_key(name):
    """频道归一键。
    同一个台在 IPv4 / IPv6 两个输出里的 tvg-id 和写法并不一致
    （CCTV-1 / CCTV1 / CCTV-1综合），不归一就会各成一组、每组只剩一条线路。"""
    if category(name) is None:
        return name
    s = re.sub(r"[（(].*?[)）]", "", name.upper())
    s = re.sub(r"[\s\-_·|/]+", "", s)
    m = re.match(r"CCTV(\d+)(\+)?", s)
    if m:
        return "CCTV" + m.group(1) + (m.group(2) or "")
    if category(name)[0] == 1:
        return "SAT_" + norm_sat(name)
    return s


def sort_key(name):
    cat = category(name)
    if cat and cat[0] == 0:
        m = re.search(r"CCTV-?\s*(\d+)", name.upper())
        return (0, int(m.group(1)) if m else 99, name)
    if cat and cat[0] == 1:
        n = norm_sat(name)
        idx = PROV_ORDER.index(n) if n in PROV_ORDER else 99
        return (1, idx, name)
    return (9, 99, name)


def is_ipv6_url(url):
    """URL 里是不是真正的 IPv6 字面地址（http://[2409:...]）。
    注意：Guovin 的 ipv6 榜单里大部分其实是普通域名，不能按来源判断。"""
    return bool(re.match(r"^https?://\[", url or "", re.I))


def line_score(url, from_v6_list):
    """线路排序：真 IPv6 地址 > ipv4 榜单（已验证最快） > ipv6 榜单里的域名源。
    安全性有兜底：LivePlayActivity 连接超时 3.5–10 秒会自动换下一条线路。"""
    if is_ipv6_url(url):
        return 0
    return 1 if not from_v6_list else 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy", default="")
    ap.add_argument("--outdir", default="live")
    ap.add_argument("--per-channel", type=int, default=3, help="每频道最多几条线路（v6 优先）")
    ap.add_argument("--epg-proxy", action="store_true", help="兼容旧参数，已不使用")
    a = ap.parse_args()

    # 每条记录末尾加 is_v6 标记
    items = []
    for label, url in (("ipv4", SRC_IPV4), ("ipv6", SRC_IPV6)):
        try:
            txt = fetch(url, a.proxy)
            got = parse_m3u(txt)
            v6 = (label == "ipv6")
            items += [g + (v6,) for g in got]
            print(f"{label}: {len(got)} 条")
        except Exception as e:
            print(f"{label}: 拉取失败 {e}")

    if not items:
        print("没有拿到任何源，中止")
        return 1

    # 按归一化频道名聚合，IPv6 线路排前面
    buckets = {}
    for tvg_id, name, logo, group, url, is_v6 in items:
        if category(name) is None:
            continue
        buckets.setdefault(channel_key(name), []).append((tvg_id, name, logo, group, url, is_v6))

    kept, seen_urls = [], set()
    for key, lst in buckets.items():
        lst.sort(key=lambda x: line_score(x[4], x[5]))
        picked = 0
        for it in lst:
            if picked >= a.per_channel:
                break
            if it[4] in seen_urls:
                continue
            seen_urls.add(it[4])
            kept.append(it)
            picked += 1

    kept.sort(key=lambda x: sort_key(x[1]))
    v6_cnt = sum(1 for x in kept if is_ipv6_url(x[4]))
    print(f"过滤后: {len(kept)} 条 / {len(buckets)} 个频道"
          f"（其中真正的 IPv6 地址线路 {v6_cnt} 条）")

    os.makedirs(a.outdir, exist_ok=True)

    # 注意：故意不写 x-tvg-url。
    # 一旦写了，ApiConfig 会把它存进 EPG_URL，LivePlayActivity 就会去下整份 xmltv
    # （e.xml.gz 约 922KB，且带 ?ch= 参数依然返回全量），每次切台都白拉一遍。
    # 留空则走 DEFAULT_EPG_ADDRESS = 51zmt 的 /api/diyp/?ch={name}&date={date}，
    # 每次只有几 KB，数据源和超级直播是同一家。
    m3u = ["#EXTM3U"]
    for tvg_id, name, logo, group, url, is_v6 in kept:
        g = category(name)[1]
        m3u.append(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{tvg_id}" tvg-logo="{logo}" group-title="{g}",{name}')
        m3u.append(url)
    m3u_path = os.path.join(a.outdir, "taoying-live.m3u")
    with open(m3u_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(m3u) + "\n")

    # TVBox txt 格式：分组,#genre# 然后 频道名,url
    lines, last_group = [], None
    for tvg_id, name, logo, group, url, is_v6 in kept:
        g = category(name)[1]
        if g != last_group:
            lines.append(f"{g},#genre#")
            last_group = g
        lines.append(f"{name},{url}")
    txt_path = os.path.join(a.outdir, "taoying-live.txt")
    with open(txt_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    print(f"输出: {m3u_path} ({os.path.getsize(m3u_path)//1024} KB), "
          f"{txt_path} ({os.path.getsize(txt_path)//1024} KB)")
    from collections import Counter
    c = Counter()
    for _i, n, _l, _g, _u, _v in kept:
        c[category(n)[1]] += 1
    print(" / ".join(f"{k} {v}" for k, v in c.items()))

    # 卫视覆盖检查（31 个省级；东方=上海，东南=福建 合并计一个）
    ALIAS = {"东方": "上海", "东南": "福建"}
    have = {ALIAS.get(norm_sat(n), norm_sat(n))
            for _i, n, _l, _g, _u, _v in kept if category(n)[1] == "卫视"}
    PROV31 = [p for p in PROV_ORDER if p not in ("东方", "东南")]
    missing = [p for p in PROV31 if p not in have]
    if missing:
        print(f"省级卫视覆盖 {len(PROV31) - len(missing)}/{len(PROV31)}，缺:", " ".join(missing))
    else:
        print(f"省级卫视覆盖: {len(PROV31)}/{len(PROV31)} 全齐")
    return 0


if __name__ == "__main__":
    sys.exit(main())
