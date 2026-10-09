# T33：关键词建议只读取商品最新搜索证据链

最后更新：2026-07-29 13:14（Asia/Shanghai）

## 范围与边界

本任务最终修改：

- `src/xhs_scout/web.py`
- 新建 `tests/test_keyword_latest_evidence.py`
- 经总控补充授权，更新 `tests/test_keyword_discovery_web.py` 中与新权威语义冲突
  的旧断言，并新增相反场景保护
- 新建本说明

未修改 T28 测试、T30 补证 API、生产数据库、`data/`、配置、服务、8793/8765、
ADB、BlueStacks、小红书、真实队列或 `HANDOFF.md`。所有测试均使用 `tmp_path`
临时数据库。

## 修复

`_keyword_review_inputs()` 的两个搜索归属入口均改为：

1. 先按 `search_result_evidence.id DESC` 选择每个商品的最新证据；
2. 再要求该最新证据 `valid=1` 且关键词非空；
3. 最新证据无效时，不回退到更早的 `valid=1`。

这同时约束：

- 传给 T25 的 `successful_searches`；
- 趋势标签映射的 `source_keyword`。

选择最大 `id` 与 `reports.py`、T30 `_remediation_plan_inputs()` 的现行“最新证据”
口径一致，也避免直接比较带不同时区偏移的 ISO 时间字符串。

## 独立回归

`tests/test_keyword_latest_evidence.py` 覆盖：

- 商品 A：旧 `valid=1`、最新 `valid=0`，不得产生 successful search，趋势标签
  不得继承旧 `source_keyword`；
- 商品 B：两条有效历史证据，只保留最新一条；
- 最新无效链存在时，旧词只有 trend label 支持，必须保持 `explore`，不得提升
  `core`；
- API 仍声明数据库只读和 `production_queue_write=false`。

## 测试证据

关键定向集合（将 T28 xfail 当普通测试执行）：

```text
.\.venv\Scripts\python.exe -m pytest -q --runxfail \
  tests\test_keyword_latest_evidence.py \
  tests\test_remediation_web.py \
  tests\test_round6_integration.py::test_keyword_review_does_not_revive_search_invalidated_by_latest_evidence

8 passed in 0.81s
```

T27 数据库缺失安全降级：

```text
.\.venv\Scripts\python.exe -m pytest -q \
  tests\test_keyword_discovery_web.py -k degrade

1 passed, 3 deselected in 0.64s
```

全量离线回归：

```text
.\.venv\Scripts\python.exe -m pytest -q -rxX

272 passed, 4 xpassed in 10.27s
```

首次全量验证曾确认唯一三条失败均在旧
`tests/test_keyword_discovery_web.py`，共用夹具先插入 `valid=1`、再为同商品插入
`valid=0`，但仍断言旧有效行应被使用。总控确认该文件无人并行写入并补充授权后，
已将其更新为：

- 最新 invalid 时，旧词只有 `trend_label`、分数 `1.25`、层级 `explore`；
- 传给 T25 的 `successful_searches` 为空，趋势标签的旧 `source_keyword` 为
  `None`；
- 既有词配置只过滤当前仍存在的一次 trend occurrence，配置 bytes 保持不变；
- 新增 `test_latest_valid_search_restores_current_attribution_after_invalid_history`：
  旧 valid → invalid → 最新 valid 后，当前归属恢复为
  `successful_search + trend_label`、分数 `3.25`、层级 `core`。

T28 的已知风险测试已从 xfail 变为 XPASS；另外三条 T32 已知缺口测试也因并行
算法修复变为 XPASS。主任务可分别清理过时的 xfail 标记。

## 文件指纹

```text
src/xhs_scout/web.py
2A1CE66EE8DC08221AFCCE4B8A8DF53E5B76080B0FE7F767145FFF6E4E973AED

tests/test_keyword_latest_evidence.py
E29EB81A21012098E91A43FFA05E374CD73BD1AE1FF6BD7414BA57E4D605D77D

tests/test_keyword_discovery_web.py
15AB30BAED81297E6A396A55522013C0FC092DE3385AC0F497B71D7F304B2CE2
```
