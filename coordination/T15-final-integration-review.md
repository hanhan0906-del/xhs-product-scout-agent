# T15 最终静态集成审计

审计时间：2026-07-28（Asia/Shanghai）

项目根目录：`C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent`

## 审计边界与方法

- 已读取 `C:\Users\Lenovo\AGENTS.md`、项目 `HANDOFF.md`、当前 `src\xhs_scout\*.py`、当前 `tests\test_*.py`，并参考最新协调审查记录核对集成背景。
- 严格只读审查生产代码和测试；没有编辑生产代码、测试或 `HANDOFF.md`。
- 没有启动/停止服务，没有操作模拟器、ADB、小红书或计划任务，没有写入真实数据库。
- 唯一写入是本报告。
- 项目不是 Git 仓库，因此以当前文件树为审计快照。静态 AST 解析覆盖 26 个生产模块、27 个测试文件、134 个测试函数，全部语法可解析。
- 为遵守“唯一允许写入本报告”的边界，本轮没有执行 pytest；不声明当前测试套件通过。最新协调记录 `T14-handoff-final-draft.md` 记载的最近一次结果为 `133 passed, 1 failed`，失败项与 `OPERATIONS.md` 编码/`dry-run` 文档契约有关，该结果不是本轮独立复跑。

## 总结结论

**结论：有条件不通过，存在 2 个 P1 阻断、3 个 P2 风险和 1 个 P3 可靠性问题。**

以下重点项当前已具备明确保护：截图接口限制在证据截图目录；工作台页面不展示运行事件日志；商品链接和证据截图是独立入口；标准低粉阈值统一为 `<= 2000`；调度器默认只使用一种补词来源且有全局/任务租约；手工低粉录入本身不能无公开笔记/主页链路直接升 A；未发现调用小红书未公开接口或自动点赞、收藏、关注、评论、加购、购买、客服、发布的代码。

但在修复两个 P1 前，不应恢复小时级后台调度，也不应把当前版本标记为“风控停止不可绕过”。

## P1 阻断

### P1-1：已知“安全限制 / 设备异常”页面不会进入硬风控停止

位置：

- `src/xhs_scout/signals.py:30-38`
- `src/xhs_scout/signals.py:339-344`
- `src/xhs_scout/monitor.py:94-123`
- `src/xhs_scout/monitor.py:746-759`
- `tests/test_signals.py:153-155`

问题：

`RISK_STOP_MARKERS` 包含“安全验证”“滑块验证”“操作频繁”“账号异常”等，但不包含项目历史上已经真实出现过的“小红书 - 安全限制”“设备异常”等文案。`HANDOFF.md` 明确记录 Android 9 实例曾进入“安全限制 / 设备异常”页。

这类页面会被分为 `unknown`，随后通常只触发软阻塞：监控暂停并写 `last_block_reason`，但不会写 `risk_stop_reason`。工作台的“执行单轮”只检查 `risk_stop_reason`，又以 `ignore_paused=True` 运行，因此用户或本机调用者可以在安全限制页上重复触发尝试。

影响：

- 已知平台安全限制没有进入不可绕过的硬熔断路径。
- 软暂停可被“执行单轮”忽略，可能在风险设备/安全限制页面重复探测或点击。
- 现有测试只覆盖“安全验证”“操作频繁”和普通商品标题中的“验证码”，没有覆盖真实出现过的“安全限制 / 设备异常”反例。

建议：

1. 用组合规则增加“安全限制”“设备异常”“风险插件”“登录异常”等明确安全页识别，避免只匹配泛化“异常”导致误报。
2. `unknown` 页面若同时出现安全/设备限制语义，应直接设置 `risk_stop_reason` 并停止任务。
3. 增加测试：这些页面必须是 `risk_stop`，连续第二轮和 `ignore_paused=True` 均不得打开设备或执行 UI 动作。

### P1-2：恢复接口和 CLI 会无二次确认地清除风险停止并启动调度

位置：

- `src/xhs_scout/db.py:593-598`
- `src/xhs_scout/web.py:202-208`
- `src/xhs_scout/cli.py:296-299`
- `src/xhs_scout/workbench_ui.py:311`
- `src/xhs_scout/workbench_ui.py:580-592`
- `src/xhs_scout/workbench_ui.py:662`
- `tests/test_web.py:77-101`

问题：

`set_monitor_desired_state(conn, "running")` 会直接清空 `risk_stop_reason`。`POST /api/monitor/resume` 没有请求体、确认字段或风险原因回显确认，随后立即启动调度器；CLI `monitor-resume` 也直接走同一清除逻辑。工作台“恢复”按钮没有在存在风险停止时要求用户确认已经检查页面、账号和风控状态。

现有测试只验证 resume 会启动 scheduler，没有覆盖“已有风险停止时 resume 必须拒绝或要求显式确认”。

影响：

- 风险停止可以被一次普通 POST 或 CLI 命令清除。
- “恢复普通暂停”和“解除硬风控”共用同一无参数动作，无法证明操作者明确确认了风险状态。
- 本地接口没有额外的恢复令牌或确认字段，无法在代码层区分有意解除和误触/脚本调用。

建议：

1. 普通 `resume` 在 `risk_stop_reason` 非空时返回 409。
2. 新增独立的风险解除动作，要求提交当前风险原因或一次性确认值，例如 `confirm_risk_reason`，并记录审计事件。
3. UI 在风险停止存在时禁用普通“恢复”，显示原因并要求二次确认；CLI 增加显式 `--confirm-risk`。
4. 增加 web、CLI、scheduler 回归测试，证明普通 resume 无法清除风险停止。

## P2 重要风险

### P2-1：“真实商品链接”没有域名或商品身份校验

位置：

- `src/xhs_scout/product_link.py:11-18`
- `src/xhs_scout/product_link.py:37-59`
- `src/xhs_scout/workflow.py:250-263`
- `src/xhs_scout/workbench_ui.py:397-405`
- `src/xhs_scout/workbench_ui.py:451-469`
- `tests/test_product_link.py:4-12`

问题：

链接采集使用可见“分享商品 -> 复制链接”UI，符合不调用隐藏接口的边界；但 `extract_share_url()` 接受剪贴板中的任意 HTTP(S) URL。写入 `products.share_url` 前没有校验域名属于 `xhslink.com` / `xiaohongshu.com`，也没有校验复制结果确实对应当前商品。工作台只检查 HTTP(S) 协议，就将其标成“真实商品链接”。

影响：

- 剪贴板竞争、错误分享面板或 UI 误命中可能把无关链接写成商品原链接。
- 后续报告、CSV 和工作台会把该 URL 当作商品身份锚点。

建议：

- 至少使用小红书官方域名允许列表，并拒绝凭据型 URL、非 HTTP(S) 和未知域名。
- 保存链接来源、采集时间和当前商品标题/店铺快照；条件允许时解析落地页后再做商品身份复核。
- 增加未知域名、旧剪贴板 URL、非商品链接和复制失败的负向测试。

### P2-2：首页搜索回退会选择任意顶部右侧可点击文本

位置：

- `src/xhs_scout/ui_automation.py:143-161`
- `src/xhs_scout/monitor.py:567-576`
- `tests/test_ui_automation.py:93-103`

问题：

`find_home_search_entry()` 只按“顶部右侧、可点击、非少量忽略词”选择最靠右目标，不要求 `content-desc` 为“搜索”，也不要求文本具有查询/搜索语义。若首页同一区域出现“扫码、签到、直播、分享”等其它入口，函数可能把它当作搜索入口点击。

当前测试只有顶部查询文本的正向样本，没有“顶部右侧存在多个非搜索入口时必须拒绝”的负向样本。

影响：

- 可能进入非搜索页面，扩大互动面和异常跳转概率。
- 后续页面守卫会降低继续操作的风险，但第一次误点击已经发生。

建议：

- 优先只接受明确 `content-desc="搜索"` / “搜索商品”或已经验证的查询框结构。
- 对扫码、直播、签到、分享、发布等入口建立明确拒绝列表。
- 无法证明是搜索入口时停止，不使用“最靠右目标”猜测。

### P2-3：A 级与摘要闭环没有强制要求可回看的证据文件

位置：

- `src/xhs_scout/low_follower.py:59-90`
- `src/xhs_scout/low_follower.py:95-149`
- `src/xhs_scout/digest.py:577-621`
- `tests/test_low_follower.py:47-112`
- `tests/test_integrated_workstation.py:215-250`

问题：

手工工作台录入路径是安全的：它只写 `note_evidence`，若没有规范化公开笔记/主页观察，会保持 B / `needs_review`，现有集成测试覆盖了这一点。

但自动升 A 的 `promote_candidate_from_note_observations()` 只校验规范化数据行、作者一致、发布时间和数值阈值，不要求 `probe_dir` / `screenshot_path` 非空、存在且位于证据目录。现有单元测试使用 `screenshot_path=None` 和并不存在的字符串 `note-probe` / `profile-probe`，仍成功升 A。

同时，`digest._strict_low_follower_complete()` 不要求证据目录存在；作者名缺一侧时也不会返回 false，因此摘要可能写“已具备闭环”，即使证据目录/作者身份仍有缺口。

影响：

- 正常 UI 采集路径通常会生成 probe，但数据库导入、历史修复或异常写入可能形成“有结构化数值、无可回看证据”的 A 级。
- 摘要闭环口径比真正可审计的证据闭环更宽，可能误导人工验收。

建议：

- 升 A 时强制要求笔记和主页证据目录/截图存在、位于 `data` 证据根目录，且页面类型和作者一致。
- 摘要直接复用同一个严格证据判定函数，不复制简化规则。
- 增加缺证据路径、路径不存在、作者缺一侧、路径越界的负向测试。

## P3 次要可靠性问题

### P3-1：低粉升级仍直接解析 `reasons_json`，坏数据会中断升级接口

位置：

- `src/xhs_scout/low_follower.py:133-149`
- `src/xhs_scout/web.py:53-59`

问题：

工作台和报告已经使用 `_safe_json_list()` 容错，但低粉升级函数仍直接执行 `json.loads(latest["reasons_json"] or "[]")`。一条历史坏数据可使公开证据升级或手工复核接口返回 500。

建议：

- 复用统一的安全 JSON 列表解析函数。
- 增加非 JSON、JSON 对象和空值测试。

## 已通过的重点检查

### 截图路径越界

- `web.py:346-355` 对数据库截图路径执行 `resolve()`，只允许 `settings.capture_dir` 的真实子文件。
- `reports/latest` 同样限制在 `settings.reports_dir`。
- `test_web.py:105-131`、`test_workstation_contract.py:268-277` 覆盖项目外路径返回 404。
- 当前未发现截图接口读取项目外文件的路径。

### UI 不显示运行日志

- 工作台首页由 `render_workbench_html()` 提供。
- 页面不引用 `/api/run-events`、`recent_run_events`，也没有运行日志表格；只显示心跳、风险停止、最近阻塞和最近跳过等状态摘要。
- `test_workbench_ui.py:44-49`、`test_workstation_contract.py:224-238` 有明确回归断言。
- `/api/run-events` 和 `/api/monitor/status` 仍保留结构化事件接口，但当前 UI 不展示事件列表。

### 商品链接与截图分离

- 工作台商品标题使用 `share_url`；证据截图使用独立 `/captures/{observation_id}`。
- DOM 使用 `textContent` 构造行，不使用 `innerHTML` 注入候选数据。
- 当前问题是链接真实性校验不足，见 P2-1，不是截图冒充链接。

### 低粉阈值 `<= 2000`

- `low_follower.py` 的标准低粉为 `follower_count <= 2000 and likes >= 1000`。
- `digest.py` 和 `quality.py` 的数值阈值已经对齐。
- `test_low_follower.py:20-44` 覆盖 2000 通过、2001 拒绝。

### 调度器不会明显双重投放

- `monitor_once()` 先获取全局监控租约；已有轮次时返回 busy，不打开设备。
- 任务通过原子条件 UPDATE 获取任务级租约，同一任务不会同时被两个 owner 预留。
- scheduler 默认 `requeue_due_keywords=False`，由 `ensure_portfolio_queue()` 统一补一个组合词，避免同轮再做历史复搜补词。
- `test_run_control.py`、`test_monitor_control.py`、`test_scheduler_portfolio.py`、`test_soak_readiness.py` 覆盖全局租约、任务租约、退避、耗尽、单轮预算和重复补词。
- 残余风险：单任务超过 15 分钟租约且长时间没有心跳时，理论上仍可能被接管；当前正常单轮预算下概率较低。

### 手工低粉不会直接无证据升 A

- `POST /api/verify-low-follower/{product_id}` 的手工输入只作为复核记录。
- 自动升 A 读取 `note_observations` 的公开笔记和主页链路，不读取手工 `note_evidence` 作为替代。
- 没有规范化公开链路时结果保持 B / `needs_review`。
- 可回看证据文件未强制存在的问题另见 P2-3。

### 隐藏接口与互动动作边界

- 当前生产代码未导入网络抓包、代理、HTTP 客户端或小红书私有接口调用库。
- 平台操作来自 ADB 可见 UI、截图、OCR、UI 树、Back、搜索输入、商品卡、公开笔记/主页和“分享商品 -> 复制链接”。
- 危险文本已覆盖加购、购买、购物车、客服、橱窗、佣金、收藏/心愿单；相关笔记和作者入口有专门区域限制。
- 未发现自动点赞、收藏、关注、评论、加购、购买、客服或发布动作。
- 首页搜索回退的目标约束仍需加强，见 P2-2。

## 测试与残余风险

- 本轮只做静态解析和代码/测试契约对照，没有运行测试。
- 当前 134 个测试函数对租约、重试、调度、风险停止、截图边界、低粉阈值、手工复核、工作台日志隐藏和真实链接分栏有覆盖，但缺少本报告 P1/P2 的关键负向样本。
- 真实商品链接复制、首页搜索回退、直播/非标准卡、指标条导航守卫、公开笔记/主页 Back 恢复仍需要后续受控真实 UI 验证；静态测试不能替代。
- 没有 24 小时 soak 证据；即使本报告问题修复，也应先做 3 至 5 个单关键词小轮次，再进入小时级试运行。
- scheduler 的 `stop()` 通过 wake 唤醒线程，但没有独立 stop flag；当 `desired_state` 仍为 running 时，应用生命周期退出可能等待超时后仍留下 daemon 线程直到进程结束。全局租约降低双投放风险，但建议后续增加显式停止标志。
- 本地工作台状态变更接口没有认证/恢复令牌；当前默认绑定 `127.0.0.1` 是重要安全前提，不应监听到局域网或公网。

## 修复优先级

1. 修复 P1-1：补齐真实安全限制文案并让它们进入硬风控停止。
2. 修复 P1-2：把普通恢复和风险解除拆成两个显式动作，并增加确认与审计。
3. 修复 P2-1 / P2-2：链接真实性验证、首页搜索目标白名单。
4. 修复 P2-3：A 级和摘要闭环要求可回看的证据文件。
5. 补齐负向测试，使用不写字节码和不写 pytest cache 的方式由主集成任务统一复跑全量测试。
6. 全绿后再做最多 3 至 5 组真实受控小轮次；没有连续稳定证据前，不恢复小时级后台调度。
