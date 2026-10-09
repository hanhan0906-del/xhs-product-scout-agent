# T29 工作台衍生关键词人工审核界面

更新时间：2026-07-29（Asia/Shanghai）

## 实现边界

- 仅修改 `src/xhs_scout/workbench_ui.py`、`tests/test_workbench_ui.py` 和本说明。
- 保持候选商品、监控任务、报告与质量、关键词池四个顶层工作区不变。
- 在“关键词池”内新增只读的“衍生关键词人工审核”区域。
- 只调用既有 `GET /api/keyword-suggestions`，没有批准按钮、表单、POST、配置写入或搜索触发。
- 没有修改 `web.py`、生产数据、服务、设备、小红书或 `HANDOFF.md`。

## 使用的静态契约

指定的 `coordination/T27-keyword-review-api.md` 在实现时尚不存在，因此直接以当前
`web.py` 和 `tests/test_keyword_discovery_web.py` 中已落地的 GET 契约为准：

- `scope` 明确只读数据库、禁止生产队列写入、禁止关键词配置写入、禁止自动批准、
  禁止搜索触发，并要求人工审核；
- `stats` 提供原始证据、去重候选、返回候选、截断候选和过滤证据计数；
- `source_stats.source_rows_truncated` 提供来源读取截断计数；
- `candidates[]` 提供关键词、`pending_review`、`core/explore` 建议、支持度、来源商品、
  来源关键词、来源类型和风险标记。

## 界面行为

- 顶部固定显示“只读建议，不自动入池、不自动搜索”。
- 每个候选卡显示：
  - 候选词和规范化词提示；
  - `pending_review` 人工审核状态；
  - `core` / `explore` 建议；
  - 支持分、证据数、独立商品数、来源类型数和来源类型；
  - 来源商品、来源关键词和软风险标记。
- 概览显示原始证据、去重候选、返回候选、截断候选和过滤证据。
- API 警告、来源读取截断或只读边界异常会显示为只读提示；失败不会触发任何补偿写入。
- 初次加载和人工点击“刷新”时读取建议；原有 10 秒状态轮询不重复读取建议。
- 全部动态内容使用 DOM `textContent` 构建，没有使用 `innerHTML`。

## 验证证据

- 定向测试：
  - `.\.venv\Scripts\python.exe -m pytest -q .\tests\test_workbench_ui.py .\tests\test_keyword_discovery_web.py`
  - 结果：`14 passed in 0.93s`
- 内嵌 JavaScript 经 `node --check -` 检查通过。
- 静态检查确认顶层工作区仍为 4 个：
  `candidates, monitor, reports, keywords`。

## 主任务集成注意事项

1. T29 不要求改动后端；当前 GET 契约可直接使用。
2. 若后续 T27 补写协调文档，应核对其字段是否与当前 `web.py` 实际契约一致，以实际
   路由和测试为准。
3. 本任务未运行 8793、未做真实浏览器或生产数据验收；主任务集成后可在其授权范围内
   做桌面与 390px 移动端视觉检查。
