# T49：scheduler evidence 接入 G2/G4 readiness

最后更新：2026-07-29（Asia/Shanghai）

## 完成范围

`evaluate_soak_readiness(...)` 与 `evaluate_sqlite_readiness(...)` 新增可选参数：

- `scheduler_evidence_ledger_path`
- `scheduler_evidence_allowed_roots`
- `scheduler_evidence_readiness`
- `expected_scheduler_scheduled_at`

调用方必须以 `{"G2": [...], "G4": [...]}` 显式给出带时区的预期
`scheduled_at` 清单。readiness 不从已有轮次、scheduler 事件或账本记录反推预期
到期点。

## 门槛语义

- G1 不依赖 scheduler evidence，旧调用继续可用。
- G2/G4 缺 scheduler evidence 或缺显式预期清单时返回非通过，不再由旧轮次中的
  `scheduled_at` 自动晋级。
- 账本输入同时执行 T46 完整性与健康评估，并逐点比较调用方预期时间与账本记录时间。
- 缺点、额外点、重复时间、模拟来源、启动延迟超过 900 秒、risk/block、异常缺
  `operator_ack_refs`、租约 active/lost、DB/SQLite、HTTP、desired/scheduler/thread
  不一致均 fail closed。
- G4 的显式预期到期点自身还必须覆盖至少 6 小时，不能只依赖 readiness 轮次跨度。
- 原生 T46 `SchedulerEvidenceReport` 不包含逐点 `scheduled_at`。readiness 可以接收
  该结果，但单独使用时不能证明它与显式时间清单逐点一致，因此不晋级；可改传账本，
  或传入带 `scheduled_at_by_stage` 绑定的等价评估 mapping。
- ACK 的 T44 语义保持不变：critical/error 缺 ACK、非 acknowledge、坏账本或 ID
  不匹配继续阻止 G3/G4/G5。

## 验证

定向及相关回归：

```text
67 passed in 4.55s
```

完整离线套件：

```text
373 passed in 19.85s
```

另已通过 `compileall`。覆盖完整 real G2、旧调用兼容、显式 expected 必需、缺账本、
同数量但错到期时间、simulated、延迟、risk/block、ACK 引用、lease、thread、DB、
HTTP、G4 时间跨度与异常记录，以及 T44/T47 ACK/Web 回归。

## 未集成项与边界

- 未修改 T46 API、`scheduler_evidence.py`、`scheduler.py`、`web.py` 或
  `workbench_ui.py`。
- 未把 T46 记录接入真实 scheduler；真实账本与预期时间仍须由未来调用方显式提供。
- 未访问或修改生产数据库、`data/`、服务、ADB、BlueStacks、小红书、真实采集、
  补证、pre-soak/24h soak、计划任务、`HANDOFF.md` 或 `PARALLEL_WORK.md`。
