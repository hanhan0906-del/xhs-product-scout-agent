# T54 补证审批清单只读工作台

更新时间：2026-07-29（Asia/Shanghai）

## 完成范围

- 在“报告与质量”的只读补证计划后增量加入
  `GET /api/approval-manifest` 审批清单卡片。
- 展示 `manifest_status`、`review_status`、`source_plan_current`、
  `plan_approval_status`、`execution_status`、已选批次和商品数量。
- 展示完整性、语义、planner hash、只读 scope、每批/每小时硬预算、强制隔离、
  低粉停止项、批次动作、`required_before`、issues 和 warnings。
- `missing`、`stale`、`invalid`、`unavailable` 均进入醒目空态或阻塞态，
  不把未知状态显示为当前或已批准。
- 页面反复说明“审批清单不等于执行授权”；即使状态为 `planned_approved`，
  仍固定展示 `not_executed` 和 `authorizes_execution=false`。

## 只读边界

- 卡片无按钮、无表单、无创建/批准/执行动作。
- 前端只对 `/api/approval-manifest` 发起 GET；不新增 POST、清单写入、审批写入、
  生产队列写入或执行入口。
- 仅修改：
  - `src/xhs_scout/workbench_ui.py`
  - `tests/test_workbench_ui.py`
  - 本说明
- 未修改 `web.py`、`remediation_approval.py`、生产数据库、`data/`、`HANDOFF.md`
  或 `PARALLEL_WORK.md`。
- 未访问 8793/8765、ADB、BlueStacks、小红书、真实补证/采集、soak 或计划任务。

## 验证证据

- 定向及相邻接口/工作台回归：
  `74 passed in 6.20s`。
- 内嵌 JavaScript：`node --check -` 退出码 `0`。
- Python 编译：`compileall` 退出码 `0`。
- 完整套件：`451 passed, 2 skipped, 1 failed in 32.66s`。
  唯一失败为并行 T55 的
  `tests/test_soak_baseline.py::test_rehashed_attempt_to_authorize_start_still_fails_closed`：
  测试期望 `never authorize`，实际先返回
  `baseline_id does not match manifest content`。该文件不在 T54 写入范围。
- 排除上述已定位的范围外断言后：
  `452 passed, 2 skipped, 1 deselected in 33.46s`。

## 未验收项

- 按任务禁令未启动服务，未做 8793 真实浏览器视觉验收。
- T55 的单项错误优先级/错误文案契约需由 T55 或总控处理。
