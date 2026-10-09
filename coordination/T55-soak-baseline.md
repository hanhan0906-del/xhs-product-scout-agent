# T55：pre-soak 离线基线清单

最后更新：2026-07-29（Asia/Shanghai）

## 完成范围

新增纯离线模块 `src/xhs_scout/soak_baseline.py`。模块只打开调用方显式列出的代码和
配置文件，不查询数据库、端口、磁盘、日志、进程或服务。数据库统计、运行参数、
8793/8765 owner 摘要、磁盘/日志摘要以及值守人和停止入口都作为
`caller_supplied` 原样规范化并校验。

公共 API：

- `build_baseline_manifest(...)`：生成确定性的 schema v1 清单；
- `validate_baseline_manifest(...)`：校验精确字段、SHA-256、关键项、安全声明，并可
  重新哈希已观察文件；
- `write_baseline_manifest(..., allowed_roots=...)`：只在显式允许根内写 canonical
  UTF-8 JSON；
- `read_baseline_manifest(..., allowed_roots=...)`：只在显式允许根内读取并 fail
  closed 校验。

## 清单结构

- `sources.observed`
  - 规范化后的绝对 `project_root`；
  - 按 `category + path` 排序的代码/配置相对路径、字节数和 SHA-256；
  - 文件集合的确定性 `file_set_sha256`。
- `sources.caller_supplied`
  - `database_statistics`；
  - `run_parameters`；
  - `port_owners`（必须精确包含 8793、8765 且各有 owner）；
  - `disk_summary`、`log_summary`；
  - `operator`、`stop_entry`。
- `safety`
  - `baseline_complete=true` 只表示清单结构完整；
  - pre-soak、24h soak、scheduler 三项启动授权永久为 `false`；
  - 明确声明清单不授权采集或任何外部动作。

清单不包含隐式当前时间；同一项目根、相同文件内容和相同调用方输入生成相同
`baseline_id`、`manifest_hash` 和 JSON。代码/配置路径越界、解析后的符号链接越界、
文件变化、未知/缺失字段、清单篡改或敏感字段均拒绝。

## fail-closed 门槛

- 代码和配置文件列表都必须非空，文件必须存在且解析后仍在项目根内；
- DB `quick_check` 必须存在且为 `ok`；
- 运行参数必须包含 `interval_seconds`、`max_keywords`、
  `max_products_per_keyword`，并保持 pre-soak 的 1 词 × 1 商品预算；
- 8793/8765 owner 摘要、磁盘摘要、日志摘要、operator 和停止入口必须存在；
- `credential`、`Cookie`、`password`、`secret`、`token` 等字段名在任意嵌套层级
  都被拒绝；
- 即使调用方自行重算清单哈希，也不能把任何启动授权位改成 `true`。

## 验证证据

定向测试：

```text
21 passed, 2 skipped in 0.42s
```

完整离线测试：

```text
453 passed, 2 skipped in 34.84s
```

两项 skip 是当前 Windows 主机不允许测试进程创建真实文件/目录符号链接。解析后
路径越界另有不依赖该权限的确定性测试，且通过；真实符号链接测试在具备权限的平台
会自动执行。

## 未集成项与边界

- 尚未接入 pre-soak orchestration、Web、scheduler 或任何真实运行入口；
- 尚未由真实状态所有者提供生产前 DB/owner/磁盘/日志快照；
- 清单完整不代表 G4/G5 准入通过，也不授权启动 pre-soak、24h soak、计划任务或
  扩容；
- 本任务未读取生产数据库或 `data/`，未访问 8793/8765、ADB、BlueStacks、
  小红书、真实采集/补证或 soak，未修改现有源码、现有测试、`HANDOFF.md` 或
  `PARALLEL_WORK.md`。
