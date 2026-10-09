# T13 运维脚本只读 / dry-run 复验报告

复验时间：2026-07-28 22:03:03 +08:00（Asia/Shanghai）
项目根目录：`C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent`

## 执行边界

- 仅运行 `ops` 下四个 PowerShell 脚本：`start_workbench.ps1`、`stop_workbench.ps1`、`health_check.ps1`、`install_scheduled_task.ps1`。
- 未使用 `-Execute`。
- 未启动或停止任何进程。
- 未注册计划任务。
- 未操作 ADB、BlueStacks 或小红书。
- 除本报告外未修改其它文件。

## 本轮修复复核

上一轮发现的两个阻断均已修复：

1. 四个脚本默认 `ProjectRoot` 已从硬编码乱码路径改为：当参数为空时使用 `Split-Path -Parent $PSScriptRoot` 推导项目根目录。
2. `start_workbench.ps1` 启动参数已包含 `--project-root="<ResolvedRoot>"`；当前 8793 监听 PID `41732` 的命令行包含正确项目路径，并被 health check 识别为项目进程。

仍保留的次要现象：

- `start_workbench.ps1 -WhatIf` 和 `stop_workbench.ps1 -WhatIf` 会因 PowerShell 模块加载输出多条 alias 相关 `What if: Performing the operation "New Alias"` / `Set Alias` 噪声。该现象影响日志可读性，但本轮未观察到状态变化，且命令退出码为 `0`。

## 脚本只读审阅结果

- 四个脚本均声明 `SupportsShouldProcess = $true`。
- `start_workbench.ps1`、`stop_workbench.ps1`、`health_check.ps1` 均通过 `Get-NetTCPConnection -LocalPort 8793` 和 `Win32_Process.CommandLine` 判断端口归属。
- 项目归属条件要求命令行同时包含：
  - 项目根目录；
  - `xhs_scout.cli` 或 `xhs-scout`；
  - `serve`；
  - `8793`。
- `stop_workbench.ps1` 明确拒绝非 `8793` 端口，并输出 `Non-target port 8765 is intentionally ignored.`。
- `start_workbench.ps1` dry-run/静态配置日志路径：
  - `ops\logs\workbench.stdout.log`
  - `ops\logs\workbench.stderr.log`
  - `ops\logs\workbench.pid`
- `install_scheduled_task.ps1` dry-run 输出的计划任务命令引用中文空格路径并加引号：
  `C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent\ops\start_workbench.ps1" -Execute`

## 命令验收记录

### 默认 dry-run / 只读命令

1. `powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\start_workbench.ps1`
   - 退出码：`0`
   - 关键输出：
     - `Project: C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent`
     - `Target:  http://127.0.0.1:8793`
     - `Workbench already appears to be running on port 8793 with PID(s): 41732`
   - 判断：默认项目路径推导成功；已运行时保持幂等，没有启动新进程。

2. `powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\stop_workbench.ps1`
   - 退出码：`0`
   - 关键输出：
     - `Project: C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent`
     - `Stop target: only project-owned listener on port 8793`
     - `Non-target port 8765 is intentionally ignored.`
     - `[dry-run] Would stop project-owned PID 41732 on port 8793`
     - `[dry-run] CommandLine: "C:\Users\Lenovo\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe" -m xhs_scout.cli serve --host 127.0.0.1 --port 8793 --project-root="C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent"`
     - `[dry-run] Re-run with -Execute to stop only the verified project process. You may also pass -WhatIf.`
   - 判断：默认 dry-run 正确识别项目进程，只预览停止动作，未停止进程；8765 明确不作为目标。

3. `powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\health_check.ps1`
   - 退出码：`0`
   - 关键输出：`OK: project-owned workbench is healthy on http://127.0.0.1:8793`
   - 判断：默认 health check 通过。

4. `powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\health_check.ps1 -Json`
   - 退出码：`0`
   - 关键输出：
     - `ok=true`
     - `project_root=C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent`
     - `port=8793`
     - `ignored_port=8765`
     - owner PID `41732`
     - `is_project_owned=true`
     - command line contains `--project-root="C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent"`
     - `http://127.0.0.1:8793/api/status` -> `200`
     - `http://127.0.0.1:8793/api/monitor/status` -> `200`
     - `http://127.0.0.1:8793/export/candidates.csv` -> `200`
   - 判断：8793 项目归属和 HTTP 健康检查均通过。

5. `powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\install_scheduled_task.ps1`
   - 退出码：`0`
   - 关键输出：
     - `Task name: XhsProductScoutWorkbench8793`
     - `Project:   C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent`
     - `Action:    C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent\ops\start_workbench.ps1" -Execute`
     - `Schedule:  at logon and every 15 minutes`
     - `Scope:     start_workbench.ps1 is idempotent and only targets port 8793; port 8765 is not used.`
     - `[dry-run] No scheduled task was registered.`
   - 判断：默认 install dry-run 通过，计划任务命令正确引用中文空格路径，未注册计划任务。

### 默认 `-WhatIf`

1. `powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\start_workbench.ps1 -WhatIf`
   - 退出码：`0`
   - 关键输出：
     - `Project: C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent`
     - `Target:  http://127.0.0.1:8793`
     - 多条 PowerShell alias `What if` 噪声。
     - `Workbench already appears to be running on port 8793 with PID(s): 41732`
   - 判断：识别已运行项目进程并退出，没有启动动作。

2. `powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\stop_workbench.ps1 -WhatIf`
   - 退出码：`0`
   - 关键输出：
     - `Non-target port 8765 is intentionally ignored.`
     - 多条 PowerShell alias `What if` 噪声。
     - `[dry-run] Would stop project-owned PID 41732 on port 8793`
     - `[dry-run] CommandLine: ... --project-root="C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent"`
   - 判断：仍处于 dry-run 预览，不停止进程；8765 不被目标化。

3. `powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\health_check.ps1 -WhatIf`
   - 退出码：`0`
   - 关键输出：
     - `[what-if] Would inspect Get-NetTCPConnection on port 8793 and request:`
     - `[what-if] http://127.0.0.1:8793/api/status`
     - `[what-if] http://127.0.0.1:8793/api/monitor/status`
     - `[what-if] http://127.0.0.1:8793/export/candidates.csv`
   - 判断：只读预览符合预期。

4. `powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\install_scheduled_task.ps1 -WhatIf`
   - 退出码：`0`
   - 关键输出：
     - `Task name: XhsProductScoutWorkbench8793`
     - `Action: ... -File "C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent\ops\start_workbench.ps1" -Execute`
     - `[dry-run] No scheduled task was registered.`
   - 判断：未传 `-Execute` 时优先 dry-run，不注册计划任务。

## 额外只读核验

1. `Get-NetTCPConnection -State Listen -LocalPort 8793,8765`
   - 退出码：`0`
   - 结果：
     - `127.0.0.1:8793` -> PID `41732`
     - `127.0.0.1:8765` -> PID `21820`
   - 判断：8793 和 8765 均仍在监听；本轮没有停止或抢占 8765。

2. `Get-CimInstance Win32_Process -Filter "ProcessId=41732"`
   - 退出码：`0`
   - 关键输出：PID `41732` 命令行为 `python.exe -m xhs_scout.cli serve --host 127.0.0.1 --port 8793 --project-root="C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent"`
   - 判断：8793 当前归属本项目。

3. `Get-CimInstance Win32_Process -Filter "ProcessId=21820"`
   - 退出码：`0`
   - 关键输出：PID `21820` 命令行为 `python.exe -m uvicorn video_course_agent.main:app --host 127.0.0.1 --port 8765`
   - 判断：8765 属于另一 Agent，本轮未触碰。

4. `Get-ChildItem -LiteralPath .\ops\logs`
   - 退出码：`0`
   - 结果：
     - `workbench.pid`
     - `workbench.stderr.log`
     - `workbench.stdout.log`
   - 判断：日志目录存在，预期日志文件路径存在。

5. `Get-ScheduledTask -TaskName 'XhsProductScoutWorkbench8793' -ErrorAction SilentlyContinue`
   - 退出码：`1`
   - 输出：空
   - 判断：本机当前未发现该计划任务；install dry-run 未注册任务。

## 是否可进入人工批准安装阶段

结论：可以进入人工批准安装阶段。

依据：

- 默认 dry-run 路径已修复，四个脚本默认运行不再解析到乱码项目路径。
- 8793 当前监听 PID `41732` 被识别为项目进程，命令行包含 `--project-root` 和正确项目路径。
- 默认 health check 退出码 `0`，三个 HTTP 端点均返回 `200`。
- 默认 install dry-run 退出码 `0`，计划任务动作正确引用中文空格路径，并明确未注册任务。
- stop 脚本默认 dry-run 只预览停止 8793 项目进程，并明确忽略 8765。
- 8765 仍由另一 Agent 的 `uvicorn ... --port 8765` 进程监听，未被本轮命令影响。

人工批准安装前建议人工再确认：

- 批准动作将运行 `install_scheduled_task.ps1 -Execute`，会注册登录时和每 15 分钟启动一次的计划任务。
- 计划任务启动命令包含 `start_workbench.ps1 -Execute`；该启动脚本是幂等的，且会拒绝非项目进程占用 8793 的情况。
- 当前仍存在 `-WhatIf` alias 噪声，建议后续优化可读性，但不阻断安装审批。
