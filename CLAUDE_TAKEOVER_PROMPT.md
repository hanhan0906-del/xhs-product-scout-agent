# 给 Claude 的完整接手提示词（直接复制）

你现在接手 Windows 本地项目“小红书选品 Agent”，并担任唯一总控。用户已经被此前反复失败和过度检查消耗了很多耐心。请不要让用户复述历史，不要开局通读全部代码，不要先做大而全的验收，也不要把“代码写完/测试通过/调度线程启动”冒充“24小时真实采集已经运行”。先掌握下方目标、真实状态、安全边界和任务顺序；只有遇到具体故障时，才读取指定源码。

项目根目录：

```text
C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent
```

## 一、最终目标

建立一套不依赖 Codex 或 Claude 对话窗口、能在 Windows 本机长期运行的小红书商品选品采集系统：

1. 当前业务主线是“教师开学场景资料”，已经有30个确认关键词置顶，首词是`开学第一课PPT`。
2. 每个关键词必须采集搜索结果前5个不同商品，顺序为rank1→rank5；第5件成功后才切换下一个关键词，不能每个关键词只采第1件，也不能把rank5循环映射成rank2。
3. 每件商品至少保存：源关键词、搜索排名、商品标题、价格、累计销量、店铺名称、粉丝数、商品直达链接、截图、页面类型、字段坐标范围、OCR原始框和置信度。缺失就明确记缺失或异常，不能语义猜值。
4. 商品标题和价格按页面类型及固定坐标框提取，不允许把整页文字全部识别后再猜哪个是标题：
   - extended标题ROI：`[0.02,0.825,0.98,0.90]`
   - compact标题ROI：`[0.02,0.78,0.98,0.82]`
   - 两类价格ROI：`[0.18,0.685,0.55,0.75]`
   - 页面不能唯一匹配两类时fail closed，不擅自增加第三类。
5. 日常运行最终必须由Windows本地机制启动和恢复8793服务；是否恢复采集还要通过既有安全门槛。登录、验证码、平台风控、未知页面身份、数据库锁必须停止等待人工，不能绕过。

## 二、不要通读；只按此顺序读取

第一轮只读以下内容：

1. 本文件全部。
2. `coordination/TASK_BOARD.md`只读`## 100`、`100.1`、`100.2`、`100.3`、`100.4`和`## 101`，不要从头读2400多行。
3. `HANDOFF.md`只读最后约35行，从“每个关键词改为连续采集前5个商品”到“最终更正：24小时采集未启动”；不要通读30万字历史。
4. `config/emulator.json`全部。
5. `README.md`只读启动工作台、8793/8765端口边界和常用命令部分。
6. `ops/autorun/README.md`全部，用来判断本地自动启动代码已经做到哪一步；当前尚未安装真实Windows计划任务。

明确不要读取：

- `coordination/NEXT_CONTROL_HANDOFF.md`：内容很长且主要停留在8月3日，已过期。
- `当前进度与人工接力.md`：7月23日旧状态，已过期。
- `PARALLEL_WORK.md`、`ROADMAP.md`、整个`evidence/`、整个`data/probes/`和全部测试：除非当前具体故障需要。
- 不要扫描或通读全部`src/`。

## 三、当前真实状态（2026-08-17最终检查点）

不要把更早的“已恢复”当成当前状态，以下为最终事实：

- 8793工作台HTTP正常，监听PID在最后检查时为`39008`。
- 8765属于其他项目，最后PID=`21776`，严禁停止、重启、探测业务接口或占用。
- 当前`desired_state=paused`、`scheduler_running=false`、`risk_stop_reason=null`。
- 当前block：`device preflight failed: device_selection`。
- ADB最后一次列表为空。手机型号必须是`M2010J19SC`、device=`lime`，稳定mDNS服务名为`adb-741da30b0920-cvuER5`。无线调试IP会变化；最近用户给过`192.168.1.119:39325`，但它后来已经不在线。不得扫描端口；mDNS发现不到时直接向用户要手机无线调试主页面的当前IP和端口。
- 24小时采集没有成功启动，也没有有效计时起点。最近两轮成功采集商品数都是0。
- task183：关键词`开学第一课PPT`、目标rank2、status=pending、attempts=1/3、无owner和lease、last_error=`monitor run ended before task completion`。
- 当前无running task、无run lease。
- `开学第一课PPT`只有rank1的有效证据：evidence52，task153/product68/observation68。rank2没有结果。
- 队列计数最后为：pending103、completed37、failed2、needs_manual_detail9、paused1。
- 30个开学关键词已作为task153–182置顶；连续根词配置为新30词+历史70词，共100个唯一词。不要重新入队或重复扩充。
- 当前项目目录不是Git仓库，不要执行git reset/checkout，也不要假设可以依靠git diff回滚。修改前保留明确文件备份或用小范围补丁。

## 四、最近真实失败，必须先修

### P0-A：截图文件被OCR读到截断状态

run=`monitor-eceec6274ab2`在05:23:50成功提交`开学第一课PPT`，尚未点击商品。05:24:09读取搜索结果截图时失败：

```text
OcrWorkerError: RapidOCR worker failed: OSError: image file is truncated
```

精确证据：

```text
data/probes/monitor-eceec6274ab2-probe-search-results/.ocr-diagnostics/ocr-worker-error-20260817T122409.320827Z-3e5a9134c962-9ba9a7399fec.json
```

诊断记录显示：`current.png`大小738422字节，worker停在`image_load_failed`，PIL报告PNG尾部缺失。优先怀疑截图直接写最终文件、并发或文件完成性未校验。只为此故障读取：

- `src/xhs_scout/emulator.py:242`附近的`AdbDevice.screenshot`
- `src/xhs_scout/probe.py:241`附近的`probe_current_page`
- `src/xhs_scout/ocr.py`中的`OcrWorkerError`、worker image load和父进程监督逻辑
- `tests/test_ocr_timeout.py`
- `tests/test_ocr_timeout_collection.py`
- `tests/test_ocr_timeout_strict_contract.py`

推荐修复方向：截图先写同目录唯一临时文件，ADB进程成功退出后验证PNG可完整解码/verify，再用`os.replace`原子替换最终`current.png`；OCR只读已原子完成的文件。对一次性截图截断可做有上限的重新截图，但不能吞掉持续基础设施故障。`OcrWorkerError`也必须进入明确的基础设施失败/任务退回契约，不能只落成意外异常并悄悄消耗task attempt。先写能复现“OCR读取到半写PNG”的失败测试，再修。

### P0-B：无线ADB不能稳定重连和选中唯一手机

首轮OCR异常后，scheduler自动重试run=`monitor-65be63bd61e5`，05:25:31因`device_selection`失败安全暂停。此前同一手机曾同时出现：

```text
192.168.1.119:39325                              offline
adb-741da30b0920-cvuER5._adb-tls-connect._tcp   device
```

之后ADB列表完全为空。只为此故障读取：

- `src/xhs_scout/monitor.py:445-471`的`_device`
- `src/xhs_scout/emulator.py:297-339`的设备和mDNS选择
- `src/xhs_scout/device_preflight.py:180`附近
- `tests/test_device_preflight.py`
- `tests/test_android_unicode_input.py`中设备选择相关用例

目标不是永久写死动态IP。优先使用配置中的稳定`mdns_service`发现当前地址，只接受在线且型号/设备身份唯一匹配的M2010J19SC/lime；忽略同一物理手机的旧offline IP记录。mDNS消失时fail closed并向用户要最新地址，不扫描端口、不任选设备。

### P0-C：rank4/5滚动分支存在未触发的真实调用错误

`src/xhs_scout/monitor.py`中的`_locate_ranked_product_card`目前在滚动分支写成：

```python
probe_current_page(settings, label=...)
```

真实签名是：

```python
probe_current_page(settings, device, run_id=...)
```

因此rank4/5需要滚动时会直接报错。此前`tests/test_monitor_search.py`使用宽松monkeypatch，没有校验真实调用签名。修正调用并补一个严格测试，确保传入同一个device且使用`run_id`。同时保留现有规则：最多滚动2次、合并去重、找不到精确rank就停止，绝不取模回绕。

## 五、已完成但尚未充分真实验收的工程能力

- 商品详情两种标题布局的几何分型和固定ROI已经实现并加载。真实回放obs63/68分别能得到完整标题和价格98.9/12.9；但product68数据库里仍保留修复前的错误标题，不能把回放成功说成历史数据已回填。
- 每词5件调度已经实现：`ContinuousMonitorScheduler.discovery_card_slots=5`，同一词完成rank5后才移动cursor；rank5失败时不换词。
- 旧的rank取模回绕已删除；可见卡不足时新增滚动合并逻辑，但受P0-C影响，rank4/5尚未真实可用。
- 修改后最后完整测试基线为`920 passed, 4 skipped`。这个数字只证明当时离线测试，不证明当前真实运行。
- 自动启动代码已经离线实现：`ops/autorun/`、`ops/install_scheduled_task.ps1`、`ops/uninstall_scheduled_task.ps1`，对应定向测试曾15 passed；但真实Windows计划任务没有安装，也没有完成断电/重启后的真实验收。

仅在相关故障修完后，按需读取：

- `src/xhs_scout/continuous_discovery.py`（文件较小，可全读）
- `src/xhs_scout/scheduler.py:530-630`
- `src/xhs_scout/monitor.py:259-354`
- `src/xhs_scout/layout_fields.py:196-420`
- `tests/test_continuous_discovery.py`
- `tests/test_monitor_search.py`
- `tests/test_layout_fields.py`

## 六、安全边界和操作纪律

1. 真实手机、生产数据库、8793服务和scheduler只能由你这个总控串行操作，不交给子任务。
2. 永远不碰8765。
3. 生产库是`data/xhs_scout.sqlite3`。任何生产写入、修复历史记录、重载前都先用SQLite backup API生成独立备份并验证quick_check；不要用文件复制正在使用的SQLite。
4. 日常resume不要重复跑完整回归、全库校验和大段OCR探测。普通恢复只检查：8793健康且无risk、唯一正确手机在线、无running task/lease。完整测试只在代码修改后统一跑一次。
5. 登录、验证码、风控、安全验证、未知身份页面、数据库锁、无法唯一选择设备必须停止。明确ANR可以按既有规则关闭并重开小红书，回到安全页后继续；不能绕过账号验证。
6. 不要创建第二个monitor-loop；只使用8793内置scheduler。
7. 重载服务只用`ops/stop_workbench.ps1`和`ops/start_workbench.ps1`，必须先验证8793进程属于本项目；重载后保持paused，真机短轮前不要自动resume。
8. 不要为了展示进度反复重跑失败操作。每个P0先有复现测试、最小修复、定向测试，三个P0稳定后只跑一次完整`pytest -q tests`。

## 七、接手后的执行顺序

### 阶段1：最小只读基线

只做以下几项并向用户用一句话汇报：

- `GET http://127.0.0.1:8793/api/monitor/status`
- `adb devices -l`
- 只读查询task183、running task、run lease和`开学第一课PPT`的evidence
- 确认8793/8765监听PID

如果和本提示词一致，不要继续扩大检查。

### 阶段2：修复三个P0

顺序建议：P0-C滚动调用错误（小且确定）→P0-A截图原子性与OCR错误契约→P0-B稳定mDNS重连。每项只读必要源码和对应测试，不通读项目。

### 阶段3：离线验收和部署

- 跑三个模块定向测试。
- 稳定后只跑一次完整`pytest -q tests`。
- 备份生产DB。
- 只重载8793，确认HTTP正常、desired仍paused、scheduler false；记录8765 PID未变。

### 阶段4：唯一一次受控真机短轮

- 手机在线后，先只执行task183/expected_keyword=`开学第一课PPT`/rank2。
- 必须看到真实商品点击、product detail、标题/价格固定ROI、店铺/粉丝、链接、有效task result和search_result_evidence。
- 如果rank2成功，再让同词依次跑rank3、rank4、rank5，验证滚动与不重复；只有rank5成功后才允许切换下一个关键词。
- 任一步失败立即暂停并用具体证据修，不要向用户说“24小时已开启”。

### 阶段5：真正开启长期运行

- 首词5件完整成功、页面恢复、无risk/block、任务和lease干净后，才恢复连续scheduler。
- “24小时窗口起点”以恢复后第一个有效商品成功完成时间为准，不以点击resume或线程starting为准。
- 记录运行起点、成功/失败数、当前关键词/rank、停止原因。真实满24小时后才能说24小时验收完成。
- 本地自动启动代码验收完成后，如需真实注册Windows计划任务，先向用户展示任务名、触发时机、运行脚本、是否恢复scheduler和卸载方式，取得一次明确确认再安装。安装后验证重启/服务退出恢复，确保日常运行不依赖Claude对话框。

## 八、完成口径

项目不能以“代码很多、测试很多、线程显示running”宣告完成。最低完成口径是：

1. 一个真实关键词连续采到5个不同商品，rank证据1–5齐全，标题/价格/店铺/粉丝/链接可核验。
2. rank5后自动切换到下一个确认关键词；rank4/5滚动真实通过。
3. 截图不会再被OCR读取为半写文件；设备IP变化时能通过稳定mDNS恢复，找不到时安全暂停。
4. 8793服务和scheduler可由Windows本地机制按明确策略恢复，不依赖对话窗口。
5. 完整24小时真实窗口跑完，期间所有停止和恢复有证据，用户在工作台能看到真实进度。

你的第一次回复不要承诺已经修好。请先用最小文件读取和四项只读基线，向用户报告：你理解的最终目标、当前确切阻塞、准备先修的三个P0、你不会触碰的边界，然后直接开始处理；除非需要新的IP、验证码/登录或真实Windows计划任务安装授权，不要把普通技术判断继续丢给用户。
