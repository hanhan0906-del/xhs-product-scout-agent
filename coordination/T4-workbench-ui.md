# T4：工作台界面模块

先完整读取 `C:\Users\Lenovo\AGENTS.md`、项目 `HANDOFF.md` 和根目录 `PARALLEL_WORK.md`。

只完成 `PARALLEL_WORK.md` 中 T4。严格遵守独占写入范围。不要修改 `web.py`，不要操作模拟器、ADB、8793、真实数据库或 `data/`。

实现 `render_workbench_html()` 供主对话后续接入。页面应是紧凑运营工作台，不显示运行事件日志。商品标题优先跳真实商品链接，证据截图使用独立入口。

交付时必须说明：

- 修改文件；
- 页面所依赖的 API；
- 桌面和移动端布局策略；
- 测试命令与结果；
- `web.py` 的最小接入方式。
