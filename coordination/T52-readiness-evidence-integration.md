# T52：ACK + scheduler evidence + readiness 端到端安全回归

最后更新：2026-07-29（Asia/Shanghai）

## 完成范围

仅新增 `tests/test_readiness_evidence_integration.py`，使用 `tmp_path` 和公开 API
构造完整离线链：

1. digest critical 与 quality error 告警进入 T43 哈希链 ACK 账本；
2. G2 三个、G4 七个真实 scheduled point 进入 T46 哈希链 scheduler evidence 账本；
3. 调用方显式提供 G2/G4 `expected_scheduler_scheduled_at`；
4. T49 readiness 逐点绑定并判定 G2/G4。

正例要求两个告警 ID 的最新决定均为 `acknowledge`，到期点清单完全匹配，
`evidence_source=real`，且 delay、DB、HTTP、scheduler thread、lease、risk/block
全部健康，最终 G2/G4 均为 `pass`。

## 负例覆盖

- 旧告警 ACK、错误告警 ID、旧 acknowledge 后最新 `reject/defer`；
- ACK 账本哈希篡改、scheduler evidence 账本哈希篡改；
- 缺 ACK、缺显式 expected 清单；
- simulated 来源；
- expected 漏点、expected 额外点、账本出现未预期点；
- 启动延迟超过 900 秒；
- DB、HTTP、thread、lease、risk 分别异常，并分别验证 G2/G4 fail closed；
- G4 显式预期点跨度不足 6 小时；
- 原生 T46 预评估报告缺少逐点 `scheduled_at` 绑定。

按既有 T44/T49 门槛契约，ACK 直接约束 G3/G4/G5，不直接约束 G2；测试明确验证
缺 ACK 时 G2 的 scheduler evidence 门槛仍可通过，但 G3/G4 关闭。expected、真实
来源及 scheduler 健康保护则直接约束 G2/G4。

## 验证证据

```text
定向：25 passed in 10.53s
完整：414 passed in 27.65s
```

完整套件首次运行时遇到一次并行 T51 路由改名中间态，表现为旧 remediation 路由
断言失败；T51 文件稳定后重跑为 407/407，通过最终 T52 扩展后再跑为 414/414。
该瞬态未修改 T52 文件，也未要求越界修复。

## 边界与风险

- 未修改任何现有源码或现有测试；
- 未访问或修改生产数据库、`data/`、`HANDOFF.md`、`PARALLEL_WORK.md`；
- 未访问服务、ADB、BlueStacks、小红书、真实采集、补证、pre-soak/24h soak 或
  Windows 计划任务；
- 未发现需要越界修改源码的缺陷；
- 所有证据均为临时目录夹具，不代表真实 scheduler 或 soak 已具备晋级证据。
