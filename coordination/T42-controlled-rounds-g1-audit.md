# T42：3 个小时级受控轮次 G1 独立只读证据审计

审计时间：2026-07-29（Asia/Shanghai）

## 1. 结论

**G1 判定：通过。**

本结论只针对以下三个明确指定的真实受控轮次：

- `monitor-45c96a5b5e1c`
- `monitor-6e6e0be23652`
- `monitor-01375a7cca15`

按 `src/xhs_scout/soak_readiness.py` 当前实现对这三轮单独筛选后评估：

- `real_round_count=3`
- `successful_round_count=3`
- `risk_count=0`
- `block_count=0`
- `skip_count=0`
- `search_recovery_count=3`
- `real_link_count=3`
- `metrics_result_count=3`
- `active_lease_count=0`
- `running_task_count=0`
- `sqlite_lock_error_count=0`
- G1：`passed`

这不是 G2、G4 或 G5 的通过结论：

- **不能外推为 G2。** 三轮相隔超过 60 分钟、总跨度约 `2.236h`，但数据库轮次没有
  `scheduled_at`，`due_point_count=0`；它们是工作台单轮/API 受控执行，
  `ignore_paused=true`，不是可核验的 scheduler 小时级到期点。
- **不能外推为 G4。** 没有连续 6–8 小时 pre-soak，也没有开始/中点/结束的 digest
  与 quality 快照。
- **不能外推为 G5。** 没有连续 24 小时墙钟、至少 18 个真实开始轮次及 G0–G4
  全部通过证据。
- 本审计也不判定 G0、G3，不授权真实补证、pre-soak、24h soak、计划任务或扩容。

## 2. 审计边界与只读证明

### 2.1 已读取的依据

- `C:\Users\Lenovo\AGENTS.md`
- `PARALLEL_WORK.md`
- `HANDOFF.md` 中 2026-07-29 的第 1/3、2/3、3/3 轮记录
- `coordination/T21-24h-readiness.md`
- `src/xhs_scout/soak_readiness.py`

G1 当前代码口径是：至少 3 个真实轮次；至少 3 个同时满足真实来源、成功结果、
run/task/product/observation 四类 ID、证据路径、搜索恢复、受支持真实链接和任一
认可指标字段的完整成功轮次；不得出现硬风险停止。只要已有至少 3 个真实轮次且其中
存在不完整轮次，G1 即失败。

### 2.2 SQLite 只读快照

生产库：

`C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent\data\xhs_scout.sqlite3`

连接与校验：

| 项目 | 结果 |
| --- | --- |
| SQLite URI | `file:C:/.../data/xhs_scout.sqlite3?mode=ro` |
| `PRAGMA query_only` | `1` |
| `PRAGMA quick_check` | `ok` |
| 快照文件大小 | `1,019,904` bytes |
| 当前 `run_leases` | `0` 行 |
| 当前 `status='running'` 任务 | `0` 行 |

本任务未写数据库、`data/`、源码、测试、配置、`HANDOFF.md` 或
`PARALLEL_WORK.md`；未访问 8793/8765、ADB、BlueStacks、小红书或任何真实采集入口。

## 3. 三轮时间、参数与结果

| 轮次 | 开始—结束 | 时长 | 与上轮结束间隔 | 参数 | task / product / observation |
| --- | --- | ---: | ---: | --- | --- |
| `monitor-45c96a5b5e1c` | 11:19:56—11:21:51 | 115s | 首轮 | `1×1`、wait 6s、metrics 最多 3 帧、swipe=true、note=false、dry_run=false | `18 / 27 / 27` |
| `monitor-6e6e0be23652` | 12:24:12—12:26:07 | 115s | 3,741s（62m21s） | 同上 | `19 / 28 / 28` |
| `monitor-01375a7cca15` | 13:31:35—13:34:06 | 151s | 3,928s（65m28s） | 同上 | `20 / 29 / 29` |

三轮从第一轮开始到第三轮结束的墙钟跨度为约 `2.236h`。每轮开始事件还包含
`allow_back_recovery=true`、`recurring_interval_hours=24`、
`requeue_due_keywords=true`、`ignore_paused=true`。其中
`recurring_interval_hours=24` 是单轮参数，不能证明本次轮次由 scheduler 到期触发。

## 4. 单轮逐项判定

### 4.1 `monitor-45c96a5b5e1c`：通过

- 真实来源：`dry_run=false`，观察来源 `android_emulator_task`。
- ID 链：run 存在；task `18`；product `27`；observation `27`，观察关联
  `product_id=27`。
- 关键词与搜索归属：task 和搜索证据均为 `模考真题`；搜索证据 `id=14`，
  `page_kind=search_results`、`valid=1`、`invalid_reason=null`。
- 商品：`2026全真模考系统高度还原长期更新`。
- 真实链接：`https://xhslink.com/m/2abDO6CVqCp`；通过当前
  `is_supported_product_url()` 校验。
- 指标：观察记录有 `cumulative_sales_min=32`，所以按当前 G1 代码
  `metrics_ok=true`。
- 指标条限制：灰色指标条事件为 `metrics_skipped`，原因是未自动定位 ROI；没有
  盲目滑动。此项不能描述为“指标条采集成功”。
- 搜索恢复：`back_to_search_results`，第 1 次回退成功；probe 显示
  `GlobalSearchActivity`、`page_kind=search_results`、`has_anr=false`、
  `risk_stop_reason=null`、`ui_dump_ok=true`。
- 结果：`processed_tasks=1`、`captured_products=1`、顶层 `skipped=[]`、
  `requeued_tasks=1`、`busy=false`、`blocked=null`、`risk_stop_reason=null`。
- 最终任务：`completed`、`attempts=1`、`last_error=null`、owner/租约为空。
- 证据路径存在：
  - `data/captures/2026-07-29T11-21-09+08-00_emulator-current.png`
  - `data/probes/monitor-45c96a5b5e1c-probe-product-tab/`
  - `data/probes/monitor-45c96a5b5e1c-probe-after-detail-back-1/`
  - `data/metric_strips/2026-07-29T11-21-13+08-00/`
  - `data/reports/candidates-2026-07-29T11-21-51+08-00.md`

### 4.2 `monitor-6e6e0be23652`：通过

- 真实来源：`dry_run=false`，观察来源 `android_emulator_task`。
- ID 链：run 存在；task `19`；product `28`；observation `28`，观察关联
  `product_id=28`。
- 关键词与搜索归属：task 和搜索证据均为 `错题本模板`；搜索证据 `id=15`，
  `page_kind=search_results`、`valid=1`、`invalid_reason=null`。
- 商品：`小初高各科通用40套错题本电子打印版`。
- 真实链接：`https://xhslink.com/m/ABS2pxOP0uZ`；通过当前
  `is_supported_product_url()` 校验。
- 指标：观察记录有 `cumulative_sales_min=131`，所以按当前 G1 代码
  `metrics_ok=true`。
- 指标条限制：灰色指标条事件为 `metrics_skipped`，原因是未自动定位 ROI；没有
  盲目滑动。此项不能描述为“指标条采集成功”。
- 搜索恢复：`back_to_search_results`，第 1 次回退成功；probe 显示
  `GlobalSearchActivity`、`page_kind=search_results`、`has_anr=false`、
  `risk_stop_reason=null`、`ui_dump_ok=true`。
- 结果：`processed_tasks=1`、`captured_products=1`、顶层 `skipped=[]`、
  `requeued_tasks=1`、`busy=false`、`blocked=null`、`risk_stop_reason=null`。
- 最终任务：`completed`、`attempts=1`、`last_error=null`、owner/租约为空。
- 证据路径存在：
  - `data/captures/2026-07-29T12-25-21+08-00_emulator-current.png`
  - `data/probes/monitor-6e6e0be23652-probe-product-tab/`
  - `data/probes/monitor-6e6e0be23652-probe-after-detail-back-1/`
  - `data/metric_strips/2026-07-29T12-25-24+08-00/`
  - `data/reports/candidates-2026-07-29T12-26-07+08-00.md`

### 4.3 `monitor-01375a7cca15`：通过

- 真实来源：`dry_run=false`，观察来源 `android_emulator_task`。
- ID 链：run 存在；task `20`；product `29`；observation `29`，观察关联
  `product_id=29`。
- 关键词与搜索归属：task 和搜索证据均为 `学习计划模板`；搜索证据 `id=16`，
  `page_kind=search_results`、`valid=1`、`invalid_reason=null`。
- 商品：`家庭积分奖励丨学习计划|学霸资料|电子模板可编辑可打印`。
- 真实链接：`https://xhslink.com/m/5eiCxjPPLnq`；通过当前
  `is_supported_product_url()` 校验。
- 指标：观察记录有累计销量 `1976`、近 30 天新增好评 `100`、近 30 天感兴趣
  `1000`；事件为 `metrics_updated`，所以 `metrics_ok=true`。
- 搜索恢复：`back_to_search_results`，第 1 次回退成功；probe 显示
  `GlobalSearchActivity`、`page_kind=search_results`、`has_anr=false`、
  `risk_stop_reason=null`、`ui_dump_ok=true`。
- 结果：`processed_tasks=1`、`captured_products=1`、顶层 `skipped=[]`、
  `requeued_tasks=1`、`busy=false`、`blocked=null`、`risk_stop_reason=null`。
- 最终任务：`completed`、`attempts=1`、`last_error=null`、owner/租约为空。
- 证据路径存在：
  - `data/captures/2026-07-29T13-32-56+08-00_emulator-current.png`
  - `data/probes/monitor-01375a7cca15-probe-product-tab/`
  - `data/probes/monitor-01375a7cca15-probe-after-detail-back-1/`
  - `data/metric_strips/2026-07-29T13-33-04+08-00/`
  - `data/reports/candidates-2026-07-29T13-34-06+08-00.md`

## 5. G1 条款逐条汇总

| G1 条款 | 判定 | 证据 |
| --- | --- | --- |
| 至少 3 个真实受控轮次 | 通过 | 3 个 run 均 `dry_run=false`，均有开始和完成事件 |
| 每轮 1 关键词 × 1 商品 | 通过 | 三轮参数均为 `max_keywords=1`、`max_products_per_keyword=1` |
| run/task/product/observation 完整 | 通过 | `18/27/27`、`19/28/28`、`20/29/29` |
| 搜索关键词归属有效 | 通过 | 三条 `search_result_evidence` 均与 task 关键词一致、`valid=1` |
| 每轮恢复搜索上下文 | 通过 | 三轮均有第 1 次成功的 `back_to_search_results` 和落盘 probe |
| 每轮真实商品链接 | 通过 | 三条 `xhslink.com/m/...` 均通过当前链接校验 |
| 每轮有认可指标结果 | 通过（有限） | 观察记录分别有累计销量 `32`、`131`、`1976`；第三轮另有两项 30 天指标 |
| 每轮证据路径存在 | 通过 | observation、搜索 probe、恢复 probe、metric 目录和报告均存在 |
| 零顶层 skip/block/risk | 通过 | 三轮 `skipped=[]`、block/risk 均空；无 guard pause |
| 结束时任务和租约清理 | 通过 | task 18/19/20 均 completed、无 owner；全库 running task=0、run lease=0 |
| SQLite 无锁异常且可读 | 通过 | 目标轮次无 lock/busy 事件；`quick_check=ok` |

### 指标语义说明

前两轮同时存在以下两个事实：

1. 灰色指标条子步骤为 `metrics_skipped`；
2. 商品详情观察仍解析出累计销量，因此当前 `soak_readiness.py` 将其视为
   `metrics_ok=true`。

二者不是证据冲突，而是“指标条趋势采集”和“详情基础指标解析”两个不同范围。
因此本审计按现行 G1 契约判为通过，但明确不能写成“三轮灰色指标条均成功”或
“三轮都有完整趋势指标”。

## 6. 全库评估与本次范围的区别

若不筛选 run、直接把生产库全部历史轮次交给 `evaluate_sqlite_readiness()`，G1 会因
历史轮次中的风险、不完整证据而失败；当前全库结果为 `22` 个真实轮次、仅 `5` 个
完整成功轮次，并包含 `1` 个历史硬风险。

这不推翻本次 T42 结论：T42 的授权范围是审计明确指定的三个 run，故应先按 run id
筛选再执行 G1 聚合。反过来，本次三个 run 的 G1 通过也不能清除、覆盖或淡化历史
风险记录，更不能代表整个生产库历史全局 G1 已通过。

## 7. 缺口、风险与停止边界

- 前两轮灰色指标条未定位成功，只有基础累计销量；趋势字段覆盖仍不完整。
- 三轮没有 `scheduled_at`，无法证明 scheduler 到期点、启动延迟、冷却游标或丢轮；
  G2 仍为证据不足。
- 未提供 6–8h pre-soak 的三阶段 digest/quality 快照；G4 仍为证据不足。
- 未提供连续 24h、至少 18 轮和 G0–G4 全部通过证据；G5 仍为证据不足。
- 全库历史仍含风险、block、skip 和不完整轮次；不得用本次 scoped pass 覆盖历史。
- 本审计未补证、未触发新的真实轮次，不能作为启动 pre-soak、24h soak、Windows
  计划任务或扩大关键词/商品预算的授权。

## 8. 共享真实状态声明

本任务只读取生产 SQLite 和既有证据文件，仅新建本审计文档。未触碰共享真实状态：
未访问或修改 8793/8765、ADB、BlueStacks、小红书、真实采集、soak、计划任务、
生产数据库、`data/`、源码、测试、配置、`HANDOFF.md` 或 `PARALLEL_WORK.md`。
