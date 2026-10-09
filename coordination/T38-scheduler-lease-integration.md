# T38：scheduler 异常恢复与 monitor 租约安全跨模块离线回归

最后更新：2026-07-29（Asia/Shanghai）

## 范围

- 仅新增 `tests/test_scheduler_lease_integration.py` 和本说明文件。
- 全部测试使用 `tmp_path` 临时 SQLite、假 monitor 和假设备。
- 未修改现有源码或测试，未读取或写入生产数据库、`data/`、`HANDOFF.md`、
  `PARALLEL_WORK.md`。
- 未访问服务、8793/8765、ADB、BlueStacks、小红书、真实采集、soak 或计划任务。

`coordination/` 当前没有单独的 T23 说明文件；本次以 `PARALLEL_WORK.md` 的 T23
范围、`run_control.py`、`tests/test_run_control.py` 和
`coordination/T26-monitor-lease-integration.md` 作为已落地契约来源。

## 新增跨模块回归

1. scheduler 第一次异常进入有限退避时，真实线程仍存活；进程内
   `thread_alive/worker_state/consecutive_failures/next_retry_at` 与临时数据库中的
   `scheduler_running/scheduler_recovery_state/scheduler_consecutive_failures/
   next_run_at` 一致。成功重试并暂停后，两边都落到 stopped/false/null。
2. 连续两次未处理异常达到预算后停止重试并持久化 paused；只回收异常轮次
   `last_run_id` 对应的 running 任务和租约，不触碰 replacement owner 的任务。
3. 异常轮次同时写入 `risk_stop_reason` 后，scheduler 完成 owner 限定清理但不会进入
   第二次 monitor 调用；风险原因原样保留，desired state 和 worker state 均进入风险
   暂停。
4. 假设备完成搜索步骤后模拟全局租约和任务租约被新 owner 接管；旧执行者在
   `after_search_stage` 复核失败后，不再查找商品卡、采集详情或执行返回动作，也不会
   完成/释放新 owner 的任务和全局租约。
5. 直接验证错误 owner 调用任务成功、任务失败和全局租约释放接口均不能改变原 owner
   的 running 状态、租约或错误字段。

这些断言直接绑定 owner、任务状态、租约字段、设备调用序列、scheduler 内存快照和
数据库状态；移除有限异常预算、风险优先级、lease-lost 门禁或 owner 条件时会失败。

## 测试证据

首次定向：

```text
.\.venv\Scripts\python.exe -m pytest -q tests\test_scheduler_lease_integration.py
5 passed in 0.73s
```

跨模块定向：

```text
.\.venv\Scripts\python.exe -m pytest -q tests\test_scheduler_lease_integration.py tests\test_scheduler.py tests\test_run_control.py tests\test_monitor_lease_safety.py tests\test_round6_integration.py tests\test_24h_readiness.py
31 passed in 4.70s
```

完整离线套件最终复跑：

```text
.\.venv\Scripts\python.exe -m pytest -q
287 passed in 11.08s
```

完整套件首次执行时，当前并行新增的 `tests/test_soak_readiness_web.py` 曾出现两项
失败（其余 `285 passed`）。该文件隔离复跑为 `5 passed`，与 T38 同进程复跑为
`10 passed`，随后完整套件复跑为 `287 passed`。当前无法稳定复现该现象，未据此
修改任何 T37 文件或目标源码。

## 结论与边界

- T38 指定的 scheduler 异常恢复、租约丢失停止、owner 隔离、快照/数据库一致性和
  risk stop 保留均有跨模块离线回归且当前全绿。
- 未发现需要越界修复的 scheduler、run-control 或 monitor 源码缺陷。
- 本结果只证明离线契约，不代表真实设备轮次、pre-soak 或 24 小时 soak 已通过。
