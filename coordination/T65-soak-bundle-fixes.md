# T65：pre-soak 证据包四项 fail-closed 修复

最后更新：2026-07-29（Asia/Shanghai）

## 已完成

1. baseline 文件输入会在显式 `allowed_roots` 内重新校验 manifest 所记录的
   project root，并重新哈希 observed code/config 文件；漂移为
   `incomplete/invalid`。
2. build API 接受显式 `assembled_at` 和正数 `max_approval_age`
   （默认 24 小时）；审批过期或相对组包时间位于未来时为 `not_ready`，无效时间结构
   为 `incomplete/invalid`。
3. build API 接受显式 `current_remediation_plan_hash` 并与审批
   `source_plan_hash` 比较；不匹配为 `not_ready`。旧调用省略该输入时仍可调用，但按
   保守契约返回 `not_ready`，不推断当前计划。
4. readiness 顶层 `ready_for_pre_soak`、`ready_for_24h_soak` 分别与
   G0–G3、G0–G4 的 gate status 交叉校验；矛盾为 `incomplete/invalid`。

所有 execution、scheduler、pre-soak、24h soak 授权位仍恒为 `false`。

## 验证证据

- T62 19 项：`19 passed in 11.06s`
- T57 单元：`14 passed, 1 skipped in 0.48s`
- T57/T62 及相关模块回归：`192 passed, 3 skipped in 24.92s`
- 完整 pytest 首轮：`561 passed, 3 skipped, 1 failed`；失败为越界模块
  `test_keyword_approval_web.py` 的临时数据库文件时序问题，单独复跑通过。
- 完整 pytest 复跑：`562 passed, 3 skipped in 48.50s`

3 个 skip 均为既有 Windows 符号链接条件测试；T62 19 项无 skip。

## 边界核查

写入仅限：

- `src/xhs_scout/soak_evidence_bundle.py`
- `tests/test_soak_evidence_bundle.py`
- `tests/test_soak_evidence_bundle_integration.py`
- `coordination/T65-soak-bundle-fixes.md`

未触碰生产库、`data/`、`HANDOFF.md`、`PARALLEL_WORK.md`、服务、端口、ADB、
BlueStacks、小红书、真实采集/补证、pre-soak/24h soak 或 Windows 计划任务。
