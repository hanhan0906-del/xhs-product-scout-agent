# 小红书选品 Agent — Codex 交接文档

最后更新：2026-07-29 17:18（Asia/Shanghai）

## 1. 项目目标

建立一个长期运行的“小红书虚拟商品选品工作台”：

1. 尽可能广泛地发现小红书虚拟商品；
2. 及时识别低粉账号带出的爆款商品；
3. 保存商品、笔记、账号、销量趋势和证据截图；
4. 输出候选品分析报告及原创复刻路径；
5. 用户人工核验候选品后，可以继续与“选品专家”长期交谈；
6. 日常采集以电脑上的安卓虚拟机为入口，真实记忆保存在本地数据库和项目文件中，不依赖无限聊天记录。

## 2. 用户已经确认的判断标准

### 低粉爆款

- 常用标准：账号粉丝少于 1 万、笔记点赞超过 1000、商品销量超过 100；
- 严格小账号标准：粉丝少于 200、点赞超过 100、销量超过 100；
- 时间上优先关注近 7 天，必要时结合近 30 天趋势；
- 评论区“求链接、已买、私我”等转化意图是辅助证据；
- 商品页证据与带货笔记作者必须完成关联，才能最终标为 A 级低粉爆款。

### 淘汰原因

- 账号粉丝已达到或超过 1 万，爆量更可能来自账号长期权重时，按高权重账号淘汰；
- 不因商品复杂而放弃。用户明确认为 AI 可以显著降低创作时间和现金成本，只要商品确实是爆款，就应继续跟进；
- 报告必须写清楚原创复刻可以从哪里入手、怎样实施以及具体路径。

### 当前证据等级

- A：低粉账号、笔记互动、商品销量和时间范围均已验证；
- B：商品销量、加购或新增趋势较强，但尚未完成作者粉丝验证；
- C：只有“销量飙升”等趋势提示，需要继续观察；
- D/淘汰：作者粉丝不少于 1 万等明确不符合条件的情况。

## 3. 安全边界

- 不抓包解密，不调用小红书未公开接口；
- 不使用代理池、多账号、设备伪装或其他方式规避平台限制；
- 不绕过验证码、滑块、登录验证、系统 UAC 或平台风控；
- 以正常用户可见页面、低频搜索、本地截图和 OCR 为基础；
- 小红书登录、短信验证码和风控提示必须由用户本人处理；
- 不在文档、代码或数据库中保存密码、Cookie、令牌或验证码。

## 4. 已完成并验证的工作

项目位置：

`C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent`

已完成：

- 建立 Python 项目、独立虚拟环境和 SQLite 数据库；
- 建立搜索任务队列、商品表、观察记录和候选评估表；
- 加入低粉笔记人工核验数据表；
- 实现截图 OCR；
- 解析商品标题、店铺、价格、累计销量下限、24 小时购买、24 小时加购、近 30 天新增、近 30 天新增好评、正在看人数和“销量飙升”；
- 明确区分“近 30 天新增好评”和“近 30 天新增销量”，防止误判；
- 实现 B/C 候选评分，以及录入作者粉丝和互动后升级 A 或淘汰高权重账号；
- 建立本地网页工作台；
- 支持打开证据截图；
- 支持下载候选品 CSV 数据库；
- 实现通用 ADB 控制层和“采集虚拟机当前画面”命令；
- 历史上曾建立一份标注为来自旧商品表的 78 词清单；后续核验发现没有完整处理原表，
  且用户已明确放弃该过时来源；
- 当前数据库共有 79 个搜索任务、4 个商品、7 条观察记录、3 个候选；第 4 个商品/第 7 条观察是 Android 11 首次截图的技术验证记录，标题为空、0 分、C 级，不是候选；
- 自动化测试结果为 `3 passed`；
- 工作台接口和 CSV 下载均返回 HTTP 200；
- 工作台已经过浏览器截图视觉检查。

### 已验证样例

“小学作文 30 次小练笔”识别结果：

- 价格：9.9 元；
- 累计销量下限：11,000；
- 24 小时购买下限：100；
- 24 小时加购下限：100；
- 近 30 天新增下限：200；
- 当前为 B 级，因为尚未关联作者粉丝和笔记互动证据。

## 5. 当前真实运行状态

### 选品工作台

- 地址：`http://127.0.0.1:8793`
- 监听地址：`127.0.0.1`
- 2026-07-23 21:42 检查时，端口 8793 正在监听；
- 2026-07-23 22:01 复核时，端口 8793 仍由 Python 监听，工作台首页返回 HTTP 200，标题为“小红书虚拟商品选品工作台”；
- 端口 8765 已被电脑上的另一个 Agent 使用，因此本项目固定使用 8793。

### BlueStacks

选择版本：

`BlueStacks 5.22.250.1016`

安装包：

`D:\CodexDownloads\BlueStacks\BlueStacksMicroInstaller_5.22.250.1016_native.exe`

已验证安装包 Authenticode 签名有效，签名者为 `Now.gg, INC`。

BlueStacks 已安装完成。2026-07-23 22:10 至 22:16 的实际复核结果：

- 主窗口已经正常打开，版本为 `5.22.250.1016`；
- 程序目录为 `C:\Program Files\BlueStacks_nxt`；
- 注册表 `HKLM\SOFTWARE\BlueStacks_nxt` 显示：
  - `DataDir = D:\app\BlueStacks_nxt\Engine\`
  - `UserDefinedDir = D:\app\BlueStacks_nxt`
- 当前虚拟机镜像位于 `D:\app\BlueStacks_nxt\Engine\Pie64`，其中 `Data.vhdx` 约 3.30 GB、`Root.vhd` 约 1.92 GB；
- 因此已确认大体积虚拟机数据在 D 盘，而不是 C 盘；
- 当前自动创建的实例是 `Pie 64-bit`，Android 9（SDK 28），不是目标 Android 11；
- 当前实例配置为 4 CPU、4096 MB 内存、1920×1080、240 DPI、60 FPS；
- `HD-Adb.exe` 位于 `C:\Program Files\BlueStacks_nxt\HD-Adb.exe`；
- 当前实例 ADB 端口为 5555，执行连接后设备可见；
- 用户已在多开管理器中选择 Android 11 64 位，并按 4 CPU、4096 MB、竖屏 1080×1920、x86 & ARM、240 DPI、单实例准备创建；
- 第一次 Android 11 镜像下载失败，界面仅显示“下载发生错误”；
- 失败时 D 盘约有 319.7 GB 可用，未发现 D 盘空间不足证据；C 盘仅约 2.82 GB 可用；
- `Player.log` 连续记录 `bridgeInstallImageProgressRpc: ipcSendToServer command failed, opcode = 3004`，同时运行中的 Pie64 实例仍占用虚拟磁盘；
- 用户停止/重开后第二次下载仍失败；2026-07-23 23:13 复核时 `HD-Player.exe` 仍在运行，管理器按钮仍显示“停止”，说明 Pie64 实例实际没有停止；
- 第二次失败日志给出直接错误：访问 BlueStacks 官方 Android 11 镜像地址时 `Cloud request failed: error Connection closed`，随后 `Some error occured while downloading image Rvc64`；
- Android 11 官方镜像 `Rvc64.exe` 的远端大小为 691,197,947 字节（约 659 MB）；使用直连方式执行 HEAD 请求返回 HTTP 200；
- Windows 用户代理当前启用，地址为 `127.0.0.1:7897`，对应 Clash Verge；直连 BlueStacks CDN 正常，因此代理链路是当前最可能的下载中断点；
- C 盘仅约 2.79 GB 可用，低于 BlueStacks 官方要求的至少 5 GB 可用空间；D 盘约 319.67 GB 可用；
- 下一步不要继续反复重试。应先真正停止 Pie64、把 C 盘可用空间安全提高到至少 5 GB（建议 8–10 GB），并让 `ak-build.bluestacks.com` 直连或临时关闭系统代理，再重试一次。
- 之后用户已成功完成 Android 11 镜像下载与实例创建；多开管理器中同时存在 Android 9 64 位与 Android 11 两个实例；
- Android 11 实例内部名为 `Rvc64`，显示名为 `BlueStacks App Player 1`；
- Android 11 配置已核实为 4 CPU、4096 MB、竖屏 1080×1920、240 DPI、x86/x64/ARM/ARM64；当前 `max_fps` 仍为 60，后续可降为 30；
- Android 11 镜像位于 `D:\app\BlueStacks_nxt\Engine\Rvc64`，`Root.vhd` 约 2.05 GB，确认大体积数据在 D 盘；
- Android 11 首次启动已完成，系统版本为 Android 11（SDK 30）；
- Android 11 ADB 端口为 5555，`HD-Adb.exe` 连接后设备状态为 `device`；
- 已创建 `config\emulator.json`，指向 `C:\Program Files\BlueStacks_nxt\HD-Adb.exe`、`127.0.0.1:5555` 和实例 `Rvc64`；
- 项目命令 `adb-status` 已验证成功；
- 项目命令 `capture-once` 已成功完成真实 ADB 截图、证据保存和 OCR；截图为 BlueStacks 商店首页，未识别出商品信号，候选数量未增加。
- Android 11 实例的持久语言为 `zh-Hans-CN`、时区为 `Asia/Shanghai`，但 BlueStacks 自动生成的虚拟 SIM/网络国家为美国（`device_country_code=840`、Android 属性为 `us`）；这没有改动用户的 Windows、Clash 或 Google 账号地区；
- BlueStacks 商店因此把官方应用显示为“REDnote—小红书国际版”，但 Google Play 官方条目 ID 仍为 `com.xingin.xhs`，开发者为“行吟信息科技（上海）有限公司”，与项目配置要求一致；小红书尚未安装。
- 2026-07-24 网络只读诊断确认：Android 11 虚拟网卡已经连接，接口为 `eth0`，地址为 `10.0.2.15/24`，网关为 `10.0.2.2`，并非完全断网；
- Android 网络能力显示 `INTERNET`，但状态为 `PARTIAL_CONNECTIVITY`，且 `everValidated=false`、`lastValidated=false`；界面 Wi-Fi 问号表示 Android 无法通过 Google 连通性验证；
- Google 登录界面明确报错“与 Google 服务器通信时出现问题”。当前最可能原因是中国大陆网络无法直接访问 Google，同时宿主机 Clash 仅监听 `127.0.0.1:7897`，BlueStacks 的独立 NAT 网络不会自动继承这个本机回环代理；
- 曾尝试只通过 ADB 建立反向端口并写入 Android 代理，但 `reverse` 和 `settings put global http_proxy` 均返回 `error: closed`，未生效；Android 代理设置没有被改变；
- 当前推荐路线是跳过 Google 登录/Google Play，改用可信的中国大陆官方应用商店或经验证的官方安装包安装 `com.xingin.xhs`。如必须使用 Google Play，可在用户明确同意后测试 Clash TUN 模式，同时保持代理开启；不要直接暴露本机代理端口或随意下载第三方 APK。
- 已从腾讯应用宝官方页面解析并下载小红书 APK 到 `D:\CodexDownloads\Xiaohongshu\com.xingin.xhs_9.39.0.apk`；应用宝页面标称开发者为“行吟信息科技（上海）有限公司”；
- APK 已验证大小为 167,432,164 字节，MD5 为 `2D63F7A315A34E5DF45905577D3AD701`，与应用宝页面完全一致；SHA-256 为 `844C1366183765FC6FE09C20182CABF989D9273043283391605416E0000A3A43`；
- `HD-Aapt.exe dump badging` 已确认包名 `com.xingin.xhs`、版本名 `9.39.0`、版本号 `9390805`；APK 内签名证书主体/颁发者为 `CN=xiaohongshu, OU=xingin, O=xingin`，证书 SHA-256 为 `f375f0f6af7c94c364b35cd6f6a66d64aefae66e32f935b48773c0faad04c121`；
- 使用 `HD-Adb.exe install -r` 安装时返回 `Connect error for write: closed`，因此尚未通过 ADB 安装；
- 曾为探测命令行参数执行 `HD-DataManager.exe --help`，意外弹出标题为“BlueStacks / Display Message”的空进度条窗口；这不是 APK 安装进度，也没有写入虚拟机。已确认其命令行并安全结束对应进程；
- 2026-07-24 16:53 和 2026-07-25 12:27 的 `Player.log` 均确认侧栏 APK 安装成功：`status = 0`，包名 `com.xingin.xhs`，版本 `9.39.0`，版本号 `9390805`；后续重复选择 APK 实际执行的是更新，不要再重复安装；
- BlueStacks 安装成功后连续出现 `bridgeOnApkInstallCompletedRpc` / `bridgeOnAppInstalledRpc: ipcSendToServer command failed`，因此主页图标和成功提示没有正常刷新，造成“点击打开后没有反应”的假象；
- 2026-07-25 12:29 已通过 `HD-Player.exe --instance Rvc64 --cmd launchApp --package com.xingin.xhs` 直接启动；日志确认 `com.xingin.xhs.index.v2.IndexActivityV2` 已显示，小红书进程 PID 11893 已建立连接。小红书现为“已安装且可启动”；
- `HD-Adb.exe devices` 能列出设备，但任何 shell/install 子命令仍返回 `error: closed`。这是 BlueStacks ADB/桥接异常，后续自动采集前仍需修复；不要把它误判成 APK 或小红书安装失败。

磁盘剩余空间：

- C 盘约 2.71 GB；
- D 盘约 317.46 GB。

C 盘空间仍然很紧张，但 BlueStacks 数据目录已经实际落在：

`D:\app\BlueStacks_nxt\Engine`

不要再迁移或重装当前已验证的 Android 11 实例；后续只需避免向 C 盘写入新的大体积缓存。

## 6. 尚未完成

按优先级排列：

1. 把 Android 11 实例最大帧率从 60 降到 30，并保持竖屏 1080×1920；
2. 用户本人完成小红书登录和任何验证码；
3. 恢复 BlueStacks ADB/桥接通道，使 shell 命令不再返回 `error: closed`；
4. 验证商品搜索页、商品详情页和作者主页能正常打开；
5. 在真实小红书页面运行 `采集虚拟机当前画面.cmd`，完成第一条小红书页面采集；
6. 根据真实页面坐标和 UI 树实现自动取任务、搜索、翻页、打开商品和关联作者的状态机；
7. 加入限速、暂停、失败重试和风控停止机制；
8. 完成一次从关键词任务到候选报告的端到端验收。

## 7. 新 Codex 接手后的前三步

### 第一步：只读核实 Android 11 与 ADB

- 确认运行的是 `Rvc64`，不要误启动旧的 Pie64；
- 确认 `D:\app\BlueStacks_nxt\Engine\Rvc64` 存在；
- 运行 `python -m xhs_scout.cli adb-status --adb "C:\Program Files\BlueStacks_nxt\HD-Adb.exe" --serial 127.0.0.1:5555`；
- 核实工作台 8793 仍返回 HTTP 200。

### 第二步：确认小红书并由用户登录

- 不要继续重复安装 APK；小红书 `com.xingin.xhs` 9.39.0 已安装；
- 如果主页没有图标，直接运行 `HD-Player.exe --instance Rvc64 --cmd launchApp --package com.xingin.xhs`；
- 登录、短信验证码、滑块和任何风控提示必须由用户本人处理；
- 不保存密码、Cookie、令牌或验证码。

### 第三步：先做真实页面采集，不先做全自动搜索

- 手动打开商品搜索页、商品详情页和作者主页；
- 在真实小红书页面运行 `采集虚拟机当前画面.cmd`；
- 核对截图、OCR、UI 树和入库结果；
- 确认稳定后再实现低频搜索状态机。

## 8. 重要文件与入口

- `README.md`：项目使用说明；
- `HANDOFF.md`：本交接文件；
- `当前进度与人工接力.md`：早期进度说明；
- `启动工作台.cmd`：打开本地工作台；
- `检查系统.cmd`：查看数据库和 ADB 状态；
- `采集虚拟机当前画面.cmd`：通过 ADB 截图并识别入库；
- `config\seed_keywords.txt`：79 个首批监控词的主要来源；
- `config\emulator.example.json`：ADB 配置示例；
- `data\xhs_scout.sqlite3`：项目事实数据库；
- `data\captures`：证据截图；
- `src\xhs_scout\signals.py`：页面信号解析和评分；
- `src\xhs_scout\ingest.py`：截图入库；
- `src\xhs_scout\emulator.py`：ADB 控制；
- `src\xhs_scout\web.py`：网页工作台；
- `src\xhs_scout\cli.py`：命令入口；
- `tests\test_signals.py`：解析规则测试。

## 9. 关键技术决策

- 使用安卓虚拟机而不是 iPhone，原因是电脑端可持续控制、截图、读取 UI 和保存数据；
- 使用 BlueStacks，是因为当前 Windows 已启用 Hyper-V，并且 BlueStacks 支持相关环境及自定义数据位置；
- 不把“模拟人工浏览”宣传成绝对安全或非爬虫；它仍属于自动化数据采集，需要低频、单账号、遇到风控立即暂停；
- 销量字段保存页面展示的下限，不伪造精确销量；
- 商品热度与低粉账号验证分开，商品页最多先给 B 级；
- 复杂商品不因创作成本被淘汰，最终报告必须提供原创复刻路径；
- 项目使用 8793 端口，以避免影响已占用 8765 的其他 Agent。

## 10. 不要重复或破坏的事项

- 不要重新创建另一个项目目录；
- 不要覆盖或删除现有 SQLite 数据库和证据截图；
- 不要停止占用 8765 端口的其他 Agent；
- 原 66,491 行历史 Excel 已按用户明确要求于 2026-07-29 移入 Windows 回收站；
  不得自行恢复或继续用它指导关键词；
- 不要把错误的“新增好评”重新当成“新增销量”；
- 不要在未核实作者粉丝前把 B 级商品升级成 A 级；
- 不要自动处理用户的登录、验证码或风控；
- 不要在未确认 D 盘数据目录前创建大体积 Android 实例；
- 不要重复启动多个 BlueStacks 安装器；
- 不要使用现有的损坏完整安装包作为可信安装源。

## 11. 建议给新 Codex 的开场指令

> 请完整读取 `C:\Users\Lenovo\AGENTS.md` 和 `C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent\HANDOFF.md`。先只读核实 BlueStacks 安装进程、安装目录、D 盘数据目录、磁盘空间和工作台端口，然后从交接文档“接手后的前三步”继续。不要重新设计或重做已经完成并验证的选品工作台。

## 12. 2026-07-25 下午续接记录

最后核验时间：2026-07-25 16:25（Asia/Shanghai）

- 用户已在 Android 11 `Rvc64` 实例内完成小红书账号登录；登录、验证码和风控仍只由用户本人处理。
- 选品工作台 `http://127.0.0.1:8793/` 返回 HTTP 200。
- `HD-Player.exe` 的 `Rvc64` 实例正常运行；ADB 设备可见，Android SDK 为 30。
- ADB 当前存在间歇性桥接异常：`getprop` 和 `screencap` 有时成功，但 `uiautomator dump` 与 `shell input tap` 返回 `error: closed`。已尝试 `HD-Adb kill-server`、`start-server` 和重新连接，输入仍失败；不要误判为小红书登录失效。
- 2026-07-25 16:10 的首次真实发现页采集成功，证据截图为 `data\captures\2026-07-25T16-10-49+08-00_emulator-current.png`。OCR 将页面海报中的 `￥1580` 误当成商品价格，产生第 8 条技术观察记录；保留该记录作为误分类证据，不删除数据库记录。
- 已在 `src\xhs_scout\signals.py` 和 `src\xhs_scout\ingest.py` 增加“必须存在标题、店铺或销量等强商品信号”的保护。仅识别出价格时保存截图但跳过入库。
- 自动化测试当前为 `5 passed`。2026-07-25 16:15 再次采集发现页时返回 `skipped=true`，采集前后数据库计数保持为 5 个商品、8 条观察、3 个候选，证明保护有效。
- 当前首个待处理任务为 `虚拟资料`（任务 id 1，attempts 0）。尚未改变任务状态。
- 下一步正在等待用户在小红书内手动执行一次低频导航：底部“市集” → 搜索“虚拟资料” → 打开一个明确显示价格或销量的商品详情，停在详情页。不得点赞、收藏、下单、评论或发布。
- 用户到达真实商品详情页后，先运行一次 `capture-once`，核对截图、OCR、强商品信号和数据库计数；再决定是否实现低频搜索状态机。
- 如用户同意重启 `Rvc64`，可把重启实例作为恢复 ADB 输入通道的下一种方案；重启前必须再次确认，不要清除应用数据、不要删除实例、不要重装小红书。

### 2026-07-25 17:35 后续节点

- 用户人工在“市集”搜索“虚拟资料”并打开真实商品详情。首次采集证据为 `data\captures\2026-07-25T17-17-41+08-00_emulator-current.png`。
- 已纠正真实页解析规则：标题为“职场新人快速成长指南知识库|求职+入职+认知+方法+SOP+思维模版”，店铺为“囍财”，价格 29.9 元，累计销量至少 12,000，近 30 天新增好评至少 1,500。
- 已补充“近 7 天购买”和“近 7 天感兴趣”字段；该商品识别为近 7 天购买至少 300、近 7 天感兴趣至少 2,000，候选分 80，证据等级 B。仍未关联低粉笔记作者，不得升级为 A。
- 商品记录为 product id 9，观察记录为 observation id 9。任务 id 1“虚拟资料”已完成并通过 `task_results` 关联，attempts 为 1；当前待搜索任务 78。
- 已新增稳定语义指纹，避免同一商品因截图文件大小变化被重复创建。旧的技术误分类记录仍保留。
- 已新增 `workflow.py` 和 `capture-task --task-id`：支持 running、paused、needs_manual_detail、risk_stopped、completed，并在安全验证、操作频繁、账号异常等可见停止信号出现时停止入库和任务推进。
- 当前测试为 `9 passed`。工作台 8793 已重新启动为 PID 36744，`/api/status` 与候选 CSV 均返回 HTTP 200；工作台已显示 `sales_7d_min=300`、`interested_7d_min=2000`、score 80。
- 数据库纠正前备份为 `data\xhs_scout.sqlite3.bak-20260725-1725`。
- 尚未完成的是自动点击搜索导航。ADB 截图可用，但 `shell input tap` 仍返回 `error: closed`；下一步要么在用户确认后重启 `Rvc64` 恢复输入通道，要么继续由用户人工搜索下一个关键词，再用 `capture-task` 完成受控采集。

### 2026-07-25 20:15 ADB 恢复与任务 2 节点

- 用户已授权只重启 Android 11 `Rvc64` 实例。没有清除应用数据、删除实例或重装小红书，登录状态保留。
- `D:\app\BlueStacks_nxt\bluestacks.conf` 原先为 `bst.enable_adb_access="0"`。已在实例停止时仅把本地 ADB 改为 `"1"`，`bst.enable_adb_remote_access` 继续保持 `"0"`；修改前备份为 `D:\app\BlueStacks_nxt\bluestacks.conf.bak-20260725-1800`。
- 重启后 `HD-Adb.exe -s 127.0.0.1:5555` 的状态为 `device`，`shell input tap`、按键、截图和剪贴板粘贴均已实测可用。
- 不要用 `adb shell monkey` 启动小红书；该方式会让 BlueStacks ADB 变为 offline/卡住。使用 `C:\Program Files\BlueStacks_nxt\HD-Player.exe --instance Rvc64 --cmd launchApp --package com.xingin.xhs` 启动。
- 重启后的首次小红书启动曾出现“没有响应”。日志显示 `ALARM_ACTION(com.xingin.xhs)` 广播接收超时，非内存或磁盘资源不足。一次仅针对 `com.xingin.xhs` 的 `am force-stop` 后，通过 `HD-Player.exe --cmd launchApp` 重开并等待，应用恢复，登录仍有效。
- `uiautomator dump` 返回的是 BlueStacks 游戏中心层级，而不是小红书真实 UI，不能把它作为小红书控件树使用；当前导航继续采用低频坐标操作且每一步截图复核。
- 任务 id 2“作文模板”的市集搜索已自动完成。中文输入采用临时写入 Windows 剪贴板、ADB `KEYCODE_PASTE`、随后恢复原剪贴板的方法，未记录或输出用户剪贴板内容。结果页证据为 `data\task2-results-retry.png`。
- 搜索结果页确认存在多款真实商品，例如“猫猫侠原创｜雅思写作急救模板”（券后 30 元，已售 3.7 万+，24 小时 200+ 人购买）和“2027 考研英语作文专用模板”（券后 9.9 元，已售 1.3 万+，7 天 300+ 人购买）。
- ADB 先后点击两个不同商品区域，均触发小红书进程重启并退回市集首页；第二次复核截图为 `data\task2-product-retry.png`。已停止重复自动点击，避免继续触发异常。
- 任务 id 2 已标记为 `needs_manual_detail`，attempts 为 1；未新增商品或观察记录。下一步需要用户在小红书内手动搜索“作文模板”，点开任一明确显示价格或销量的商品并停在详情页，然后运行 `capture-task --task-id 2`。不得点赞、收藏、下单、评论或发布。
- 已再次自动搜索并把小红书停在“作文模板”的商品结果页，待用户直接手动点选；当前画面证据为 `data\task2-ready-for-manual.png`。

### 2026-07-25 20:40 用户验收与范围澄清

- 用户实测亲手点击“作文模板”商品也会直接退回小红书首页，因此问题不属于 ADB 坐标点击，也不应继续要求用户重复人工点击。任务 id 2 已从 `needs_manual_detail` 改为 `paused`，attempts 保持 1，阻塞定义为 BlueStacks/小红书商品详情路由兼容性故障。
- 当前真实任务状态为：1 个 `completed`、1 个 `paused`、77 个 `pending`；`task_results` 只有任务 id 1 的 1 条正式关联结果，`note_evidence` 仍为 0。
- 第一个真实商品已经完成截图、OCR、入库、评分和任务关联，证据截图为 `data\captures\2026-07-25T17-17-41+08-00_emulator-current.png`，product id 9、observation id 9、任务 id 1 已完成。
- 工作台 `http://127.0.0.1:8793/` 当前由 PID 36744 监听并返回正常页面；页面显示 77 个待搜索任务、6 个数据库商品、9 条观察、4 个候选。它会每 10 秒刷新本地数据库，但这不等于已经实现定时访问小红书的监测循环。
- 当前网页是可用的本地 MVP：支持查看观察表、点击证据截图、查看候选分与证据理由、人工录入作者粉丝/互动数据、下载候选 CSV。它尚没有任务启动/暂停控件、监控周期设置、商品卡片/图集浏览、趋势图、异常日志页或完整分析报告页。
- `data\reports` 当前为空；系统只有规则评分和证据理由，尚未实现面向用户的完整选品分析报告生成。不得把当前评分表宣称为完整分析报告。
- 下一阶段优先级应为：先按 BlueStacks 官方兼容性建议逐项、可回滚地排查小红书崩溃（应用缓存、图形渲染器、设备配置；必要时才考虑独立兼容实例），修复详情页后再完成自动任务循环，最后补全报告生成和网页监控控制台。

### 2026-07-25 21:05 横向指标条多帧采集规范

- 用户提供的三张手机商品详情截图证明，价格/标题下方的灰色指标条是横向滑动区域，单张首屏无法覆盖全部信号。三张图合并后至少包含：近 30 天新增 2000+ 条好评、近 7 天 5000+ 人感兴趣、24 小时销量飙升、24 小时内 100+ 人购买过、24 小时内 200+ 人加购、近 30 天新增 200+ 人收藏。
- 后续详情页采集不得只截一张全屏。应先截首屏确认商品身份，再在灰色指标条内部使用真实触摸滑动，从右向左分段滑动并逐帧截图、OCR、合并。
- `AdbDevice.swipe()` 已存在，可用 ADB `input swipe` 生成触摸手势；不要依赖鼠标滚轮。BlueStacks 自带 Swipe 控件也可作为人工验证备用方案。
- 多帧合并规则：同一指标取可见下限的最大值，不求和；按规范化指标名去重；连续两次滑动没有出现新指标或指标条 ROI 图像基本不变时停止；建议最多 4 至 5 帧，避免无意义重复滑动。
- 必须新增独立字段 `favorites_30d_min`（近 30 天新增收藏）。不得继续用泛化的 `new_30d_min` 同时承载销量、收藏或好评；销量、新增收藏、新增好评必须分别保存。
- 当前还不能在虚拟机内完成实时验证，因为小红书商品详情页仍会在点击后重启并退回首页。先修复详情页兼容性，再验证指标条坐标、滑动方向、步长和停止条件。

### 2026-07-25 22:34 新对话接手核验与 ANR 复现

- 已在新 Codex 对话中完整读取 `C:\Users\Lenovo\AGENTS.md`、本 `HANDOFF.md` 和相关小红书 Agent 技能说明。技能说明主要适用于小红书内容实验 Agent，本项目仍以当前目录和本交接文档为事实来源。
- 项目目录仍为 `C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent`，目录存在且不是 Git 仓库。未发现需要回滚的 Git 状态。
- 工作台 `http://127.0.0.1:8793/` 返回 HTTP 200，标题为“小红书虚拟商品选品工作台”；端口 8793 仍由 Python 进程 PID 36744 监听。`/api/status` 返回 77 个待搜索任务、6 个商品、9 条观察、4 个候选；`/export/candidates.csv` 返回 HTTP 200。
- SQLite 只读核验结果：`search_tasks=79`，其中 `completed=1`、`paused=1`、`pending=77`；`products=6`、`observations=9`、`candidate_assessments=9`、`task_results=1`、`note_evidence=0`。任务 id 2“作文模板”仍为 `paused`，attempts 为 1，阻塞原因为用户手动点击和 ADB 点击均触发小红书进程重启并退回首页。
- BlueStacks `HD-Player.exe` 版本为 `5.22.250.1016`；`D:\app\BlueStacks_nxt\Engine\Rvc64` 存在，`Data.vhdx` 约 6.1 GB，`Root.vhd` 约 2.2 GB。`bluestacks.conf` 显示 `bst.enable_adb_access="1"`、`bst.enable_adb_remote_access="0"`，Rvc64 为 4 CPU、4096 MB、1080x1920、240 DPI、`graphics_engine="aga"`、`graphics_renderer="vlcn"`、`max_fps="60"`。
- ADB 只读核验：`HD-Adb.exe devices` 同时显示 `127.0.0.1:5555` 和 `emulator-5554` 为 `device`，两者读到的 SDK、机型、语言和小红书包路径一致，后续仍优先使用项目配置中的 `127.0.0.1:5555`，避免误连。`com.xingin.xhs` 已安装，SDK 30，语言 `zh-Hans-CN`。
- 本轮首次核验时，小红书前台已经卡在 Android 系统 ANR 对话框：`Application Not Responding: com.xingin.xhs`，截图证据保存在临时文件 `C:\Users\Lenovo\AppData\Local\Temp\xhs-rvc64-current-anr.png`。未对小红书执行清缓存、清数据、重装或配置变更。
- 执行一次应用级低风险恢复：仅 `am force-stop com.xingin.xhs`，随后用 `HD-Player.exe --instance Rvc64 --cmd launchApp --package com.xingin.xhs` 重开；未清除应用数据，未删除实例，未重装 APK。重开后小红书回到 `IndexActivityV2`，新 PID 为 10399，截图证据 `C:\Users\Lenovo\AppData\Local\Temp\xhs-rvc64-after-relaunch.png`。
- 恢复后短时间内，小红书在普通发现流页面再次出现“小红书没有响应”，截图证据为 `C:\Users\Lenovo\AppData\Local\Temp\xhs-step-current.png`。这次尚未进入市集商品详情，因此当前故障范围已经扩大为 Rvc64 + 小红书 9.39.0 在普通浏览状态也会 ANR，不只是商品详情点击坐标或详情路由问题。
- 最新日志证据显示：`ActivityManager` 在 2026-07-25 22:32:59 记录 `Completed ANR of com.xingin.xhs`，并出现 `Broadcast of Intent { act=ALARM_ACTION(com.xingin.xhs) }`、`mNotResponding=true`、输入事件注入超时、GL/Vulkan/egl 相关错误日志。当前内存证据不支持简单判断为宿主机内存不足，xhs 主进程 PSS 约 272 MB；更可疑方向是 BlueStacks 图形渲染/应用兼容性/小红书自身后台广播或缓存状态。
- 已按用户规则检索 BlueStacks 相关官方排查方向。当前推荐下一步必须先暂停自动采集，改为逐项、可回滚排查兼容性：第一优先级是保留登录数据的应用级恢复和必要时清小红书缓存；第二优先级是将 Rvc64 从 Vulkan 渲染切换到 OpenGL 或 DirectX/兼容渲染路径并重启实例；第三优先级是把 `max_fps` 从 60 降到 30；第四优先级是仅在前面无效且用户确认后创建独立兼容测试实例。不得清除小红书数据或重装 APK，除非用户明确确认。
- 代码层面发现 `src\xhs_scout\emulator.py` 的 `AdbDevice.launch()` 仍使用 `adb shell monkey` 启动应用，和前文“不要用 monkey 启动小红书”的经验冲突。后续应改为 BlueStacks `HD-Player.exe --cmd launchApp` 或在调用层避免使用该方法；本轮尚未改代码。

### 2026-07-25 23:18 小红书 ANR 兼容性修复节点

- 已按用户要求先检索资料再处理。BlueStacks 官方排查路径包括：应用强停、清缓存、切换图形/界面渲染器、更新显卡驱动，最后才重装。没有执行重装、清数据、删除实例或绕过风控。
- 已备份 BlueStacks 配置：`D:\app\BlueStacks_nxt\bluestacks.conf.bak-xhs-anr-20260725-225200`。后续如需回滚，可用该文件参考恢复。
- 第一轮：仅 `am force-stop com.xingin.xhs`、尝试清小红书外部缓存并执行 `pm trim-caches 2G internal`，不清应用数据。结果：仍在 2026-07-25 22:55 左右复现 ANR，说明单独清缓存无效。
- 第二轮：停止 Rvc64，把 `bst.instance.Rvc64.graphics_renderer` 从 `vlcn` 改为 `gl`，同时把 `bst.instance.Rvc64.max_fps` 从 `60` 改为 `30`。结果：OpenGL Only 路径更差，启动后出现黑屏并 ANR，证据截图为临时文件 `C:\Users\Lenovo\AppData\Local\Temp\xhs-after-gl-observe-4.png`。该方案已判定无效。
- 第三轮有效方案：恢复 `bst.instance.Rvc64.graphics_renderer="vlcn"`，保留 `bst.instance.Rvc64.max_fps="30"`，并把 `bst.qt_renderer` 从 `Auto` 改为 `DirectX`。当前实际配置：
  - `bst.instance.Rvc64.graphics_renderer="vlcn"`
  - `bst.instance.Rvc64.max_fps="30"`
  - `bst.qt_renderer="DirectX"`
- 有效性验证：使用 `HD-Player.exe --instance Rvc64 --cmd launchApp --package com.xingin.xhs` 启动小红书后，普通发现流连续 3 分钟稳定，无 ANR；随后进入底部“市集”，页面稳定；点击“雅思写作速成6.5模板”商品卡后成功进入 `com.xingin.commercial.goodsdetail.v2.activity.GoodsDetailActivityV2`，详情页连续 2 分钟稳定，无 ANR。此前“商品详情页点击后退回首页/ANR”的核心阻塞已修复到可继续验证的状态。
- 重要：修复有效组合是“Vulkan 路径 + BlueStacks Interface renderer DirectX + 30fps”。不要再把 Rvc64 切到 OpenGL Only；已验证会黑屏/ANR。
- 已在当前真实详情页执行一次低频 `capture-once` 验证采集链路，未启动自动搜索循环。新增记录：
  - 截图：`data\captures\2026-07-25T23-17-06+08-00_emulator-current.png`
  - product id 10，observation id 10
  - 标题：`雅思写作救急模板|短期速成选这个|一天速成6.5`
  - 价格 35.0 元，累计销量下限 1203，虚拟商品，证据等级 B，候选分 13.0。
- 当前数据库状态：77 个待搜索任务、7 个商品、10 条观察、4 个候选。工作台 `/api/status` 返回 HTTP 200。
- 已修改 `src\xhs_scout\emulator.py`：禁用 `AdbDevice.launch()` 的 `adb shell monkey` 路径，改为直接抛出 RuntimeError；新增 `launch_with_bluestacks_player()` 使用 BlueStacks `HD-Player.exe --cmd launchApp`。新增测试 `tests\test_emulator.py` 覆盖该保护。当前测试结果：`10 passed`。
- 下一步优先级：
  1. 在当前稳定配置下继续验证真实商品详情页灰色横向指标条：首屏确认商品身份后，在指标条 ROI 内用 ADB `input swipe` 分段横向滑动，多帧截图、OCR、去重合并。
  2. 新增数据库字段 `favorites_30d_min`，并区分新增收藏、新增好评、新增销量，不再混用 `new_30d_min`。
  3. 小步恢复任务 2 或新的单个关键词任务，不要直接大规模自动搜索。
  4. 再补任务启动/暂停控件、完整报告生成和工作台增强。

### 2026-07-26 06:44 指标字段与安全采集命令节点

- 用户明确表示暂时不用交接，继续完成任务。已继续实现灰色横向指标条采集的基础能力，但没有启动大规模自动搜索。
- 已新增独立字段 `favorites_30d_min`：
  - `src\xhs_scout\signals.py`：解析 `近30天新增200+人收藏`，并确保它不会误写入泛化的 `new_30d_min`；候选理由新增“近30天新增收藏至少...”，评分最多加 8 分。
  - `src\xhs_scout\db.py`：`observations` 表新增 `favorites_30d_min`，`connect()` 会对现有 SQLite 自动迁移。
  - `src\xhs_scout\ingest.py`：新字段入库。
  - `src\xhs_scout\web.py`：工作台 API、表格和 CSV 导出新增“近30天新增收藏下限”。
  - `tests\test_signals.py`：新增测试覆盖收藏不误判为销量。
- 已新增 `src\xhs_scout\detail_metrics.py` 和 CLI 命令 `capture-metrics-strip`：
  - 默认只做 ROI 预览，不滑动，避免误操作；
  - 只有显式传 `--swipe` 才会在 ROI 内横向滑动；
  - 采集帧保存到 `data\metric_strips\<timestamp>\`，同时保存全屏帧与 ROI 裁剪图；
  - 多帧合并规则按字段取最大可见下限，不求和；
  - 连续两帧无新指标或 ROI 图像重复时停止；
  - `--observation-id` 仅在识别到真实指标时才回写 observation；空 ROI 不再回写。
- 实测记录：
  - 第一次默认 ROI `(16,930,1064,1208)` 偏低，采到“已选/商品评价”区域；没有污染销量字段，但该 ROI 不适合当前详情页。
  - 此次错误 ROI 的滑动曾导致小红书退出到 BlueStacks 桌面；已据此改成“默认预览、不滑动，显式 `--swipe` 才滑动”的安全模式。不要再在未确认 ROI 的情况下直接滑动。
  - 重新打开小红书后，仍能稳定进入 `GoodsDetailActivityV2`，ANR 修复配置仍有效。
  - 当前实测商品“新人教七上七下英语公开课视频课件逐字稿”没有可见的灰色横向指标条，因此无法完成多指标滑动合并的端到端验证；只验证了 ROI 预览命令安全可用。
  - 安全预览示例命令：`python -m xhs_scout.cli capture-metrics-strip --roi 16 875 1064 1045 --max-frames 5`；该命令只截一帧，不滑动。OCR 识别出价格 13.9、已售 1444、标题和自动发货，但这不是灰色横向指标条验证。
- 当前工作台已重启为 PID 40764，`http://127.0.0.1:8793/api/status` 返回 HTTP 200，并包含 `favorites_30d_min` 字段。
- 当前测试结果：`11 passed`。
- 当前数据库状态：77 个待搜索任务、7 个商品、10 条观察、4 个候选。`favorites_30d_min` 字段已存在；当前 observation 10 的 `favorites_30d_min` 仍为空。
- 当前小红书前台状态：仍在商品详情页 `com.xingin.commercial.goodsdetail.v2.activity.GoodsDetailActivityV2`，未出现 ANR。
- 下一步建议：
  1. 找到一个真实存在灰色横向指标条的商品详情页，先运行不带 `--swipe` 的 ROI 预览，确认 ROI 只覆盖指标条。
  2. 只有确认 ROI 正确后，再运行带 `--swipe` 的多帧采集，例如 `capture-metrics-strip --observation-id <id> --roi <x1> <y1> <x2> <y2> --max-frames 5 --swipe`。
  3. 若当前页面没有灰色指标条，不要强行滑动；先换一个有“24小时购买/加购、近7天感兴趣、近30天新增收藏/好评”等横向指标的商品。
  4. 指标条端到端验证完成后，再恢复任务 2 或单个关键词任务；仍不要直接大规模自动搜索。

### 2026-07-26 12:55 Rvc64 稳定性复核与仍未解决的 ANR 边界

- 本轮继续执行前已只读核验：ADB `127.0.0.1:5555` 在线，工作台 `http://127.0.0.1:8793/api/status` 返回 HTTP 200，数据库仍为 7 个商品、10 条观察、4 个候选、77 个待搜索任务。当前测试结果为 `11 passed`。
- 复核旧样本确认灰色横向指标条位置：在 observation 9 的截图 `data\captures\2026-07-25T17-17-41+08-00_emulator-current.png` 中，指标条位于商品标题下方、约 `y=1120-1185`，内容包括“近30天新增1500+条好评”“近7天2000+人感兴趣”“近期店铺销量TOP1”“一周内300+人购买”等灰色胶囊标签。已保存参考裁剪图 `data\captures\metric_strip_reference_from_obs9.png`。
- 当前实测商品“新人教七上七下英语公开课视频课件逐字稿”详情页没有灰色指标条；不应在该页面强行执行横向滑动采集。
- 复现了新的稳定性边界：点击详情页顶部“搜索商品”入口后，`GlobalSearchActivity` 短暂出现，随后又回到详情页；再执行返回操作时，小红书出现系统 ANR“没有响应”。证据截图：`data\captures\xhs_anr_again_20260726_1243.png`。
- 按 BlueStacks 官方通用排查方向做了一个可回滚资源配置调整：先备份 `D:\app\BlueStacks_nxt\bluestacks.conf` 到 `D:\app\BlueStacks_nxt\bluestacks.conf.bak-xhs-ram-20260726-1246`，然后仅将 `bst.instance.Rvc64.ram` 从 `4096` 调为 `8192`；保留已验证较好的 `graphics_renderer="vlcn"`、`max_fps="30"`、`bst.qt_renderer="DirectX"`。未清数据、未重装 APK、未删除实例。
- RAM 调整已生效：Android 内 `MemTotal` 约 8,157,204 kB；重启后小红书首页 `IndexActivityV2` 连续 1 分钟稳定，没有 ANR。ADB 固定串口 `127.0.0.1:5555` 通过 `HD-Adb.exe connect 127.0.0.1:5555` 恢复在线。
- RAM 调整不是完整解决方案：点击底部“市集”后页面长时间白屏但无 ANR，且 UI 树仍残留旧商品详情结构；随后改走首页搜索并粘贴“职场新人快速成长指南”，`com.xingin.alioth.search.GlobalSearchActivity` 再次触发 ANR。证据截图：`data\captures\xhs_search_anr_20260726_1252.png`。
- 已执行最小恢复：`am force-stop com.xingin.xhs` 后用 `HD-Player.exe --instance Rvc64 --cmd launchApp --package com.xingin.xhs` 重启小红书。最终截图 `data\captures\final_state_20260726_1258.png` 显示回到首页发现流；当前窗口为 `IndexActivityV2`，没有 ANR 弹窗。
- 当前判断：8GB RAM 改善了资源余量和首页稳定性，但 Rvc64 + 小红书 9.39.0 在搜索 Activity、市集加载、部分商品详情路径上仍存在兼容性问题。不要继续用坐标盲点、不要启动自动搜索循环、不要在未确认 ROI 的页面执行 `--swipe`。
- 下一步建议必须先解决兼容性，而不是继续采集：
  1. 优先考虑用户确认后建立独立兼容性测试实例（更偏 ARM/ARM64 ABI 的实例路线），但这会涉及重新安装小红书和重新登录，必须先征得用户明确同意。
  2. 若不新建实例，则只能继续在当前 Rvc64 上做很小步的可回滚配置验证；已确认 OpenGL Only 无效且会黑屏/ANR，不要重试。
  3. 在搜索/市集稳定前，灰色指标条端到端采集只能用已有截图和当前 CLI 做离线/安全预览级验证，不能宣称真实多帧滑动采集已完成。

### 2026-07-26 14:30 独立兼容实例路线推进状态

- 已继续按官方方向推进：BlueStacks 对应用崩溃/黑屏/冻结类问题的官方排查路径包含创建全新实例并调整 ABI；本项目当前应优先验证独立测试实例，而不是继续在现有 Rvc64 登录实例上反复触发小红书搜索/市集 ANR。
- 已只读核验本机现有 BlueStacks 状态：`D:\app\BlueStacks_nxt\Engine` 仅有 `Pie64` 和 `Rvc64` 两个实例；`MimMetaData.json` 也只登记 `BlueStacks App Player` 与 `BlueStacks App Player 1`。D 盘仍有约 299 GB 可用，C 盘仅约 2.7 GB 可用；新实例仍应确认落在 D 盘 BlueStacks 数据目录。
- 当前 Rvc64 状态：小红书已 `force-stop`，BlueStacks 桌面可见，小红书数据未清理、未重装、未删除实例。截图证据：`data\captures\xhs_anr_residual_20260726.png`。
- 已打开 BlueStacks Multi Instance Manager。点击“多开引擎”后出现“新增多开引擎”弹窗，包含两个选项：
  - `全新多开引擎`：需要再次登录并安装所有内容；
  - `多开并复制应用`：复制所选多开引擎。
- 当前推荐选择 `全新多开引擎`，因为它不会复制当前 Rvc64 登录数据，也更适合作为隔离兼容性测试环境。不要选择“多开并复制应用”，除非用户明确要求复制当前实例。
- 当前阻塞：BlueStacks 该弹窗为 Qt 自绘控件，Windows UI Automation 只能识别外层窗口和关闭按钮；已尝试 UIA Invoke、鼠标坐标、键盘导航、Win32 `PostMessage`，均未能安全触发“全新多开引擎”。因此需要用户人工点击弹窗中的 `全新多开引擎` 一行。弹窗可见截图：`data\captures\mim_child_moved_20260726.png`。
- 用户人工点击后，Codex 下一步应继续：
  1. 截图确认进入配置页；
  2. 选择 Android 11 或 BlueStacks 当前可提供的兼容 Android 版本；
  3. ABI 优先选择 ARM/ARM64 或官方界面中最接近“ARM”的选项，不选择复制 Rvc64；
  4. 配置 4 CPU、至少 4GB 内存，建议 8GB；分辨率 1080x1920、240 DPI、30 FPS；
  5. 创建完成后确认新实例目录、ADB 端口和配置，不安装/登录小红书前先记录实例名。
- 安全边界仍然不变：不得删除或重置 Rvc64；不得清除当前小红书数据；不得重装当前 Rvc64 的小红书；不得用代理池、多账号、设备伪装或隐藏接口；新实例的小红书安装和登录若进入真实账号步骤，需要用户本人处理。

### 2026-07-26 16:20 Android 9 独立测试实例创建与首启验证

- 用户已人工创建全新 Android 9 64 位多开实例，BlueStacks 内部实例名为 `Pie64_2`，显示名为 `BlueStacks App Player 2`，实例目录为 `D:\app\BlueStacks_nxt\Engine\Pie64_2`。
- 只读核验配置：`Pie64_2` 为 4 CPU、4096 MB RAM、竖屏 1080x1920、320 DPI、`abi_list="x86,x64,arm,arm64"`、`graphics_renderer="vlcn"`、`max_fps="60"`；全局 `bst.qt_renderer` 仍沿用此前验证较好的 DirectX 路线。
- 新实例 ADB 固定端口为 `127.0.0.1:5575`，同时可见别名 `emulator-5574`。只读核验系统为 Android 9 / SDK 28，CPU ABI 为 `x86_64,x86,arm64-v8a,armeabi-v7a,armeabi`，设备型号 `SCG02`。
- 新实例初始未安装 `com.xingin.xhs`。已将此前验证来源、包名和版本的本地 APK `D:\CodexDownloads\Xiaohongshu\com.xingin.xhs_9.39.0.apk` 安装到 `Pie64_2`，ADB 返回 `Success`。此操作只作用于新实例，未重装或改动 Rvc64。
- 使用 `HD-Player.exe --instance Pie64_2 --cmd launchApp --package com.xingin.xhs` 启动小红书。首次停在启动页 `LoginDelaySplashActivity`，约 30 秒未进入下一页，但 `dumpsys window lastanr` 显示本次启动后无 ANR。截图：`data\captures\pie64_2_xhs_launch_20260726.png` 与 `data\captures\pie64_2_xhs_after_wait_20260726.png`。
- 网络低风险核验：Android 网络显示 `INTERNET` 但 `everValidated=false`，HTTP 代理为空；`ping www.xiaohongshu.com` 与 `ping 8.8.8.8` 均成功。语言 `zh-Hans-CN`，时区 `Asia/Shanghai`，虚拟 SIM 国家为 `jp`。WebView 提供方显示为 `com.android.chrome`。
- 执行一次最小恢复：仅 `am force-stop com.xingin.xhs`，随后用 BlueStacks 官方命令重启，不清数据。重启后成功进入 `com.xingin.login.overseas.OverseasLoginActivity` 验证码登录页，仍无 ANR。截图：`data\captures\pie64_2_xhs_relaunch_20260726.png`。
- 当前真实阻塞：新 Android 9 实例已经进入账号验证码页面，需要用户本人完成验证码/登录；Codex 不得读取、保存或代填验证码，不得要求用户把验证码、密码、Cookie 或令牌发到对话里。
- 下一步：用户完成 `Pie64_2` 登录后，只做低频手动验证：进入首页、搜索、市集、打开一个商品详情，观察是否还出现 Rvc64 上的回首页/ANR；确认稳定后再把项目 `config\emulator.json` 临时切到 `127.0.0.1:5575` 做 `capture-once`，仍不要启动大规模自动搜索。
- 2026-07-26 16:45 左右，用户反馈在 `Pie64_2` 小红书验证码页多次登录均提示“登录异常，请稍后再试”。该页面包含手机号和验证码，敏感信息不得写入交接文档。公开资料与本机现象共同指向账号/设备登录风控或连续重试限制，而不是 Android 9 闪退；当前建议停止继续重试，等待冷却或走小红书 App 内“帮助/账号申诉”等官方入口。不要尝试设备伪装、隐藏模拟器、代理池、多账号或绕过风控。
- 随后用户截图显示 `Pie64_2` 进入“小红书 - 安全限制”页，文案为“设备异常，请尝试关闭/卸载风险插件或重启尝试”。这进一步确认 Android 9 新实例当前被小红书登录安全策略识别为风险设备/环境，而不是 App 崩溃。该路线当前阻塞在平台风控边界，不能继续通过隐藏模拟器、Magisk、Xposed/LSPosed、风险插件隐藏、设备伪装、代理池或多账号方式绕过。

### 2026-07-26 17:30 Rvc64 恢复商品详情与指标条验证进展

- 用户反馈旧 Android 11 `Rvc64` 再次打开商品详情时没有屏闪/回首页。只读核验确认 `127.0.0.1:5555` 当前前台为 `com.xingin.commercial.goodsdetail.v2.activity.GoodsDetailActivityV2`，分辨率 `1080x1920`，`dumpsys window lastanr` 显示本次启动后无 ANR。
- 在当前商品详情页执行一次低频 `capture-once`，成功新增 product id 11 / observation id 11。截图证据：`data\captures\2026-07-26T17-20-12+08-00_emulator-current.png`。商品为“结构化面试话术素材开挂手册电子版知识服务”，价格 36.9，已售 3 万+，虚拟商品，证据等级 B。
- 灰色横向指标条 ROI 已验证：`--roi 16 1128 1064 1188` 能精准采到“近30天新增750+条好评”“近30天3000+人感兴趣”“近期店铺销量TOP1”“近30天内600+人购买”“1000+人收藏”。无滑动预览目录：`data\metric_strips\2026-07-26T17-21-02+08-00`。
- 执行一次带 `--swipe` 的多帧验证后发现边界：前两帧正确/重复，第三帧被页面其它区域污染，且当前页面被带到店铺商品列表区域。后续不要在已完整展示全部指标的商品上继续强行横向滑动；只有确认存在被遮挡的横向指标条时才用 `--swipe`，并要依赖污染帧过滤。
- 已修复解析与采集逻辑：
  - 新增 `sales_30d_min` 和 `interested_30d_min` 字段，避免把“近30天3000+人感兴趣”误写成泛化 `new_30d_min`；
  - “近30天内600+人购买”会写入 `sales_30d_min`；
  - 指标条采集遇到非指标条文本或重复帧会停止，污染帧不参与合并文本和指标更新；
  - 工作台 API/CSV/页面已补充“近30天购买”和“近30天感兴趣”字段。
- 已回填 observation 11：`sales_30d_min=600`、`interested_30d_min=3000`、`positive_reviews_30d_min=750`、`new_30d_min=NULL`，最新候选评分 61.0，等级 B。测试结果：`12 passed`。
- 注意：8793 工作台旧进程仍可能未加载新字段；Codex 尝试直接停止并隐藏重启 PID 40764 时被系统策略拦截。代码和数据库已更新，若页面/CSV 看不到新字段，需先关闭旧的 8793 工作台进程，再运行 `启动工作台.cmd`。
- 用户随后人工验证出一种灰色指标条左滑方式：需要先用鼠标在灰色条位置双击两下，让控件获得焦点，再向左拖动，才能拖动灰色指标条而不是外层页面。Codex 已据此新增 CLI 参数 `--focus-taps`、`--swipe-pixels`、`--swipe-ms`，但实测 ADB 的 `input tap` + `input swipe` 不能复现用户鼠标双击后的焦点选择效果：在 `--roi 16 970 1064 1018 --swipe --focus-taps 2 --swipe-pixels 420 --swipe-ms 650` 下，第一帧正确采到指标条，第二帧被带到店铺商品列表，污染帧被过滤，未合并入指标。证据目录：`data\metric_strips\2026-07-26T17-56-01+08-00`。当前结论：灰色条可以由用户鼠标手动左滑，但 ADB 方式暂不可靠；后续不要继续用 ADB 盲试，可采用“用户手动滑到下一段 -> Codex 截图/OCR”的半自动方案，或另行评估 Windows 鼠标级自动化。
- 2026-07-26 18:46 重新系统验证后，上述“ADB 暂不可靠”结论已修正：ADB 可以复现灰色指标条横向左滑，但需要更接近用户描述的“先选中控件”动作。有效参数为 `--focus-taps 4 --swipe-pixels 240 --swipe-ms 900`，ROI 按当前页面动态定位；在商品“【1年学习】商学提升计划...”页面，ROI `16 920 1064 973` 下成功从初始指标滑到右侧隐藏指标，未跳转外层页面。证据目录：
  - `data\metric_strips\2026-07-26T18-46-04+08-00`：第一段左滑成功，出现“店铺商品回购第3名”“24小时内200...”；
  - `data\metric_strips\2026-07-26T18-46-39+08-00`：继续左滑成功，完整识别“24小时内200+人加购”“近30天新增200+人收藏”。
- 由该测试发现并修复一个解析污染点：中间帧只露出半截“近30天新增200”时，不应写入泛化 `new_30d_min`。已要求泛化“近30天新增”必须包含 `+`，而明确类型如“近30天新增200+人收藏”仍写入 `favorites_30d_min`。当前测试结果：`13 passed`。

### 2026-07-27 交接前只读核验与下一阶段入口

- 交接前只读核验时间：2026-07-27（Asia/Shanghai）。
- `C:\Users\Lenovo\AGENTS.md` 已新增“受控实验与失败判断规则”：不要把一组参数失败误判为方案不可行；低风险、可观测、参数空间明确的场景可做默认 3 到 5 组有限受控实验；出现风控、验证码、安全限制、危险跳转、数据风险或不可解释异常应立即停止并汇报。
- 工作台状态：`http://127.0.0.1:8793/api/status` 返回 HTTP 200。当前统计为 77 个待搜索任务、8 个商品、11 条观察、5 个候选。用户若想看人类工作台页面，应打开 `http://127.0.0.1:8793/`，不要打开裸 JSON 接口 `/api/status`。
- ADB 状态：`HD-Adb.exe devices` 可见 `127.0.0.1:5555` 和 `emulator-5554`。项目 `config\emulator.json` 当前仍指向 `127.0.0.1:5555`、实例 `Rvc64`。
- 当前小红书状态：`Rvc64` 前台仍为商品详情页 `com.xingin.commercial.goodsdetail.v2.activity.GoodsDetailActivityV2`，`dumpsys window lastanr` 显示本次启动后无 ANR。
- 当前测试结果：`13 passed`。
- 当前最重要可继续工作的方向：
  1. 安全重启 8793 工作台，使新字段 `sales_30d_min`、`interested_30d_min` 在页面/CSV 中生效；此前直接停止并隐藏重启旧 PID 时被系统策略拦截，建议用户关闭旧工作台窗口后运行 `启动工作台.cmd`，或由新 Codex 用非破坏方式定位并重启本项目服务。
  2. 把灰色指标条能力产品化：动态定位 ROI，使用已验证参数 `--focus-taps 4 --swipe-pixels 240 --swipe-ms 900` 做低频横滑，多帧 OCR 合并去重，并防止半截指标污染。
  3. 做单个关键词、最多 1 到 3 个商品的小闭环：搜索、打开商品、截图/OCR、指标条采集、入库、候选评分。不要直接跑 77 个任务。
  4. 补齐候选报告：商品证据、趋势指标、风险点、原创化改写方向、低粉账号/笔记证据。
  5. 自动流程必须继续遵守边界：不绕过风控，不使用隐藏接口，不抓私密数据，不发布内容，不点击购买/加购/收藏/客服等交易或互动动作。
- Android 9 `Pie64_2` 路线当前不是主线：能启动小红书但登录进入“安全限制/设备异常”，不得用设备伪装、代理池、多账号、Magisk/Xposed/LSPosed 或隐藏风险插件等方式绕过。

### 2026-07-27 15:45 工作台重启、自动 ROI 与一次低频详情页闭环

- 本轮接手后已完整读取 `C:\Users\Lenovo\AGENTS.md` 和本文件，并按只读优先核验真实状态。
- 工作台重启结果：
  - 重启前 8793 由 PID `40764` 监听，命令行为 `python -m xhs_scout.cli serve --host 127.0.0.1 --port 8793`。
  - 已仅停止该项目 8793 服务进程，并用隐藏窗口重新启动同一服务；当前 8793 由 PID `43000` 监听。
  - `http://127.0.0.1:8793/api/status` 返回 HTTP 200，API 已包含 `sales_30d_min` 和 `interested_30d_min`。
  - `http://127.0.0.1:8793/export/candidates.csv` 返回 HTTP 200，CSV 表头已包含“近30天购买下限”和“近30天感兴趣下限”。
- 当前数据库统计已变为：77 个待搜索任务、9 个商品、12 条观察、6 个候选。
- 当前项目测试结果：`14 passed`。
- 代码变更：
  - `src\xhs_scout\detail_metrics.py` 新增灰色指标条自动 ROI 定位：未传 `--roi` 时先在当前截图中找候选灰色横条，再用 OCR/指标关键词选择真正的指标条。
  - `capture-metrics-strip` 的显式横滑默认参数已固化为已验证组合：`--focus-taps 4 --swipe-pixels 240 --swipe-ms 900`。仍然只有显式传 `--swipe` 才会滑动。
  - 自动 ROI 候选会惩罚非指标文本行，避免选择带商品长图/评论/图片文字污染的上沿区域。
  - 新增 `tests\test_detail_metrics.py`，用合成截图覆盖灰色横条候选定位。
- 真实低频采集：
  - 在当前 `Rvc64` 商品详情页运行一次 `capture-once`，新增 product id `12` / observation id `12`。
  - 商品页面为“【1年学习】商学提升计划|0-1搭建商业认知体系·商业思维课程”相关详情页；全屏 OCR 仍存在标题污染，把评论长句误识别成标题，后续需要修复标题提取局部规则。
  - observation 12 当前候选评分 `62.5`，等级 `B`；识别到 `cumulative_sales_min=3401`、`sales_7d_min=300`、`cart_24h_min=200`、`favorites_30d_min=200`，店铺为 `Builder OS的店`。
  - 截图证据：`data\captures\2026-07-27T15-42-47+08-00_emulator-current.png`。
- 自动 ROI 验证：
  - 不带 `--roi` 的预览成功定位 `roi=[16, 890, 1063, 951]`，识别“一周内300+人购买”“24小时内200+人加购”“近30天新增200+人收藏”；预览目录：`data\metric_strips\2026-07-27T15-42-09+08-00`。
  - 对 observation 12 执行一次最多 3 帧、显式 `--swipe` 的低频验证。第一帧正确，第二帧被商品长图文字污染；污染帧被标记 `ignored=true`，没有合并入库。证据目录：`data\metric_strips\2026-07-27T15-43-13+08-00`。
  - 该验证说明污染过滤有效，但在当前页面状态下横滑仍可能移动外层内容；后续不要连续试滑。应先确保指标条在首帧处于可见且可聚焦位置，必要时让用户手动把页面停在指标条区域，再由 Codex 预览/采集。
  - 横滑后再次运行自动 ROI 预览时没有找到指标条，并返回 `skip_reason`，没有误把商品长图灰色内容当成指标条；证据目录：`data\metric_strips\2026-07-27T15-44-46+08-00`。
- 当前小红书状态：`Rvc64` 前台仍为商品详情页 `com.xingin.commercial.goodsdetail.v2.activity.GoodsDetailActivityV2`，`dumpsys window lastanr` 显示本次启动后无 ANR。
- 当前安全边界与下一步：
  1. 不要直接跑 77 个任务，也不要启动大规模自动搜索。
  2. 搜索/市集路径仍有历史 ANR 风险；如要继续小闭环，优先让用户手动停在一个商品详情页或只做单关键词、1 个商品的受控实验。
  3. 下一步优先修复全屏 OCR 标题提取污染，再继续做候选报告与任务状态机。
  4. 如果继续指标条采集，先运行不带 `--swipe` 的自动 ROI 预览；只有首帧明确是指标条时才允许一次低频 `--swipe`，出现污染帧、风控、验证码、安全限制或不可解释跳转立即停止。

### 2026-07-27 15:52 受控小批量入口与当前批量条件判断

- 用户明确表示暂时不用交接，当前对话继续推进；不要再把“更新 HANDOFF.md”误当成要求新开对话。
- 当前结论：项目不适合直接无人值守跑 77 个任务，但已经具备“受控小批量/单商品 pilot”的基础。详情页截图、OCR、指标条、入库、评分、工作台展示均可运行；搜索/市集路径、低粉作者证据自动关联、异常恢复仍未达到无人值守批量要求。
- 已新增受控 runner：
  - `src\xhs_scout\workflow.py`：`capture_current_page_for_task()` 支持 `capture_metrics`、`metrics_roi`、`metrics_swipe`、`metrics_max_frames`，可把当前商品详情页的截图/OCR与指标条采集合并到同一个任务结果。
  - `src\xhs_scout\workflow.py`：新增 `next_startable_task()` 和 `capture_next_current_detail()`，只处理当前商品详情页，不执行搜索 UI，不点击交易/互动入口，默认最多 1 个任务/1 个商品。
  - `src\xhs_scout\cli.py`：`capture-task` 新增 `--metrics-strip`、`--metrics-swipe`、`--metrics-roi`、`--metrics-max-frames`。
  - `src\xhs_scout\cli.py`：新增 `pilot-current-detail`，用于“当前详情页 -> 截图/OCR -> 指标条 -> 入库 -> 任务状态”的小闭环。
- 已验证命令帮助：
  - `python -m xhs_scout.cli pilot-current-detail --help`
  - `python -m xhs_scout.cli capture-task --help`
- 测试结果仍为 `14 passed`。
- 注意：本轮没有在真实数据库上运行 `pilot-current-detail`，因为它会把“当前详情页”关联到队列中的下一个待处理关键词；如果当前页面与关键词不匹配，会污染任务结果。只有当用户确认当前页面就是要关联的关键词商品，或指定明确 `task_id` 后，才运行真实 pilot。
- 推荐推进顺序：
  1. 先修复全屏 OCR 标题污染，避免 observation 12 这类评论长句被当成商品标题。
  2. 用户或自动流程把小红书停在一个与任务关键词匹配的商品详情页后，运行 `capture-task --task-id <id> --metrics-strip`；若 ROI 首帧明确安全，再运行一次带 `--metrics-swipe` 的受控采集。
  3. 连续 3 到 5 个商品详情页 pilot 成功、无 ANR/风控/错链任务后，再接搜索 UI 自动化。
  4. 搜索 UI 自动化必须先做单关键词、最多 1 到 3 个商品的受控实验；成功率和停止逻辑达标后，才扩大到定时监控队列。

### 2026-07-27 16:03 标题污染修复与 pilot 错链保护

- 用户要求继续执行，不交接；本阶段继续在当前对话推进。
- 修复 OCR 标题污染：
  - `src\xhs_scout\signals.py` 的标题选择逻辑已从“全屏最长虚拟商品候选”改为综合评分：靠近价格/已售/到手价/商家券/发货/已选等商品购买区加权；评论区、商品评价、店铺口碑等区域降权；短宣传词降权；带 `【】`、`|` 且较长的商品标题加权。
  - 价格和累计销量也优先从最终选中的标题附近读取，避免取到上方商品长图里的旧价格/旧销量。
  - 新增真实结构测试：`test_real_detail_title_ignores_review_after_product_section`。
- observation 12 已本地回填：
  - 标题：`【1年学习】商学提升计划|0-1搭建商业认知体系·商业思维课程`
  - 店铺：`Builder OS的店`
  - 价格：`149.0`
  - 累计已售下限：`1177`
  - 趋势字段：`sales_7d_min=300`、`cart_24h_min=200`、`favorites_30d_min=200`
  - 最新候选评分：`56.9`，等级 `B`
- 已新增 pilot 错链保护：
  - `src\xhs_scout\workflow.py` 新增 `keyword_visible_on_page()`。
  - `capture_current_page_for_task()` 支持 `require_keyword_match`；若当前页 OCR 文本不包含任务关键词，则不把 observation 关联到该 task，并把 task 标记为 `needs_manual_detail`。
  - `pilot-current-detail` 默认要求关键词匹配；只有显式 `--allow-keyword-mismatch` 才允许不匹配关联。
  - `capture-task` 新增 `--require-keyword-match`。
- 当前测试结果：`16 passed`。
- 工作台已再次重启；当前 `http://127.0.0.1:8793/api/status` 返回 HTTP 200，统计仍为 77 个待搜索任务、9 个商品、12 条观察、6 个候选。当前端口监听 PID 为 `10308`。
- 当前 `Rvc64` 状态：`dumpsys window lastanr` 显示本次启动后无 ANR。
- 当前仍未运行真实 `pilot-current-detail`：队列前排任务为“作文模板、教师课件、飞书模板、人生管理系统...”等，与当前商学课程详情页不匹配；按新保护规则不应强行关联。
- 下一步最稳妥的真实 pilot：
  1. 由用户或后续单步自动化把小红书停在与某个任务关键词匹配的商品详情页；
  2. 运行 `python -m xhs_scout.cli capture-task --task-id <id> --metrics-strip --require-keyword-match`；
  3. 如果自动 ROI 首帧明确识别为灰色指标条，再追加一次 `--metrics-swipe --metrics-max-frames 3` 的低频采集；
  4. 连续 3 到 5 个匹配详情页成功后，再进入单关键词搜索 UI 自动化实验。

### 2026-07-27 16:45 路线图、运行日志、只读探测和搜索入口卡点

- 已新增 `ROADMAP.md`，列明从当前基础采集到长期广覆盖监控的阶段路线：基础采集闭环、当前详情页受控 pilot、单关键词搜索 UI 实验、小批量关键词队列、低粉证据关联、广覆盖监控。
- 已新增运行事件表 `run_events`：
  - `src\xhs_scout\db.py` 新增 `run_events` schema、`record_run_event()` 和 `recent_run_events()`。
  - `src\xhs_scout\workflow.py` 在任务开始、截图失败、风险停止、非商品页、关键词不匹配、指标条更新、任务完成等节点记录结构化事件。
- 已新增只读探测层：
  - `src\xhs_scout\probe.py` 和 CLI `probe-current-page`。
  - 探测内容包括 Activity、last ANR、截图、OCR、风险停止原因、页面类型、UI 树是否可读取，并保存到 `data\probes\<run_id>\`。
  - 已修复 Windows/ADB 中文输出的 UTF-8 解码问题，`ui_dump_ok=true`。
- 已新增页面类型识别：
  - `classify_page_text()` 可区分 `product_detail`、`shop_product_list`、`search_results`、`home_feed`、`risk_stop`、`forbidden_interaction_area`、`unknown`。
  - `capture-task` 会拒绝把非 `product_detail` 页面关联到任务。
  - 新增禁止交互页识别：`带货赚佣金`、`选品加橱窗`、`提醒商家开通` 会标记为 `forbidden_interaction_area`。
- 已执行一个真实当前详情页 pilot：
  - 在店铺商品列表页受控点击左侧商品卡片，成功进入商品详情页，无 ANR/风控。
  - 新增本地任务 `84 / 商学提升计划`。
  - 执行 `capture-task --task-id 84 --metrics-strip --require-keyword-match` 成功，生成 product id `13` / observation id `13`，任务状态 `completed`。
  - observation 13：标题 `【1年学习】商学提升计划|0-1搭建商业认知体系·商业思维课程`，店铺 `Builder OS的店`，价格 `149.0`，累计已售下限 `1200`，`sales_30d_min=900`，`positive_reviews_30d_min=400`，`interested_7d_min=4000`，等级 `B`，评分 `43.7`。
  - 指标条自动 ROI 预览成功，证据目录：`data\metric_strips\2026-07-27T16-42-06+08-00`。
- 搜索入口受控实验卡点：
  - 在当前详情页点击顶部搜索图标位置后，并未进入普通搜索页，而是进入 `com.xingin.xhs/com.xingin.reactnative.ui.XhsReactActivity` 的“带货赚佣金 / 选品中心”页面。
  - 页面包含 `选品加橱窗` 按钮，属于可能产生橱窗/带货互动的危险区域；未点击任何该类按钮。
  - 已立即停止搜索实验，并只执行一次 Android Back 返回商品详情页。
  - 返回后只读探测显示当前重新处于 `product_detail`，无 ANR/风控。
  - 因此当前搜索入口路线被判定为卡点：不能继续用该坐标/入口做搜索自动化。
- 当前测试结果：`20 passed`。
- 下一步必须讨论或改走替代路线：
  1. 从首页/发现页的普通搜索入口重新做受控实验，而不是从商品详情页顶部图标进入；
  2. 或先让用户手动进入普通搜索页，Codex 只从普通搜索页开始做输入/结果页识别；
  3. 或先实现更严格的 UI 树/按钮文本定位，确认目标控件是普通搜索框后才允许点击。
### 2026-07-27 17:30 搜索入口纠偏、单关键词小闭环、任务表迁移与报告生成

- 本阶段继续在当前对话推进，用户明确要求不要因为更新 `HANDOFF.md` 就要求重新交接；本节为滚动状态记录，不代表需要新开对话。
- 用户通过截图纠正：商品详情页顶部左侧的放大镜才是普通 `搜索商品` 入口；相邻右侧图标会进入 `带货赚佣金/选品中心`。后续自动化不得盲点相邻坐标，必须优先使用 UI 树 `content-desc="搜索商品"` 或探测确认。
- 已按低频受控路径完成一次单关键词搜索链路：
  - 当前详情页点击正确搜索入口后进入 `com.xingin.xhs/com.xingin.alioth.search.GlobalSearchActivity`，无 ANR、无风险信号；
  - 点击历史关键词 `虚拟资料` 后进入结果页，再点击 `商品` tab；
  - 结果页探测目录：`data\probes\probe-2026-07-27T17-07-55+08-00`，页面类型识别为商品结果/商品列表；
  - 从结果页首个商品卡片进入商品详情，探测目录：`data\probes\probe-2026-07-27T17-09-24+08-00`，Activity 为 `GoodsDetailActivityV2`，无 ANR、无风险信号。
- 已完成任务 85 的真实采集闭环：
  - 任务：`85 / 虚拟资料`；
  - 商品：product id `13`，observation id `14`；
  - 标题：`【1年学习】商学提升计划|0-1搭建商业认知体系·商业思维课程`；
  - 店铺：`Builder OS的店`；
  - 价格：`149.0`；
  - 趋势字段：`cumulative_sales_min=1202`、`sales_30d_min=900`、`cart_24h_min=100`、`positive_reviews_30d_min=400`、`favorites_30d_min=200`、`interested_7d_min=4000`；
  - 候选评分：`57.7`，等级 `B`；
  - 任务状态：`completed`，attempts `1`。
- 灰色指标条本次使用 `--metrics-strip --metrics-swipe --metrics-max-frames 5` 完成多帧合并，确认可从右侧隐藏指标补到 `cart_24h_min` 与 `favorites_30d_min`。
- 修复长期监控必须解决的任务表缺陷：
  - 旧结构 `UNIQUE(keyword,status)` 会导致同一关键词已有 completed 后，下一轮同关键词任务无法完成；
  - 已迁移为 `idx_search_tasks_active_keyword`：同一关键词只限制 pending/running/paused/needs_manual_detail/risk_stopped 等活跃任务唯一，允许多条 completed 历史；
  - 任务 85 曾因旧约束异常停在 `running`，已在迁移后关联 observation 14 并恢复为 `completed`；
  - 测试覆盖同关键词多轮 completed、活跃任务去重和旧库迁移。
- 已新增搜索来源证据表 `search_result_evidence`：
  - observation 14 已登记 `source_keyword=虚拟资料`、`result_rank=1`、`page_kind=shop_product_list`、`search_probe_dir=data\probes\probe-2026-07-27T17-07-55+08-00`；
  - `dashboard_stats()` 已能带出 `search_source_keyword`、`search_result_rank`、`search_probe_dir`、`search_screenshot_path`；
  - `web.py` 的 CSV 查询已增加搜索来源字段，但当前监听 8793 的旧进程可能尚未加载这次 `web.py` 变更。
- 已新增候选分析报告生成：
  - 新文件：`src\xhs_scout\reports.py`；
  - 新命令：`python -m xhs_scout.cli report-candidates --limit 10`；
  - 最新报告：`data\reports\candidates-2026-07-27T17-29-10+08-00.md`；
  - 报告包含商品证据、趋势指标、入选理由、风险点、原创化改写方向、低粉账号/笔记证据状态。
- 当前工作台/数据库/ADB 状态：
  - `http://127.0.0.1:8793/api/status` 返回 HTTP 200；
  - 8793 当前监听 PID：`10308`；
  - 数据库统计：`77` 个 pending tasks、`10` 个 products、`14` 条 observations、`7` 个 candidates；
  - `Rvc64` 当前可通过 ADB 访问，项目配置仍指向 `127.0.0.1:5555`；
  - 最后只读探测：`data\probes\probe-2026-07-27T17-29-42+08-00`，Activity 为 `GoodsDetailActivityV2`，OCR/Page kind 当前偏向店铺商品列表视图，`has_anr=false`，无风控停止信号。
- 当前测试结果：`25 passed`。
- 当前卡点/注意事项：
  - 本地执行策略阻止 Codex 直接 `Stop-Process` 重启 PID 10308；如果页面/CSV 看不到刚新增的搜索来源字段，需要用户手动关闭旧工作台窗口，或用允许的进程管理方式只重启本项目 8793 服务；
  - 当前小红书停在 `GoodsDetailActivityV2` 内的店铺商品列表视图，不是标准商品详情首屏；下一次采集前必须先探测页面类型，不要直接关联任务；
  - 仍不得启动 77 个任务的大规模自动采集；下一步最多做 1 个关键词、1 到 3 个商品的受控实验。
- 下一步优先级：
  1. 将“正确搜索入口 -> 搜索页 -> 商品 tab -> 商品卡片 -> 详情 -> capture-task”的链路封装为一个带硬上限的 pilot 命令，默认最多 1 个关键词、1 个商品；
  2. 增加 UI 树定位规则：用 `content-desc="搜索商品"`、tab 文本和商品卡片区域定位，禁止点击带货/佣金/选品/购物/客服控件；
  3. 增加结果卡片打开后的回退和页面复核，不是 `product_detail` 就停止并记录；
  4. 把运行事件和搜索来源证据展示到工作台；
  5. 再补低粉笔记/账号证据采集与报告升级规则。

### 2026-07-27 18:52 搜索归属保护、软阻塞修复、单次真实 monitor 闭环与工作台重启

- 本阶段继续在当前对话推进，用户明确要求只看最终结果；本节为滚动状态记录，不代表需要新开对话。
- 已修复搜索结果页关键词归属保护：
  - `src\xhs_scout\ui_automation.py` 新增 `find_top_query_text()`，用于读取搜索结果页顶部查询框文本；
  - `src\xhs_scout\monitor.py` 新增 `_keyword_matches_search_page()`，优先以顶部查询词判断页面归属；
  - 如果顶部查询词不是当前任务关键词，即使 OCR 结果列表里碰巧出现目标词，也不会继续点击商品卡片，避免“虚拟资料”结果页误处理“飞书模板”任务。
- 已收敛搜索页重置策略：
  - 从旧搜索结果页切换关键词时，优先 Android Back 回到搜索输入页；
  - 回退失败后，最多尝试 `全部删除` 与顶部查询框两个目标；
  - 仍打不开搜索输入页时停止并记录，不做无限坐标试错。
- 已修复商品打开错误页处理：
  - `src\xhs_scout\signals.py` 将 `常在网上混，总有卡住的时候` 识别为 `open_error`；
  - `monitor.py` 将该类页面作为软失败，任务标记为 `needs_manual_detail`，并记录 `last_block_reason`，不再误判为风控熔断；
  - 成功完成真实轮次时会清空旧的 `last_block_reason`。
- 已补充测试：
  - 顶部查询框文本读取；
  - `open_error` 页面分类；
  - 搜索结果页关键词归属优先使用顶部查询词；
  - 当前测试结果：`32 passed`。
- 已完成一次真实单关键词、单商品闭环：
  - 先用当前 `GlobalSearchActivity` / `shop_product_list` 页面做干跑，验证旧查询页不会误点商品；
  - 为当前页面顶部查询词 `虚拟资料` 创建受控单次任务 `86`，修正了一次 PowerShell 管道造成的中文写入 `????` 问题，最终任务关键词已恢复为 `虚拟资料`；
  - 执行 `monitor-once --ignore-paused --max-keywords 1 --max-products-per-keyword 1 --metrics-max-frames 3 --wait-seconds 6` 成功；
  - run id：`monitor-846dc0dfd05c`；
  - product id：`16`，observation id：`16`；
  - 标题：`让你比同龄人快3年的效率系统`；
  - 趋势字段：`sales_30d_min=800`、`positive_reviews_30d_min=400`、`interested_7d_min=2000`；
  - 候选评分：`40.7`，等级 `B`；
  - 搜索来源：`虚拟资料`，搜索结果位次 `1`；
  - 最新报告：`data\reports\candidates-2026-07-27T18-49-00+08-00.md`。
- 已安全重启本项目工作台：
  - 旧 8793 进程 PID：`9360`，命令行为 `python -m xhs_scout.cli serve --host 127.0.0.1 --port 8793`；
  - 新 8793 进程 PID：`30388`；
  - 未处理 8765 或其它 Agent；
  - `http://127.0.0.1:8793/api/monitor/status` 返回 HTTP 200，`risk_stop_reason=null`，`last_block_reason=null`；
  - `http://127.0.0.1:8793/api/status` 返回 HTTP 200；
  - CSV 表头已包含 `近30天购买下限`、`近30天感兴趣下限`、`搜索来源关键词`、`搜索结果位次`、`搜索证据目录`。
- 当前数据库统计：
  - `pending_tasks=75`；
  - `products=12`；
  - `observations=16`；
  - `candidates=8`。
- 当前 ADB/小红书状态：
  - `HD-Adb` 可见 `127.0.0.1:5555 device`，另有 `emulator-5554 device`；
  - 项目配置仍指向 `127.0.0.1:5555`；
  - 最新只读探测：`data\probes\probe-2026-07-27T18-49-22+08-00`；
  - 前台 Activity：`com.xingin.xhs/com.xingin.alioth.search.GlobalSearchActivity`；
  - 页面类型：`shop_product_list`；
  - 顶部查询词：`虚拟资料`；
  - `has_anr=false`，`risk_stop_reason=null`。
- 当前仍未达到 24 小时全自动全类监控：
  - 已具备单关键词、单商品受控闭环能力；
  - 小批量前还必须继续强化搜索输入真实重置、结果卡片定位、详情页错误恢复、指标条 ROI 失败兜底、低粉笔记/账号证据关联、定时调度和熔断策略；
  - 不得直接运行剩余 75 个任务。
- 下一步优先级：
  1. 修复/增强从旧搜索结果页切到新关键词的真实 UI 操作，优先验证 Back 到搜索输入页；
  2. 改进商品卡片定位与 result_rank 证据，避免长图 OCR 造成标题和卡片错位；
  3. 对 observation 16 这类指标条 ROI 失败样本补二次定位或手动 ROI 入口；
  4. 增加低粉笔记/账号证据采集与报告升级规则；
  5. 将工作台暂停/恢复、运行事件、最近失败、下一轮计划做成可操作控制面板；
  6. 在连续多个单关键词闭环成功后，才扩展到 3 到 5 个关键词的小批量队列。

### 2026-07-27 19:07 第二次真实闭环、回退复核与工作台单轮控制

- 已继续完成第二次真实单关键词、单商品闭环，验证从搜索输入页进入新关键词链路：
  - run id：`monitor-7a3103bc1ad0`；
  - 任务：`5 / 人生管理系统`；
  - product id：`17`，observation id：`17`；
  - 标题：`游戏化人生管理系统|多功能工作计划记账Ai情绪陪伴`；
  - 价格：`29.9`；
  - 累计销量下限：`904`；
  - 指标条合并成功：`sales_30d_min=700`、`positive_reviews_30d_min=150`、`favorites_30d_min=100`、`interested_7d_min=2000`；
  - 候选评分：`42.8`，等级 `B`；
  - 搜索来源：`人生管理系统`，搜索结果位次 `1`；
  - 最新报告：`data\reports\candidates-2026-07-27T18-56-22+08-00.md`。
- 已新增采集后回退复核：
  - `src\xhs_scout\monitor.py` 增加 `_recover_to_search_results_after_detail()`；
  - 采集成功后最多执行两次 Android Back，并用只读 probe 验证是否回到 `GlobalSearchActivity` 的 `search_results/shop_product_list`；
  - 若仍未回到搜索结果页，会记录 `post_capture_back_failed`、设置 `last_block_reason` 并暂停，避免循环监控停在详情页内继续错链。
- 已新增工作台人工值守单轮入口：
  - `src\xhs_scout\web.py` 新增 `POST /api/monitor/run-once`；
  - 首页新增 `执行单轮` 按钮；
  - 默认限制为 `max_keywords=1`、`max_products_per_keyword=1`、`wait_seconds=6`、`metrics_max_frames=3`；
  - 该按钮只是人工触发的受控单轮，不会自动启动长期循环。
- 已再次重启并验证工作台：
  - 当前 8793 PID：`50792`；
  - 首页 HTTP 200，页面包含 `执行单轮`；
  - `/api/monitor/status` 返回 `risk_stop_reason=null`、`last_block_reason=null`；
  - CSV 表头仍包含新增趋势与搜索来源字段。
- 当前测试结果：`32 passed`。
- 当前数据库统计：
  - `pending_tasks=74`；
  - `products=13`；
  - `observations=17`；
  - `candidates=9`。
- 当前小红书/ADB 状态：
  - 最新只读探测：`data\probes\probe-2026-07-27T18-56-45+08-00`；
  - 前台 Activity：`com.xingin.xhs/com.xingin.commercial.goodsdetail.v2.activity.GoodsDetailActivityV2`；
  - 页面类型：`product_detail`；
  - 页面商品：`游戏化人生管理系统|多功能工作计划记账Ai情绪陪伴`；
  - `has_anr=false`，`risk_stop_reason=null`。
- 当前结论：
  - 项目已具备“人工值守下的单关键词/单商品自动采集监控闭环”；
  - 还不应启动 24 小时无人值守全量监控；
  - 下一步应先扩大到 3 到 5 个关键词的小批量受控队列，并补低粉笔记/账号证据链。

### 2026-07-27 20:24 小批量闭环复核、相关笔记/公开账号证据链与工作台重启

- 已完成一次受控小批量 `monitor-once` 结果复核：
  - run id：`monitor-448bd22a6439`；
  - 默认仍保持人工值守，不启动 24 小时循环；
  - 任务 `6 / 小学学习资料` 因打开页为 `unknown` 被软跳过，任务状态进入 `needs_manual_detail`，未误判为风控；
  - 任务 `7 / 初中学习资料` 完成：product id `18`，observation id `18`，标题 `2026新初一初二初三语文数学英语生物化史地道法知识点电子版`，`sales_30d_min=1000`、`positive_reviews_30d_min=1500`、`interested_7d_min=2000`，评分 `67.7`，等级 `B`；
  - 任务 `8 / 高中学习资料` 完成：product id `19`，observation id `19`，标题 `高考英语核心3500考纲词+高频词+1000短语+词性转换（电子版）`，`cumulative_sales_min=10000`、`sales_7d_min=500`、`positive_reviews_30d_min=1000`、`favorites_30d_min=100`、`interested_7d_min=2000`，评分 `78.7`，等级 `B`；
  - 该轮完成后数据库统计为 `pending_tasks=71`、`products=15`、`observations=19`、`candidates=11`。
- 已把商品详情页的“开箱精选/相关笔记”采集产品化到第一阶段：
  - `src\xhs_scout\ui_automation.py` 新增/增强 `find_related_note_cards()`，支持真实 UI 中只暴露作者名的横向视觉卡片；
  - 继续过滤底部 `加入购物车`、`立即购买`、`客服`、`购物车`、`收藏/心愿单` 等危险交互区域；
  - CLI `open-related-note` 已验证可从 product id `19` 商品详情页打开公开相关笔记，不触发 ANR/风控。
- 已新增公开笔记详情页与作者主页观察链路：
  - `src\xhs_scout\signals.py` 新增 `note_detail`、`account_profile` 页面识别；
  - `src\xhs_scout\note_observation.py` 新增 `parse_account_profile_text()` 与 `open_note_author_profile_once()`；
  - `src\xhs_scout\ui_automation.py` 新增 `find_note_author_entry()`，只点击作者名文本中心，避免误点右侧 `关注`；
  - CLI 新增 `open-note-author`，仅在当前页为 `note_detail` 时工作。
- 已完成一次真实公开笔记/账号证据采集：
  - 相关笔记卡 dry-run 命中 bounds `[24,1418][362,1836]`，label `猫叔英语研究所`；
  - 实际打开后进入 `com.xingin.xhs/com.xingin.matrix.notedetail.NoteDetailActivity`，page kind `note_detail`，probe `data\probes\note-open-1-after`，无 ANR/风控；
  - note observation id `1` 已回填作者 `猫叔英语研究所`；
  - 作者入口 dry-run 命中 bounds `[167,64][328,91]`，坐标 `(247,77)`，避开 `关注` 按钮；
  - 实际打开后识别为 `account_profile`，probe `data\probes\note-author-profile-after`，作者 `猫叔英语研究所`，公开粉丝数 `5600`，公开获赞/收藏 `64000`，note observation id `2`；
  - 该账号粉丝数低于 1 万，但当前尚未自动解析到单条笔记点赞/收藏/评论，因此仍不能把候选自动升为 A。
- 已增强候选分析报告：
  - `src\xhs_scout\reports.py` 现在会带出最新公开笔记/账号观察、作者名、粉丝数、获赞/收藏和证据目录；
  - 最新报告：`data\reports\candidates-2026-07-27T20-20-29+08-00.md`；
  - 报告中 product id `19` 已显示：公开笔记观察 `2` 条，作者 `猫叔英语研究所`，粉丝 `5600`，获赞/收藏 `64000`，但仍标注未完成 A 级闭环。
- 已将模拟器安全退回：
  - `note-recover-back-1` 回到 `note_detail`；
  - `note-recover-back-2` 回到 `GoodsDetailActivityV2` 的 `product_detail`；
  - `has_anr=false`，`risk_stop_reason=null`。
- 已安全重启本项目工作台：
  - 停止旧 8793 监听 PID `61392`；
  - 新 8793 监听 PID `47380`；
  - 未处理 8765 或其它 Agent；
  - 首页 `http://127.0.0.1:8793/` 返回 HTTP 200，页面包含 `执行单轮`；
  - `/api/monitor/status` 返回 HTTP 200，`desired_state=paused`，`risk_stop_reason=null`，`last_block_reason=null`，`last_skip_reason=task 6 skipped: opened page is unknown`；
  - CSV 正确路径为 `/export/candidates.csv`，不是 `/api/export/candidates.csv`。
- 当前测试结果：`40 passed`。
- 当前数据库统计：
  - `pending_tasks=71`；
  - `products=15`；
  - `observations=19`；
  - `candidates=11`；
  - `note_observations=2`。
- 当前仍未达到无人值守 24 小时全类监控：
  - 已具备受控小批量、商品趋势采集、相关笔记打开、公开账号页粉丝/获赞采集、报告展示；
  - 还缺：自动回收笔记页/账号页链路并接回搜索结果、单条笔记互动数稳定解析、低粉 A 级升级规则自动化、更多关键词连续小批量稳定性、循环调度冷却、失败重试和风控停止面板；
  - 仍不得直接跑完剩余 `71` 个 pending tasks，也不得启动无人值守 24 小时循环。
- 下一步优先级：
  1. 将 `open-related-note` 与 `open-note-author` 接入 `monitor_once` 的可选低频证据阶段，并加入自动 Back 恢复；
  2. 补单条笔记点赞/收藏/评论 OCR 与 UI 树解析，只有粉丝数和笔记互动同时满足条件时才自动升 A；
  3. 对 `task 6 / 小学学习资料` 的 `unknown` 打开页做软失败复盘，增加更稳的商品卡点击/二次验证；
  4. 在 3 到 5 个关键词连续稳定后，再进入低频 `monitor-loop` 小时级试运行；
  5. 工作台继续补最近失败、下一轮计划、笔记证据和报告入口。

### 2026-07-28 12:40 严格低粉证据、查询归属修复、真实闭环与无人值守阻塞

- 已把低粉爆款升级规则收敛为严格证据闭环：
  - 新增 `src\xhs_scout\low_follower.py`；
  - A 级自动升级必须同时有相关笔记和作者公开主页，且作者名一致；
  - 笔记必须可确定为近 7 天；
  - 满足“粉丝少于 200 且单条笔记点赞至少 100”，或“粉丝少于 1 万且单条笔记点赞至少 1000”；
  - 账号累计获赞/收藏不再冒充单条笔记点赞；
  - 旧 note observation `3` 已按原始证据回填为作者 `小红点点`、单条笔记点赞 `6460`、发布距今 `240` 天，因此不会被误判为近期爆款。
- 已完善工作台、报告与 CSV：
  - 首页新增 `笔记/账号证据` 统计卡；
  - 商品列表新增单条笔记点赞、发布天数、作者粉丝；
  - 报告分开显示“单条公开笔记”和“公开作者主页”，不再混淆互动口径；
  - CSV 新增笔记作者、单条笔记点赞/收藏/评论、发布天数、作者粉丝、账号累计获赞与收藏及两类证据目录；
  - 最新报告：`data\reports\candidates-2026-07-28T12-35-47+08-00.md`。
- 已修复真实运行中发现的查询归属污染：
  - run `monitor-51a0aae1d139` 暴露出任务 `12 / 阅读理解` 被旧的 `仿写训练` 搜索结果错误关联；
  - `_keyword_matches_search_page()` 现在只接受顶部查询框，或 OCR 中紧邻顶部“搜索”的查询行，不再用整个结果页正文碰撞关键词；
  - `task_results` 与 `search_result_evidence` 新增 `valid`、`invalid_reason`；
  - 错误关联证据未删除，已保留并标记为无效：`task_results.id=10`、`search_result_evidence.id=8`；
  - 工作台、报告和来源查询自动忽略无效证据。
- 已完成修复后的真实单关键词、单商品闭环：
  - run id：`monitor-784b4cbd940a`；
  - 任务：`12 / 阅读理解`，状态完成；
  - product id：`22`，observation id：`22`；
  - 标题：`小学语文二升三升四升五升六年级阅读理解暑假讲义`；
  - 价格：`29.9`，累计销量下限：`4067`；
  - 趋势：`sales_30d_min=3000`、`positive_reviews_30d_min=2000`、`interested_30d_min=9000`；
  - 候选评分：`56.2`，等级 `B`；
  - 搜索来源：`阅读理解`，结果位次 `1`；
  - 标题解析曾误取图片文案，已把 `讲义` 纳入虚拟资料标题词并原位修正，修正事件为 `data-correction-2026-07-28-title-reparse`。
- 已修复指标条横滑的页面误跳风险：
  - 真实帧显示第 4 次焦点点击可能落在可点击的 `近期店铺销量TOP1`，从商品详情误入店铺页；
  - `detail_metrics.py` 现在每次焦点点击后都读取 UI 树，必须仍同时存在 `加入购物车` 与 `立即购买` 两个详情页控件；
  - 一旦离开详情页，立即保存 `navigation-guard.png`、停止滑动、只回退一次并返回 `navigation_guard`；
  - UI 树读取失败时也停止，不继续猜测滑动；
  - 仍保留已验证参数 `focus-taps=4`、`swipe-pixels=240`、`swipe-ms=900`，但增加了逐步页面守卫。
- 已修复页面分类和打开页稳定等待：
  - 店铺商品列表优先于账号主页分类；
  - 账号主页必须具备 `小红书号+粉丝`，或 `粉丝+关注+获赞与收藏` 强信号；
  - 商品打开后的空 Activity、零 OCR、小红书启动页会先有限等待并复探两次；
  - 如果最终落到首页发现流或仍是启动页，监控暂停，不盲目 Back。
- 已针对本轮阻塞补上下一层防护，但尚未再次触发真实 UI：
  - `find_product_cards()` 会在点击前过滤含 `直播中`、`正在直播`、`进入直播间` 的非标准结果卡，并继续寻找下一张普通商品卡；
  - 新增 `find_home_search_entry()`，仅在 `home_feed` 上识别顶部右侧可见查询入口，不会点击底部发布、市集、消息等入口；
  - `_open_search_results()` 在首页发现流找不到详情页专用 `搜索商品` 按钮时，可使用该首页搜索入口进入正常搜索流程；
  - 上述逻辑已用真实页面结构样本编写回归测试；由于本轮受控实验预算已满，真实点击复验留给下一轮 3 到 5 次受控实验。
- 本轮受控实验共 4 次，已经达到默认实验预算：
  - `monitor-51a0aae1d139`：发现并修复查询归属污染；
  - `monitor-784b4cbd940a`：成功完成 `阅读理解` / product `22` 闭环；
  - `monitor-b0b3ee6208c2`：发现 `古诗文` 搜索结果被误分为账号主页，分类器已修复；
  - `monitor-eb8c1d81b928`：首个结果为直播/非标准商品卡，打开后经历小红书启动页并落到首页发现流；无 ANR、无验证码、无风控页，但搜索流程丢失，任务 `13` 进入 `needs_manual_detail`；
  - 按受控实验停止条件，本轮不再继续模拟器点击。
- 当前工作台已加载最新代码：
  - 地址：`http://127.0.0.1:8793/`；
  - 当前 8793 监听 PID：`40980`；
  - 未停止或修改 8765 及其它 Agent；
  - 首页、`/api/status`、`/api/monitor/status`、`/export/candidates.csv` 均已验证 HTTP 200；
  - CSV 已验证包含新增笔记/账号证据字段。
- 当前真实统计：
  - `pending_tasks=67`；
  - `products=17`；
  - `observations=22`；
  - `note_observations=5`；
  - `candidates=13`；
  - 测试：`52 passed`。
- 当前运行状态：
  - `desired_state=paused`；
  - `risk_stop_reason=null`；
  - `last_block_reason=app returned to home feed while opening product; unattended loop remains paused`；
  - `last_skip_reason=task 13 skipped: product open reached splash screen and home feed`；
  - Rvc64 前台为 `IndexActivityV2` 的 `home_feed`，无 ANR、无风控页；
  - 最新只读探测：`data\probes\probe-2026-07-28T12-24-33+08-00`。
- 当前结论：
  - 已具备人工值守下的单关键词闭环、严格低粉证据判定、商品/笔记/账号报告和可操作工作台；
  - 仍不具备 24 小时无人值守条件；
  - 当前真实阻塞是直播/非标准结果卡可能触发应用启动页并丢失搜索上下文，且指标条页面守卫尚未做下一轮真实复验；
  - 不得直接恢复全部 `67` 个任务或启动长期 `monitor-loop`。
- 下一步执行顺序：
  1. 用新一轮最多 3 到 5 组受控实验真实验证直播卡过滤、首页搜索入口恢复和指标条 `navigation_guard`；
  2. 若仍存在无文本直播卡，再结合 Activity 和卡片结构增加第二层非标准结果过滤；
  3. 验证失败时保留截图、UI 树和事件记录，达到预算即停止，不重复盲点；
  4. 连续 3 到 5 个单关键词小轮次无错链、无丢失搜索上下文后，再启用带冷却、重试预算和熔断的小时级调度；
  5. 相关笔记存在时才采集笔记/主页，A 级继续严格要求近期、低粉和单条笔记互动三项证据。

### 2026-07-28 并行开发拆分

- 用户确认将剩余开发拆成互不干扰的并行板块，以缩短整体工期。
- 并行规则和独占文件范围记录在项目根目录 `PARALLEL_WORK.md`。
- 已建立四个独立 Codex 任务：
  - T1：运行租约、失败重试、冷却和任务状态接口；
  - T2：灰色指标条动态 ROI、多帧去重和污染过滤；
  - T3：候选商品证据、风险、缺口与原创化分析报告；
  - T4：不展示运行日志的工作台界面模块。
- 当前主对话是唯一集成负责人；只有主对话可以操作 BlueStacks、ADB、小红书、真实数据库、8793 服务，以及修改 `monitor.py`、`workflow.py`、`web.py`、`cli.py` 和交接文档。
- 四个并行任务只做离线代码和测试，不得操作 `data/`、真实数据库、模拟器或服务。项目不是 Git 仓库，因此通过严格的独占写入文件范围避免冲突。
- 四路完成后由主对话统一审查、接线、运行完整测试、安全重启 8793，并执行最多 1 至 3 个商品的真实受控小闭环。

### 2026-07-28 22:42 最终集成、安全加固与工作台验收

- 本阶段继续按“主任务统一控制真实状态、独立任务只改互不重叠文件”的方式并行完成：
  - README、ROADMAP、OPERATIONS 最终化；
  - SQLite `timeout=10s` 与 `PRAGMA busy_timeout=10000`；
  - 工作站 API/UI 契约、跨轮 soak-readiness、dashboard 最新观察去重测试；
  - 生产数据只读质量盘点；
  - 最终静态安全审计及其全部阻断项修复。
- 最终静态审计发现并已修复：
  - “安全限制”“设备异常”“风险插件”“登录异常”进入硬风控停止；
  - 普通恢复不能清除 `risk_stop_reason`；独立风险解除接口/CLI/UI 必须提交与当前风险原因一致的显式确认，并记录审计事件；
  - 首页搜索入口只接受明确搜索/查询语义或可验证查询框，不再猜测顶部最右可点击目标；
  - 商品分享链接限制为已验证的小红书公开链接格式；当前真实样本 `https://xhslink.com/m/...` 已加入允许列表，未知域名、伪装域名、凭据 URL、端口、旧剪贴板和非商品路径被拒绝；
  - A 级低粉闭环必须有作者一致、近期笔记、单条互动、公开粉丝数和位于数据证据根目录内的真实可回看文件；坏 `reasons_json` 安全降级；
  - scheduler 新增独立停止事件，`desired_state=running` 时也能可靠关闭并重新启动；
  - `/captures/{observation_id}` 只能读取 `data\captures` 内文件；
  - 工作台不显示运行事件日志，商品真实链接和证据截图保持独立入口。
- 最终离线测试：
  - 命令：`.\.venv\Scripts\python.exe -m pytest -q`
  - 结果：`176 passed in 7.68s`
- 已安全重启并验收本项目工作台：
  - 工作台：`http://127.0.0.1:8793/`
  - 当前 8793 PID：`51644`
  - 命令行包含精确项目所有权标记：`--project-root="C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent"`
  - `ops\health_check.ps1 -Json` 返回 `ok=true`
  - `/`、`/api/status`、`/api/monitor/status`、`/api/quality`、`/api/digest/daily`、`/api/digest/weekly`、`/api/portfolio`、`/reports/latest`、`/export/candidates.csv` 均返回 HTTP 200
  - 8765 仍由 PID `21820` 监听，本阶段未停止、重启或修改
  - `XhsProductScoutWorkbench8793` 计划任务当前不存在；未获对外部 Windows 配置变更的单独确认，因此未安装
- 当前数据库真实计数：
  - `pending_tasks=66`
  - `products=20`
  - `observations=26`
  - `note_observations=5`
  - `candidates=13`
  - dashboard 最近观察已按商品去重，每个商品只显示最新 observation
- 当前监控状态：
  - `desired_state=paused`
  - `risk_stop_reason=null`
  - `last_block_reason=null`
  - `last_skip_reason=null`
  - `scheduler_running=false`
  - `next_run_at=null`
  - 最近调度 run：`monitor-b3a62486c2fc`
- 当前 Rvc64：
  - ADB `127.0.0.1:5555` 在线；
  - 前台 Activity：`com.xingin.xhs/com.xingin.alioth.search.GlobalSearchActivity`
  - 无 ANR；
  - 未发现验证码或安全限制页。
- 当前可追溯的最新两次真实安全闭环：
  - `monitor-922a34c61530`：关键词 `阶段复习`，product `25`，observation `25`，真实链接 `https://xhslink.com/m/5opIwRSMelM`；
  - `monitor-b3a62486c2fc`：小时级调度器关键词 `备考资料`，product `24`，observation `26`，真实链接 `https://xhslink.com/m/4RNhgVftJtH`；
  - 两次均安全返回搜索结果页，无 ANR、验证码或风险停止。
- 当前报告与质量：
  - 最新报告：`data\reports\candidates-2026-07-28T21-56-34+08-00.md`
  - 质量问题 `123`：error `47`、warning `75`、info `1`
  - 主要为历史缺真实链接、低粉证据缺口和 OCR 半截污染记录；质量模块只读提示，不删除或篡改历史证据
  - 日摘要：窗口内观察 `6`、新增候选 `2`、严格低粉闭环 `0`、失败任务 `5/85`、人工复核项 `18`
  - 关键词组合共 `104` 个有限候选，当前下一词为 `Excel模板`；这是高覆盖轮转，不是全站穷举
- 工作台最终浏览器验收：
  - 桌面 `1440x1000`：页面 `clientWidth=scrollWidth=1425`，无横向页面溢出；
  - 移动 `390x844`：页面 `clientWidth=scrollWidth=375`，控制按钮和概览卡可见，宽表在自身容器内滚动；
  - 页面不含“运行日志”或 `/api/run-events`；
  - 两个已采集商品标题分别打开真实 `xhslink.com/m/...`，截图通过独立 `/captures/...` 打开；
  - 风险解除按钮在当前无风险状态下禁用。
- 当前仍未完成，不能虚报：
  1. 尚未完成连续 3 至 5 个小时级轮次和 24 小时 soak；
  2. Windows 计划任务尚未安装；
  3. 当前严格低粉闭环候选仍为 `0`，需要更多近 7 天公开笔记和 `<=2000` 粉丝主页证据；
  4. 当前待处理候选中仍有大量历史商品缺真实链接；按 `coordination\T16-data-quality-remediation.md` 分批低频回访，不得一次跑完 66 个任务；
  5. 全站/全类目只能继续解释为有限关键词池的高覆盖轮转，不得宣称穷举全站。
- 下一阶段执行顺序：
  1. 保持每小时 1 关键词、每关键词 1 商品，先完成连续 3 至 5 个小时级安全轮次并记录 run id、页面恢复、风险、链接、指标条和数据库锁；
  2. 小时级试运行全程稳定后，再进入 24 小时 soak；任何验证码、安全限制、ANR、未知危险页或搜索上下文丢失立即硬停止；
  3. 按数据质量清单优先补真实商品链接和有效搜索归属，再补指标条，最后只对近 7 天高互动笔记访问公开作者主页；
  4. 计划任务安装仍需用户明确批准后才可运行 `ops\install_scheduled_task.ps1 -Execute`。

最后更新时间：2026-07-28 22:42（Asia/Shanghai）

### 2026-07-28 23:00 工作台候选表精简与千瓜对标准备

- 按用户确认的展示需求完成：
  - 候选表删除“证据截图”列和“打开截图”入口；
  - 后台截图文件、数据库字段、质量审计和安全的 `/captures/{observation_id}` 接口保留，不删除历史证据；
  - “搜索来源”改名为“搜索关键词”；
  - 候选表只显示关键词，不再拼接 `#结果位次`；
  - 商品标题继续优先打开真实 `share_url`，无链接时显示“链接待采集”。
- 已更新 `README.md` 和工作台契约测试。
- 最终测试仍为 `176 passed`。
- 8793 已安全重启：
  - 当前 PID：`44120`
  - `ops\health_check.ps1 -Json` 返回 `ok=true`
  - 首页已验证不含“证据截图”、`makeCaptureLink` 或 `search_result_rank`，并包含“搜索关键词”。
- 千瓜对标仍需要，但不再是当前工作站运行的阻塞项：
  - 用途限定为对比数据字段、筛选/排序、商品-笔记-作者证据链、趋势表达和报告结构；
  - 不把千瓜作为本项目数据源，不抓包、不调用隐藏接口、不批量复制数据；
  - 开通一小时会员前先使用 `QIANGUA_ONE_HOUR_AUDIT.md`，预设 3 个关键词并准备截图目录；
  - 若一小时会员不包含商品搜索、笔记搜索和达人/账号三个核心模块，不建议仅为页面设计开通。

最后更新时间：2026-07-28 23:00（Asia/Shanghai）

### 2026-07-28 23:18 工作台视觉与交互精修

- 本阶段只调整工作台单页和对应测试，没有改动采集器、数据库结构、评分、调度策略或小红书 UI 操作逻辑。
- 页面在保留原有接口和安全门禁的前提下完成：
  - 六张独立统计卡压缩为连续 KPI 概览条，监控状态在顶栏和概览中同步显示；
  - 顶栏增加最后刷新时间，刷新时显示明确的读取状态；
  - 监控控制区收紧为操作条、参数区和扁平状态条，硬风控解除保持独立红色危险动作；
  - 候选表由 13 个数据库式字段列合并为 8 个业务列：等级、商品、价格/分数、销量趋势、搜索关键词、笔记/账号证据、低粉核验、证据摘要；
  - 商品标题继续打开真实 `share_url`，不恢复证据截图列、不显示结果位次、不展示运行日志；
  - 证据摘要最多显示前三条并保留完整悬停文本；
  - 低粉复核从连续 5 个 `window.prompt` 改为同屏表单弹层，仍调用原 `/api/verify-low-follower/{product_id}`；
  - 移动端候选表改为可扫描的逐商品记录，页面本身无横向溢出。
- 测试：
  - 定向工作台与工作站契约测试：`10 passed`；
  - 完整测试：`177 passed in 9.01s`。
- 服务验收：
  - 8793 已安全重启，当前 PID：`19040`；
  - `ops\health_check.ps1 -Json` 返回 `ok=true`；
  - 8765 仍由 PID `21820` 监听，本阶段未停止、重启或修改；
  - 当前数据仍为 `pending_tasks=66`、`products=20`、`observations=26`、`note_observations=5`、`candidates=13`；
  - 监控仍为 `desired_state=paused`、`risk_stop_reason=null`、`scheduler_running=false`，本阶段未触发真实采集。
- 浏览器实测：
  - 桌面 `1440x1000`：`clientWidth=1425`、`scrollWidth=1425`，候选表显示 8 个业务列，风险解除按钮在无风险时正确隐藏；
  - 移动 `390x844`：`clientWidth=375`、`scrollWidth=375`，控制按钮、KPI、候选记录均无页面级横向溢出；
  - 低粉复核弹层在移动端可见 5 个字段，首字段自动聚焦，可取消、关闭或保存；
  - 页面不含“运行日志”“证据截图”或 `window.prompt`。

最后更新时间：2026-07-28 23:18（Asia/Shanghai）

### 2026-07-28 23:26 新对话交接前只读核验

- 用户确认当前对话过长，准备新开 Codex 对话继续项目；本节是交接前的最新真实检查点。
- 工作台：
  - `http://127.0.0.1:8793/` 正常；
  - `ops\health_check.ps1 -Json` 返回 `ok=true`；
  - `/api/status`、`/api/monitor/status`、`/export/candidates.csv` 均为 HTTP 200；
  - 8793 仍由本项目 PID `19040` 监听，命令行包含精确 `--project-root`；
  - 8765 仍由 PID `21820` 监听，未停止、重启或修改。
- 数据库与监控：
  - `pending_tasks=66`；
  - `products=20`；
  - `observations=26`；
  - `note_observations=5`；
  - `candidates=13`；
  - `desired_state=paused`；
  - `risk_stop_reason=null`；
  - `last_block_reason=null`；
  - `last_skip_reason=null`；
  - `scheduler_running=false`；
  - 最新报告仍为 `data\reports\candidates-2026-07-28T21-56-34+08-00.md`。
- Rvc64：
  - 配置仍为 `config\emulator.json` 中的 `Rvc64`、`127.0.0.1:5555`、`com.xingin.xhs`；
  - ADB `get-state=device`；
  - 小红书进程 PID `9017`；
  - 前台 Activity 为 `com.xingin.xhs/com.xingin.alioth.search.GlobalSearchActivity`；
  - 只读进程检查未发现 `notResponding=true` 或 ANR。
- 最近验证：
  - 完整测试仍为本阶段刚完成的 `177 passed in 9.01s`；
  - 工作台桌面、移动端、低粉复核弹层均已完成真实浏览器验收；
  - 本次交接核验没有启动采集、没有点击模拟器、没有改变监控状态。
- 新对话接手后的执行重点：
  1. 先完成连续 3 至 5 个“每小时 1 关键词、每词 1 商品”的受控放大轮次；每轮记录 run id、搜索上下文恢复、真实链接、指标条、数据库锁和风险状态；
  2. 稳定后按 `coordination\T16-data-quality-remediation.md` 分批补真实商品链接、搜索关键词归属、趋势指标，再补近 7 天公开笔记和 `<=2000` 粉丝账号证据；
  3. 上述两项通过后进入 24 小时 soak；出现验证码、安全限制、ANR、未知危险页或搜索上下文丢失时必须硬停止；
  4. Windows 计划任务仍未安装，必须在实际执行 `ops\install_scheduled_task.ps1 -Execute` 前取得用户明确确认；
  5. 千瓜会员对标不是运行阻塞项；用户开通前先阅读 `QIANGUA_ONE_HOUR_AUDIT.md`，不要把千瓜当数据源或调用隐藏接口。

最后更新时间：2026-07-28 23:26（Asia/Shanghai）

### 2026-07-28 23:49 工作站交互重构与最终交接检查点

- 用户认为上一版仍然像粗糙的纵向面板，提供运营数据后台参考图后要求重做交互；本阶段已完成，不照搬参考产品品牌。
- 工作站信息架构已改为：
  - 左侧工作区导航：候选商品、监控任务、报告与质量、关键词池；
  - 顶部统一显示当前工作区、监控状态、刷新时间、刷新和 CSV 导出；
  - 候选商品为默认主视图，其余三个功能区通过前端切换，不刷新页面、不触发平台请求；
  - 桌面端采用高密度数据表，移动端自动转为逐商品记录。
- 候选商品交互已新增：
  - 按商品标题、店铺或搜索关键词即时搜索；
  - 按 A/B/C/D 证据等级筛选；
  - “只看低粉”筛选仅接受已采到且 `1-2000` 的公开粉丝数，`0` 不再误标为核心低粉；
  - “有趋势证据”筛选；
  - 按分数、近 30 天购买、累计销量或作者粉丝排序；
  - 9 个业务列：等级、商品、价格/分数、店铺/关键词、数据指标、近期趋势、低粉证据、候选依据、操作；
  - 商品标题和“打开”继续使用经过安全校验的真实 `share_url`；
  - “复核”继续使用同屏低粉表单，不使用连续 `window.prompt`。
- 监控、报告和关键词视图：
  - 监控视图保留单轮参数、执行单轮、暂停、普通恢复、硬风控独立恢复和安全状态；
  - 报告视图展示最新报告、证据质量、近 24 小时摘要和关键词覆盖；
  - 关键词视图展示候选总量、预算、当前选择、待处理任务、监控状态和下一关键词；
  - 页面仍不展示运行日志、证据截图或搜索结果位次。
- 测试：
  - 工作台/工作站定向契约测试：`11 passed`；
  - 完整测试：`178 passed in 7.35s`。
- 浏览器验收：
  - 桌面 `1440x1000`：`clientWidth=scrollWidth=1425`，表格容器与表格均为 `1173px`，操作列可见，无页面横向溢出；
  - 四个工作区均能正确切换，监控页未触发任何按钮；
  - 报告页显示质量 `错误 47 · 警告 75 · 提示 1`；
  - 关键词页显示候选总量 `104`、下一关键词 `Excel模板`；
  - 搜索“小学语文”得到 `2 / 20` 条记录，清空后恢复；
  - 移动 `390x844`：页面 `clientWidth=scrollWidth=375`，导航可横向滚动，商品记录宽 `337px`，无页面横向溢出；
  - 页面不含“运行日志”或“证据截图”。
- 交接前最新只读状态：
  - 8793 已安全重启，当前 PID `43912`，健康检查 `ok=true`；
  - 8765 仍为 PID `21820`，未修改；
  - 数据仍为 `pending_tasks=66`、`products=20`、`observations=26`、`note_observations=5`、`candidates=13`；
  - 监控仍为 `desired_state=paused`、`risk_stop_reason=null`、`last_block_reason=null`、`last_skip_reason=null`、`scheduler_running=false`；
  - Rvc64 ADB 状态 `device`，前台仍为 `com.xingin.xhs/com.xingin.alioth.search.GlobalSearchActivity`，未发现 ANR；
  - 本阶段没有启动采集、没有点击模拟器、没有改变数据库或监控状态。
- 下一阶段不再继续重做界面。按顺序执行：
  1. 连续 3 至 5 个每小时 1 关键词、每词 1 商品的受控放大轮次；
  2. 按 `coordination\T16-data-quality-remediation.md` 分批补商品链接、关键词归属、趋势和低粉笔记/账号证据；
  3. 小时级轮次稳定后执行 24 小时 soak；
  4. 计划任务安装仍需用户明确确认。

最后更新时间：2026-07-28 23:49（Asia/Shanghai）

### 2026-07-29 11:26 受控放大第 1/3 轮

- 接手后先完成只读复核，结果与上一检查点一致：
  - 8793 仍由本项目 PID `43912` 监听，命令行含精确 `--project-root`，`ops\health_check.ps1 -Json` 返回 `ok=true`；
  - 8765 仍由其他 Agent PID `21820` 监听，未停止、重启或修改；
  - 轮次前数据库为 `pending_tasks=66`、`products=20`、`observations=26`、`note_observations=5`、`candidates=13`；
  - 监控为 `desired_state=paused`、`risk_stop_reason=null`、`last_block_reason=null`、`last_skip_reason=null`、`scheduler_running=false`；
  - Rvc64 ADB `127.0.0.1:5555` 在线，小红书 PID `9017`，前台为 `com.xingin.xhs/com.xingin.alioth.search.GlobalSearchActivity`，未发现 ANR。
- 本轮通过工作台单轮 API 执行，没有恢复全局调度：
  - run id：`monitor-45c96a5b5e1c`；
  - 参数：`max_keywords=1`、`max_products_per_keyword=1`、`wait_seconds=6`、`metrics_max_frames=3`、`metrics_swipe=true`、`note_evidence=false`；
  - 关键词：`模考真题`，task `18`；
  - product `27`，observation `27`，标题 `2026全真模考系统高度还原长期更新`；
  - 真实链接：`https://xhslink.com/m/2abDO6CVqCp`；
  - 指标条自动定位未命中，安全记录为 `metrics_skipped`，没有盲目滑动；证据目录为 `data\metric_strips\2026-07-29T11-21-13+08-00`；
  - 一次回退即恢复 `search_results`，最终 Activity 仍为 `GlobalSearchActivity`，无 ANR、验证码或风险停止；
  - 结果为 `processed_tasks=1`、`captured_products=1`、`skipped=[]`、`requeued_tasks=1`；运行租约已正常释放，后续 CLI 状态读取成功，未见数据库锁异常。
- 轮次后真实状态：
  - `pending_tasks=66`、`products=21`、`observations=27`、`note_observations=5`、`candidates=13`；
  - `desired_state=paused`、`risk_stop_reason=null`、`last_block_reason=null`、`last_skip_reason=null`、`scheduler_running=false`、`next_run_at=null`；
  - 最新报告：`data\reports\candidates-2026-07-29T11-21-51+08-00.md`。
- 为严格保持每小时最多 1 个关键词、每词 1 个商品，已建立当前 Codex 任务专用 heartbeat：
  - 自动化名称：`小红书选品受控放大轮次`；
  - 自动化 id：`automation`；
  - 当前状态：`ACTIVE`，每小时唤醒一次；
  - 只允许再完成 2 轮，使本阶段总数达到 3；每次运行前必须重新做端口、健康、监控、ADB、前台 Activity 和 ANR 只读核验；
  - 达到 3 轮或出现任一 risk/block/skip、ANR、危险页、上下文丢失或数据库锁异常后，必须立即停止并把该 heartbeat 改为 `PAUSED`；
  - 不得启动 `monitor-loop`、24 小时 soak、全部 66 个任务或 Windows 计划任务。
- 下一步：
  1. 最早在第一轮完成 60 分钟后执行第 2/3 轮；
  2. 再间隔至少 60 分钟执行第 3/3 轮；
  3. 三轮均稳定后更新本文件、暂停 heartbeat，再读取 `coordination\T16-data-quality-remediation.md` 判断是否进入分批质量修复；不得自动进入 24 小时 soak。

最后更新时间：2026-07-29 11:26（Asia/Shanghai）

### 2026-07-29 12:15 总控台第五轮并行拆分

- 用户明确确认当前项目远未完成，并要求本对话继续担任唯一总控台，不得因等待小时级
  受控轮次而让其余工作空转。
- 主任务继续独占真实数据库写入、8793、ADB、BlueStacks、小红书真实 UI、小时级
  heartbeat、集成和最终验收；第 2/3、3/3 轮不得提前执行。
- 已创建四个互不重叠的新 Codex 任务，详细边界见 `PARALLEL_WORK.md`：
  - T18 `019fac12-0630-7a61-a93a-4dca267b4ab0`：生产数据只读补证队列刷新，只写
    `coordination\T18-live-remediation-queue.md`；
  - T19 `019fac12-4418-75b2-a523-e1c0a6d5b258`：候选报告完整性与无效证据防误用，
    独占 `analysis.py`、`reports.py` 及其测试；
  - T20 `019fac12-79a5-7aa1-aa33-8a8138867b0f`：有限虚拟商品关键词池扩展，独占
    `keyword_portfolio.py`、关键词配置及其测试；
  - T21 `019fac12-ae65-7563-bf70-b4aaadb64e42`：24 小时监控就绪差距和验收方案，
    只写独立协调文档和可选的新离线测试。
- 四个任务均已确认开工或进入运行队列；全部禁止操作生产数据库写入、8793、8765、
  ADB、BlueStacks、小红书、真实队列、24 小时 soak 和 Windows 计划任务。
- 当前正确项目状态仍是：代码主体和多次小规模真实闭环已具备，但广覆盖商品积累、
  完整趋势/链接/搜索归属、近期低粉笔记与账号闭环、多小时稳定性和 24 小时运行均
  尚未完成，不能宣称全站或长期自动监控。

最后更新时间：2026-07-29 12:15（Asia/Shanghai）

### 2026-07-29 12:28 受控放大第 2/3 轮

- 轮次前只读门槛全部通过：
  - 距第 1/3 轮完成超过 61 分钟；
  - 8793 仍由本项目 PID `43912` 持有且健康，8765 仍为其他 Agent PID `21820`；
  - `desired_state=paused`、`risk_stop_reason=null`、`last_block_reason=null`、
    `last_skip_reason=null`、`scheduler_running=false`；
  - Rvc64 ADB 在线，前台为 `GlobalSearchActivity`，无 ANR。
- 第 2/3 轮：
  - run id：`monitor-6e6e0be23652`；
  - 参数仍为 `1 关键词 × 1 商品`、等待 6 秒、指标条最多 3 帧、不采笔记扩展；
  - 关键词：`错题本模板`，task `19`；
  - product `28`，observation `28`；
  - 真实链接：`https://xhslink.com/m/ABS2pxOP0uZ`；
  - 指标条自动定位未命中，记录 `metrics_skipped`，没有盲目滑动；证据目录为
    `data\metric_strips\2026-07-29T12-25-24+08-00`；
  - 一次回退恢复 `search_results`；结果为 `processed_tasks=1`、
    `captured_products=1`、`skipped=[]`、`requeued_tasks=1`；
  - 无验证码、风控、未知页、ANR、risk/block/skip。
- 轮次后验证：
  - `pending_tasks=66`、`products=22`、`observations=28`、
    `note_observations=5`、`candidates=13`；
  - SQLite 只读 `quick_check=ok`，`running_tasks=0`、`run_leases=0`，租约正常释放；
  - 监控继续保持 paused，调度器未运行，最终 Activity 仍为搜索结果页。
- heartbeat 保持 `ACTIVE`，下一小时只允许执行最后第 3/3 轮；不得提前执行、不得
  启动 monitor-loop、24 小时 soak 或全部队列。

最后更新时间：2026-07-29 12:28（Asia/Shanghai）

### 2026-07-29 13:36 受控放大第 3/3 轮与离线可靠性检查点

- 第 3/3 轮开始前的只读门禁全部通过：
  - 8793 仍由本项目 PID `43912` 持有，健康检查 `ok=true`；8765 仍由其他 Agent
    PID `21820` 持有，未停止、重启或修改；
  - 监控为 `desired_state=paused`、`risk_stop_reason=null`、
    `last_block_reason=null`、`last_skip_reason=null`、`scheduler_running=false`；
  - SQLite `quick_check=ok`，轮次前 `running_tasks=0`、`run_leases=0`；
  - Rvc64 ADB 在线，前台为
    `com.xingin.xhs/com.xingin.alioth.search.GlobalSearchActivity`，未发现 ANR；
  - 自 2026-07-29 11:19 起仅有前两条 `monitor_once_finished`，且距第 2 轮完成
    已超过 60 分钟。
- 第 3/3 轮结果：
  - run id：`monitor-01375a7cca15`；
  - 参数：`max_keywords=1`、`max_products_per_keyword=1`、`wait_seconds=6`、
    `metrics_max_frames=3`、`metrics_swipe=true`、`note_evidence=false`；
  - 关键词：`学习计划模板`，task `20`；
  - product `29`，observation `29`，标题
    `家庭积分奖励丨学习计划|学霸资料|电子模板可编辑可打印`；
  - 真实链接：`https://xhslink.com/m/5eiCxjPPLnq`；
  - 指标条成功自动定位并写入：近 30 天新增好评 `100+`、近 30 天感兴趣
    `1000+`；证据目录为
    `data\metric_strips\2026-07-29T13-33-04+08-00`；
  - 一次回退恢复 `search_results`，最终前台仍为安全搜索页，无 ANR、验证码、
    风控、未知页、risk/block/skip；
  - 结果为 `processed_tasks=1`、`captured_products=1`、`skipped=[]`、
    `requeued_tasks=1`。
- 轮次后真实状态：
  - 自 11:19 起的 `monitor_once_finished` 总数已严格达到 `3`，不得再执行本阶段
    真实受控轮次；
  - `pending_tasks=66`、`products=23`、`observations=29`、
    `note_observations=5`、`candidates=13`；
  - SQLite `quick_check=ok`、`running_tasks=0`、`run_leases=0`；
  - task `20` 为 `completed`，无 owner、无租约、无错误；
  - 监控继续 paused，scheduler 未运行，所有 risk/block/skip 原因均为空。
- 离线并行成果已集成到当前工作区：
  - T31–T39 已完成 pre-soak fail-closed 准入、最新搜索证据语义、补证计划工作台、
    关键词质量修复、只读 soak readiness API、scheduler/租约跨模块回归、SQLite
    并发压力测试以及过时 xfail 清理；
  - 当前总控完整离线回归基线为 `287 passed`，无 xfail/xpass；
  - 新接口和工作台代码尚未重启 8793 做真实浏览器验收，当前运行中的 8793 仍是
    重启前代码；不得把离线通过写成线上已生效。
- 下一步边界：
  1. heartbeat 继续只做离线任务总控，不再触发真实采集；
  2. 可只读刷新 T18 补证队列、完善 pre-soak 展示与集成回归；
  3. 不自动开始真实补证、monitor-loop、6–8h pre-soak 或 24h soak；
  4. 后续若要重启 8793 验收新代码，由主任务单独确认所有权后串行执行；
  5. Windows 计划任务仍必须取得用户明确确认后才能安装。

最后更新时间：2026-07-29 13:36（Asia/Shanghai）

### 2026-07-29 13:45 三轮后离线审计与补证队列检查点

- T40–T43 已完成并由总控复跑完整测试：`304 passed in 10.52s`。
- 三轮 G1 独立只读审计结论为“通过”：
  - 三轮间隔为 62 分 21 秒、65 分 28 秒，均为真实 `1×1`；
  - run/task/product/observation、有效搜索归属、白名单真实链接、搜索页恢复和证据路径
    完整，顶层均无 skip/block/risk，最终无租约和 running 任务；
  - 前两轮指标条为 `metrics_skipped`，但商品详情仍解析到累计销量 32、131；第 3 轮
    指标条成功。只能写成“当前 G1 代码口径通过”，不能写成三轮指标条均成功；
  - 该结论不能外推为 G2、G4 或 G5：当前没有 scheduler `scheduled_at` 到期点、
    6–8 小时快照或连续 24 小时证据。
- 三轮后的只读补证队列：
  - 活跃集合仍为 14 个（13 candidate、1 needs_review）；
  - identity 阶段 13 个、7 批；product 20 继续隔离；
  - metrics 条件队列 7 个、4 批，但因 identity 依赖当前可执行数为 0；
  - note 条件队列 12 个、6 批，当前可执行数为 0；
  - profile 当前合格数为 0，候选池上限 12；
  - 硬预算仍为每批最多 2 个、每小时最多 6 次商品级访问；
  - 新 product 29 为 observed / 17.6，已具备链接、有效搜索归属和两帧指标条，不进入
    candidate/needs_review 补证队列。
- 新的离线能力：
  - 工作台代码已增加只读 G0–G6、gaps、warnings 和“未授权启动”展示，但 8793
    尚未重启，因此真实浏览器仍未验收此版本；
  - `soak_ack.py` 已提供追加式人工 ACK 账本、路径和敏感字段限制、哈希链及
    fail-closed 判定；当前尚未接入 T31/T37、Web、scheduler 或生产状态。
- 下一步仍只做离线准备：
  1. 把 ACK 结果接入 readiness 的 fail-closed 门槛；
  2. 为真实补证建立显式审批清单和预算/隔离校验，但不执行补证；
  3. 为未来 G2 建立 scheduler 到期点证据记录契约；
  4. 不启动真实补证、monitor-loop、pre-soak、24 小时 soak 或计划任务。

最后更新时间：2026-07-29 13:45（Asia/Shanghai）

### 2026-07-29 15:20 并行总控暂停与 token 成本检查点

- 用户要求因并行任务 token 消耗过高暂时停工；总控 heartbeat `automation` 已改为
  `PAUSED`，不再每 5 分钟唤醒，不再创建新任务。
- 离线任务 T18–T66 已完成。其间 T62 严格集成测试发现四项 fail-closed 缺口：
  baseline 文件漂移、审批过期、当前补证计划漂移、readiness 顶层与 gate 矛盾；
  T65 已逐项修复并复验。
- 暂停前最近一次完整离线回归为 `562 passed, 3 skipped`。
- 三个在途任务已在安全检查点停止：
  - T67 已修改 `workbench_ui.py` 和 `test_workbench_ui.py`，定向/相邻 `66 passed`，
    但尚未完成完整回归、有效 JS 检查和最终差异复核，属于未验收半成品；
  - T68、T69 只做了只读调研，没有修改文件或运行测试。
- 本轮暂停没有触发真实小红书采集、补证、monitor-loop、pre-soak、24h soak 或
  Windows 计划任务；没有操作 8793/8765、ADB、BlueStacks 或生产数据库。
- 真实业务进度仍为三轮受控放大完成后的状态：23 个商品、29 条商品观察、5 条
  笔记/账号观察、13 个候选、66 个待处理任务；这不是广覆盖或 24 小时自动监控。
- 8793 仍未重启加载这批离线代码，也未做真实浏览器验收。
- 恢复建议：关闭高频 heartbeat，采用“总控 + 最多 1 个并行任务”的低 token 模式；
  先处理 T67 半成品并只运行一次批次完整回归，再由总控串行完成 8793 重载/浏览器
  验收、真实补证小批次、G2/G3/G4 和最终 24h soak。未经用户确认不得恢复自动续派。

最后更新时间：2026-07-29 15:20（Asia/Shanghai）

### 2026-07-29 17:18 统一项目板与当前基线

- 已建立唯一项目完成板：`coordination\TASK_BOARD.md`。它现在是“从当前状态到最终完成”
  的唯一任务规划和完成度入口；`HANDOFF.md` 继续负责真实状态、关键决策、历史证据和
  接手步骤，`PARALLEL_WORK.md` 只保留为历史并行运行日志。
- 任何新任务在执行或分派前必须先进入项目板，并写明优先级、依赖、预计耗时、是否可
  分派、验收标准和停止条件；不得再根据空闲并发槽临时续派。
- 本次只读核验结果：
  - 8793 仍由本项目 PID `43912` 监听；8765 仍由其他 Agent PID `21820` 监听；
  - 生产数据仍为 66 个待处理任务、23 个商品、29 条商品观察、5 条笔记/账号观察、
    13 个候选；
  - 监控仍 paused，scheduler 未运行，risk/block/skip 原因均为空；
  - Rvc64 ADB `127.0.0.1:5555` 在线，前台为安全搜索页，未发现 ANR；
  - 当前完整离线测试为 `568 passed, 3 skipped in 46.93s`。
- T67 当前改动已能通过完整 pytest，但仍缺有效 JavaScript 静态检查、范围复核和加载
  后真实浏览器验收，继续标记为“待验收”，不能算完成；T68、T69 仅有只读调研，已在
  项目板中降为 P2 延后项。
- 当前唯一主线：先收口 T67，串行重启并验收 8793，完成 G0 生产准入证据封板；然后
  重新只读刷新 T41，从 Identity 阶段开始小批量真实补证。不得先恢复全部队列或直接
  开始 G2/G4/G5。
- 本次没有触发真实采集、补证、monitor-loop、pre-soak、24h soak 或 Windows 计划任务。

最后更新时间：2026-07-29 17:18（Asia/Shanghai）

### 2026-07-29 词库原文件重新核验

- 原始工作簿已只读定位并确认仍存在：
  `C:\Users\Lenovo\Desktop\小红书K12&虚拟产品抓取.xlsx`。
- 文件大小 13,939,383 字节，工作表 `文本1`，共 66,491 行、14 列；除表头外有
  66,490 条商品数据，商品标题非空 66,490 条。
- 主要字段包括一级场景、二级场景、解决方案类型、商品标题、商品链接、价格、销量、
  销售额、店铺名称、店铺链接、店铺粉丝数和店铺销量。
- 只读统计得到 10 个一级场景、161 个二级场景、15 个解决方案类型；一级场景包括
  学科学习、教师发展、校园活动、兴趣爱好、考试、心理健康、研学实践、非标升学、
  家庭教育和生理健康。
- 重要纠正：当前 `config\seed_keywords.txt` 只有 78 个种子词；
  `config\keyword_portfolio.json` 明确写着当前配置“未读取项目外原始 xlsx”。
  因此此前“已从 66,491 行历史商品表中完成提炼”的表述不够准确。当前只能确认首批
  78 个词被标记为来自该表，不能证明完整 66,490 行已经被系统分析或覆盖。
- `coordination\TASK_BOARD.md` 已据此把完整原始词库结构化提炼新增为 M5-00/P0，
  并下调关键词发现与轮转的完成度。原文件未被修改。

### 2026-07-29 100 个形态词与原表的双源决策

- 用户提供了 100 个通用商品形态词，如模板、手册、笔记、方案、表格、题库、课件、
  清单、脚本、资料库、提示词等。
- 对原表 66,490 条商品标题做只读精确匹配：
  - 至少命中一个形态词的商品 22,125 条，行覆盖率 33.28%；
  - 73/100 个词在原表有命中；
  - 覆盖 156/165 个实际一级+二级场景组合，场景覆盖率 94.55%；
  - 高频词包括课件 8,714、模板 3,411、笔记 1,700、合集 1,534、讲义 1,272。
- 结论：100 词横向覆盖很强，但单独搜索过宽；原表提供领域/场景纵轴，100 词作为
  商品形态横轴。采用两者结合，不把图片中的原始 100 词直接当成最终搜索词。
- 最终目标是从“领域/场景 × 商品形态”中筛选 100 个可直接搜索的核心查询，建议
  初始结构为 60 个原表支持组合、25 个非 K12 补充组合、15 个探索组合；全部先人工
  审核，首批只投 10–20 个。
- 详细证据与边界记录在 `coordination\M5-keyword-source-evaluation.md`。

### 2026-07-29 放弃过时原表，改用100个发现型根词

- 用户确认旧 Excel 是去年 12 月的虚拟资料统计，现已过时且教育类偏向明显，不再
  具有关键词验证价值。
- 已将精确文件 `C:\Users\Lenovo\Desktop\小红书K12&虚拟产品抓取.xlsx` 送入
  Windows 回收站；删除前大小 13,939,383 字节，删除后原路径 `Test-Path=False`。
  该操作可从回收站恢复，但未经用户要求不得恢复。
- 已创建 `config\discovery_root_terms.txt`，保存用户确认的100个发现型根词。
- `config\seed_keywords.txt` 78 个旧词只保留用于审计当前66个待处理任务，不得重新
  全量导入；`keyword_portfolio.json` 当前126个离线候选也视为旧方案，后续需基于
  100根词重新设计。
- `coordination\TASK_BOARD.md` 已取消原表结构化提炼任务，并把“根词搜索→真实结果
  短语→衍生词→人工审核”的闭环提升为 M5/P0。
- 本次没有修改生产数据库，没有启动监控、ADB、小红书采集、pre-soak 或计划任务。

### 2026-07-29 关键词策略正式收口

- 已新增 `coordination\KEYWORD_STRATEGY.md`，作为关键词来源、逐商品拆解、组合、
  人工审核和有限轮转的唯一现行策略。
- 当前闭环确定为：100 个发现型根词宽搜索 → 每条真实商品沉淀领域/场景/人群/
  形态/阶段/功能词元 → 数据达到门槛后生成有证据支持的组合 → 人工审核 →
  批准词有限入队 → 轮转结果继续反哺词库。
- 默认小样组合门槛为至少 30 个有效不同商品、10 个不同根词和 3 个不同领域/场景；
  稳定组合阶段至少 100 个有效商品、30 个根词，单个组合至少由 2 个不同商品支持。
  门槛在首轮真实试点后可以根据命中率和噪声率调整。
- `README.md`、`ROADMAP.md`、`OPERATIONS.md` 和
  `coordination\TASK_BOARD.md` 已同步到新策略。旧 78 词和旧 126 候选只保留
  审计/兼容用途，不得批量入队或主导新轮转。
- 项目板已把 M5-01 策略定义标记为完成，并将后续拆成逐商品持久化、支持度组合、
  新审批界面适配、批准清单写入和真实轮转验证。关键词新闭环仍未实现，不能把
  “策略已写清”算成“关键词发现与轮转已完成”。
- 本次仅修改离线文档和旧组合配置的说明文字；没有写生产数据库，没有操作 8793、
  8765、ADB、BlueStacks、小红书真实 UI，也没有启动任何采集、soak 或计划任务。

### 2026-07-30 新总控最小上下文交接

- 用户决定更换新对话，避免当前长对话继续增加上下文和 token 成本。
- 已新增 `coordination\NEXT_CONTROL_HANDOFF.md`。新总控开局只需读取全局
  `AGENTS.md`、该压缩交接，以及统一项目板第 1–6 节和第 20 节；不得开局通读完整
  HANDOFF、PARALLEL_WORK、全部专项文档或历史对话。
- 项目板第 20 节已纠正：旧 T67/T68/T69 不再阻塞主线。新固定顺序为 M1/M2
  生产验收 → M5 新关键词最小实现 → M3 小批真实数据补证与根词试点 →
  G2/G3/G4 → 用户确认后的 G5。
- 交接文档内已写明历史快照、必须重新只读核验的项目、按阶段读取表、真实状态所有权、
  硬停止条件、低 token 并行规则和可直接复制的新对话提示词。
- 本次只修改文档，没有操作生产数据库、8793/8765、ADB、BlueStacks、小红书真实 UI，
  没有启动采集、scheduler、monitor-loop、soak、heartbeat 或 Windows 计划任务。

### 2026-07-30 新总控读取规则纠正

- 用户指出正式 `HANDOFF.md` 不能被新总控跳过。已纠正
  `coordination\NEXT_CONTROL_HANDOFF.md`：新总控开局必须读取 HANDOFF 最新约
  180 行，同时完整读取统一项目板。
- 为控制 token，开局不从第一行通读 HANDOFF 的全部历史；遇到状态冲突、历史决策或
  专项证据需要追溯时，再按关键词和章节定向读取更早内容。
- `PARALLEL_WORK.md`、完整 ROADMAP/OPERATIONS、全部 T 文档、全部源码和测试仍不在
  开局读取范围，执行到相应阶段时按交接文件第 8 节读取。

### 2026-07-30 14:20 新总控首次只读核验

- 8793 仍由本项目 PID `43912` 监听，父进程为 PID `45820`；命令行项目根目录、
  `xhs_scout.cli serve` 和端口均正确。`/api/status`、`/api/monitor/status`、
  `/export/candidates.csv` 均返回 200。
- 8765 仍由其他 Agent 的 `video_course_agent` PID `21820` 监听；本次未触碰。
- 当前数据仍为 66 个 pending、23 个商品、29 条商品观察、5 条笔记观察、13 个
  API 当前候选。数据库 `PRAGMA quick_check=ok`、`query_only=1`；0 个 running
  task、0 条运行租约。
- `desired_state=paused`、`scheduler_running=false`、`next_run_at=null`；
  `risk_stop_reason`、`last_block_reason`、`last_skip_reason` 均为空。
- Rvc64 `127.0.0.1:5555` 在线，前台为
  `com.xingin.xhs/com.xingin.alioth.search.GlobalSearchActivity`；
  `dumpsys activity lastanr` 显示本次开机以来无 ANR。
- 旧 Codex heartbeat `小红书选品离线总控台` 存在但状态为 `PAUSED`；当前没有
  活动子任务，也未发现 monitor-loop、soak 或本项目 Windows 计划任务残留。
- 只读核验偏差：生产库为 WAL 模式，标准 `mode=ro + query_only` 连接仍生成了
  0 字节 `data\xhs_scout.sqlite3-wal` 和 32 KiB
  `data\xhs_scout.sqlite3-shm` sidecar。主库大小、修改时间和 SHA-256
  `FC359585DD67E3477A32E17B654FE7383309A958F45263DCCAF7E1438C1D159C`
  在查询前后未变；未擅自删除 sidecar，后续生产只读检查改用不创建 sidecar 的方式。
- 本次未触发真实采集、补证、scheduler、monitor-loop、pre-soak、24 小时 soak，
  未安装计划任务，也未修改生产数据库主文件。

下一步：按统一项目板进入 M1，只串行重启并验收本项目 8793；8765 保持不变。

### 2026-07-30 14:28 M1 当前代码加载与生产工作台验收完成

- 重启前工作台定向回归通过：`86 passed in 6.25s`；从实际
  `render_workbench_html()` 提取的内嵌 JavaScript 通过 `node --check`。
- 所有权脚本 dry-run 再次确认唯一停止目标为本项目 8793 / PID `43912`，随后串行
  停止该监听者。停止后 8793 无监听，8765 仍由其他 Agent PID `21820` 监听。
- 使用 `ops\start_workbench.ps1 -Execute` 启动当前代码；新 8793 监听 PID 为
  `62700`。健康检查 `ok=true`，`/api/status`、`/api/monitor/status` 和候选 CSV
  均为 200。启动日志只有正常 Uvicorn 启动记录。
- 重载后仍为 `desired_state=paused`、`scheduler_running=false`、
  `scheduler.thread_alive=false`、`next_run_at=null`；risk/block/skip 均为空。
  本次重启没有恢复 scheduler，也没有触发真实采集。
- 真实浏览器验收通过：
  - 候选商品显示 23 个商品和 13 个当前候选；
  - 监控任务显示 66 个待搜索任务，状态为已暂停；
  - 报告与质量正常展示 readiness、补证计划和补证审批只读面板；
  - 关键词池正常展示旧兼容组合、衍生建议和关键词审批只读面板；
  - 四工作区切换正常，浏览器 console 无 warning/error。
- readiness、补证审批、关键词审批在当前运行服务 OpenAPI 中均只有 GET。缺
  baseline、scheduler evidence、补证审批或关键词审批清单时均 fail closed；
  `soak_start_authorized=false`，补证审批
  `execution_status=not_executed / authorizes_execution=false`，关键词审批 scope
  的 queue/search/monitor/soak 授权均为 false。页面未发现补证、搜索或 soak
  执行按钮。
- 当前完整离线回归：`568 passed, 3 skipped in 60.76s`。这是重载后唯一完整
  基线；3 个 skip 保留现有严格测试定义，未新增 xfail/skip 或放宽断言。
- 关键文件 SHA-256：
  - `src\xhs_scout\web.py`：
    `79EE4C5EC2EF77434CE6975D1F7DFE5904F0B1F0632B7047C6E1BA26D2E8DF64`
  - `src\xhs_scout\workbench_ui.py`：
    `B352A8F847E50AD24EE5762ED7260D9B7C68BC0C680CD6370F303BF0C2DAB2D8`
  - `config\discovery_root_terms.txt`：
    `E107D880EB6ACB7C59790BDB354C0391FA85A0C1D3673AD98C89EB9B979140E7`
  - `config\seed_keywords.txt`：
    `8EB3C42E778B12A3BAB2C43850A1671591978B6CD4D552D162AD81C09BFA9A4E`
  - `config\keyword_portfolio.json`：
    `6EB7097D76D1839A654A9AEB5694B12DDC21504775050533FC0B2F17973138FA`

M1 已完成。下一步按统一项目板进入 M2，生成当前生产 baseline manifest 并完成
G0 证据封板；这不授权 scheduler、真实补证、monitor-loop 或 soak。

### 2026-07-30 14:35 M2 / G0 当前生产证据封板

- 已生成并回读重验 `evidence\soak-baseline.json`：
  - baseline id：`pre-soak-baseline-7139bae333e41c73`；
  - manifest hash：
    `0a909e54cc6f27a8b985d5e419f393614c8e747954ada0596ae41874c04e34c0`；
  - 文件 SHA-256：
    `CE20E9735AF90A9234063D9B6DA29BCC3BC88B1764E58D953B5E5D407F66E7BF`；
  - 记录 45 个显式代码/config 文件、生产 DB quick_check/计数、8793/8765 owner、
    固定 1×1 参数、磁盘/日志摘要和已验证停止入口；
  - pre-soak、24h soak、scheduler 启动授权全部为 false。
- 首次用 `immutable=1` 查询时 `PRAGMA journal_mode` 报成 `delete`，与本轮较早通过
  正常 `mode=ro + query_only` 核验的真实 WAL 状态不一致；该不准确 manifest 已被
  重建覆盖，最终清单明确记录 `journal_mode=wal`。
- G0 四项证据没有凭空置 true：
  - 重载后完整回归为 `568 passed, 3 skipped in 60.76s`；
  - SQLite 并发、scheduler 恢复/关闭、scheduler lease、monitor lease-lost 和
    run-control 定向复验为 `29 passed in 2.29s`；
  - 生产 DB `quick_check=ok`，run_events 中 malformed JSON 数为 0。
- 已生成 `evidence\g0-readiness.json`：
  - G0=`passed`、baseline=`passed`；
  - G1=`failed`、G2=`failed`、G3=`insufficient_evidence`、G4/G5=`failed`、
    G6=`not_reached`；
  - `ready_for_pre_soak=false`、`ready_for_24h_soak=false`，所有启动授权 false；
  - 文件 SHA-256：
    `A6BF8240BAE10ECC7EC857F2637AE169B119F6068247EC486E704F275F5AD7BB`。
- G1 口径说明：本文件从全量历史 run_events 做通用 readiness，历史轮次包含失败/
  风险，因此不能替代 T42 对指定三轮的专项 G1 通过结论；两者范围不同。当前 M2
  只封板 G0，不重判 G1。
- 已生成并回读 `evidence\pre-soak-evidence-bundle.json`：
  - bundle id：`pre-soak-evidence-d8de02a01b61f001`；
  - 状态 `incomplete`；
  - baseline/readiness 为 valid，ACK、scheduler due-point evidence、remediation
    approval 为 missing；
  - 证据包明确 `authorizes_execution=false`、`authorizes_soak=false`；
  - 文件 SHA-256：
    `BEC428EAB425575B846997F89BBAD4A2D14A6AE7D3C5D23883189B4C928C8D28`。
- baseline/readiness/evidence-bundle 的 fail-closed 定向回归：
  `72 passed, 3 skipped in 12.26s`。漂移、损坏、过期、计划 hash 不一致和 gate
  矛盾仍会阻止准入。
- 运行服务的 `/api/soak-readiness` 已能重新验证 baseline 为 passed，但该接口
  没有注入本轮离线测试事实，故其 G0 仍保守显示 `insufficient_evidence`。正式 G0
  结论以本轮固定 `g0-readiness.json` 和证据包为准；接口未被放宽或伪造为通过。
- M2 结束时 8793 PID `62700` 健康，仍为 paused；scheduler 未运行，
  `next_run_at=null`，risk/block/skip 均为空。生产 DB SHA-256 仍为
  `FC359585DD67E3477A32E17B654FE7383309A958F45263DCCAF7E1438C1D159C`，
  大小 1,019,904 字节。

M2 正式结论：**G0 当前快照通过；整体 pre-soak/24h 准入仍不通过。** 后续 M5
代码或 config 发生变化会使当前 baseline 失效，进入 G2/G4 前必须重新封板。
下一步按统一项目板进入 M5-01A，不回到旧 78 词、旧 126 候选或旧审批界面扩展。

### 2026-07-30 14:43 M5-01A 逐商品关键词拆解离线实现

- 新增 `product_keyword_records` 与 `product_keyword_terms` 两张表的 schema，
  以及 `src\xhs_scout\product_keyword_terms.py`。本阶段没有连接或迁移生产库；
  持久化只在 pytest 临时 SQLite 中验收。
- 每条拆解记录固定绑定发现根词、run/task/product/observation、原始与规范标题、
  搜索结果位次、搜索上下文、链接缺口、证据、风险/噪音和人工审核状态；词元维度
  限定为领域、场景、人群、形态、阶段、功能六类。
- 持久化前会反查商品—观察—任务—run—搜索证据同链，核对发现根词属于现行
  `config\discovery_root_terms.txt`，并限制证据路径只能位于允许根目录。上下文丢失、
  商品身份不明、证据越界或 run 链不一致均失败关闭，不产生半行数据。
- 新词固定为 `pending_review`，scope 中 queue/search/monitor/soak/write 授权全
  false；该模块没有入队、搜索、scheduler 或 UI 执行动作。
- 现行根词文件实测为 100 个非重复词；没有读取回收站 Excel，也没有让旧 78 词或
  旧 126 候选参与拆解。
- 新模块和现有关键词发现定向：`21 passed in 0.41s`；DB/Web/baseline/证据包相邻
  回归：`59 passed, 3 skipped in 15.45s`。未新增 skip/xfail。
- M5 改动后对旧 `evidence\soak-baseline.json` 做只读重验，按预期失败关闭：
  `observed file changed after baseline: src/xhs_scout/db.py`。因此 M2 的 G0 结论
  现在是历史检查点；本批代码收口并重载后必须重新生成 baseline/readiness/bundle。
- 8793 仍运行 M1 已验收版本 PID `62700` 且保持 paused；本次没有重启服务、操作
  8765、触发 ADB/真实采集、修改生产数据库或启动 scheduler/monitor-loop/soak。

下一步：按统一项目板进入 M5-01B 支持度统计和分阶段组合；达到当前批次出口后，
再统一完整回归、重载 8793 和重封 G0，避免每个离线小模块都重复操作真实服务。

### 2026-07-30 15:03 M5 最小代码闭环加载与 G0 重封

- M5-01B 已实现支持度统计与分阶段组合：
  - 小样门槛严格为 30 个有效不同商品、10 个发现根词、3 个领域或场景；
  - 稳定门槛为 100 个商品、30 个根词，单个稳定组合至少 2 个不同商品支持；
  - 候选只截取真实标题中相邻或极小间隔的自然连续表达，不做跨商品词元全排列；
  - 风险、噪音、链接缺失或搜索/run 证据链不完整的记录不能解锁门槛。
- M5-02 已新增 `/api/keyword-combination-review` GET-only 接口和“新策略组合候选 ·
  只读审核”工作台区域。页面只显示业务结论与支持度，不显示证据路径/内部 ID，
  没有批准、入队、搜索、monitor 或 soak 按钮。
- M5-03 已实现默认 dry-run 的批准词入队计划：
  - 数据集指纹和候选证据指纹必须与当前分析完全一致；
  - 每次最多 5 词，关键词冷却至少 24 小时，活动任务和历史冷却均去重；
  - 真正执行还要求 monitor paused、0 running、0 run lease、精确 plan hash 确认；
  - 写入使用 savepoint，队列变化会整批回滚，并记录一次性审计；
  - 本轮没有生成真实批准清单，也没有对生产调用 execute。
- M5 新增与相邻定向测试通过；当前唯一完整回归：
  `590 passed, 3 skipped in 67.69s`。未新增 skip/xfail 或放宽断言。
- 所有权脚本再次确认旧 8793 PID `62700` 后串行停止并重载；当前 8793 PID
  `36648`，8765 仍为其他 Agent PID `21820`，未触碰。
- 重载只执行预期 schema 增量：
  - 搜索任务仍 88，总 pending 仍 66，running 0，run lease 0；
  - `product_keyword_records`、组合 snapshot、queue audit 当前均为 0；
  - `PRAGMA quick_check=ok`；
  - 主库大小 1,069,056 字节，SHA-256
    `209AB8FC3C69E8570F6C01181696394BDAC026E463AB2D2E5FF5E87337C14A28`。
- 真实浏览器验收：候选 13、待处理 66；新策略审核区显示 0 有效商品、0 根词、
  0 候选并明确“门槛未达到，只积累”；浏览器 console 零 warning/error。
- 已重新封板：
  - baseline `pre-soak-baseline-95e6dec99cfa79d0`，manifest hash
    `857d933ba9f2d7314703e7ee77205e09d58cd88b7c2695665767e1421575db1a`，
    文件 SHA-256
    `595C57C22698DC11A6541282D458BBA4CBA286CCAA74DA67A0C7A26BFEEE48C2`；
  - `g0-readiness.json` 的当前 G0=`passed`，G1=`failed`、G2=`failed`、
    G3=`insufficient_evidence`、G4=`failed`，文件 SHA-256
    `EBFC065AD5BF54FC1CA76777149191D4CD614FF0E52D02EEA002EB6AD06A5E82`；
  - bundle `pre-soak-evidence-6a08cbb1870e136a` 仍为 `incomplete`，
    ACK、scheduler evidence、补证审批仍缺失，文件 SHA-256
    `FFE475F5243B4A550CA4E3DE8082F971E6B75F28EF14151108FAF46182199ACC`；
  - 重封后准入定向 `110 passed, 3 skipped in 26.18s`。
- 当前 8793 仍 paused，scheduler thread false、next_run_at null，risk/block/skip
  均为空。未触发 ADB、真实采集、补证、monitor-loop、pre-soak 或 24 小时 soak。

下一步：按统一项目板只读刷新 T41 和首批 10–20 个不同形态发现根词，然后从
M3-I1 开始小批真实补证；新增真实商品同时进入新拆解表。数据不足 30/10/3 时只
积累，不生成组合。任何验证码、风控、ANR、未知页、上下文丢失、身份不明或 DB
锁异常立即停止并保留证据。

## 2026-07-30 15:20 检查点：M3 首批硬停并完成安全收口

- 总控按实时 `/api/remediation-plan` 启动 M3-I1，批次为 product `22 + 9`，
  严格先执行 22，任何硬停即取消 9。
- 15:11 preflight 通过：Rvc64 位于搜索结果页，无验证码/风控/ANR；证据目录：
  `data/probes/m3-preflight-20260730T151146+0800`。
- 本轮仅创建一个补证任务并调用一次 1×1 `run-once`；run id
  `monitor-7c25e73a97c1` 在进入商品前被
  `search results keyword mismatch` 拦截，processed=0、captured=0。
- 已确认根因是总控调用链的中文编码损坏：task 93 的目标“阅读理解”实际写成
  `????`，不是平台风控，也不是商品身份判断。product 22 未访问、product 9
  未执行；商品仍 23、观测仍 29、有效链接仍 5。
- `run-once` 默认还意外恢复了 task 94 `仿写训练`。task 93、94 均未删除，
  已原地标记 `failed` 并写入 `controller_cleanup` 审计事件；pending 恢复 66，
  running=0、run lease=0。
- 已修复 `src/xhs_scout/web.py`：Web `run-once` 明确传入
  `requeue_due_keywords=False`，避免受控单轮夹带旧轮转恢复；新增契约测试，
  `tests/test_workstation_contract.py` 为 `5 passed in 1.13s`。
- 8793 已通过项目所有权脚本串行重载，当前 PID `29220`；8765 仍为其他 Agent
  PID `21820`，未触碰。当前 8793 健康、desired_state=paused、
  scheduler_running=false、next_run_at=null、risk_stop_reason=null、
  last_skip_reason=null，保留
  `last_block_reason=search results keyword mismatch`。
- 数据库 `PRAGMA quick_check=ok`，search_tasks=90、pending=66、running=0、
  run_leases=0。未发现残留 heartbeat、monitor-loop、soak 或并行任务。
- 15:03 的 baseline/G0 证据是变更前历史快照；因本轮 DB 审计记录和代码已变化，
  统一项目板已将当前 G0 标成“待下一稳定检查点重封”，不得继续把旧 hash 说成
  当前生产快照。
- M5-04 已拟首批 12 个不同形态发现根词：
  `模板、清单、表格、手册、话术、脚本、方案、预算表、合同、食谱、图纸、提示词`。
  仍待用户人工审核；本轮未入队、未搜索，未使用旧 78/126 词驱动生产。

下一步：保持停止状态，不在本批重试。新批次先用 UTF-8 安全参数重新入队并做
preflight，再按 M3-I1R 先 22、后 9；任何硬停仍立即取消余项。稳定后重封 G0。
M5 的 12 个根词只有用户审核通过后才允许有限入队。G5 和 Windows 计划任务仍
没有授权。

## 2026-07-30 15:25 检查点：首批发现根词已批准并有限入队

- 用户已明确批准 12 个发现根词：
  `模板、清单、表格、手册、话术、脚本、方案、预算表、合同、食谱、图纸、提示词`。
- 现行 `config/discovery_root_terms.txt` 有 103 个非空行，其中前 3 行为注释，
  实际为 100 个唯一根词；上述 12 词全部属于现行根词库。文件 SHA-256：
  `e107d880eb6acb7c59790bdb354c0391fa85a0c1d3673ad98c89eb9b979140e7`。
- 发现现有 M5-03 planner 只接受达到 30/10/3 门槛后的组合候选，不能把发现根词
  伪装成组合词。因此新增独立根词批准 planner：
  - 必须绑定根词文件指纹、逐词来源指纹、`discovery_root_pilot` 类型和安全 scope；
  - 必须显式指定当前批次，单批最多 5 词；
  - 仍复用活动任务去重、24 小时冷却、paused/running/lease、精确 plan hash、
    savepoint 原子写入和一次性审计门禁。
- 首次真实 execute 被门禁拒绝且没有写入：生产 `desired_state` 使用 JSON
  `"paused"`，旧执行器错误按裸字符串比较。已改为统一 `get_monitor_state`
  解码并补生产格式回归测试；批准入队定向 `8 passed`，与工作台契约合计
  `13 passed`。
- 批准清单：
  `approvals/discovery-root-pilot-approval.json`。
  首批计划证据：
  `evidence/discovery-root-pilot-queue-plan.json`。
- dry-run 精确选择 `模板、话术、预算表、合同、食谱`，其余 7 词标记
  `future_batch`。plan hash：
  `1aa9efda77c49f8c1f16b19d5b609233c41e4421013bc44f69712e997c1c1579`。
- 相同 hash 经重新计算后执行成功，新增 task 95–99，source 均为
  `approved_discovery_keyword`，status=pending、attempts=0、next_run_at=null；
  `keyword_queue_audits` 新增 1 条，inserted_count=5。
- 当前生产：search_tasks=95、pending=71、running=0、run lease=0；
  products=23、observations=29，`PRAGMA quick_check=ok`。
- 8793 已重载当前代码，PID `3296`；8765 仍为其他 Agent PID `21820`，未触碰。
  desired_state=paused、scheduler_running=false、next_run_at=null；
  risk_stop_reason/last_skip_reason 均为空，保留上一批历史
  `last_block_reason=search results keyword mismatch`。无残留 heartbeat、
  monitor-loop、soak 或并行任务。
- 本检查点只批准和入队，没有搜索、ADB 操作、采集、scheduler、monitor-loop、
  pre-soak 或 24 小时 soak。15:03 G0 继续属于历史快照，待后续稳定点重封。

下一步按统一项目板：先处理 M3-I1R 的 UTF-8 安全重试，再从 task 95–99 中按
每小时最多 1 词、每词最多 1 商品执行首个根词真实试点；出现任何 hard stop
立即停止，不继续下一个词。其余 7 个已批准根词只有在首批结果复核后才进入下一批。

## 2026-07-30 15:55 检查点：策略切换为“虚拟资料”并因 ANR 硬停

- 用户纠正业务口径：
  - 不再做旧商品链接、关联笔记、笔记发布时间或笔记互动补证；
  - 当前主发现入口改为 `虚拟资料`；
  - 商品详情页至少出现 3 个不同有效灰色指标条，才进入总控台；
  - 达标商品无论粉丝多少都保留；
  - 粉丝取商品对应店铺/发布账号主页，1～2000 标注低粉爆款，超过 2000
    仍保留为小爆款；不使用关联笔记作者数据；
  - 达标商品标题继续拆解人群、类别、场景、形态、阶段和功能词元，迭代种子词。
- 已更新 `coordination/KEYWORD_STRATEGY.md` 和统一项目板。原 100 根词降为备用池，
  task 95–99 已暂停并保留批准/入队审计；旧 M3-I1R 退出当前主线。
- 已实现并加载 3 灰条门槛：
  - 初始商品截图只生成 `observed`；
  - 指标条帧中至少 3 个不同、未污染、未忽略、未重复的有效项目才生成
    `candidate`；
  - 工作台候选区只展示灰条数不少于 3 的商品；
  - 低粉区域改为店铺账号粉丝字段，不再显示笔记点赞/发布时间；
  - 定向及相邻测试共 `87 passed`。
- 当前历史 23 个商品中，按新灰条证据口径有 6 个可进入总控台；这是历史数据
  重算结果，不代表本轮新增。
- 复用了现有 task 89 `虚拟资料`，source 改为
  `virtual_materials_discovery_pilot_reused`、priority=100、max_attempts=1；
  未新建重复任务。
- 真实执行前的只读 probe：
  `data/probes/probe-2026-07-30T15-52-24+08-00`。
  截图明确显示“小红书没有响应”对话框，选项为“关闭应用/等待”。
  虽然当时 `dumpsys` 未返回 ANR，视觉证据已满足硬停止条件。
- 总控没有点击对话框、没有输入 `虚拟资料`、没有搜索、没有打开商品，也没有
  新增商品或观察。task 89 仍 pending、attempts=0。
- 已写入风险状态：
  `risk_stop_reason=last_block_reason=ANR dialog visible: 小红书没有响应`；
  desired_state=paused、scheduler=false、next_run_at=null、running=0、lease=0。
- 当前数据库：products=23、observations=29、search_tasks=95、pending=66、
  paused=6，`PRAGMA quick_check=ok`。8765 未触碰，未启动 scheduler、
  monitor-loop、pre-soak 或 24 小时 soak。

下一步必须由用户先人工处理模拟器中的无响应对话框并确认小红书恢复正常。总控随后
重新只读 probe，按精确风险原因走审计恢复，再执行 task 89 的单次
`虚拟资料 × 1 商品`。不得自动点击“等待”或“关闭应用”，不得绕过 ANR 风险状态。

## 2026-07-30 16:05 检查点：ANR 已恢复，首轮“虚拟资料”试点因搜索词不匹配硬停

- 用户人工处理 ANR 后明确回复“OK了”。总控随后执行只读 probe：
  `data/probes/probe-2026-07-30T15-59-45+08-00`。
  该 probe 未发现 ANR 或风险页，前台 Activity 为
  `com.xingin.xhs/.index.v2.IndexActivityV2`。
- 按精确原因清除了
  `ANR dialog visible: 小红书没有响应` 风险状态；清除后立即继续保持
  `desired_state=paused`，scheduler 没有获得授权，也没有启动。
- 只执行了一次受控 `虚拟资料 × 1 商品`：
  - run_id：`monitor-584572f930c2`；
  - `max_keywords=1`、`max_products_per_keyword=1`；
  - `note_evidence=false`、`requeue_due_keywords=false`；
  - 结果为 `processed_tasks=0`、`captured_products=0`、
    `requeued_tasks=0`；
  - 硬停止原因：`search results keyword mismatch`。
- task 89 的数据库关键词仍是正确的 `虚拟资料`。但起始证据
  `data/probes/monitor-584572f930c2-probe-start/current.png`
  显示搜索框仍是无关旧词“真正的硅水凝胶品牌美瞳”，商品网格也是旧搜索结果。
  因此这是搜索页旧词清空/新词提交链路失败，不是任务关键词编码错误，也不能通过
  放宽关键词一致性检查绕过。
- 本轮没有打开商品详情、没有采集灰条、没有查看店铺主页，也没有新增商品或观察。
  生产仍为 products=23、observations=29、search_tasks=95。
- 为防止自动重试，task 89 已在精确状态断言后改为 paused、attempts=1、
  next_run_at=null、run_owner=null、run_lease_expires_at=null，并写入
  run_event 391 `pilot_task_paused`。当前 pending=65、paused=7、
  running=0、run_leases=0。
- 收尾核验：
  - `PRAGMA quick_check=ok`；
  - desired_state=paused、scheduler_running=false、next_run_at=null；
  - risk_stop_reason=null；
  - last_block_reason=`search results keyword mismatch`；
  - last_skip_reason=null；
  - 8793 为 PID 31424 且 `/api/monitor/status` 正常响应；
  - 8765 仍为其他 Agent 的 PID 21820，未触碰；
  - ADB `127.0.0.1:5555` 在线；
  - 小红书前台为 IndexActivityV2，`dumpsys activity lastanr` 为
    `<no ANR has occurred since boot>`；
  - 未发现残留 heartbeat、monitor-loop、pre-soak 或 soak 进程。

下一步按统一项目板执行 M5-05B1：先离线定位并修复搜索页旧词清空、新词输入/提交
和结果页一致性链路，保留现有 fail-closed 检查。定向测试通过后，才允许重新安排
下一次 `虚拟资料 × 1 商品`。本检查点不再操作真实 UI；G5 和 Windows 计划任务
仍未获授权。

## 2026-07-30 16:42 检查点：100 根词继续保留；第二次试跑误取旧任务后硬停

- 用户明确纠正：现有 100 个种子词不删除、不清空、不作废，后续仍可使用；
  `虚拟资料` 只是第一波优先检测词。已同步更新
  `coordination/KEYWORD_STRATEGY.md` 和统一项目板。
- 已修复 M5-05B1：
  - 真实根因为市集搜索结果页处于 IndexActivityV2，旧代码只在
    GlobalSearchActivity 中重置不匹配搜索词；
  - 现改为市集结果页优先点击顶部搜索框，全局搜索继续沿用原返回输入页逻辑；
  - 没有放宽结果页关键词一致性硬检查；
  - 新增市集直接重置回归测试，相关定向/安全测试 `29 passed`。
- 重载 8793 时曾出现两项本地环境问题：
  - 首次 `uv` 同步因运行服务锁住 onnxruntime DLL 中断，导致虚拟环境缺少
    uvicorn；
  - 停止 8793 后已执行 `uv sync` 恢复运行依赖，并重新安装测试依赖；
  - 8793 最终已由新代码恢复监听，PID 56800；8765 未触碰。
- 真实执行前 probe
  `data/probes/probe-2026-07-30T16-36-43+08-00`
  显示当前为 GlobalSearchActivity/search_input，无 ANR、无风险页。
- 原计划先把 task 89 从 paused 精确恢复，再发单次 run-once。但恢复脚本调用
  `ZoneInfo("Asia/Shanghai")` 时因本机虚拟环境缺少 tzdata，在任何数据库写入前
  失败；PowerShell 没有因前一进程非零退出而停止，随后仍发送了 run-once 请求。
- 由于 task 89 仍为 paused，run `monitor-e50b286e05c2` 错误选择了旧 pending
  task 21 `学习方法`。这不是 `虚拟资料` 第一波结果：
  - 搜索词提交为 `学习方法`；
  - 打开了 1 个商品并新增 product 30、observation 30；
  - 商品标题为
    `4.被弯/被慰/被盘问？高情商应答模板（通用+场景版）`；
  - 识别为虚拟商品，4 个有效灰条字段为：近 30 天购买 1000+、近 30 天好评
    900+、近 7 天感兴趣 1000+、近 30 天收藏 200+；
  - 按用户统一的“至少 3 灰条”规则，该商品是真实有效的小爆款观察，保留在
    总控台；但必须标明来源为旧词 `学习方法`，不能冒充 `虚拟资料` 第一波；
  - 未查看关联笔记、笔记作者或账号粉丝，未执行购买、加购、收藏等动作。
- task 21 在详情采集内部被标记 completed 后，外层租约检查发现
  `task_not_running`，触发硬停止：
  `lease safety blocked at after_detail_capture_and_metrics_ocr: task_not_running`。
  run 结果显示 processed_tasks=0/captured_products=0，但数据库真实新增了
  product 30 和 observation 30；以数据库和 run events 为准。
- 已追加 run_event 406
  `unintended_task_executed_after_arming_failure`，完整保留准备失败、误选任务和
  新增记录证据。没有删除真实商品，也没有继续 UI 重试。
- 收尾状态：
  - products=24、observations=30、search_tasks=95；
  - task 89 仍为 paused、attempts=1、next_run_at=null；
  - running=0、run_leases=0；
  - desired_state=paused、scheduler_running=false、next_run_at=null；
  - risk_stop_reason=last_block_reason=
    `lease safety blocked at after_detail_capture_and_metrics_ocr: task_not_running`；
  - `PRAGMA quick_check=ok`，无 ANR。

下一步是 M5-05B2：先离线实现 run-once 对 task_id/关键词的精确绑定，并确保任何
准备步骤失败都不会继续发送真实请求；同时修复详情内部完成任务与外层租约检查的顺序。
只有定向测试通过、用户确认当前硬停止原因后，才允许再次恢复 task 89。不得把本轮
product 30 计入 `虚拟资料` 第一波，也不得删除现有 100 根词。

## 2026-07-30 18:10 检查点：`虚拟资料` 单商品闭环已完成

- 用户本轮把范围收缩为一个可见的真实闭环：
  - 总控台商品销量必须按小红书原文展示；
  - 不显示昨日累计、今日累计和采集日期；
  - 只显示“24小时新增销量”；
  - 用户界面移除“报告与质量”；
  - 用 `虚拟资料` 搜索一个真实商品，补齐灰色条、店铺账号粉丝、可跳转商品链接、关键词拆解和单品分析。
- 已完成代码修正：
  - `ProductSignals` 新增 `cumulative_sales_display` 与 `cumulative_sales_exact`；
  - 全页识别 `已售/目前已售`，`1.9万+` 原样保存，只有无单位、无加号的整数才进入 exact；
  - observations 新增 `cumulative_sales_display`、`cumulative_sales_exact`、`daily_sales_delta`；
  - 具体整数前后采集间隔 20–28 小时时计算差值；模糊销量不计算；
  - 候选表显示“商品销量”和“24小时新增销量”，移除商品行采集日期；
  - “报告与质量”从用户导航移除并保持不可见；
  - 低粉筛选与排序统一使用 `seller_follower_count`，不再使用笔记作者粉丝；
  - 新增 `/products/{product_id}/analysis` 用户可见单品分析页。
- 已完成安全链修正：
  - run-once 支持 `task_id + expected_keyword` 精确绑定；
  - `capture_current_page_for_task(..., complete_task=False)` 由 monitor 在补证和搜索页恢复后再完成任务；
  - 修复旧的 `task_not_running` 租约硬停止根因；
  - 新增从商品详情底部“店铺”直接进入店铺页读取粉丝的流程，不访问关联笔记。
- 定向测试最终为 `112 passed`。
- 用户明确授权后清除的旧风险原因为：
  `lease safety blocked at after_detail_capture_and_metrics_ocr: task_not_running`。
  清除后仍保持 desired_state=paused、scheduler_running=false。
- 精确执行 task 89：
  - run_id=`monitor-3c246fd76465`；
  - 搜索词=`虚拟资料`；
  - processed_tasks=1、captured_products=1；
  - 无验证码、风控、ANR、未知页或数据库锁异常；
  - 未触发笔记采集。
- 本次重新从 `虚拟资料` 搜索取得的是原 product 30，但新增了独立、有效的 observation 31 和 task 89 搜索证据。因此旧 observation 30 仍保留为 task 21 误跑证据；新的 observation 31 可以正式计入 `虚拟资料` 第一波。
- 最终商品：
  - 标题：`普通人社会化成长指南-i人社交技巧-人情世故保姆级攻略`；
  - 店铺：`成长论NuYoah.`；
  - 商品价格：到手价 `¥19.8`；商品页同时显示原价 `¥39.8`，工作台使用实际到手价；
  - 商品链接：`https://xhslink.com/m/7X9KDzX3Dxc`；
  - 商品销量：`1.9万+`；
  - exact 销量为空，因此 24 小时新增销量显示“待满24小时”；
  - 有效灰色指标 4 条：近30天购买1000+、近30天好评900+、近30天收藏200+、近7天感兴趣1000+；
  - 店铺账号粉丝 5284；
  - 结论：符合小爆款入台标准，但不是低粉爆款。
- 关键词拆解已写入 product_keyword_records / product_keyword_terms：
  - audience：普通人、i人；
  - domain：人情世故、社交；
  - scene：社交；
  - format：指南、攻略；
  - function：成长、社交；
  - stage：无可靠标题证据，保持为空。
- 浏览器可视验收：
  - 工作台 `http://127.0.0.1:8793/` 第一行显示 `商品销量 1.9万+`、`24小时新增销量 待满24小时`、`店铺账号粉丝 5284`；
  - 商品标题 href 为 `https://xhslink.com/m/7X9KDzX3Dxc`；
  - “分析” href 为 `http://127.0.0.1:8793/products/30/analysis`；
  - 导航无“报告与质量”，报告 panel 不可见；
  - 分析页展示小爆款/非低粉结论、完整指标、4 条灰色指标、五类关键词拆解和分析结论。
- 收尾：
  - 8793=PID 38340；
  - 8765=PID 21820，未触碰；
  - products=24、observations=31；
  - task 89=completed、attempts=2、last_error=null；
  - running=0、run_leases=0、`PRAGMA quick_check=ok`；
  - desired_state=paused、scheduler_running=false、next_run_at=null；
  - risk_stop_reason=null、last_block_reason=null、last_skip_reason=null；
  - ADB 在线，小红书停在 GlobalSearchActivity，`dumpsys activity lastanr` 为 `<no ANR has occurred since boot>`；
  - 无 heartbeat、monitor-loop、pre-soak、soak 残留进程。

下一步固定为：先让用户查看工作台和 product 30 单品分析页；用户确认样品符合预期后，才扩大 `虚拟资料` 的真实商品数量。不得自动启动 scheduler、24 小时采集、pre-soak、G5 或 Windows 计划任务。

### 2026-07-30 价格漏采补正

- 用户截图指出商品 30 的价格仍显示 `-`。
- 根因：旧标题识别错位后，价格解析窗口没有覆盖商品正式价格区；同一份 observation 31 原始文字经现行解析已稳定得到到手价 `19.8`。
- 已把 product 30 的价格补正为 `19.8`，并新增真实版式回归测试，验证原价 `39.8` 与到手价 `19.8` 同时存在时优先使用到手价。
- 工作台浏览器验收：价格显示 `¥19.8`。
- 单品分析页浏览器验收：完整指标依次显示商品价格 `¥19.8`、商品销量 `1.9万+`、24小时新增销量待计算、店铺账号粉丝 5284。
- 定向测试：`62 passed`；8793 已重载为 PID 51060；未触发新的小红书采集。

### 2026-07-30 18:37 数据指标显示口径补正

- 用户指出工作台遗漏“近30天收藏”和“近7天感兴趣”，并把来源中的
  `1000+`、`900+` 错显为 `1000`、`900`。
- 已删除候选商品表的“候选依据”列，把数据指标扩为：
  商品销量、近30天购买、近30天好评、近30天收藏、近7天感兴趣。
- 所有正数下限指标统一保留 `+`；空值仍显示 `-`，零值显示 `0`，不伪造
  `0+`。
- 本地浏览器实际验收商品 30：
  `1.9万+ / 1000+ / 900+ / 200+ / 1000+`，表头已无“候选依据”。
- 定向回归：`47 passed`。
- 8793 已由确认归属本项目的旧 PID 51060 串行重载为 PID 64944；
  根页面和 `/api/status` 均为 200。8765 仍为其他 Agent 的 PID 21820，
  未触碰。
- 本次仅修改展示和测试，没有重新采集、没有生产数据库写入，也未启动
  scheduler、monitor-loop、pre-soak 或 soak。

### 2026-07-30 18:53 用户工作台去技术化

- 用户截图明确指出关键词候选卡片中的支持度、证据来源、来源商品、来源关键词、
  软风险，以及整块“关键词审批清单·只读复核”不应出现在面向用户的控制台。
- 关键词候选卡片现只显示：关键词、重点候选/探索候选、待审核。
- 候选区说明改为自然语言；原始证据计数、去重数、截断数等开发者统计不再展示。
- “关键词审批清单·只读复核”已设置为用户不可见，页面刷新也不再请求该清单；
  后台只读接口和 fail-closed 校验代码保留，未削弱执行安全边界。
- 本地浏览器实际验收：
  - 审批清单 `display:none`；
  - 可见文字不含“支持度”“来源商品”“软风险”“关键词审批清单”；
  - 候选卡片示例为“虚拟资料 / 重点候选 / 待审核”。
- 定向回归：`47 passed`。
- 8793 已由确认归属本项目的旧 PID 64944 串行重载为 PID 3328，根页面 200；
  8765 未触碰。
- 本次没有重新采集、没有生产数据库写入，也未启动 scheduler、monitor-loop、
  pre-soak 或 soak。

### 2026-07-30 18:59 候选表阅读布局补正

- 用户要求价格靠左、数据指标改为两列且不得省略、低粉栏只显示粉丝数，并把
  0–2000 统一标为“低粉爆款”。
- 已发现并修复一个真实列宽错位根因：价格列 `<col>` 与价格内容容器共用
  `commercial` 类名，内容的 grid 样式使价格列宽坍缩，导致后续各单元格错用
  下一列宽度。价格列现使用独立 `price` 类名。
- 当前可见规则：
  - 价格和分数左对齐；
  - 数据指标列 282px，内部两列排列；
  - 五个标签均完整显示，无省略号；
  - 表头由“低粉证据”改为“粉丝数”；
  - 粉丝数缺失显示 `-`，0–2000 显示数值并加“低粉爆款”，超过 2000 只显示数值。
- 本地浏览器验收商品 30：价格 `¥19.8` 距单元格左边 10px；指标列两列各约
  122px，五个标签均未截断；粉丝栏只显示 `5284`，无“超过 2000”标签。
- 定向回归：`48 passed`。
- 8793 已串行重载为 PID 46228，根页面 200；8765 未触碰。
- 本次没有重新采集、没有生产数据库写入，也未启动 scheduler、monitor-loop、
  pre-soak 或 soak。

### 2026-07-30 19:07 监控页安全详情去技术化

- 用户指出“安全状态”卡中的最近心跳、风险停止、最近阻塞、最近跳过和下次运行
  不属于用户需要查看的工作台内容。
- 已从监控页页面结构和绑定代码中删除整张“安全状态”卡；单轮参数区改为整行铺满。
- 后台风险停止、阻塞、跳过和心跳字段继续保留；顶部状态只显示“运行中 / 已暂停 /
  风险停止”等通俗结论，风险恢复保护未删除。
- 本地浏览器验收：监控页可见文字不含“安全状态”“最近心跳”“最近阻塞”，
  对应五个详情节点均不存在；单轮参数区宽 992px，顶部状态为“已暂停”。
- 定向回归：`49 passed`。
- 8793 已串行重载为 PID 40876，根页面 200；8765 未触碰。
- 本次没有重新采集、没有生产数据库写入，也未启动 scheduler、monitor-loop、
  pre-soak 或 soak。

### 2026-07-30 19:24 真实商品分类词池接通

- 用户指出关键词页顶部显示旧候选数 `126`，下方却只有 `13` 条标题片段，并且含有
  “有了这个资料”这类噪声，同时商品 30 的标题拆词没有进入用户可见的分类池。
- 根因已确认：
  - `126` 是历史 `keyword_portfolio.json` 的兼容/审计候选数量；
  - `13` 是另一套旧标题片段建议接口的唯一候选数量；
  - 商品真实拆词已经保存在 `product_keyword_terms`，但旧页面没有读取。
- 用户可见关键词页已改为直接读取真实商品拆词，并按人群词、功效词、场景词、
  品类词、形式词、阶段词分类展示；旧 126 候选和旧标题片段不再作为当前词池展示。
- 商品 30 当前归档 13 个分类词：
  - 人群词：I人、普通人；
  - 功效词：社交技巧、社会化、成长、社交；
  - 场景词：社交；
  - 品类词：人情世故、社交；
  - 形式词：保姆级攻略、成长指南、攻略、指南；
  - 阶段词：空。
- 用户点名的成长指南、社会化、普通人、I人、社交技巧、人情世故、攻略、
  保姆级攻略已标为人工确认；数据库修改前已生成两份时间戳备份，
  `PRAGMA quick_check=ok`。
- 浏览器验收：
  - 关键词总数 `13`，分类计数一致；
  - 页面不存在 `126` 和“有了这个资料”；
  - “已归档商品”显示商品 30；
  - 点击可进入 `/products/30/analysis`，标题与关键词可见。
- 回归测试：`148 passed`。
- 8793 已由本项目旧 PID 40876 串行重载为 PID 51772，根页面和
  `/api/keyword-pool` 正常；8765 仍为其他 Agent 的 PID 21820，未触碰。
- 本轮没有触发新的真实搜索或采集，也未启动 scheduler、monitor-loop、
  pre-soak、soak 或 Windows 计划任务。

### 2026-07-30 21:22 监控统计两级下钻与精准并行任务

- 监控页五个静态数字已改为“完整清单 → 单条详情”两级查看：
  待搜索任务 64、已发现商品 24、观察记录 31、笔记/账号证据 6、候选商品 7。
- 浏览器逐项验收：每个数字返回的清单条数与顶部一致，均无截断；点击第一条后能看到
  业务详情。商品、观察、证据和候选详情可以继续进入 `/products/{id}/analysis`。
- 商品 30 在明细中显示价格 `¥19.8`、销量 `1.9万+`、四条灰色指标、粉丝数 5284、
  观察次数 2；账号证据显示店铺名 `成长论NuYoah.`，不再使用不可靠 OCR 名称。
- 新增明细接口为 GET-only、SQLite `mode=ro + query_only`，不写数据库、不触发搜索或监控。
- 定向回归 `52 passed`，嵌入脚本 `node --check` 通过；共享完整测试超过 60 秒后被工具
  超时中止，未发现本功能失败，但不把该次运行记录为完整通过。
- 8793 已加载为 PID 50088；8765 仍为 PID 21820，未触碰。收尾仍为 paused、
  scheduler=false、running=0、run_leases=0、`PRAGMA quick_check=ok`。
- 用户同意使用一个不干扰主线的新任务分担进度。已创建 `DATA-24H-02`：
  仅允许处理 `ingest.py` 与 `test_ingest_sales_delta.py` 的北京时间每日 0 点销量周期，
  禁止读取完整工程历史、重复已完成工作、触碰生产 data/数据库/服务/设备/调度/soak。

### 2026-07-30 22:02 人工持续关注名单与 24 小时销量复查口径

- 用户确认放弃“选品台全部商品每天全量复查”。现行口径：
  - 商品进入选品台后默认不做每日销量监控；
  - 用户点击“持续关注”才进入后续每日复查名单；
  - 再次点击取消关注，只影响后续新批次，不删除商品和历史销量记录。
- 8793 候选商品操作栏已增加“持续关注/已关注”按钮，状态持久化到
  `product_sales_follows`。商品 30 已在真实工作台点击为“已关注”，刷新页面后仍保留。
- 当前人工关注名单只有 1 件：
  - product 30；
  - `普通人社会化成长指南-i人社交技巧-人情世故保姆级攻略`；
  - `https://xhslink.com/m/7X9KDzX3Dxc`。
- `DATA-24H-03` 离线模块已按最终口径完成：
  - 只冻结调用方传入的人工关注商品；
  - 接受上游已验明身份的 `https://xhslink.com/m/...` 分享链接；
  - 日常复查禁止关键词搜索回退；
  - 同日快照不可变，取消关注从次日新批次生效；
  - 普通明确单品失败可记录后继续；进程中断可续跑；
  - 验证码、风控、ANR、未知页、商品身份不明/不匹配、数据库锁整批硬停。
- 总控已将关注名单输出字段对齐为 `product_id + verified_direct_url`。
- 定向合并回归：`91 passed`；生产数据库 `PRAGMA quick_check=ok`。
- 当前 8793=PID 31304；8765 仍为其他 Agent 的 PID 21820，未触碰。
- 真实状态仍为 `desired_state=paused`、scheduler 未运行；未启动真实零点复查、
  monitor-loop、pre-soak、soak 或 Windows 计划任务。
- 尚未完成：把关注名单接入真实零点执行器和工作台 24 小时新增销量刷新。
  该动作继续由总控独占真实 DB、8793、ADB 和小红书 UI；实际定时启动前仍需用户明确确认。

### 2026-07-30 23:20 完整 24 小时版本工程完成，真实运行仍保持暂停

- 用户取消逐级扩大样本后，总控按完整 24 小时标准完成了工程集成，但没有继承为
  G5 或 Windows 计划任务的自动启动授权。
- 新增持续发现规划：
  - 运行词只允许 `虚拟资料` 和来源为 `approved_discovery_keyword` 的人工批准词；
  - 不读取旧 78 seeds 或旧 126 portfolio 作为运行队列；
  - 每轮精确绑定 `task_id + expected_keyword`，不会误取现有 64 个旧 pending；
  - 按有效搜索证据在前 3 个可见商品卡之间轮转，并记录实际结果位次。
- 新增人工关注商品的真实零点复查链：
  - 北京时间 00:00–00:15 冻结关注名单；
  - 直接通过保存的 `xhslink.com`/官方商品链接进入详情，不做关键词搜索回退；
  - 精确销量写入本日累计并计算与前一日零点的新增；模糊销量只更新销量展示；
  - 普通单品失败隔离后继续，租约过期可恢复；
  - 验证码、风控、ANR、未知页、商品身份不明/不一致、DB lock 整批硬停。
- 工作台用户侧：
  - 监控统计中的“笔记/账号证据”已替换为“持续关注”；
  - 点击可见完整关注清单、商品销量、24 小时新增和单品详情；
  - 商品 30 当前显示销量 `1.9万+`、24 小时新增“待下一次零点计算”；
  - 用户可见的“采集笔记/账号证据”开关已删除，发送的单轮参数固定
    `note_evidence=false`。
- 当前完整回归：`678 passed, 3 skipped in 60.32s`；健康脚本定向
  `7 passed`。
- 8793 已按项目所有权串行重载，当前 PID `42564`，命令行显式携带
  `--project-root`；`/api/status`、`/api/monitor/status`、候选 CSV 均为 200。
  健康脚本同时修复了标准 `--project-root "path"` 命令行的误报。
- 8765 仍为其他 Agent 的 PID `21820`，从未触碰。
- 当前生产只读核验：
  - 96 个任务、64 pending、0 running、0 run lease；
  - 25 个商品、32 条观察、1 个持续关注商品；
  - task 100=`虚拟资料 / needs_manual_detail`，owner/lease 均为空；
  - 商品 32 的部分真实证据保留，不删除、不伪装完成；
  - `PRAGMA quick_check=ok`；
  - `desired_state=paused`、`scheduler_running=false`、`next_run_at=null`；
  - risk/block/skip 均为空；
  - ADB `127.0.0.1:5555` 在线，Rvc64 前台为
    `GoodsDetailActivityV2`，本次开机以来无 ANR；
  - 未发现 heartbeat、monitor-loop、pre-soak、soak 或活动并行任务。
- G0 已按新代码重新封板：
  - baseline `pre-soak-baseline-6d9f5e3b102a26a9`；
  - manifest hash
    `796388dc8d7ef42a9f39d4e3a29e3c1ac8090bd69d53bff2fef41afe48e6d1f1`；
  - 53 个显式代码/配置文件复核通过；
  - `evidence/g0-readiness.json` 中 G0=`passed`；
  - pre-soak、24h soak、scheduler 三类授权仍全部为 false。
- 尚未通过：G1/G2/G4=`failed`，G3=`insufficient_evidence`。缺真实 scheduler
  到期点、租约/崩溃与风险恢复演练、真实 pre-soak 和开始/中点/结束快照。
- 当前停止点：不启动 scheduler、真实采集、monitor-loop、pre-soak、24 小时
  soak 或 Windows 计划任务。下一步从统一项目板第 25 节和 AUTO-24H-02 继续。

### 2026-07-30 23:31 候选商品人工复核界面已移除

- 用户确认选品台用于大批量筛选；看中商品后直接通过商品链接进入小红书，不需要再录入作者粉丝和笔记互动做人工复核。
- 已从用户界面删除：
  - 候选商品行“复核”按钮；
  - “低粉账号人工复核”弹窗；
  - 作者粉丝、笔记点赞/收藏/评论、发布距今天数的录入表单；
  - 对 `/api/verify-low-follower/` 的前端调用和弹窗事件。
- 仍保留：商品标题直达链接、“打开”、单品分析、粉丝数、0–2000 自动“低粉爆款”标记、持续关注/已关注。
- 定向回归 `58 passed in 1.40s`。
- 8793 已按项目所有权串行重载，当前 PID `55616`；健康检查三接口均为 200。8765 仍为其他 Agent 的 PID `21820`，未触碰。
- 浏览器真实页面确认：商品 30 操作栏只显示“分析 / 打开 / 已关注”，页面无人工复核入口；商品链接、价格、销量、灰色指标和粉丝数正常。
- 本轮没有触发搜索、采集、scheduler、monitor-loop、pre-soak、24 小时 soak 或 Windows 计划任务。
- 23:18 的 G0 baseline 因 `workbench_ui.py` 已变化而降为历史基线；AUTO-24H-02 继续前必须对当前代码重新封板。

### 2026-07-30 23:52 UI-11 后 G0 已重新封板并通过

- 完整回归：`678 passed, 3 skipped in 50.29s`。
- G0 专项复验：`29 passed in 2.49s`，覆盖 SQLite 并发、scheduler 恢复/关闭、scheduler 租约、monitor lease-lost 和 run-control。
- 新 baseline：
  - `pre-soak-baseline-b54a28d3da63c946`；
  - manifest hash `40ba1c9559f3b68b6e70aa2218f06013e6f186d2dce6371ef13b1191c43989a8`；
  - 53 个显式代码/config 文件回读重验通过；
  - 文件 SHA-256 `ecaf1f05e22c86eeca34a4c39f67a3957c85cfc0d77aaf1c3a89ef691797f95a`。
- `evidence/g0-readiness.json`：
  - G0=`passed`；
  - G1/G2/G4=`failed`，G3=`insufficient_evidence`；
  - `ready_for_pre_soak=false`、`ready_for_24h_soak=false`；
  - pre-soak、24h soak、scheduler 启动授权全部为 false；
  - 文件 SHA-256 `5fe0b2df59a125d9def4eb1bbdf330a15e084128e12c9c2ec030dcd2108a17a9`。
- `pre-soak-evidence-bundle.json` 已同步到 bundle
  `pre-soak-evidence-972c1e8c4f3100b3`，仍为 `incomplete`；ACK、scheduler 真实到期点和补证审批保持 missing，不授权执行或 soak。
- 当前生产状态仍为 paused、scheduler 未运行、running task=0、run lease=0、DB `quick_check=ok`；8793 PID `55616`，8765 PID `21820` 未触碰。
- 下一阶段 M6/G2 需要跨约 3–4 小时运行至少 3 个真实小时到期点，保持 1 词×1 商品。启动前须明确告知用户时长、次数、真实小红书搜索/商品查看、本地 DB/证据写入和硬停止条件并取得确认；这不构成 G5 24 小时 soak 授权。

### 2026-07-31 00:01 G2 首个零点到期点因旧商品短链接未正确导航硬停止

- 用户已确认按原门槛执行 M6/G2；该授权只覆盖 1 词×1 商品、每小时一次、至少 3 个真实到期点，不覆盖 G5 24 小时 soak 或 Windows 计划任务。
- 启动前预检通过：8793 所有权正确、8765 未触碰、DB `quick_check=ok`、无 running task/run lease、ADB 在线、小红书无 ANR、无残留 monitor-loop/pre-soak/soak。
- scheduler 于 `2026-07-31T00:00:28+08:00` 启动，零点销量复查先冻结唯一关注商品 30；约 00:01 自动硬停止：
  - `desired_state=paused`、`scheduler_running=false`、`next_run_at=null`；
  - `risk_stop_reason=last_block_reason=daily sales tracking stopped: unknown_page`；
  - 零点批次 `hard_stopped`，只领取商品 30，没有进入后续发现轮次，没有误写销量。
- 真实原因修正：商品 30 的短链接会先 302 到正确的官方商品长链接，但长链接网页端最终返回 404；ADB 直接打开短链时没有切换到详情。设备页面仍停在 `职场生存手册` 搜索结果，因而无法验证商品身份。
- 证据固定在 `data/probes/daily-sales-30-e4e03960e9`，run event id `444`，run id `daily-sales-30-e4e03960e9`。
- 原跨小时 heartbeat 已暂停；不得自动恢复 scheduler。
- 接手后的唯一 P0：实现“分享短链接首次采集时即时解析并保存经过官方域名校验的耐久长链接”；失效或非官方跳转必须失败关闭，不得用关键词搜索替代直达。随后受控重新取得商品 30 链接、验证一次真实直达，再重新开始 G2。
- G5、pre-soak 和 Windows 计划任务仍未授权、未启动。

### 2026-07-31 00:40 商品稳定直达已补齐，真实验证因小红书 ANR 再次硬停止

- 已把用户点击链接与系统监控地址分开：
  - `products.share_url` 保留公开分享链接；
  - 新增 `products.direct_url`，只允许官方 `goods-detail` 或固定商品 deeplink；
  - 每日销量快照不再接受 `xhslink.com` 短链接，也不允许关键词搜索回退。
- 新采集链会从当前商品详情的只读 Activity Intent 或公开短链第一跳提取固定商品编号；公开页面最终 404 不会再丢失前一跳已经确认的官方商品身份。
- 商品 30 已安全补写：
  - `share_url=https://xhslink.com/m/7X9KDzX3Dxc`；
  - `direct_url=xhsdiscover://goods_detail/67fa3ecf1899f10001df7917`；
  - 生产库写入前备份 `data/xhs_scout.sqlite3.bak-linkfix-20260731-003950`；
  - 审计 event id `449`，`PRAGMA quick_check=ok`。
- 验证：定向 `75 passed`；完整 `690 passed, 3 skipped in 55.70s`。
- 00:40 受控打开上述 stable direct URL 时检测到小红书 ANR：
  - collector 返回 `hard_stop` / `reason_code=anr`；
  - 探针 `data/probes/daily-sales-30-a54461973d`，OCR 明确出现“小红书没有响应”；
  - 当时底层页面仍是错误商品“亚马逊主图模板”，没有采信、没有写销量；
  - 未点击“等待”或“关闭应用”，未继续 UI 操作；
  - 安全状态已固定为 paused、scheduler false、next null，risk/block 均为 `direct product validation stopped: anr`，审计 event id `451`。
- 接手后不得自动处理 ANR 对话框。必须等待用户手动处理或明确授权；应用恢复后先只验证商品 30 直达与标题，成功后才讨论清除风险并重新开始 G2。
- G5、pre-soak 和 Windows 计划任务仍未授权、未启动。

### 2026-07-31 11:15 ANR 已恢复，商品直达因内容未加载继续硬停止

- 用户已手动关闭并重开小红书；只读探针 `probe-2026-07-31T11-02-35+08-00` 显示首页正常，当前没有可见 ANR。
- 已修复历史 ANR 误报：不再使用 `dumpsys window lastanr` 判断当前页面，只认当前窗口/截图实际可见的无响应信号。
- 11:03 受控打开商品 30 固定 deeplink：Android 建立了商品编号正确的 `GoodsDetailActivityV2`，但 Activity 没有绘制商品内容，截图始终是首页，标题和 `1.9万+` 不可见；按 `unknown_page` 停止，没有写销量、没有重试或搜索。
- 现场证据：`data/probes/daily-sales-30-f30de9c7a7`、`data/probes/daily-sales-30-followup-current.png`。
- 离线修复已完成：
  - 固定 `direct_url` 继续作为商品身份锚点；
  - 每次复查使用现有公开 `share_url` 取得当日官方 `goods-detail` 跳转；
  - 公开跳转商品编号必须与固定编号完全一致，否则身份不明硬停止；
  - 销量探针跳过可能卡满 30 秒且非必需的 UI tree，只使用截图、Activity、风险信号、标题和销量。
- 当前分享链接公开跳转仍准确指向 `67fa3ecf1899f10001df7917`；定向 `49 passed in 1.49s`，完整 `695 passed, 3 skipped in 73.06s`。
- 生产状态：event id `454`、`PRAGMA quick_check=ok`、desired paused、scheduler false、next null，risk/block 均为 `direct product validation stopped: unknown_page`。
- 当前代码尚未重载到 8793，旧 G0 baseline 已因源码变化降为历史证据。接手后先等用户把小红书再次恢复到首页，再只做一次“公开跳转→商品 30”真实验证；成功后才能清风险、重载 8793、重封 G0 和重新安排 G2。
- G5、pre-soak 和 Windows 计划任务仍未授权、未启动。

### 2026-07-31 11:25 用户重开了错误的 BlueStacks 实例

- 当前显示的是 `Pie64 / BlueStacks App Player`，ADB 为 `emulator-5554`；该 Android 9 设备没有安装 `com.xingin.xhs`。
- 项目原设备 `127.0.0.1:5555` 当前不在线；项目原实例是 `Rvc64 / BlueStacks App Player 1`，其配置和 `D:\app\BlueStacks_nxt\Engine\Rvc64` 目录仍存在。
- 不要在 Pie64 里重新安装或登录小红书，也不要修改项目配置去适配错误实例。
- 用户应关闭当前窗口，并通过 BlueStacks 多开管理器启动 `BlueStacks App Player 1`。Rvc64 恢复后先只读确认包、ADB、前台页和 ANR，再继续商品 30 的一次真实直达验证。
- 所有调度和长期自动化继续暂停。

### 2026-07-31 11:33 Rvc64 已恢复，HTTPS 打开命令触发选择框和 ANR

- 正确 Rvc64 已恢复：`SM_S908E / Android 11`，小红书 9.39.0 和数据目录仍在，首页账号内容可见；项目 ADB 别名 `127.0.0.1:5555` 已重新连接。
- 第二次商品 30 验证时，公开官方 HTTPS 地址的商品编号核对正确，但旧 `adb shell am start` 没有引用包含 `&` 的参数，也没有使用 `-p com.xingin.xhs` 限定应用，导致系统弹出“小红书 / Chrome”打开方式，随后出现“小红书没有响应”。
- 未点击任何对话框、未写销量、未重试。截图：`data/probes/daily-sales-30-resolver-20260731-1131.png`。
- 已离线修复 URL shell 引用和小红书包限定；定向 `51 passed in 1.55s`，完整 `696 passed, 3 skipped in 69.77s`。
- 生产状态 event id `455`、DB quick_check=ok、desired paused、scheduler false、next null，risk/block 均为 `direct product validation stopped: anr`。
- 等用户手动关闭应用并恢复到首页后，先只读确认，再只验证一次修正后的商品 30 直达；成功前不得清风险、重载 8793、重封 G0 或恢复 G2。

### 2026-07-31 11:41 商品 30 真实直达验证成功

- Rvc64、`127.0.0.1:5555` 和小红书首页均已恢复；验证前无 ANR、验证码或风控。
- 修正后的公开分享跳转成功限定由小红书打开，并用固定商品编号校验身份：
  - 23 秒完成；
  - 商品 30 标题身份匹配；
  - 当前销量显示 `1.9万+`；
  - collector=`fuzzy`、observed_product_id=30；
  - 证据 `data/probes/daily-sales-30-a7998bc8f1`；
  - 验证后自动返回首页。
- 返回页为 home_feed，当前 ANR=false、risk 为空；没有写销量业务数据，没有启动 scheduler。
- 成功 event id `457`，DB quick_check=ok。
- 历史硬停止仍保留：risk=`direct product validation stopped: anr`、desired paused、scheduler false。必须由用户显式确认当前风险原因后才能解除；不得用普通恢复绕过。
- 用户确认后：清风险但先保持调度受控，重载 8793、重封当前 G0，再重新安排 G2 三个真实到期点。G5、pre-soak 和 Windows 计划任务仍未授权。

### 2026-07-31 12:23 G0 已重封，G2 从 12:30 重新累计

- 用户已明确授权继续 G2/G3/G4；这不构成 G5 24 小时 soak 或 Windows 计划任务授权。
- 历史 ANR 风险已按原原因和用户确认安全解除；8793 已按所有权规则重载为 PID
  `55344`，8765 仍为其他项目 PID `21820`，未触碰。
- 当前完整回归 `696 passed, 3 skipped in 68.38s`；最终清空已经解决的历史
  `last_block_reason` 后，审计 event id `460`，risk/block/skip 均为空。
- 当前 G0 baseline：
  - id `pre-soak-baseline-5d0d0fba9d4c5cbd`；
  - manifest hash `fca1fb7f5bae5fe863b2aaf72a86d026016b4d12221687934a28a8a020d5e8b3`；
  - 54 个代码/config 文件回读通过；
  - G0=`passed`，所有授权字段仍为 false。
- 12:03 的首次试启没有操作设备；planner 返回
  `all_allowed_keywords_cooling_down`。按任一 skip 即停的规则已经暂停，当前
  desired paused、scheduler false、next null、risk 为空、running=0、lease=0。
- 根因是 5 个已人工批准的新词 task 95–99 仍处于上一阶段 paused，而 task 100
  的不完整 `虚拟资料` 证据继续以 `needs_manual_detail` 占位。
- 已用 SQLite backup API 备份到
  `data/backups/xhs_scout.sqlite3.before-g2-approved-resume-20260731-120653`，
  只恢复 task 95–99 为 pending；没有恢复其余旧任务，也没有改动 task 100。
  审计 event id `459`，DB quick_check=ok。
- 用户指出无需等待整点；固定到期点已提前为 2026-07-31 12:30、13:30、
  14:30（北京时间），保持 1 词×1 商品。G0 重新计算仍为 passed，首点前
  scheduler 维持暂停。
- 任一验证码、风控、ANR、未知页、身份不明、DB 锁或新的 risk/block/skip
  立即暂停并保留证据。三个点完成后先暂停并判定 G2，再进入 G3。

### 2026-07-31 12:40 G2 首点采到完整商品，但返回搜索页失败后自动暂停

- G2 首点按固定时间 `2026-07-31T12:30:00+08:00` 执行；实际于 12:32:20
  启动，run id `monitor-04160f2ea993`，只运行 task 95 / `模板` / 1 个商品。
- 商品 33《职场新人全周期成长指南（pdf版）》的核心业务信息已真实采集：
  价格 29.8、累计销量 1364、五条灰色指标、分享链接、固定直达、账号
  “阿K在成长”和粉丝 870；商品主体采集没有失败。
- 12:37:17 采集后返回动作只到 `search_input`，没有回到搜索结果页，阻塞原因为
  `post-capture back did not reach search results: search_input`。系统已自动
  `paused`，没有自动恢复，也没有触发第二个商品。
- 当前：scheduler=false、next_run_at=null、risk/skip 为空、block 保留、
  running=0、run lease=0、DB quick_check=ok；8793 健康入口均为 200。
  ADB `127.0.0.1:5555` 在线，前台是小红书搜索 Activity，当前无新 ANR。
- 首点正式证据已写入：
  `evidence/scheduler-evidence.jsonl`（result=blocked）以及
  `evidence/g2-20260731-1230-{db,http,round}.json`。
- 不得在 13:30 或 14:30 自动恢复。先修复并受控验证“商品采集完成后回到搜索结果”
  的逻辑，再从新的三个固定点重新累计 G2。G3 真实演练、G4、G5 和 Windows
  计划任务均不得越级启动。

### 2026-07-31 13:14 G3 离线恢复验证已由总控复验

- 独立离线任务交付的 `tests/test_g3_offline_recovery.py` 和
  `evidence/g3-offline-recovery-validation.json` 已由总控逐项检查。
- 总控使用临时数据库重跑 scheduler、shutdown、租约、run-control、monitor-control
  和新增 G3 测试，结果 `31 passed in 2.67s`；当前完整套件同时为
  `702 passed, 3 skipped in 77.11s`。
- 已证明：异常退避初始 2 秒、上限 3 秒；连续第三次异常后自动 paused；
  普通恢复不会清除 risk；过期 owner 无法续租且不会双 owner；stop 后不多跑一轮。
- 这是 M7-01 离线证据，不代表 G3 真实进程/租约恢复演练已经完成，也不授权启动
  scheduler、G4、G5、soak 或 Windows 计划任务。M7-02 仍必须等 G2 通过后串行执行。

### 2026-07-31 13:22 返回页修复离线通过，真实复验因 ADB 点击触发 ANR

- “多退一步”根因已经修复：返回后若页面为 `search_results` 且顶部查询词仍与任务
  关键词一致，即使 Android 临时上报 ResolverActivity，也立即认定已经回到正确
  列表，不再多按一次返回；关键词不匹配和可疑店铺列表仍失败关闭。
- 真实复验又暴露截图 OCR 偶尔只识别底部导航的问题；新增 UI-tree fallback，
  仅当 OCR=unknown 且顶部存在可点击 EditText 搜索框时补判 search_input。
- 定向最终 `9 passed`；完整回归 `702 passed, 3 skipped in 77.11s`；8793 当前
  PID `3624` 已加载修复。
- 13:19 唯一受控复验已识别搜索输入页，但点击历史关键词 `模板` 的 ADB 命令
  `input tap 64 202` 超时 30 秒，HTTP 返回 500；随后当前窗口明确出现
  `Application Not Responding: com.xingin.xhs`。
- 已立即 pause，没有继续点击、关闭/等待 ANR 或重试。当前 running=0、lease=0、
  scheduler=false、next=null、DB quick_check=ok；task 95 保留为
  `needs_manual_detail`（attempts=3），没有新增错误商品数据。
- 安全状态已明确写入：
  `risk_stop_reason=last_block_reason=controlled post-capture validation stopped:
  anr during ADB input tap`；备份
  `data/backups/xhs_scout.sqlite3.before-anr-safety-marker-20260731-1321`。
- 接手后不得自动处理 ANR 或普通 resume。必须等待用户手动关闭并重开小红书；
  用户确认“好了”后，先只读核验，再按精确原因解除风险并继续唯一一次真实复验。

### 2026-07-31 13:40 用户授权小红书 ANR 的有限应用级自恢复

- 用户明确允许总控在小红书出现“没有响应”时关闭应用并重新打开。本次已实际关闭
  ANR 应用并重开到正常首页；无登录、验证码或风控，未继续采集。
- 新规则不是无限重试：当前商品先中止；只允许自动关闭并重开
  `com.xingin.xhs` 1 次；验证首页/搜索页安全后，发现采集等待下一轮从安全起点
  继续，零点销量则用固定商品链接重试当前商品。再次 ANR、未知页、登录、验证码、
  风控或重开失败继续暂停；不自动重启 BlueStacks。
- 实现文件：
  - `src/xhs_scout/emulator.py`
  - `src/xhs_scout/monitor.py`
  - `src/xhs_scout/daily_sales_collector.py`
  - `tests/test_app_recovery.py`
  - `tests/test_daily_sales_collector.py`
- 定向：发现/调度恢复 `26 passed`，零点销量恢复 `40 passed`；最终完整正式测试
  `712 passed, 3 skipped in 67.34s`。裸 `pytest -q` 曾误扫三个历史受限临时目录，
  属收集范围问题；未删除历史证据，`pytest tests -q` 全绿。
- 真实自动恢复第一次发现 BlueStacks launcher 返回 `114`，但小红书实际已打开；
  已改为只认随后 Android 页面探针。第二次真实验证通过：
  `page_kind=home_feed`、Activity=`com.xingin.xhs.index.v2.IndexActivityV2`、
  ANR=false、risk=null；证据
  `data/probes/app-recovery-live-validation-20260731-1346`。
- 当前运行服务已加载为 PID `35856`，8793 健康 200；8765 PID `21820` 未触碰。
  DB quick_check=ok、running=0、lease=0。
- 已先备份
  `data/backups/xhs_scout.sqlite3.before-anr-auto-recovery-clear-20260731-1352`，
  再只清除已解决的精确 ANR risk/block，并记录
  `resolved_anr_marker_cleared`。调度继续 paused、next=null，没有恢复 G2。
  下一步重排 G2 三个新固定点。G5、24 小时 soak 和 Windows 计划任务仍未启动。

### 2026-07-31 13:56 G2 新固定点已排定，等待 14:30 首点

- 只读复核：8793 PID `35856` 健康；8765 PID `21820` 未触碰；DB
  quick_check=ok、running=0、lease=0；desired paused、scheduler false、
  next null、risk/block/skip 均为空；ADB 在线，小红书正常首页，无残留真实循环或
  并行任务。
- task 95 `模板` 的旧失败预算不重置；新三点从 pending task 96 `话术` 开始，
  其后可使用 task 97–99。task 100 `虚拟资料` 旧不完整状态继续隔离。
- `evidence/scheduler-expected.json` 新清单为 14:30、15:30、16:30（北京时间）；
  旧 12:30 blocked 证据只留审计，不计入新 G2。
- heartbeat `g2` 已更新为 ACTIVE，每小时半点唤醒。14:30 安全时只 resume 8793
  一次；每点 15 分钟内记录正式证据。代码允许一次应用级 ANR/ADB 超时恢复，
  heartbeat 不额外手工重试；恢复失败或任何 risk/block/skip 立即 pause。
- 当前尚未启动真实采集；G4/G5、24 小时 soak 和 Windows 计划任务仍未启动。

### 2026-07-31 16:16 用户纠正 ANR 恢复规则；G2 保持暂停

- 先纠正一个关键误解：“自动重开额度”不是小红书、BlueStacks 或 Codex 的限制，
  而是项目在 13:40 加入的内部计数规则。它把
  `app_recovery_consecutive_count=1` 解释成“上次完整商品采集成功前只允许自动
  关闭并重开一次”，第二次 ANR 就拒绝恢复。用户明确认为该设计错误，要求废止。
- 用户最新、现行口径：
  - 每次明确出现“小红书没有响应”，总控都应直接关闭小红书应用并重新打开；
  - 确认恢复到正常首页或搜索页后，从安全起点重新搜索；
  - 不能因为此前已经自动重开过一次，就停下来要求用户处理；
  - 登录、验证码、风控、未知商品身份或数据库锁仍停止，不允许借重开绕过。
- 当前没有再启动任务。Windows 窗口只读观察显示小红书已经处于正常首页，ANR
  对话框不存在，所以没有重复点击“关闭应用”，也没有 resume G2。
- 最新失败轮 `monitor-be821cc9e2c1`：
  - 14:30:22 启动，首页截图于 14:30:24 完成；
  - 同一探针的 `window.xml`/`probe.json` 到 16:10:37 才生成，约 1 小时 40 分钟
    卡在 `RapidOCR` 识别，不是等待定时点，也没有持续消耗 Codex token；
  - 随后搜索入口短暂空白，第二次复探于 16:11 识别到 ANR；
  - 因旧计数仍为 1，系统报
    `Xiaohongshu ANR detected; automatic app recovery already used since the last successful product capture`
    并暂停；本轮没有采到商品。
- 当前状态：8793 PID `53764`；8765 PID `21820` 未触碰；desired=paused、
  scheduler=false、next=null；heartbeat `g2` 已 PAUSED；risk/block 保留上述
  精确旧原因；DB quick_check=ok、running task=0、lease=0；ADB
  `127.0.0.1:5555` 在线。旧 14:29/15:29/16:29 清单已经失效，不得作为 G2 证据。
- 本轮代码已有四项修复：搜索入口短暂空白复探、首页历史查询词入口识别、
  `IndexActivityV2` 首页误分类纠正、误入店铺商品列表时直接采集粉丝并返回；
  完整回归为 `717 passed, 3 skipped`。这些不解决 OCR 超长卡死和旧恢复计数。
- 新对话接手后先做两个 P0，不要直接启动 G2：
  1. 把 RapidOCR 放入可终止的独立进程，增加单次识别硬超时；超时必须终止 OCR
     工作进程并返回明确错误，禁止再出现数十分钟挂死。
  2. 删除/重构 monitor 与 daily-sales 的粘性一次恢复预算。每次当前 ANR 都执行
     关闭应用、重新打开、验证正常页面、从安全起点重新搜索；不得再以旧计数拒绝。
- 两项修复经离线测试和一次受控真实恢复验证后，才能备份 DB、按精确原因清除旧
  risk/block，并重新设置三个全新的 G2 固定点。不得沿用旧清单，不得触碰 8765，
  不得启动 G4/G5、24 小时 soak 或 Windows 计划任务。

### 2026-07-31 16:28 新总控只读基线：当前 ANR 对话框仍在焦点

- 新总控按最小交接入口完成只读核验，没有启动采集、scheduler、monitor-loop，
  没有写生产数据库，也没有触碰 8765。
- 8793 仍为本项目 PID `53764`，三个健康入口均为 200；8765 仍为其他项目 PID
  `21820`。
- API 仍为 desired paused、scheduler false、next null；旧 risk/block 精确保留，
  skip 为空；G2 heartbeat `g2` 已确认 PAUSED。
- 数据库 `PRAGMA quick_check=ok`；pending=68、running=0、run lease=0；
  products=27、observations=34、followed_products=1、candidates=15。
- ADB `127.0.0.1:5555` 在线。底层 resumed Activity 是
  `IndexActivityV2`，但 Windows 当前焦点明确为
  `Application Not Responding: com.xingin.xhs`。因此此前“已经恢复正常首页”
  只描述了底层页面，不是当前可操作前台状态。
- 当前 ANR 现场先保持不动。执行顺序不变：RapidOCR 独立进程 60 秒硬超时 →
  删除跨轮次一次性重开限制 → 定向与完整回归 → 只重载 8793 → 唯一一次受控
  关闭/重开/首页验证 → 向用户汇报。用户同意前不清旧 risk/block、不重排 G2。

### 2026-07-31 16:35 两项 P0 离线完成，完整回归通过

- RapidOCR 现由 `spawn` 独立工作进程承载，默认单次硬超时 60 秒；超时后父进程
  先 terminate、必要时 kill，并返回明确 `OcrTimeoutError`。
- 页面探针在 OCR 前先保存 `window.txt` 和截图；超时时写出
  `page_kind=ocr_timeout` 的 `probe.json` 与运行事件，不再因 OCR 卡死而缺失证据。
- 发现监控已删除 `app_recovery_consecutive_count` 的读取、递增、重置和
  `app_recovery_budget_exhausted` 分支；旧状态键只作为历史记录存在，不再参与
  任何恢复决策。
- 零点销量采集已删除 `_app_recovery_used` 拒绝逻辑；测试证明同一商品连续两次
  当前 ANR 会分别执行两次关闭/重开，再从固定链接重试。
- 登录、验证码、风险页、未知页、商品身份不明和数据库锁停止边界未放宽；OCR
  timeout 在零点销量流程中明确返回 `reason_code=ocr_timeout`。
- 测试：P0 直接定向 `37 passed`；相邻回归 `120 passed`；完整正式回归
  `719 passed, 3 skipped in 49.49s`。
- 生产服务尚未重载，当前 ANR 对话框仍保持现场；旧 risk/block、scheduler 和 G2
  均未改动。下一步只重载 8793，再做唯一一次受控关闭—重开—首页验证。

### 2026-07-31 16:42 两项 P0 已加载，受控关闭—重开—首页验证通过

- 8793 先后两次仅按项目所有权脚本重载；最终项目自有 PID `59724`，三个健康
  入口均为 200。8765 仍为其他项目 PID `21820`，未触碰。
- 首次受控关闭/重开已经把小红书恢复到首页，但首次探针发现窗口转储同时保留旧
  ANR Window 和新首页焦点；旧解析取第一条，误报 Activity=`Application`、
  has_anr=true。该误报没有清风险、没有启动任务。
- 已修复为只认最后一个 `mCurrentFocus`，新增严格测试后完整回归为
  `720 passed, 3 skipped in 50.49s`。
- 最终复验 run `probe-2026-07-31T16-41-29+08-00`：
  - evidence `data/probes/probe-2026-07-31T16-41-29+08-00`；
  - Activity=`com.xingin.xhs/com.xingin.xhs.index.v2.IndexActivityV2`；
  - page_kind=home_feed、has_anr=false、risk_stop_reason=null；
  - 真实独立进程 RapidOCR 正常返回 99 条结果；
  - DB quick_check=ok、running=0、lease=0。
- 旧 risk/block 仍精确保留
  `Xiaohongshu ANR detected; automatic app recovery already used since the last successful product capture`；
  历史 `app_recovery_consecutive_count=1` 也未擅自改写，但新代码完全不再使用它。
- 当前 desired paused、scheduler false、next null、G2 heartbeat PAUSED。停在用户
  确认点：只有用户看到上述结果并同意继续后，才备份数据库、精确清除旧 risk/block
  及历史计数展示值，并设置三个全新的 G2 到期点。

### 2026-07-31 16:53 用户授权后立即启动新 G2，第一点完成 ANR 自恢复

- 用户要求不等整点；备份、精确清险后立即开始 G2。
- 备份：
  `data/backups/xhs_scout.sqlite3.before-g2-risk-clear-20260731-164812`，
  SHA-256 `0732f105e774df4900e17986becddf1d0bf563f3268d22a1ac6d0f4e98f34265`，
  quick_check=ok。
- 在 paused、running=0、lease=0 和原因精确匹配门禁下，仅清除旧 risk/block
  与历史 counter 展示值；审计事件 `obsolete_recovery_budget_cleared`。没有删除
  商品、任务、观察、销量或历史事件。
- 新 G2 显式三点为 16:48:39、17:48:39、18:48:39（北京时间）；heartbeat `g2`
  已迁移到当前任务并 ACTIVE。
- 第一轮 `monitor-bf9f8841ac88` 于 16:49:34 启动 task 97 `预算表`。16:50:12
  检出当前 ANR，新规则成功关闭/重开，16:50:29 验证回到正常首页。
- 本轮 captured=0，正式结论为 failed/recovered，不冒充成功采集；当前
  risk/block/skip 均为空、running=0、lease=0、DB quick_check=ok，scheduler
  继续 running，next=17:50:29。
- 正式证据为 `evidence/g2-20260731-164839-{db,http,round}.json` 和账本 record
  `g2-20260731-164839-failed-recovered`。账本 hash 链完整；账本 keyword 因本次
  PowerShell 管道编码显示 `???`，但 DB/round 文件正确记录 task 97/`预算表`。
  后续证据禁止通过 PowerShell 管道传原始中文。

### 2026-08-02 20:22 用户重新授权 G2；首轮商品成功、误点导致卖家阶段硬停止

- 启动前 8793/数据库/ADB/首页只读核验全部通过；用户授权后首轮
  `monitor-1f7bb58e415e` 成功写入 product 35、observation 35，task 98 `合同`，
  累计销量 6730。搜索入口、搜索结果和商品详情均正常，无 ANR。
- 指标条自动定位错误地把普通“已售6730”弱候选当成可横滑条；连续 focus tap
  把页面从详情带回首页，随后卖家采集硬停止
  `seller capture requires product_detail, got home_feed`。该轮不计 G2 通过。
- scheduler 与 heartbeat 均已暂停；DB quick_check=ok、running=0、lease=0。
- 已增加弱候选保护：视觉分和布局分均弱、无指标标记且仅一个累计销量字段时，
  只读取，不 tap、不 swipe。复现/相邻 `22 passed`，完整 `tests` 回归
  `721 passed, 3 skipped in 69.45s`。
- 8793 已仅按所有权脚本重载为 PID 9388，健康入口全 200；8765 PID 21820 未触碰。
  当前仍 paused，并保留本次新 risk；旧 20:13/21:13/22:13 清单已经因首轮失败失效。

### 2026-08-02 20:29 修复后再次启动，搜索入口 ANR 复现并安全收口

- 精确确认新 risk 后于 20:24:29 启动 `monitor-a0acebd3d611`；首页健康，但点击
  搜索入口后再次空白，20:25:11 检出小红书 ANR，captured=0。
- 应用级恢复于 20:25:34 成功回到正常首页；总控随后显式暂停 scheduler。
- 最终 desired paused、scheduler false、next null、risk/block/skip null、running=0、
  lease=0、DB quick_check=ok；heartbeat PAUSED，G2 expected 清空。
- 该失败位于搜索页启动阶段，和已修复的详情弱 ROI 误点无关。不得继续重复同一路径；
  下一步应针对小红书首页切换 `GlobalSearchActivity` 的重复主线程 ANR 做环境/入口
  级诊断，再由用户确认新一轮 G2。

### 2026-08-02 首页两种搜索入口已显式区分

- 用户确认首页只有独立放大镜和带历史词/推荐词的长条搜索框两种合法形态。
- UI 识别现分别返回 `home-search-button`、`home-search-bar`；monitor 事件分别记录
  `tap_home_search_button`、`tap_home_search_bar`，不再使用模糊统一名称。
- `codex 重置` 等长条搜索框已纳入明确测试。定向 `34 passed`，完整回归
  `722 passed, 3 skipped in 67.43s`。
- 8793 已加载为 PID 67200，8765 PID 21820 未触碰；scheduler/G2 保持暂停，
  本次没有真实搜索或生产采集。

### 2026-08-02 22:02 用户授权后 G2 重启，第一点真实通过

- 启动预检从他人主页逐步系统返回；第三次返回触发当前 ANR，因此未直接启动。
  按现行规则立即关闭/重开应用，新 PID 2333，连续复核为正常首页且 ANR Window
  消失后才放行。
- G2 新清单只认 21:01、22:01、23:01（北京时间），heartbeat `g2` ACTIVE；
  21:01:51 只 resume 8793 一次，没有启动 CLI monitor-loop。
- 第一轮 `monitor-3baaed5970d1` 使用 task 96 `话术`：真实点击长条入口
  `tap_home_search_bar`，正常打开 `GlobalSearchActivity`；点击第 1 张商品卡并进入
  `GoodsDetailActivityV2`，没有黑白屏或 ANR。
- 真实写入 product 36、observation 36、note observation 8；累计销量 433，卖家
  粉丝 1010，分享链接与 durable direct URL 均已保存。指标 ROI 无法可靠定位时
  安全跳过，没有 tap/swipe；卖家店铺列表读取后成功返回详情和搜索结果页。
- 21:06:17 正式完成：captured_products=1、blocked=null、skipped=[]；DB
  quick_check=ok、running=0、lease=0、risk/block/skip=null。scheduler 继续 running，
  next=22:06:17。
- 正式证据：`g2-20260802-210100-{db,http,round}.json`；账本 record
  `g2-20260802-210100-completed`、hash
  `b6efa768ce1b96892a2b781eb8856e0797e0f90ea70312a0b7b7a12b1036a41b`。
  账本 keyword 再次受 PowerShell 管道编码影响显示 `??`，但 DB/round 正确记录
  `话术`；后续写账本必须传 ASCII Unicode 转义。
- 22:02 heartbeat 第二点预检安全；第二轮等待 scheduler 于 22:06:17 自然到期，
  不重复 resume。8765 PID 21820 全程未触碰。

### 2026-08-02 22:12 G2 第二点因小红书 OOM 崩溃，已停止并查明原因

- 桌面任务挂起/唤醒后 scheduler 的进程内等待未随墙钟推进；22:07:24 next 已过期
  但仍无新 run。总控在 running=0、lease=0 下先 pause、确认旧线程退出，再于
  22:07:58 resume，未并发启动或调用 run-once。
- 第二轮 `monitor-08649ddcbc84`、task 97 `预算表`；正常从搜索结果返回输入页、
  重新搜索，并点击第 1 张商品卡 `(898,527)`。前后截图证明坐标在商品卡内，Android
  Activity 日志证明 `GoodsDetailActivityV2` 已经启动。
- 失败真实原因不是搜索按钮、商品卡误点或 ANR，而是小红书进程自身 OOM 崩溃：
  FrescoDecodeExecutor 出现致命异常，日志含 `Large object allocation failed`、
  `OutOfMemoryError: pthread_create failed`、`Could not allocate JNI Env`；旧 PID
  2333 于 22:09:20.701 被 SIGSEGV(status 11)终止，RSS 约 799MB；系统随后以
  PID 23611 重启到首页。
- monitor 于 22:09:35 看到 home_feed 并安全停止：captured=0、block=`app left
  search flow while opening product: home_feed`、skip=`opened page is home_feed`；
  task 97=`needs_manual_detail`，没有商品写入。
- scheduler/heartbeat 均 PAUSED，23:01 第三点取消；`scheduler-expected.json` 的
  G2 已清空，本批不形成 G2 通过。最终 quick_check=ok、running=0、lease=0；当前
  小红书 PID 23611、正常首页、无 ANR。
- 第二点正式证据 `g2-20260802-220100-{db,http,round}.json`；ledger record
  `g2-20260802-220100-blocked`、hash
  `4ce4a8ff5d78f47e44b1bfdf62a27c313087de66586979bf3f9542fde99cfa30`。
- 下一步不是继续 G2，而是补齐应用进程崩溃检测/恢复，并确定轮次前内存清理策略；
  登录、验证码、风控、未知页、身份不明和 DB 锁硬停止边界不变。

### 2026-08-02 22:36 OOM 崩溃恢复修复已加载并完成受控验收

- 已在 `AdbDevice` 增加小红书进程 PID 读取；monitor 点击商品前后比较 PID。若详情
  探测不是商品页且 PID 已变化，明确记录应用进程崩溃，不再误记成普通 home_feed。
- 第一次进程崩溃会关闭并重开小红书、验证安全页、对当前关键词重新搜索并重新点击
  同一结果位一次；若第二次仍崩溃或重搜失败则暂停，不会无限重试。登录、验证码、
  风控、未知危险页、身份不明和 DB 锁硬停止边界未放宽。
- 8793 内置 scheduler 的默认每轮配置已增加任务开始前应用关闭/重开，避免跨小时
  累积的 Fresco 图片内存继续带入下一轮；无任务和 dry-run 不触发真实应用重启。
- 新增模拟 PID 100→200 崩溃、重启、重搜当前关键词、PID 300 保持稳定的测试；
  定向 `20 passed`，完整 `tests` 回归 `726 passed, 3 skipped in 78.19s`。两次首次
  测试收集失败均来自无权访问的历史/系统 pytest 临时目录，不是代码红灯；限定
  `tests` 并使用独立 basetemp 后全绿。
- 8793 已由本项目旧 PID `67200` 串行重载为 PID `61072`，HTTP 200；8765 仍为
  其他项目 PID `21820`，未触碰。
- 受控真实恢复只执行一次：小红书 PID `23611` force-stop 后用 BlueStacks 官方
  launchApp 重开为 PID `26823`；探针
  `data/probes/probe-2026-08-02T22-35-43+08-00` 为 `IndexActivityV2`、home_feed、
  has_anr=false、risk_stop_reason=null，未搜索、未采集商品、未启动 scheduler/G2。
- 最终 DB quick_check=ok、running task=0、lease=0；desired=paused、
  scheduler=false、next=null，G2 expected 为空。历史 block/skip 仍精确保留为第二轮
  失败证据：`app left search flow while opening product: home_feed` / `opened page is
  home_feed`；risk=null。只有用户看到修复结果并明确同意继续后，才清这两项历史展示
  并按当时实际时间建立全新 G2 批次。

### 2026-08-03 12:23 新 G2 首轮及现场手动复现：搜索页原生库加载锁导致黑屏 ANR

- 新首轮 `monitor-3dc599a2df2a` / task 98 `合同` 在准确点击
  `home-search-bar` 后黑屏 ANR，captured=0；自动关闭/重开已成功，随后总控显式
  pause。13:15、14:15 作废，G2 expected 已清空。
- 用户要求现场查看后，总控只按程序同一坐标 `(906,64)` 再点一次，立即复现全黑；
  当前保留现场，未再点击、未 force-stop、未重开。
- Activity/Window 证据：`GlobalSearchActivity` 已 resumed，但 `windows=[]`、
  `reportedDrawn=false`；搜索页没有创建可见窗口。
- 12:16 和 12:20 ANR 主线程栈相同：`GlobalSearchActivity.onCreate →
  SoLoadProxy.loadLibrary → System.load → Runtime.load0 → MonitorEnter`。后台
  `SentryThreadPoo` 也在 `SentryFDMonitor` 的 `loadLibrary0` 等待；紧邻日志出现
  `Bad JNI version passed to GetEnv: 1879114240`。系统最终报首页失焦 FocusEvent
  超时和搜索页无 focused window。
- 本次无 OOM/FATAL 证据，不是按钮识别、OCR、关键词或商品卡问题，也不同于前一日
  Fresco OOM。当前判断是小红书 9.39.0 在 BlueStacks x86/Android 11 中的原生库/JNI
  初始化竞争或兼容故障。8793 仍 paused；8765 未触碰。修复方向应先做有限的环境/
  启动时序实验，不得直接重启 G2。

### 2026-08-03 12:54 删除每轮无条件冷启动，健康暖进程搜索验收通过

- 已确认“每轮先关再开”来自 scheduler 自行设置的
  `restart_app_before_round=True`，不是用户要求。现已改为 False；正常轮次保持应用
  进程，ANR/进程崩溃时的定向恢复仍保留。
- 定向 `22 passed`；完整回归 `727 passed, 3 skipped in 66.01s`。8793 已只按
  所有权脚本重载为 PID `5452`、HTTP 200；8765 PID `21820` 未触碰。
- 首次 BlueStacks 命令行冷启动 PID 27626 在没有搜索点击的情况下约 90 秒后 ANR；
  新栈为 `Alarm.onReceive → FindCodeForNativeMethod` 等待原生库锁，邻近日志含
  `libpag.so` 递归加载和非法 JNI version。该证据修正了“只要等待就一定稳定”的
  过度推断。
- 从模拟器首页人工点击图标后 PID 29302 首页稳定约 90 秒；程序准确识别并点击
  `home-search-button (1039,69)`，搜索页 Window 已绘制、可见并取得焦点，连续约
  40 秒无 ANR。未输入关键词、未采集或写商品，G2 未启动。
- 当前 desired paused、scheduler false、next null、risk/block/skip null、running=0、
  lease=0、quick_check=ok；页面停在稳定搜索页。无条件冷启动 P0 已完成；命令行冷
  启动本身的 JNI 兼容风险仍需作为后续恢复加固项，不得宣称整个模拟器环境已根治。

### 2026-08-03 14:25 新 G2 第一轮因指标条导航守卫误 Back 失败

- 用户明确授权立即开始新 G2。启动前 8793 PID `5452`、8765 PID `21820` 所有权
  正确；DB quick_check=ok、running=0、lease=0；小红书搜索页已绘制且获焦。
- 生产 DB 已备份到
  `data/backups/xhs_scout.sqlite3.before-g2-20260803-141621`，备份 quick_check=ok，
  SHA-256=`5710264c202a4a0775c45163cdac55a60003b6f7fa6f141251119493a4ab9b18`。
- 原定唯一有效点为 14:18/15:18/16:18。14:18:00 启动 run
  `monitor-753a39ad55df`、task 99 `食谱`；本轮 limits 明确
  `restart_app_before_round=false`，没有轮前重开。
- 搜索、商品卡和商品本体采集成功，写入 product 37 / observation 37：累计销量
  420、近 30 天新增好评 150、近 30 天感兴趣 1000，captured_products=1。
- G2 仍失败：`detail_metrics.py` 指标条流程在 focus tap 后仅凭 XML 控件启发式
  判断已离开商品详情。现场 `navigation-guard.png` 明确仍是完整商品详情，说明这是
  false positive；旧守卫随后自行 `device.back()`，实际把页面退回搜索结果，卖家
  采集前置探针因此硬停止
  `seller capture requires product_detail, got search_results`。
- 这不是黑屏、ANR、搜索失败或商品身份不明。scheduler 与 heartbeat `g2` 已暂停，
  15:18/16:18 取消，expected 已清空；DB quick_check=ok、running=0、lease=0，
  当前页面为搜索结果。精确 risk 原因保留，未清除、未重试。
- 正式证据：`evidence/g2-20260803-141800-{db,http,round}.json`；scheduler ledger
  record `g2-20260803-141800-blocked`，sequence=5，hash
  `ece8643c2116634b298d0bf566a046965519946bb614709398dbd6cced9600dc`。
- 下一唯一 P0 是修复导航守卫：实际 Activity/Window 仍为商品详情时不得因 XML
  控件缺失执行 Back；定向和完整回归、8793 重载及受控详情页验收完成并向用户
  汇报前，不得再启动 G2。

### 2026-08-03 14:45 按用户指定的三固定指标完成修复与加载

- 用户明确指定：购买按钮文案变化多，不再以“立即购买”或“领券购买”判断；商品
  详情只使用稳定的“客服”“购物车”“加入购物车”三项，必须同时存在。
- 失败现场真实 XML 核验完全支持该规则：detail-99 三项均为 true、立即购买=false、
  领券购买=true；seller-before 搜索结果三项均为 false。新函数对两份保存的真实
  XML 回放分别返回 true / false。
- `src/xhs_scout/detail_metrics.py` 已修改；`tests/test_detail_metrics.py` 新增两种购买
  文案均不影响详情判断，以及三项缺任一项都拒绝的回归用例。
- 定向 `11 passed in 2.99s`；完整 `728 passed, 3 skipped in 62.65s`。
- 仅重载本项目 8793，PID `5452` → `44268`；8765 PID `21820` 未触碰。当前
  desired=paused、scheduler=false、next=null，旧精确 risk 保留，G2 expected 为空；
  没有再次采集或启动 G2。

### 2026-08-03 15:15 用户现场重跑：分享链接 finally 的旧购买文案判断多按一次 Back

- 用户明确授权在可见 BlueStacks 中再次执行一次完整单商品采集。启动前小红书已从
  关闭状态恢复到正常首页；8793 PID 44268，8765 PID 21820 未触碰，scheduler 保持
  paused。生产 DB 备份为
  `data/backups/xhs_scout.sqlite3.before-visible-controlled-rerun-20260803-1510`，
  quick_check=ok，SHA-256=`e9cb512960ac40ff5d335693868c8dfd913aff52487fb24ca0185396e7973b36`。
- 受控 run `monitor-bd07cab4561d` / task 99 `食谱` 的所有导航点击均正确：点击首页
  长条搜索入口 `(906,64)`，点击历史词“食谱” `(64,209)`，点击商品结果第 1 张卡
  `(898,510)`，进入 `GoodsDetailActivityV2` 并通过三固定控件详情判断。小红书 PID
  始终为 `28358`，本轮没有黑屏、ANR 或 SIGSEGV/进程重启。
- 商品本体与分享链接采集成功，写入 product 39 / observation 39：价格 11.8、累计
  销量 717、share URL `https://xhslink.com/m/463063Q0npK`、direct URL
  `xhsdiscover://goods_detail/6859bff847fd8b0001e9d203`。灰色指标条未自动定位而安全
  跳过；卖家粉丝没有采集，所以完整流程仍失败。
- 根因已经精确到 `src/xhs_scout/product_link.py:391`：复制链接后分享面板自行关闭，
  但 finally 仍检查旧的“加入购物车”和“立即购买”。现场详情的购买按钮是“领券购买”，
  导致程序误判仍在分享面板并额外 `device.back()`，实际退回搜索结果。seller-before
  探针随后得到 `search_results` 并硬停止
  `seller capture requires product_detail, got search_results`。
- 前后证据分别为
  `data/probes/monitor-bd07cab4561d-probe-detail-99/current.png` 和
  `data/probes/monitor-bd07cab4561d-seller-before-99/current.png`。最终 DB
  quick_check=ok、running=0、lease=0；task 99 needs_manual_detail attempts=3/3；
  desired paused、scheduler false、next null，精确 risk 保留。G2 未启动。
- 下一唯一 P0：让 product-link 分享收尾复用“客服/购物车/加入购物车”三固定控件，
  增加领券购买回归测试；完成代码、完整回归、8793 重载和一次受控验收后再讨论 G2。

### 2026-08-03 15:26 分享链接收尾误 Back 修复已加载，等待真实验收

- 已把商品详情三固定控件判断集中到 `src/xhs_scout/ui_automation.py` 的
  `product_detail_controls_present`；`detail_metrics.py` 和 `product_link.py` 共用同一
  规则，避免再出现一处已改、另一处仍依赖购买按钮文案的漂移。
- `product_link.py` 复制链接 finally 现在只有在“客服/购物车/加入购物车”不完整时
  执行 Back。测试模拟分享面板已自动关闭、商品为“领券购买”的现场：旧代码
  `back_count=1` 并准确红灯，修复后 `back_count=0`；另一个分享面板仍开的分支继续
  断言一次 Back。
- 分享链接/详情指标/卖家相关定向 `28 passed in 3.35s`。完整回归第一次因自定义
  basetemp 的父目录不存在导致大量同源 FileNotFoundError，未形成代码失败证据；创建
  隔离父目录后正式重跑 `728 passed, 3 skipped in 75.50s`。
- 仅通过所有权脚本重载 8793，PID `44268` → `61332`；8765 PID `21820` 未触碰。
  当前 desired=paused、scheduler=false、next=null；精确 risk
  `seller capture requires product_detail, got search_results` 保留；DB quick_check=ok、
  running=0、lease=0。
- 本次没有操作小红书、没有再次写生产商品、没有真实流程验收或启动 G2。下一步在
  用户明确同意后，只执行一次单商品完整验收；完整通过后再汇报并决定是否进入 G2。

### 2026-08-03 16:16 单商品验收：店铺券弹层后小红书 SIGSEGV

- 用户授权一次完整单商品验收。生产 DB 先备份至
  `data/backups/xhs_scout.sqlite3.before-post-fix-full-validation-20260803-160946`，
  quick_check=ok，SHA-256=`6297c23216dc9b53f0763e09cf52819ad15c4c0c6555dd1419927cc7baba9f36`。
- run `monitor-f9899bb802d6` 搜索和商品详情成功，写入 product 40 / observation 40：
  价格 11.8、累计销量 717。复制链接阶段 Windows `Set-Clipboard` 临时标记写入失败，
  因此本轮链接为空；但 seller-before 仍为 product_detail，证明上一 P0 已解决多余
  Back，没有再次退回搜索结果。
- 用户现场看到点击店铺后出现店铺券弹层，随后黑/白屏和商品详情再次出现。日志给出
  精确归因：16:12:44.676 正确启动 ShopDetailActivity，16:12:44.939 displayed；
  16:12:46.430 启动 XhsReactTranslucentActivity 券弹层，16:12:46.733 displayed；
  16:12:48.081 PID 28358 因 signal 11 / SIGSEGV 退出。系统移除 ShopDetail/券弹层，
  16:12:48.117 自动启动 PID 13222 恢复 GoodsDetailActivityV2。程序没有再次点击商品。
- 当前卖家流程在点击店铺后固定等待，无法在约 1.35 秒窗口内识别/关闭券弹层，也没
  有卖家阶段 PID 变化守卫，最终把白屏误报为
  `店铺入口打开了未知页面：unknown`。卖家粉丝未采集，完整流程仍失败。
- run 结束 desired=paused、scheduler=false、next=null；上述 unknown 精确 risk
  保留，DB quick_check=ok、running=0、lease=0，task 99 needs_manual_detail 3/3；
  G2 未启动。用户随后可能人工操作，当前页面不纳入该受控 run 结论。
- 下一 P0 是点击店铺后的轻量 Activity/PID 快速观测：识别券弹层即留证并立即关闭；
  PID 改变则按 shop-open 进程崩溃明确停止/恢复，不能继续等待后报 unknown。

### 2026-08-09 红米真机店铺与粉丝局部闭环通过，正式代码已适配

- 真机为 Redmi Note 9 4G，Android 11 / MIUI 12.5，ADB 型号
  `M2010J19SC`、device `lime`；普通 USB 调试和“USB 调试（安全设置）”最终均生效，
  `persist.security.adbinput=1`，ADB 输入不再报 `INJECT_EVENTS`。
- 用户要求跳过完整环境验收，优先直接尝试采集。总控未启动 scheduler、G2 或
  monitor-loop，而是从 product 39 已验证 direct URL 打开商品详情，并调用现有卖家
  采集函数。首次标准输入临时脚本只因 RapidOCR multiprocessing 无法重载 `<stdin>`
  而在点击前停止；没有形成一次店铺点击。
- 第二次文件入口正常完成前置 OCR，但暴露真机差异：“店铺”TextView 的 bounds 为
  `[0,0][0,0]`，其最近可点击父节点为 `[22,2142][143,2218]`。新增专用定位后程序计算
  `(82,2180)` 并准确点击底部左侧店铺入口，没有点到评论、店铺口碑、客服或购物车。
- 店铺正常打开并显示“大麦美食 / 粉丝4437 / 238篇笔记”，同时出现“双重福利”券
  弹层。券不暴露在 UI XML；当前真实截图的唯一居中圆形叉号为 `(539,1720)`、半径
  27。程序高置信度点击一次后弹层关闭，XHS PID 点击前后均为 `691`，无黑屏、ANR、
  SIGSEGV 或进程重启；关闭后页面为 `shop_product_list`，现有解析器得到
  `follower_count=4437`。手机保留在店铺页，未继续操作。
- 真实证据：点击店铺前
  `data/probes/phone-direct-seller-20260809-file-seller-before-99/`；券弹层现场
  `data/probes/phone-direct-seller-20260809-file-seller-after-99/`；关闭后
  `data/probes/phone-direct-coupon-closed-20260809/`；额外截图证据
  `evidence/phone-direct-coupon-close/before.png`。
- 正式修复：`ui_automation.py` 支持店铺零尺寸文字节点回溯到左下角可点击父节点；
  新增 `coupon_overlay.py` 做券文字判断与唯一居中圆形叉号检测；`seller_profile.py`
  点击店铺后轮询 Activity/PID，快速关券并在 PID 改变时返回
  `shop_open_process_crash`；`signals.py` 能识别优惠券覆盖下的真实店铺页。
- 真机迁移：`emulator.py` 新增 Android 原生应用启动、按型号唯一选机和精确 mDNS
  服务地址选择；monitor 的恢复入口按 `backend` 分流。`config/emulator.json` 已切为
  `backend=android`，使用官方 Platform Tools、mDNS 服务
  `adb-741da30b0920-cvuER5` 和型号 `M2010J19SC`，不写死变化端口。
- 测试：首批相关定向 `39 passed`；恢复定向 `14 passed`；mDNS/最终相关定向
  `42 passed in 1.06s`；当前代码最终完整回归
  `734 passed, 3 skipped in 58.64s`。
- 本轮没有操作 8793 或其他项目 8765，没有启动/恢复 scheduler、G2、G4、G5 或
  CLI monitor-loop。局部读取结果没有写成 seller note observation；probe 仍按现有设计
  记录运行事件。新代码尚未重载到 8793，也未执行真机完整 monitor 的生产写入验收。
  下一步须经用户确认后，先按项目所有权方式重载 8793，再做一次最多单商品的完整
  真机验收；登录、验证码、风控、未知危险页、ANR、进程崩溃和 DB 锁仍硬停止。

### 2026-08-09 24 小时真机启动前 P0 工程已收口，等待接电

- 两个独立 Codex 任务均已完成并由总控验收：每日销量采集已迁移到 Android 原生启动、
  model + mDNS 稳定选机且兼容 BlueStacks；新增只读真机预检并接入 monitor，预检失败
  会在任务预留前暂停，不消耗 attempts。
- 现场发现 ADB 把同一红米同时列为 `192.168.110.182:43217` 与
  `adb-741da30b0920-cvuER5._adb-tls-connect._tcp`。选择器现按配置的 mDNS service
  优先稳定 serial，不再误报两台同型号设备。MIUI 的 `mIsShowing=false` /
  `isKeyguardShowing=false` 锁屏格式也已纳入失败关闭解析。
- 真机只读预检当前确认：ADB 在线、`M2010J19SC / lime`、
  `persist.security.adbinput=1`、USB 调试开启、屏幕亮且已解锁、小红书已安装、电量
  60%；唯一未通过项是当前未接外部电源。启动 24 小时前必须接充电线。
- 总控定向 `32 passed`，正式完整回归 `764 passed, 3 skipped in 71.17s`。验证前 DB
  备份为 `data/backups/pre-real-phone-validation-20260809T115512Z.sqlite3`，备份和
  原库 `quick_check=ok`；running=0、lease=0。task 99 仍为
  `needs_manual_detail` 3/3，没有恢复整批任务。
- 8793 已用项目脚本启动并加载新代码，PID `51536`、健康；desired=paused、scheduler
  未运行，旧 risk `店铺入口打开了未知页面：unknown` 原样保留。8765 未访问、未操作。
- 接手下一步：用户接电后先只读复跑预检。若全通过，精确确认并解除旧 risk、只把
  task 99 重置为单次验收任务，调用 8793 `/api/monitor/run-once`，参数固定为
  `task_id=99`、`expected_keyword=食谱`、1 keyword、1 product、seller profile=true。
  验收完整落库和 seller follower 后，再做 2–3 个短轮次；24 小时 scheduler 的具体
  间隔、每轮上限与停止条件仍须用户确认。禁止 CLI monitor-loop、G4/G5、Windows
  计划任务、8765、批量恢复和任何购买/加购/收藏/关注/评论/客服动作。
- 用户下达“开始执行”后已复跑只读预检：除 charging 外全部通过，电量 60%，系统仍
  报未接外部电源。按失败关闭规则在解除 risk、重置 task 99、点击手机和启动采集前
  停止；需用户确认手机状态栏显示正在充电后再继续。

### 2026-08-09 接电后三次真机完整验收与后续修复

- 接电后预检全部通过。仅重置 task 99，scheduler 始终未启动；备份为
  `before-task99-real-phone-validation-20260809T120806Z.sqlite3`，第二次后另有
  `before-task99-third-real-phone-validation-*` 备份。
- `monitor-b573dfef4185` 暴露 MIUI `mCurrentFocus` 新格式和真实店铺页恢复缺口；修复
  后完整回归 768/3。`monitor-8e0045e53347` 写入 product 41 / observation 41，价格
  8.9、销量 721，无进程崩溃；券 Activity 与截图之间自行消失造成时序误判，修复后
  完整回归 769/3。
- `monitor-f763d0ca743f` 启动时券仍覆盖店铺页，顶部搜索点击被弹层拦截；任务安全停止
  并耗尽 3/3。真实截图圆检测显示叉号 `(539,1720,r=27)`，同时存在券卡大圆角伪圆。
  现已用半径 + 中性灰中心过滤伪圆，并在搜索恢复前先关闭可见券；两张真实截图均
  唯一识别目标，最终完整回归 `771 passed, 3 skipped in 70.67s`。
- 8793 已加载最终代码，PID `58704`；desired=paused、scheduler=false、risk=null、
  running=0、lease=0、DB quick_check=ok。task 99=`needs_manual_detail 3/3`；product 41
  已有基础 observation，但没有 seller note/follower，完整闭环尚未通过。
- 下一步必须先取得用户明确授权，仅给 task 99 一次额外真实验收机会并保留现有审计；
  不得恢复其他任务。额外一次通过后才能进入 2–3 个短轮次；在这些阶段完成前不得
  启动 24 小时 scheduler。8765、CLI monitor-loop、G4/G5 和外部互动继续禁止。
- 用户最新方案已实现：店铺券不再点击关闭。程序进入店铺后对当前画面 OCR，遮罩下
  能看到粉丝数即记录 seller note；看不到则安全停止。恢复导航只允许有限 Back，搜索
  起点存在遗留券时同样使用 Back，不点击券。定向 23 通过、完整
  `771 passed, 3 skipped in 70.12s`；8793 PID `3756` 已加载。task 99 仍保留
  `needs_manual_detail 3/3`，额外一次真实验收仍需明确授权。

### 2026-08-09 额外一次 run 未进入小红书：起点仍在开发者选项

- 用户明确授权 task 99 仅增加一次额外真实验收。执行前手机曾熄屏、未充电，无线 ADB
  也短暂变为 offline；总控没有在这些预检失败时修改任务。用户重新连接并接电后，最终
  预检全绿：mDNS serial 在线、`M2010J19SC / lime`、ADB 输入与 USB 调试正常、亮屏
  解锁、包已安装、外部供电、电量 59%。
- 生产库先通过 SQLite backup API 备份到
  `data/backups/before-task99-coupon-ocr-validation-20260809T133353Z.sqlite3`，备份
  `quick_check=ok`。仅将 task 99 从 `needs_manual_detail 3/3` 重置为 `pending 2/3`，
  没有恢复其他任务，scheduler/monitor desired state 仍为停止/暂停。
- 调用 8793 单次入口得到 run `monitor-1ed4aceb99e7`。本轮预检通过，但 start probe
  Activity 为 `com.android.settings/com.android.settings.SubSettings`，截图
  `data/probes/monitor-1ed4aceb99e7-probe-start/current.png` 明确显示“开发者选项”。
  用户为恢复无线调试停留在系统设置；总控沿用了 `restart_app_before_round=false`，未在
  调用前补查小红书前台页面，这是本次前置条件遗漏。
- run 以 `search product button not found` 停止，processed=0、captured=0，没有点击
  小红书、没有进入商品/店铺、没有执行优惠券截图 OCR，也没有新增 product/observation。
  task 99 现为 `needs_manual_detail 3/3`，last_error 为上述错误；running=0、lease=0、
  主库 `quick_check=ok`。
- 该 run 对“券遮罩下读取粉丝数”没有形成任何成败证据。未经用户再次明确授权，不再
  重置或重跑。若获授权，执行前必须额外确认前台 Activity/page_kind 已是小红书目标页；
  或先离线修复 run-once 在非小红书起点的安全启动策略，再进行真实验收。8765、
  scheduler、CLI monitor-loop、G2/G4/G5 均未操作。

### 2026-08-09 券遮罩不关闭方案已在正式 run 完整落库

- 用户回到目标商品详情后，总控通过 `dumpsys window` 只读确认前台为
  `com.xingin.commercial.goodsdetail.v2.activity.GoodsDetailActivityV2`；设备预检同时
  全绿，外部供电、电量 61%。用户明确同意后才再次为 task 99 增加一次机会。
- 重置前备份为
  `data/backups/before-task99-coupon-ocr-validation-retry-20260809T134046Z.sqlite3`，
  backup quick_check=ok。只修改 task 99 为 `pending 2/3`，其他任务、risk、scheduler
  均未改动。
- 8793 run `monitor-22121bd8c617` 成功处理 1 task、采集 1 product：product 42 / 
  observation 42，价格 8.9、累计销量 721。product link 仍因 Windows clipboard 未收到
  复制内容而跳过；灰色 metrics strip 仍未定位，这两项不是本轮店铺粉丝闭环的失败。
- seller before 为商品详情；程序准确点击底部店铺入口后，seller after Activity 为
  `XhsReactTranslucentActivity`，页面分类为 `shop_product_list`。真实截图
  `data/probes/monitor-22121bd8c617-seller-after-99/current.png` 中券遮罩仍在，同时顶部
  清晰可见“大麦美食 / 粉丝4439 / 238篇笔记”。
- 程序没有点击优惠券：note observation 9 的 `raw_json` 为
  `coupon_observed=true`、`coupon_close=null`。OCR 解析 `follower_count=4439` 并成功
  写库；这正是用户指定的“优惠券不关，只要截图能读到粉丝数即可”路径。
- 记录后程序使用有限 Android Back：先从券 Activity 回到 `ShopDetailActivity`，再回到
  商品详情，随后回到搜索结果。无 ANR、黑屏、SIGSEGV、进程重启、验证码或风控；
  event 751 为 `task_completed`。
- 当前生产状态：task 99=`completed 3/3`、last_error=null，running=0、lease=0、
  desired=paused、scheduler=false、risk=null、主库 quick_check=ok。没有操作 8765，
  没有启动 CLI monitor-loop、G2/G4/G5 或 24 小时 scheduler。
- 阶段判断：正式单商品的基础信息与 seller follower 已在同一 run 闭环通过，但仍不能
  宣称 24 小时就绪或稳定。已知缺口包括：非小红书前台起点会在失败前领取任务、商品
  title/shop_name/direct_url 仍为空、seller `author_name` 误解析为页面时间“晚上9:43”、
  Windows clipboard 链接失败、metrics strip 未取到。
  下一步由用户选择先修 P0/P1，还是先授权 2–3 个短连续轮次；任何 scheduler/长期运行
  都需另行明确确认。

### 2026-08-09 24H 前起点恢复、名称标题与 direct URL 离线修复完成

- 用户要求继续后，本批只做本地代码与测试，没有操作手机、生产 DB、8793、8765、
  scheduler、CLI monitor-loop 或 G2/G4/G5。真实重载与 2–3 个短轮次留在用户确认点。
- `monitor.py` 新增 Android 任务领取前的前台保护：若 `mCurrentFocus` 不是小红书，先
  用 Android 原生入口启动，再 probe 验证 Activity 和允许的 page_kind；启动后仍是
  Android 设置/unknown 时，monitor 暂停并在任务领取前返回。测试精确复现
  `SubSettings`，search task 保持 `pending attempts=0 run_owner=null`。
- `note_observation.py` 不再从页面顶部机械取第一个短文本。店铺/账号名称优先从“粉丝”
  行向上查找，过滤“晚上9:43”、纯数字、星级、已售量、好评率等噪声。正式 run 保存的
  seller probe 离线回放得到“大麦美食 / 粉丝4439”。`seller_profile.py` 在产品店名为空
  时回填该可靠店名，不覆盖已有值。
- `signals.py` 保留原虚拟品关键词标题规则，并增加严格兜底：必须存在“已售”强锚点，
  只扫描其后最多 8 行且排除优惠、发货、评价、购买控件。正式 detail probe 回放得到
  “从160斤到105斤，30天减脂烹饪食谱分享！！”、8.9、721；价格孤证首页仍不成立。
- `product_link.py` / `workflow.py` 修复真机剪贴板架构差异：Android 手机内复制不会
  自动同步 Windows clipboard，但 Activity dump 可能已经包含稳定商品 deeplink。现在
  即使 share_url 获取失败，也保留、验证并写入
  `xhsdiscover://goods_detail/...` direct_url；已有 share_url 不会被 null 覆盖。没有尝试
  未授权的 Android 剪贴板服务、辅助应用或重复点击。
- 组合定向 `62 passed in 1.11s`，正式完整回归
  `776 passed, 3 skipped in 54.32s`。本批代码尚未加载到运行中的 8793；product 42 的
  历史 title/shop_name/direct_url 未做生产库回填。下一步若用户确认：先按项目所有权
  方式重载仅 8793，再复核 paused/scheduler=false/DB 无 lease，之后制定最多 2–3 个
  单商品短轮次的明确任务、停止条件和备份，不直接启动 24 小时 scheduler。

### 2026-08-09 第一个短轮暴露首页搜索无 XML 节点，视觉定位离线修复完成

- 用户批准备份生产库、仅重载 8793、最多进行 3 个“1 task / 1 product”短轮；明确
  禁止启动 scheduler，并要求遇到验证码、风控、ANR、黑屏、进程异常或 unknown 立即
  停止。执行前 desired=paused、risk=null、scheduler=false、running=0、lease=0、
  DB quick_check=ok。
- 生产备份：`data/backups/before-8793-short-rounds-20260809T145800Z.sqlite3`，
  quick_check=ok。使用 `ops/stop_workbench.ps1 -Execute` 和
  `ops/start_workbench.ps1 -Execute` 仅重载 8793；健康检查全绿，8765 只作为 ignored
  port 出现在脚本结果中，未访问、未操作。
- 第 1 轮 `monitor-97bfcb656286` 领取 task 22 / 奥数资料。monitor 在领取任务前发现
  Android 设置页，成功启动小红书并 probe 到 `IndexActivityV2 / home_feed`，说明新的
  前台起点保护已在真实 run 生效。
- 起点首页截图中右上角搜索放大镜清晰可见，但 UI XML 完全没有顶部导航/搜索节点，
  旧程序因此报 `search product button not found`。本轮没有点击错误区域、没有新增
  product/observation，task 22=`pending attempts=1/3`，running=0、lease=0、主库
  quick_check=ok。按停止规则取消剩余两轮。证据：
  `data/probes/monitor-97bfcb656286-probe-start/current.png`。
- 离线新增截图式搜索入口识别：调用方必须已确认 `home_feed + IndexActivity`；检测器
  只看右上安全区域，并要求唯一的圆环、亮色中心及右下斜柄，坐标来自实际圆心。任何
  缺失、歧义或区域错误都拒绝定位；绝不恢复“顶部最右节点”或固定坐标盲点。XML 明确
  搜索语义继续拥有优先级。
- 真实失败截图回放得到搜索圆心约 `(1002,136)`。视觉检测、安全门和原 XML guard
  定向 `22 passed in 0.77s`；完整 `tests` 回归
  `784 passed, 3 skipped in 54.96s`。根目录 pytest 曾只因收集三个历史
  `data/test-tmp` 权限目录失败，随后按项目测试边界全绿；没有删除历史目录。
- 当前停止点：新修复尚未加载到 8793，也尚未真实点击验证。下一步需用户明确确认后，
  仅重载 8793，并在 task 22 剩余 attempts 内做一次单商品短轮；成功后再决定是否继续
  后续短轮。scheduler、CLI monitor-loop、G2/G4/G5、批量任务恢复、外部互动和 8765
  仍严格禁止。

### 2026-08-09 首页搜索图标真实验证通过，当前阻塞转为 Android 中文输入

- 用户授权仅重载 8793 并让 task 22 单轮运行。无线 ADB 重新配对、连接到
  `192.168.2.238:41183` 后，设备预检全绿：`M2010J19SC / lime`、输入权限、USB
  调试、屏幕/锁屏、包安装、充电和 100% 电量均通过。
- 备份为 `data/backups/before-task22-home-search-visual-20260810T025140Z.sqlite3`，
  quick_check=ok。只重载项目 8793：旧 PID 55632 已停，健康检查确认新 listener
  PID 67276；8765 未访问、未操作，scheduler 未启动。
- 正式 run `monitor-e21561165b70` 从 Android 设置页自动拉起小红书，确认
  `IndexActivityV2 / home_feed`。新检测器唯一定位 `(1003,135)`，事件
  `tap_home_search_visual_icon` 后正常到达 `GlobalSearchActivity / search_input`。
  结论：此前“首页右上搜索按钮可见但 XML 缺失”问题已真实解决，不需要再改坐标。
- 新的真实失败发生在关键词输入。旧代码用 Windows `Set-Clipboard` 后发送 Android
  PASTE；Windows 与红米手机剪贴板不互通，手机粘贴的是历史内容
  “【小红书】2026最新30天减脂…”，并非“奥数资料”。`keyword_submitted` 事件只说明
  发出了粘贴动作，不能证明关键词正确。
- 随后页面是正常 `GlobalSearchActivity` 结果页，顶部 query 和 UI XML 均保存了错误
  关键词；页面同时出现首次“搜索后支持下拉刷新”引导层。旧 OCR 分类器缺少
  `GlobalSearchActivity + 全部/商品等标签` 的结构兜底，故返回 unknown。程序按约定
  停止，没有点击商品/店铺或写入 observation。
- 当前生产状态：task 22=`pending attempts=2/3`、last_error=`not on search results:
  unknown`，running=0、lease=0、risk=null、desired=paused、scheduler=false、DB
  quick_check=ok。最后一次 attempt 必须保留到 Android Unicode 输入和提交后 query
  校验完成，不能直接再跑。
- AOSP `input text` 走 `KeyCharacterMap` 键事件映射，不能当作可靠中文注入；该 MIUI
  的 `cmd clipboard help` 返回 `No shell command implementation`。建议使用可审计的
  ADB Unicode 输入助手：只在搜索输入时临时切换，输入后立即恢复原
  `com.sohu.inputmethod.sogou.xiaomi/.SogouIME`，并在任务领取前检查助手安装/启用，
  提交后精确读回 query。下载 APK、安装和启用第三方 IME 属于新的真机配置变更，必须
  先取得用户明确确认；确认前不下载、不安装、不继续 task 22。

### 2026-08-09 用户授权直接完成 24H 低粉爆款扫描台，当前任务转交新总控

- 用户最新明确指令：不要再为正常执行步骤反复询问，由总控自行列好计划直接执行，
  最终交付可运行的 24 小时低粉爆款扫描台。用户已授权下载、校验、安装并临时启用
  ADBKeyBoard（或总控经审计选择的等价开源 Unicode 输入助手）、修改代码与测试、
  备份生产库、仅重载 8793、分阶段真机验收，并在所有 P0 和短轮阶段门槛通过后使用
  项目已有内置 scheduler 进入保守 24H 运行；无需再逐项询问同一授权。
- 授权不包含任何绕过或外部互动：验证码、登录、风控、ANR、黑屏、XHS PID 异常、
  unknown/危险页面、数据库锁、定位歧义仍硬停止；严禁 8765、CLI monitor-loop、
  G2/G4/G5、24H soak、Windows 计划任务，以及购买、加购、收藏、关注、评论、客服。
- 本任务在下载/安装前停止，未产生半安装状态。新总控从 TASK_BOARD section 63/64
  继续；不要重做已通过的首页视觉定位。当前关键数据：8793 健康 listener 最近为
  PID 67276；task 22=`pending attempts=2/3`；最新 run `monitor-e21561165b70` 已证明
  `(1003,135)` 首页搜索点击正确，但手机粘贴了旧剪贴板内容，结果页引导遮罩被误判
  unknown。备份为
  `data/backups/before-task22-home-search-visual-20260810T025140Z.sqlite3`。
- 新总控下一顺序：压缩读取交接 -> 只读复核状态 -> 安装并验证 Unicode 输入助手 ->
  代码实现“任务领取前助手预检、Base64 中文输入、finally 恢复搜狗 IME、提交前和结果
  页 query 精确读回” -> 用 `GlobalSearchActivity + 全部/商品标签` 严格识别引导遮罩下
  结果页且不点击遮罩 -> 定向/完整回归 -> 新备份、仅重载 8793 -> task 22 最后一次
  单商品验收 -> 2 个额外短轮 -> 达标后才启动内置 scheduler。正常步骤直接执行；只有
  手机系统确认框或硬停止事件才找用户。

### 2026-08-10 新总控已接管，ADBKeyBoard 安装等待 MIUI 系统人工允许

- 压缩交接与只读基线已完成。8793 仍为本项目 PID `67276`；desired=paused、
  scheduler=false、next=null、risk=null、running=0、lease=0、DB quick_check=ok；task 22
  仍为 `pending attempts=2/3`，没有消耗最后一次机会。未访问或操作 8765。
- 红米仍通过 `192.168.2.238:41183` 在线，`M2010J19SC / lime`、亮屏解锁、外部供电、
  电量 100%；小红书 PID `29019`，前台为 `GlobalSearchActivity`。原默认输入法仍是
  `com.sohu.inputmethod.sogou.xiaomi/.SogouIME`。
- 官方 GitHub Release APK 已下载至
  `tools/adbkeyboard/v2.4-dev/keyboardservice-debug.apk`。版本 `v2.4-dev`，大小 18595，
  SHA-256=`e0d0cf276b710cb34c46121f58720f5285a83ed410b0d45f57a0677b67dc2852`；来源、发布日期、
  选择依据和源码审计见同目录 `SOURCE.json`。官方 README 将其标作 stable APK，Release
  页面自身标为 pre-release，二者均已如实记录。
- 首次安装命令返回
  `INSTALL_FAILED_USER_RESTRICTED: Install canceled by user`。这属于 MIUI 系统必须人工
  允许的门禁；没有绕过、没有重复安装、没有启用助手、没有切换 IME，搜狗保持默认。
- 用户当前只需在手机上允许 USB/ADB 安装：若有系统安装确认框，手动确认；若没有弹框，
  在开发者选项启用“USB 安装”。确认完成后回复总控即可。总控随后只重试同一已校验 APK
  一次，验证 package/IME 且保持搜狗默认，再继续 Unicode 输入代码、query 校验、遮罩分类、
  测试、备份、仅重载 8793 和分阶段短轮。task22 在离线全绿前继续禁止运行。

### 2026-08-10 Unicode 输入成功但即时读回假阴性，等待一次额外 task22 授权

- 用户允许 MIUI USB 安装后，官方 ADBKeyBoard 已成功安装、启用；真实切换/恢复预检
  全绿，默认输入法仍为原搜狗。Android Base64 输入、提交前后 query 精确校验、finally
  恢复、助手缺失时领取前失败和结果页引导遮罩严格分类均已实现；BlueStacks 剪贴板兼容
  路径未删除。
- 首轮代码相邻回归 104 通过，完整 `792 passed, 3 skipped`；备份
  `before-unicode-input-8793-reload-20260810T041345Z.sqlite3` quick_check=ok，随后仅重载
  8793，listener PID `47712`。
- 正式 run `monitor-fbeb3bba8d87` 的设备、助手和小红书前台预检全部通过。Base64 实际
  已把“奥数资料”写入搜索框，但第一次 UI dump 过早，旧通用读取返回 None，所以提交前
  安全门停止。没有提交搜索、没有点击商品/店铺、没有新增 product/observation；搜狗已
  恢复，无 ANR、风控、黑屏或 PID 异常。
- 停止后证据 `data/probes/probe-2026-08-09T21-16-13-07-00` 清楚显示“奥数资料”；XML
  真实格式是 `搜索, 奥数资料`。task22 已按现有语义转为
  `needs_manual_detail attempts=3/3`，不得自行重置。
- 已新增专用输入框解析和最多 10 次 × 0.3 秒有限精确轮询，真实 XML 回放通过；定向
  `38 passed`，最终完整 `794 passed, 3 skipped in 53.12s`。第二备份
  `after-task22-unicode-readback-stop-20260810T041919Z.sqlite3` quick_check=ok，SHA-256=
  `a65f939d2fc0ec4aad43e82bbd8be38b1bea525368df8ac9469e91c435b55ca8`。仅重载 8793 后
  当前 listener PID `46132`。
- 当前 desired=paused、scheduler=false、risk=null、running=0、lease=0、DB
  quick_check=ok、搜狗为默认；last_block 精确保留该读回假阴性。未访问/操作 8765，未
  启动后续短轮或任何 scheduler/soak。
- 下一步只有一个决策点：用户是否明确授权仅把 task22 从 3/3 调整回 `pending 2/3`，
  保留全部历史审计，再执行一次 `task_id=22 / expected_keyword=奥数资料 / 1×1` 验收。
  未获授权前不得重置或以其他任务替代。通过后才做两个额外短轮，全部通过后才启动已有
  内置 scheduler 的保守 24H 运行。

### 2026-08-10 额外 task22 已正确搜索，结果页顶部 query 读回假阴性再次硬停止

- 用户授权仅给 task22 增加一次机会。先备份为
  `data/backups/before-task22-unicode-readback-retry-20260810T044343Z.sqlite3`，SHA-256=
  `a65f939d2fc0ec4aad43e82bbd8be38b1bea525368df8ac9469e91c435b55ca8`，原库/备份
  quick_check=ok；仅 task22 由 `needs_manual_detail 3/3` 审计调整到 `pending 2/3`，
  没有改其他任务。
- 唯一 run `monitor-f5c35cea68d8` 的设备和 helper 预检全绿。Base64 输入后提交前精确
  读回“奥数资料”，事件记录 `query_verified=true`；finally 已恢复原搜狗。提交后正常
  到达 `GlobalSearchActivity / search_results`，没有验证码、登录、风控、ANR、黑屏、
  进程异常或危险页。
- 真实结果证据位于
  `data/probes/monitor-f5c35cea68d8-probe-search-results/`。截图、OCR、XML 顶部 query
  都精确是“奥数资料”，且五个结果标签完整。程序仍报
  `search results query mismatch after Unicode submit` 并硬停止；没有点击商品/店铺，
  products=34、observations=42，processed=0、captured=0。
- 根因是结果页 UI 树 y=78 的空文本 ViewPager 排在 y=89 的 query TextView 前面，旧
  通用函数先选空容器后返回 None。现已改为优先读取顶部非空 TextView/EditText；仍
  精确匹配，不读 OCR 正文、不做模糊包含，并保留旧 BlueStacks 兼容回退。真实 XML
  回放通过；定向 `31 passed`，正式完整回归 `795 passed, 3 skipped in 48.91s`。
- 停止后备份
  `data/backups/after-task22-post-submit-readback-stop-20260810T044804Z.sqlite3`，SHA-256=
  `f0b7f1b9fc28b0f74e75e74e01550bcd26d2030fe66dc66874a7fb1423ea2cc3`，原库/备份
  quick_check=ok。只重载 8793 后健康 listener PID=`36672`；未访问或操作 8765。
- 当前 task22=`needs_manual_detail 3/3`，running=0、lease=0、desired=paused、
  scheduler=false、next=null、risk=null，默认 IME=搜狗，小红书 PID=29019。用户本次
  授权的一次机会已经消耗，禁止自行再重置或用其他任务绕过。两个额外短轮和 24H
  scheduler 均未启动；下一步必须由用户明确决定是否再给 task22 一次真实验收机会。

### 2026-08-10 task22 已完整成功，额外短轮 1 因 unknown/lease 风险锁暂停

- 用户已明确授权项目内持续执行，不再为正常备份、审计重试、修复、测试、仅重载
  8793、短轮和门槛通过后的内置 scheduler 重复询问；只有验证码、登录/风控、ANR、
  黑屏、unknown/危险页、进程异常、DB 锁或手机系统人工确认等硬停止才找用户。
- 结果页顶部 query 与商品卡两个真实假阴性已分别修复并回放。task22 最终 run
  `monitor-f205db4ec79e` 完整成功：processed=1、captured=1、task22=completed 3/3，
  新增 product/observation ID 43。商品 price=19.9、已售4313、近30天好评>=500、近30天
  感兴趣>=1000、direct_url 已保存；店铺“不暴躁的杨老师”粉丝约17000；店铺后安全
  恢复详情，搜狗恢复，无硬风险。
- task22 最终轮前备份为
  `data/backups/before-task22-product-card-retry-20260810T054413Z.sqlite3`，SHA-256=
  `7fa37fa0f9084bb2526efe42bd854572a99c71750c44c57166efafa5062f18e8`，quick_check=ok。
- 额外短轮 1 为 task23“自然拼读”，run `monitor-8b0134de4b35`。Unicode 关键词与结果页
  均正确，点击第1张明确商品卡后 Activity 为 `GoodsDetailActivityV2`，但旧 OCR 评分把
  页面判为 unknown；lease 门禁随即硬停止并阻止 back。processed=0、captured=0，task23
  保持 pending attempts=1/3，没有新增 product/observation。
- 证据 `data/probes/monitor-8b0134de4b35-probe-detail-23/` 清楚证明是正常商品详情：价格
  8.8、已售6166、完整顶部和底部控件均存在，无验证码、登录、风控、ANR、黑屏或危险
  跳转。误判只因页面显示“款式”而非“已选”。
- 已新增严格 `GoodsDetailActivityV2 + 完整顶部/底部控件 + 价格 + 已售` UI 兜底，只分类
  不交互；真实 XML 回放通过。定向 `33 passed`，完整
  `797 passed, 3 skipped in 51.32s`。
- 停止后备份
  `data/backups/after-task23-unknown-stop-20260810T055345Z.sqlite3`，SHA-256=
  `4cd4ac613604d6b34dc4ec1560877b20edaeea889686f0d3c4f209fe73c92472`，主库/备份
  quick_check=ok、running=0、lease=0。仅重载 8793 后 listener PID=`52820`；未访问或
  操作 8765。
- 当前 desired=paused、scheduler=false、next=null，默认 IME=搜狗、XHS PID=29019。
  risk_stop_reason 与 last_block_reason 精确为
  `lease safety blocked at before_non_product_recovery: task_not_running`。这是生产风险锁，
  必须由用户明确确认同一原因后才能使用现有风险恢复 API 清除；额外短轮 2 和 24H
  scheduler 均未启动。

### 2026-08-10 风险锁已清除，当前改由无线 ADB 网络变化阻塞

- 用户回复“确认”后，已按精确原因清除 lease safety 风险锁，并立即重新 pause。API
  恢复瞬间 scheduler 状态短暂切换，0.75 秒后复核为 desired=paused、
  scheduler_running=false、next_run_at=null；没有执行 scheduler 轮次。
- task23 重试前备份
  `data/backups/before-task23-product-detail-retry-20260810T090944Z.sqlite3`，SHA-256=
  `67c0c9d6e59022e352fcd62c60b3c69f1d78c3404a5ea8c35f56f9443c754f68`，主库/备份
  quick_check=ok。
- `monitor-42922597c226` 在领取任务前失败关闭：未发现已配对无线调试服务
  `adb-741da30b0920-cvuER5`。processed=0、captured=0；task23 仍 pending attempts=1/3，
  没有点击手机或新增数据。
- ADB devices/mDNS 在重启本地 daemon 后仍为空；电脑当前 WLAN 为 `192.168.1.118`，
  手机旧 `192.168.2.238:41183` 已不可达，推断网络段或手机无线调试状态已变化。未扫描
  局域网其他设备。
- 当前 desired=paused、scheduler=false、next=null、risk=null、running=0、lease=0、
  DB quick_check=ok。需要用户让手机与电脑连同一 Wi-Fi，打开并保持“无线调试”，提供
  当前“IP 地址和端口”；若必须重新配对，再提供配对码页端口。连接恢复后直接继续
  task23、额外短轮2与24H门槛，不再询问普通授权。

### 2026-08-10 新 ADB 地址已连接，搜狗用户须知需要手机人工选择

- 用户提供 `192.168.1.119:37503`，现有配对密钥直接连接成功；设备仍为
  `M2010J19SC/lime`，helper 已启用、默认 IME=搜狗、小红书 PID=29019。
- run `monitor-ab4e9dbb3622` 的设备/helper 预检全绿，并从无线调试设置页安全拉起小红书
  首页；视觉搜索入口 `(1003,135)` 继续真实有效。
- 进入搜索框后出现 MIUI 管理的搜狗小米版首次“用户须知”弹窗，Activity 为
  `com.miui.securitycenter/com.miui.permcenter.permissions.SystemAppPermissionDialogActivity`，
  按钮为“退出 / 同意”。证据目录：
  `data/probes/monitor-ab4e9dbb3622-probe-search-input/`。这是隐私协议选择，程序不能代替
  用户点击，已按 unknown 硬停止；未输入/提交关键词、未点击商品/店铺、未新增数据。
- task23=`pending attempts=2/3`，最后一次机会继续保留到用户处理弹窗后；备份
  `data/backups/after-task23-sogou-notice-stop-20260810T092006Z.sqlite3`，SHA-256=
  `0a33134abcb2d2e24f48b181990eb64f4ef010056a8a894d38f60114508a2d33`，主库/备份
  quick_check=ok。
- 当前 desired=paused、scheduler=false、next=null、risk=null、running=0、lease=0。
  用户需亲自在手机上决定“退出/同意”，处理完回复后再只读确认弹窗消失并继续 task23；
  额外短轮2和24H scheduler 均未启动。

### 2026-08-10 搜狗须知已消失，当前再次等待无线调试地址

- 用户处理搜狗须知后，已只读确认弹窗文本消失、默认 IME=搜狗、小红书前台为
  `IndexActivityV2`。没有代替用户点击协议。
- 8793 随后发现无 listener；确认 DB 无 running/lease 后仅用项目脚本恢复。当前健康
  listener PID=`30372`，desired=paused、scheduler=false、risk=null，未操作 8765。
- 本地 ADB daemon 重启后，`192.168.1.119:37503` 已超时且 mDNS 为空。task23 仍为
  pending attempts=2/3，最后机会未消耗；DB quick_check=ok。
- 需要用户重新打开并保持手机无线调试页，发送当前 IP:port。连接恢复后直接跑 task23，
  不再重复询问其他授权；额外短轮2和24H scheduler 仍未启动。

### 2026-08-10 两个额外短轮全绿，内置保守 24H scheduler 已真实启动

- 无线 ADB 当前为 `192.168.1.119:38241`，设备 `M2010J19SC / lime` 唯一在线。Windows
  重名 mDNS serial 含空格和 `(2)` 的两处解析缺陷已经修复；最新完整回归为
  `799 passed, 3 skipped`。默认 IME 始终恢复
  `com.sohu.inputmethod.sogou.xiaomi/.SogouIME`。
- task23“自然拼读”最终 run=`monitor-ebef1c966fe2` 完整成功，product/observation ID 44：
  price=3.99、已售3009、近30天感兴趣>=1000、店铺粉丝约12000；task23=completed 3/3。
- task24“教资题库”遇到一次真实 React 店铺页/关注优惠券层误判；已用严格店铺结构修复，
  未点击关注或优惠券。最终 run=`monitor-7e82d360a987` 完整成功，product ID 45：
  price=20.9、已售2174、近7天感兴趣>=3000、店铺“顾顾敌川”粉丝约21000；task24=
  completed 3/3。React 店铺页、商品详情和搜索结果恢复均通过，无验证码、登录/风控、
  ANR、黑屏、进程异常或 DB 锁。
- scheduler 启动前备份：
  `data/backups/before-built-in-24h-scheduler-start-20260810T102413Z.sqlite3`，
  quick_check=ok，SHA-256=
  `75896033ef43256794811ef4ff12a6d948d53002c6d27ca692c38627325d9f9a`。
- 已仅通过 8793 的 `/api/monitor/resume` 启动项目内置
  `ContinuousMonitorScheduler`；没有启动 CLI monitor-loop、G2/G4/G5、soak、Windows
  计划任务，也未操作其他端口。配置为每3600秒1轮、每轮1关键词/1商品、最多3张结果卡、
  metrics最多3帧、note_evidence=false、seller_profile=true、App不做无条件冷启动；范围
  仅“虚拟资料”根词与5个已批准 discovery 关键词。
- 首轮 scheduler run=`monitor-05ce26871176` 已成功完成 task117“食谱”：processed=1、
  captured=1，新增 product/observation ID 47，price=8.9、已售722、店铺粉丝4442；店铺后
  正确恢复搜索结果。当前 listener PID=`28472`，desired=running、scheduler_running=true、
  risk=null、scheduler_consecutive_failures=0、running task=0、lease=0、DB quick_check=ok、
  next_run_at=`2026-08-10T04:28:08-07:00`。
- 24H 状态必须如实表述为“已启动并首轮成功，尚未累计满24小时”，不能用测试或首轮
  冒充24H稳定。后续只观察内置 scheduler 的真实轮次；验证码、登录/风控、unknown、
  ANR、黑屏、XHS进程异常、ADB不唯一/掉线或DB锁仍按硬停止处理。

### 2026-08-10 主机重启中断首个24H窗口，当前等待新无线调试地址

- 后续核验发现 Windows 在 `04:42:35-07:00` 被系统正常重启，新启动时间
  `04:43:05-07:00`；8793 与 ADB daemon 因主机重启同时消失。此前首轮
  `monitor-05ce26871176` 数据完整，但24H连续窗口已中断，不能宣称稳定或继续累计。
- DB 仍 quick_check=ok、products=38、observations=47、running=0、lease=0。服务恢复前
  已把 stale running 状态原子落为 desired=paused、scheduler=false、next=null，避免
  监听器恢复后在无设备状态自动抢跑。
- 当前 8793 仍由项目原 `start_workbench.ps1` 启动，但调用方改为 Windows WMI
  `Win32_Process.Create`，以脱离当前 Codex 子进程；未创建 Windows 计划任务、服务、
  CLI monitor-loop 或任何替代 scheduler。健康 listener PID=`2792`，保持 paused。
- ADB daemon 已重建，但 mDNS 与 devices 均为空，旧 `192.168.1.119:38241` 超时。必须由
  用户在手机无线调试页提供最新 IP:port（若弹出系统配对确认则人工确认）。连接恢复后
  总控直接做唯一设备/IME/DB/8793 预检，重新启动同一个内置 scheduler；新的连续24H
  起点以恢复后的成功首轮为准。

### 2026-08-10 8793 已跨回合存活，ADB 被不同 Wi-Fi 网段阻塞

- WMI 启动的 8793 listener PID `2792` 在新回合仍健康，当前 paused；该启动方式已证明
  不依附前一 Codex 子进程。
- 用户提供的手机地址仍为 `192.168.1.119:38241`，但电脑 WLAN 当前地址为
  `172.20.10.3`、网关 `172.20.10.1`。Ping、TCP 38241、ADB connect 和 mDNS 均失败，
  明确是两端网络不同，不是项目代码问题。
- 用户需先让电脑与 Redmi 处于同一 Wi-Fi，再从手机无线调试页发送实时 IP:port。恢复后
  不再重做工程验收，直接完成设备/IME/DB 预检并启动新的连续24H内置 scheduler 窗口。

### 2026-08-11 主机再次重启，当前手机无线调试监听未开启

- Windows 又在上一轮后重启，当前 boot time=`2026-08-10T06:36:05-07:00`；这会终止
  所有普通/WMI 进程，故此前24H窗口继续无效。当前电脑 WLAN=`192.168.3.217`。
- 历史已配对手机端点 `192.168.3.220:38241/41183` 均拒绝连接；mDNS 的
  `192.168.3.220:41183` 广播短暂出现后消失，ADB devices 为空。必须在 Redmi 上重新
  关闭/打开无线调试并保持页面亮屏，提供实时 IP:port。
- DB 安全 paused、risk=null、scheduler=false、next=null；首轮成功数据仍完整。8793
  已再次由 WMI 调用项目脚本启动，健康 listener PID=`36188`，未创建计划任务、服务或
  替代 scheduler。ADB 恢复前不会启动新的连续24H窗口。

### 2026-08-11 手机新端口与电脑实时网段仍不一致

- 用户发送 `192.168.3.220:41469`，但电脑 WLAN 已切回
  `192.168.1.118/192.168.1.1`。直连、Ping、TCP、mDNS 均失败；尝试同端口的历史手机
  地址 `192.168.1.119:41469` 也超时。
- 8793 PID `36188` 跨回合仍健康 paused，DB/任务没有变化。下一步只能由用户确认电脑与
  Redmi Wi-Fi SSID 完全相同，再在 Redmi 上关闭/打开无线调试并发送与电脑同网段的实时
  IP:port；连接前不启动 scheduler。

### 2026-08-11 网络审计结论：Clash 不是不同子网的原因

- 电脑连接 SSID=`享学`、BSSID=`fa:4c:da:e4:45:6c`，WLAN=`192.168.1.118/24`、
  gateway=`192.168.1.1`。Clash Party/mihomo 仅设置 WinINET proxy `127.0.0.1:7890`；
  当前无活动 TUN/VPN 网卡或 VPN 路由。
- 到手机 `192.168.3.220` 的路由实际走 `192.168.1.1 -> 100.64.0.1`，Neighbor 为
  Unreachable，说明该地址被当作外部网络，不是同一 LAN，也不是代理截获。
- 即使两端显示同一个 SSID 名，仍可能连接到两个同名路由器、路由模式扩展器/mesh、访客
  VLAN 等不同 DHCP 域。必须读取 Redmi Wi-Fi 详情的 SSID/IP/网关/BSSID；与电脑真正
  同网时应为 `192.168.1.x` 且网关 `192.168.1.1`。服务继续 paused、无任务消耗。

### 2026-08-11 电脑侧深查完成：ADB/防火墙/代理正常，享学实际有 4 个 BSSID

- WLAN 由 `192.168.1.1` DHCP 实时发放 `192.168.1.118/24`，默认路由和本地路由均正常；
  Clash `tun.enable=false`、Wintun stopped、WinHTTP direct，无 Windows VPN、NAT、ICS
  共享或第三方 WLAN 过滤绑定。电脑梯子没有接管 ADB 原始 TCP/mDNS 流量。
- 当前网络虽为 Public，但 UDP 5353 mDNS 入/出站规则在 Public 上明确 allow，官方
  `adb.exe` 也有 Public allow。唯一 ADB server 是 platform-tools 37.0.1，5037、密钥和
  LIBADBMDNS 均正常；Codex 沙箱出站阻断规则绑定另一 SID，不作用于 Lenovo/ADB。
- 电脑能访问多个 `192.168.1.x` 局域网邻居。ADB 日志显示今天曾真实发现
  `adb-741da30b0920-cvuER5`/`(2)`，之后才 TLS 断开，进一步证明本机 ADB/mDNS 栈可用。
  按官方建议重启一次 ADB 后 server 健康，但当前手机不再广播。
- `享学` 同时广播 4 个不同 BSSID（2.4G ch1、5G ch36、两个5G ch44）；电脑连接
  `fa:4c:da:e4:45:6c`。同名 SSID 并不保证同 AP/同二层网络，最符合手机地址多次跨
  `192.168.1/2/3/110` 网段和 mDNS 间歇消失的现象。Intel WLAN 还配置为漫游主动性中等、
  无首选频带和自动连接；系统事件确有多次断开后自动重新关联，但不含所选 BSSID，故只将
  其记为电脑侧跨 AP 风险条件。临时 `/32` 直连路由测试因无管理员权限被 Windows 拒绝，
  未留下网络改动。
- 当前故障时间线已闭环：ADB `04:03:34` 仍看到手机 mDNS；电脑 WLAN `04:04:46` 断开，
  `04:04:51` 自动重连同名 `享学` 并在同一时间取得新 DHCP 租约 `192.168.1.118/24`；
  重连前电脑已核验为 `192.168.3.217`。所以这次手机仍为 `192.168.3.220`、电脑变成
  `192.168.1.118`，直接触发点是电脑在同名多 BSSID 网络中的自动重新关联，不是 Clash。
- 当前 8793 PID=`36188` 健康 paused、scheduler=false，本轮无扫描和任务消耗。电脑侧
  没有发现需关闭 Clash、关闭防火墙或重装 ADB 的故障；恢复条件是确认手机与电脑连接同一
  BSSID/二层广播域，或临时共同连接一个确定的单 AP/热点。

### 2026-08-11 电脑已切回手机所在 AP；当前只等手机接电

- 经一次 UAC 受控 WLAN 重新关联，电脑从 BSSID `fa:4c:da:e4:45:6c` / `192.168.1.118`
  切换到同名 `享学` 的 BSSID `02:d5:61:47:30:b2` / `192.168.3.217` / gateway
  `192.168.3.1`。临时频带偏好已恢复为“无首选”；为减少24H期间再漫游，把 Intel
  `RoamAggressiveness` 从原值2（中等）调为0（最低），24H结束后须恢复2。
- 手机 `192.168.3.220` 随即 ARP Reachable，mDNS 当前广播 stable service `(2)` at
  `:40295` 与原 service at `:41183`；ADB 唯一选中 `M2010J19SC/lime`。这已用真实 A/B
  证据确认根因是电脑自动关联到同名不同 DHCP 域 AP，不是手机 IP 或 Clash。
- 设备身份、调试权限、亮屏解锁、XHS 安装、Unicode helper 切换与搜狗恢复均通过；DB
  quick_check=ok、running=0、lease=0，8793 PID `36188` healthy paused、risk=null、
  scheduler=false。
- 当前唯一硬停止：手机 `AC/USB/Wireless powered=false`、status=3 放电、battery=82%。
  未领取任务、未启动 scheduler。用户只需给手机接上稳定充电电源；接电后总控直接复核
  charging，安全启动当前未运行的 XHS，再恢复项目内置保守24H scheduler。

### 2026-08-11 接电后手机无线调试监听关闭，电脑/AP 连接仍正常

- 用户已接电，但随后 ADB transport/mDNS 消失。电脑仍在目标 BSSID
  `02:d5:61:47:30:b2`、`192.168.3.217`；手机 `192.168.3.220` Ping/ARP 正常，说明不是
  再次跨 AP。旧 `40295/41183` 均10061拒绝，连续20秒无 mDNS，属于手机无线调试监听关闭。
- 8793 PID `36188` 继续 paused、risk=null、scheduler=false；没有领取任务。用户只需在
  Redmi 上关闭再打开“无线调试”并保持页面，无需再找 BSSID/IP。mDNS 恢复后总控自动选中
  stable service，先验证接电，再恢复内置24H scheduler。

### 2026-08-11 成功轮已改为零等待；详情误判修复已加载，当前等待同网 ADB

- scheduler run `monitor-c8b5f1a49b1d` 已正确完成关键词“话术”的 Unicode 输入/精确
  读回、搜索结果和商品卡点击，并进入正常 `GoodsDetailActivityV2`。旧 ingest 只看 OCR，
  与 probe 的 Activity+严格 UI fallback 不一致，把正常详情误判 unknown；helper 先结束
  task 后 monitor 再检查 lease，又把 `task_not_running` 误报成 lease 风险。当前 risk
  reason 仍精确保留为
  `lease safety blocked at after_detail_capture_and_metrics_ocr: task_not_running`，不能在
  ADB 未恢复时清除。task114=`needs_manual_detail attempts=1/3`。
- 已统一页面证据分类并让风险/禁止信号优先；required page 不匹配时在 DB 写入前拒绝；
  monitor 持有任务状态并在处置 disposition 前先做真实 lease checkpoint。相关真实
  XML/OCR、危险遮罩、IME/query 与 lease 回归已覆盖。
- 用户明确要求成功采集后直接下一轮。内置 scheduler 已从固定等待改为：成功且完整采到
  商品后 `0` 秒立即下一轮；无可运行关键词、busy 或零采集才60秒退避；异常仍有限指数
  退避，blocked/risk 仍硬停。关键词自身3600秒 cooldown 保留，只防止同词连续轰击；有
  其他批准关键词时会立即轮转。每轮仍1关键词/1商品，`note_evidence=false`。
- 线程行为定向 `24 passed`，最新完整回归 `811 passed, 3 skipped in 66.75s`。备份
  `data/backups/before-immediate-round-reload-20260811T143620Z.sqlite3`，大小2019328，
  SHA-256=`91410dbd4b0acb22cde48adfb90562fe2d316fb9e6c85035e966a0f1e3f1601d`；
  主库与备份 quick_check=ok。只重载8793并健康验证，实际运行配置已读回
  `interval_seconds=0`、`idle_interval_seconds=60`、desired=paused、scheduler=false、
  `note_evidence=false`。
- 当前电脑不再位于此前目标网络：SSID=`xiongxiong_5G_Wi-Fi5`、
  BSSID=`18:3c:b7:ff:3e:9a`、IPv4=`192.168.2.178/24`、gateway=`192.168.2.1`；原“享学”
  当前完全不在可见 Wi-Fi 列表，ADB devices/mDNS 为空。不要关闭当前唯一可用 Wi-Fi 或
  盲清风险。先让 Redmi 与电脑进入同一可见 Wi-Fi并重新打开无线调试；恢复后依次做唯一
  设备/充电/IME/DB预检，按上述精确风险文本调用现有 risk-resume，验收 task114 完整成功，
  再以该成功轮作为新24H连续窗口起点。不得用测试通过冒充已开始24H运行。
- 补充最终网络证据：旧手机地址 `192.168.2.238` 当前已可 Ping、ARP reachable，MAC
  `DC-B7-2E-38-9C-24`，所以两端现在其实已同网；历史配对端口和5555全部10061拒绝、
  mDNS为空、USB无Android transport，唯一剩余门槛是手机系统重新开启“无线调试”。
  用户无需再切 Wi-Fi；打开后保持该页面，优先等待 stable mDNS 自动恢复。
- 2026-08-12 用户确认开启后，手机 `192.168.2.238` 仍可 Ping/ARP，但重启本机 ADB 并
  连续约20秒检查仍没有 `_adb-tls-connect` 广播或 device。8793 隔夜消失后已仅用项目
  脚本恢复健康；DB quick_check=ok、running=0、lease=0，task114 attempts仍为1/3，
  scheduler未启动。需用户发送无线调试主页面当前“IP 地址和端口”（不要发送配对码页
  端口），随后使用既有配对密钥精确 connect；不得扫描端口。

### 2026-08-14 当前交接：OCR P0 连续复现，禁止用旧8793继续采集

- 当前真实状态：8793 PID=`17048`，desired=`paused`、scheduler=false、risk reason 为
  首页 OCR 60秒超时，running task=0、lease=0、DB quick_check=ok。唯一 ADB stable serial
  在线，mDNS=`192.168.1.119:37653`；Redmi AC供电、battery=100、XHS PID=`16882`，
  前台为正常 `IndexActivityV2` 首页，默认搜狗 IME 已恢复。不得触碰8765。
- run=`monitor-044c30ce7bec`：task133“指南”的相同详情截图先成功 OCR 30 行，数秒后正式
  capture 重复冷启动 OCR 超时并裸穿透成 HTTP 500；task133 被错误耗尽为
  `needs_manual_detail attempts=3/3`。相同字节 SHA-256=
  `52C7EBB32CCA152CB2E5A9826BD0CD0A0319059C409651457A6C0FD6E9F686DB`。
- run=`monitor-628308c4c3c6`：正常首页截图再次 OCR 超时，证明不是商品图触发。设备与
  Unicode/IME 预检全绿、无验证码/登录/风控/ANR/黑屏；但旧流程把 task25“教招题库”
  写成 `risk_stopped attempts=1/3`，虽然接口报告 `processed_tasks=0`。证据目录为
  `data/probes/monitor-628308c4c3c6-probe-start/`。
- 本轮生产备份为
  `data/backups/before-task25-controlled-20260814T061958-0700.sqlite3`，源库/备份
  quick_check=ok，SHA-256=
  `89CC4D81512B092F4893B3B43DA6EBC22BCD3BC36CED9088D9BAAB191D7B61B3`。
- 当前两个离线子任务分别独占 OCR 核心和 ingest/workflow/monitor/db 超时语义；它们不得
  访问真实设备、生产库、服务或端口。总控独占真实状态。旧8793不得再跑下一任务。
- 接手顺序：等待两个子任务稳定交付 -> 总控检查实际文件并运行定向/完整测试 -> 新生产
  备份 -> 仅重载8793 -> 精确返还 task133/task25 的基础设施错误 attempt 并记录审计 ->
  连续真机短轮 -> 全绿后启动内置 scheduler 的新24H观察窗口。不得用离线测试或短轮冒充
  已完成24H。

### 2026-08-15 当前交接：修复已部署，等待手机重新开启无线调试

- 用户最新电量契约已加载：无需外接电源；电量严格 `>30%` 可采集，`<=30%` 或无法读取
  在领取前hard fail。31/100未充电通过，30/29失败。外接电源状态仅作信息。
- OCR核心现为受监管长寿命单worker、模型复用、同字节有界缓存与分阶段诊断；业务链使用
  严格结构化timeout契约，普通异常文本不能返还attempt；monitor/task双lease有效才允许
  返还，竞争失败结构化hard stop且不二次处置。合并定向90 passed、真实双图smoke 1 passed、
  唯一完整回归=`862 passed, 4 skipped in 67.39s`。
- 生产备份：`data/backups/before-ocr-battery-reload-20260814T235714-0700.sqlite3`，
  size=2281472，SHA-256=`C24B2F7677252E22C38EC0C75EED4AF6C7C4D4742C9047EADC1F92AAC6251480`；
  源库/备份quick_check均ok。首次修复事务仅因管道中文编码前置断言不匹配而在任何UPDATE前
  回滚；改用Unicode escape后成功。
- 历史修复run=`maintenance-ocr-refund-20260815T065824Z`：task25“教招题库”已变为
  `pending attempts=0/3`；task133“指南”已变为`pending attempts=2/3`；两条审计事件ID
  1132/1133。仅目标行status/attempts/updated_at变化，其他任务、monitor、lease、task_result
  不变；DB quick_check=ok、running=0、lease=0。
- 旧8793 PID17048已由项目脚本停止；新listener PID=`58296`，health_check三个端点均200。
  当前desired=paused、risk仍为旧首页OCR reason、scheduler=false/thread_alive=false，未抢跑。
- 当前唯一外部阻塞：手机ADB stable serial已消失，mDNS为空；最近已知
  `192.168.1.119:37653`明确10061拒绝，不能盲扫端口。需要在Redmi开发者选项关闭再打开
  “无线调试”并保持该页。设备恢复后依次：真实验证100%未充电preflight ready -> 直接数据库
  精确清旧risk但保持paused -> task25单轮 -> 连续额外短轮 -> 无P0后启动内置scheduler，
  该成功首轮才是新24H窗口起点。严禁8765。

### 2026-08-15 最新停止点：task25店铺页关注券透明层

- mDNS已恢复`192.168.1.119:39071`；真机未充电battery=91%，新device preflight真实
  `ready=true`。正式CLI OCR首页成功：11.9秒、`home_feed`、45行、无ANR/risk。
- 清除精确旧OCR risk但保持scheduler paused后，备份
  `before-task25-post-ocr-battery-20260815T000446-0700.sqlite3`，SHA-256=
  `496F3A6FB0C14CBDE6DA11564C0E0AC468695AC0118CD0AD4A673786B6524722`，quick_check=ok。
- run=`monitor-ebf25783933a`已正确到达详情并写product55/observation55；店铺入口点击后为
  `XhsReactTranslucentActivity + shop_product_list`，页面明确显示“青禾科技/粉丝2014”，同时
  有“送你一张优惠券/关注领取”弹层。安全门以
  `unrecognized_translucent_activity_after_shop_tap`停止；未点关注、优惠券、购买、购物车、
  商品卡或关闭X。截图=`data/probes/monitor-ebf25783933a-seller-after-25/current.png`。
- 当前task25=`pending attempts=1/3`，valid result=0；product55/observation55为部分采集。
  desired=paused、risk为上述reason、scheduler=false、running=0、lease=0、DB quick_check=ok。
  不得继续操作，先让用户查看当前截图；后续若修复，必须只围绕严格店铺页+明确关注券遮罩，
  禁止点击“关注领取”，并保留unknown/risk/ANR/PID变化硬停。

### 2026-08-15 最新交接：可见粉丝优先规则已部署，真机因黑屏停止

- 用户明确要求开独立子对话修复、主对话继续真实采集，并先提交开学季关键词候选供确认；
  未确认前不得写关键词池或队列，其余现有关键词仅后移、不删除。子对话ID=
  `01a00484-6a4f-7271-a7fb-4d57f0a344e5`。
- 修复已实现：严格 `shop_product_list/account_profile` 且既有risk/ANR/PID门禁通过时，先解析并
  持久化粉丝数，再使用最多两次系统Back恢复；不再因未枚举的优惠券/关注券文案挡住已清晰
  可见的粉丝证据。仍禁止点击优惠券、关注领取、关闭X、购买、加购等CTA；粉丝未显示仍写
  `not_displayed`并按非低粉。只改`seller_profile.py`和对应定向测试。
- 总控独立验收：定向=`21 passed`；唯一完整回归=`862 passed, 4 skipped in 57.62s`。备份
  `data/backups/before-visible-follower-coupon-reload-20260815T013242-0700.sqlite3`，
  size=2318336，SHA-256=`35C2670A40DF78FCAADEC2063547AAB379F1D6C1C23F9B6B7299B19A28872BA4`，
  源库/备份quick_check=ok。仅重载8793，当前project-owned PID=`43532`，健康端点全200；未碰8765。
- 重载后的正式CLI probe显示手机当前Activity=`NotificationShade`、截图全黑、
  page_kind=`unknown`，证据目录=`data/probes/probe-2026-08-15T01-33-44-07-00/`。这是新的真机
  硬停止；总控已按用户要求立即报告并停止，没有清旧risk、没有领取task25、没有唤醒/点击手机。
- 接手出口：用户手动亮屏解锁并打开小红书后，先probe确认安全正常页；再精确清除
  `unrecognized_translucent_activity_after_shop_tap`但保持scheduler paused，重跑task25。
  成功记录青禾科技粉丝2014（`low_follower_qualified=false`）并形成valid task_result后，继续
  额外短轮。用户确认开学季词后以高priority加入批准任务，其余任务保留低优先级；无P0才启动
  内置scheduler的新24H观察窗口。

### 2026-08-15 最新交接：无链接历史测试商品已清理，链接采集仍有P0缺口

- 按用户要求，精确删除`share_url` 与 `direct_url` 同时为空的25个历史测试商品；未删除
  已有其中一种链接的商品。商品总数43->18，删除后双空=0，search_tasks=102不变，
  foreign_key_check=0，quick_check=ok。从属删除：observations31、candidate_assessments48、
  task_results13、search_result_evidence17、note_observations6、note_evidence1；保留运行审计，
  49条run_events的已删product/observation引用置空。未删除证据文件。
- 可恢复备份=`data/backups/before-delete-linkless-products-20260815T014643-0700.sqlite3`，size=2318336，
  SHA-256=`425AEA702A30DB81855530491B4CDCCAFB6CD21E939028C24716F114462FF7C3`，源库/备份
  quick_check=ok。维护run=`maintenance-delete-linkless-products-20260815T084643Z`。本轮未操作手机、
  未重载8793、未触碰8765。
- 删除后18条链接组合：两种都有=4，仅share_url=5，仅direct_url=9，两种都无=0。
  控制台只用`share_url`决定标题是否可点，所以9条direct-only仍显示“链接待采集”；它们不是
  完全无链接，故本轮保留。
- 当前链接采集不得称“完善”：2026-08-09至08-15的13次真机链接阶段为11次direct-only、
  2次全跳过、share_url成功0次。`capture_product_share_url()`点击“复制链接”后只轮询
  Windows剪贴板，没有真机Android剪贴板回传通道；而Activity intent可提取
  `xhsdiscover://goods_detail/...`，因此现行结果通常是direct-only。最新product55已明确记录
  `share_url=null`与`share_url_gap=copied link did not reach Windows clipboard`。
- 当前8793实时仍为products=18、desired=paused、scheduler=false，原risk reason精确保留；
  手机仍处于上次`NotificationShade + black + unknown`硬停后的人工恢复门槛。本轮没有清risk或领取任务。
- 下一P0：实现不依赖Windows剪贴板的安全share_url回传，保留官方域名白名单、旧剪贴板
  防误采和商品ID一致性验证；随后用3–5次真机受控轮验收两种链接同时存在、控制台可打开、
  销量跟踪门槛通过。在此前只能称“商品直达身份基本可用”，不能称链接采集已完善。

### 2026-08-15 最新交接：direct_url主链接契约已修复并加载8793

- 用户纠正业务口径：经白名单和商品身份校验的`direct_url`就是核心商品链接；小红书无需另找网页
  商品页，`share_url`仅为可选分享短链。此前“必须双链才完整”的说法与实现均已作废。
- 已完成实现：合法direct_url在链接阶段直接成功，不再打开分享面板或等待Windows剪贴板；
  dashboard输出direct_url；控制台优先用direct_url生成标题和“打开主链接”，仅无direct_url时回退
  share_url；两者均无才标“链接待采集”；销量关注只要求合法direct_url。
- 关联回归=`113 passed`；唯一完整回归=`882 passed, 4 skipped in 60.17s`。完整回归中唯一初始红灯
  是旧测试仍断言只能使用share_url，已按新契约更新后全绿，没有放宽生产白名单或身份安全门。
- 上线前DB为desired=paused、scheduler=false、risk=null、running=0、task lease=0、run lease=0、
  quick_check=ok。备份=`data/backups/before-direct-link-ui-reload-20260815T103040Z.sqlite3`，
  size=2330624，SHA-256=`f8203e07cd58e1bb5bdd0dea23a26dd4bebb7d73578889352052f03f33931bd0`，
  源库/备份quick_check均ok。
- 只用项目脚本重载8793，当前listener PID=`45544`，health_check三个端点均200；未操作手机、未启动
  scheduler。真实浏览器刷新后，product56标题为可点击`A`，href精确为
  `xhsdiscover://goods_detail/689ce6b9b7465e0001fde28c`，同行显示“主链接已采集 / 打开主链接 / 完整采集”。
- 当前状态保持desired=paused、scheduler=false、risk=null。本批链接UI修复已经完成；如继续真实采集，
  应另起受控轮并重新做设备预检，不能把本次部署验收计作24H运行。

### 2026-08-15 最新交接：“开学第一课”新增product58，店名解析仍有缺口

- 用户要求追加1个商品。task137/rank1安全完成但重复已有product56，仅新增观察；随后task138明确
  选择搜索结果rank2，run=`monitor-26845cb66dbe`成功新增product58、observation58和valid task_result32。
- product58标题为“初中【开学第一课/最后一课】ppt送发言稿（含初一初…”，到手价159、销量1699，
  direct_url=`xhsdiscover://goods_detail/6a16bbdccfe575000168a1d2`；店铺页粉丝2637，非低粉。
- 已知缺口：店铺OCR明确显示“爱做PPT的小熊猫”，解析器却把“★★★★★4.8”误作author_name/shop_name。
  商品主体与粉丝证据有效，但店名字段不正确；后续必须修解析器并回填58，不能用本轮冒充全字段无误。
- 全程无risk/ANR/unknown，结束后desired=paused、scheduler=false、risk=null、running=0、lease=0、
  quick_check=ok。两份运行前备份及stdin基础设施attempt返还审计详见TASK_BOARD section93。

### 2026-08-15 最新交接：商品链接双入口已通过真机验收

- 新契约已经部署：`share_url`只供“电脑打开”；`direct_url`不再作为Chrome href，而由8793的
  “手机打开”接口从生产DB按product_id读取、严格校验后发送给唯一在线真机。商品标题为普通文本，
  两类链接分别显示可用或禁用状态。
- 离线证据：子任务完整回归=`896 passed, 4 skipped in 59.10s`；总控独立聚焦回归=
  `74 passed in 2.01s`。备份=`data/backups/before-dual-link-real-acceptance-20260815T124119Z.sqlite3`，
  size=`2330624`，SHA-256=`7b5a765c0b7b93aa8b42b140e90cfd7203636b6632fdba5622cba49450f6128d`，
  源库/备份quick_check均ok。仅重载8793，验收结束时project-owned listener PID=`16920`，健康端点全200；
  严禁触碰的8765未操作。
- 真实UI与手机证据：product56标题实际为无href的`SPAN`；因share_url为空，“暂无电脑链接”禁用，
  “手机打开”启用。点击后真机从product58的
  `xhsdiscover://goods_detail/6a16bbdccfe575000168a1d2`切换到product56的
  `xhsdiscover://goods_detail/689ce6b9b7465e0001fde28c`，前台Activity为`GoodsDetailActivityV2`。
  随后只读probe=`data/probes/probe-2026-08-15T05-46-43-07-00`确认`product_detail`、标题及销量3726匹配，
  无ANR/风控。
- 验收后安全状态：desired=paused、scheduler=false、risk=null、running task=0、task lease=0、
  run lease=0、生产DB quick_check=ok。本次仅验收打开链接功能，没有启动新采集或24H调度。

### 2026-08-15 最新交接：链接操作列已单行左对齐

- `workbench_ui.py`已将操作列扩至120px，操作项纵向排列并统一左对齐，文字强制单行不换行；
  “暂无电脑链接/暂无手机链接”不会再把“接”折到下一行。界面定向测试=`48 passed in 0.46s`。
- 仅重载8793，验收时project-owned listener PID=`57316`，健康端点全200；真实浏览器计算样式确认
  两个“暂无…链接”标签均为72x22px单行、左对齐，所有操作项x坐标一致。未改DB、链接业务或手机行为，
  未触碰8765。

### 2026-08-15 最新交接：product58店铺名已按顶部布局修复并上线

- 根因已修正：旧逻辑从整页OCR猜`author_name`，把店铺页第二行评分“★★★★★4.8”误写成店名。
  现在`shop_product_list`只从店铺页顶部限定布局读取唯一TextView店名，并显式拒绝评分、已售、
  粉丝、好评率、客服、优惠券等指标；顶部不唯一或不可靠时返回未识别，不再猜测。
- 真实回放证据：`data/probes/monitor-26845cb66dbe-seller-after-138/window.xml`顶部节点为
  “爱做PPT的小熊猫🐼”，解析后规范化为“爱做PPT的小熊猫”；同一probe粉丝2637保持正确。
  定向回归=`45 passed`，当前唯一完整回归=`900 passed, 4 skipped in 76.71s`。
- 生产修正前备份=`data/backups/before-product58-shop-name-fix-20260815T124543Z.sqlite3`，
  size=`2330624`，SHA-256=`7b5a765c0b7b93aa8b42b140e90cfd7203636b6632fdba5622cba49450f6128d`，
  源库/备份quick_check均ok。单事务仅更正product58及seller observation19的店名并写审计，粉丝2637未变。
- 只用项目脚本重载8793，当前project-owned listener PID=`16920`，三个健康端点均200；未触碰8765。
  真实浏览器刷新验收：product58显示“爱做PPT的小熊猫”、粉丝2637、完整采集、暂无电脑链接、手机打开，
  不再显示“★★★★★4.8”。未点击手机打开、未操作真机、未启动采集。
- 当前安全状态：desired=paused、scheduler=false、risk=null、running task=0、task lease=0、run lease=0、
  DB quick_check=ok。下一步只有在用户明确要求继续真机采集或启动scheduler时才进入真实运行。

### 2026-08-15 新总控只读接手：ADB离线，生产库存在1条外键异常

- 8793当前由本项目PID=`57316`监听，三个健康端点均为200；未访问8765。实时状态为
  desired=paused、scheduler=false、next=null、risk/block/skip=null、running task=0、
  task lease=0、run lease=0。API计数：pending=65、products=20、observations=27、
  note_observations=13、正式候选=2。
- 生产库`quick_check=ok`，但`foreign_key_check`返回1条：`run_events.id=1235`、
  run=`maintenance-product58-shop-name-layout-fix`的`observation_id=19`违反到`observations`的外键。
  事件描述的是product58卖家证据，疑似误把`note_observations.id=19`写入商品观察外键字段。
  本轮仅只读定位，未修改生产库。
- 当前ADB `devices`无在线设备，mDNS为空，因此本轮不能确认真机实时电量、屏幕/解锁、前台Activity、
  小红书PID或默认输入法；未扫端口、未操作手机、未触发采集。
- 下一步必须先取得用户执行授权：精确修复该单条外键异常并复核完整性，同时让Redmi重新开启无线调试；
  ADB恢复后再做设备预检、优惠券叉号真机成功事件和一个单商品短轮。全部通过前不得启动scheduler或
  将任何短轮/测试冒充新的24小时连续观察。

### 2026-08-15 Redmi无线ADB已恢复

- 用户更正主页面地址为`192.168.2.238:43289`后，总控仅对该地址精确连接，未扫描端口。
  ADB连接成功，唯一设备为`device`，model=`M2010J19SC`、device=`lime`，身份匹配指定Redmi。
- 本步没有运行完整设备预检或页面probe，没有操作小红书、生产库、任务或scheduler。
  下一P0仍为精确处理`run_events.id=1235`的单条外键异常；修复和复核后再进入真机预检、优惠券
  叉号真实成功事件与单商品短轮。

### 2026-08-15 最新交接：24H首窗已中断，当前“开学”单商品耗时139.910秒

- section97后的关键事实已收口：`run_events.id=1235`错误商品观察外键已精确置空并留下审计，
  DB恢复quick_check=ok、foreign_key_check=0；备份=
  `data/backups/before-fk-event1235-fix-20260815T210625-0700.sqlite3`，SHA-256=
  `4f6516c4f0e66881ab4e11112c8fdc1dfc0c1bc5b8679f05aff343de51a66493`。
- task25/run=`monitor-8fde389b02b2`已完成优惠券叉号真机验收：唯一视觉X单次点击成功，事件ID1257
  `seller_coupon_closed_by_unique_visual_x`；PID未变、店铺粉丝2018落库、valid result33，安全返回。
- 内置scheduler曾启动：首轮task139“食谱”/run=`monitor-a20690b60ba8`于21:19:55-07成功；随后
  task140因XML ParseError、task141因完整`dumpsys window`非零退出而连续失败，21:29:58-07暂停。
  原24H窗口只运行约10分钟，已作废，不能计作连续24小时。task140/141仍为pending attempts=1/3，
  尚未执行基础设施attempt返还。
- ADB窗口检查已改为`adb shell dumpsys window displays`、timeout15秒，相关定向47 passed；完整回归
  `901 passed, 4 skipped`，但耗时异常达到1:18:41，需作为性能风险保留。修复已加载8793，真实
  `probe-2026-08-15T22-56-16-07-00`成功返回安全search_results。
- 用户随后要求以“开学”采集1个商品并计时。task142首次run=`monitor-8829fbc057f6`用25.161秒暴露
  商品卡边界误排除，未点击商品。`find_product_cards`已窄修复当前首排XML从y=78开始的布局，同时
  保留价格/销量、可点击大卡、交易控件/直播排除门禁；相关测试30 passed，真实失败XML识别4卡。
- task142最终run=`monitor-2d23326c9024`从23:21:32.2127709-07到23:23:52.0502584-07，
  端到端`139.910秒`，processed=1、captured=1、无skip/block。valid task_result36，product63/
  observation63，direct_url=`xhsdiscover://goods_detail/6a532ea901c1af00012083af`，累计销量111；
  店铺“七七资料铺”、粉丝389。最终安全返回“开学”search_results，搜狗IME恢复，无ANR/风控。
- 需如实保留两个缺口：一次通用monitor在task142退避期自动领取task27，额外用130.191秒采集了
  product62，说明受控单任务缺少精确task-id绑定；product63标题误解析为“36页可编辑PPT+教案”且
  price为空，而详情证据显示完整“新初一七年级开学第一课...”标题和到手价98.9。二者均为P1，
  未修复前不得称精确任务选择与标题/价格字段全绿。
- 最终有效备份=`data/backups/after-timed-kaixue-single-20260815T232617-0700.sqlite3`，size=2330624，
  SHA-256=`9702f624d2d2aeee40624b196659c52368659738966fc319dbfa88ce5ed3ca71`，源库/备份
  quick_check均ok、foreign_key_check均0。首个带时区冒号的备份形成NTFS附加流，已保留但不作主要恢复点。
- 8793已仅用项目脚本重载，当前project-owned listener PID=48736，三个健康端点200；desired=paused、
  scheduler=false、risk=null、running=0、task lease=0、run lease=0，未触碰8765。下一主线应先处理
  task140/141基础设施attempt与上述两个P1，再决定是否重新启动新的24小时连续窗口。

## 2026-08-17 坐标字段子任务已分派，主控已恢复连续采集

- 用户明确要求把“页面→固定坐标区域→字段”交给子智能体，同时主控继续采集。统一项目板section 99已建立；唯一子任务`LAYOUT-ROI-01`仅允许离线修改`layout_fields.py/ingest.py/probe.py/seller_profile.py`及定向测试，禁止生产DB、ADB、手机、8793、8765、scheduler、完整回归与外部账号动作。主控仍是真实状态唯一所有者，子任务完成并验收前不重载8793。
- 恢复前只读基线：8793为project-owned PID=48736且健康；desired=paused、scheduler=false、risk/block/skip=null；生产库quick_check=ok、foreign_key_check=0、running=0、task lease=0、run lease=0；唯一ADB设备为M2010J19SC/lime。
- 2026-08-17T01:23:40-07:00通过已加载8793的`POST /api/monitor/resume`恢复项目内scheduler。首轮run=`monitor-90b2ae3e2109`完成设备/Unicode预检（电量50%）及从Android设置页到安全商品详情页的恢复，无ANR/风控，但task146“表格”在正式完成前回队为pending attempts=1/3，未形成商品结果。
- 第二轮run=`monitor-cf245e943aab`完成首个真实成功：task147“题库”completed attempts=1/3，valid task_result37，product55新增observation64、累计销量464；搜索、详情、direct_url、店铺粉丝、唯一视觉叉号关闭与返回搜索结果全部走通，risk/block/skip为空，scheduler连续失败数归零。结束时间为2026-08-17T01:29:05-07:00。
- scheduler成功后立即进入run=`monitor-0c8ff29beabe`并继续创建task148；当前连续采集窗口的首个成功基准点记为2026-08-17T01:29:05-07:00。只能称窗口已启动并持续，尚未完成24小时。不得为了子任务部署而中断当前运行；待子任务代码验收和全量回归通过后，再选择安全暂停点、备份生产库、只重载8793并做真机字段验收。
- 运行随后被真实ADB掉线安全中断：本轮实际transport=`192.168.3.245:39325`先通过预检，之后变为offline且mDNS为空；run=`monitor-1a42d8b87247`在任务领取前以`device_selection`硬停，task149仍pending attempts=0/3，desired=paused、scheduler=false。只对该精确地址尝试一次重连仍为offline，未扫描任何端口。恢复需要手机“无线调试”主页面当前IP和端口，或人工关开一次无线调试；不得在此之前恢复scheduler。
- 用户随后提供当前地址`192.168.3.245:39325`，身份复核为M2010J19SC/lime并曾恢复scheduler；之后用户纠正关键词主线，指出待搜索仍为历史泛词。总控已再次暂停。生产库只存在已完成的`开学`和`开学第一课`，此前section 88的开学候选清单未持久化，通用100根词仍在自动轮转。当前先给用户候选清单确认，未改队列优先级；确认后把开学词置顶、其他任务后移不删除，并收窄连续发现根词。
- 暂停时最新risk=`seller capture requires product_detail, got unknown`，run=`monitor-586f102ad961`。即使关键词确认并重排，也必须先复核该真实页面风险再恢复scheduler。坐标字段子任务已交付、报告定向52 passed，但总控尚未审查diff、跑唯一完整回归、重载8793或真机验收，状态只能记为待验收。
## 2026-08-17 最新交接：30个教师开学场景词已置顶，首词短轮完成但标题ROI真实验收未通过

- 子智能体已将30个教师开学场景词写入生产队列为task153–182、priority1080→1051，首条为`开学第一课PPT`；pending 73→103，其他pending最高priority=50且全部在后。连续发现根词配置保持严格100项唯一（新30+历史70）；定向21 passed，当前唯一完整回归`908 passed, 4 skipped`。队列前备份`data/backups/xhs_scout_OPENING_QUEUE_01_20260817T021152.sqlite3`，SHA-256=`3284f143d3e443253aedfa6d571f0aca26e34557e60c6302907b92438bb51919`；审计event1450。
- 8793已加载坐标字段实现，PID=`69968`、健康端点全200；未触碰8765。安全probe=`data/probes/probe-2026-08-17T02-22-09-07-00`确认真机`192.168.3.245:39325`、M2010J19SC/lime、search_results、无ANR/风控。恢复时发现连续发现不按priority领队列，而按持久化cursor轮转；旧cursor=14误领task167`学生信息登记表`。主控立即暂停，在安全检查点结束该轮，保留已产生的product67证据，但将该基础设施误耗的task167 attempt退回0并清空错误，cursor归零。修正前备份`data/backups/before-opening-cursor-correction-20260817T022700.sqlite3`，SHA-256=`854f106520b2453232012a503161ec4f559361f213382ddd81f24c248939f715`，源库/备份quick_check=ok、FK=0；审计event1470。
- 正式首词使用`task_id=153 + expected_keyword=开学第一课PPT`双重绑定，run=`monitor-1b08b81db4fa`从02:27:54到02:31:04，共190秒，completed attempts=1；新增product68/observation68/valid task_result。可靠字段：到手价12.9、累计已售150、店铺`糖果老师的课件`、粉丝1256、direct_url=`xhsdiscover://goods_detail/6a70a9e2f3369d0001248e2e`。灰色指标条未定位，明确缺失未猜数。
- 真实验收失败项：product68真正标题为`开学第一课/收心立规矩主题班会PPT+教案+逐字稿`，但当前title ROI下移并误取`近期店铺销量TOP1付款后自动发货`。因此product68标题不合格，不能据此恢复批量采集。`LAYOUT-ROI-02`已交回子智能体，仅允许用真实截图修正标题框与定向测试，禁止DB/ADB/8793/8765/服务。当前desired=paused、scheduler=false、risk=null、running=0；修复、完整回归、只重载8793和真机单件复验完成前不得继续第二词。
- 当前规则仍为每关键词1件、默认搜索结果rank1；完成后返回搜索结果再切换下一关键词，不会退出小红书。代码支持rank2/rank3及每词最多3件，但是否将30词扩大为90件仍待用户决定，未获确认不得扩量。
- 02:45部署操作中总控第一次调用停止脚本后，遗漏`start_workbench.ps1 -Execute`的执行参数，造成8793短暂停机；第二次启动被用户中断后立即只恢复服务，未恢复采集。当前8793 PID=`35024`、健康检查通过；8765仍为PID=`21776`且未触碰；desired=paused、scheduler=false、risk=null、running=0。不得把此前任何短轮或修复称为24小时连续运行完成。
- 用户最终确认商品详情标题按两种已知页面类型固定坐标：新详情页先做几何类型匹配，再只读该类型的标题框和价格框；不能唯一匹配则报异常。当前实现：extended标题ROI=`[0.02,0.825,0.98,0.90]`，compact标题ROI=`[0.02,0.78,0.98,0.82]`，价格ROI两型均为`[0.18,0.685,0.55,0.75]`。主控直接回放生产证据obs63/68：分别识别完整标题、价格98.9/12.9、店铺入口，状态均ok；相邻37 passed，当前完整回归910 passed/4 skipped。现有product68落库标题仍是修复前错误值，后续若要修正历史数据必须另做有备份的精确回填，不能把回放成功冒充历史记录已更正。

## 2026-08-17 最新交接：每个关键词改为连续采集前5个商品

- 用户已把采集深度从每词1件改为每词5件。实现不是重复采5次rank1：连续发现调度会对同一个关键词依次产生rank1、2、3、4、5，只有第5件成功形成有效采集结果后才移动到下一个关键词；第5件失败或被阻断时cursor不前进。
- 修复了旧选卡逻辑的真实重复风险：此前请求rank5但页面只识别3张卡时会通过取模误选rank2。现在超出已观察范围直接返回空；程序会在搜索结果页最多向下滚动2次，合并并按卡片证据去重后再选择精确rank。搜索页类型或顶部关键词变化、精确rank仍不存在时一律fail closed，不猜测、不回绕。
- 代码涉及`src/xhs_scout/continuous_discovery.py`、`src/xhs_scout/scheduler.py`、`src/xhs_scout/monitor.py`及对应测试。定向52 passed；修复旧soak夹具兼容后相邻34 passed；唯一完整回归`920 passed, 4 skipped`，`py_compile`通过。
- 部署前备份`data/backups/before-opening-depth5-20260817T045957-0700.sqlite3`，SHA-256=`EF5B38BE4F3AAD2C7608646EC8195BE984325B8EC4CF6B63632B66D01D677C51`；源库及备份quick_check=ok，源库foreign_key_check=0。随后只重载项目8793使代码生效；desired=paused、scheduler=false、risk=null，未启动采集、未操作ADB/手机、未触碰8765。
- 尚未完成的真实目标：还没有执行“开学第一课PPT”的首次rank2–5真机短轮，因此当前只能称代码已实现、已加载、离线回归通过，不能称5件真机验收完成，更不能称24小时窗口已恢复。下一步必须先安全复核当前页面/设备，再由总控串行恢复采集。

## 2026-08-17 最新运行状态：已恢复真实采集

- 用户提供新的无线调试地址`192.168.1.119:39325`，精确连接成功。8793已执行普通resume，当前desired=`running`、scheduler=`true`、risk/block=`null`；8765未触碰。
- 首轮run=`monitor-eceec6274ab2`已启动并正确领取task183。设备身份M2010J19SC/lime通过，limits为expected_keyword=`开学第一课PPT`、search_result_rank=2、search_card_scan_limit=5；event1500确认关键词读取校验通过并已提交。
- 这表示每词5件规则已经进入真实运行，当前正在采首词的第2件；尚未把rank2记为成功，最终以有效task result和search_result_evidence为准。验证码、风控、ANR、未知页面、设备掉线、DB锁或任务错位继续按既有规则硬停。

## 2026-08-17 最终更正：24小时采集未启动，交接新总控

- 上一节只是启动瞬间，不能作为运行成功。run=`monitor-eceec6274ab2`在05:23:50提交`开学第一课PPT`后，没有点击商品；05:24:09因`OcrWorkerError: image file is truncated`异常结束，captured=0。截图大小738422字节但PNG尾部不完整，worker停在`image_load_failed`。精确诊断证据为`data/probes/monitor-eceec6274ab2-probe-search-results/.ocr-diagnostics/ocr-worker-error-20260817T122409.320827Z-3e5a9134c962-9ba9a7399fec.json`。
- scheduler自动重试run=`monitor-65be63bd61e5`，05:25:31因`device preflight failed: device_selection`安全暂停。当前真实状态：8793 PID=39008且HTTP正常；desired=paused、scheduler=false、risk=null、block为上述device_selection；8765为其他项目PID=21776，严禁触碰。ADB最新列表为空。
- 数据状态：task183=`开学第一课PPT`、rank2，status=pending、attempts=1/3、last_error=`monitor run ended before task completion`，无run owner/lease；running task=0、run lease=0。该关键词只有rank1的有效evidence52（task153/product68/observation68），rank2没有结果。24小时窗口从未形成有效起点。
- 接手前必须知道的额外代码缺陷：`src/xhs_scout/monitor.py`中`_locate_ranked_product_card`的滚动分支调用`probe_current_page(settings, label=...)`，但真实接口是`probe_current_page(settings, device, run_id=...)`；rank4/5需要滚动时会直接报参数错误。此前测试用宽松monkeypatch没有暴露它。
- 新总控不要通读本文件或全部代码。直接读取根目录`CLAUDE_TAKEOVER_PROMPT.md`，再按其中限定的少量文件和行段接手。

## 2026-08-18 三个P0已修复并通过离线验收，8793已重载，真机验收仍未开始

- 本轮为新总控接手。上一轮总控在被中断前已经把三个P0的代码和测试写完，但没有验收、没有跑完整回归、也没有更新本文件和任务板；本节是对该批修复的独立复核结果，不是新的实现。
- P0-A（截图被OCR读到半写PNG）已修复。`src/xhs_scout/emulator.py`的`AdbDevice.screenshot`现在先写同目录唯一临时文件`.{name}.{uuid}.tmp`，用PIL完整`image.load()`解码校验通过后才`os.replace`原子替换`current.png`；单次截断在`max_attempts=2`内有界重试，持续失败抛`ScreenshotCaptureError`而不是把坏文件交给OCR。
- P0-B（无线ADB不能稳定重连和选中唯一手机）已修复。新增`tests/test_monitor_device_selection.py`，4个用例分别覆盖：未配置型号时拒绝无范围兜底、忽略同一手机的过期offline IP而选在线mDNS serial、通过稳定`mdns_service`重连、mDNS为空时fail closed且不扫描端口。
- P0-C（rank4/5滚动分支调用签名错误）已修复。`monitor.py`的`_locate_ranked_product_card`滚动分支现为真实签名`probe_current_page(settings, device, run_id=f"{run_id}-probe-result-scroll-{n}")`，并接同一个device做`_guard_probe`。
- 唯一完整回归由本轮总控实跑：`929 passed, 4 skipped`（69.45s），较上一基线920多出的9项即三个P0的新增测试。定向复核`test_monitor_device_selection.py`/`test_monitor_search.py`/`test_emulator.py`/`test_probe.py`共33 passed；`test_layout_fields.py` 8 passed，其中product63真实回放判为extended（wide_box_count=0）、product68判为compact（wide_box_count=1），两者标题与价格98.9/12.9均正确，且明确断言不匹配`36页可编辑PPT+教案`、`￥129`、`近期店铺销量TOP1`、`付款后自动发货`等相邻干扰项。
- 重载前备份`data/backups/before-p0-fixes-reload-20260817T235740.sqlite3`，SHA-256=`35A7154F466496FEA44325C9EE6C6EEBA3C6530F046AF5921468F03AE8F5C4EC`，2,392,064字节；源库quick_check=ok、foreign_key_check=0，备份quick_check=ok、search_tasks=152行。备份走SQLite backup API，未复制正在使用的库文件。
- 只用`ops/start_workbench.ps1 -Execute`启动8793（此前一次事故正是漏了`-Execute`）。启动器PID=`33920`，实际监听子进程PID=`32252`，两者命令行均带本项目`--project-root`，确认project-owned。健康检查通过。8765仍为其他项目PID=`21200`（`-m uvicorn video_co...`），本轮完全未触碰。
- 重载后状态：`desired_state=paused`、`scheduler_running=false`、`risk_stop_reason=null`、`last_skip_reason=null`、`next_run_at=null`。`last_block_reason`仍显示`device preflight failed: device_selection`，这是上一轮run=`monitor-65be63bd61e5`遗留的历史值，不是本轮新增阻塞。
- 已确认连续发现的下一个领取目标为`task_id=183`、keyword=`开学第一课PPT`、`search_result_rank=2`、reason=`existing_allowed_task`、`allowed_keyword_count=100`。此前担心的task183 priority=50低于task153的1080并不构成错领风险：连续发现按持久化cursor与既有可用任务选取，不按priority排序。
- 用户已提供手机无线调试当前地址`192.168.1.119:38143`（端口较上次的39325已变化）。本轮按阶段3边界未执行任何ADB或手机操作，该地址尚未做身份复核。
- 附带清理：删除历史pytest临时产物`.tmp/`、`.test-tmp/`、`.pytest_tmp_cold_restart_fix/`、`.pytest_tmp_full_cold_restart_fix/`、`.pytest_cache/`、根目录空文件`datetime`及3处`__pycache__`，释放约300MB；新增`.gitignore`。两个0字节空目录`.pytest-tmp-crash-fix-20260802`和`.pytest-tmp-full-crash-fix-tests-20260802`为真实Access Denied，非提权无法删除，不影响运行。本目录仍不是Git仓库。
- 仍未完成，不得宣称完成：`开学第一课PPT`的rank2–5真机短轮一次都没跑过；三个P0的修复只有离线测试证据，没有真机证据；`product68`落库标题仍是修复前错值`近期店铺销量TOP1付款后自动发货`，真实标题`开学第一课/收心立规矩主题班会PPT+教案+逐字稿`尚未带备份回填；24小时窗口没有有效起点；Windows计划任务经`Get-ScheduledTask`确认一个都没安装。

### 2026-08-18 阶段4首次预检：task183仅剩1次，设备再次离线

- 用户明确授权以`192.168.1.119:38143`进入阶段4，只做`task183 / 开学第一课PPT / rank2`，rank2有效后才允许依次继续rank3、rank4、rank5；本次授权不包含24小时scheduler或Windows计划任务安装。
- 接手时发现阶段3之后另有一次真实run=`monitor-495aa66d4c90`于`2026-08-18T00:09:33-07:00`启动。该轮设备、IME和首页预检通过，但首页存在“继续编辑图文笔记吗？”弹窗，最终以`search product button not found`结束；task183被消耗为`pending attempts=2/3`，rank2仍无`task_result`或`search_result_evidence`。当前没有running task或run lease，8793保持`desired=paused`、`scheduler=false`、`risk=null`；`last_block_reason`为上述新阻塞。
- 05:00后对用户提供的精确地址执行一次连接，曾短暂得到`device`并确认身份`M2010J19SC/lime`，电量32%、未充电；同时可见同一手机的mDNS别名`adb-741da30b0920-cvuER5._adb-tls-connect._tcp`，不是第二台手机。随后IP别名迅速变为`offline`，mDNS广播也消失。
- 按既有规则只对精确地址执行一次`disconnect/connect`重连，不扫描端口；重连后`adb devices -l`与`adb mdns services`均为空。因此未恢复scheduler、未领取task183最后一次、未点击手机、未写生产业务数据、未触碰8765。
- 当前唯一出口：用户在Redmi“无线调试”主页面关闭后重新开启无线调试，保持该页面亮屏，并提供新的“IP地址和端口”。新地址到达后先确认唯一设备、型号、页面安全和电量`>30%`，再关闭草稿提示并只跑rank2。若电量降至30%或以下，必须先充电再继续。

## 2026-08-19 搜索词误判已按固定坐标方案离线修复

- 真实故障run=`monitor-1d7b46b56687`在定位`task184 / 开学第一课PPT / rank3`时触发`search result keyword changed while locating requested rank`。真实截图前后搜索框内容均为`开学第一课PPT`；误判来自Android无障碍XML在页面上滑后仍报告离屏商品节点，并把商品标题放到顶部坐标，旧逻辑因此把商品标题当成搜索词。
- 按用户确认的冷流程修改：搜索词只从1080x2340 Redmi截图OCR固定安全区`(120,100)-(820,200)`读取，且OCR文字中心点必须落在该框内、置信度至少0.80；XML文字、整页OCR文本和商品卡文字不再参与搜索词归属判断。
- 固定框内必须唯一得到一条文字，并与期望关键词去空白后完全相等；框内缺失、多条、低置信度或内容不同均fail closed，不做语义猜测。
- 两份真实故障样本`data/probes/monitor-1d7b46b56687-probe-start`与`data/probes/monitor-1d7b46b56687-probe-result-scroll-1`均回放得到`开学第一课PPT`，证明上滑前后搜索词不再被商品标题替换。
- 修改文件：`src/xhs_scout/monitor.py`、`tests/test_monitor_search.py`、`tests/test_workflow.py`。相邻定向测试`66 passed`，`py_compile`通过。
- 已使用项目自有`ops/stop_workbench.ps1 -Execute`与`ops/start_workbench.ps1 -Execute`重载8793；启动脚本报告健康，新监听PID=`55956`。8765仍为原PID=`14148`，未触碰。重载后desired=`paused`、scheduler=`false`、risk=`search result keyword changed while locating requested rank`，原风险锁完整保留；本轮未清风险、未操作ADB/手机、未写生产业务数据。下一步只剩受控rank3真机验收，成功后才能进入rank4/5或长期运行。

### 2026-08-19 rank3真机复验被新的搜索入口故障阻断

- 用户提供并授权使用`192.168.3.245:40527`。唯一设备身份`M2010J19SC/lime`、电量52%、屏幕解锁、无线调试“当前已连接”均通过；旧搜索词风险按原文确认清除后立即把desired重新设为paused，再通过`/api/monitor/run-once`精确绑定`task184 / 开学第一课PPT / rank3`，没有启动长期scheduler。
- run=`monitor-b334d6a229fa`未进入商品采集，最终`processed_tasks=0`、`captured_products=0`，阻塞=`query reset did not open search input: note_detail`。task184仍pending，但attempts由1/3变为2/3；下次不得直接重试消耗最后一次。
- 截图证明首页搜索入口实际已成功打开`search_input`，但输入框中残留旧词`小程序`。程序没有在当前搜索输入页点击右侧清除叉号，而是执行返回，回到了先前的“凡科小程序”笔记详情页；随后XML把整页错误识别成top-query-field，第二次又把详情页坐标`(828,150)`错误标成“全部删除”。
- 该第二次错误点击意外把“凡科小程序”账号从“关注”切换为“已关注”。这是本轮产生的外部副作用；总控已停下，没有擅自取消关注，需先向用户汇报并取得是否恢复原状态的明确确认。
- 当前desired=paused、scheduler=false、risk=null、last_block=`query reset did not open search input: note_detail`，8793健康，8765未触碰。下一步必须先讨论并修复“search_input残留词直接点固定清除叉号、禁止从note_detail继续重置、禁止整页top-query-field”三点，完成真实截图回归后再保护性处理task184最后一次机会。

### 2026-08-19 用户将手机放到搜索页后再次重跑rank3，输入校验失败

- 用户明确要求不处理误关注，已人工把手机放到搜索界面并要求直接重跑。重跑前probe=`probe-2026-08-19T04-30-07-07-00`确认`GlobalSearchActivity/search_input`、设备M2010J19SC、电量50%、无ANR/风控；输入框视觉文字为`小程序页面代做`。
- run=`monitor-c96e50b8b7af`仍精确绑定`task184 / 开学第一课PPT / rank3`，scheduler全程保持paused。Unicode输入流程在提交搜索前连续读取10次UI树，但`find_search_input_query_text`均返回None，故以`search input query mismatch before submit: expected='开学第一课PPT', actual=None`安全停止；0商品、0有效rank3证据。
- 结束后probe=`probe-2026-08-19T04-37-03-07-00`仍为search_input，截图固定框显示`小程序页面设计`而非目标词；UI树对应EditText却只暴露`text="搜索, "`。因此这不是仅有“读取不到但实际已输入”，而是目标词没有可靠写入，且截图OCR与无障碍树对输入框内容不一致。
- task184现为`needs_manual_detail`、attempts=3/3、last_error为上述输入校验失败；rank3仍为0件。当前desired=paused、scheduler=false、risk=null，未继续点击、未启动长期调度、未触碰8765。
- 继续前需要用户确认两个生产修复动作：把这两次明确的自动化基础设施失败从task184尝试次数中返还，使任务重新pending；修复search_input为“固定输入框坐标聚焦/清除/输入，截图OCR固定框确认目标词后才提交”，并保留XML为空时fail closed。未经确认不得直接改库或继续重试。

## 2026-08-19 本地视觉模型离线试验：3/3准确，但整图CPU推理约130秒

- 按用户授权仅在本机安装并离线评估，没有操作手机、ADB、生产DB、8793、8765、scheduler或外部账号。Ollama 0.32.13 安装在 `C:\Users\Lenovo\AppData\Local\Programs\Ollama`；模型目录持久化为 `D:\APP\Ollama\models`。
- 已成功下载 `qwen3-vl:4b-instruct-q4_K_M`。`ollama list` 与 `GET /api/tags` 均返回模型，API报告大小3,295,636,231字节、digest=`ee4b975b58c17ce268cd19d40db35d5edc64603035d2ffc1fee1968eb0947f7b`；D盘实际5个文件、3,295,625,769字节（约3.069GiB）。`C:\Users\Lenovo\.ollama\models` 是指向D盘目录的junction，不是C盘第二份模型。
- 使用三张既有真实商品详情整图、同一严格JSON提示离线测试：product63标题与到手价98.9正确；product68标题与到手价12.9正确；product71标题与价格54.9正确。三张均与人工基准逐字/数值一致，且前两张没有误取主图大字或原价。
- 真实耗时：冷启动138.472秒（load 9.181秒、视觉prompt 116.187秒）；热启动129.907秒与130.795秒（load仅0.378/0.350秒，视觉prompt仍118.659/120.881秒）。本机Ollama显示`100% CPU`，整图视觉编码是主要瓶颈。
- 结论：准确率基线通过，连续采集主链的速度门槛不通过。当前不得直接把模型放进“每件商品必调”路径，否则单件额外增加约130秒。若后续继续，只能先单独验证缩图/裁剪区域能否显著提速，或把模型限定为ROI/OCR异常时的低频兜底；两种方案都必须先取得用户确认并另做验收。

## 2026-08-20 本地视觉链已加载；rank4在模型调用前因搜索页误分类停止

- 用户接受耗时后，本机Qwen3-VL标题/价格识别已接入正式`ingest_image`持久化前路径：每商品一次调用，
  AI结果为标题/价格主值，ROI仅作证据；超时、服务不可用、JSON/类型/范围/缺字段异常均整件停止并禁止落库。
  定向13 passed、相邻101 passed、完整回归`953 passed, 4 skipped`。8793已加载，Ollama API正常；
  部署前备份`data/backups/before-vision-fields-integration-reload-20260820T040312-0700.sqlite3`，SHA-256=
  `c02c324cb8a665f401e32a5e2c9357bd9af592f980fe6f010bb57c9f46f0a920`。
- 新地址`192.168.3.245:39775`连接成功，唯一物理设备为`M2010J19SC/lime`（同时显示其配置内mDNS别名），
  电量64%、外接供电、屏幕解锁。新建task185并通过`/api/monitor/run-once`精确执行
  `开学第一课PPT`/rank4；run=`monitor-d2550d932da1`。
- 搜索词提交成功并进入商品tab；第一次下滑后的
  `data/probes/monitor-d2550d932da1-probe-result-scroll-1/current.png`肉眼仍是正常搜索结果页：固定搜索框为
  “开学第一课PPT”、商品tab选中、4张商品卡完整可见。分类器却返回
  `page_kind=unknown/page_kind_source=ocr_ui_unclassified`，流程以
  `not on search results while scrolling for rank: unknown`停止。尚未点击商品、未调用视觉模型、0商品、
  0 rank4证据。
- 当前task185=`pending attempts=1/3`；desired=paused、scheduler=false、risk保留上述原文、running=0、
  lease=0。下一步先向用户确认几何搜索结果页签名修复和基础设施attempt返还；未经确认不得清risk或重跑。

## 2026-08-20 搜索框单一身份规则已部署；task185已返还，等待新ADB地址

- 用户明确取消搜索结果页标签集合判断。rank滚动现在只要求`GlobalSearchActivity`及固定搜索框文字与任务词
  完全一致；满足即按搜索结果页继续，搜索框缺失或词不同才停止。真实probe回放证明本轮unknown页面固定框仍为
  `开学第一课PPT`。
- 同一真实回放暴露并修复重叠商品卡去重：滚动前卡片带评价摘要、滚动后评价消失，旧整段label键会把rank1
  误当新卡。现只用核心商品标题去重，忽略评价前缀和交易指标后缀；回放最终rank4为
  `2026秋开学第一课……`，不是rank1。
- 定向33 passed；完整回归`954 passed, 4 skipped in 70.90s`。备份
  `data/backups/before-rank4-search-page-fix-20260820T061016.sqlite3`，SHA-256=
  `d18c431f48237cad01891043bd75d93eac5cad3b8aef187d412fb05bb634023a`。task185的基础设施失败attempt
  已从1返还为0，审计event1647；原risk精确清除，desired保持paused。
- 8793已加载修复，监听PID41624；8765 PID22176前后未变。准备真实重跑时`192.168.3.245:39775`
  再次消失，精确重连返回10060，mDNS为空。未领取task185；当前pending attempts0/3、running=0、lease=0、
  risk=null。下一步仅需用户提供无线调试主页面新的完整`IP:port`，即可直接跑rank4。

## 2026-08-21 rank4已落库，但AI标题漏字且收尾搜索页规则未复用

- 新地址`192.168.3.245:43021`连接成功，设备`M2010J19SC/lime`、电量81%。受控run=
  `monitor-d6c80899da28`准确完成搜索、一次滚动、rank4点击和商品详情采集；新增product72/observation72，
  valid search evidence56明确为rank4，累计销量1万+、direct_url和卖家粉丝4.5万均有证据。
- Qwen视觉调用耗时134.531秒，正确取到到手价9.8；标题却漏1字。页面OCR原文两行为
  `2026秋开学第一课！多年级原创开学第一课ppt课件一`和`二三四五六上`，AI/产品表写成
  `2026秋开学第一课！多年级原创开学第一课ppt课件一二三四五上`，缺“六”。product72当前值不能视为合格。
- 商品采集后第一次Back已到`GlobalSearchActivity`且固定搜索框仍为任务词，但probe1675分类为unknown；
  收尾函数仍只接受page_kind=`search_results`，没有复用rank滚动的固定搜索框规则，因此第二次Back进入
  search_input并以`post-capture back did not reach search results: search_input`停止。
- 当前task185=pending attempts1/3、task_result=0；商品72和valid rank4 evidence已存在，不能直接重跑制造重复观察。
  desired=paused、risk=null、running=0、lease=0、DB quick_check=ok、FK=0。下一步先取得用户确认，再同时处理
  收尾规则复用、AI标题可核验门槛、product72精确回填及基于既有证据完成task185；未完成前不进入rank5。

## 2026-08-21 搜索页判断已统一为公共固定框规则并加载8793

- 按用户要求，搜索页身份不再依赖变化的标签集合。新增公共函数`_is_expected_search_context`，只认
  `GlobalSearchActivity`及固定搜索框唯一文字与任务词完全一致；rank滚动和详情返回均复用，禁止再各写一套规则。
- 真实probe`monitor-d6c80899da28-probe-after-detail-back-1`虽为`page_kind=unknown`，新规则回放在第一次Back
  即返回成功，`back_calls==1`；不会再多Back到search_input。错误关键词或固定框不可靠仍停止。
- 定向17 passed，完整回归`955 passed, 4 skipped in 65.31s`。8793已重载为项目监听PID31964且健康；
  8765 PID22176未变。desired=paused、scheduler=false、risk=null、running=0、lease=0；旧last_block仅作为历史保留。
- 本次只修并部署搜索页公共规则，没有操作手机、没有修改product72或task185。product72标题漏“六”和task185尚无
  task_result仍为独立未完成项，解决前不得进入rank5。

## 2026-08-21 新千问提示词已加载，真实采集已恢复

- 默认视觉提示词已改为高精度逐字转写：先定位价格下方正文标题，跨行按顺序拼接，逐字保留字符，对数字/年级序列二次点验，禁止概括改写；无法唯一确认时返回空标题和0，由现有校验fail closed。`tests/test_vision_fields.py`为13 passed。
- 用product72原始详情整图离线回放，新提示词返回完整标题`2026秋开学第一课！多年级原创开学第一课ppt课件一二三四五六上`和到手价9.8，没有再漏“六”。
- 用户要求省略每次启动前的重复全套核对并直接采集。项目8793已由脚本拉起为PID 28208；精确地址`192.168.3.245:43021`连接成功；8765为其他项目PID 20884，未触碰。
- 真实run=`monitor-f6afb31522b6`完成task185/rank4，`processed_tasks=1`、`captured_products=1`，新增product73；页面返回链未再出现unknown。随后调用普通resume，`desired_state=running`、risk=null，scheduler线程alive/running，开始自动推进rank5和后续关键词。
- 尚未清理的历史质量项：product72仍保留旧的漏“六”标题，后续需SQLite backup API备份后精确修正；这不代表新版提示词本轮仍漏字。

## 2026-08-21 工作台新增采集时间排序；rank5跨轮入口仍待修复

- 商品采集时间一直有保存：每条观察写入`observations.observed_at`，工作台`/api/status`对每件商品返回最新观察的`observed_at`。现有排序下拉框已新增“采集时间从近到远”和“采集时间从远到近”，按最新成功采集时间排序；无效/缺失时间排在末尾，不修改生产数据库。
- 修改`src/xhs_scout/workbench_ui.py`和`tests/test_workbench_ui.py`；定向`tests/test_workbench_ui.py tests/test_web.py`为65 passed。仅用项目脚本重载8793，新PID 24784；网页回读确认两个新选项均存在；8765未触碰。
- 自动化尚未闭环：rank4成功后scheduler自动创建task186/rank5，但run=`monitor-07239fc78493`启动时手机已经位于正确`GlobalSearchActivity`，起始probe仍为unknown，`_open_search_results`入口没有调用已存在的`_is_expected_search_context`，转而寻找首页搜索按钮并报`search product button not found`。当前desired=paused、scheduler=false。
- 这与滚动/详情返回处的unknown修复属于同一类“公共规则未覆盖全部入口”，但发生在新一轮任务起点。建议最小修复：轮次开始先调用公共固定搜索框规则；同关键词直接复用结果页，关键词不同则从固定搜索框进入输入与替换流程，只有真实首页才寻找首页搜索按钮。未经用户确认，本轮未改采集逻辑。

## 2026-08-21 rank5跨轮入口与空UI树HTTP 500已修复；真机终验被设备离线阻塞

- `SEARCH-ROUND-ENTRY-04`已落地：轮次起点、详情页返回和搜索收尾统一使用固定搜索框精确词规则。只有`GlobalSearchActivity`、固定搜索框OCR精确等于当前关键词且页面存在完整商品卡时，才把旧分类器的`unknown`归一为`search_results`；搜索输入页不会误认。使用真实`monitor-07239fc78493-probe-start`及`monitor-d2acc101c016-probe-start`回归通过。
- 随后的受控run=`monitor-e8f962291bd0`已成功走到“商品”分类页，但该probe的uiautomator dump为空，旧`find_product_cards`把空字符串直接交给ElementTree，抛`ParseError: no element found`并使`POST /api/monitor/run-once`返回HTTP 500。这不是搜索词或页面类型再次误判。
- 已在`src/xhs_scout/monitor.py`增加空/损坏UI树有界恢复：不重复整套截图/OCR，只在当前页面最多原地重抓2次XML，成功后原子回写`window.xml`并记录`ui_tree_retry_recovered`；连续失败则以`reason_code=ui_tree_unavailable`执行基础设施硬停止并返还当前attempt。`src/xhs_scout/ui_automation.py`的商品卡选择器同时对空/损坏XML fail closed，不再向HTTP层泄漏`ParseError`。
- 新增真实故障回归、损坏XML防护和基础设施attempt返还测试；相关套件`tests/test_monitor_search.py tests/test_workflow.py tests/test_detail_page_evidence.py tests/test_monitor_seller_profile.py tests/test_ui_automation.py tests/test_vision_fields.py`共70 passed。
- HTTP 500曾把task186的attempts从0错误扣为1。修改生产库前已使用SQLite backup API备份到`data/backups/before-task186-ui-tree-refund-20260821T191346.sqlite3`并确认`PRAGMA quick_check=ok`；随后仅把task186从attempts=1返还为0、清除该错误并写入审计run=`repair-task186-ui-tree-20260821T191346`。当前task186=`pending`、run_owner=null、attempts=0。
- 8793已用项目脚本重载为PID 36296，8765明确未触碰；scheduler继续paused。真机终验未执行：`192.168.3.245:43021`先显示offline，精确disconnect/reconnect后连接超时且ADB列表为空。取得手机当前无线调试地址后，直接以task186/开学第一课PPT/rank5重跑，验收真实下滑、商品详情标题与价格、店铺粉丝、direct_url及采集后返回搜索页；通过前不得宣称24小时自动化闭环。

## 2026-08-22 task186/rank5真机终验通过

- 用户提供新无线调试地址`192.168.2.238:41495`；ADB连接成功，设备门禁确认配置中的唯一型号`M2010J19SC`、device=`lime`，电量60%、屏幕解锁，未触碰8765。
- 受控run=`monitor-119d9442d7cd`完成task186/“开学第一课PPT”/rank5：接口返回`processed_tasks=1`、`captured_products=1`、无skipped；事件明确包含`scroll_product_results_for_rank`，证明第5件真实触发一次下滑，而非回绕旧卡。
- 新增product74、observation74；标题为`高一开学第一课班会PPT课件（30页可编辑+教案+逐字稿）`，价格9.9，累计销量103，`direct_url=xhsdiscover://goods_detail/6a7ad1bafa5d5c0001bfa589`。店铺入口与店铺页证据已采，页面显示店铺/作者名`小彩老师`，粉丝数字未展示，因此按`not_displayed`保留空值，不猜测。
- `search_result_evidence` id=58：source_keyword=`开学第一课PPT`、result_rank=5、page_kind=`search_results`、valid=1；`task_results` id=43为valid=1。采集后事件`back_to_search_results`和`task_completed`均存在，task186最终`completed`、last_error=null。
- 本轮未再出现空UI树`ParseError`、HTTP 500或搜索页unknown阻塞，说明`SEARCH-ROUND-ENTRY-04`与`UI-TREE-EMPTY-05`均已通过真实链路验收。当前`desired_state=paused`、risk=null；长期scheduler尚未恢复，需用户确认后再开始连续采集和rank5后自动换词验收。

## 2026-08-22 连续scheduler已完成rank5并自动换到下一关键词

- 在修复旧词结果页切换、`领券购买`详情页分类和非商品恢复租约顺序后，连续scheduler真实完成“收心主题班会”task187–190/rank2–5；rank5对应run=`monitor-bff6223ae324`，事件包含一次`scroll_product_results_for_rank`，并于`2026-08-22T01:59:55-07:00`完成商品、店铺补充取证和返回搜索结果页。
- rank5完成后没有人工点按、没有调用run-once。scheduler立即启动run=`monitor-63c6d5f963f6`，把固定搜索框中的旧词替换为下一关键词`新生入学教育PPT`；事件`keyword_resubmitted`确认截图固定ROI回读与任务词一致，随后点击rank1并进入`GoodsDetailActivityV2`。
- 当前24小时真实窗口起点按“恢复后首个有效商品完成时间”记录为`2026-08-22T01:47:02-07:00`。当前`desired_state=running`、`scheduler_running=true`、`risk_stop_reason=null`；这证明连续推进已经启动，但只有运行到次日同一时间且期间证据连续，才能声明24小时验收通过。
- Windows计划任务`XhsProductScoutWorkbench8793`仍未安装，`ops/autorun/autorun.config.json`仍不存在。因此当前进程内自动采集已运行，但Windows登录后、8793进程退出后的无人值守自恢复尚未完成。安装前需用户明确确认系统级写入；批准后配置仅恢复项目8793，并只在`desired_state=running`且无风险停止时普通resume，绝不清理风控/登录/CAPTCHA等风险，也不触碰8765。
