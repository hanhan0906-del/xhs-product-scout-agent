# T58 readiness API + 工作台端到端只读契约回归

最后更新：2026-07-29（Asia/Shanghai）

## 覆盖范围

新增 `tests/test_readiness_workbench_contract.py`，只使用 pytest 临时项目与临时
SQLite，串联验证：

- `GET /api/soak-readiness` 的 ACK、scheduler evidence、scheduler expected
  缺失或损坏时，G2/G4、pre-soak、24h soak 均不会误显示通过；
- `GET /api/approval-manifest` 的清单缺失或损坏状态分别保持 `missing` /
  `invalid`，工作台有对应阻塞文案，不会显示为当前或已批准；
- readiness 始终返回 `soak_start_authorized=false`，approval 始终返回
  `execution_status=not_executed`、`authorizes_execution=false`；
- 两个接口均为 GET-only；
- 两个工作台区域均无按钮、表单、输入控件或目标 POST 调用，不提供批准、执行补证、
  启动 pre-soak / 24h soak 或扩容入口；
- readiness API 调用前后临时 SQLite 主文件 SHA256 不变。

## 验证证据

- T58 定向测试：
  `.\.venv\Scripts\python.exe -m pytest -q .\tests\test_readiness_workbench_contract.py`
  → `6 passed in 0.84s`
- T53/T54 及相邻契约回归：
  `95 passed in 17.32s`
- 完整离线套件：
  `.\.venv\Scripts\python.exe -m pytest -q`
  → `469 passed, 2 skipped in 35.05s`

## 写入与真实状态边界

仅新建：

- `tests/test_readiness_workbench_contract.py`
- `coordination/T58-readiness-workbench-contract.md`

未修改任何现有源码或现有测试；未读取或写入生产数据库、`data/`、`HANDOFF.md`、
`PARALLEL_WORK.md`；未访问 8793/8765、ADB、BlueStacks、小红书、真实补证/采集、
pre-soak、24h soak 或 Windows 计划任务。

最终回归未发现稳定可复现的源代码缺陷。
