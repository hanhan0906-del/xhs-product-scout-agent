# 小红书选品 Agent 并行开发分工

最后更新：2026-07-28（Asia/Shanghai）

## 协作原则

- 当前主对话是唯一集成负责人。
- 只有主对话可以操作 BlueStacks、ADB、小红书、真实数据库、8793 服务和 `HANDOFF.md`。
- 并行对话只做离线代码与测试，不运行真实采集，不修改 `data/`，不重启服务。
- 每个并行任务有独占写入范围。范围外文件只能读取，不能修改。
- 并行对话不得创建重复实现；完成后应列出修改文件、接口、测试结果和集成注意事项。
- 项目当前不是 Git 仓库，因此不依赖分支或 worktree 隔离，完全依靠独占文件范围避免冲突。

## 任务分配

### T1 运行可靠性与任务状态

独占写入：

- `src/xhs_scout/db.py`
- `src/xhs_scout/run_control.py`
- `tests/test_run_control.py`
- 必要时仅补充 `tests/test_workflow.py` 中与数据库状态有关的测试

目标：

- 单实例运行租约，防止两个监控轮次同时控制模拟器；
- 任务失败重试次数、退避冷却和下次可运行时间；
- 崩溃后的过期租约恢复；
- 提供纯粹、清晰的数据库接口，后续由主对话接入 `monitor.py`。

禁止修改：

- `monitor.py`、`workflow.py`、`web.py`、`cli.py`
- 模拟器、截图、真实数据库和服务

### T2 灰色指标条采集质量

独占写入：

- `src/xhs_scout/detail_metrics.py`
- `tests/test_detail_metrics.py`

目标：

- 动态 ROI 排名更稳；
- 多帧 OCR 文本和指标去重；
- 过滤非指标、半截 OCR、冲突值和污染帧；
- 保留已验证参数：`focus_taps=4`、`swipe_pixels=240`、`swipe_ms=900`；
- 所有验证使用已有截图或合成测试，不操作模拟器。

禁止修改：

- 其它源码、数据库、服务、ADB 和 BlueStacks

### T3 候选分析与原创化报告

独占写入：

- `src/xhs_scout/analysis.py`
- `src/xhs_scout/reports.py`
- `tests/test_analysis.py`
- `tests/test_reports.py`

目标：

- 报告包含商品证据、趋势指标、低粉笔记/账号证据；
- 明确风险点、证据缺口和置信度；
- 根据商品标题与类型生成具体、非照抄的原创化方向；
- 不调用外部大模型，不依赖千瓜会员，不改变数据库结构。

禁止修改：

- `db.py`、`web.py`、`monitor.py`、真实数据库和服务

### T4 工作台界面模块

独占写入：

- `src/xhs_scout/workbench_ui.py`
- `tests/test_workbench_ui.py`

目标：

- 输出可由 `web.py` 调用的 `render_workbench_html()`；
- 运营型紧凑界面，包含状态概览、暂停/恢复、单轮运行、候选表格、真实商品链接、独立证据入口和报告入口；
- 不显示运行事件日志；
- 页面文案使用中文，移动端和桌面端均不溢出；
- 只依赖现有 API 路径，不修改后端。

禁止修改：

- `web.py`、其它源码、数据库、服务、ADB 和 BlueStacks

## 主对话集成范围

并行任务完成后，主对话独占处理：

- `monitor.py`、`workflow.py`、`web.py`、`cli.py`、`ui_automation.py`
- 调用 T1 的租约/重试接口；
- 接入 T4 的 HTML 渲染模块；
- 合并 T2 指标采集和 T3 报告；
- 完整测试；
- 安全重启 8793；
- 最多 1 至 3 个商品的真实受控小闭环；
- 更新 `ROADMAP.md` 和 `HANDOFF.md`。

## 冲突处理

- 发现范围外文件已变化时，不回滚、不覆盖，停止写入该文件并在结果中说明。
- 发现接口需要调整时，在本任务独占文件内提供适配层，不直接修改集成文件。
- 任何风控、验证码、登录、交易或互动页面都不属于并行任务范围。
## 第二轮并行拆分（2026-07-28）

主任务仍是唯一集成负责人，并独占真实数据库、8793 服务、ADB、BlueStacks、
小红书真实 UI、`monitor.py`、`scheduler.py`、`web.py`、`cli.py`、`README.md`、
`ROADMAP.md` 和 `HANDOFF.md`。

| 任务 | 负责范围 | 独占写入文件 | 禁止事项 |
| --- | --- | --- | --- |
| T5 | 24 小时运行保障与 Windows 运维脚本 | `ops/*.ps1`、`OPERATIONS.md`、`tests/test_ops_scripts.py` | 不启动/停止进程，不安装计划任务，不碰真实服务 |
| T6 | 广覆盖关键词组合与轮转规划 | `src/xhs_scout/keyword_portfolio.py`、`config/keyword_portfolio.json`、`tests/test_keyword_portfolio.py` | 不查询真实数据库，不操作模拟器 |
| T7 | 每日/每周摘要与告警判断 | `src/xhs_scout/digest.py`、`tests/test_digest.py` | 不发送消息，不写真实报告目录 |
| T8 | 采集数据质量审计 | `src/xhs_scout/quality.py`、`tests/test_quality.py` | 不自动删除、修正或回填真实数据 |

第二轮 Codex 任务：

- T5：`019fa8ec-b4d2-7b70-89e1-31ddb033cd76`
- T6：`019fa8ec-e8b3-7a53-8898-b9a8612524ce`
- T7：`019fa8ed-1a86-75f3-b372-bff45cb5117f`
- T8：`019fa8ed-4e72-7380-97a8-1f54e1856b0c`

第三轮 Codex 任务：

- T9 集成回归测试：`019fa8ff-0934-7401-995b-02b0c3f1c6a5`
  - 独占 `tests/test_integrated_workstation.py`
- T10 调度/关键词轮转边界测试：`019fa8ff-35b6-77e2-ab2e-c8df5f30e13d`
  - 独占 `tests/test_scheduler_portfolio.py`
- T11 文档一致性更新草案：`019fa8ff-607d-7710-8108-3768792d3393`
  - 独占 `coordination/T11-doc-draft.md`
- T12 集成代码只读审查：`019fa8ff-8410-7df2-9e20-ed55b1c99c81`
  - 独占 `coordination/T12-integration-review.md`
- T13 运维脚本 dry-run 验收：`019fa8ff-aeb4-7c83-8b33-833b8348c008`
  - 独占 `coordination/T13-ops-qa.md`

第三轮任务不得修改生产代码、真实数据库或运行中服务；发现缺陷由主任务统一修复。

集成顺序：先审查各模块及独立测试，再由主任务按依赖顺序接入
`db.py` / `scheduler.py` / `reports.py` / `web.py`，最后运行全量测试和一次受控真实调度。

## 第四轮与安全收敛并行拆分（2026-07-28）

第四轮文档、测试与只读盘点：

- README 最终化：`019fa912-39ae-7bb2-9c3a-5d1f93a954d4`
- ROADMAP 最终化：`019fa912-563c-7bf1-9df1-01973026242d`
- HANDOFF 最终草案：`019fa912-7d0b-7a23-8f58-707251d33362`
- SQLite busy timeout：`019fa912-9d3d-7bd2-b7ba-12ae69d898f9`
- 最终静态集成审计：`019fa912-c266-78a3-bc33-0a0716c26b1a`
- 工作站契约测试：`019fa912-f56d-74b0-9887-b338763f2969`
- OPERATIONS 最终化：`019fa913-2d73-7ab1-ab2d-79323b197b4a`
- 生产数据只读质量盘点：`019fa913-52c7-7a71-9d69-d7a462c5883f`
- 跨轮 soak-readiness 测试：`019fa913-77f4-7801-8b82-b4a68308da6a`

静态审计后的安全收敛：

- 安全限制硬熔断：`019fa91e-d475-7021-860f-40d6d1b77672`
- 风险恢复显式确认：`019fa91f-0177-79a3-ae9b-7f0d85cc33fd`
- 商品链接白名单：`019fa91f-2275-7521-b9f4-43c0892b7fd1`
- 首页搜索入口守卫：`019fa91f-479a-7002-aad9-56a78659332c`
- A 级证据文件完整性与 JSON 容错：`019fa91f-6e18-73d1-8a2a-bbd610684167`
- scheduler 生命周期停止标志：`019fa91f-9389-7d82-bcb3-e5f1ea05ecac`
- dashboard 最新观察去重测试：`019fa920-343a-7632-b2fd-a441cbc90ec0`

上述任务均在互不重叠的文件范围内完成；主任务负责修正跨任务旧测试夹具、
补入真实 `xhslink.com/m/...` 链接格式、运行全量测试、重启 8793 和更新正式
`HANDOFF.md`。最终离线测试基线为 `176 passed`。

## 第五轮：受控放大期间的离线并行任务（2026-07-29）

主任务继续作为唯一总控，并独占真实数据库写入、8793、ADB、BlueStacks、小红书
真实 UI、小时级 heartbeat、跨模块集成、完整测试和 `HANDOFF.md`。以下任务只做
互不重叠的离线工作，不得提前触发第 2/3 或第 3/3 轮。

| 任务 | Codex 任务 | 独占写入范围 | 禁止事项 |
| --- | --- | --- | --- |
| T18 当前生产数据补证队列刷新 | `019fac12-0630-7a61-a93a-4dca267b4ab0` | `coordination/T18-live-remediation-queue.md` | 生产库只允许 `mode=ro` + `query_only`；不得改源码、配置、服务或设备 |
| T19 候选报告完整性与无效证据防误用 | `019fac12-4418-75b2-a523-e1c0a6d5b258` | `analysis.py`、`reports.py`、`test_analysis.py`、`test_reports.py`、可选 T19 审计文档 | 不读写生产库，不操作服务或设备 |
| T20 有限虚拟商品关键词池扩展 | `019fac12-79a5-7aa1-aa33-8a8138867b0f` | `keyword_portfolio.py`、`keyword_portfolio.json`、`test_keyword_portfolio.py`、可选 T20 文档 | 不把组合写入真实队列，不执行真实搜索 |
| T21 24 小时监控就绪差距与验收 | `019fac12-ae65-7563-bf70-b4aaadb64e42` | `coordination/T21-24h-readiness.md`、可选新建 `tests/test_24h_readiness.py` | 不改现有源码/测试/运维脚本，不启动 soak、服务、设备或计划任务 |

集成顺序：

1. 主任务先完成第 2/3、3/3 小时级受控轮次并暂停 heartbeat；
2. 审查 T18 的只读事实口径，确定真实补证批次；
3. 审查并集成 T19、T20 的代码和测试，运行定向及完整测试；
4. 用 T21 的门槛决定何时可以从小批量扩到多小时及 24 小时 soak；
5. 任何真实采集扩容仍由主任务逐级执行，不因离线任务完成而自动放量。

## 第六轮：24 小时能力关键缺口并行修复（2026-07-29）

第五轮四项均已完成后，主任务立即启动以下互不重叠任务；真实设备和生产状态仍只由
主任务控制：

| 任务 | Codex 任务 | 独占写入范围 |
| --- | --- | --- |
| T22 scheduler 异常退出检测与有限自恢复 | `019fac19-d38f-7cb2-985c-a54776857150` | `scheduler.py`、`test_scheduler.py`、可选 T22 文档 |
| T23 长步骤租约续期与过期接管安全 | `019fac19-fd4d-7070-af13-6564301124c5` | `run_control.py`、`test_run_control.py`、可选 T23 文档 |
| T24 数据补证批次规划器 | `019fac1a-26ba-7873-8575-8b5d10021563` | 新建 `remediation.py`、`test_remediation.py`、可选 T24 文档 |
| T25 已采商品衍生关键词引擎 | `019fac1a-5166-7600-a138-e0e3d62b5bb1` | 新建 `keyword_discovery.py`、`test_keyword_discovery.py`、可选 T25 文档 |

上述任务全部禁止操作生产数据库、真实队列、服务、ADB、BlueStacks、小红书、soak
和 Windows 计划任务。T22/T23 解决 T21 指出的两个 P0；T24/T25 分别把补证顺序和
“从已采商品不断衍生关键词”的用户目标转成可测试、默认不写生产队列的离线模块。

## 第七轮：只读集成与工作台准备（2026-07-29）

- T26 租约安全接入 monitor：`019fac20-922f-75d3-80d4-d70430471ef6`
  - 独占 `monitor.py`、新建 `test_monitor_lease_safety.py` 和可选 T26 文档。
- T27 衍生关键词只读审核 API：`019fac20-d005-78b0-97d4-e4c58a3d8602`
  - 独占 `web.py`、新建 `test_keyword_discovery_web.py` 和可选 T27 文档。
- T28 跨模块集成契约回归：`019fac28-dd9d-7193-95bc-6454947eca93`
  - 只新建 `test_round6_integration.py` 和 T28 文档。
- T29 工作台衍生关键词只读审核界面：`019fac29-0bf3-7751-9210-c70f9fd982b7`
  - 独占 `workbench_ui.py`、`test_workbench_ui.py` 和可选 T29 文档。
- T30 补证计划只读 API：`019fac29-376b-7570-a414-3783cd084201`
  - 在 T27 当前版本基础上增量修改 `web.py`，新建 `test_remediation_web.py` 和可选
    T30 文档，不得覆盖关键词建议 API。
- T31 pre-soak 证据聚合与准入判定：`019fac29-61cb-7b30-a24e-2b34e6d52fde`
  - 只新建 `soak_readiness.py`、`test_soak_evidence.py` 和可选 T31 文档。

总控 heartbeat 已调整为每 5 分钟检查并行任务并续派；真实采集仍必须满足距离上一轮
至少 60 分钟且总计不超过 3 轮。达到 3/3 后 heartbeat 继续做离线总控，但不得自动
开始补证、pre-soak 或 24 小时 soak。

- T32 关键词衍生质量语料与误报回归：`019fac2e-05cb-71d1-b3bc-ea465da994bf`
  - 只新建 `tests/test_keyword_discovery_corpus.py` 和
    `coordination/T32-keyword-corpus.md`；
  - 不修改现有算法，只用离线语料验证应提取、应过滤、应降级探索层和不写生产队列。

## 第八轮：最新证据语义、补证展示与关键词质量修复（2026-07-29）

- T33 关键词建议 API 最新证据链修复：`019fac33-0767-7472-8ee5-1988e6d904bb`
  - 独占 `web.py`、新建 `tests/test_keyword_latest_evidence.py` 和可选 T33 文档；
  - 最新搜索证据无效时不得回退复活旧的有效归属，同时保留 T27/T30 两个只读接口。
- T34 补证计划只读工作台：`019fac34-24bf-7143-9084-7bbba2ea1a29`
  - 独占 `workbench_ui.py`、`tests/test_workbench_ui.py` 和可选 T34 文档；
  - 展示阶段、批次、隔离项、依赖和预算，不提供执行补证或写队列动作。
- T35 关键词衍生质量缺口修复：`019fac34-c2bf-7a70-b203-6e774172cc33`
  - 独占 `keyword_discovery.py`、`tests/test_keyword_discovery.py` 和可选 T35 文档；
  - 修复同源变体重复计权、OCR 乱码进入探索层和超长标题残缺滑窗三个 T32 缺口。

以上任务全部禁止写生产数据库或真实队列，禁止操作 `data/`、8793/8765、ADB、
BlueStacks、小红书、真实采集、soak 和 Windows 计划任务；主任务继续独占这些真实资源。

## 第九轮：pre-soak 只读准入与离线可靠性回归（2026-07-29）

- T36 清理已修复的 xfail 测试债务：`019fac51-432c-7503-8ec7-806a854687fc`
  - 独占 `tests/test_round6_integration.py`、`tests/test_keyword_discovery_corpus.py`
    和可选 T36 文档；
  - 逐条确认 4 个 XPASS 后改为普通严格测试，不删用例、不降低断言。
- T37 pre-soak 准入只读 API：`019fac51-721d-7883-bc73-20af453d9429`
  - 独占 `web.py`、新建 `tests/test_soak_readiness_web.py` 和可选 T37 文档；
  - fail-closed 返回 G0–G6、缺口和 warnings，不触发或授权 soak。
- T38 scheduler/租约跨模块安全回归：`019fac51-9ec7-7041-94de-bf162800d590`
  - 仅新建 `tests/test_scheduler_lease_integration.py` 和可选 T38 文档；
  - 用临时库和假设备验证异常自恢复、lease-lost 停止设备步骤及 risk stop 保留。
- T39 SQLite 并发压力离线测试：`019fac51-d252-7b13-9122-eb3adb041d26`
  - 仅新建 `tests/test_sqlite_concurrency.py` 和可选 T39 文档；
  - 用临时库模拟多读、短写、租约和任务状态竞争，验证无锁异常且 `quick_check=ok`。

第九轮同样禁止触碰生产数据库、`data/`、8793/8765、ADB、BlueStacks、小红书、
真实采集、pre-soak/24h soak 和 Windows 计划任务。主任务在第 3/3 轮门槛到达前
继续保持真实环境静止。

## 第十轮：三轮后只读审计与 pre-soak 可见性（2026-07-29）

- T40 soak readiness 只读工作台：`019fac5f-b165-77a2-938c-abd0196807fe`
  - 独占 `workbench_ui.py`、`tests/test_workbench_ui.py` 和可选 T40 文档；
  - 展示 G0–G6、gaps、warnings 和未授权状态，不新增启动或授权动作。
- T41 三轮后补证队列只读刷新：`019fac5f-de71-72d1-8f14-d846fa916482`
  - 仅新建 `coordination/T41-post-round-remediation-queue.md`；
  - 生产 SQLite 仅允许 `mode=ro` + `query_only`，刷新 identity→metrics→note→profile
    的数量、商品 ID、隔离项和批次预算。
- T42 三个受控轮次 G1 证据审计：`019fac60-0d42-7551-8da8-35150ef2430b`
  - 仅新建 `coordination/T42-controlled-rounds-g1-audit.md`；
  - 只读核对三轮的间隔、参数、证据链、恢复、风险和最终租约状态，fail closed 判定 G1。
- T43 人工告警 ACK 离线记录模块：`019fac60-621c-77c1-98c1-7e94317c4a2a`
  - 新建 `soak_ack.py`、`tests/test_soak_ack.py` 和可选 T43 文档；
  - 仅用临时目录验证追加审计、路径约束、敏感字段拒绝和缺 ACK fail closed，不接入生产。

第 3/3 轮已经完成，因此第十轮及后续 heartbeat 不得再触发真实受控轮次，也不得
自动开始补证、monitor-loop、pre-soak 或 24 小时 soak。主任务继续独占真实数据库
写入、`data/`、8793/8765、ADB、BlueStacks、小红书和 `HANDOFF.md`。

## 第十一轮：ACK 准入、补证审批与 G2 证据契约（2026-07-29）

- T44 ACK 接入 soak readiness：`019fac68-83cb-7f20-81cd-908eb3192ace`
  - 独占 `soak_readiness.py`、`tests/test_soak_evidence.py` 和可选 T44 文档；
  - critical/error 缺 ACK、非 acknowledge、坏账本或证据不匹配时 fail closed。
- T45 补证审批清单与预算/隔离校验：`019fac68-c631-72c1-84e3-cabaa26cf38c`
  - 新建 `remediation_approval.py`、`tests/test_remediation_approval.py` 和可选 T45 文档；
  - 只批准计划，不执行补证；强制阶段顺序、每批 2、每小时 6、quarantine 和依赖。
- T46 scheduler 到期点证据记录：`019fac68-f763-7f50-b4a3-21837a287d83`
  - 新建 `scheduler_evidence.py`、`tests/test_scheduler_evidence.py` 和可选 T46 文档；
  - 追加式记录 scheduled/start/finish、run/lease/风险/证据路径，模拟记录不得晋级。
- T47 ACK fail-closed 接入 soak readiness Web API：`019fac71-6b29-7560-a2c2-e9720e4f2634`
  - 独占 `web.py`、`tests/test_soak_readiness_web.py` 和可选 T47 文档；
  - 只读固定项目内 ACK 账本，缺失/损坏/拒绝/延后/ID 不匹配均关闭准入，
    API 始终保持 `soak_start_authorized=false`。
- T48 补证规划→审批跨模块安全契约：`019fac71-f22f-7cb0-9ec3-b25cc971a759`
  - 仅新建 `tests/test_remediation_approval_integration.py` 和可选 T48 文档；
  - 验证审批不等于执行、计划变更使旧审批失效、隔离/预算/依赖不能被跨模块绕过。
- T49 scheduler evidence 接入 G2/G4 readiness：`019fac76-619f-7f21-9e84-a71c46f8b14d`
  - 独占 `soak_readiness.py`、`tests/test_soak_evidence.py` 和可选 T49 文档；
  - 调用方必须显式提供预期到期点，缺点、模拟来源、延迟/风险/线程/DB/HTTP/ACK
    异常均 fail closed，不能从已有事件反推计划。
- T50 工作台展示 ACK 与 scheduler evidence：`019fac80-0a7f-7f12-be65-ff77770f6eec`
  - 独占 `workbench_ui.py`、`tests/test_workbench_ui.py` 和可选 T50 文档；
  - 只读展示 ACK 完整性及 G2/G4 到期点缺失/模拟/延迟/风险状态，不新增操作入口。
- T51 补证审批清单只读 API：`019fac80-603b-7bb2-90ca-7499a7e1793f`
  - 独占 `web.py`、新建 `tests/test_remediation_approval_web.py` 和可选 T51 文档；
  - 固定读取项目内清单并与生产库只读重算 planner hash 比较，缺失/篡改/过期/越界
    一律 fail closed，绝不提供批准、写队列或执行入口。
- T52 ACK + scheduler evidence + readiness 端到端回归：`019fac81-01f0-7912-82d2-d62f94d5948b`
  - 仅新建 `tests/test_readiness_evidence_integration.py` 和可选 T52 文档；
  - 验证只有完整 ACK、显式预期点、真实来源及健康状态全部满足时 G2/G4 才能通过。

## 第十二轮：G2 Web 可见性、审批展示与 pre-soak 基线（2026-07-29）

- T53 scheduler evidence 接入 readiness Web：`019fac8a-e983-7f20-b136-2faee259fa7f`
  - 独占 `web.py`、`tests/test_soak_readiness_web.py` 和可选 T53 文档；
  - 固定读取项目内 evidence 账本与显式 expected 文件，禁止从历史事件反推到期点。
- T54 工作台展示补证审批清单：`019fac8b-1e1a-7680-b4b0-ce62aafd4245`
  - 独占 `workbench_ui.py`、`tests/test_workbench_ui.py` 和可选 T54 文档；
  - 只读展示清单缺失/过期/损坏、预算/隔离/依赖及 not_executed，不提供操作入口。
- T55 pre-soak 离线基线清单：`019fac8b-61ff-75a1-afd1-013f1cf904c7`
  - 新建 `soak_baseline.py`、`tests/test_soak_baseline.py` 和可选 T55 文档；
  - 生成代码/配置/DB 统计/owner/参数/停止入口的确定性清单，拒绝敏感字段且永不授权启动。

第十二轮仍禁止生产数据库、`data/`、8793/8765、ADB、BlueStacks、小红书、真实补证/
采集、pre-soak/24h soak 和计划任务；所有验收只使用临时项目、临时数据库或纯对象。

## 第十三轮：基线准入、证据包与只读界面契约（2026-07-29）

| 任务 | 依赖 | 独占写入范围 | 交付与验收 | 停止条件 |
| --- | --- | --- | --- | --- |
| T56 baseline 接入 readiness（`019fac95-3685-7690-8cc3-b7eb85b85f00`） | T55 | `src/xhs_scout/soak_readiness.py`、`tests/test_soak_evidence.py`、可选 T56 文档 | 读取调用方显式提供的 baseline 清单；缺失、篡改、过期或任何授权位为真时 fail closed；定向与完整离线测试通过 | 需要触碰 Web、真实数据库、服务或现有 baseline 模块时停止升级 |
| T57 pre-soak 证据包聚合器（`019fac95-61c2-7ab2-aa13-ceb19fcd5605`） | T43/T45/T46/T49/T55 | 仅新建 `src/xhs_scout/soak_evidence_bundle.py`、`tests/test_soak_evidence_bundle.py`、可选 T57 文档 | 纯对象/临时目录聚合 baseline、ACK、scheduler、approval、readiness 的哈希和状态；确定性、拒绝敏感字段、永不授权启动 | 需要生成真实证据、读取生产库或改变任一现有模块时停止升级 |
| T58 readiness API + 工作台只读契约回归（`019fac95-a4c8-76a0-bd77-ad7d6cc9af73`） | T53/T54 | 仅新建 `tests/test_readiness_workbench_contract.py`、可选 T58 文档 | 临时项目验证 readiness/approval API 与工作台展示一致，缺文件 fail closed，页面无批准/执行/soak 动作入口 | 发现源代码缺陷只报告，不越界修改源代码或既有测试 |

第十三轮全部禁止生产数据库、`data/`、8793/8765、ADB、BlueStacks、小红书、真实
补证/采集、pre-soak/24h soak 和 Windows 计划任务；主任务在创建后补录任务 id，
并负责检查实际文件、定向测试和完整回归。

- T59 baseline → readiness 跨模块安全回归（`019fac9e-6870-74d1-97d5-efb9b61c4169`）
  - 依赖：T55、T56；
  - 独占写入：仅新建 `tests/test_baseline_readiness_integration.py` 和可选
    `coordination/T59-baseline-readiness-integration.md`；
  - 验收：临时项目覆盖确定性 baseline、对象/路径输入、代码/config 漂移、owner、
    stop-entry、DB quick_check、1×1 参数和所有授权位的 fail-closed 传递，完整测试通过；
  - 停止条件：发现源代码缺陷只保留失败证据并升级，不得修改现有源码或测试。

- T60 baseline 固定路径接入 readiness Web（`019fac9f-127f-7850-9068-930a52b9098e`）
  - 依赖：T53、T55、T56、T58；
  - 独占写入：`src/xhs_scout/web.py`、`tests/test_soak_readiness_web.py` 和可选
    `coordination/T60-baseline-readiness-web.md`；
  - 验收：GET `/api/soak-readiness` 仅从项目内固定 baseline 路径只读接入，缺失/
    损坏/漂移均 fail closed，响应仍永不授权 soak，且 T53 scheduler/ACK 契约不回归；
  - 停止条件：需要生成真实 baseline、读取生产数据之外的共享状态、修改工作台或触碰
    服务/设备时停止升级。

- T61 衍生关键词人工审批清单（`019faca3-4ee7-7d12-bbc8-f919a73379e8`）
  - 依赖：T25、T27、T29、T35；
  - 独占写入：仅新建 `src/xhs_scout/keyword_approval.py`、
    `tests/test_keyword_approval.py` 和可选 `coordination/T61-keyword-approval.md`；
  - 验收：把离线 suggestion 集合转为确定性人工审核清单，区分 core/exploration、
    保留来源/证据哈希/拒绝理由，限制批准数量与词长，旧建议变化使审批失效；清单仅
    表示人工选择，不写生产队列、不授权真实搜索；
  - 停止条件：需要修改现有关键词算法/API/UI、访问生产库或真实小红书环境时停止升级。

- T62 pre-soak 证据包跨模块集成回归（`019faca3-ed75-7d91-95a3-7a6421e728eb`）
  - 依赖：T43、T45、T46、T49、T55–T57；
  - 独占写入：仅新建 `tests/test_soak_evidence_bundle_integration.py` 和可选
    `coordination/T62-soak-evidence-bundle-integration.md`；
  - 验收：用各现有模块真实生成的临时 baseline/ACK/scheduler/approval/readiness
    组成 bundle，验证任一来源缺失、篡改、过期或状态降级都会使包不完整，且完整包仍
    不产生执行或 soak 授权；
  - 停止条件：发现源缺陷只报告，不修改现有源码/测试，不触碰真实证据和运行状态。

- T63 工作台展示 baseline 准入状态（`019faca8-4fea-7bd2-a3c7-852957aec840`）
  - 依赖：T54、T56、T58、T60；
  - 独占写入：`src/xhs_scout/workbench_ui.py`、`tests/test_workbench_ui.py` 和可选
    `coordination/T63-baseline-workbench.md`；
  - 验收：只读展示 baseline 的 source/integrity/id/hash、缺失/损坏/漂移、owner、
    stop-entry、DB quick_check 与 1×1 参数缺口；无上传、生成、批准或启动按钮；
  - 停止条件：需要修改 API/readiness/baseline 模块或触碰真实服务、数据、设备时停止。

- T64 关键词审批清单只读 API（`019facae-3ca3-7212-8663-42771236efc8`）
  - 依赖：T27、T33、T35、T61；
  - 独占写入：`src/xhs_scout/web.py`、仅新建
    `tests/test_keyword_approval_web.py` 和可选 `coordination/T64-keyword-approval-web.md`；
  - 验收：GET-only 固定读取项目内关键词审批清单，并用临时/只读建议集合校验来源哈希、
    词数/层级/状态与过期；缺失/损坏/漂移 fail closed，所有入队/搜索授权恒为 false；
  - 停止条件：需要修改关键词算法、工作台、生产队列或操作服务/设备时停止升级。

- T65 修复 T62 证据包四项 fail-closed 缺口（`019facaf-b905-7c02-a140-6ca1d6ec4172`）
  - 依赖：T57、T62；优先级：集成红灯修复；
  - 独占写入：`src/xhs_scout/soak_evidence_bundle.py`、
    `tests/test_soak_evidence_bundle.py`、`tests/test_soak_evidence_bundle_integration.py`
    和可选 `coordination/T65-soak-bundle-fixes.md`；
  - 验收：重新校验 baseline 观察文件；按显式 assembled_at/时限判断审批过期；通过
    显式 current plan hash 检测计划漂移（不得凭空推断）；验证 readiness 顶层 ready
    与 gates 一致；T62 四项失败转绿且完整回归无新增失败；
  - 停止条件：需要读取生产状态、修改其他模块或以删除/放宽断言掩盖失败时停止升级。

- T66 关键词衍生 → 人工审批跨模块回归（`019facb3-48e8-7c12-bb42-9a1cb94bce8d`）
  - 依赖：T25、T35、T61；
  - 独占写入：仅新建 `tests/test_keyword_approval_integration.py` 和可选
    `coordination/T66-keyword-approval-integration.md`；
  - 验收：用真实衍生模块的离线 suggestions 生成审批清单，覆盖 core/exploration、
    同源去重、OCR/乱码过滤、来源或证据变化使审批失效、未知词/超预算拒绝，且无队列
    写入和搜索授权；
  - 停止条件：发现源缺陷只保留严格失败证据，不修改现有算法、审批模块或既有测试。

- T67 工作台展示关键词审批清单（`019facbd-55d0-7c51-a06d-5b73e20e2245`）
  - 依赖：T29、T54、T61、T64；
  - 独占写入：`src/xhs_scout/workbench_ui.py`、`tests/test_workbench_ui.py` 和可选
    `coordination/T67-keyword-approval-workbench.md`；
  - 验收：在关键词池区域只读展示审批清单缺失/损坏/过期/漂移、core/exploration、
    approved/rejected/pending、issues/warnings，并明确不写队列、不执行搜索；无批准、
    入队、搜索或 monitor 控件；
  - 停止条件：需要修改 API/审批模块/关键词算法或触碰真实数据、服务、设备时停止升级。

- T68 pre-soak 证据包只读 API（`019facbe-378d-70d1-9ca2-a135b5ef1cc9`）
  - 依赖：T57、T60、T65；
  - 独占写入：`src/xhs_scout/web.py`、仅新建
    `tests/test_soak_evidence_bundle_web.py` 和可选 `coordination/T68-soak-bundle-web.md`；
  - 验收：GET-only 固定读取项目内证据包并调用 T65 完整校验；缺失/坏 JSON/哈希篡改/
    incomplete/not_ready fail closed，展示来源状态与 gaps；所有执行和 soak 授权恒为 false；
  - 停止条件：需要生成/写入真实证据包、修改 bundle 模块/工作台或触碰服务、设备时停止。

- T69 关键词审批显式时间与新鲜度契约（`019facbf-1575-7d22-8ff8-a8e473277de2`）
  - 依赖：T61、T64、T66；
  - 独占写入：`src/xhs_scout/keyword_approval.py`、
    `tests/test_keyword_approval.py` 和可选 `coordination/T69-keyword-approval-time.md`；
  - 验收：清单由调用方显式提供带时区生成/审核时间并纳入哈希，拒绝未来/无时区时间；
    保持旧安全契约与 T64 只读 Web 兼容，不再需要把文件 mtime 当成权威审批时间；
  - 停止条件：需要修改 Web/UI/算法或破坏既有清单读取兼容时停止并升级给总控。

## 2026-07-29 15:20 暂停检查点

- 用户因并行任务 token 消耗过高，要求项目暂时停工；总控不得续派新任务。
- 总控 heartbeat `automation` 已改为 `PAUSED`。
- T18–T66 已完成；T62 暴露的四项证据包缺口已由 T65 修复。
- 最近一次已确认的完整离线基线为 `562 passed, 3 skipped`。
- T67 已停在半成品检查点：
  - 已修改 `src/xhs_scout/workbench_ui.py`、`tests/test_workbench_ui.py`；
  - 定向与相邻回归 `66 passed`；
  - 尚未完成完整 pytest、有效 JavaScript 检查和最终差异复核，因此不得计为完成。
- T68、T69 均只完成只读调研，没有修改文件、没有运行测试。
- 三个任务均已停止且未触碰生产数据库、`data/`、8793/8765、ADB、BlueStacks、
  小红书、真实队列、采集、补证、soak 或 Windows 计划任务。
- 恢复项目前，应先决定保留还是回退/完成 T67 半成品；在此之前不要重启 8793 加载
  新代码，也不要开启新的并行批次。

第十一轮只做临时目录和纯对象离线验证，禁止生产数据库、`data/`、8793/8765、
ADB、BlueStacks、小红书、真实补证/采集、pre-soak/24h soak 和计划任务；真实状态及
`HANDOFF.md` 仍由主任务独占。
