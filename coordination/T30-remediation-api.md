# T30 补证计划只读 API

## 接口

- `GET /api/remediation-plan`
- 数据库通过 SQLite URI `mode=ro` 打开，并显式设置 `PRAGMA query_only=ON`。
- 只读取每个商品的最新候选评估和最新观察，以及搜索归属、指标条、规范笔记、
  主页和明确 `phase='remediation'` 运行事件。
- 数据库行先转换成普通 `dict`，再调用 T24 的 `plan_remediation()`；不会把生产
  SQLite 连接传给规划器。

## 搜索与证据口径

严格有效搜索归属同时要求：

1. `search_result_evidence.valid=1`；
2. `source_keyword` 非空，且去首尾空格后与 `search_tasks.keyword` 相等；
3. 搜索证据、观察和商品属于同一条链；
4. 同一 `task_id + observation_id` 如有 `task_results`，不得存在无效结果。

最新搜索链存在但不满足以上条件时，`latest_search_attribution_valid=false`，规划器会
隔离该商品；旧有效链不会覆盖最新污染。

指标条只接受最新观察 `raw_signals_json.metrics_strip.frames` 中非空数组。坏 JSON
按缺少指标条处理，并在 `warnings` / `source_stats` 中记录，不导致接口 500。

规范笔记只认 `page_kind='note_detail'` 或 `source='related_note_card'`；主页证据只认
`page_kind='account_profile'` 或 `source='author_profile_from_note'`，且必须有粉丝数。

商品冷却只读取明确的 `run_events.phase='remediation'` 事件。普通商品观察或搜索时间
不会被猜测为补证时间；这避免无依据地把当前候选全部放入 24 小时冷却。

## 返回与安全边界

返回包括：

- `earliest_executable_stage` 和 `next_batch`；
- 全部 `batches`、`isolated`、`skipped`；
- `blocking_dependencies`；
- 单批、每小时、商品冷却和当前计划访问量预算；
- 数据来源统计与降级警告。

`scope` 固定明确：

- `production_queue_write=false`
- `collection_trigger=false`
- `approval_write=false`
- `execution_endpoint=false`

本任务没有新增 POST、批准、执行或队列写入入口。数据库缺失、schema 不可读时返回空
计划和警告，不创建数据库。

## 验证

专项与相关回归：

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests\test_remediation_web.py `
  tests\test_keyword_discovery_web.py `
  tests\test_remediation.py `
  tests\test_web.py
```

结果：`29 passed`。最终完整回归：`237 passed, 1 xfailed`。

专项测试使用 `tmp_path` 临时数据库，并对接口调用前后所有业务表行数进行比较，确认
零写入；另覆盖最新污染隔离、普通字典传参、坏 JSON、数据库缺失降级，以及补证相关
路由只有一个 GET 入口。
