# T62：pre-soak 证据包跨模块集成回归

最后更新：2026-07-29（Asia/Shanghai）

## 交付与边界

- 新增 `tests/test_soak_evidence_bundle_integration.py`。
- 本测试只使用 `tmp_path`、两个临时 SQLite、临时 JSON/JSONL 和纯对象。
- 真实调用 `soak_baseline`、`soak_ack`、`scheduler_evidence`、
  `remediation`/`remediation_approval`、`soak_readiness` 和
  `soak_evidence_bundle` 的公开 API。
- 未修改任何现有源码或现有测试。
- 未读取或写入生产库、`data/`、服务、端口、设备、外部平台、真实采集/补证、
  pre-soak/24h soak 或 Windows 计划任务。
- 未修改 `HANDOFF.md` 或 `PARALLEL_WORK.md`。

## 已通过覆盖

- 完整真实模块链生成 deterministic baseline、ACK hash-chain、scheduler
  evidence/expected、补证审批、readiness 和 bundle。
- 同一来源链的 `bundle_id`、`manifest_hash` 和 JSON 完全确定。
- 五类来源任一缺失均为 `incomplete`。
- baseline manifest、ACK ledger、scheduler ledger、approval manifest 的落盘内容
  被改写后均为 `incomplete/invalid`。
- 最新 ACK 为 `reject` 或 `defer` 时为 `not_ready`。
- scheduler 来源为 `simulated`、显式 expected due-point 漂移、readiness G3 降级时
  均为 `not_ready`。
- 完整包中 execution、scheduler、pre-soak、24h 四类授权始终为 `false`。

## 严格失败证据（现有源契约缺口）

以下 4 条测试稳定失败，均为聚合器返回 `evidence_complete`，但 T62 期望
`incomplete/not_ready`：

1. `test_observed_baseline_file_drift_makes_bundle_incomplete`
   - baseline 生成后观察到的 code file 内容发生漂移；
   - bundle 的 baseline loader 使用 `verify_files=False`，没有重验观察文件。
2. `test_stale_approval_makes_bundle_not_ready`
   - 2020 年审批在 2026 年组包仍被接受；
   - bundle 没有 max-age、expires-at 或调用方 freshness policy。
3. `test_remediation_plan_drift_invalidates_old_approval`
   - 当前 planner hash 已不同于旧 approval 的 `source_plan_hash`；
   - bundle API 没有接收当前 planner hash/plan，因此无法比较。
4. `test_internally_inconsistent_readiness_payload_is_incomplete`
   - readiness 的 G3 被改成 `failed`，但顶层 `ready_for_pre_soak` 仍为 `true`；
   - bundle 没有交叉校验 gate statuses 与 ready 布尔值，也没有 readiness 签名。

按 T62 停止条件，没有修改现有源模块来修复这些缺口。

## 测试证据

- T62 定向：`15 passed, 4 failed in 10.25s`。
- 相关回归：`181 passed, 3 skipped, 4 failed in 28.87s`。
- 完整 pytest：`529 passed, 3 skipped, 4 failed in 44.93s`。
- 排除 T62 新文件的既有完整基线：`514 passed, 3 skipped in 33.27s`。

3 个 skip 均来自既有 Windows 符号链接条件测试；T62 新文件没有 skip。
