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

INJECT_IJK = (
    "{\"options\":[{\"name\":\"opensles\",\"category\":4,\"value\":\"0\"},{\"name\":\"framedrop\",\"category\":4,\"value\":\"1\"},{\"name\":\"soundtouch\",\"category\":4,\"value\":\"1\"},{\"name\":\"start-on-prepared\",\"category\":4,\"value\":\"1\"},{\"name\":\"http-detect-rangeupport\",\"category\":1,\"value\":\"0\"},{\"name\":\"fflags\",\"category\":1,\"value\":\"fastseek\"},{\"name\":\"skip_loop_filter\",\"category\":2,\"value\":\"48\"},{\"name\":\"reconnect\",\"category\":4,\"value\":\"1\"},{\"name\":\"enable-accurate-seek\",\"category\":4,\"value\":\"0\"},{\"name\":\"mediacodec\",\"category\":4,\"value\":\"0\"},{\"name\":\"mediacodec-all-videos\",\"category\":4,\"value\":\"0\"},{\"name\":\"mediacodec-auto-rotate\",\"category\":4,\"value\":\"0\"},{\"name\":\"mediacodec-handle-resolution-change\",\"category\":4,\"value\":\"0\"},{\"name\":\"mediacodec-hevc\",\"category\":4,\"value\":\"0\"},{\"name\":\"max-buffer-size\",\"category\":4,\"value\":\"8388608\"},{\"name\":\"probesize\",\"category\":1,\"value\":\"1048576\"},{\"name\":\"analyzeduration\",\"category\":1,\"value\":\"2000000\"}],\"group\":\"软解码·秒开\"},{\"options\":[{\"name\":\"opensles\",\"category\":4,\"value\":\"0\"},{\"name\":\"framedrop\",\"category\":4,\"value\":\"1\"},{\"name\":\"soundtouch\",\"category\":4,\"value\":\"1\"},{\"name\":\"start-on-prepared\",\"category\":4,\"value\":\"1\"},{\"name\":\"http-detect-rangeupport\",\"category\":1,\"value\":\"0\"},{\"name\":\"fflags\",\"category\":1,\"value\":\"fastseek\"},{\"name\":\"skip_loop_filter\",\"category\":2,\"value\":\"48\"},{\"name\":\"reconnect\",\"category\":4,\"value\":\"1\"},{\"name\":\"enable-accurate-seek\",\"category\":4,\"value\":\"0\"},{\"name\":\"mediacodec\",\"category\":4,\"value\":\"1\"},{\"name\":\"mediacodec-all-videos\",\"category\":4,\"value\":\"1\"},{\"name\":\"mediacodec-auto-rotate\",\"category\":4,\"value\":\"1\"},{\"name\":\"mediacodec-handle-resolution-change\",\"category\":4,\"value\":\"1\"},{\"name\":\"mediacodec-hevc\",\"category\":4,\"value\":\"1\"},{\"name\":\"max-buffer-size\",\"category\":4,\"value\":\"8388608\"},{\"name\":\"probesize\",\"category\":1,\"value\":\"1048576\"},{\"name\":\"analyzeduration\",\"category\":1,\"value\":\"2000000\"}],\"group\":\"硬解码·秒开\"}"
)

done, skipped, failed = [], [], []


class Doc:
    """把文件内容读进内存，多次替换后一次性落盘，避免 sed 逐行改的漏改/重改。

    上游源码是 CRLF（Windows 换行），脚本里的多行匹配串写的是 \\n。
    读入时统一成 \\n 再匹配，落盘时还原，否则所有多行补丁都会静默匹配失败。
    """

    def __init__(self, rel):
        self.rel = rel
        self.path = ROOT / rel
        if not self.path.exists():
            raise SystemExit(f"[FATAL] 找不到文件: {rel}")
        with open(self.path, "r", encoding="utf-8", newline="") as f:
            self.text = f.read()
        self.crlf = "\r\n" in self.text
        if self.crlf:
            self.text = self.text.replace("\r\n", "\n")

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
        out = self.text.replace("\n", "\r\n") if self.crlf else self.text
        with open(self.path, "w", encoding="utf-8", newline="") as f:
            f.write(out)


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

# [观影听涛 2026-11-12] 启用资源压缩：release 已开 minifyEnabled，配套 shrinkResources
# 可剔除未被引用的 res/ 资源；失败只跳过，不影响出包。
g.replace(
    "启用资源压缩 shrinkResources",
    "        release {\n            signingConfig signingConfigs.myConfig\n            minifyEnabled true",
    "        release {\n            signingConfig signingConfigs.myConfig\n"
    "            minifyEnabled true\n            shrinkResources true",
    required=False,
    expect=1,
)

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
    '        // [观影听涛] 内置源：首次写入；若仍是旧内置源（gao/ghproxy），升级时自动迁移到自托管配置\n'
    '        String tyApi = Hawk.get(HawkConfig.API_URL, "");\n'
    '        if (tyApi.isEmpty() || tyApi.contains("gaotianliuyun/gao") || tyApi.contains("ghproxy.net") || tyApi.contains("gh.74259136.xyz")) {\n'
    f'            Hawk.put(HawkConfig.API_URL, "{API_URL}");\n'
    '        }\n'
    '        // [观影听涛] 锁定最优设置：每次启动强制写入，避免误调导致变慢\n'
    '        Hawk.put(HawkConfig.LIVE_PLAY_TYPE, 2);  // [观影听涛] 直播先用 EXO：IJK 硬解不支持该源 profile 时会干等 10 秒才换\n'
    '        Hawk.put(HawkConfig.IJK_CODEC, "硬解码·秒开");\n'
    '        Hawk.put(HawkConfig.IJK_CACHE_PLAY, false);\n'
    '        Hawk.put(HawkConfig.DANMU_OPEN, false);\n'
    '        // [观影听涛] 首页分类网格走采集站（按更新时间倒序 = 最新）；热播横条另由豆瓣填充\n'
    '        String tyHome = Hawk.get(HawkConfig.HOME_API, "");\n'
    '        if (tyHome.isEmpty() || "豆豆".equals(tyHome)) { Hawk.put(HawkConfig.HOME_API, "暴風"); }\n'
    '        // [观影听涛] 片源广告过滤默认开启：拦截 m3u8 里插播的广告分片（棋牌/博彩类常见）\n'
    '        // 只在没设过时写 true，用户仍可在 设置→播放器 里手动关闭（个别片源过滤后起播失败时用）\n'
    '        if (!Hawk.contains(HawkConfig.M3U8_PURIFY)) { Hawk.put(HawkConfig.M3U8_PURIFY, true); }\n'
    '        // [观影听涛] 直播画面比例默认「裁剪」：不少源是 720x576/640x480 的 4:3 标清，\n'
    '        // 「默认」比例会左右留 31% 黑边（实机截图确认）。裁剪可铺满且不变形；\n'
    '        // 16:9 的源比例相同，裁剪结果与默认完全一致，不受影响。\n'
    '        // 想改回来：直播界面 → 长按 OK → 画面比例 → 默认\n'
    '        if (!Hawk.contains(HawkConfig.LIVE_PLAY_SCALE)) { Hawk.put(HawkConfig.LIVE_PLAY_SCALE, 5); }',
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
        "    // [观影听涛] 轻量后台线程：把纯 IO / JSON 解析类初始化挪出主线程，缩短首屏时间\n"
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
# 4.5 隐私 / 性能微调（2026-10-24）
# ----------------------------------------------------------------------------
import shutil

# 4.5.1 删掉代码里从未使用的定位权限（全仓库无 LocationManager 调用）
for mf in ("app/src/main/AndroidManifest.xml", "player/src/main/AndroidManifest.xml"):
    try:
        d = Doc(mf)
        d.replace("移除定位权限",
                  '    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />\n',
                  "", required=False, expect=None)
        d.save()
    except SystemExit:
        pass

# 4.5.2 直播右上角台标：不再旋转（原来 ObjectAnimator 无限转，方图转起来四角露白边，还持续重绘）
lp = Doc("app/src/main/java/com/github/tvbox/osc/ui/activity/LivePlayActivity.java")
lp.replace(
    "去掉台标旋转动画",
    '        //右上角图片旋转\n'
    '        objectAnimator = ObjectAnimator.ofFloat(iv_circle_bg,"rotation", 360.0f);\n'
    '        objectAnimator.setDuration(postTimeout);\n'
    '        objectAnimator.setRepeatCount(-1);\n'
    '        objectAnimator.start();',
    "        // [观影听涛] 台标固定不旋转：省掉持续重绘，也避免方图旋转时的白边",
    required=False,
)
lp.save()

# 4.5.3 台标换成圆形透明图（原来直接用 app_icon 这张方图）
try:
    src_icon = pathlib.Path(os.environ.get("GITHUB_WORKSPACE", ".")) / "tools/assets/ic_live_logo.png"
    if src_icon.exists():
        dst_dir = ROOT / "app/src/main/res/drawable-nodpi"
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_icon, dst_dir / "ic_live_logo.png")
        done.append("复制圆形台标 ic_live_logo.png")
        lay = Doc("app/src/main/res/layout/activity_live_play.xml")
        src_line = 'android:src="@drawable/app_icon" />'
        cnt = lay.text.count(src_line)
        if cnt == 1:
            lay.text = lay.text.replace(src_line, 'android:src="@drawable/ic_live_logo" />', 1)
            done.append("台标 src 改为 ic_live_logo")
        else:
            skipped.append("台标 src 匹配 %d 处，跳过换图" % cnt)
        lay.save()
    else:
        skipped.append("缺少 tools/assets/ic_live_logo.png")
except Exception as e:
    skipped.append("台标圆形图处理失败：%s" % e)

# 4.5.4 修局域网 HTTP 服务 /file/ 的路径穿越（原来可读设备任意文件）
rs = Doc("app/src/main/java/com/github/tvbox/osc/server/RemoteServer.java")
rs.replace(
    "修复 /file/ 路径穿越",
    '                        String f = fileName.substring(6);\n'
    '                        String root = Environment.getExternalStorageDirectory().getAbsolutePath();\n'
    '                        String file = root + "/" + f;',
    '                        String f = fileName.substring(6);\n'
    '                        String root = Environment.getExternalStorageDirectory().getAbsolutePath();\n'
    '                        // [观影听涛] 规范化路径，禁止 ../ 跳出外部存储根目录\n'
    '                        String file = new File(root, f).getCanonicalPath();\n'
    '                        if (!file.startsWith(root)) {\n'
    '                            return NanoHTTPD.newFixedLengthResponse(NanoHTTPD.Response.Status.FORBIDDEN, NanoHTTPD.MIME_PLAINTEXT, "forbidden");\n'
    '                        }',
    required=False,
)
rs.save()

# ----------------------------------------------------------------------------
# 4.6 点播站点自检（App 自己遍历所有源真实加载一遍，输出可用/失效清单）
# ----------------------------------------------------------------------------
try:
    hsrc = pathlib.Path(os.environ.get("GITHUB_WORKSPACE", ".")) / "tools/site-health/SiteHealthChecker.java"
    if hsrc.exists():
        hdst = ROOT / "app/src/main/java/com/github/tvbox/osc/util/health/SiteHealthChecker.java"
        hdst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(hsrc, hdst)
        done.append("注入站点自检 SiteHealthChecker")

        hc = Doc("app/src/main/java/com/github/tvbox/osc/ui/activity/HomeActivity.java")
        hc.replace(
            "站点自检入口",
            "    protected void init() {",
            "    protected void init() {\n"
            "        // [观影听涛] 每 N 天自动跑一次点播源自检，结果写 files/site-health.json\n"
            "        com.github.tvbox.osc.util.health.SiteHealthChecker.schedule(this);",
            required=False,
        )
        hc.save()

        # release 构建 minifyEnabled=true，加 keep 规则防止被裁剪/改名
        pg = Doc("app/proguard-rules.pro")
        if "com.github.tvbox.osc.util.health" not in pg.text:
            pg.text += ("\n# [涛影] 点播站点自检，保持类名避免被裁剪\n"
                        "-keep class com.github.tvbox.osc.util.health.** { *; }\n")
            pg.save()
            done.append("proguard keep 站点自检")
    else:
        skipped.append("缺少 tools/site-health/SiteHealthChecker.java")
except Exception as e:
    skipped.append("站点自检注入失败：%s" % e)

# ----------------------------------------------------------------------------
# 4.7 界面与文案（2026-10-24）
# ----------------------------------------------------------------------------

# 4.7.1 关于页：精简 + 保留原版出处 + 标注二次封装
ab = Doc("app/src/main/res/layout/dialog_about.xml")
ab.replace(
    "关于页文案",
    '本软件只提供聚合展示功能，所有资源来自网上, 软件不参与任何制作, 上传, 储存, 下载等内容. '
    '软件仅供学习参考, 请于安装后24小时内删除。\\n\\n打包分发请保留出处\\n'
    'https://github.com/CatVodTVOfficial/TVBoxOSC\\nhttps://github.com/q215613905/TVBoxOS',
    '涛影 · 涛声依旧　　二次封装：涛声依旧\\n\\n'
    '基于 TVBox 开源项目修改，感谢原作者\\n'
    'https://github.com/CatVodTVOfficial/TVBoxOSC\\n'
    'https://github.com/q215613905/TVBoxOS\\n\\n'
    '仅聚合展示网络公开内容，不制作、不上传、不存储任何资源。\\n'
    '仅供学习参考，请于安装后 24 小时内删除。',
    required=False,
)
# 直接改写文案：兼容上游原文变动，找不到原文时也能生效
ab.text = ab.text.replace(
    '涛影 · 涛声依旧　　二次封装：涛声依旧',
    f'观影听涛　　二次封装：涛声依旧\\n版本 {BUILD_DATE}'
)
ab.text = ab.text.replace(
    '本软件只提供聚合展示功能，所有资源来自网上, 软件不参与任何制作, 上传, 储存, 下载等内容. 软件仅供学习参考, 请于安装后24小时内删除。',
    f'版本 {BUILD_DATE}     二次封装：涛声依旧',
)
ab.save()

# 4.7.2 全屏播放：控制条加「返回」按钮（点它回到频道列表，不占画面）
lay = Doc("app/src/main/res/layout/activity_live_play.xml")
BACK_BTN = (
    '\t\t\t<TextView\n'
    '\t\t\t\tandroid:id="@+id/tv_back_live"\n'
    '\t\t\t\tandroid:layout_width="wrap_content"\n'
    '\t\t\t\tandroid:layout_height="30dp"\n'
    '\t\t\t\tandroid:layout_marginEnd="6dp"\n'
    '\t\t\t\tandroid:gravity="center"\n'
    '\t\t\t\tandroid:paddingStart="8dp"\n'
    '\t\t\t\tandroid:paddingEnd="8dp"\n'
    '\t\t\t\tandroid:text="‹ 返回"\n'
    '\t\t\t\tandroid:textColor="#ffffff"\n'
    '\t\t\t\tandroid:textSize="14dp" />\n\n'
)
lay.replace(
    "直播控制条加返回按钮",
    '\t\t\t<ImageView\n\t\t\t\tandroid:id="@+id/iv_playpause"',
    BACK_BTN + '\t\t\t<ImageView\n\t\t\t\tandroid:id="@+id/iv_playpause"',
    required=False,
)
lay.save()

# 4.7.3 绑定返回按钮：显示频道列表（该列表本来就会自动隐藏，不干扰观看）
lp2 = Doc("app/src/main/java/com/github/tvbox/osc/ui/activity/LivePlayActivity.java")
lp2.replace(
    "绑定返回按钮",
    "        iv_playpause = findViewById(R.id.iv_playpause);",
    "        iv_playpause = findViewById(R.id.iv_playpause);\n"
    "        // [观影听涛] 全屏播放时的返回入口：点它显示频道列表，几秒后自动隐藏\n"
    "        View tyBackBtn = findViewById(R.id.tv_back_live);\n"
    "        if (tyBackBtn != null) {\n"
    "            tyBackBtn.setOnClickListener(new View.OnClickListener() {\n"
    "                @Override\n"
    "                public void onClick(View v) {\n"
    "                    iv_play.setVisibility(View.INVISIBLE);\n"
    "                    divLoadEpgLeft(null);\n"
    "                }\n"
    "            });\n"
    "        }",
    required=False,
)
lp2.save()

# ----------------------------------------------------------------------------
# 4.8 权限收敛（2026-10-24）
# ----------------------------------------------------------------------------
# READ_PHONE_STATE 只在 player 模块的清单里声明，代码仅用到 TelephonyManager.getPhoneType()
# 和 NETWORK_TYPE_* 常量，两者都不需要该权限。机顶盒更没有电话功能，移除可少一个敏感权限。
try:
    pm = Doc("player/src/main/AndroidManifest.xml")
    pm.replace(
        "移除 READ_PHONE_STATE",
        '    <uses-permission android:name="android.permission.READ_PHONE_STATE" />\n',
        "",
        required=False,
        expect=None,
    )
    pm.save()
except SystemExit:
    skipped.append("player 模块清单不存在，跳过权限收敛")

# ----------------------------------------------------------------------------
# 4.9b 补齐 IJK 秒开参数 + 增加 4MB probesize 对照（2026-11-12 云主机实测驱动）
# ----------------------------------------------------------------------------
# 依据：超级直播 3.5.1 反编译 b0;->a() 的 setOption 清单，以及盒端 Configuration.json
# 实测 IJK_probesize=4096000。T0 基线显示 4 秒固定超时是主要浪费，参数只解决起流后的
# 首帧延迟，不解决超时；两组任务分开，避免混淆。
# 不设 packet-buffering=0：该组同时用于点播 IJK，关缓冲会造成点播反复卡顿。
import json as _json

_ijk_groups = _json.loads("[" + INJECT_IJK + "]")
_IJK_EXTRA = [
    {"name": "min-frames", "category": 4, "value": "5"},
    {"name": "flush_packets", "category": 4, "value": "1"},
    {"name": "seek-at-start", "category": 4, "value": "0"},
    {"name": "sw-fallback", "category": 4, "value": "1"},
]
for _g in _ijk_groups:
    _have = {o["name"] for o in _g["options"]}
    for _o in _IJK_EXTRA:
        if _o["name"] not in _have:
            _g["options"].append(dict(_o))
# 第三组：与「硬解码·秒开」完全相同，仅 probesize 回到盒端实测的 4MB，供实机 A/B
_stable = _json.loads(_json.dumps(_ijk_groups[1]))
for _o in _stable["options"]:
    if _o["name"] == "probesize":
        _o["value"] = "4096000"
_stable["group"] = "硬解码·稳定4M"
_ijk_groups.append(_stable)
INJECT_IJK = ",".join(
    _json.dumps(g, ensure_ascii=False, separators=(",", ":")) for g in _ijk_groups
)
done.append("IJK 秒开参数补齐 min-frames/flush_packets/seek-at-start/sw-fallback + 4MB 对照")

# ----------------------------------------------------------------------------
# 4.9 IJK 起播加速参数（2026-10-24）
# ----------------------------------------------------------------------------
# 上游默认两组（软/硬解码）都缺 probesize 和 analyzeduration，ffmpeg 走默认值
# probesize=5MB / analyzeduration=5s，探测流信息慢，直播起播就慢。
# 这里在原两组之后追加「软解码·秒开」「硬解码·秒开」两组（原两组完全不动，可回退）：
#   probesize       1MB（默认 5MB）
#   analyzeduration 2s（默认 5s）
#   max-buffer-size 8MB（默认 15MB）
# 追加在数组末尾，ijkCodes.get(0) 兜底仍是原来的「软解码」，老用户行为不变。
try:
    ac = Doc("app/src/main/java/com/github/tvbox/osc/api/ApiConfig.java")
    ac.replace(
        "IJK 秒开参数组",
        '\\"group\\":\\"硬解码\\"}]',
        '\\"group\\":\\"硬解码\\"},' + INJECT_IJK.replace('"', '\\"') + ']',
        required=False,
        expect=1,
    )
    ac.save()
except SystemExit:
    skipped.append("ApiConfig.java 不存在，跳过 IJK 参数")

# ----------------------------------------------------------------------------
# 4.10 首页双列表（热播走豆瓣 / 分类网格走采集站）
# ----------------------------------------------------------------------------
try:
    _src = pathlib.Path(os.environ.get("GITHUB_WORKSPACE", ".")) / "tools/site-health/HomeHotDouban.java"
    if _src.exists():
        _dst = ROOT / "app/src/main/java/com/github/tvbox/osc/util/HomeHotDouban.java"
        _dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_src, _dst)
        done.append("注入 HomeHotDouban")

        _ha = Doc("app/src/main/java/com/github/tvbox/osc/ui/activity/HomeActivity.java")
        _ha.replace(
            "首页热播条加载豆瓣",
            '            mViewPager.setCurrentItem(currentSelected, false);\n        }\n    }',
            '            mViewPager.setCurrentItem(currentSelected, false);\n        }\n'
            '        // [观影听涛] 热播横条固定走豆瓣（有评分）；分类网格仍是首页数据源（最新）\n'
            '        mHandler.postDelayed(new Runnable() {\n'
            '            @Override\n'
            '            public void run() {\n'
            '                com.github.tvbox.osc.util.HomeHotDouban.load(HomeActivity.this);\n'
            '            }\n'
            '        }, 1500);\n'
            '    }',
            required=False,
            expect=1,
        )
        _ha.replace(
            "首页分类 tab 上限 13",
            '    private void updateSortData(List<MovieSort.SortData> newSortData) {\n'
            '        if (newSortData == null) {\n'
            '            newSortData = new ArrayList<>();\n'
            '        }',
            '    private void updateSortData(List<MovieSort.SortData> newSortData) {\n'
            '        if (newSortData == null) {\n'
            '            newSortData = new ArrayList<>();\n'
            '        }\n'
            '        // [观影听涛] 采集站分类 50+：按大类优先排序后只留 12 个，避免 tab 全是电影子类\n'
            '        if (newSortData.size() > 1) {\n'
            '            String[] tyCat = {"电影", "电视剧", "综艺", "动漫", "纪录片", "短剧", "体育", "少儿"};\n'
            '            List<MovieSort.SortData> tyRest = new ArrayList<>();\n'
            '            for (int tyI = 1; tyI < newSortData.size(); tyI++) tyRest.add(newSortData.get(tyI));\n'
            '            List<MovieSort.SortData> tyHead = new ArrayList<>();\n'
            '            for (int tyK = 0; tyK < tyCat.length; tyK++) {\n'
            '                for (int tyJ = 0; tyJ < tyRest.size(); tyJ++) {\n'
            '                    MovieSort.SortData tyD = tyRest.get(tyJ);\n'
            '                    if (tyD != null && tyD.name != null && tyHead.size() < 12 && tyD.name.startsWith(tyCat[tyK])) tyHead.add(tyD);\n'
            '                }\n'
            '            }\n'
            '            List<MovieSort.SortData> tyOut = new ArrayList<>();\n'
            '            tyOut.add(newSortData.get(0));\n'
            '            tyOut.addAll(tyHead);\n'
            '            for (int tyJ = 0; tyJ < tyRest.size() && tyOut.size() < 13; tyJ++) {\n'
            '                MovieSort.SortData tyD = tyRest.get(tyJ);\n'
            '                if (!tyHead.contains(tyD)) tyOut.add(tyD);\n'
            '            }\n'
            '            newSortData = tyOut;\n'
            '        }',
            required=False,
            expect=1,
        )
        _ha.replace(
            "热播条不被站点列表覆盖",
            '        if (absXml == null || absXml.videoList == null || UserFragment.homeHotVodAdapter == null) return;',
            '        if (com.github.tvbox.osc.util.HomeHotDouban.enabled()) return; // [观影听涛] 热播条由豆瓣填充\n'
            '        if (absXml == null || absXml.videoList == null || UserFragment.homeHotVodAdapter == null) return;',
            required=False,
            expect=1,
        )
        _ha.save()

        _uf = Doc("app/src/main/java/com/github/tvbox/osc/ui/fragment/UserFragment.java")
        _uf.replace(
            "热播条标题固定豆瓣",
            'homeSourceRec!=null?"站点推荐":"豆瓣热播"',
            '"豆瓣热播"',
            required=False,
            expect=1,
        )
        _uf.save()
    else:
        skipped.append("缺少 tools/site-health/HomeHotDouban.java")
except Exception as _e:
    skipped.append("首页双列表处理失败：%s" % _e)

# ----------------------------------------------------------------------------
# 4.11 体验细节（2026-11-06 实机测试后）
# ----------------------------------------------------------------------------

# C. 热播卡片：评分为 0 时不要显示「0」
try:
    _hv = Doc("app/src/main/java/com/github/tvbox/osc/ui/adapter/HomeHotVodAdapter.java")
    _hv.replace(
        "评分为0不显示",
        'if (item.note == null || item.note.isEmpty()) {',
        'if (item.note == null || item.note.isEmpty() || "0".equals(item.note.trim()) || "0.0".equals(item.note.trim())) {',
        required=False,
        expect=1,
    )
    _hv.save()
except SystemExit:
    skipped.append("HomeHotVodAdapter 不存在，跳过评分处理")

# D. 详情页：隐藏无意义的「播放地址」长直链
try:
    _dl = Doc("app/src/main/res/layout/activity_detail.xml")
    _dl.replace(
        "隐藏播放地址",
        'android:id="@+id/tvPlayUrl"\n                    android:layout_width="match_parent"',
        'android:id="@+id/tvPlayUrl"\n                    android:visibility="gone"\n                    android:layout_width="match_parent"',
        required=False,
        expect=1,
    )
    _dl.save()
except SystemExit:
    skipped.append("activity_detail.xml 不存在，跳过播放地址隐藏")

# D2. setTextShow 会把 view 设为 VISIBLE，光改布局没用，这里在方法入口拦掉
try:
    _dt = Doc("app/src/main/java/com/github/tvbox/osc/ui/activity/DetailActivity.java")
    _dt.replace(
        "隐藏播放地址(代码)",
        '    private void setTextShow(TextView view, String tag, String info) {\n',
        '    private void setTextShow(TextView view, String tag, String info) {\n'
        '        // [观影听涛] 详情页不展示播放直链（对用户无意义，还暴露源站）\n'
        '        if (view != null && view.getId() == R.id.tvPlayUrl) { view.setVisibility(View.GONE); return; }\n',
        required=False,
        expect=1,
    )
    _dt.save()
except SystemExit:
    skipped.append("DetailActivity 不存在，跳过播放地址隐藏（代码）")

# ----------------------------------------------------------------------------
# 4.12 直播播放器固定 EXO（不受远端配置缓存影响）
# ----------------------------------------------------------------------------
# 原来 ApiConfig 会用远端 config 的 lives[].playerType 覆盖 LIVE_PLAY_TYPE，
# 而配置走 CF 代理有缓存，导致"改配置改不动播放器"。这里直接固定。
try:
    _ac = Doc("app/src/main/java/com/github/tvbox/osc/api/ApiConfig.java")
    _ac.replace(
        "直播播放器固定",
        '            if(livesOBJ.has("playerType")){\n'
        '                String livePlayType =livesOBJ.get("playerType").getAsString();\n'
        '                Hawk.put(HawkConfig.LIVE_PLAY_TYPE,livePlayType);\n'
        '            }else {\n'
        '                Hawk.put(HawkConfig.LIVE_PLAY_TYPE,Hawk.get(HawkConfig.PLAY_TYPE, 2));\n'
        '            }',
        '            // [观影听涛] 直播播放器固定 EXO：IJK 硬解遇到不支持的 profile 会干等 10s 才切换\n'
        '            Hawk.put(HawkConfig.LIVE_PLAY_TYPE, 2);',
        required=False,
        expect=1,
    )
    _ac.save()
except SystemExit:
    skipped.append("ApiConfig.java 不存在，跳过直播播放器固定")

# ----------------------------------------------------------------------------
# 4.13 直播换源/换播放器超时 10s -> 4s -> 1.5s
# ----------------------------------------------------------------------------
# 原逻辑 (LIVE_CONNECT_TIMEOUT 默认 1 + 1) * 5000 = 10 秒才切下一条线路/播放器。
# 2026-11-06 实测切台中位 15.3 秒，其中 10 秒都花在等这个超时，压到 4 秒。
# 2026-11-12 云主机 T0 复测：12 次切台发生 10 次播放器切换，等待中位 4.035s；
# 同时对 154 条线路做分片级探活，m3u8 索引返回中位仅 0.133s。
# 结论：4 秒里约 3 秒是纯浪费，压到 1.5 秒（留足弱网余量，且失败会自动换源）。
try:
    _lp = Doc("app/src/main/java/com/github/tvbox/osc/ui/activity/LivePlayActivity.java")
    _lp.replace(
        "换源超时改 1.5 秒",
        '(Hawk.get(HawkConfig.LIVE_CONNECT_TIMEOUT, 1) + 1) * 5000L',
        '(Hawk.get(HawkConfig.LIVE_CONNECT_TIMEOUT, 0) + 1) * 1500L',
        required=False,
        expect=1,
    )
    _lp.save()
except SystemExit:
    skipped.append("LivePlayActivity 不存在，跳过超时调整")

# ----------------------------------------------------------------------------
# 4.14 按 host 记忆直播播放器（2026-11-06 第二轮复测后）
# ----------------------------------------------------------------------------
# 复测日志：88 次播放器切换 / 83 次起流 —— 几乎每次起播都要「先试 EXO，4 秒起不来
# 再切 IJK」。同一源站 host 对 EXO/IJK 的兼容性基本固定，记住上次真正播出画面的
# 那个类型，下次直接用，省掉这 4 秒。
try:
    _lpm = Doc("app/src/main/java/com/github/tvbox/osc/bean/LivePlayerManager.java")
    _lpm.replace(
        "host 记忆播放器",
        '    public void changeLivePlayerScale(@NonNull VideoView videoView, int playerScale){',
        '    // [观影听涛] 按 host 记住上次能起播的播放器类型（1=IJK 2=EXO），最多记 50 个 host\n'
        '    private static final String HOST_MEM_PREFIX = "live_pl_";\n'
        '    private static final String HOST_MEM_INDEX = "live_pl_index";\n'
        '    private static final int HOST_MEM_MAX = 50;\n'
        '\n'
        '    private static String hostOf(String url) {\n'
        '        if (url == null || url.isEmpty()) return "";\n'
        '        try {\n'
        '            String h = android.net.Uri.parse(url).getHost();\n'
        '            if (h == null || h.isEmpty()) return "";\n'
        '            return h.toLowerCase();\n'
        '        } catch (Throwable t) {\n'
        '            return "";\n'
        '        }\n'
        '    }\n'
        '\n'
        '    /** 起播前调用：这个 host 记住过播放器就直接用，不再试错 */\n'
        '    public void applyHostPlayerMemory(VideoView videoView, String url) {\n'
        '        if (videoView == null || currentPlayerConfig == null) return;\n'
        '        String host = hostOf(url);\n'
        '        if (host.isEmpty()) return;\n'
        '        int pl = Hawk.get(HOST_MEM_PREFIX + host, 0);\n'
        '        if (pl != 1 && pl != 2) return;\n'
        '        if (currentPlayerConfig.optInt("pl", 2) == pl) return;\n'
        '        try {\n'
        '            currentPlayerConfig.put("pl", pl);\n'
        '            defaultPlayerConfig.put("pl", pl);\n'
        '        } catch (JSONException e) {\n'
        '            return;\n'
        '        }\n'
        '        PlayerHelper.updateCfg(videoView, currentPlayerConfig);\n'
        '        LOG.i("echo-livePlayerMemory use pl=" + pl + " for " + host);\n'
        '    }\n'
        '\n'
        '    /** 画面真的出来之后调用：把当前播放器记到这个 host 名下 */\n'
        '    public void rememberHostPlayer(String url) {\n'
        '        if (currentPlayerConfig == null) return;\n'
        '        String host = hostOf(url);\n'
        '        if (host.isEmpty()) return;\n'
        '        int pl;\n'
        '        try {\n'
        '            pl = currentPlayerConfig.getInt("pl");\n'
        '        } catch (JSONException e) {\n'
        '            return;\n'
        '        }\n'
        '        if (pl != 1 && pl != 2) return;\n'
        '        if (Hawk.get(HOST_MEM_PREFIX + host, 0) == pl) return;\n'
        '        Hawk.put(HOST_MEM_PREFIX + host, pl);\n'
        '        String idx = Hawk.get(HOST_MEM_INDEX, "");\n'
        '        java.util.ArrayList<String> hosts = new java.util.ArrayList<String>();\n'
        '        for (String h : idx.split(",")) {\n'
        '            if (!h.isEmpty() && !h.equals(host)) hosts.add(h);\n'
        '        }\n'
        '        hosts.add(host);\n'
        '        // 超上限只从索引里丢掉最老的，残留的 Hawk 键不影响功能\n'
        '        while (hosts.size() > HOST_MEM_MAX) hosts.remove(0);\n'
        '        Hawk.put(HOST_MEM_INDEX, android.text.TextUtils.join(",", hosts));\n'
        '        LOG.i("echo-livePlayerMemory remember pl=" + pl + " for " + host);\n'
        '    }\n'
        '\n'
        '    public void changeLivePlayerScale(@NonNull VideoView videoView, int playerScale){',
        required=False,
        expect=1,
    )
    _lpm.save()
except SystemExit:
    skipped.append("LivePlayerManager 不存在，跳过 host 记忆播放器")

# 起播前应用记忆（必须在 canReusePlayer 之前，改了播放器类型就不能复用播放器）
try:
    _lp2 = Doc("app/src/main/java/com/github/tvbox/osc/ui/activity/LivePlayActivity.java")
    _lp2.replace(
        "起播前用 host 记忆",
        '            boolean reusePlayer = canReusePlayer(previousLivePlayerType);\n'
        '            boolean keepExoFrame = reusePlayer && previousLivePlayerType == 2;\n'
        '            if (showPreviousFrame && !keepExoFrame) {\n'
        '                showSwitchChannelSnapshot();\n'
        '            } else {\n'
        '                hideSwitchChannelSnapshot();\n'
        '            }\n'
        '            String liveUrl = currentLiveChannelItem.getUrl();\n',
        '            String liveUrl = currentLiveChannelItem.getUrl();\n'
        '            // [观影听涛] 这个 host 上次用哪个播放器能起，就直接用它起播\n'
        '            livePlayerManager.applyHostPlayerMemory(mVideoView, liveUrl);\n'
        '            boolean reusePlayer = canReusePlayer(previousLivePlayerType);\n'
        '            boolean keepExoFrame = reusePlayer && previousLivePlayerType == 2;\n'
        '            if (showPreviousFrame && !keepExoFrame) {\n'
        '                showSwitchChannelSnapshot();\n'
        '            } else {\n'
        '                hideSwitchChannelSnapshot();\n'
        '            }\n',
        required=False,
        expect=1,
    )
    # 切换播放器 = 上一个类型在这个 host 上起不来，此时才写记忆。
    # 不要在 playStateChanged 里写：EXO 常常短暂进一下 BUFFERED 就卡住，会把记错的值写进去，
    # 导致同一个 host 的记忆在 1/2 之间来回翻（v6 实测 125.93.74.27 就翻了 5 次）。
    _lp2.replace(
        "切播放器时写 host 记忆",
        '        allowLiveSwitchPlayer = false;\n'
        '        String retryUrl = isSHIYI && !TextUtils.isEmpty(playUrl) ? playUrl : currentLiveChannelItem.getUrl();\n'
        '        mVideoView.setUrl(retryUrl, liveChannelHeader());',
        '        allowLiveSwitchPlayer = false;\n'
        '        String retryUrl = isSHIYI && !TextUtils.isEmpty(playUrl) ? playUrl : currentLiveChannelItem.getUrl();\n'
        '        // [观影听涛] 换播放器了说明上一个在这个 host 起不来，把换后的记下来\n'
        '        livePlayerManager.rememberHostPlayer(retryUrl);\n'
        '        mVideoView.setUrl(retryUrl, liveChannelHeader());',
        required=False,
        expect=1,
    )
    _lp2.save()
except SystemExit:
    skipped.append("LivePlayActivity 不存在，跳过 host 记忆应用")

# ----------------------------------------------------------------------------
# 4.15 （已证伪，不做）「有缓冲就不急着切台」
# ----------------------------------------------------------------------------
# v7 试过：超时那一刻若 bufferedPercentage>0 就再宽限 2.5 秒。实测 29 次触发、
# 其中绝大多数宽限后照样得切 —— 这些源是 EXO 根本解不了（不是慢），缓冲一点就卡住。
# 结论：问题在播放器兼容性，不在超时阈值。解法是 4.14 的 host 记忆（切过就记住）。

# ----------------------------------------------------------------------------
# 4.16 一个台只允许换一次播放器（2026-11-06 v6/v7/v8 实测后）
# ----------------------------------------------------------------------------
# playStateChanged 的 PREPARED/BUFFERED/PLAYING 分支会把 allowLiveSwitchPlayer 置回 true，
# 于是「EXO 失败→切 IJK→IJK 失败→切回 EXO→…」会一直乒乓下去，每个来回多付 4 秒，
# 而且 host 记忆被两边轮流覆盖（v8 实测 52 次写入，同一 host 在 1/2 之间反复翻）。
# 改成只在 playChannel 里复位：一个台中途最多换一次播放器，换了还不行就换源。
try:
    _lp4 = Doc("app/src/main/java/com/github/tvbox/osc/ui/activity/LivePlayActivity.java")
    _lp4.replace(
        "播放器不再无限轮换",
        '                        currentLiveChangeSourceTimes = 0;\n'
        '                        allowLiveSwitchPlayer = true;\n'
        '                        break;',
        '                        currentLiveChangeSourceTimes = 0;\n'
        '                        // [观影听涛] 不在这里重置 allowLiveSwitchPlayer：\n'
        '                        // 一个台最多换一次播放器，换了还不行就换源，避免 EXO/IJK 乒乓\n'
        '                        break;',
        required=False,
        expect=1,
    )
    _lp4.save()
except SystemExit:
    skipped.append("LivePlayActivity 不存在，跳过播放器轮换限制")

# ----------------------------------------------------------------------------
# 4.17 手机遥控台（借鉴影视仓的「手机配置 / 电视播放」双端分工）
# ----------------------------------------------------------------------------
# 上游自带的 Web 页（res/raw/index.html）只能推片和填接口，看不到电视当前状态。
# 这里换成手机友好的单页：状态面板 + 改源 + 切画面比例 + 重启生效。
# 后端只加两个只读/白名单接口，其余复用原有的 /action。
print("== 手机遥控台 ==")
_webdir = pathlib.Path(os.environ.get("GITHUB_WORKSPACE", ".")) / "tools/taoying-web"
if (_webdir / "TaoyingStatus.java").exists():
    _dst = ROOT / "app/src/main/java/com/github/tvbox/osc/util/TaoyingStatus.java"
    _dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_webdir / "TaoyingStatus.java", _dst)
    done.append("注入 TaoyingStatus")
else:
    skipped.append("缺少 tools/taoying-web/TaoyingStatus.java")

try:
    _webdir / "index.html"
    if (_webdir / "index.html").exists():
        shutil.copyfile(_webdir / "index.html", ROOT / "app/src/main/res/raw/index.html")
        done.append("替换手机遥控台页面")
    _rs = Doc("app/src/main/java/com/github/tvbox/osc/server/RemoteServer.java")
    _rs.replace(
        "遥控台接口",
        '                } else if (fileName.equals("/action")) {',
        '                } else if (fileName.equals("/api/status")) {\n'
        '                    // [观影听涛] 手机遥控台：手机打开 http://盒子IP:9978/ 就能看到电视当前配置\n'
        '                    return NanoHTTPD.newFixedLengthResponse(NanoHTTPD.Response.Status.OK, "application/json; charset=utf-8",\n'
        '                            com.github.tvbox.osc.util.TaoyingStatus.json(com.github.tvbox.osc.base.App.getInstance()));\n'
        '                } else if (fileName.equals("/api/set")) {\n'
        '                    com.github.tvbox.osc.base.App tyApp = com.github.tvbox.osc.base.App.getInstance();\n'
        '                    String tyK = session.getParms().get("k");\n'
        '                    String tyV = session.getParms().get("v");\n'
        '                    if ("reboot".equals(tyK)) {\n'
        '                        com.github.tvbox.osc.util.TaoyingStatus.reboot(tyApp);\n'
        '                        return NanoHTTPD.newFixedLengthResponse(NanoHTTPD.Response.Status.OK, "text/plain; charset=utf-8", "restarting");\n'
        '                    }\n'
        '                    boolean tyOk = com.github.tvbox.osc.util.TaoyingStatus.set(tyK, tyV);\n'
        '                    return NanoHTTPD.newFixedLengthResponse(NanoHTTPD.Response.Status.OK, "text/plain; charset=utf-8", tyOk ? "ok" : "reject");\n'
        '                } else if (fileName.equals("/action")) {',
        required=False,
        expect=1,
    )
    _rs.save()
except SystemExit:
    skipped.append("RemoteServer 不存在，跳过遥控台接口")

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
