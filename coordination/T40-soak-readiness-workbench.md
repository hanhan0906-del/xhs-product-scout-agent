# T40：soak-readiness 只读工作台

最后更新：2026-07-29（Asia/Shanghai）

## 完成范围

- 在现有“报告与质量”工作区增量加入 `GET /api/soak-readiness` 只读视图。
- 保留 T29 衍生关键词人工审核和 T34 只读补证计划，没有重做工作台导航。
- 仅修改 `src/xhs_scout/workbench_ui.py`、`tests/test_workbench_ui.py`，并新增本说明。
- 未修改 `web.py`、生产数据库、`data/`、`HANDOFF.md` 或 `PARALLEL_WORK.md`。

## 界面信息与安全语义

- 显示 pre-soak 与 24 小时 soak 的 `ready` / `insufficient` 证据门槛状态。
- 固定显示 G0–G6 的状态和主要原因。
- 显示主要 `gaps`、`warnings`、只读数据库模式、证据表、轮次、时间范围和坏 JSON 数。
- 固定核对并展示 `soak_start_authorized=false`；同时核对
  `authorization.expansion_authorized=false`。
- 文案明确说明：这不是启动按钮或扩容授权，即使证据门槛通过也仍需另行人工确认。
- 面板没有按钮、表单、POST、启动、授权或扩容动作。
- 空 gaps、空 warnings、接口契约异常、HTTP 失败和 JSON 解析失败均有明确空态或错误态。
- 初次加载和人工点击“刷新”时读取；既有 10 秒状态轮询不重复读取该接口。
- 动态响应内容继续使用 DOM 节点和 `textContent`，没有使用 `innerHTML`。

## 验证证据

定向及相邻接口回归：

```text
33 passed in 1.14s
```

覆盖：

- `tests/test_workbench_ui.py`
- `tests/test_keyword_discovery_web.py`
- `tests/test_remediation_web.py`
- `tests/test_soak_readiness_web.py`

内嵌 JavaScript 经 `node --check -` 检查，退出码 `0`。

完整离线套件：

```text
291 passed in 11.35s
```

验证全程未访问 8793/8765、ADB、BlueStacks、小红书、生产数据库、真实采集、补证、
pre-soak、24 小时 soak、计划任务或其他共享真实状态。

## 剩余风险

- 本任务只做离线静态与契约测试，没有启动服务或做真实浏览器视觉验收。
- 若主任务后续需要视觉验收，应由真实状态所有者在其权限范围内检查桌面与移动端布局；
  该动作不应被解释为授权启动 soak 或扩容。
