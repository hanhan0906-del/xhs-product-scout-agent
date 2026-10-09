# 小红书选品 Agent 运营手册

本手册只说明本机 Windows 上的运行维护。项目工作台固定使用
`http://127.0.0.1:8793/`。端口 `8765` 属于另一个 Agent，任何时候都不得把本项目
的启动、健康检查或停止命令改到 `8765`。

当前能力边界：

- 可以保守地启停 8793 工作台、检查健康、暂停或恢复小时级调度。
- 可以根据运行租约避免两个监控轮次同时操作设备，并在风险信号出现时暂停。
- 计划任务安装会修改 Windows 外部配置，必须在用户明确确认后才可执行。
- 计划任务只负责恢复 8793 工作台，不等于监控已恢复，也不代表完成过 24 小时运行。
- 未经真实连续验证，不得声称系统已完成 24 小时无人值守运行。
- 关键词来源、拆解、组合和审核以 `coordination\KEYWORD_STRATEGY.md` 为准；旧 78 词和旧 126 候选不得直接恢复为新生产词池。

## 1. 固定路径与进入项目

```powershell
$ProjectRoot = 'C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent'
Set-Location -LiteralPath $ProjectRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
```

主要入口：

```text
ops\start_workbench.ps1
ops\stop_workbench.ps1
ops\health_check.ps1
ops\install_scheduled_task.ps1
ops\logs\workbench.stdout.log
ops\logs\workbench.stderr.log
ops\logs\workbench.pid
```

所有会改变状态的 PowerShell 脚本默认以 `dry-run` 方式只预览；启停和安装计划
任务必须显式加 `-Execute`。以下命令均假定当前目录为项目根目录。
这些脚本也支持 PowerShell 通用参数 `-WhatIf`；它只用于再次确认预期动作，
不能与 `-Execute` 一起当作已经执行成功的证据。

## 2. 8793 启动

先预览，不启动进程：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\start_workbench.ps1
```

确认目标仍为 `127.0.0.1:8793` 后启动：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\start_workbench.ps1 -Execute
```

需要启动后打开浏览器时：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\start_workbench.ps1 -Execute -OpenBrowser
```

启动脚本的实际行为：

- 发现 8793 已由本项目拥有时，直接成功退出，不重复启动。
- 发现 8793 有非本项目监听者时，拒绝启动，也不会停止该进程。
- 后台进程使用隐藏窗口运行；标准输出和错误分别写入
  `ops\logs\workbench.stdout.log` 和 `ops\logs\workbench.stderr.log`。
- PID 写入 `ops\logs\workbench.pid`，但停止脚本以端口和命令行所有权为准，
  不会只凭 PID 文件杀进程。
- 启动前处理日志：默认把超过 10 MB 的 `*.log` 改名为时间戳 `.old`，并在
  `*.log*` 中只保留最新 10 个文件。这是“启动时轮换”，不是持续轮换。
- 启动后最多等待约 15 秒检查 `/api/status`；若未健康会报错。此时报错不应被
  理解为进程一定已退出，必须再查端口和日志。

`start_workbench.ps1` 技术上接受 `-Port` 参数，因此 8765 隔离依赖运营约束：
不要传 `-Port 8765`，日常命令保持默认 8793。

## 3. 8793 停止

先预览将停止的 PID 和命令行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\stop_workbench.ps1
```

只停止验证为本项目所有的 8793 监听进程：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\stop_workbench.ps1 -Execute
```

仅在普通停止失败且已经再次核对所有权后，才可强制停止：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\stop_workbench.ps1 -Execute -Force
```

停止脚本硬性拒绝 8793 以外的端口，不扫描、不停止 8765。若 8793 存在任何
非本项目所有者，脚本会拒绝停止，避免误杀。

## 4. 进程所有权标记

启动、停止和健康检查不会只看端口或 PID。监听进程的
`Win32_Process.CommandLine` 必须同时包含：

1. 精确项目标记  
   `--project-root="C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent"`
2. CLI 标记之一：`xhs_scout.cli` 或 `xhs-scout`
3. 子命令 `serve`
4. 目标端口号 `8793`

只读查看 8793 监听者及命令行：

```powershell
$Owners = Get-NetTCPConnection -LocalPort 8793 -State Listen -ErrorAction SilentlyContinue
$Owners | ForEach-Object {
    Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)" |
        Select-Object ProcessId, Name, CommandLine
}
```

确认 8765 仍完全隔离：

```powershell
Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, State, OwningProcess
```

不要用通用的 `Stop-Process`、`taskkill` 或“按 python 进程名批量结束”代替项目停止
脚本。

## 5. 健康检查与验收

标准只读健康检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\health_check.ps1
```

机器可读输出：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\health_check.ps1 -Json
```

健康检查必须同时满足：

- 8793 至少有一个本项目所有的监听者；
- 8793 没有非本项目所有者；
- `/api/status` 返回 2xx；
- `/api/monitor/status` 返回 2xx；
- `/export/candidates.csv` 返回 2xx。

单独验证 HTTP：

```powershell
Invoke-WebRequest http://127.0.0.1:8793/api/status -UseBasicParsing -TimeoutSec 5 |
    Select-Object StatusCode
Invoke-WebRequest http://127.0.0.1:8793/api/monitor/status -UseBasicParsing -TimeoutSec 5 |
    Select-Object StatusCode
Invoke-WebRequest http://127.0.0.1:8793/export/candidates.csv -UseBasicParsing -TimeoutSec 5 |
    Select-Object StatusCode
```

查看监控状态和最近事件：

```powershell
Invoke-RestMethod http://127.0.0.1:8793/api/monitor/status |
    ConvertTo-Json -Depth 8
```

CLI 只读状态：

```powershell
& $Python -m xhs_scout.cli status
& $Python -m xhs_scout.cli monitor-state
```

重点核对字段：

- `desired_state`：期望状态，只有 `running` 或 `paused`。
- `scheduler_running`：内置调度线程记录的运行状态。
- `next_run_at`：下一轮计划时间；暂停或阻塞后通常为空。
- `risk_stop_reason`：验证码、操作频繁、ANR 或禁区等硬停止原因。
- `last_block_reason`、`last_skip_reason`：最近软阻塞或跳过原因。
- `last_run_id`、`last_heartbeat`：最近一轮标识和心跳。

## 6. 关键词池与小时级调度

### 6.1 关键词池准入

当前生产关键词的准入顺序是：

1. 从 `config\discovery_root_terms.txt` 选择小批发现根词；
2. 真实采集后，为每个商品保存根词、搜索上下文、商品证据和拆解词元；
3. 达到 `coordination\KEYWORD_STRATEGY.md` 的数据门槛后，生成 `pending_review` 组合；
4. 人工批准并完成受控写入后，关键词才能进入生产队列。

`config\seed_keywords.txt` 和当前 `config\keyword_portfolio.json` 属于旧方案。即使旧接口仍能读取或展示，也不得据此批量入队、恢复全部任务或启动轮转。新批准清单和生产写入入口尚未完成前，保持监控暂停。

### 6.2 小时级调度

8793 工作台内置保守调度器，默认每 3600 秒尝试一轮；默认每轮最多处理 1 个
关键词、每个关键词 1 个商品。工作台启动时只有数据库中的
`desired_state=running` 才会启动调度线程。

推荐通过 8793 API 恢复，因为它会同时写入期望状态并启动当前 Web 进程内的调度
线程：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8793/api/monitor/resume |
    ConvertTo-Json -Depth 6
```

随后验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8793/api/status |
    Select-Object -ExpandProperty scheduler
Invoke-RestMethod http://127.0.0.1:8793/api/monitor/status |
    ConvertTo-Json -Depth 8
```

独立 CLI 循环也支持小时级间隔：

```powershell
& $Python -m xhs_scout.cli monitor-loop --interval-seconds 3600 `
    --max-keywords 1 --max-products-per-keyword 1
```

但它是前台长运行进程，不使用工作台后台日志脚本，也不会被 8793 的调度线程唤醒。
日常运营不要同时启动 CLI 循环和工作台内置调度。即使误启动，运行租约也会让同一
时刻只有一个 `monitor_once` 获得所有权；未获得租约的一轮会返回 `busy=true`，
而不是操作设备。

CLI 的 `--recurring-interval-hours 24` 是关键词再次入队的冷却参数，不是“已运行
24 小时”的证明。计划任务每 15 分钟检查启动也不是监控采集频率；实际内置监控
间隔仍是 1 小时。

## 7. 暂停与恢复

推荐暂停方式：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8793/api/monitor/pause |
    ConvertTo-Json -Depth 6
```

该入口会把 `desired_state` 设为 `paused` 并唤醒正在等待的内置调度线程。它不会
强制中断已经进入设备操作的当前轮次；暂停后仍应观察状态与日志，确认当前轮次已经
返回，再把系统视为完全静止。

CLI 也可写入暂停状态：

```powershell
& $Python -m xhs_scout.cli monitor-pause
```

恢复前必须先完成第 8 节的风险检查。确认页面安全后，推荐使用 API 恢复：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8793/api/monitor/resume |
    ConvertTo-Json -Depth 6
```

CLI 命令：

```powershell
& $Python -m xhs_scout.cli monitor-resume
```

CLI `monitor-resume` 只把数据库期望状态设为 `running`，并清除
`risk_stop_reason`；它不会直接启动已经停止的 Web 调度线程。因此工作台在线时
优先使用 API/界面恢复，并核对 `scheduler.thread_alive`。

## 8. 风险停止与人工恢复边界

出现以下任一情况，应保持暂停，不得用 `--ignore-paused` 绕过：

- 安全验证、验证码、操作频繁或账号风控；
- ANR、未知页面、禁区或 UI 树不可解释；
- 离开搜索流程、回退失败或商品页所有权无法确认；
- 运行租约所有者异常、同一任务状态无法解释；
- 连续失败达到受控实验预算。

风险信号会写入 `risk_stop_reason` 并将 `desired_state` 设为 `paused`。软阻塞通常
写入 `last_block_reason`，同样会暂停调度。`/api/monitor/run-once` 在风险停止仍
生效时返回 HTTP 409；CLI `monitor-once --ignore-paused` 也不会越过
`risk_stop_reason`。

恢复前的只读步骤：

```powershell
Invoke-RestMethod http://127.0.0.1:8793/api/monitor/status |
    ConvertTo-Json -Depth 8
Get-Content -LiteralPath .\ops\logs\workbench.stderr.log -Tail 100
Get-Content -LiteralPath .\ops\logs\workbench.stdout.log -Tail 100
```

还必须由人工确认模拟器当前页面无验证码、无风控、无 ANR，且页面上下文与待处理
任务一致。只有确认风险已解除后，才执行恢复命令。恢复动作会清空
`risk_stop_reason`，所以不要为了“试试看”直接恢复。

用户已于 2026-07-31 明确允许系统在小红书出现 ANR 时关闭并重开应用。当前
自恢复边界如下：

- 当前商品立即中止，不从不确定坐标继续点击；
- 每次当前明确 ANR 都关闭并重开小红书；不得读取或使用跨轮次的“一次性恢复
  额度”拒绝当前恢复；
- 发现流程恢复安全首页/搜索页后中止当前轮，由下一轮从安全起点重新搜索；
- 零点销量流程恢复安全页后，从已冻结的固定商品链接重新尝试当前商品；
- 只允许关闭并重开 `com.xingin.xhs`，不得自动重启 BlueStacks、操作 8765 或
  绕过登录/验证码/风控；
- 重开后必须探测到首页或已识别的搜索页，且无 ANR、验证码和风控，才视为恢复；
- 恢复后页面未知、登录失效、验证码、风控、商品身份不明或数据库锁异常仍保持
  暂停并保留证据；
- 恢复只清理由本次恢复流程刚写入的精确 ANR 原因；历史风险或其他原因仍必须
  人工确认，不得借此普通恢复。
- RapidOCR 在独立工作进程中运行，单次硬超时 60 秒；超时后必须终止 OCR 工作
  进程并保留截图、窗口文本和 `probe.json`，不得继续等待同一 OCR 调用。

## 9. 后台日志与诊断

查看最近错误和输出：

```powershell
Get-Content -LiteralPath .\ops\logs\workbench.stderr.log -Tail 100
Get-Content -LiteralPath .\ops\logs\workbench.stdout.log -Tail 100
Get-Content -LiteralPath .\ops\logs\workbench.pid -ErrorAction SilentlyContinue
```

持续观察日志是只读操作：

```powershell
Get-Content -LiteralPath .\ops\logs\workbench.stderr.log -Tail 50 -Wait
```

PID 文件只用于辅助诊断。若 PID 文件、监听端口和命令行不一致，以当前
`Get-NetTCPConnection` 与 `Win32_Process.CommandLine` 的联合结果为准。

## 10. Windows 计划任务：必须先取得明确确认

计划任务安装属于 Windows 外部配置变更。未获得用户对“现在安装”的明确确认时，
最多只能运行默认预览，不能加 `-Execute`。

只预览：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\install_scheduled_task.ps1
```

用户明确确认后才可安装：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\install_scheduled_task.ps1 -Execute
```

默认任务名为 `XhsProductScoutWorkbench8793`，触发器为用户登录时及每 15 分钟，
动作是运行 `start_workbench.ps1 -Execute`。脚本使用 `-Force` 注册，因此可能
覆盖同名计划任务；执行前应先只读检查：

```powershell
Get-ScheduledTask -TaskName 'XhsProductScoutWorkbench8793' -ErrorAction SilentlyContinue |
    Select-Object TaskName, State, TaskPath
```

安装后才可用以下命令验证；仅看到任务存在不等于 8793 健康，更不等于监控已运行
24 小时：

```powershell
Get-ScheduledTask -TaskName 'XhsProductScoutWorkbench8793' |
    Select-Object TaskName, State, TaskPath
Get-ScheduledTaskInfo -TaskName 'XhsProductScoutWorkbench8793' |
    Select-Object LastRunTime, LastTaskResult, NextRunTime
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\health_check.ps1
```

本手册不宣称该计划任务当前已经安装。

## 11. 常见故障排查

### 8793 无监听

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\start_workbench.ps1
Test-Path -LiteralPath .\.venv\Scripts\python.exe
Get-Content -LiteralPath .\ops\logs\workbench.stderr.log -Tail 100
```

先看预览中的 Python、工作目录和参数，再决定是否执行启动。

### 8793 被非项目进程占用

```powershell
Get-NetTCPConnection -LocalPort 8793 -State Listen |
    ForEach-Object {
        Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)" |
            Select-Object ProcessId, Name, CommandLine
    }
```

不要自动结束该进程。记录 PID 和命令行，确认归属后交由对应项目处理。

### 启动脚本报告健康超时

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\health_check.ps1 -Json
Get-Content -LiteralPath .\ops\logs\workbench.stderr.log -Tail 200
Get-Content -LiteralPath .\ops\logs\workbench.stdout.log -Tail 200
```

同时核对端口所有权。若确认是本项目残留监听者，可使用项目停止脚本，再重新启动；
不要直接按 PID 猜测性结束。

### API 正常但调度未运行

```powershell
Invoke-RestMethod http://127.0.0.1:8793/api/status |
    ConvertTo-Json -Depth 8
Invoke-RestMethod http://127.0.0.1:8793/api/monitor/status |
    ConvertTo-Json -Depth 8
```

若 `desired_state=paused`，先判断是人工暂停、软阻塞还是风险停止。若
`risk_stop_reason` 非空，必须人工检查页面后再恢复。若风险为空且已经明确决定恢复，
使用 `/api/monitor/resume`，不要只调用 CLI `monitor-resume`。

### 调度返回 busy 或租约已被占用

`busy=true` 表示已有一轮持有监控租约，是防重入结果。查看
`/api/monitor/status` 的最近事件和 `last_heartbeat`，不要再启动第二个循环。只有
租约已过期且没有对应活跃进程时，后续轮次才会按代码的租约恢复规则接手。

### 风险停止反复出现

保持 `paused`，保存状态、日志和已有截图证据。不要连续恢复重试。按受控实验规则
限定 3 至 5 组参数；出现验证码、安全限制、危险页面或不可解释异常时立即停止并
汇报。

### 8765 隔离核对

```powershell
Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
rg -n "8765" .\ops .\OPERATIONS.md
```

只读核对即可，不停止、不重启、不修改 8765 的所有者。

## 12. 每次运营变更后的最小验证清单

1. 运行 `health_check.ps1 -Json`，确认 `ok=true`、`port=8793`。
2. 查看 8793 命令行，确认项目根路径、CLI、`serve` 和 8793 四项所有权标记。
3. 只读查看 8765，确认未对其执行任何启停动作。
4. 查看 `/api/monitor/status`，记录期望状态、风险原因、阻塞原因和最近事件。
5. 若恢复小时级调度，再核对 `/api/status` 中
   `scheduler.thread_alive=true`、`interval_seconds=3600`。
6. 查看后台错误日志，确认没有新的启动异常。
7. 若安装过计划任务，另行核对任务定义和最近结果；不要把它当作 24 小时运行证明。
