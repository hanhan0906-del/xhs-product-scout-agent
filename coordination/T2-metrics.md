# T2：灰色指标条采集质量

先完整读取 `C:\Users\Lenovo\AGENTS.md`、项目 `HANDOFF.md` 和根目录 `PARALLEL_WORK.md`。

只完成 `PARALLEL_WORK.md` 中 T2。严格遵守独占写入范围。不要操作模拟器、ADB、8793、真实数据库或 `data/`。

保留已验证参数 `focus_taps=4`、`swipe_pixels=240`、`swipe_ms=900`。重点解决动态 ROI、多帧合并去重、半截 OCR 和污染帧过滤。所有验证必须是离线测试。

交付时必须说明：

- 修改文件；
- 污染判断与冲突合并规则；
- 新增测试；
- 测试命令与结果；
- 主对话是否需要改调用接口。
