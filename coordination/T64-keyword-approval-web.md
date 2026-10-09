# T64 关键词审批清单只读 API

更新时间：2026-07-29（Asia/Shanghai）

## 范围与边界

- 修改 `src/xhs_scout/web.py`。
- 新建 `tests/test_keyword_approval_web.py`。
- 新建本说明。
- 未修改 `keyword_approval.py`、`keyword_discovery.py`、工作台、既有测试、
  `HANDOFF.md`、`PARALLEL_WORK.md` 或 `data/`。
- 未操作服务、8793/8765、ADB、BlueStacks、小红书、真实数据库、真实队列、
  搜索、采集、monitor、soak 或计划任务。

## 交付

新增 GET-only `/api/keyword-approval-manifest`：

- 固定读取项目内 `approvals/keyword-approval.json`，endpoint 不接收路径参数；
- 通过现有 T27/T33/T35 建议链重算当前建议集合，数据库沿用
  `mode=ro` 与 `PRAGMA query_only=ON`；
- 复核清单完整性、确定性语义、T61 默认安全上限、suggestion set hash、
  evidence hash、候选 id、core/exploration、pending/approved/rejected 和统计数量；
- 审批文件修改时间超过 24 小时或超前 5 分钟以上时视为过期/异常；
- 缺失、坏 JSON、越界、过期、建议漂移、证据漂移、层级漂移、未知候选或
  数量不一致均 fail closed；
- 失效响应保留只读审计所需条目时，会把所有 `approval_valid` 强制降为
  `false`；
- `writes_queue`、`search_execution`、`monitor_authorization`、
  `soak_authorization` 在 scope 和 authorization 中恒为 `false`；
- 未新增创建、批准、写队列或执行 POST，既有关键词建议、补证计划、补证审批和
  readiness 路由保留。

## 测试证据

静态编译：

```text
.\.venv\Scripts\python.exe -m py_compile \
  src\xhs_scout\web.py tests\test_keyword_approval_web.py
```

T64 定向与相邻回归：

```text
.\.venv\Scripts\python.exe -m pytest -q \
  tests\test_keyword_approval_web.py \
  tests\test_keyword_approval.py \
  tests\test_keyword_discovery_web.py \
  tests\test_keyword_latest_evidence.py \
  tests\test_remediation_web.py \
  tests\test_remediation_approval_web.py \
  tests\test_soak_readiness_web.py

77 passed in 7.92s
```

完整离线回归：

```text
.\.venv\Scripts\python.exe -m pytest -q -rxX

562 passed, 3 skipped in 49.32s
```

完整回归前后 `web.py` SHA-256 均为
`79EE4C5EC2EF77434CE6975D1F7DFE5904F0B1F0632B7047C6E1BA26D2E8DF64`，
未检测到测试期间的并发覆盖。

测试只使用 `tmp_path`、临时 SQLite 或纯对象。真实临时 SQLite 验证还比较了
调用前后的数据库与审批清单字节，两者保持不变。

## 剩余风险

- T61 清单没有自身生成时间字段，因此 Web 层只能用固定文件的修改时间实施
  24 小时过期检查；复制或还原文件可能改变该时间，届时会保守要求重新核验。
- API 固定以最多 50 条当前建议重算完整集合。被截断或只覆盖旧建议子集的审批
  清单会按建议集合漂移失效，不会静默沿用旧批准。
- 本结果仅代表离线只读 API 契约，不代表批准真实搜索、写队列、monitor 或 soak。
