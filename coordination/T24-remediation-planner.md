# T24 数据补证批次规划器

## 范围

`src/xhs_scout/remediation.py` 是纯离线、确定性规划模块。它只读取调用方提供的普通字典，
或只读查询调用方创建的 SQLite fixture 表；不连接生产数据库，不采集，不操作设备，也不写
`search_tasks` 或其他队列表。

## 输入契约

入口：

```python
plan_remediation(products, now=..., policy=...)
```

`products` 可以是字典 iterable，也可以是 `sqlite3.Connection`。SQLite fixture 默认表名为
`remediation_products`，列名与下列字段相同。

必要字段：

- `product_id`（或 `id`）
- `status`：只有 `candidate`、`needs_review` 进入规划

主要证据字段：

- `has_valid_search_attribution`
- `latest_search_attribution_valid`：显式为假时隔离，旧有效链不能抵消最新污染
- `has_supported_product_link`，或由 `share_url` 走现有白名单校验
- `has_metrics_strip`，或由 `raw_signals_json.metrics_strip.frames` 判定
- `has_note_evidence`
- `has_profile_evidence`
- `note_author_identifiable`
- `note_published_days_ago`
- `note_likes`
- `potential_follower_ceiling`
- `known_follower_count`
- `last_remediation_at`
- `quarantined` / `quarantine_released`
- `priority`、`score`

`now` 必须显式传入，避免测试和运行结果依赖系统当前时间。

## 输出契约

返回 `RemediationPlan`：

- `batches`：按 `identity → metrics → note → profile` 排序；同一商品只进入当前最早可执行阶段，
  每完成一批应使用刷新后的证据重新规划；
- `PlanItem.actions`：本批动作；
- `PlanItem.reasons`：进入本阶段的结构化原因；
- `PlanItem.required_before`：本阶段已经满足的前置；
- `PlanItem.blocks`：当前缺口尚在阻塞的后续阶段；
- `isolated`：搜索污染、T18 product 20 审计隔离、24 小时商品冷却；
- `skipped`：已知高粉或笔记未过门槛，因此明确不访问主页；
- `completed_product_ids`：无需再补证；
- `excluded_product_ids`：非候选状态，不进入计划。

默认硬上限：每批 2 个、每小时 6 次、同商品 24 小时一次。调用方传入更大的值也会收紧到
这些上限；`hour_window` 只用于离线分窗，不代表已建立生产任务。

## 安全边界与集成点

1. 主任务从最新只读快照组装输入字典，或建立临时 fixture；不要把生产连接交给写队列代码。
2. 调用 `plan_remediation` 后，只选择 `batches` 中下一批；当前 scheduler 单轮实际只允许
   1 个商品时，应由主任务再拆为单商品轮次。
3. 执行结果写回生产事实库后必须重新读取最新证据并重算，不能把离线计划当作静态队列。
4. product 20 默认处于 T18 审计隔离集；只有新有效搜索已经落证且主任务显式提供
   `quarantine_released=1` 才能重入。
5. 主页永远后置：缺笔记时先规划 note；已有笔记也必须通过作者、7 天时效与互动门槛。
   已知粉丝超过 2000 的商品输出到 `skipped`，不得继续追主页。

## 验证

定向命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_remediation.py
```

测试覆盖普通字典、内存 SQLite fixture、阶段前置、product 20 隔离、高粉跳过主页、笔记门槛、
24 小时边界、批次/小时限额、稳定排序、重复 ID 和非法 fixture 表名 fail-closed。
