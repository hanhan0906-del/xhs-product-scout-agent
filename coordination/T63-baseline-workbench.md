# T63 工作台只读展示 pre-soak baseline 准入状态

最后更新：2026-07-29（Asia/Shanghai）

## 完成范围

- 在现有“pre-soak 只读准入证据”中保留 T50 的人工 ACK 和 scheduler evidence，
  增量加入第三块 baseline 证据卡片。
- 只读取 `GET /api/soak-readiness` 已有响应中的 `record.baseline`，并保留
  `summary.baseline` 兼容回退；没有新增接口或请求。
- 展示 `status`、`source`、`integrity_ok`、`baseline_id`、
  `manifest_hash`、真实 baseline 缺失、坏清单、文件漂移以及 baseline 自带的
  `gaps` / `warnings`。
- owner（8793 / 8765）、stop-entry、DB `quick_check=ok`、固定 1×1 参数和
  `interval_seconds` 作为硬核对项展示。接口没有逐项返回时不猜测通过，而是随
  baseline 阻塞；只有完整 baseline 通过时才说明已由固定清单完整性复核。
- 通过态要求固定来源、`status=passed`、`integrity_ok=true`、
  `files_reverified=true`、ID/hash 非空，并且全部 start/soak/scheduler 授权字段
  明确为 false。任何字段缺失或未知均 fail closed。
- 真实 baseline 未生成、清单损坏或文件漂移时，页面明确显示“不具备准入”。

## 只读与真实状态边界

- baseline 卡片无按钮、表单、输入、上传、生成、编辑、批准、执行或启动入口。
- 未修改 API、readiness、baseline、T58 契约测试、`HANDOFF.md` 或
  `PARALLEL_WORK.md`。
- 未直接读取或写入生产数据库中的内容，未访问 8793/8765、ADB、BlueStacks、
  小红书、真实采集/补证、pre-soak/24h soak 或 Windows 计划任务。
- 边界复核发现：按任务要求执行完整 pytest 后，`data/` 目录自身的修改时间从
  14:56:11 变为 15:04:01；目录内最新持久文件仍停留在 13:34:06，生产 SQLite
  文件大小仍为 1,019,904 bytes、修改时间仍为 13:34:06。说明完整测试期间很可能
  创建并删除了瞬时 SQLite sidecar；没有发现持久文件内容被本任务修改。未擅自
  删除、回滚或改写 `data/`。
- 仅修改：
  - `src/xhs_scout/workbench_ui.py`
  - `tests/test_workbench_ui.py`
  - 本说明

## 验证证据

- 工作台定向测试：`36 passed in 0.30s`。
- readiness/baseline/approval 相邻回归：`126 passed, 2 skipped in 6.97s`。
- 内嵌 JavaScript：`node --check` 退出码 `0`。
- Python 编译：`compileall` 退出码 `0`。
- 完整离线套件：`536 passed, 3 skipped, 4 failed in 45.09s`。
- 4 个失败均稳定复现于
  `tests/test_soak_evidence_bundle_integration.py`，分别是 baseline 文件漂移、
  过期 approval、计划漂移和 readiness 内部矛盾未使 evidence bundle 降级。
  该测试只导入 `soak_evidence_bundle`，不依赖 `workbench_ui`；T63 未越界修改。

## 风险与未完成

- 完整 pytest 不是全绿；上述 4 个 evidence bundle 集成失败需由其文件所有者或
  总控处理。
- 按任务禁令未启动 8793，因此没有做真实浏览器视觉验收。
- 当前 API 不逐项返回 owner、stop-entry、DB quick_check 和 1×1 参数值；工作台
  只能显示 baseline 模块整体复核结果或相关 gaps/warnings。为避免误导，未从
  `status=passed` 之外推断任何逐项事实。
