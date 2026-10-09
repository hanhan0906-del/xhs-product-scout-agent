# T47：ACK fail-closed 接入 soak readiness Web API

最后更新：2026-07-29（Asia/Shanghai）

## 完成范围

现有 `GET /api/soak-readiness` 已将 T44 的 ACK 准入参数接入
`evaluate_sqlite_readiness(...)`：

- ACK 账本固定为项目根下 `acks/soak-ack.jsonl`；
- `ack_allowed_roots` 固定为解析后的项目根；
- 不接收请求参数覆盖账本路径；
- Web 层不创建、不追加、不修复账本，只在 T44 判定有 required critical/error
  告警时由 T43 读取和校验；
- 无需 ACK 的告警场景保持 `source=not_required`，不因账本不存在改变既有 G0–G6
  结果。

响应新增顶层 `ack_readiness`，展示 required/ready、要求和已确认 ID、缺失和未解决
ID、最新决定、完整性错误、证据不匹配、固定账本位置与只读路径策略。既有
`gaps`、`warnings`、`soak_start_authorized=false` 和 `authorization` 保持不变。

## Fail-closed 与路径边界

- 有 required critical/error 告警但账本缺失、损坏、最新决定为 reject/defer、
  或账本没有匹配的 alert ID 时，`ack_readiness.ready=false`；
- ACK 失败继续进入 T44 的 G3/G4/G5 缺口与 warning；
- 固定相对路径若被错误配置为绝对路径或含 `..`，在打开数据库或账本前拒绝；
- API 无账本路径参数，始终 GET-only，且始终不授权启动或扩容 soak。

## 验证

定向及相邻 Web/ACK/readiness 回归：

```text
55 passed in 2.11s
```

完整离线套件：

```text
357 passed in 12.11s
```

测试仅使用 pytest 临时项目和临时 SQLite/ACK 文件，覆盖无告警、缺账本、有效 ACK、
reject/defer、损坏账本、ID 不匹配、路径越界、旧接口、GET-only、SQLite
`mode=ro + query_only` 与表行数不变。

未访问或修改生产数据库、`data/`、8793/8765、ADB、BlueStacks、小红书、真实采集、
补证、pre-soak/24h soak、计划任务、`HANDOFF.md` 或 `PARALLEL_WORK.md`。
