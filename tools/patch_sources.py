#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
涛影构建期源码定制脚本（替代原 taoying.yml 里的多条 sed）

用法：
    python3 tools/patch_sources.py <上游源码目录>      # 默认 TVBoxOSC

设计原则：
  * core()  必须有：包名 / 应用名 / 内置源 / 版本号 / 图标外的关键定制。匹配失败 → 直接 exit 1，绝不出半成品包。
  * soft()  可选优化：启动提速、去无用依赖等。匹配失败 → 跳过并记录，不影响出包。
  * 所有替换都带「匹配条数」校验，替换结果在结束前统一回读确认。

环境变量：
    APP_NAME        应用显示名，默认 涛影
    API_URL         内置订阅源
    APP_ID          包名，默认 com.taoying.app
    BUILD_DATE      构建日期 yyyymmdd
    VERSION_CODE    版本号数字
    ENABLE_DESUGAR  true 时启用 core library desugaring（java.time 等 API 在 4.4 上可用）
"""

import os
import sys
import pathlib

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "TVBoxOSC").resolve()

APP_NAME = os.environ.get("APP_NAME", "涛影")
API_URL = os.environ.get(
    "API_URL",
    "https://ghproxy.net/https://raw.githubusercontent.com/gaotianliuyun/gao/master/0821.json",
)
APP_ID = os.environ.get("APP_ID", "com.taoying.app")
BUILD_DATE = os.environ.get("BUILD_DATE", "20260101")
VERSION_CODE = os.environ.get("VERSION_CODE", "2026010100")
ENABLE_DESUGAR = os.environ.get("ENABLE_DESUGAR", "false").lower() == "true"

done, skipped, failed = [], [], []


class Doc:
    """把文件内容读进内存，多次替换后一次性落盘，避免 sed 逐行改的漏改/重改。"""

    def __init__(self, rel):
        self.rel = rel
        self.path = ROOT / rel
        if not self.path.exists():
            raise SystemExit(f"[FATAL] 找不到文件: {rel}")
        with open(self.path, "r", encoding="utf-8", newline="") as f:
            self.text = f.read()

    def replace(self, tag, old, new, required=True, expect=1):
        """expect=None 表示只替换第一处、不校验总数。"""
        cnt = self.text.count(old)
        if cnt == 0:
            (failed if required else skipped).append(f"{tag}（未匹配）")
            return False
        if expect is not None and cnt != expect:
            msg = f"{tag}（匹配 {cnt} 处，预期 {expect}）"
            (failed if required else skipped).append(msg)
            return False
        self.text = self.text.replace(old, new, 1)
        done.append(tag)
        return True

    def save(self):
        with open(self.path, "w", encoding="utf-8", newline="") as f:
            f.write(self.text)


print(f"== 涛影定制开始：APP_NAME={APP_NAME} APP_ID={APP_ID} VERSION={VERSION_CODE}")

# ----------------------------------------------------------------------------
# 1. app/build.gradle —— 包名 / 版本 / 签名 / 依赖
# ----------------------------------------------------------------------------
g = Doc("app/build.gradle")

g.replace(
    "包名 applicationId",
    "applicationId 'com.github.tvbox.osc.jun'",
    f"applicationId '{APP_ID}'",
    expect=1,
)
g.replace(
    "versionName",
    "versionName '1.0.0'",
    f"versionName '1.0.0-taoying-{BUILD_DATE}'",
    expect=1,
)
g.replace("versionCode", "versionCode 1", f"versionCode {VERSION_CODE}", expect=1)

# 签名配置（原先用 base64 + sed 注入，这里改成可读写法）
if "signingConfigs {" not in g.text:
    signing_block = """    signingConfigs {
        if (project.hasProperty("RELEASE_STORE_FILE")) {
            myConfig {
                storeFile file(RELEASE_STORE_FILE)
                storePassword RELEASE_STORE_PASSWORD
                keyAlias RELEASE_KEY_ALIAS
                keyPassword RELEASE_KEY_PASSWORD
                v1SigningEnabled true
                v2SigningEnabled true
                enableV3Signing = true
                enableV4Signing = true
            }
        }
    }

"""
    g.replace(
        "签名 signingConfigs 块",
        "    defaultConfig {",
        signing_block + "    defaultConfig {",
        expect=1,
    )
    g.replace(
        "debug 签名引用",
        "        debug {\n            minifyEnabled false",
        "        debug {\n            signingConfig signingConfigs.myConfig\n            minifyEnabled false",
        expect=1,
    )
    g.replace(
        "release 签名引用",
        "        release {\n            minifyEnabled true",
        "        release {\n            signingConfig signingConfigs.myConfig\n            minifyEnabled true",
        expect=1,
    )
else:
    skipped.append("签名块已存在，跳过注入")

# 去掉零引用的 cronet（代码零 import，纯占体积；4.4 上也不参与逻辑）
g.replace(
    "移除 cronet-okhttp 依赖",
    "    implementation ('com.google.net.cronet:cronet-okhttp:0.1.0')\n",
    "",
)
g.replace(
    "移除 cronet-embedded 依赖",
    "    implementation ('org.chromium.net:cronet-embedded:101.4951.41')\n",
    "",
)

# 可选：core library desugaring（让 java.time / java.nio.file 在 API 19 可用）
if ENABLE_DESUGAR:
    g.replace(
        "启用 desugaring 编译开关",
        "        targetCompatibility JavaVersion.VERSION_1_8\n    }",
        "        targetCompatibility JavaVersion.VERSION_1_8\n        coreLibraryDesugaringEnabled true\n    }",
        required=False,
    )
    g.replace(
        "增加 desugar_jdk_libs 依赖",
        "dependencies {\n",
        "dependencies {\n    coreLibraryDesugaring 'com.android.tools:desugar_jdk_libs:1.1.5'\n",
        required=False,
    )
else:
    skipped.append("desugaring 未启用（ENABLE_DESUGAR≠true）")

g.save()

# ----------------------------------------------------------------------------
# 2. 应用名 / 投屏文案
# ----------------------------------------------------------------------------
s = Doc("app/src/main/res/values/strings.xml")
s.replace(
    "应用名 app_name",
    '<string name="app_name">TVBox</string>',
    f'<string name="app_name">{APP_NAME}</string>',
    expect=1,
)
s.save()

c = Doc("app/src/main/res/layout/dialog_cast.xml")
c.replace("投屏文案", "已安装TVBox", f"已安装{APP_NAME}", required=True, expect=None)
c.save()

# ----------------------------------------------------------------------------
# 3. App.java —— 内置源 + 启动提速
# ----------------------------------------------------------------------------
a = Doc("app/src/main/java/com/github/tvbox/osc/base/App.java")

a.replace(
    "内置订阅源注入",
    "Hawk.init(this).build();",
    "Hawk.init(this).build();\n"
    '        // [涛影] 内置源：首次写入；若仍是旧内置源（gao/ghproxy），升级时自动迁移到自托管配置\n'
    '        String tyApi = Hawk.get(HawkConfig.API_URL, "");\n'
    '        if (tyApi.isEmpty() || tyApi.contains("gaotianliuyun/gao") || tyApi.contains("ghproxy.net")) {\n'
    f'            Hawk.put(HawkConfig.API_URL, "{API_URL}");\n'
    '        }\n'
    '        // [涛影] 直播默认 IJK 硬解：EXO 在 4.4 老盒子上播 HLS 常黑屏（点播仍用 EXO，不动）\n'
    '        if (!Hawk.contains(HawkConfig.LIVE_PLAY_TYPE)) { Hawk.put(HawkConfig.LIVE_PLAY_TYPE, 1); }\n'
    '        if (!Hawk.contains(HawkConfig.IJK_CODEC)) { Hawk.put(HawkConfig.IJK_CODEC, "\u786c\u89e3\u7801"); }',
    expect=1,
)

# 启动提速 1：100KB 的 EPG JSON 解析移出主线程（原来在 onCreate 同步解析）
a.replace(
    "EPG 解析移出主线程",
    "        EpgUtil.init();\n",
    '        startAsync("taoying-epg", () -> EpgUtil.init());\n',
    required=False,
)
# 启动提速 2：播放缓存清理是纯 IO，二次启动时可能删几百 MB，移出主线程
a.replace(
    "播放缓存清理移出主线程",
    "        FileUtils.cleanPlayerCache();\n",
    '        startAsync("taoying-cache", () -> FileUtils.cleanPlayerCache());\n',
    required=False,
)
# 配套的后台任务工具方法
if "private static void startAsync" not in a.text:
    a.replace(
        "后台任务工具方法",
        "    private void initParams() {",
        "    // [涛影] 轻量后台线程：把纯 IO / JSON 解析类初始化挪出主线程，缩短首屏时间\n"
        "    private static void startAsync(String name, Runnable task) {\n"
        "        Thread t = new Thread(task, name);\n"
        "        t.setPriority(Thread.MIN_PRIORITY);\n"
        "        t.start();\n"
        "    }\n\n"
        "    private void initParams() {",
        required=False,
    )
a.save()

# ----------------------------------------------------------------------------
# 4. EpgUtil.java —— init() 加锁 + 首次使用时兜底（配合上面异步预热）
# ----------------------------------------------------------------------------
e = Doc("app/src/main/java/com/github/tvbox/osc/util/EpgUtil.java")
e.replace(
    "EpgUtil.init 加锁",
    "    public static void init() {\n        if(epgDoc != null)\n            return;",
    "    public static void init() {\n"
    "        synchronized (EpgUtil.class) {\n"
    "            initLocked();\n"
    "        }\n"
    "    }\n\n"
    "    private static void initLocked() {\n"
    "        if(epgDoc != null)\n            return;",
    required=False,
)
e.replace(
    "EpgUtil 懒加载兜底",
    "    public static String[] getEpgInfo(String channelName) {\n        try {",
    "    public static String[] getEpgInfo(String channelName) {\n"
    "        if (epgDoc == null) init();\n"
    "        try {",
    required=False,
)
e.replace(
    "epgDoc 可见性",
    "    private static JsonObject epgDoc = null;",
    "    private static volatile JsonObject epgDoc = null;",
    required=False,
)
e.save()

# ----------------------------------------------------------------------------
# 5. 工程配置
# ----------------------------------------------------------------------------
root_gradle = ROOT / "build.gradle"
if root_gradle.exists():
    rg = Doc("build.gradle")
    if "j4uq.github.io/crosswalk" in rg.text:
        skipped.append("crosswalk 镜像已存在")
    else:
        rg.replace(
            "crosswalk 镜像",
            '        maven { url "https://jitpack.io" }',
            '        maven { url "https://jitpack.io" }\n'
            "        maven { url 'https://j4uq.github.io/crosswalk/releases/crosswalk/android/maven2' }",
            required=False,
            expect=None,
        )
        rg.save()

# pyramid 的 Windows 硬编码 python 路径（配置阶段会报错）
py_gradle = ROOT / "pyramid/build.gradle"
if py_gradle.exists():
    lines = []
    removed = 0
    with open(py_gradle, "r", encoding="utf-8", newline="") as f:
        for line in f:
            if "buildPython" in line and "python.exe" in line:
                removed += 1
                continue
            lines.append(line)
    if removed:
        with open(py_gradle, "w", encoding="utf-8", newline="") as f:
            f.writelines(lines)
        done.append(f"移除 pyramid 硬编码 python 路径（{removed} 行）")

# local.properties 清空，避免继承本机 SDK 路径
with open(ROOT / "local.properties", "w", encoding="utf-8", newline="") as f:
    f.write("")

# ----------------------------------------------------------------------------
# 6. 结果回读校验 + 报告
# ----------------------------------------------------------------------------
checks = [
    ("包名", "app/build.gradle", APP_ID),
    ("应用名", "app/src/main/res/values/strings.xml", APP_NAME),
    ("versionName", "app/build.gradle", f"1.0.0-taoying-{BUILD_DATE}"),
    ("versionCode", "app/build.gradle", f"versionCode {VERSION_CODE}"),
    ("内置源", "app/src/main/java/com/github/tvbox/osc/base/App.java", "HawkConfig.API_URL"),
]
for name, rel, needle in checks:
    text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    if needle not in text:
        failed.append(f"回读校验失败：{name} 未包含 {needle}")

print("\n== 已应用 ==")
for x in done:
    print("  [OK]  " + x)
print("== 已跳过（可选优化） ==")
for x in skipped:
    print("  [SKIP] " + x)
if failed:
    print("== 失败 ==")
    for x in failed:
        print("  [FAIL] " + x)
    final = Doc("app/build.gradle")
    print("---- applicationId / version 现状 ----")
    for line in final.text.splitlines():
        if "applicationId" in line or "versionCode" in line or "versionName" in line:
            print("   " + line.strip())
    sys.exit(1)

print("\n== 定制完成 ==")
