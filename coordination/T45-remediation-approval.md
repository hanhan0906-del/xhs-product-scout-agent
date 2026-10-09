# T45 补证审批清单与预算/隔离校验

## 范围

新增 `src/xhs_scout/remediation_approval.py`，只接收 T24 planner 的普通对象输出和
人工选择，生成离线 JSON 审批清单。模块不连接数据库、不写任务队列、不访问服务或
设备，也不包含任何补证执行入口。

## API

- `build_approval_manifest(planner_output, selections, ...)`
  - `planner_output` 接受 `RemediationPlan` 或其字典形式；
  - `selections` 接受 `{batch_id: [product_id, ...]}`，或按人工顺序排列的
    `{"batch_id": ..., "product_ids": [...]}` 列表；
  - 默认 `decision="pending_review"`；
  - 只有无校验问题且显式 `decision="approve"` 时，状态才是
    `planned_approved`。
- `serialize_approval_manifest(manifest)`：确定性 UTF-8 JSON。
- `write_approval_manifest(path, manifest)`：仅写调用方指定的离线文件。
- `read_approval_manifest(path)`：校验字段、SHA-256 完整性和安全语义；篡改后
  fail closed。

所有清单固定：

- `execution_status="not_executed"`；
- `authorizes_execution=false`。

因此 `planned_approved` 只表示人工批准了离线计划，不能解释为已经执行或授权生产动作。

## 强制校验

- 阶段和选择顺序只能是 `identity → metrics → note → profile`；
- 每批最多 2 个商品，每小时最多 6 次商品级访问；
- product 20 是不可由本审批层解除的强制隔离项；
- T41 已停止低粉追踪的 product 19、20 不得进入 `note/profile`；
- `required_before`、`blocks`、动作与阶段必须符合 T24 契约；
- 隔离项、重复商品、跨批选择、非活跃状态、未知批次和坏输入均拒绝；
- 持久化后即使重算哈希，也不能把执行状态改为已执行或移除硬隔离。

## 测试与边界

- 定向：`31 passed`（`test_remediation_approval.py` + `test_remediation.py`）。
- 全量：`327 passed in 11.14s`。
- 测试只使用纯对象和 `tmp_path`。
- 未接入 `web.py`、scheduler、队列或生产数据；后续若要真实补证，必须由总控重新读取
  最新生产事实、重新规划，并在本模块之外另行取得真实动作确认。
