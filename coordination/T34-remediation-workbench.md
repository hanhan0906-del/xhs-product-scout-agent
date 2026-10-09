# T34 工作台只读补证计划视图

更新时间：2026-07-29（Asia/Shanghai）

## 范围与边界

- 仅修改 `src/xhs_scout/workbench_ui.py`、`tests/test_workbench_ui.py`，并新增本说明。
- 在既有“报告与质量”工作区增量加入补证计划视图，没有重做顶层导航或整站。
- 读取既有 `GET /api/remediation-plan`；没有新增补证执行、批准、队列写入或其他 POST
  动作。
- 保留 T29 的“衍生关键词人工审核”区域、`GET /api/keyword-suggestions` 读取逻辑及
  原有只读边界检查。
- 未修改 `web.py`、数据库、`data/`、`HANDOFF.md` 或 `PARALLEL_WORK.md`，未访问
  8793/8765、ADB、BlueStacks、小红书、真实采集、soak 或计划任务。

## 展示内容

- 计划概览：最早可执行阶段、下一批、批次数、隔离商品数和计划访问数。
- 批次预算：单批上限、每小时访问上限、商品冷却小时和下一批商品数。
- 阶段与批次：批次 id、阶段、小时窗、商品、计划动作和批次上限。
- 隔离与跳过：商品 id、代码、原因、阻塞项和可重试时间。
- 依赖 / 阻塞：按商品显示隔离依赖或阶段阻塞项。
- 空计划、接口警告、只读边界异常和 HTTP/解析失败均显示明确空态或错误提示。
- 初次加载和人工点击工作台“刷新”时读取补证计划；原有 10 秒状态轮询不重复读取。
- 动态内容继续使用 DOM 节点和 `textContent`，没有使用 `innerHTML`。

## 验证证据

定向回归：

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests\test_workbench_ui.py `
  tests\test_keyword_discovery_web.py `
  tests\test_remediation_web.py
```

最终复跑结果：`24 passed in 0.89s`。

内嵌 JavaScript：

```powershell
$env:PYTHONUTF8='1'
# 从 render_workbench_html() 提取 <script> 后传给 node --check -
```

结果：退出码 `0`。

## 集成注意事项

- 本任务只做离线静态与契约测试，没有启动服务或做真实浏览器视觉验收。
- 主任务如需视觉验收，应在其真实状态所有权范围内核对桌面与 390px 移动端布局。
- 当前动作、原因和依赖直接展示 API 的机器字段，后续如需中文术语映射，应继续只在
  `workbench_ui.py` 内增量适配，不要求修改 API。
