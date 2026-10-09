# T21：24 小时自动监控就绪差距与验收方案

最后更新：2026-07-29（Asia/Shanghai）

## 1. 结论

当前代码已经具备保守小时级调度、全局/任务租约、任务失败退避、24 小时关键词
冷却、硬风险暂停、摘要/质量只读审计、工作台启停与健康检查等基础机制；现有相关
离线测试加上 T21 新增测试共 `39 passed`。

但“机制存在”不等于“24 小时自动监控已就绪”。当前至少还有三个 P0 门槛：

1. **先取得连续真实小轮次与多小时证据。** T21 不读取或改写真实库，不认领主任务
   正在执行的第几轮；实际 3–5 个受控单轮、3–5 个小时级轮次和对应 run/product/
   observation 证据必须由主任务确认。
2. **调度线程异常退出后的自恢复仍不闭环。** `MonitorScheduler._run()` 没有轮次级
   异常捕获/重启监督；一次未处理异常或超过 10 秒的 SQLite 锁可能结束线程。
   8793 进程仍健康时，现有启动脚本会幂等退出，计划任务也不一定能发现“Web 活着、
   scheduler 死了”。这会形成静默停跑。
3. **长设备步骤中的租约续期与超时证据不足。** 全局租约只在每个任务开始前续期，
   任务租约在 `monitor.py` 的设备处理阶段没有周期延长。若单个 UI/ADB/OCR 步骤
   卡住超过租约 TTL，旧执行者仍存活时可能出现租约过期接管风险。

因此当前判定为：**尚不可开始 24 小时 soak；可继续 1 词/1 商品的受控轮次，并按
本文分阶段补齐门槛。**

## 2. 审计边界与证据

本任务只做离线审计和测试设计：

- 未读取或写入生产数据库、`data/` 和真实运行状态；
- 未启动 8793/8765、soak、ADB、BlueStacks、小红书或 Windows 计划任务；
- 未修改现有源码、现有测试、运维脚本、`HANDOFF.md`；
- 新增测试只使用 `tmp_path`、假监控函数和临时 SQLite。

审计文件：

- `scheduler.py`、`run_control.py`、`monitor.py`、`digest.py`、`quality.py`；
- `db.py` 中租约、WAL、busy timeout 和状态接口；
- `web.py` 中 scheduler 生命周期；
- 现有 run-control、scheduler、soak-readiness、digest、quality、ops 测试。

离线结果：

| 测试批次 | 结果 | 说明 |
| --- | --- | --- |
| 修改前相关基线 | `37 passed in 1.60s` | 现有租约、退避、调度、摘要和质量测试 |
| 加入 T21 后相关基线 | `39 passed in 2.28s` | 新增 24 个模拟周期与真实双写连接竞争测试 |

新增测试的 24 个周期是**结构模拟**，没有等待 24 小时，不能当作 24 小时运行证据。

## 3. 八项就绪差距

| 维度 | 已有机制/离线证据 | 当前缺口 | 进入 24h 前的硬门槛 |
| --- | --- | --- | --- |
| 连续轮次 | 默认每轮 1 词/1 商品；离线模拟 24 个周期保持预算、轮转且最终暂停 | 模拟周期不含真实 UI、网络、OCR、磁盘和墙钟漂移；主任务实时轮次进度不归 T21 所有 | 先完成 3–5 个安全受控单轮，再完成 3–5 个真实小时级轮次；每轮都有 run/task/product/observation 与证据目录 |
| 租约/崩溃恢复 | 单一全局租约；第二 owner 被拒；过期租约可接管；未完成任务在正常 `finally` 中失败回收；任务过期可回到 pending/人工态 | 没有“进程硬退出”后的真实恢复演练；长设备操作期间无周期租约心跳；过期接管不能证明旧进程已停止碰设备 | 完成一次受控故障演练：旧进程确实终止、租约到期、任务恢复、只有新 owner 操作；任何 owner 重叠或 lease lost 立即失败 |
| SQLite 竞争 | WAL、10 秒 `busy_timeout`；T21 临时库验证第二写者在锁释放后成功提交 | 只有短锁竞争；`connect()` 每次执行 schema/pragma，监控轮次有多次短连接；无持续 API 读 + scheduler 写压力；无 `database is locked` 计数或线程自愈 | 离线并发压力测试无锁错误；6–8h 阶段中记录所有 DB 异常，零未处理 `OperationalError`、零损坏、零不可解释写入丢失 |
| 关键词冷却 | portfolio 有 24h 冷却、规范化/轮转；scheduler 默认关闭旧 recurring requeue，避免双重补队；已有冷却和跨轮测试 | 未验证真实墙钟 24h 边界、时区/重启后轮转游标和小词池耗尽行为；“完成后 +3600 秒”并非整点调度 | 3–5 小时与 6–8h 阶段零冷却内重复；每轮保存 selected/deferred/reason/cursor；先确认接受“上一轮结束后再等 1h”的保守节奏 |
| 失败退避 | 默认 3 次；300s、600s 指数退避，最高 3600s；预算耗尽进 `needs_manual_detail`；离线验证每轮释放租约 | 未验证真实错误分类是否都应重试；冷却中的旧任务可能与 portfolio 新任务并存；摘要依赖调用方提供连续失败字段 | 受控注入 1 个可重试失败和 1 个不可自动恢复场景；时间、attempt、next_run_at、最终状态均正确；不得形成无预算重试 |
| 风险熔断 | captcha/风控/ANR/禁区等 hard stop 写 `risk_stop_reason` 并暂停；普通 resume 和 `ignore_paused` 不能越过；显式风险原因匹配后才可恢复 | 真实多小时中尚未证明所有危险页面都能触发；软阻塞与硬风险的运营处置仍需人工证据 | 任一硬风险立即结束当前阶段；保留截图/probe/日志/状态，不自动恢复；恢复必须由人工核页并精确确认当前 reason |
| 摘要/质量告警 | digest 能报风控、失败率、连续失败、心跳陈旧、数据陈旧；quality 输出 error/warning/info 和 code 汇总；工作台/API 可读 | 当前是按需生成/展示，不是独立推送或强制熔断；质量 error 不会自动停止 scheduler；无“告警已被看到/处理”的 ACK 证据 | 每阶段结束生成 daily digest + quality snapshot；critical 或 quality error 必须人工判定；未 ACK 不得晋级。24h 内至少保存开始/中点/结束三组快照 |
| 工作台存活/恢复 | lifespan 在 `desired_state=running` 时启动 scheduler；退出时 stop；健康检查覆盖 8793 三个 HTTP 入口；启动脚本有所有权校验；计划任务脚本默认 dry-run | Web 活着但 scheduler 线程死掉时，端口/HTTP 可能仍为 2xx；现有计划任务只恢复工作台进程，且尚未安装；安装需用户批准 | 增加或验证 scheduler-dead 检测与恢复闭环；受控验证进程退出后 15 分钟内恢复；8793/8765 所有权不混淆；安装计划任务前必须用户明确确认 |

## 4. 关键实现风险说明

### 4.1 调度不是固定整点

`next_run_at` 在一轮结束后设置为“当前时间 + interval”。因此一轮耗时会累加到下一
轮，24 小时墙钟窗口不保证恰好 24 次运行。验收必须同时记录：

- 真实墙钟持续时间；
- 每个 `next_run_at` 与实际开始时间；
- 实际到期决策点数量和完成数量。

不应把 `recurring_interval_hours=24`、24 个模拟周期或计划任务每 15 分钟触发误写成
“已完成 24 小时监控”。

### 4.2 静默停跑是当前最大自动化缺口

若 `monitor_once()` 抛出未处理异常，scheduler 线程会退出。`finally` 通常会把
`scheduler_running` 写回 false，但 8793 仍可能在线；仅检查端口和 HTTP 2xx 不足以
证明监控仍运行。开始 24h 前，主任务至少需要一个可验证的判断：

```text
desired_state=running
AND scheduler.thread_alive=false 或 scheduler_running=false
=> 健康失败、产生告警、执行受控恢复或保持暂停等待人工
```

不能只依赖“启动脚本发现 8793 已存在后成功退出”。

### 4.3 租约必须覆盖最长设备步骤

1 词/1 商品的全局租约下限是 900 秒，任务租约默认也是 900 秒。当前续全局租约发生
在任务处理开始前，而不是 ADB/UI/OCR 长步骤中。24h 前应满足二者之一：

- 每个外部步骤有明确超时，最坏总耗时显著小于租约 TTL；或
- 长步骤期间有 owner 匹配的周期 heartbeat/extend，并在 lease lost 时停止碰设备。

否则“过期可接管”可能在旧执行者仍卡住时变成双控制风险。

## 5. 分阶段验收矩阵

| 阶段 | 规模 | 目标 | 通过条件 | 失败后的动作 |
| --- | --- | --- | --- | --- |
| G0 离线门槛 | 临时库、假设备/假 monitor | 证明结构、租约、退避、冷却、熔断、摘要、质量和 SQLite 基础行为 | 相关测试全绿；补充并发压力；没有依赖真实 `data/` | 修代码/测试后重跑，不进入真实轮次 |
| G1 受控连续单轮 | 3–5 次；每次 1 词/1 商品；人工在场 | 验证搜索归属、商品页、指标、返回路径和证据落盘 | 每轮安全结束；零错链/禁区；每轮证据字段完整；暂停后任务真正返回 | 任一硬风险立即停；普通失败最多按 3–5 组受控实验预算处理 |
| G2 小时级连续轮次 | 3–5 个到期决策点；仍为 1×1 | 验证冷却、轮转、退避、scheduler 状态与墙钟漂移 | 100% 到期点有结果；零冷却内重复；零双跑；heartbeat/next_run_at 可解释 | 丢轮、线程死、锁异常或状态不一致则退回 G0/G1 |
| G3 恢复与告警演练 | 离线注入 + 1 次主任务受控真实演练 | 验证崩溃租约恢复、scheduler-dead 识别、Web 恢复、风险后人工恢复 | 旧 owner 已终止；恢复时间和 owner 链可追溯；告警可见；无自动清除风险 | 任一重叠 owner、风险绕过或静默停跑即 P0，不进入长跑 |
| G4 6–8h 预 soak | 1×1，人工可随时介入 | 暴露 SQLite、日志、漂移、工作台/线程存活和数据质量问题 | 全部到期点有记录；零安全事件；零未处理 DB 错误；开始/中点/结束质量快照可解释 | 终止并保留证据；修复后从 G2 重新累计 |
| G5 24h soak | 连续墙钟 ≥24h；仍为 1×1，不扩词量 | 验证完整昼夜的稳定性和恢复能力 | 满足第 7 节全部准入；用户批准所需外部恢复配置；全程可审计 | 任一硬停止条件即结束本次 soak；修复后重新开始完整窗口 |
| G6 扩容评估 | 仅在 G5 通过后讨论 | 判断是否可到每轮 3–5 词 | 另立预算、租约 TTL、风控和 DB 压力验收；用户再次确认 | 不因 G5 通过自动扩容 |

## 6. 开始 24h soak 的准入清单

以下项目必须全部为“是”：

1. G0–G4 已通过，且证据文件路径可打开。
2. 主任务确认 3–5 个受控单轮和 3–5 个小时级轮次的真实 ID。
3. scheduler 未处理异常后的监测/恢复方案已实现并离线验证。
4. 最长外部步骤超时小于租约安全余量，或已实现周期续租和 lease-lost 停止。
5. 并发 SQLite 压力无锁错误；备份/磁盘空间检查由主任务完成。
6. 风险恢复仍需人工明确确认，任何自动恢复不得清除 `risk_stop_reason`。
7. daily digest 与 quality snapshot 的保存位置、检查人和 ACK 方式已确定。
8. 若需要 Windows 计划任务，用户已明确批准安装，且主任务已验证任务定义、8793
   所有权、15 分钟恢复与 8765 隔离。
9. soak 开始前保存代码/配置指纹、运行参数和初始数据库只读快照统计。
10. 明确值守人、停止入口和“暂停不会强杀已进入设备操作的当前轮次”这一事实。

## 7. 24 小时通过标准

### 7.1 必须同时满足

- 墙钟持续时间不少于 24 小时，开始和结束时间均带时区；
- 始终保持 `max_keywords=1`、`max_products_per_keyword=1`；
- 从每轮结束后记录的 `next_run_at` 计算到期点，**每个到期点都有运行、busy、
  明确跳过或停止结果**，不得有无记录的丢轮；
- 实际开始相对 `next_run_at` 的延迟不超过 15 分钟；24h 内至少有 18 个真实轮次
  开始，防止以超长卡顿掩盖“持续在线”；
- 零验证码/风控绕过、零未知页面继续操作、零交易/互动入口、零错关键词归属；
- 零同时控制设备的 owner；所有租约获取、续期、释放/过期接管可解释；
- 零未处理 SQLite 锁异常、零数据库损坏、零不可解释的 running 任务；
- 工作台健康采样成功率至少 96%，不得连续失联超过 15 分钟；任何恢复都有恢复事件；
- `desired_state`、`scheduler_running`、`thread_alive` 三者无持续矛盾；
- 开始/约 12h/结束的 digest 和 quality 快照均生成；critical、error 和 warning 有
  人工结论，未处理 critical/error 为不通过；
- 结束时主动暂停，等待当前轮次返回，确认 scheduler 停止、`next_run_at=null`，
  再形成结论。

### 7.2 不算通过的情况

- 只跑了 24 个快速模拟周期；
- 只看计划任务存在或 8793 端口在线；
- 只看 `desired_state=running`，未检查 scheduler 线程；
- 中途硬风险后自动清除原因继续累计；
- 缺少 run id、时间、任务状态或证据目录；
- 发生中断后把前后两段拼成“连续 24 小时”；
- 为追求次数临时扩大关键词、商品数或缩短安全等待。

## 8. 停止条件

### 8.1 立即硬停止并保留现场

- 验证码、操作频繁、账号风控、安全限制；
- ANR、未知页、禁区、离开搜索流程且无法解释；
- 关键词归属不一致或商品页所有权无法确认；
- 任何交易、互动、发布入口被触发或即将被触发；
- 两个 owner 可能同时控制设备、lease lost 后仍继续设备操作；
- 数据库损坏、状态回退、任务 owner 无法解释；
- 8765 被触碰或 8793 所有权不明。

### 8.2 判定本阶段失败并停止累计

- scheduler 线程退出但没有在 15 分钟内被检测；
- 任一到期点无结果，或启动延迟超过 15 分钟；
- `database is locked/busy` 超过 10 秒并传播为未处理异常；
- heartbeat 超过“计划间隔 + 15 分钟”仍未更新且没有明确 paused/blocked 解释；
- 同一关键词在 24h 冷却内被非人工授权重复入队；
- 单任务超过重试预算仍被自动重试；
- 质量 error、critical digest 告警未 ACK；
- 连续两个真实轮次失败，或整体失败/需人工率达到 20%；
- 工作台连续失联超过 15 分钟或恢复动作不能证明进程所有权。

停止后不得为了“凑满 24 小时”直接续跑。保存状态和证据，修复后从相应前置阶段
重新验收。

## 9. 每轮证据字段

建议每个决策点保存一条 JSONL/CSV 记录，至少包含：

```text
soak_id
sequence
scheduled_at
started_at
finished_at
duration_seconds
start_delay_seconds
run_id
task_id
keyword
keyword_source
portfolio_cursor_before
portfolio_cursor_after
portfolio_selected
portfolio_deferred_reason
attempt
max_attempts
task_status_before
task_status_after
next_run_at
run_lease_owner
run_lease_acquired_at
run_lease_heartbeat_at
run_lease_expires_at
run_lease_release_or_takeover
task_lease_owner
task_lease_expires_at
processed_tasks
captured_products
busy
blocked
skip_reason
risk_stop_reason
last_block_reason
last_skip_reason
monitor_last_heartbeat
scheduler_running
scheduler_thread_alive
workbench_pid
http_status_api_status
http_status_monitor_status
http_status_candidates_csv
sqlite_error
product_id
observation_id
report_path
probe_or_evidence_path
quality_issue_count
quality_error_count
digest_alert_count
operator_ack
notes
```

凭据、Cookie、验证码、令牌不得进入记录。

## 10. 24 小时 soak 记录模板

```markdown
# 24h soak 记录

## A. 会话元数据

- soak_id：
- 开始时间（Asia/Shanghai）：
- 计划结束时间：
- 实际结束时间：
- 执行模式：8793 内置 scheduler / 其他（必须说明）
- 项目根目录：
- Python/依赖基线：
- 代码与配置指纹：
- 数据库路径（只记录路径，不复制敏感内容）：
- 关键词配置版本/哈希：
- 参数：interval_seconds=3600, max_keywords=1, max_products_per_keyword=1
- 8793 owner PID/命令行摘要：
- 8765 隔离检查：
- Windows 计划任务状态：
- 用户对外部配置动作的确认记录：
- 值守人/停止入口：

## B. 开始前快照

- desired_state：
- scheduler_running：
- scheduler.thread_alive：
- next_run_at：
- risk_stop_reason：
- last_block_reason：
- last_heartbeat：
- 当前 run lease：
- running/pending/manual tasks：
- health_check 结果：
- digest 路径/告警：
- quality 路径/error-warning-info：
- 可用磁盘与日志大小：

## C. 轮次记录

| # | scheduled_at | start/finish | delay/duration | run_id/task_id | keyword | attempt | result | product/observation | lease | DB | health | evidence | alert/ACK |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | | | | | | | | | | | | | |

## D. 健康采样

| sampled_at | 8793 owner | /api/status | /api/monitor/status | CSV | desired/scheduler/thread | heartbeat age | next_run_at | DB/log note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | | |

## E. 恢复/异常事件

| time | severity | symptom | state before | action | state after | owner/lease proof | evidence | decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | | |

## F. 中点与结束审计

- 约 12h digest/quality：
- 结束 digest/quality：
- 到期点数 / 有结果点数：
- 实际轮次开始数 / 完成数 / busy / skipped / blocked：
- 成功采集数：
- 失败/需人工率：
- 最大启动延迟：
- 最大轮次耗时：
- 最大 heartbeat age：
- HTTP 成功采样率：
- SQLite 错误数：
- 租约重叠数：
- 冷却内重复关键词数：
- critical/error/warning 及 ACK：

## G. 最终判定

- 结论：通过 / 不通过 / 证据不足
- 未满足条款：
- 是否允许进入扩容评估：否（默认）/ 是（需另行确认）
- 后续修复和复验阶段：
- 审核人：
- 审核时间：
```

## 11. 主任务建议的下一步

按以下顺序推进，不要直接启动 24h：

1. 先由主任务核对并记录当前真实受控轮次进度；只用 run/product/observation、状态和
   证据目录说话，不根据 T21 猜测。
2. 集成 T21 新测试并运行全量离线测试；补一组持续并发读写压力测试。
3. 优先修复/设计 scheduler-dead 监测与恢复，以及长步骤租约心跳/超时。这两项是
   自动监控 P0。
4. 完成 G2 的 3–5 个小时级轮次，再做 G3 恢复演练和 G4 6–8h 预 soak。
5. 只有 G0–G4 全部通过，且用户明确批准所需 Windows 外部配置后，才创建真实 24h
   soak 计划；仍保持 1 词/1 商品。
6. 24h 通过只允许“进入扩容评估”，不自动扩大关键词池、每轮预算或宣称无人值守/
   全站监控。
