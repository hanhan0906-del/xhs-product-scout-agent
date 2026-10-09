# T22：scheduler 异常退出检测与离线自恢复

最后更新：2026-07-29（Asia/Shanghai）

## 1. 范围与结论

本任务只修改：

- `src/xhs_scout/scheduler.py`
- `tests/test_scheduler.py`
- 本说明文件

所有验证均使用 `tmp_path` 临时 SQLite、假 portfolio 和假 `monitor_once`。未读取或
写入生产数据库、`data/`，未启动服务、8793/8765、ADB、BlueStacks、小红书、真实
调度、soak 或计划任务，也未修改 `HANDOFF.md`。

T21 指出的 scheduler 单轮未处理异常静默杀死线程问题已在离线代码层闭环：

- scheduler 对每个调度阶段做轮次级异常捕获；
- `monitor_once` 已经被调用且异常退栈时，scheduler 只回收该轮
  `last_run_id` 持有的 `running` 任务，并释放同 owner 的 monitor lease；
- portfolio、状态读取或结果持久化等非 monitor 阶段异常不会误清理其他 owner；
- 异常按有限指数退避继续，默认 `60s -> 120s`，第三次连续失败后暂停；
- 退避上限默认 900 秒，不会形成无限快速重启；
- 失败预算耗尽后写 `desired_state=paused`、`scheduler_running=false`、
  `next_run_at=null` 和明确的 `last_block_reason`；
- 活跃 `risk_stop_reason` 始终优先，scheduler 只会暂停，不会清除风险原因或自动恢复。

## 2. 运行时行为

默认恢复参数：

| 参数 | 默认值 | 行为 |
| --- | ---: | --- |
| `recovery_initial_seconds` | 60 | 第一次未处理异常后的等待 |
| `recovery_max_seconds` | 900 | 退避上限 |
| `max_consecutive_failures` | 3 | 连续失败达到此值后进入 paused |

退避公式为：

```text
min(recovery_max_seconds, recovery_initial_seconds * 2 ** (consecutive_failures - 1))
```

一次成功返回的 `monitor_once` 会把 `consecutive_failures` 清零。历史
`last_exception` 和累计 `recovery_count` 保留，便于健康检查和审计。

任务清理是 fail-closed 的：

1. 只有异常发生在 `monitor_once` 调用阶段才尝试任务/租约回收；
2. owner 取自该异常轮次写入的 `last_run_id`；
3. 只选择 `status='running' AND run_owner=<last_run_id>`；
4. 使用现有 `mark_task_failed(..., retryable=True)`，沿用任务重试预算和冷却；
5. 清理失败会写入异常快照的 `cleanup_errors`，不会扩大到其他 owner。

## 3. 可供主任务读取的接口

`MonitorScheduler.snapshot()` 新增：

```text
thread_alive
worker_state
last_exception
consecutive_failures
recovery_count
next_retry_at
max_consecutive_failures
recovery_backoff_seconds.initial
recovery_backoff_seconds.maximum
```

其中 `last_exception` 包含：

```text
type
message
at
consecutive_failures
run_id
recovered_tasks
cleanup_errors
```

现有 `web.py` 的 `/api/status` 已调用 `scheduler.snapshot()`，主任务无需修改 scheduler
即可取得进程内线程真实存活与恢复状态。

同时写入 `monitor_state`：

```text
last_scheduler_exception
scheduler_consecutive_failures
scheduler_recovery_count
scheduler_recovery_state
scheduler_running
next_run_at
last_block_reason
```

这些键可由现有 `get_monitor_state()` 动态返回，因此 `/api/monitor/status` 也能读取
持久化的最近失败和恢复状态。

主要 `worker_state`：

| 状态 | 含义 |
| --- | --- |
| `running` | 正常运行或成功轮次后 |
| `backing_off` | 异常已记录，正在有限退避 |
| `recovering` | 退避结束，已通过 desired/risk 检查，准备下一轮 |
| `paused_after_error_budget` | 连续失败预算耗尽，已持久化暂停 |
| `error_budget_exhausted_unpersisted` | 预算耗尽但数据库暂停写入失败，必须视为健康失败 |
| `risk_paused` | 检测到硬风险，保留原因并暂停 |
| `recovery_state_check_failed` | 退避后无法核验 desired/risk，线程 fail-closed 停止 |
| `stopped` | 正常停止、普通暂停或 blocked 返回 |

## 4. 离线测试证据

定向测试：

```text
.\.venv\Scripts\python.exe -m pytest -q tests\test_scheduler.py tests\test_scheduler_portfolio.py tests\test_24h_readiness.py
15 passed in 1.71s
```

全量离线回归：

```text
.\.venv\Scripts\python.exe -m pytest -q
221 passed in 9.44s
```

新增覆盖：

- 后台线程第一次 `monitor_once` 异常后仍存活并进入第二轮；
- 异常轮次的 `running` 任务按原重试策略回到 pending，owner/lease 清空；
- 最近异常、恢复计数和持久化状态可读；
- 连续异常达到有限预算后自动 paused，不再快速重启；
- portfolio 等 pre-monitor 异常不会清理另一个 owner 的任务；
- 活跃 `risk_stop_reason` 不被清除，monitor 不会启动。

## 5. 主任务集成注意事项

1. `/api/status` 已能直接得到 `scheduler.snapshot()`；健康判断建议至少使用：

   ```text
   desired_state == "running"
   AND (
     scheduler.thread_alive == false
     OR scheduler.worker_state in {
       "error_budget_exhausted_unpersisted",
       "recovery_state_check_failed"
     }
   )
   => health failure
   ```

2. `backing_off` 不是健康完成，应结合 `next_retry_at`、`consecutive_failures` 和
   `last_exception` 展示；超过 `next_retry_at` 仍无恢复应告警。
3. `paused_after_error_budget` 是明确停机结果，不应由计划任务或普通健康脚本直接改回
   running；应由人工检查最近异常后通过现有 resume 入口恢复。
4. `risk_paused` 与非空 `risk_stop_reason` 的优先级最高；只能使用现有精确风险确认流程
   解除，不能把 scheduler 自恢复当作风险恢复。
5. 本实现只解决 scheduler 线程级 P0，不替代 T21 的长设备步骤租约续期/超时、SQLite
   压力、G2/G3/G4 真实验收或 24 小时 soak 门槛。
6. 主任务如修改 `web.py`/运维健康检查，应同时展示进程内快照和持久化
   `monitor_state`；两者矛盾应判为异常，不应仅以 HTTP 2xx 或
   `scheduler_running=true` 判健康。
