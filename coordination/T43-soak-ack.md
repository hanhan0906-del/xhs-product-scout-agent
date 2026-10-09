# T43：pre-soak / soak 人工告警 ACK 离线记录

最后更新：2026-07-29（Asia/Shanghai）

## 完成范围

新增纯本地、显式调用模块 `src/xhs_scout/soak_ack.py`。它不读取生产数据库，不接入
Web、scheduler、monitor，也不会启动 pre-soak 或 soak。

主要 API：

- `append_soak_ack(...)`：追加一条人工决定；
- `read_soak_acks(...)`：按物理顺序读取并校验完整 JSONL 哈希链；
- `evaluate_ack_readiness(...)`：要求调用方显式给出必须处理的告警 ID，缺失、拒绝、
  延后或账本损坏均返回 `ready=false`。

每条记录包含 schema、连续序号、record/alert ID、告警类别、操作人、带时区决定时间、
`acknowledge/reject/defer`、证据路径、备注、前序哈希和记录哈希。

## 安全与审计边界

- 账本路径与证据路径都必须解析到调用方显式传入的 `allowed_roots` 内；
- 证据必须已存在，符号链接或 `..` 解析后的越界路径会被拒绝；
- credential、Cookie、password、secret、token 等字段禁止进入账本；
- 写入使用独占锁文件、单行追加、flush 与 `fsync`；
- 同一 `record_id` 的相同调用幂等返回，内容冲突会拒绝；
- 后续决定不会覆盖旧记录；某告警只有最新决定为 `acknowledge` 才算已 ACK；
- 坏 JSON、截断行、字段异常、重复 ID、断链、哈希不匹配和证据失效均 fail closed。

本模块不尝试防御有权限同时重写整个账本和全部哈希的恶意操作者；如需更强不可抵赖
性，应由后续集成任务另行设计外部签名或只追加存储。

## 验证边界

`tests/test_soak_ack.py` 只使用 `tmp_path`，覆盖合法 ACK、幂等/冲突、后续决定、
坏 JSON、篡改/截断、路径越界、敏感字段、缺 ACK、确定性读取和时间/证据校验。

验证结果：

```text
定向：13 passed in 0.53s
完整：304 passed in 11.35s
```

未修改 T31/T37、既有源码/测试、生产数据库、`data/`、`HANDOFF.md` 或
`PARALLEL_WORK.md`；未访问服务、ADB、BlueStacks、小红书、真实采集、补证、soak
或计划任务。
