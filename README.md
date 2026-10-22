# 涛影 TaoYing（TVBox 个人定制版）

基于 [q215613905/TVBoxOS](https://github.com/q215613905/TVBoxOS) 的个人定制安卓影视壳，通过 GitHub Actions 在云端一键构建，**无需本地 Android 开发环境**。

本仓库本身不包含安卓源码，只存放定制工作流、图标资源和签名文件；每次构建时实时拉取上游最新源码并注入定制内容。

## 定制内容

| 项目 | 内容 |
|---|---|
| 应用名称 | **涛影**（构建时可在表单中自定义） |
| 包名 | `com.taoying.app`（与原版 TVBox 可共存，互不覆盖） |
| 内置订阅源 | 高天流云聚合源（经 ghproxy.net 国内加速），构建时可在表单中替换 |
| 图标 | 浪涛播放负形（纯图形），含各 DPI 启动器图标与 TV 横幅 |
| 构建产物 | 仅 `java` flavor，含 `armeabi-v7a` + `arm64-v8a` 双架构 |
| 签名 | 仓库内置 `TVBoxOSC.jks`（社区公开签名，同包名可覆盖升级） |

## 下载安装

进入本仓库的 **Releases** 页面，下载最新 `TaoYing_taoying-日期.apk`，传到安卓手机/电视盒子安装即可。首次启动会自动加载内置订阅源。

## 如何重新构建

1. 仓库页面点击 **Actions** 标签页
2. 左侧选择 **TaoYing Build**
3. 右侧点击 **Run workflow**，在弹出的表单中填写：
   - **应用显示名称**：默认「涛影」
   - **内置订阅源URL**：默认高天流云源，可粘贴任意你自己的订阅源地址
   - **发布到 Releases**：勾选则构建后自动发布，不勾选则仅在 Artifacts 中保留 30 天
4. 点击绿色 **Run workflow** 开始构建，约 10–15 分钟
5. 构建结束后，在该次运行页面底部 **Artifacts** 下载 APK，或到 Releases 查看

## 如何更换订阅源（两种方式）

**方式一：App 内更换（推荐，即时生效，无需重新打包）**

打开涛影 → 设置（齿轮）→ 配置地址 → 粘贴新的订阅源 URL → 确定。

**方式二：重新构建时内置**

在 Actions 的 Run workflow 表单「内置订阅源URL」中填入新地址，构建出的 APK 首次启动即使用该源。

> 注意：内置源仅在首次启动写入；之后以 App 内设置的地址为准，重新构建升级不会覆盖你已手动选择的源。

## 如何更换图标

替换 `custom/icons/` 下对应文件后重新运行构建即可（保持文件名和尺寸不变）：

| 文件 | 尺寸 | 用途 |
|---|---|---|
| `drawable-hdpi/app_icon.png` | 192×192 | 启动器图标 |
| `drawable-xhdpi/app_icon.png` | 256×256 | 启动器图标 |
| `drawable-xxhdpi/app_icon.png` | 384×384 | 启动器图标 |
| `drawable-xxxhdpi/app_icon.png` | 512×512 | 启动器图标 |
| `drawable/app_banner.png` | 320×180 | Android TV 启动器横幅 |

## 目录结构

```
├── .github/
│   └── workflows/
│       ├── taoying.yml      # 定制云构建工作流（核心）
│       └── TVBoxOSC.jks     # 签名库（alias/密码均为 TVBoxOSC）
└── custom/
    └── icons/               # 定制图标资源
        ├── drawable-hdpi/
        ├── drawable-xhdpi/
        ├── drawable-xxhdpi/
        ├── drawable-xxxhdpi/
        └── drawable/
```

## 构建时自动修改的内容

工作流在拉取上游源码后自动完成：
1. `applicationId` 改为 `com.taoying.app`
2. `app_name` 改为表单中的应用名称（默认「涛影」）
3. `App.java` 中注入内置订阅源（首次启动写入逻辑）
4. 替换全部启动器图标和 TV 横幅
5. 注入签名配置并执行 `./gradlew assembleJavaRelease`

## 免责声明

- 本项目仅供个人学习与技术研究使用，**不提供任何影视内容**，不内置任何资源站账号。
- 所有影视资源均来自网络上的公开订阅源，本软件只做聚合展示，不参与制作、上传、存储、下载。
- 请于安装后 24 小时内删除；请遵守当地法律法规，版权内容请通过正版渠道观看。
- 禁止用于任何商业用途。

## 致谢

- 上游源码：[q215613905/TVBoxOS](https://github.com/q215613905/TVBoxOS)
- 构建方案参考：[j4Uq/TVBoxOSC](https://github.com/j4Uq/TVBoxOSC)
- 感谢以上开源项目的作者。
