# T31：pre-soak 证据聚合与准入判定

最后更新：2026-07-29（Asia/Shanghai）

## 完成范围

新增纯离线模块 `src/xhs_scout/soak_readiness.py`，不启动循环、不连接设备、不访问
生产库。支持两类输入：

1. 普通 mappings：`evaluate_soak_readiness(evidence, target=...)`；
2. 临时或既有 SQLite：`load_sqlite_evidence(...)` /
   `evaluate_sqlite_readiness(...)`。路径输入使用 SQLite `mode=ro`，不会建表或迁移；
   已有 connection 仅执行 `SELECT`。

## 输出

`SoakReadinessReport` 同时提供：

- `summary`：真实/模拟轮次、合格成功轮次、墙钟跨度、risk/block/skip、搜索恢复、
  真实商品链接、指标、残留租约/running 任务、scheduler 异常恢复、SQLite lock、
  digest/quality 告警与快照覆盖；
- `gates`：G0–G6 的 `passed`、`failed`、`insufficient_evidence`、
  `not_reached` 或 `eligible_for_evaluation`；
- `record`：可序列化的 schema v1 结构化记录，保留每轮时间、ID、结果和关键证据；
- 固定声明：模拟、dry-run、合成测试不等于真实 pre-soak/24h soak。

缺少真实来源、时间、ID、证据路径、搜索返回、受支持商品链接、指标、快照或 ACK 时
不会推断通过。G6 即使在 G5 通过后也只表示可以另行评估，不代表已授权扩容。

## SQLite 只读适配

适配项目现有 `run_events` / `monitor_state`，并在表存在时只读关联：

- `search_tasks`
- `run_leases`
- `products`
- `observations`
- `search_result_evidence`

真实成功轮次以 `monitor_once_started` / `monitor_once_finished` 为边界；搜索恢复只认
`back_to_search_results`；真实链接复用 `product_link.is_supported_product_url()`；
指标读取现有 observation 指标字段。

## 验证

新增 `tests/test_soak_evidence.py`，覆盖：

- 真实 6 小时 pre-soak mappings 通过 G0–G4；
- 24 个以上模拟周期不能冒充真实 soak；
- 缺 ID/搜索恢复/真实链接/指标时 fail closed；
- risk、租约/任务残留、SQLite lock、未 ACK 告警硬失败；
- 24 小时、至少 18 个真实开始轮次与 G6 仅可评估；
- scheduler 异常未恢复；
- 临时 SQLite fixture 只读聚合；
- 普通轮次 iterable 输入。

定向及相关回归：

```text
31 passed in 2.20s
```

完整离线套件：

```text
262 passed, 4 xfailed in 9.38s
```

执行期间未修改生产数据库、`data/`、服务、设备、小红书、`HANDOFF.md` 或计划任务。
