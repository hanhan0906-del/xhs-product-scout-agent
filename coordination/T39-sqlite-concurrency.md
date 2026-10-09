# T39：SQLite 并发读写压力离线测试

最后更新：2026-07-29（Asia/Shanghai）

## 边界

- 只使用 `tmp_path` 临时 SQLite；
- 未读取或写入生产数据库、`data/`；
- 未访问 8793/8765、ADB、BlueStacks、小红书、真实采集、soak 或计划任务；
- 测试是有界离线竞争模型，不是墙钟 soak 证据。

## 测试模型

`tests/test_sqlite_concurrency.py` 同时启动 5 个 daemon worker，并由
`threading.Barrier` 同步起跑：

- 3 路工作台只读：各 24 次短连接，读取 dashboard、monitor state、任务状态聚合和
  当前 monitor lease；
- 1 路 monitor 短写：16 次短连接，更新 heartbeat 和 scheduler output；
- 1 路租约/任务写：获取全局租约，顺序处理 8 个临时任务；每个任务执行全局租约
  heartbeat、任务 reserve、全局/任务租约原子续期，以及 succeed 或不可重试 fail；
  最后释放全局租约。

测试不使用 `sleep`。所有循环均有限，barrier 自带 5 秒 timeout，worker 统一使用
15 秒 monotonic deadline；超时线程、任何 worker 异常或任何租约 fail-closed 结果
都会令测试失败。

## 最终断言

- 所有 worker 正常结束，异常列表为空；
- 3 路读取和两路写入均完成精确次数；
- `PRAGMA quick_check = ok`；
- `journal_mode = wal`，`busy_timeout = 10000`；
- monitor 最终写入值可解释；
- monitor lease 已释放；
- 8 个任务均 `attempts=1`，4 个 `completed`、4 个
  `needs_manual_detail`，无 `pending/running`，无残留 owner/lease。

## 验证证据

项目虚拟环境：

```text
.\.venv\Scripts\python.exe -m pytest -q tests\test_sqlite_concurrency.py
1 passed in 0.72s
```

随后独立进程重复 3 次：

```text
repeat 1/3: 1 passed in 0.80s
repeat 2/3: 1 passed in 0.66s
repeat 3/3: 1 passed in 0.75s
```

最终完整套件：

```text
287 passed in 12.23s
```

第一次完整套件曾在并行任务更新 `web.py` 和
`tests/test_soak_readiness_web.py` 的同一时刻得到 `285 passed, 2 failed`；两项失败
均属于 soak-readiness Web 契约。文件更新结束后，该文件定向运行 `5 passed in
0.83s`，随后完整套件 `287 passed`。T39 未修改这些文件。

## 缺口与风险

- 这是小规模、短时、单进程多线程的离线竞争模型，不能替代 6–8h pre-soak 或 24h
  soak；
- 不覆盖真实磁盘压力、进程硬退出、跨进程连接风暴、设备步骤阻塞或生产库体量；
- SQLite `busy_timeout` 的通过只证明本模型中的短写竞争没有传播未处理锁异常。
