# T26：monitor 长步骤租约安全接入

最后更新：2026-07-29 12:33（Asia/Shanghai）

## 范围

- 只修改 `src/xhs_scout/monitor.py`。
- 新增 `tests/test_monitor_lease_safety.py`。
- 全程只使用假设备和 pytest 临时 SQLite。
- 未操作生产数据库、`data/`、8793/8765、服务、ADB、BlueStacks、小红书、
  soak、计划任务或 `HANDOFF.md`。

## 接入结果

`monitor.py` 通过 T23 的 `renew_lease_safety()` 和
`check_lease_safety()` 在粗粒度设备阶段设置门禁：

1. 任务预留后、首次设备打开前续租；
2. 搜索阶段前已续租，搜索阶段完成后复核；
3. 商品点击与等待前续租，详情探测后复核；
4. 非商品页恢复前续租，恢复探测后复核；
5. 详情采集与指标 OCR 前续租，完成后复核；
6. 可选笔记证据前续租，完成后复核；
7. 返回搜索结果页前续租，完成后复核。

策略是“长阶段前续租、长阶段后只读复核”，不为每次 tap、文本解析或事件写入
单独建立租约连接。单个阻塞调用无法被 Python 从中途强制取消；它返回后立即复核，
复核失败时不会进入下一个设备阶段。

任何 `safe_to_continue=False` 都会：

- 立即停止后续设备动作；
- 写入 `lease_safety_blocked` warning 事件和明确 checkpoint/reason；
- 设置 `desired_state=paused`、`risk_stop_reason` 和 `last_block_reason`；
- 仅在任务仍为本 owner 的 running 状态时，以 `retryable=False` 释放任务到
  `needs_manual_detail`，不产生普通冷却重试；
- owner 限定释放全局租约，不会删除已由其他 owner 接管的租约；
- `monitor_once()` 的最终清理对同一 owner 的其他未完成预留任务同样 fail-closed。

dry-run 不预留任务租约，因此保持原有行为，不执行租约门禁。

## 离线证据

- 定向回归：
  `30 passed in 1.56s`
- 全量离线测试：
  `227 passed in 9.22s`

新增回归覆盖：

- 搜索阶段结束时模拟其他 owner 接管，确认之后不查商品卡、不采集、不返回；
- 指标 OCR 完成时模拟其他 owner 接管，确认之后不采笔记证据、不返回搜索页；
- 两种情况都确认任务 owner/lease 字段清空、无 next_run_at、明确人工态和风险阻断；
- 确认旧 owner 的清理不会删除 replacement owner 的全局租约。

## 主任务集成与重启前注意事项

1. 先读取本文件和 `tests/test_monitor_lease_safety.py`，再复跑定向与全量离线测试。
2. 不要把本次离线通过解释为真实设备、小时级轮次、预 soak 或 24 小时 soak 通过。
3. 重启 8793 前由主任务检查当前真实轮次、生产库 running owner、全局租约和
   `risk_stop_reason`；不要直接清除已有风险原因。
4. 若真实库已存在 lease-safety block，必须人工核对 owner 与页面后再按精确原因
   恢复；不得用普通重试或 `ignore_paused` 绕过。
5. 本任务未改服务、配置或数据库 schema；主任务无需迁移，但应在受控 1×1 轮次中
   验证事件、人工态和 owner 清理符合预期后，才继续 G2/G3。
