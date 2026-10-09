# T57：纯离线 pre-soak 证据包聚合器

最后更新：2026-07-29（Asia/Shanghai）

## 交付

- `src/xhs_scout/soak_evidence_bundle.py`
- `tests/test_soak_evidence_bundle.py`

聚合器只接受调用方提供的对象或显式允许根目录内的文件。它聚合 baseline、ACK、
scheduler evidence/expected、remediation approval 与 readiness 的来源哈希、状态、
缺口和时间，并生成确定性的 `bundle_id` 与 `manifest_hash`。

## 安全契约

- 不读取生产数据库、`data/`、服务、设备或外部平台。
- 文件输入和 bundle 读写都必须位于调用方给出的 `allowed_roots` 内；路径越界和
  符号链接逃逸直接拒绝。
- 凭据、Cookie、密码、secret、token 等敏感字段直接拒绝，不进入 bundle。
- 缺失、损坏、哈希不符、结构无效或证据未就绪只会得到 `incomplete` /
  `not_ready`，不会转成通过。
- `execution_authorized`、`pre_soak_start_authorized`、
  `soak_24h_start_authorized`、`scheduler_start_authorized` 永远为 `false`。
- `evidence_complete` 仅表示证据结构与状态完整，不是执行或 soak 授权。

## 验证证据

- T57 定向：`9 passed, 1 skipped in 0.36s`
- T57 + 五个依赖契约回归：`138 passed, 3 skipped in 18.20s`
- 完整离线回归：`478 passed, 3 skipped in 33.51s`

跳过项均为 Windows 当前权限下无法创建符号链接的条件跳过；越界路径仍有独立测试
覆盖。测试只使用 `tmp_path` / 临时目录。

## 边界核查

未触碰 `HANDOFF.md`、`PARALLEL_WORK.md`、现有源码、现有测试、生产数据库、
`data/`、8793/8765、ADB、BlueStacks、小红书、真实补证/采集、pre-soak/24h soak
或 Windows 计划任务。
