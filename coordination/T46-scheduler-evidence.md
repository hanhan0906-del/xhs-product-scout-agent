# T46：scheduler 到期点证据记录模块

最后更新：2026-07-29（Asia/Shanghai）

## 完成范围

新增纯离线模块 `src/xhs_scout/scheduler_evidence.py`，未接入
`scheduler.py`、`soak_readiness.py` 或真实 scheduler。模块只操作调用方显式传入且
位于 `allowed_roots` 内的本地 JSONL 账本与既有证据路径。

## 公共 API

- `append_scheduler_evidence(ledger_path, allowed_roots=..., evidence=...)`
  - 严格要求完整 schema；
  - 校验带时区时间、时间顺序、delay/duration 与时间差一致；
  - 校验 G2/G4、`simulated|real`、结果、租约、scheduler/thread、DB、HTTP、
    关键词/游标、证据路径和 ACK 引用字段；
  - 自动分配连续 sequence，以 canonical JSON 建立 SHA-256 哈希链，并 `fsync`
    追加；
  - 相同 `record_id`/相同内容幂等返回，冲突内容或重复到期点拒绝。
- `read_scheduler_evidence(ledger_path, allowed_roots=...)`
  - 按物理行顺序确定性读取；
  - 校验 JSON、精确字段集合、连续 sequence、唯一 record/due point、前序哈希、
    当前记录哈希和证据路径；
  - 任一损坏均抛出 `SchedulerEvidenceIntegrityError`，不返回部分可信结果。
- `evaluate_scheduler_evidence(..., expected_due_points=...)`
  - 支持按 G2/G4 提供预期到期点 ID 清单或预期数量；
  - 返回每阶段的记录数、真实/模拟数、结果分类、缺失/额外/重复点、最大 delay/
    duration、risk/block 和缺 ACK 数；
  - 账本损坏、缺到期点、模拟来源、延迟超过 900 秒、风险/block、租约残留或丢失、
    DB/HTTP 异常、scheduler/thread 状态不一致时均 fail closed。

`ready_for_gate_evaluation=true` 只表示这本到期点账本具备交给上层 G2/G4 判定的
完整、真实、健康证据；它不自行宣称 G2/G4 已通过，也不授权 pre-soak、24h soak、
扩容或计划任务。

## 记录语义

- `completed` 必须有 run/task/product/observation、关键词与来源。
- `busy`、`skipped`、`blocked` 可在未进入具体任务时将上述 ID 明确记为 `null`；
  `skipped` 必须有 skip reason，`blocked` 必须有 block 或 risk reason。
- 风险、block、SQLite 异常、DB busy/error 或非 200 HTTP 结果可以如实追加，但会
  阻止阶段晋级；异常记录缺少 `operator_ack_refs` 时另计为 ACK 缺口。
- `evidence_source=simulated` 可以用于离线结构验证，但永远不能晋级；准入只接受
  `real`。
- DB、HTTP 和一般证据路径必须已存在且位于显式 allowed root 内。凭据、Cookie、
  token、密码等敏感字段名会被拒绝。

## 验证

定向测试：

```text
13 passed in 0.83s
```

完整离线测试：

```text
340 passed in 11.68s
```

覆盖完整 real 点、simulated 不晋级、缺到期点/字段、重复 sequence/到期点、时间
倒置、延迟超限、坏 JSON、哈希篡改、risk/block、ACK 引用、busy/skipped/blocked
结果、DB/HTTP/证据路径和确定性阶段汇总。

## 未集成项与边界

- 尚未在 `scheduler.py` 的实际到期决策前后调用本模块。
- 尚未把本模块的阶段汇总接入 `soak_readiness.py`；上层未来应显式传入期望到期点
  清单，不能仅从已有记录反推“应有多少点”。
- 未验证真实 scheduler、生产数据库、HTTP、服务、设备或 soak；本任务生成的全部
  记录均为 `tmp_path` 测试夹具，不是任何真实 G2/G4 证据。
- 未修改生产数据库、`data/`、`HANDOFF.md`、`PARALLEL_WORK.md`、现有源码或现有
  测试，未访问服务、ADB、BlueStacks、小红书、计划任务或真实采集。
