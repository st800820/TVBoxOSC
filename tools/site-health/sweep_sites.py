#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
涛影点播站点巡检 + 自动剔除

目的：不需要人工逐个点，靠多层探测判断哪些点播站点已死，把死站从
taoying/config.json 里剔除（移到 sites_parked，可一键恢复）。

判定分层（证据由弱到强）：
  L1 引擎层   spider jar / drpy 引擎 js 是否可达；挂了则相关站点全废
  L2 ext 层   site.ext 指向的配置文件是否 404 / 空 / 返回错误页
  L3 域名层   从 ext 内容里抽出真实源站域名，全部不可达 → 站点必死
  L4 搜索层   能抽出苹果CMS 接口的，直接真实搜一次（等于在 App 里点搜索）

剔除策略（保守，避免误杀）：
  - 只有 strong 级失败才计数；weak 只记录不计数
  - 连续 FAIL_STREAK 次（默认 3）失败才剔除
  - 站点数不低于 MIN_SITES（默认 45）
  - 剔除的对象完整搬到 sites_parked，恢复只需移回 sites

用法：
  python sweep_sites.py                     # 只体检，出报告，不改配置
  python sweep_sites.py --apply             # 体检后按规则剔除并写回
  python sweep_sites.py --apply --streak 2  # 自定义连续失败次数
  python sweep_sites.py --restore 豆豆      # 从 parked 恢复到 sites
  python sweep_sites.py --list-parked       # 看被剔除的站点
"""
import argparse
import json
import os
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

UA = "Mozilla/5.0 (Linux; Android 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.41 Mobile Safari/537.36"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# 不是源站的公共域名，探测它们没有意义
COMMON_HOSTS = {
    "github.com", "raw.githubusercontent.com", "gist.githubusercontent.com",
    "notabug.org", "gitee.com", "jsdelivr.net", "unpkg.com", "npmjs.com",
    "googleapis.com", "gstatic.com", "google.com", "bing.com",
    "cloudflare.com", "cloudflare-dns.com", "dns.google",
    "baidu.com", "bdstatic.com", "qq.com", "gtimg.com", "aliyun.com",
    "alicdn.com", "taobao.com", "tmall.com", "bilibili.com", "hdslb.com",
    "douban.com", "doubanio.com", "w3.org", "schema.org",
    "gh-proxy.com", "ghproxy.net", "gh.74259136.xyz",
}

OK, WEAK, STRONG, UNKNOWN = "ok", "weak", "strong", "unknown"

# 这些站点对未登录/非浏览器请求一律返回 404（防爬），离线无法区分"文件没了"和"被拦"，
# 因此它们的结果只做参考，绝不作为剔除依据。
UNVERIFIABLE = ("notabug.org",)


def now_cn():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def is_common(host):
    h = host.lower()
    return any(h == c or h.endswith("." + c) for c in COMMON_HOSTS)


def enc_url(url):
    """中文/空格路径必须先百分号编码，否则 urllib 在构造请求行时会抛 ascii 编码错"""
    try:
        return urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")
    except Exception:
        return url


def http_get(url, timeout=12, limit=200_000):
    req = urllib.request.Request(enc_url(url), headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.status, r.read(limit)


def http_ok(url, timeout=10):
    """只关心能不能拿到 200 和一点内容"""
    t = time.time()
    try:
        st, body = http_get(url, timeout=timeout, limit=4096)
        return st == 200 and len(body) > 0, round(time.time() - t, 2), ""
    except urllib.error.HTTPError as e:
        return False, round(time.time() - t, 2), f"HTTP {e.code}"
    except Exception as e:
        return False, round(time.time() - t, 2), type(e).__name__


def probe_host(host, timeout=8):
    """DNS + HTTPS（失败再试 HTTP）"""
    t = time.time()
    try:
        socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except Exception as e:
        return False, round(time.time() - t, 2), "DNS " + type(e).__name__

    for scheme, port in (("https", 443), ("http", 80)):
        s = socket.socket()
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            return True, round(time.time() - t, 2), ""
        except Exception:
            continue
        finally:
            s.close()
    return False, round(time.time() - t, 2), "连接失败"


HOST_RE = re.compile(r"https?://([a-zA-Z0-9][a-zA-Z0-9\.\-]{2,80}\.[a-zA-Z]{2,12})")


def extract_hosts(text):
    out = []
    for h in HOST_RE.findall(text or ""):
        h = h.lower().split(":")[0]
        if is_common(h) or h in out:
            continue
        out.append(h)
    return out


VOD_API_RE = re.compile(r"https?://[^\s\"'<>,;)）]+?/api\.php/provide/vod[^\s\"'<>,;)）]*")


def try_vod_search(text):
    """能抽出苹果CMS接口就真实搜一次 —— 等价于在 App 里点一次搜索"""
    m = VOD_API_RE.search(text or "")
    if not m:
        return None
    base = m.group(0)
    sep = "&" if "?" in base else "?"
    url = f"{base}{sep}ac=videolist&wd=%E7%94%B5%E8%A7%86&pg=1"
    t = time.time()
    try:
        st, body = http_get(url, timeout=12, limit=120_000)
        txt = body.decode("utf-8", "replace")
        # 苹果CMS 正常返回 {"code":1,"list":[...]} 或 {"total":...}
        if st == 200 and re.search(r'"(list|total|pagecount)"\s*:', txt):
            n = len(re.findall(r'"vod_id"', txt))
            return {"ok": True, "hits": n, "sec": round(time.time() - t, 2), "api": base}
        return {"ok": False, "hits": 0, "sec": round(time.time() - t, 2),
                "api": base, "why": "返回非 JSON 接口格式"}
    except urllib.error.HTTPError as e:
        return {"ok": False, "hits": 0, "sec": round(time.time() - t, 2),
                "api": base, "why": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "hits": 0, "sec": round(time.time() - t, 2),
                "api": base, "why": type(e).__name__}


def resolve_ext(site, base_dir):
    """返回 [(url|None, 说明)]"""
    ext = site.get("ext")
    out = []
    if ext is None:
        return out
    if isinstance(ext, dict):
        for k in ("siteUrl", "json", "url", "api"):
            v = ext.get(k)
            if isinstance(v, str) and v.startswith("http"):
                out.append((v, f"ext.{k}"))
        txt = json.dumps(ext, ensure_ascii=False)
        out.append((None, txt))
        return out
    s = str(ext).strip()
    if not s:
        return out
    if s.startswith("http"):
        return [(s, "ext")]
    if s.startswith(("./", "/")):
        return [(base_dir + s.lstrip("./").lstrip("/"), "ext相对")]
    return [(None, s)]


def check_site(site, base_dir, engine_state):
    """返回一个 dict 描述该站点的体检结论"""
    key = site.get("key") or site.get("name", "?")
    api = str(site.get("api", ""))
    rec = {
        "key": key, "name": site.get("name", ""), "api": api,
        "kind": "csp" if api.startswith("csp_") else ("drpy" if ("drpy" in api or api.startswith("./lib/")) else "other"),
        "verdict": OK, "reasons": [], "hosts": [], "host_dead": [], "search": None,
    }

    # L1 引擎层
    if rec["kind"] == "csp" and not engine_state.get("spider_ok"):
        rec["verdict"] = STRONG
        rec["reasons"].append("spider jar 不可用（全局）")
        return rec
    if rec["kind"] == "drpy":
        eng = engine_state.get("drpy_ok")
        if eng is False and api.startswith("http"):
            pass  # 单个引擎挂了不代表这个站死，继续看 ext

    # L2 ext 层
    ext_texts = []
    ext_fetched = False
    for url, note in resolve_ext(site, base_dir):
        if url is None:
            ext_texts.append(note)
            continue
        ok, sec, err = http_ok(url)
        if ok:
            ext_fetched = True
            try:
                _, body = http_get(url, limit=300_000)
                t = body.decode("utf-8", "replace")
                if t.lstrip().lower().startswith(("<!doctype", "<html")) and "404" in t[:2000]:
                    rec["verdict"] = STRONG
                    rec["reasons"].append(f"{note} 返回 404 页面")
                    return rec
                ext_texts.append(t)
            except Exception:
                ext_texts.append("")
        else:
            if err.startswith("HTTP 404"):
                if any(u in url for u in UNVERIFIABLE):
                    rec["reasons"].append(f"{note} 返回 404（该站防爬，无法离线判定）")
                else:
                    rec["verdict"] = STRONG
                    rec["reasons"].append(f"{note} 404")
                    return rec
            else:
                rec["reasons"].append(f"{note} 取不到（{err}）")

    # L3 域名层
    joined = "\n".join(ext_texts)
    hosts = extract_hosts(joined)
    hosts = hosts[:8]
    rec["hosts"] = hosts
    if hosts:
        with ThreadPoolExecutor(max_workers=6) as ex:
            results = list(ex.map(lambda h: (h,) + probe_host(h), hosts))
        alive = [h for h, ok, _, _ in results if ok]
        dead = [h for h, ok, _, _ in results if not ok]
        rec["host_dead"] = dead
        if not alive:
            rec["verdict"] = STRONG
            rec["reasons"].append(f"ext 中 {len(hosts)} 个源站域名全部不可达")
            return rec
        if dead:
            rec["reasons"].append(f"{len(dead)}/{len(hosts)} 个域名不可达")

    # L4 真实搜索
    rec["search"] = try_vod_search(joined)
    if rec["search"] and rec["search"]["ok"] and rec["search"]["hits"] > 0:
        rec["verdict"] = OK
        rec["reasons"].append(f"真实搜索命中 {rec['search']['hits']} 条")
        return rec
    if rec["search"] and not rec["search"]["ok"]:
        # 接口格式不符不足以判死（可能是变体），只在域名也全死时才算强证据
        rec["reasons"].append("搜索接口异常：" + rec["search"].get("why", ""))

    if not hosts and not ext_fetched and not ext_texts:
        rec["verdict"] = UNKNOWN
        rec["reasons"].append("无 ext 信息，无法离线判定")
    elif rec["verdict"] == OK:
        # 有域名活着但没搜到 → 弱信号，不计数
        if hosts:
            rec["verdict"] = WEAK if (rec["search"] and not rec["search"]["ok"]) else OK
        else:
            rec["verdict"] = UNKNOWN
            rec["reasons"].append("ext 里没提到源站域名")
    return rec


IMPORT_RE = re.compile(
    r'import\s*(?:[\w{}\s,$*]+from\s*)?["\'](https?://[^"\']+)["\']'
)


def check_engine_deps(engine_url):
    """drpy 引擎 js 里常 import 远程插件，插件挂了整个引擎就起不来"""
    try:
        _, body = http_get(engine_url, timeout=20, limit=400_000)
        txt = body.decode("utf-8", "replace")
    except Exception as e:
        return {"ok": False, "deps": [], "bad": [], "why": type(e).__name__}
    deps = []
    for m in IMPORT_RE.finditer(txt):
        u = m.group(1)
        if u not in deps:
            deps.append(u)
    deps = deps[:8]
    if not deps:
        return {"ok": True, "deps": [], "bad": [], "why": ""}
    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(lambda u: (u,) + http_ok(u, timeout=12), deps))
    bad = [u for u, ok, _s, _e in results if not ok]
    return {"ok": not bad, "deps": results, "bad": bad, "why": ""}


def check_engines(cfg, base_dir):
    state = {"deps": {}}

    spider = (cfg.get("spider") or "").split(";md5;")[0]
    if spider:
        ok, sec, err = http_ok(spider)
        state["spider_ok"] = ok
        state["spider_url"] = spider
        print(f"[引擎] {'spider jar':24s} {'OK' if ok else '不可用 ' + err}  {spider[:60]}")

    engines = set()
    for s in cfg.get("sites", []):
        api = str(s.get("api", ""))
        if api.startswith("http"):
            engines.add(api)
        elif api.startswith("./") and api.endswith(".js"):
            engines.add(base_dir + api.lstrip("./"))

    state["drpy_ok"] = None
    for e in sorted(engines)[:4]:
        ok, sec, err = http_ok(e)
        label = e.split("/")[-1] or e[:20]
        print(f"[引擎] {label:24s} {'OK' if ok else '不可用 ' + err}  {e[:60]}")
        if not ok:
            continue
        state["drpy_ok"] = True
        dep = check_engine_deps(e)
        state["deps"][e] = dep
        if dep["deps"]:
            print(f"       远程依赖 {len(dep['deps'])} 个，失败 {len(dep['bad'])}")
            for u, o, _s2, e2 in dep["deps"]:
                print(f"         {'OK  ' if o else 'FAIL'} {u[:72]} {'' if o else e2}")
    return state


def load_state(path):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            pass
    return {"sites": {}}


def save_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--config", default=os.path.join(here, "taoying-config.json"))
    ap.add_argument("--state", default=os.path.join(here, "site-health.json"))
    ap.add_argument("--report", default=os.path.join(here, "last-sweep.md"))
    ap.add_argument("--apply", action="store_true", help="按规则剔除死站并写回配置")
    ap.add_argument("--streak", type=int, default=3, help="连续失败多少次才剔除")
    ap.add_argument("--min-sites", type=int, default=45)
    ap.add_argument("--restore", default="", help="把某个 key 从 parked 恢复")
    ap.add_argument("--list-parked", action="store_true")
    args = ap.parse_args()

    cfg = json.load(open(args.config, encoding="utf-8"))
    state = load_state(args.state)
    parked = cfg.setdefault("sites_parked", [])

    if args.list_parked:
        print(f"已剔除 {len(parked)} 个站点：")
        for s in parked:
            print(f"  {s.get('key')}  {s.get('name')}  ({s.get('_parked_reason', '')})")
        return

    if args.restore:
        hit = [s for s in parked if s.get("key") == args.restore or s.get("name") == args.restore]
        if not hit:
            print(f"没找到 {args.restore}，用 --list-parked 看看有哪些")
            sys.exit(1)
        for s in hit:
            s.pop("_parked_at", None)
            s.pop("_parked_reason", None)
            cfg["sites"].append(s)
            parked.remove(s)
            state["sites"].pop(s.get("key"), None)
            print(f"已恢复 {s.get('key')}")
        save_json(args.config, cfg)
        return

    # ext 相对路径的基址 = spider 所在仓库根目录
    spider = (cfg.get("spider") or "").split(";md5;")[0]
    m = re.match(r"(https?://.+?/)(?:jar/)?[^/]+$", spider)
    base_dir = m.group(1) if m else ""
    print(f"[配置] {len(cfg.get('sites', []))} 个站点，base={base_dir}")
    print(f"[配置] 已 parked {len(parked)} 个")

    engines = check_engines(cfg, base_dir)

    sites = [s for s in cfg.get("sites", []) if isinstance(s, dict)]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(lambda s: check_site(s, base_dir, engines), sites))
    print(f"[探测] {len(results)} 个站点，用时 {time.time() - t0:.0f}s")

    # 累积历史
    hist = state.setdefault("sites", {})
    for r in results:
        h = hist.setdefault(r["key"], {"streak": 0, "total": 0, "ok": 0})
        h["total"] += 1
        if r["verdict"] == STRONG:
            h["streak"] += 1
        elif r["verdict"] == OK:
            h["streak"] = 0
            h["ok"] += 1
            h["last_ok"] = now_cn()
        # weak / unknown 不改变 streak
        h["last_verdict"] = r["verdict"]
    state["last_run"] = now_cn()

    strong = [r for r in results if r["verdict"] == STRONG]
    weak = [r for r in results if r["verdict"] == WEAK]
    unknown = [r for r in results if r["verdict"] == UNKNOWN]
    good = [r for r in results if r["verdict"] == OK]

    # 打印
    print(f"\n结论：正常 {len(good)} / 可疑 {len(weak)} / 判死 {len(strong)} / 无法判定 {len(unknown)}")
    if strong:
        print("\n判死的站点（连续失败次数）：")
        for r in strong:
            st = hist[r["key"]]["streak"]
            print(f"  [{st}次] {r['key']:16s} {r['name'][:16]:18s} {'；'.join(r['reasons'])[:70]}")
    if weak:
        print("\n可疑（不剔除，仅提示）：")
        for r in weak[:12]:
            print(f"  {r['key']:16s} {r['name'][:16]:18s} {'；'.join(r['reasons'])[:70]}")

    # 剔除决策
    to_park = []
    if args.apply:
        cap = max(args.min_sites, 30)
        for r in sorted(strong, key=lambda x: -hist[x["key"]]["streak"]):
            if hist[r["key"]]["streak"] < args.streak:
                continue
            if len(cfg["sites"]) - len(to_park) <= cap:
                print(f"[保护] 站点数将低于 {cap}，停止剔除")
                break
            to_park.append(r)

        if to_park:
            by_key = {r["key"]: r for r in to_park}
            keep = []
            for s in cfg["sites"]:
                r = by_key.get(s.get("key"))
                if r:
                    s["_parked_at"] = now_cn()
                    s["_parked_reason"] = "；".join(r["reasons"])[:200]
                    parked.append(s)
                else:
                    keep.append(s)
            cfg["sites"] = keep
            print(f"\n[剔除] {len(to_park)} 个站点移到 sites_parked，剩余 {len(cfg['sites'])} 个")
        else:
            print("\n[剔除] 没有达到剔除条件的站点")

    # 写报告
    lines = [
        "# 涛影点播站点巡检报告", "",
        f"- 运行时间：{now_cn()}",
        f"- 站点总数：{len(sites)}（已剔除 {len(parked)}）",
        f"- 结论：正常 **{len(good)}** / 可疑 {len(weak)} / 判死 {len(strong)} / 无法判定 {len(unknown)}",
        f"- 剔除规则：连续 {args.streak} 次强失败，且站点数不低于 {args.min_sites}",
        "",
        "## 判死明细", "",
        "| 站点 | 名称 | 连续失败 | 原因 |", "|---|---|---|---|",
    ]
    for r in strong:
        lines.append(f"| `{r['key']}` | {r['name']} | {hist[r['key']]['streak']} | {'；'.join(r['reasons'])[:120]} |")
    if not strong:
        lines.append("| — | — | — | 无 |")
    lines += ["", "## 可疑（未剔除）", "", "| 站点 | 名称 | 原因 |", "|---|---|---|"]
    for r in weak:
        lines.append(f"| `{r['key']}` | {r['name']} | {'；'.join(r['reasons'])[:120]} |")
    if not weak:
        lines.append("| — | — | — |")
    lines += ["", "## 本轮正常且搜索命中", "", "| 站点 | 名称 | 命中 |", "|---|---|---|"]
    hit_ok = [r for r in good if r["search"] and r["search"].get("ok")]
    for r in hit_ok:
        lines.append(f"| `{r['key']}` | {r['name']} | {r['search']['hits']} |")
    if not hit_ok:
        lines.append("| — | — | — |")

    open(args.report, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    save_json(args.state, state)
    if args.apply and to_park:
        save_json(args.config, cfg)
    print(f"\n报告：{args.report}")
    print(f"状态：{args.state}")


if __name__ == "__main__":
    main()
