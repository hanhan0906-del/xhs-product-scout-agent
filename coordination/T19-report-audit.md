# T19 候选报告完整性与无效证据防误用

更新时间：2026-07-29（Asia/Shanghai）

## 范围

- 仅离线审计和修改 `analysis.py`、`reports.py` 及对应测试。
- 未读取或修改生产数据库；未触碰 `data/`、`HANDOFF.md`、8793、服务、ADB、BlueStacks 或小红书。
- 数据口径沿用 `coordination/T16-data-quality-remediation.md`：每个商品只看最新评估；最新状态为 `candidate` 或 `needs_review` 均属于当前待处理商品，但后者必须显式进入人工复核。

## 已确认并修复

1. 原报告查询只允许最新 `status='candidate'`，会遗漏最新 `needs_review`。现改为纳入两种状态，并在总览和逐商品段落分别统计、标记。
2. 原报告连接“最新一条 `valid=1` 搜索证据”，会在后续证据已失效时回退到更早有效记录。现改为连接该商品最新一条搜索证据，不过滤 `valid`；若最新记录失效，报告显式显示失效原因、记录关键词和证据目录，并在风险、证据缺口和置信度中按无有效当前归属处理。
3. 缺失或坏 `reasons_json` 不会中断报告；坏 JSON 转为人工复核提示。回归夹具同时包含坏 `raw_signals_json`，报告仍可生成。

## 报告完整性

每个纳入商品继续覆盖：

- 商品证据与最新评估状态；
- 趋势指标与推断；
- 入选理由；
- 风险点；
- 证据缺口；
- 置信度；
- 原创化改写方向；
- 规范化公开笔记与账号主页证据。

## 兼容性

- `generate_candidate_report()` 原有参数不变。
- 返回值 `candidate_count` 保留，语义为本次报告的待处理商品总数；新增 `active_candidate_count` 和 `needs_review_count` 供调用方区分。
- 对没有 `search_evidence_valid` 字段的直接 `analyze_candidate()` 调用保持兼容：存在关键词时仍按有效/旧格式处理。
- 没有修改数据库 schema 或其他模块接口。

## 验证

- 定向：`.\.venv\Scripts\python.exe -m pytest -q tests\test_analysis.py tests\test_reports.py`
  - `5 passed in 0.34s`
- 全量：`.\.venv\Scripts\python.exe -m pytest -q`
  - `180 passed in 7.40s`

## 主任务集成注意事项

- 工作台或 API 若把 `candidate_count` 文案硬编码为“仅 candidate 状态数量”，应改用新增的两个细分字段；当前报告内部文案已改为“待处理商品数量”。
- 不要在其他查询中继续使用“`valid=1 ORDER BY id DESC LIMIT 1`”来表达当前搜索归属；这会跳过后续失效记录。当前归属应先取最新证据链，再判断其 `valid`。
- T19 没有调整 `insights.py` 内摘要查询；若主任务要求摘要与报告采用同一状态口径，应另行审计并在其独占范围内集成。
