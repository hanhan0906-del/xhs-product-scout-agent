# T37：pre-soak 准入只读 Web API

最后更新：2026-07-29（Asia/Shanghai）

## 完成范围

新增 `GET /api/soak-readiness`，将 T31 的 `SoakReadinessReport` 接入现有
FastAPI 应用。接口只读取 `Settings.db_path` 指向的现有 SQLite 数据库：

- 使用 SQLite URI `mode=ro`；
- 连接后显式执行 `PRAGMA query_only=ON`；
- 不调用项目常规 `connect()`，不建表、不迁移、不写队列；
- 不启动 scheduler、monitor、pre-soak 或 24 小时 soak。

## API 契约

响应保留 T31 原始字段：

- `target`、`evidence_kind`、`generated_at`；
- `summary`；
- `gates.G0` 至 `gates.G6`；
- `record`（schema v1）；
- `warnings`；
- `ready_for_pre_soak`、`ready_for_24h_soak`。

Web 层补充：

- `gaps`：所有未通过门槛及 evidence-integrity 缺口；
- `evidence_scope`：只读模式、考虑的表、时间范围、轮次与坏 JSON 数；
- `soak_start_authorized: false`；
- `authorization`：明确声明接口不授权启动 soak、监控或扩容。

数据库缺失、SQLite 读取异常或 T31 输入解析异常时，返回完整 fail-closed 结构，
而不是推断准入。非空 `run_events.data_json` 若不是 JSON object，会增加
`malformed_run_event_json` warning 和 `EVIDENCE_INTEGRITY` 缺口，并强制两个
readiness 字段为 `false`。

生产数据库只能提供当前库内证据；T31 所需的离线测试、压力测试、恢复演练和
start/mid/end 快照若不在库中，相关门槛保持 `insufficient_evidence`，Web 层不补造。

## 验证

定向及相邻接口回归：

```text
29 passed in 1.54s
```

完整离线套件：

```text
287 passed in 10.73s
```

测试覆盖正常聚合、数据库缺失、坏 JSON、`mode=ro + query_only` 写入阻断、
表行数不变、GET-only，以及关键词建议、补证计划和旧 Web 接口回归。

验证过程只使用 pytest 临时数据库；未访问生产 `data/`、8793/8765、ADB、
BlueStacks、小红书、真实采集、soak、计划任务或共享运行状态。
