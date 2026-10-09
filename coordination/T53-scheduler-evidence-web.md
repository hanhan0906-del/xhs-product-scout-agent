# T53：scheduler evidence 接入 readiness Web

最后更新：2026-07-29（Asia/Shanghai）

## 固定只读契约

`GET /api/soak-readiness` 固定读取项目根目录内：

- `evidence/scheduler-evidence.jsonl`
- `evidence/scheduler-expected.json`

请求不能覆盖两个路径。相对路径为绝对路径、包含 `..`、经解析越出项目根或通过
符号链接指向项目外时，会在读取数据库或调用 readiness 前拒绝。

`scheduler-expected.json` 的顶层必须是直接映射：

```json
{
  "G2": ["2026-07-29T08:00:00+08:00"],
  "G4": ["2026-07-29T08:00:00+08:00"]
}
```

每项都是调用方显式列出的、带时区 ISO-8601 `scheduled_at`。Web 不从
`run_events`、账本已有记录或轮次数量推导、补齐或修复 expected。

## 接入语义

- Web 把固定账本、项目根 allowed root 和 expected 原值交给 T49
  `evaluate_sqlite_readiness(...)`。
- 账本完整性、逐点匹配、simulated、漏点、额外点、重复时间、启动延迟、risk/block、
  lease、scheduler/thread、DB/SQLite、HTTP 和异常 ACK 仍由 T49/T46 fail closed。
- expected 缺失或 JSON 损坏时仍执行数据库只读评估，旧 G0/G1 证据不会丢失；
  G2/G4 保持非通过。
- 即使 scheduler G2/G4 维度完整，SQLite 旧轮次没有 `scheduled_at` 时，聚合 G2
  仍不会通过；Web 不以账本反向填充轮次。
- 响应始终 `soak_start_authorized=false`、`expansion_authorized=false`，路由保持
  GET-only。

固定路径、expected 契约、完整性和 G2/G4 阶段明细位于
`record.scheduler_evidence`；门槛结果进入 `gaps`；文件输入错误及 T49 阶段
missing/failed 原因进入 `warnings`。

## 修改文件

- `src/xhs_scout/web.py`
- `tests/test_soak_readiness_web.py`
- `coordination/T53-scheduler-evidence-web.md`

未修改 `scheduler_evidence.py`、`soak_readiness.py`、`workbench_ui.py`、
`HANDOFF.md`、`PARALLEL_WORK.md`、生产数据库或 `data/`。

## 离线验证

- T53 定向测试：`22 passed in 5.03s`
- scheduler/readiness/ACK/相邻 Web 回归：`119 passed in 22.29s`
- 完整离线套件：`453 passed, 2 skipped in 33.96s`
- `compileall`：退出码 `0`

测试全部使用 pytest 临时项目、临时 SQLite、临时 ACK 和 scheduler 文件；覆盖缺
文件、完整 real G2/G4、坏 expected JSON、路径越界、缺到期点、坏账本、simulated、
延迟、risk、thread 健康异常、旧 ACK/Web 路由回归和 SQLite `query_only`/表计数
不变。

## 未集成项与边界

- 未创建真实 `evidence/scheduler-evidence.jsonl` 或
  `evidence/scheduler-expected.json`。
- 未把 T46 接入真实 scheduler，未生成或补录任何真实 G2/G4 证据。
- 未访问服务、ADB、BlueStacks、小红书、真实采集、补证、soak 或 Windows
  计划任务。
- 项目不是 Git 仓库，无法用 `git diff/status` 生成改动清单；本任务工具写入仅限
  上述三个授权文件。
