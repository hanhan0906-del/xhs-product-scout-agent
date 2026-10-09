# T12 集成只读代码审查报告

审查时间：2026-07-28（Asia/Shanghai）

审查范围：`src/xhs_scout/insights.py`、`scheduler.py`、`web.py`、`reports.py`、`keyword_portfolio.py`、`digest.py`、`quality.py`、`low_follower.py` 相关口径、`monitor.py`/`db.py`/`run_control.py` 的集成调用点，以及 `ops/*.ps1` 运维脚本。

边界确认：项目目录当前不是 Git 仓库，无法用 `git diff` 区分“未提交变更”；本报告按当前工作区文件树审查。未修改任何生产代码、测试、真实 `data/`，未操作服务、ADB、BlueStacks 或小红书。验证方式为只读静态检查与 AST 导入图检查；未运行测试，避免产生测试缓存或触碰真实环境。

## 结论摘要

- 未发现 `web.py`、`scheduler.py`、`insights.py`、`reports.py`、`keyword_portfolio.py`、`digest.py`、`quality.py` 之间的 Python 循环导入；AST 导入图检查结果为 `cycles: []`。
- 任务级 SQLite 租约主路径已经接入 `run_control.reserve_next_runnable_task()`，未发现同一任务会被两个监控轮次直接并发执行的明显缺陷。
- 仍有 8 个集成风险需要处理，其中 2 个 P1、5 个 P2、1 个 P3。P1 主要集中在风险停止绕过与截图路径出界。

## P1：工作台单轮运行会绕过并清除风险停止

位置：
- `src/xhs_scout/web.py:187-199`
- `src/xhs_scout/monitor.py:740-747`
- `src/xhs_scout/db.py:585-590`

问题：`POST /api/monitor/run-once` 固定以 `ignore_paused=True` 调用 `monitor_once()`。`monitor_once()` 在 `ignore_paused` 为真时，即使当前 `desired_state=paused` 且 `risk_stop_reason` 非空，也会清空 `risk_stop_reason`、`last_block_reason`、`last_skip_reason` 并继续进入真实采集流程。

可复现条件：
1. 数据库 `monitor_state` 中存在 `desired_state=paused` 和 `risk_stop_reason='captcha detected'`。
2. 在工作台点击“执行单轮”，或直接请求 `POST /api/monitor/run-once`。
3. 代码会进入 `monitor_once(settings, ignore_paused=True)`，并在开始阶段清空风险状态，随后可能操作模拟器。

影响：风险停止本应要求人工确认页面、账号和风控状态后再恢复；当前单轮入口相当于提供了一个无确认的风险覆盖按钮。

最小修复建议：
- `web.py` 在 `monitor_run_once()` 入口先读取 `get_monitor_state()`；若 `risk_stop_reason` 非空，返回 409，除非请求体显式带 `confirm_risk_override=True`。
- `monitor.py` 不应因 `ignore_paused=True` 自动清空 `risk_stop_reason`；风险字段只应由明确的“人工恢复/清除风险”动作清理。

## P1：截图接口可按数据库路径读取项目外文件

位置：
- `src/xhs_scout/web.py:307-316`
- `src/xhs_scout/insights.py:282-288`

问题：`GET /captures/{observation_id}` 直接信任 `observations.screenshot_path`，只判断路径存在，然后 `FileResponse(row["screenshot_path"])`。如果数据库中该字段被错误写成绝对路径或被污染为项目外路径，本地工作台会读取并返回任意存在文件。`insights._path_exists()` 也会把项目外绝对路径视为有效证据。

可复现条件：
1. 某条 `observations.screenshot_path` 为 `C:\Users\Lenovo\some-private-file.txt`。
2. 请求 `/captures/{observation_id}`。
3. 只要文件存在，接口会返回该文件内容。

影响：虽然工作台绑定本机，但这仍破坏证据目录边界；若工作台被浏览器插件、局域网误暴露或脚本调用，可能泄露项目外文件。

最小修复建议：
- 对截图路径做 `Path(...).resolve()`，只允许位于 `settings.capture_dir.resolve()` 或明确证据根目录下。
- 对项目外路径返回 404，并在质量审计中把项目外绝对路径标为 `screenshot_path_out_of_scope`。

## P2：10 秒轮询的 `/api/status` 过重，数据增长后会拖慢工作台

位置：
- `src/xhs_scout/web.py:124-141`
- `src/xhs_scout/insights.py:21-93`
- `src/xhs_scout/insights.py:96-178`
- `src/xhs_scout/insights.py:181-221`
- `src/xhs_scout/workbench_ui.py:562-678`

问题：前端每 10 秒请求一次 `/api/status`，后端同一个请求内执行：
- `dashboard_stats()` 和最近 30 条查询；
- `quality_snapshot()`，读取最多 200 商品、500 观察、500 笔记、500 搜索证据并做审计；
- `digest_snapshot()`，读取 500 观察、最多 500 任务以及全部候选；
- `portfolio_snapshot()`，读取全部 `search_tasks` 并重建关键词轮转计划。

可复现条件：当 `observations`、`search_result_evidence`、`note_observations` 和候选数量继续增长时，保持工作台打开即可每 10 秒重复全量摘要/审计计算。

影响：SQLite 读压力和 Python CPU 会随数据增长放大；调度器运行时还可能与采集写入争用 SQLite 连接，造成工作台卡顿或偶发 `database is locked`。

最小修复建议：
- `/api/status` 只返回轻量状态、计数和最近列表。
- 新增 `/api/quality`、`/api/digest/daily`、`/api/portfolio` 的独立慢接口，前端降低频率或按需刷新。
- 对 digest/quality 增加缓存，例如按 `last_heartbeat`、最新 observation id 或 60 秒 TTL 缓存。

## P2：摘要的低粉闭环阈值与真实升 A 阈值不一致

位置：
- `src/xhs_scout/digest.py:611-621`
- `src/xhs_scout/low_follower.py:10-26`
- `src/xhs_scout/quality.py:616-618`

问题：真实升 A 逻辑 `evaluate_low_follower_evidence()` 要求标准低粉为 `follower_count <= 2000 and likes >= 1000`，但 `digest._strict_low_follower_complete()` 使用 `profile_follower_count < 10000 and note_likes >= 1000`。因此摘要可能把 9000 粉丝、1000 点赞、近 7 天的证据标成“已具备近期低粉单条笔记互动闭环”，但真实 `promote_candidate_from_note_observations()` 不会升 A。

可复现条件：
1. 候选 `low_follower_verified=0`。
2. `profile_follower_count=9000`，`note_likes=1000`，`note_published_days_ago=1`，作者名一致。
3. `digest_snapshot()` 会把它计入 `low_follower_complete`，而 `low_follower.py` 不会验证通过。

影响：报告和工作台摘要可能误导人工以为低粉证据已经闭环；目前看不会直接写入 A 级，但会影响运营判断。

最小修复建议：
- `digest.py` 直接复用 `evaluate_low_follower_evidence()`，不要复制阈值。
- 或至少把 `digest._strict_low_follower_complete()` 的标准阈值改为 `<= 2000`，并补测试覆盖 9000 粉丝反例。

## P2：调度器可能在一轮内同时做组合补词和历史复搜补词，超出单轮预算

位置：
- `src/xhs_scout/scheduler.py:83-89`
- `src/xhs_scout/insights.py:224-268`
- `src/xhs_scout/monitor.py:759-766`
- `src/xhs_scout/monitor.py:148-187`

问题：调度循环先调用 `ensure_portfolio_queue()`，当没有 runnable pending 任务时会从关键词组合中补 1 个词；随后 `monitor_once()` 又调用 `_requeue_due_keywords()`，可能从已完成关键词中再补 1 个 due 词。两者不共享同一个“本轮补词预算”。

可复现条件：
1. 当前无 pending/running 任务。
2. 关键词组合计划选中 A。
3. 数据库存在一个已完成且超过复搜间隔的关键词 B。
4. 单轮 `max_keywords=1` 时，调度可同时入队 A 和 B，然后只执行其中一个，另一个留在 pending。

影响：长期运行时 pending 队列可能被后台慢慢放大，违背“低频、受控、单轮小预算”的运行边界。

最小修复建议：
- 把组合补词和历史复搜补词合并到同一个 scheduler 层预算函数。
- 或让 `monitor_once()` 接受 `requeue_due=False`，由 scheduler 已补组合词时关闭历史复搜。
- 至少在 `_requeue_due_keywords()` 前检查本轮已补词数量，按剩余预算执行。

## P2：搜索归属证据可能被同键重写为有效

位置：
- `src/xhs_scout/db.py:593-648`

问题：`record_search_result_evidence()` 的 conflict update 会无条件设置 `valid=1, invalid_reason=NULL`。如果某条同 `(task_id, observation_id, result_rank)` 的搜索证据已被人工或修复脚本标成无效，后续再次记录同键证据会把它恢复为有效。

可复现条件：
1. `search_result_evidence` 中已有同键记录，`valid=0`、`invalid_reason='keyword mismatch'`。
2. 调用 `record_search_result_evidence()` 记录同键来源。
3. conflict update 清空无效原因并重设 `valid=1`。

影响：之前修复的错链/跨任务污染证据可能被后续重跑重新纳入报告和工作台。

最小修复建议：
- 默认不要在 conflict update 中清理 `valid/invalid_reason`。
- 只有调用方传入明确 `validated=True` 或新建一条新的 observation 证据时，才允许恢复有效。
- 增加测试覆盖“已标无效的同键证据不会被普通 record 调用复活”。

## P2：运维脚本的项目归属判断使用路径子串，可能误判同名前缀目录

位置：
- `ops/stop_workbench.ps1:21-40`
- `ops/stop_workbench.ps1:82-91`
- `ops/start_workbench.ps1:24-43`

问题：`Test-ProjectOwnedCommandLine()` 用 `$normalizedCommand.Contains($normalizedRoot)` 判断进程归属。如果另一个目录名以前缀方式包含当前项目路径，例如 `...\小红书选品 Agent Backup`，且也运行 `xhs_scout.cli serve --port 8793`，会被误判为当前项目进程。`stop_workbench.ps1 -Execute` 随后会停止该 PID。

可复现条件：
1. 另一个 Agent 位于 `C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent Backup`。
2. 它监听 8793，命令行包含 `xhs_scout.cli serve --port 8793`。
3. 执行当前项目 `ops\stop_workbench.ps1 -Execute`。

影响：默认端口已经降低了误杀概率，但路径前缀目录仍可能被误判，尤其在备份/复制项目时。

最小修复建议：
- 对命令行参数做 token 化，要求出现完整路径边界，例如带引号的项目根或 `--app-dir`/工作目录标记。
- 更稳妥：启动时写 PID 文件后，停止脚本同时校验 PID 文件、端口 owner、进程命令行三者一致。
- 路径比较时要求下一个字符为路径分隔符、引号或字符串结束，避免前缀匹配。

## P3：`reasons_json` 解析缺少容错，会让工作台或报告 500

位置：
- `src/xhs_scout/web.py:142-143`
- `src/xhs_scout/web.py:235`
- `src/xhs_scout/reports.py:135`

问题：这些位置直接 `json.loads(row["reasons_json"] or "[]")`。如果历史数据或人工修复写入了非 JSON 文本，`/api/status`、低粉录入接口或报告生成会抛 `JSONDecodeError`。

可复现条件：任意最新 `candidate_assessments.reasons_json='低粉待复核'`，请求 `/api/status` 或生成报告。

影响：单条坏数据会拖垮工作台状态页或报告生成。

最小修复建议：
- 增加 `_safe_json_list(value)`，解析失败时返回 `["reasons_json 解析失败，需人工复核"]` 并记录质量警告。
- 在写入端继续保持 `json.dumps(..., ensure_ascii=False)`。

## 未发现阻塞性问题的审查项

- 循环导入：未发现。只读 AST 导入图检查显示目标模块无 cycle。
- SQLite 同一任务并发：`monitor_once()` 主路径已用全局 monitor lease 和任务级 lease；`reserve_next_runnable_task()` 的 UPDATE 带状态和时间条件，未发现明显双跑同一任务问题。
- 手工低粉直接升 A：`web.py` 的手工录入会写 `note_evidence`，但实际升 A 由 `promote_candidate_from_note_observations()` 决定；该函数只读取公开笔记/作者主页 `note_observations`，未直接用手工输入升 A。残余风险是摘要口径会误报闭环，见 P2。
- JSON 序列化：`insights._json_ready()` 已处理 `datetime`、dict、list/tuple；`quality.as_dict()` 产物基本可 JSON 化。主要风险不是序列化类型，而是 `reasons_json` 反序列化容错。
- 运维脚本误杀：脚本没有使用 `taskkill` 或宽泛进程名杀进程；`stop_workbench.ps1` 限定 8793、命令行和项目路径。残余风险是路径子串误判，见 P2。

## 残余风险

- `connect()` 每次打开 SQLite 都执行 schema/migration 检查；在首次部署或多进程冷启动时仍可能放大 schema lock 风险。当前已有库迁移完成时影响较小。
- `sqlite3.connect(path)` 未显式设置 `timeout` 或 `PRAGMA busy_timeout`；状态页 10 秒重轮询和调度写入并发时，仍可能出现偶发锁等待失败。
- 未运行测试，因此本报告不声明当前测试套件通过；建议由主集成任务在处理上述问题后统一运行全量测试。
