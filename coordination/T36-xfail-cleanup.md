# T36：清理已修复的 xfail 测试债务

更新时间：2026-07-29（Asia/Shanghai）

## 范围与边界

- 仅修改：
  - `tests/test_round6_integration.py`
  - `tests/test_keyword_discovery_corpus.py`
- 新建本说明。
- 只移除 4 个已经过时的 `xfail` 装饰器；测试函数、输入夹具和断言均未删除、
  放宽或改写。
- `test_round6_integration.py` 随装饰器移除后，同时删除了不再使用的
  `pytest` 导入。
- 未修改任何生产源码、其他测试、数据库、`data/`、`HANDOFF.md` 或
  `PARALLEL_WORK.md`。
- 未访问服务、ADB、BlueStacks、小红书、采集、soak 或计划任务。

## 逐条确认

在编辑测试前，使用 `pytest --runxfail` 将四项按普通严格测试连续执行 3 轮，
每轮均为 `4 passed`：

1. `test_keyword_review_does_not_revive_search_invalidated_by_latest_evidence`
   - T33 已把关键词建议的搜索来源改为“先取每个商品最新证据，再判断
     `valid=1`”。
   - 夹具中的旧有效证据不会在最新证据无效后复活：
     `valid_search_sources_read == 0`，建议只由 `trend_label` 支持并保持
     `explore`。
2. `test_same_source_normalization_variants_should_not_inflate_support`
   - T35 已把证据去重身份改为使用规范化来源词。
   - 同一来源的标点、空白变体只计 1 条证据，支持分为 `2.0`。
3. `test_ocr_gibberish_should_be_filtered_instead_of_becoming_explore_candidates`
   - T35 已增加有限、高置信 OCR 乱码规则。
   - 两条既有乱码语料均进入过滤列表，候选列表为空。
4. `test_overlong_title_extraction_should_start_at_a_semantic_boundary`
   - T35 已对超长字段的锚点滑窗增加有限前导残片清理。
   - 结果严格等于 `小学三年级数学暑假预习资料`，仍为
     `pending_review`。

## 验收结果

编辑后目标文件定向回归：

```text
.\.venv\Scripts\python.exe -m pytest -q -rxX \
  tests\test_round6_integration.py \
  tests\test_keyword_discovery_corpus.py

23 passed in 0.82s
```

完整离线套件：

```text
.\.venv\Scripts\python.exe -m pytest -q -rxX

276 passed in 9.10s
```

没有 xfail、xpass 或失败。原总控基线 `272 passed, 4 xpassed` 中的四项 XPASS
现已全部成为普通通过，测试总数未减少。

## 剩余风险

- 本任务证明四条既有回归语料在当前实现上稳定通过，不把该结论扩大为通用中文
  分词或所有 OCR 错误形态均已解决。
- OCR 过滤和中文标题边界修复仍是 T35 明确记录的有限规则；新语料应继续以普通
  严格测试补充，不能依赖宽泛过滤。
- 以上仅为本地离线测试证据，不代表任何真实设备、服务、采集或 soak 验证。
