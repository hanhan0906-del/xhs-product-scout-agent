# T50：工作台展示 ACK 与 scheduler evidence

最后更新：2026-07-29（Asia/Shanghai）

## 完成范围

- 在既有 `pre-soak 只读准入证据` 卡片内增量展示顶层 `ack_readiness`。
- 展示 scheduler evidence 的 G2/G4 显式 expected/recorded/missing 到期点，以及
  simulated、late、risk/block、health mismatch 和完整性状态。
- ACK 与 scheduler 字段缺失时进入兼容空态，不把未知状态显示为通过。
- 固定提示：required 告警未记录或未 ACK、scheduler 到期点未记录或不匹配都不能晋级。
- 保持卡片无按钮、无表单、无 POST、无启动或授权入口。
- 仅修改 `src/xhs_scout/workbench_ui.py`、`tests/test_workbench_ui.py` 并新增本说明。

## 兼容与安全语义

- ACK 首选顶层 `ack_readiness`，兼容从旧 `summary.ack_*` 字段构造只读视图。
- scheduler evidence 依次读取顶层、`record.scheduler_evidence` 和旧
  `summary.scheduler_evidence_*` 字段。
- 未返回新字段、完整性损坏、missing/unresolved ACK、scheduler 缺点、模拟点、
  延迟、风险或健康不匹配均不会显示为可晋级。
- 动态内容继续通过 DOM 节点与 `textContent` 渲染，不使用 `innerHTML`。
- 没有修改 `web.py`、`soak_readiness.py`、生产数据库、`data/`、`HANDOFF.md` 或
  `PARALLEL_WORK.md`。

## 验证证据

- 定向及 T29/T34/T40 相邻回归（最终复跑）：`44 passed in 1.62s`。
- 内嵌 JavaScript：`node --check -` 退出码 `0`。
- Python 编译：`compileall` 退出码 `0`。
- 完整套件首次运行：`406 passed, 1 failed in 25.87s`。唯一失败是
  `tests/test_remediation_web.py::test_remediation_surface_exposes_get_plan_only`：
  当前共享 `web.py` 已新增 T51 的只读 `GET /api/remediation-approval`，旧断言仍要求
  remediation 路由只能有 `/api/remediation-plan`。该失败不在 T50 独占写入范围内，
  本任务未修改或回滚相关文件。
- 排除上述已定位的范围外旧断言后：`406 passed, 1 deselected in 25.94s`。

## 未验收项与边界

- 按任务禁令未访问 8793/8765，未做真实浏览器视觉验收。
- 未访问 ADB、BlueStacks、小红书、生产数据库、真实采集/补证、soak 或计划任务。
- T51 路由与旧 T30 回归断言的集成修正应由总控或对应文件所有者处理。
