# 本地自动运行入口

这个入口把两件事严格分开：

1. `service_recovery_enabled` 只负责恢复本项目的 8793 工作台；不操作 8765。
2. `scheduler_recovery_enabled` 默认是 `false`。即使 8793 被恢复，也不会自动开始采集。

如需未来启用调度恢复，先把示例配置复制为 `autorun.config.json`，再由人工把
`scheduler_recovery_enabled` 改成 `true`。入口仍只会在现有健康检查通过、没有
`risk_stop_reason`、且数据库中保留 `desired_state=running` 时调用普通
`/api/monitor/resume`。它不会调用 `risk-resume`，不会清除验证码、登录、风控、
设备身份异常、数据库锁或其他停止原因。

所有脚本默认 dry-run。安装、卸载和真实执行都必须显式传入 `-Execute`。
状态保存在 `ops/logs/autorun/status.json`，追加日志保存在
`ops/logs/autorun/autorun.jsonl`；查询脚本默认只读取该状态文件，只有显式传入
`-IncludeTaskScheduler` 才读取 Windows 计划任务状态。
