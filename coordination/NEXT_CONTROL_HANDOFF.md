# 小红书选品 Agent — 新总控最小上下文交接

交接日期：2026-07-31 16:53（Asia/Shanghai）

项目根目录：

```text
C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent
```

## 2026-08-03 16:16 最新强制检查点：店铺券弹层后 SIGSEGV，非程序二次点商品

- 单次真实验收 `monitor-f9899bb802d6` 证明分享链接收尾误 Back 修复生效：
  seller-before 仍为完整商品详情，没有退回搜索结果。但完整流程仍失败。
- 程序 16:12:44 正确点击店铺并正常打开 `ShopDetailActivity`；16:12:46 小红书自行
  弹出券页 `XhsReactTranslucentActivity`；16:12:48 小红书 PID 28358 以 SIGSEGV
  退出。Android 自动启动 PID 13222 并恢复旧 `GoodsDetailActivityV2`，视觉上像再次
  打开商品，但没有第二次商品卡点击事件。
- 当前程序点击店铺后固定等待，未及时识别/关闭券弹层，也未在卖家阶段检测 PID
  改变，最后误报 `店铺入口打开了未知页面：unknown`。另有独立的 Windows
  `Set-Clipboard` 非零退出，导致本轮 product 40 链接为空。
- 备份：`data/backups/xhs_scout.sqlite3.before-post-fix-full-validation-20260803-160946`，
  SHA-256=`6297c23216dc9b53f0763e09cf52819ad15c4c0c6555dd1419927cc7baba9f36`。
  最终 desired paused、scheduler false、DB quick_check=ok、running=0、lease=0；G2
  未启动。下一主线是卖家入口的券弹层快速关闭和 PID 崩溃识别，不得直接重跑。

## 2026-08-03 15:26 最新强制检查点：分享链接误 Back 已修复加载，尚未真实复跑

- 三固定控件判断已集中到 `ui_automation.product_detail_controls_present`，
  `detail_metrics.py` 与 `product_link.py` 共同复用“客服/购物车/加入购物车”。分享链接
  finally 不再依赖“立即购买”，现场“领券购买”同型测试确认 `Back=0`；分享面板仍
  打开时保持 `Back=1`。
- 修改前复现测试准确失败；修改后相关定向 `28 passed`，完整
  `728 passed, 3 skipped`。8793 已从 PID 44268 重载为 PID 61332；8765 PID 21820
  未触碰。
- 当前 desired paused、scheduler false、next null；精确旧 risk 保留，DB
  quick_check=ok、running=0、lease=0。没有再次操作小红书、没有真实验收、没有启动
  G2。下一步只有用户同意后才做一次受控单商品完整验收，不能把离线测试冒充流程通过。

## 2026-08-03 15:15 最新强制检查点：分享链接收尾旧判断多按 Back

- 用户现场观察的一次受控重跑 `monitor-bd07cab4561d` 已明确排除本轮兼容崩溃和
  点击错误：首页搜索入口、历史词、商品第 1 卡均点击正确，进入商品详情；小红书
  PID `28358` 全程不变，无黑屏、ANR 或进程重启。
- 商品本体及链接已写入 product 39 / observation 39（价格 11.8、累计销量 717、
  share URL 已取得），但完整流程失败，卖家粉丝未采集。
- 精确根因：`src/xhs_scout/product_link.py:391` 在复制链接 finally 仍以“加入购物车 +
  立即购买”判断分享面板是否关闭。现场为“领券购买”，分享面板实际已经关闭，程序
  却额外 Back 一次，把详情退回搜索结果，随后 risk=`seller capture requires
  product_detail, got search_results`。
- 生产 DB 备份：`data/backups/xhs_scout.sqlite3.before-visible-controlled-rerun-20260803-1510`，
  quick_check=ok，SHA-256=`e9cb512960ac40ff5d335693868c8dfd913aff52487fb24ca0185396e7973b36`。
- 当前 8793 PID 44268、desired paused、scheduler false、next null；8765 PID 21820
  未触碰；DB quick_check=ok、running=0、lease=0，G2 未启动。下一主线只修
  product-link 收尾复用“客服/购物车/加入购物车”三固定控件并回归，不能再把它归为
  BlueStacks 兼容问题。

## 2026-08-03 14:45 最新强制检查点：三固定指标修复已加载

- 按用户指定口径，商品详情不再用变化的“立即购买/领券购买”判断；现在只在 XML
  同时出现“客服”“购物车”“加入购物车”时认定三固定控件存在。
- 失败现场真实 detail XML 三指标全部存在且购买文案为“领券购买”；同轮搜索结果
  XML 三指标均不存在。新函数真实回放结果 detail=true、search_results=false。
- 定向 `11 passed`；完整 `728 passed, 3 skipped`。8793 已从 PID 5452 重载为
  PID 44268；8765 PID 21820 未触碰。
- 当前 desired paused、scheduler false、next null；14:18 旧精确 risk 保留，G2
  expected 为空。本次没有清险、采集或重启 G2。先向用户汇报，用户确认继续后才
  建立全新 G2。

## 2026-08-03 14:25 最新强制检查点：新 G2 第一轮因导航守卫误 Back 失败

- 启动前 DB 已备份为
  `data/backups/xhs_scout.sqlite3.before-g2-20260803-141621`，quick_check=ok；8793
  PID 5452，8765 PID 21820 未触碰。
- 14:18:00 启动 `monitor-753a39ad55df`、task 99 `食谱`，确认
  `restart_app_before_round=false`。搜索和商品本体采集成功，写入 product 37 /
  observation 37，captured_products=1。
- 失败根因已精确定位：指标条导航守卫截图仍是商品详情，但 XML 控件启发式误判
  已离开详情并执行 Back，导致卖家采集前退回 search_results，硬停止
  `seller capture requires product_detail, got search_results`。这不是 ANR 或黑屏。
- scheduler 和 heartbeat `g2` 已暂停，15:18/16:18 取消，expected 为空；DB
  quick_check=ok、running=0、lease=0。不得把商品本体成功冒充 G2 通过。下一主线是
  修复 `detail_metrics.py` 导航守卫误判和多余 Back，回归并受控验收后再请用户确认
  新 G2。
- 证据：`g2-20260803-141800-{db,http,round}.json`；ledger
  `g2-20260803-141800-blocked`，hash
  `ece8643c2116634b298d0bf566a046965519946bb614709398dbd6cced9600dc`。

## 2026-08-03 12:54 最新强制检查点：无条件冷启动已删除，暖进程搜索通过

- 8793 scheduler 已从 `restart_app_before_round=True` 改为 False；正常轮次不再
  force-stop/relaunch。ANR 和进程崩溃恢复仍保留，安全硬停止边界未变。
- 定向 `22 passed`；完整 `727 passed, 3 skipped`。8793 已加载为 PID `5452`、
  desired paused、scheduler false；8765 PID `21820` 未触碰。
- 首次 BlueStacks 命令行冷启动仍曾在未点击搜索前因 `Alarm.onReceive` / 原生库锁
  ANR，证明固定等待不是充分修复；人工图标启动 PID 29302 稳定约 90 秒后，程序
  点击独立搜索按钮成功，`GlobalSearchActivity` 已绘制、可见、获焦，约 40 秒无 ANR。
- 当前停在稳定搜索页，未输入关键词、未采集、未写商品、G2 expected 为空。无条件
  冷启动 P0 已验收；下一步如继续，应先决定是否加固异常恢复后的稳定性窗口，不能
  直接宣称 BlueStacks/JNI 兼容问题已全部解决或直接重启 G2。

## 2026-08-03 12:23 最新强制检查点：搜索页黑屏根因已定位，禁止直接重启 G2

- `monitor-3dc599a2df2a` 首轮 captured=0；准确点击首页长条搜索框后黑屏 ANR，
  scheduler 已暂停，12:15/13:15/14:15 全部作废，G2 expected 已清空。
- 用户现场观察下按程序同一坐标再次点击，黑屏稳定复现；当前现场保留，未重开应用。
- `GlobalSearchActivity` 已 resumed 但无 Window、从未 drawn。两次 ANR 主线程都卡在
  `GlobalSearchActivity.onCreate → SoLoadProxy.loadLibrary → Runtime.load0 →
  MonitorEnter`；后台 Sentry FD monitor 也等待原生库加载锁，日志另有非法 JNI
  version。结论为小红书 9.39.0 与 BlueStacks x86/Android 11 的原生库/JNI 初始化
  竞争或兼容故障，不是搜索按钮、OCR、关键词或商品卡识别问题，也不是前次 OOM。
- 8793 PID `61072`、desired paused、scheduler false、next null；8765 PID `21820`
  未触碰。下一步先设计最多 3–5 组、每组有截图/Activity/ANR 证据的低风险环境或
  启动时序实验；未形成稳定绕行前不得启动新 G2。

## 2026-08-02 22:36 历史检查点：OOM 崩溃恢复（轮前重开部分已于 2026-08-03 废止）

- 当时曾加入 scheduler 每轮有真实任务先关闭/重开小红书；该部分已在
  2026-08-03 12:54 因放大冷启动 JNI/ANR 风险而删除，不得恢复。仍然有效的是：
  点击商品前后读取 PID，进程变化且未到详情页时按应用崩溃处理，重启后重新搜索
  当前关键词并只重试一次，第二次失败即暂停。硬风险停止边界保持不变。
- 定向 `20 passed`；完整 `tests` 回归 `726 passed, 3 skipped in 78.19s`。
- 8793 已加载当前代码，PID `61072`、HTTP 200；8765 仍为其他项目 PID `21820`，
  未触碰。
- 唯一一次受控应用关闭/重开已通过：小红书 PID `23611`→`26823`，探针
  `data/probes/probe-2026-08-02T22-35-43+08-00` 为正常首页、无 ANR、无风险页。
- 当前 DB quick_check=ok、running=0、lease=0；desired paused、scheduler false、
  next null、G2 expected 为空。本次没有搜索、商品采集或 G2 启动。
- 第二轮历史 block/skip 仍作为证据保留，risk=null。用户同意继续后，才精确清除
  历史 block/skip，并从当时实际时间建立三个全新的 G2 点；旧 21:01/22:01/23:01
  永久失效。

## 0. 2026-07-31 最新强制接手检查点（优先于本文旧阶段说明）

### 2026-07-31 16:28 只读基线补充

- 8793/8765、API、数据库、调度、任务和租约均与 16:16 交接一致；
  当前计数刷新为 pending=68、products=27、observations=34、candidates=15。
- 重要现场偏差：ADB 底层 resumed Activity 是首页 `IndexActivityV2`，但当前
  `mCurrentFocus` 仍是 `Application Not Responding: com.xingin.xhs`。
- 当前 ANR 对话框在两项 P0 和离线回归完成前保持不动；之后只做一次受控
  关闭—重开—正常首页验证。用户同意前不清旧 risk/block、不重排 G2。

### 2026-07-31 16:35 两项 P0 离线完成

- RapidOCR 已改为独立进程，默认 60 秒硬超时并可强制终止；超时探针保留截图、
  window 和明确 `ocr_timeout` 结果。
- monitor 与 daily-sales 已删除一次性恢复额度的决策逻辑；每次当前 ANR 都执行
  应用级关闭/重开，硬停止边界未放宽。
- 定向 `37 passed`、相邻 `120 passed`、完整
  `719 passed, 3 skipped in 49.49s`。
- 当前代码尚未加载到 8793，ANR 对话框仍在，旧 risk/block 和 G2 状态未改。
  下一步只重载 8793，再做唯一一次受控恢复验证；用户同意前不清旧风险、不重排 G2。

### 2026-07-31 16:42 两项 P0 已真实验收，等待用户确认继续 G2

- 当前代码已加载到 8793 PID `59724`；8765 PID `21820` 未触碰。
- 受控关闭/重开成功。最终探针
  `data/probes/probe-2026-07-31T16-41-29+08-00` 为正常首页、
  `IndexActivityV2`、has_anr=false，真实独立进程 OCR 正常返回。
- 同时修复了窗口转储残留旧 ANR Window 导致的当前焦点误判；最终完整回归
  `720 passed, 3 skipped in 50.49s`。
- DB quick_check=ok、running=0、lease=0；desired paused、scheduler false、
  next null、G2 heartbeat PAUSED。
- 旧 risk/block 和历史 counter=1 仍作为精确现场保留，但新代码不再读取 counter。
  等用户明确同意后，才备份 DB、精确清旧原因并设置三个全新的 G2 时间点。

### 2026-07-31 16:53 用户已授权，G2 已立即启动

- DB 已备份到
  `data/backups/xhs_scout.sqlite3.before-g2-risk-clear-20260731-164812`，
  quick_check=ok；旧 risk/block 和 counter 已按精确门禁清除并有审计。
- 新三点：16:48:39、17:48:39、18:48:39（北京时间）；heartbeat `g2`
  已迁移到当前任务并 ACTIVE。
- 第一轮 `monitor-bf9f8841ac88` / task 97 `预算表`：当前 ANR 检出后成功
  关闭/重开到首页；captured=0、failed/recovered、无 risk/block/skip、租约释放。
- 当前 scheduler running，next=17:50:29。后两点继续保持 1 词×1 商品；第三点
  后先 pause 再判定 G2。
- 第一轮正式证据已写入 `g2-20260731-164839-{db,http,round}.json` 和 scheduler
  账本。账本中文显示 `???` 是 PowerShell 管道编码缺陷，DB/round 证据正确；
  后续从 SQLite 读取中文或用 Unicode 转义。

当前不得重复 resume 或启动 CLI monitor-loop。8793 内置 scheduler 与 heartbeat
`g2` 已运行；`evidence/scheduler-expected.json` 只认新的
16:48:39/17:48:39/18:48:39，旧 14:29/15:29/16:29 继续失效。

用户刚刚明确纠正 ANR 处理口径：

- “自动重开额度”不是平台限制，而是项目内部错误设计；
- 旧逻辑通过 `app_recovery_consecutive_count=1` 限制“自上次完整商品采集后只自动
  关闭并重开一次”，第二次 ANR 就拒绝处理；该逻辑必须废止；
- 每次明确出现“小红书没有响应”，都应关闭小红书应用、重新打开，确认回到无
  登录/验证码/风控的正常首页或搜索页后，从安全起点重新搜索；
- 不得因为此前重开过一次，就要求用户手动处理；
- 登录、验证码、风控、未知商品身份和数据库锁仍必须停止，不能借重开绕过。

最新失败轮为 `monitor-be821cc9e2c1`：14:30:22 启动，首页截图于 14:30:24
完成，但 `probe.json`/`window.xml` 到 16:10:37 才生成，证明约 1 小时 40 分钟
卡在进程内 `RapidOCR`。随后搜索入口复探识别到 ANR；旧一次性预算拒绝重开并
暂停，本轮 captured=0。该长时间卡顿是本地 OCR 挂起，不是定时等待，也不是
Codex 持续消耗 token。

接手后先完成两个 P0：

1. 把 RapidOCR 放入可强制终止的独立进程，设置单次识别硬超时；超时后必须终止
   OCR 工作进程并返回明确错误，不得再挂数十分钟。
2. 删除/重构 monitor 与 daily-sales 的粘性一次恢复预算，使每次当前 ANR 都能
   关闭应用、重开、验证正常页面并重新搜索。

当前已完成四项相邻修复：搜索入口短暂空白复探、首页历史查询词入口识别、
`IndexActivityV2` 首页误分类纠正、误入店铺商品列表时直接采集粉丝并返回。
当前完整测试基线为 `717 passed, 3 skipped`。

最新只读状态：8793 PID `53764`；8765 PID `21820`（严禁触碰）；desired=paused、
scheduler=false、next=null；DB quick_check=ok、running task=0、lease=0；
ADB `127.0.0.1:5555` 在线。旧 risk/block 仍保留
`Xiaohongshu ANR detected; automatic app recovery already used since the last successful product capture`，
只能在两项 P0 修复和受控验证后按精确原因清除。

详细证据与新决策见：

- `coordination\TASK_BOARD.md` 检查点 39；
- `HANDOFF.md` 最新 `2026-07-31 16:16` 检查点。

## 1. 这份交接怎么用

这份文件是为新总控准备的压缩入口，目的是避免重新通读一周历史。

新总控开局只需要读取：

1. `C:\Users\Lenovo\AGENTS.md`
2. 本文件 `coordination\NEXT_CONTROL_HANDOFF.md`
3. 完整 `coordination\TASK_BOARD.md`
4. 正式 `HANDOFF.md` 的最新约 180 行

`HANDOFF.md` 必须读取，但开局只读最新检查点，不从第一行通读全部历史。PowerShell
可以使用：

```powershell
Get-Content -LiteralPath .\HANDOFF.md -Encoding UTF8 -Tail 180
```

开局不要通读：

- `HANDOFF.md` 更早的全部历史章节
- 完整 `PARALLEL_WORK.md`
- 全部 `coordination\T*.md`
- 全部源码和测试
- 历史对话或旧并行任务

执行到对应阶段时，再按本文件第 8 节读取所需文档。

## 2. 最终目标

建立一个高覆盖、低频、可暂停、可审计的小红书虚拟商品选品平台：

- 从 100 个发现型根词开始搜索公开虚拟商品；
- 对每个真实商品拆解和沉淀关键词；
- 数据足够后生成有证据支持的组合词；
- 新词经人工审核后有限入队和持续轮转；
- 采集商品身份、真实链接、趋势、公开笔记和公开账号证据；
- 识别低粉爆款，输出候选分析、风险、证据缺口和原创化方向；
- 依次通过 G0–G5，最终完成经过验证的 24 小时 1×1 自动监控。

不能宣称全站穷举。“全站/全类目”只能解释为有限关键词池的高覆盖轮转。

## 3. 已经完成的主要成果

- 最小真实闭环已跑通。
- G1 三个受控真实轮次已完成：
  - `monitor-45c96a5b5e1c`
  - `monitor-6e6e0be23652`
  - `monitor-01375a7cca15`
- 基础采集、截图/OCR、数据库、状态机、租约、风险停止、灰色指标条、评分、报告、质量审计、摘要和四工作区已有主体代码。
- 最近一次记录的完整离线基线为 `568 passed, 3 skipped`。
- 工作台四工作区重构已完成，不要重新设计界面。
- 已建立唯一项目板 `coordination\TASK_BOARD.md`。
- 已固定 100 个发现型根词：
  `config\discovery_root_terms.txt`，恰好 100 个且无重复。
- 已建立唯一关键词策略：
  `coordination\KEYWORD_STRATEGY.md`。
- 过时的 66,491 行历史 Excel 已按用户要求移入 Windows 回收站，不得恢复或重新读取。
- 旧 `config\seed_keywords.txt` 78 词和旧
  `config\keyword_portfolio.json` 126 候选只作审计/兼容，不得主导新词库或批量入队。

## 4. 尚未完成的核心业务结果

不要因为代码和测试较多就误判项目接近完成。当前主要缺口仍然很大：

| 维度 | 最近记录的粗略状态 | 主要缺口 |
|---|---:|---|
| 功能代码与离线安全 | 约 85% | 当前运行进程尚未加载并完成真实验收 |
| 真实商品数据完整度 | 约 20–30% | 商品少，真实链接、趋势和低粉证据严重不足 |
| 关键词发现与轮转 | 约 20–30% | 只有策略和 100 根词；逐商品拆解、组合、审核、入队和轮转未完成 |
| 24 小时自动化验证 | 约 20% | 只有 G1；G2、G3、G4、G5 均未完成 |

最近一次已记录数据快照：

- 66 个待处理任务
- 23 个商品
- 29 条商品观察
- 5 条笔记/账号观察
- 13 个候选

以下第 5 节起是 2026-07-29 的历史路线；当前事实和主线以本文最上方
2026-08-03 12:54 检查点及统一项目板最新检查点为准。

## 5. 当前唯一主线

当前主线不是继续增加展示组件、只读接口或证明工具。下述长路线仅作历史背景；
现行唯一主线是：无条件轮前冷启动已删除且暖进程搜索已验收，scheduler/G2 保持
暂停；用户确认继续后才按当时实际时间建立全新 G2 批次。

固定顺序：

1. M1：只读基线后，串行重启并验收本项目 8793。
2. M2：完成 G0 生产准入证据封板。
3. M5-01A：实现并持久化每商品关键词拆解。
4. M5-01B：实现支持度统计和有门槛的组合候选。
5. M5-02～03：按新字段适配人工审核，并建立默认 dry-run 的批准词入队入口。
6. 重新只读刷新 T41，按 M3 Identity 小批补真实链接和搜索归属；同页才补趋势。
7. 用真实新增商品验证拆词和组合，不足门槛时只积累，不强行组合。
8. 用户审核首批 10–20 个不同形态根词/衍生词。
9. 总控有限入队，但不因入队自动启动采集。
10. 依次完成 G2、G3、G4。
11. G0–G4 全部通过，并再次得到用户明确确认后，才运行 G5 24 小时 soak。
12. G5 通过后才讨论每轮 3–5 个关键词和 Windows 计划任务。

旧 T67/T68/T69 和继续美化界面均为 P2，不得挡住上述主线。

## 6. 接手后的前三步

### 第一步：只读刷新真实状态

核验：

- 8793 和 8765 的端口所有者、PID、命令行；
- 8793 健康接口和监控状态；
- 数据库计数和 `PRAGMA quick_check`；
- `desired_state`、`scheduler_running`、`next_run_at`；
- risk/block/skip；
- running task 和运行租约；
- ADB `127.0.0.1:5555`；
- Rvc64 前台 Activity 和 ANR；
- 是否存在旧 heartbeat、monitor-loop、soak 或并行任务仍在运行。

这一步不得触发采集、补证、恢复调度或写数据库。

### 第二步：对照项目板更新事实

- 把刷新后的状态写入 `coordination\TASK_BOARD.md`。
- 旧 PID、数据计数、测试数和 Activity 若已变化，以新核验为准。
- 检查有没有未验收改动；全量测试只能在写入稳定后由总控串行运行一次。

### 第三步：从 M1 开始，不自动跳到真实轮转

- 先完成 M1 和 M2。
- 服务重启只操作本项目 8793；严禁触碰 8765。
- 在进入 M3、G2 或任何真实采集前，重新核对安全门槛和用户当前授权。

## 7. 关键词新策略的关键口径

现行闭环：

```text
100 个发现型根词
→ 小批宽搜索
→ 每个真实商品拆解词元
→ 支持度统计
→ 数据达到门槛后生成组合候选
→ pending_review
→ 人工批准
→ 有限入队
→ 轮转结果继续反哺词库
```

每个商品至少记录：

- 来源根词、run/task/product/observation；
- 原始标题、规范化标题；
- 领域、场景、人群、形态、阶段、功能；
- 搜索上下文、商品证据、真实链接或缺口；
- 支持商品数、支持根词数、风险和审核状态。

默认组合门槛：

- 小样：至少 30 个有效不同商品、10 个不同根词、3 个领域/场景；
- 稳定：至少 100 个有效不同商品、30 个根词；
- 单个稳定组合至少由 2 个不同商品支持；
- 不做全笛卡尔积；
- 新词永远先 `pending_review`，不得自动搜索。

## 8. 按阶段读取文件

| 阶段 | 需要读取 | 不需要读取 |
|---|---|---|
| 开局只读核验 | 全局 `AGENTS.md`、本文件、完整项目板、正式 HANDOFF 最新约 180 行；必要时 `OPERATIONS.md` 的端口、状态检查部分 | HANDOFF 更早历史、PARALLEL_WORK、全部专项文档 |
| M1 工作台加载验收 | `README.md`、`OPERATIONS.md` 相关章节、工作台入口代码和定向测试 | T16、T41、全部历史并行记录 |
| M2 G0 | 项目板 M2、当前 readiness/baseline/evidence 代码和测试 | M3 详细补证文档 |
| M5 关键词实现 | `coordination\KEYWORD_STRATEGY.md`、项目板 M5、直接相关源码/测试 | 旧 Excel、完整 HANDOFF、旧 T20 历史设计 |
| M3 数据补证 | `coordination\T16-data-quality-remediation.md`、最新 T41 队列/证据文件、项目板 M3 | 全部其他 T 文档 |
| G2/G3 | `OPERATIONS.md` 调度/恢复章节、项目板 M6/M7、直接相关代码测试 | G4/G5 证据文件 |
| G4/G5 | 只有前序门槛通过后再读对应 readiness、soak 和证据文档 | 不提前组装或启动 |

如果专项文档与项目板或 `KEYWORD_STRATEGY.md` 冲突，以项目板和现行策略为准，并在 HANDOFF 记录冲突。

## 9. 真实状态所有权和硬边界

总控独占：

- 生产数据库写入和 `data/`；
- 8793/8765 所有权操作；
- ADB、BlueStacks、小红书真实 UI；
- 真实采集、补证、scheduler、pre-soak、24 小时 soak；
- HANDOFF、项目板最终更新；
- 批准词写入生产队列；
- Windows 计划任务安装。

严禁：

- 操作属于其他 Agent 的 8765；
- 恢复全部 66 个任务；
- 绕过验证码、风控、登录或设备限制；
- 使用隐藏接口、抓私密数据、代理池、多账号、设备伪装、Magisk/Xposed/LSPosed；
- 发布、购买、加购、收藏、关注、评论、客服；
- 未经用户明确确认启动 24 小时 soak 或安装 Windows 计划任务。

验证码、安全限制、ANR、未知危险页、搜索上下文丢失、商品身份不明、数据库锁异常或任何 risk/block/skip 出现时，立即停止并保留证据。

## 10. 并行和 token 预算

- 默认“1 个总控 + 最多 1 个子任务”。
- 只有真正独立、边界清楚、直接阻塞 P0/P1 的离线模块才分派。
- 子任务只读取施工单点名的源码和测试，不得读取本交接、完整项目板或完整 HANDOFF。
- 一个批次最多 1–2 个交付物；批次结束先验收、集成、更新项目板，再决定下一批。
- 不用 heartbeat 高频轮询，不为了保持窗口活跃而续派。
- 真实环境、共享数据库、服务重启和完整测试永远由总控串行持有。

## 11. 新总控的开局提示词

### 2026-08-02 20:22 最新覆盖状态

- 用户已重新授权 G2，但 20:12 首轮虽成功写入 product 35 / observation 35，随后
  因弱指标 ROI 连续聚焦点击回到首页，卖家阶段硬停止；该轮不计 G2 通过。
- 已修复为弱单指标 ROI 只读、不 tap、不 swipe；完整回归
  `721 passed, 3 skipped`，8793 已加载 PID 9388，8765 PID 21820 未触碰。
- 当前 scheduler/heartbeat 均暂停、running=0、lease=0、DB quick_check=ok；新 risk
  为 `seller capture requires product_detail, got home_feed`。旧 20:13/21:13/22:13
  清单失效。只有以新的实际 resume 时间重建三个点后才能继续。

### 2026-08-02 20:29 最新覆盖状态

- 弱 ROI 修复加载后曾精确清险并再次启动，但 `monitor-a0acebd3d611` 在首页点击
  搜索入口后再次空白并 ANR；captured=0。应用恢复成功回首页。
- 最终 scheduler/heartbeat 均 PAUSED、desired paused、next null、risk/block/skip
  null、running=0、lease=0、DB quick_check=ok；G2 expected 已清空。
- 当前 P0 是首页→`GlobalSearchActivity` 重复主线程 ANR，不得重复同一路径启动 G2。

### 2026-08-02 搜索入口识别覆盖状态

- 首页独立放大镜和长条搜索框现已显式区分为 `home-search-button`、
  `home-search-bar`，运行事件也分别命名；完整回归 `722 passed, 3 skipped`。
- 8793 已加载 PID 67200；8765 PID 21820 未触碰。scheduler/G2 仍暂停，本次未做
  真实搜索验证。

### 2026-08-02 22:02 最新覆盖状态

- 用户授权后 G2 已从实际时间重启，新 expected 只认 21:01/22:01/23:01；旧点
  全部失效，heartbeat `g2` ACTIVE。
- 第一有效点 `monitor-3baaed5970d1` 已通过：task 96 `话术`，captured=1，
  product/observation=36，卖家粉丝=1010；长条搜索框真实点击成功，无 ANR，弱 ROI
  安全跳过，卖家店铺列表读取后安全返回。
- 第一轮收口 quick_check=ok、running=0、lease=0、risk/block/skip=null；scheduler
  运行中，第二轮 next=22:06:17。第二点 heartbeat 已于 22:02 预检安全，不得重复
  resume，只等自然到期并观察完整结果。
- 第一点评估证据 `g2-20260802-210100-{db,http,round}.json`；ledger record
  `g2-20260802-210100-completed`。账本 keyword 因 PowerShell 编码显示 `??`，但
  DB/round 为正确 `话术`；后续账本必须使用 ASCII Unicode 转义。

### 2026-08-02 22:12 最新覆盖状态：第二点 OOM 崩溃，G2 已停止

- 第二轮 `monitor-08649ddcbc84`、task 97 `预算表` 正常搜索并准确点击商品卡，
  `GoodsDetailActivityV2` 已启动；随后小红书 PID 2333 在 FrescoDecodeExecutor
  内存耗尽并以 SIGSEGV(status 11)崩溃，系统用 PID 23611 重启到首页。
- captured=0、block=`app left search flow while opening product: home_feed`、
  skip=`opened page is home_feed`。这不是误点或 ANR；截图、Activity、exit-info 和
  logcat 已互证。
- scheduler 与 heartbeat `g2` 已 PAUSED，23:01 取消，G2 expected 清空；最终
  quick_check=ok、running=0、lease=0，当前小红书正常首页、无 ANR。8765 未触碰。
- 第二点评估证据 `g2-20260802-220100-{db,http,round}.json`；ledger record
  `g2-20260802-220100-blocked`，hash
  `4ce4a8ff5d78f47e44b1bfdf62a27c313087de66586979bf3f9542fde99cfa30`。
- 当前唯一 P0：让 monitor 识别商品详情启动期间的小红书进程崩溃，按应用可恢复故障
  重开并从安全起点重搜；同时设计每轮前低风险内存清理，避免一小时后再次 OOM。
  修复、定向/完整回归、只重载 8793 和受控真实验证完成前，不得再启动 G2。

```text
请接手“小红书选品 Agent”总控任务。

项目根目录：
C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent

开局只读取：
1. C:\Users\Lenovo\AGENTS.md
2. coordination\NEXT_CONTROL_HANDOFF.md
3. 完整 coordination\TASK_BOARD.md
4. HANDOFF.md 最新约 180 行（例如 PowerShell Get-Content -Tail 180）

正式 HANDOFF 必须读取最新检查点，但不要从第一行通读全部历史。
不要开局通读 PARALLEL_WORK、全部 ROADMAP/OPERATIONS 或所有 T 文档；
执行到具体阶段时，按 NEXT_CONTROL_HANDOFF 第 8 节按需读取。

不要要求用户重新解释项目历史。统一项目板是任务规划和完成度的唯一入口，
HANDOFF 负责真实状态和决策证据，KEYWORD_STRATEGY 负责现行关键词口径。

先只读刷新 8793/8765 所有权、健康、数据库计数和 quick_check、监控状态、
risk/block/skip、running task/lease、ADB、Rvc64 前台 Activity、ANR 和残留自动化。
不得触发采集、补证、scheduler、monitor-loop、soak 或生产数据库写入。

刷新后先向用户做一次简明状态汇报、更新统一项目板，然后在安全边界内自主继续 M1，
不因普通低风险本地步骤反复请求确认。当前业务主线是：
M1/M2 生产验收 → M5 新关键词最小实现 → M3 小批真实数据补证与根词试点
→ G2/G3/G4 → 用户确认后的 G5。

不要继续围绕旧 78 词、旧 126 候选、T67/T68/T69、界面美化或更多只读展示开发。
默认不创建子任务；确有独立 P0/P1 离线模块时，最多创建 1 个精确子任务。

总控独占生产数据库、data、8793/8765、ADB、BlueStacks、小红书真实 UI、真实采集、
批准词生产入队、soak、HANDOFF 和项目板。不得恢复已删除的旧 Excel，不得恢复全部
66 个任务。验证码、风控、ANR、未知页、上下文丢失、身份不明、DB 锁异常或任何
risk/block/skip 出现时立即停止并保留证据。

不得发布、购买、加购、收藏、关注、评论、客服或绕过平台风控。24 小时 soak 和
Windows 计划任务必须在到达对应门槛后再次获得用户明确确认，不能继承旧授权自动启动。
```
