# T28：第五/六轮并行成果集成契约回归

最后更新：2026-07-29 12:44（Asia/Shanghai）

## 1. 范围与边界

本任务只新增：

- `tests/test_round6_integration.py`
- `coordination/T28-round6-integration.md`

未修改生产源码、现有测试、生产数据库、`data/`、配置、服务、8793/8765、ADB、
BlueStacks、小红书或 `HANDOFF.md`。全部运行测试使用 `tmp_path` 临时根目录、临时
SQLite 和假 scheduler monitor。

已完整读取继承规则 `C:\Users\Lenovo\AGENTS.md`、`PARALLEL_WORK.md`，以及当前
存在的 T18–T27 coordination 文档。检查时 T23、T27 没有可选说明文档，但对应
`run_control.py` / `test_run_control.py` 与 `web.py` /
`test_keyword_discovery_web.py` 已存在，因此接口判断以实际源码和测试为准。

## 2. 覆盖的跨模块契约

| 来源 | 公开接口/接线 | T28 验证 |
| --- | --- | --- |
| T19 报告 | `generate_candidate_report()`、`analyze_candidate()` | `needs_review` 被纳入并单独计数；报告只展示最新无效搜索证据，不复活更早有效证据 |
| T20 关键词池 | `build_keyword_candidates()`、`build_rotation_plan()` | core/explore 同时可用；离线 scope 明确 `production_queue_write=false` |
| T22 scheduler | `MonitorScheduler`、`snapshot()` | 注入单轮异常后有限恢复；只回收本轮 owner 的 running 任务；恢复计数和异常快照可读 |
| T23 租约安全 | `renew_lease_safety()`、`check_lease_safety()` | owner 匹配时原子续租；scheduler 回收后旧 owner 检查 fail-closed |
| T24 补证规划 | `plan_remediation()` | 最新搜索归属为无效时进入隔离；另一 `needs_review` 商品按前置条件进入 metrics 批次 |
| T25 衍生建议 | `discover_keyword_candidates()` | 多来源聚合为 `pending_review`；只返回建议，不写数据库或队列 |
| T26 monitor 接入 | `monitor_once`、`MonitorLimits` 与 scheduler 模块接线 | scheduler 导入的 `monitor_once` 与 monitor 公开入口一致；保守默认 `max_keywords=1` |
| T27 只读 API | `GET /api/keyword-suggestions` | 实际 endpoint 可调用；scope 声明数据库只读、配置不写、队列不写、人工复核 |

## 3. 只读不变量

`test_round6_readonly_modules_share_contract_without_queue_or_config_writes` 在同一临时
fixture 中依次执行：

1. 生成 `needs_review` 候选报告；
2. 构建 T20 关键词候选和轮转计划；
3. 生成 T25 衍生建议；
4. 调用 T27 只读关键词建议 endpoint；
5. 运行 T24 补证规划。

调用前后对 `search_tasks` 做全列、全行有序快照，并对
`config/keyword_portfolio.json` 比较原始 bytes。两者均完全相等。允许的唯一输出是
显式指定到 `tmp_path` 的 Markdown 报告。测试没有连接生产库或读取生产配置。

## 4. 定向与全量证据

### 4.1 T28 单文件

```text
.\.venv\Scripts\python.exe -m pytest -q -rxX tests\test_round6_integration.py
2 passed, 1 xfailed in 1.28s
```

测试文件 SHA-256：

```text
D7F12E734E227ADA109FACF03108D9B7625C1DA19340422DFC95E35DCCD96E2E
```

### 4.2 T19/T20/T22–T27 定向集合

在加入已知风险 xfail 前，以下模块集合稳定通过：

```text
tests/test_analysis.py
tests/test_reports.py
tests/test_keyword_portfolio.py
tests/test_scheduler.py
tests/test_scheduler_portfolio.py
tests/test_run_control.py
tests/test_remediation.py
tests/test_keyword_discovery.py
tests/test_monitor_lease_safety.py
tests/test_keyword_discovery_web.py
tests/test_round6_integration.py

78 passed in 2.43s
```

并行期间 `web.py` 在首轮回归后继续由范围外任务更新，检测到时间戳变为
`2026-07-29 12:41:30`。针对更新后的当前文件重新执行：

```text
.\.venv\Scripts\python.exe -m pytest -q \
  tests\test_keyword_discovery_web.py tests\test_round6_integration.py
6 passed in 0.92s
```

当前 `web.py` SHA-256：

```text
7DACBF0331C218723F47BD42633A7D22934E7A7ED8040D4010789C6622EC9A6A
```

### 4.3 当前完整离线回归

并行任务增加测试期间，全量数量从 `232`、`236` 继续变化；每次均通过。加入已知
契约风险 xfail 后，对当前文件状态重新执行的最终结果是：

```text
.\.venv\Scripts\python.exe -m pytest -q -rxX
237 passed, 1 xfailed in 11.92s
```

没有范围外失败；数量变化来自并行任务新增测试，不是失败后重跑掩盖。

## 5. 已发现的集成风险

### R1（高）：T27 会复活已被最新记录否定的旧搜索归属

T19 报告的现行契约是：先取商品最新一条 `search_result_evidence`，再判断
`valid`；若最新记录无效，禁止回退到更早有效记录。

但 T27 `_keyword_review_inputs()` 当前查询直接使用：

```sql
WHERE se.valid=1
```

并读取所有历史有效行。T28 fixture 同时放入“更早 valid=1”和“最新 valid=0 /
keyword_mismatch”后：

- T19 报告正确只展示最新无效证据；
- T27 API 仍把更早有效关键词作为 `successful_search`；
- 该旧行与趋势标签叠加后，可把衍生建议从 explore 提升为 core。

此差异已固化为：

```text
XFAIL test_keyword_review_does_not_revive_search_invalidated_by_latest_evidence
```

建议由 `web.py` 的独占集成人在不改变只读边界的前提下，把搜索来源查询改成
“每商品先取最新证据，再限定 latest.valid=1”，修复后移除 xfail 并复跑 T19/T25/T27/T28。
在修复前，工作台/API 的衍生建议不能把“历史 valid 行存在”解释为当前有效归属。

### R2（中）：T23/T27 缺少 coordination 说明文档

截至本次检查，`coordination/` 下没有 `T23-*`、`T27-*`。源码和定向测试足以完成
本次接口回归，但主任务集成时应以源码、测试和本文件为索引，不能假设可选文档已交付。

### R3（既有限制）：T26 只能在阻塞外部调用返回后复核租约

当前 monitor 是“长阶段前续租、长阶段后复核”。单个阻塞的 ADB/UI/OCR 调用不能在
中途被 Python 强制取消；这不影响本次离线接口通过，但仍不能据此宣称真实设备、
pre-soak 或 24 小时 soak 已通过。

## 6. 集成结论

- T19/T20/T22–T27 的公开模块可在同一 Python 进程共同导入并用临时数据工作。
- `needs_review`、最新无效证据、有限关键词池、衍生建议、补证规划、scheduler
  自恢复和租约 fail-closed 均有跨模块证据。
- T27 endpoint 的数据库、队列和配置只读不变量已通过字节/行快照验证。
- 当前唯一未满足的语义契约是 R1，已明确 xfail，未修改生产源码绕过。
- 本结果只代表离线集成回归，不批准真实补证、设备操作、pre-soak 或 24 小时运行。
