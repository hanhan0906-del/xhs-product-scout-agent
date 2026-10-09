# T44：readiness 与人工 ACK 离线准入集成

最后更新：2026-07-29（Asia/Shanghai）

## 完成范围

`evaluate_soak_readiness(...)` 与 `evaluate_sqlite_readiness(...)` 新增两种可选 ACK
输入方式：

1. `ack_ledger_path` + `ack_allowed_roots`：由 readiness 调用 T43
   `evaluate_ack_readiness(...)`；
2. `ack_readiness`：接收 T43 已生成的 `AckReadiness` 或等价 mapping。

未修改 T43 API，也未接入 Web、工作台、生产配置或任何运行入口。

## 准入语义

- digest 的 `critical/error` 与 quality 的 `error` 必须有稳定 `alert_id`（兼容 `id`）；
- readiness 从快照提取的告警 ID 必须与 ACK 评估中的 `required_alert_ids` 完全一致；
- 每个要求处理的告警只有最新决定为 `acknowledge` 才通过；
- 缺 ACK、`reject`、`defer`、账本损坏、告警缺 ID 或 ID 集合不匹配均 fail closed；
- 没有需要 ACK 的 critical/error 时，ACK 状态为 `not_required`，不改变旧 G0–G6
  判定结果；
- 快照内旧的 `acknowledged/operator_ack` 仅保留在原摘要计数中，不能替代 T43
  哈希链账本或其评估结果。

ACK 诊断写入 `summary`：要求/已确认/缺失/未解决 ID、最新决定、完整性错误、
证据不匹配、来源与最终 `ack_ready`。G3、G4、G5 都使用同一 fail-closed 结果。

## 验证边界

测试仅使用 mappings 与 `tmp_path`，覆盖无告警兼容、缺 ACK、账本 acknowledge、
reject/defer、损坏账本、评估结果 ID 不匹配、预评估结果和旧 T31 契约回归。

未访问或修改生产数据库、`data/`、服务、ADB、BlueStacks、小红书、真实采集、
补证、pre-soak/24h soak、计划任务、`HANDOFF.md` 或 `PARALLEL_WORK.md`。
