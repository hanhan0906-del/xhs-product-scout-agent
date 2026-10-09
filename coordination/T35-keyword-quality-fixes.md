# T35 关键词衍生质量缺口修复

更新时间：2026-07-29（Asia/Shanghai）

## 任务边界

- 修改 `src/xhs_scout/keyword_discovery.py` 和
  `tests/test_keyword_discovery.py`。
- 保留 T32 的 `tests/test_keyword_discovery_corpus.py` 及其中三条非严格
  `xfail`，以 XPASS 形式保留历史缺口证据。
- 未修改 `web.py`、`workbench_ui.py`、`data/`、`HANDOFF.md` 或
  `PARALLEL_WORK.md`。
- 未访问或写入生产数据库、真实队列、8793/8765、ADB、BlueStacks、
  小红书、真实采集、soak 或计划任务。

## 算法变化

1. 证据去重仍保留原始 `source_keyword` 供审计，但去重身份使用其规范化值。
   同一 `source_type + source_id + product_id` 下仅标点或空白不同的来源词
   不再重复增加证据数和支持分。
2. 新增有限 OCR 质量规则：
   - 同时命中至少两个已记录的中文 OCR 混淆组合；
   - 关键词开头为至少四位 `l/I/1/O/0/|` 混排，且同时含字母形和数字形。
   命中后以 `ocr_gibberish` 进入过滤列表。普通 `AI 101学习资料` 保持召回。
3. 仅对超长字段的锚点滑窗应用有限前导残片清理，去除 `为`、`专为`、
   `适合`、`针对` 等悬空功能词。短标题不应用该清理，
   `为小学生准备的学习资料` 仍保持完整。

既有 `pending_review`、输出上限、来源聚合、支持权重、软硬风险和离线只读
契约均未改变。

## 测试证据

- 修改前定向基线：
  `.venv\Scripts\python.exe -m pytest tests/test_keyword_discovery.py tests/test_keyword_discovery_corpus.py -q -rxX`
  → `27 passed, 3 xfailed`。
- 修改后定向：
  同一命令 → `30 passed, 3 xpassed`。
- 静态编译：
  `.venv\Scripts\python.exe -m py_compile src\xhs_scout\keyword_discovery.py tests\test_keyword_discovery.py`
  → 通过。
- 排除并行修改中的 `tests/test_keyword_discovery_web.py` 后：
  `.venv\Scripts\python.exe -m pytest -q --ignore=tests/test_keyword_discovery_web.py -rxX`
  → `263 passed, 4 xpassed`。
- T33 完成后重新运行不排除文件的完整离线套件：
  `.venv\Scripts\python.exe -m pytest -q -rxX`
  → `1 failed, 271 passed, 4 xpassed`。先前并行中间态的三个 `web.py` 失败
  已全部消失；当前唯一失败为
  `tests/test_workbench_ui.py::test_render_workbench_html_exposes_remediation_contract_and_states`
  缺少 `product_cooldown_hours`，属于 T34 正在修改的 `workbench_ui.py`
  并行中间态，不属于 T35 回归。T35 未越权修改这些文件。

## 剩余风险

- OCR 过滤有意保持窄范围，只覆盖已记录的高置信混淆形态；新的 OCR 错字组合
  仍可能需要由后续语料驱动补充，避免一次性宽泛封杀正常中英混合词。
- 中文标题没有通用分词器；当前只清理有限的滑窗前导功能词。未记录的新型
  残缺边界仍可能进入人工审核，但不会自动批准或写入生产队列。
- 待 T34 完成并稳定 `workbench_ui.py` 后，应由总控补跑一次完整离线套件；
  当前 T35 定向测试和除并行中间态外的离线测试均已通过。
