# T51 补证审批清单只读 API

## API 契约

- 路径：`GET /api/approval-manifest`
  - 因既有 `test_remediation_web.py` 把所有包含 `remediation` 的路由限定为
    `GET /api/remediation-plan`，在不修改该文件的独占边界下采用此名称。
- 固定清单：项目根目录
  `approvals/remediation-approval.json`。
- 不接受路径参数、查询参数或请求体；不提供 POST、批准、写清单、写队列或执行入口。
- 所有响应固定：
  - `execution_status="not_executed"`
  - `authorizes_execution=false`
  - `scope.production_queue_write=false`
  - `scope.approval_write=false`
  - `scope.execution_endpoint=false`

缺文件返回：

- `review_status="pending"`
- `manifest_status="missing"`
- `plan_approval_status="pending_review"`

存在文件时依次执行：

1. 用 T45 `read_approval_manifest()` 严格检查字段、SHA-256 完整性及存储语义；
2. 使用清单 `source_generated_at` 作为确定性 planner 时间；
3. 以 SQLite URI `mode=ro` 打开当前配置数据库并显式执行
   `PRAGMA query_only=ON`；
4. 用当前数据库事实重算 T24 planner 并比较 `source_plan_hash`；
5. 用当前 planner、清单选择、决策、审核人、时间和 policy 重建 T45 清单，
   要求逐字段完全相同。

坏 JSON、完整性篡改、重新哈希后的语义篡改、planner hash 过期、预算/隔离/
依赖异常、数据库快照截断、补证冷却时间损坏、固定路径逃逸或只读数据库不可用，
全部返回 pending 且不暴露任何执行授权。

## 验证

- 最终专项及相邻接口：`76 passed in 2.67s`
- 最终完整回归：`415 passed in 29.51s`
- 测试全部使用临时项目和临时 SQLite。
- 未访问 `data/`、8793/8765、ADB、BlueStacks、小红书、真实补证/采集、
  soak 或计划任务；未修改生产数据库、队列、`HANDOFF.md` 或
  `PARALLEL_WORK.md`。
