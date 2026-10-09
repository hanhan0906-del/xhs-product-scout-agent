# 小红书选品 Agent

> 本机运行的小红书虚拟商品选品工作台：通过安卓虚拟机低频采集公开商品与笔记证据，OCR 识别后评分并生成选品报告。

| 项目状态 | 技术栈 |
| --- | --- |
| 🚧 开发中（可人工值守试运行，未完成 24 小时连续验证） | Python、FastAPI、RapidOCR、安卓模拟器 |

> 本项目为个人 AI 辅助开发（vibe coding）作品。仓库只包含源码与文档，运行数据、账号配置、密钥均已排除；文中出现的本机路径仅供参考，使用时请按自己的环境修改。

---

这是一个运行在本机的小红书虚拟商品选品工作台。它通过安卓虚拟机中的正常可见页面，以低频、受控方式采集商品、公开笔记和公开账号证据，并把截图、OCR 结果、趋势指标、候选评分和分析报告保存在本地。

当前项目适合人工值守下的单轮采集，以及每小时 1 个关键词、每个关键词 1 个商品的保守试运行。代码已经提供调度、质量审计、日/周摘要和关键词组合轮转入口，但尚未完成 24 小时连续运行验证，也不具备全站穷举能力。

## 当前能力

- 从用户确认的 100 个发现型根词开始搜索，并从真实商品标题和证据中持续沉淀更具体的关键词；
- 在公开商品页面采集标题、店铺、价格、累计销量及页面展示的趋势下限；
- 识别 24 小时、近 7 天和近 30 天的购买、加购、好评、收藏、感兴趣等信号；
- 区分“近 30 天新增好评”和“近 30 天购买/新增销量”，避免混淆口径；
- 保存商品证据截图、搜索来源关键词、结果位次和探测目录；
- 对候选商品评分并生成包含证据、风险、缺口和原创化方向的报告；
- 从商品详情页的公开分享入口尝试复制真实商品链接并回填；
- 采集公开相关笔记、单条笔记互动、发布时间和作者公开主页数据；
- 在工作台查看候选、运行状态、质量问题、近 24 小时摘要和关键词轮转计划；
- 导出候选商品 CSV。

真实商品链接采集依赖小红书当前 UI 和 Windows 剪贴板，仍需继续实测其稳定性。公开笔记和作者主页证据只有在页面存在且链路安全时才采集。

## 工作台入口

工作台地址：

```text
http://127.0.0.1:8793/
```

项目固定使用本机 `8793` 端口。`8765` 属于其他 Agent，本项目的运维脚本不会操作它。

可双击项目根目录的 `启动工作台.cmd`，也可以使用保守运维脚本：

```powershell
cd "C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent"

# 预览启动动作，不改变状态
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\start_workbench.ps1

# 确认后启动工作台
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\start_workbench.ps1 -Execute -OpenBrowser

# 只读健康检查
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\health_check.ps1
```

也可以直接启动：

```powershell
.\.venv\Scripts\python.exe -m xhs_scout.cli serve --host 127.0.0.1 --port 8793 --project-root "C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent"
```

## 默认监控策略

工作台点击“恢复监控”后会启动保守调度器：

- 每小时执行一轮；
- 每轮默认最多处理 1 个关键词；
- 每个关键词默认最多打开 1 个商品；
- 同一关键词默认保留 24 小时复搜冷却；
- 相关笔记和作者主页证据默认不在后台调度中自动开启；
- 风控、验证码、ANR、页面类型异常或搜索归属不匹配时暂停或记录失败原因。

“执行单轮”是人工值守的即时入口，不代表后台长期无人值守。CLI 等价用法：

```powershell
# 人工值守下执行一次：1 个关键词、1 个商品
.\.venv\Scripts\python.exe -m xhs_scout.cli monitor-once --max-keywords 1 --max-products-per-keyword 1 --ignore-paused

# 小时级受控循环；只用于小规模验证
.\.venv\Scripts\python.exe -m xhs_scout.cli monitor-loop --interval-seconds 3600 --max-keywords 1 --max-products-per-keyword 1

# 查看、暂停和恢复监控状态
.\.venv\Scripts\python.exe -m xhs_scout.cli monitor-state
.\.venv\Scripts\python.exe -m xhs_scout.cli monitor-pause
.\.venv\Scripts\python.exe -m xhs_scout.cli monitor-resume
```

不要直接运行全部待处理任务。应先完成连续的小规模真实验证，再决定是否扩大关键词池、每轮预算或运行时长。

## 关键词覆盖口径

项目追求的是安全边界内的高覆盖，不是全站穷举。

当前主来源是 `config\discovery_root_terms.txt` 中用户确认的 100 个发现型根词。每个真实商品都要拆出领域、场景、人群、商品形态、阶段和功能等词元；积累达到门槛后，才生成有真实商品支持的组合候选。候选必须人工批准，才能在预算、去重、轮转、冷却和风险停止约束下有限入队。

旧 `config\seed_keywords.txt` 78 词和 `config\keyword_portfolio.json` 126 个候选只保留审计与兼容用途，不再主导新词库，也不得自动批量入队。完整现行规则见 `coordination\KEYWORD_STRATEGY.md`。

## 候选等级与低粉阈值

- A 级：商品热度证据成立，并形成同一作者的公开笔记与公开主页证据闭环；笔记需为近 7 天，同时满足低粉与单条笔记点赞阈值。
- B 级：商品销量、购买、加购、收藏、感兴趣或新增趋势较强，但低粉作者、单条笔记互动或发布时间尚未闭环。
- C 级：只有弱商品信号或“销量飙升”等提示，需要继续观察。
- D/淘汰：证据归属无效、商品身份不清或明确不符合条件。

当前自动低粉判断的作者粉丝上限为 `<= 2000`：

- 严格小账号规则：粉丝 `< 200`，且近 7 天单条笔记点赞 `>= 100`；
- 标准低粉规则：粉丝 `<= 2000`，且近 7 天单条笔记点赞 `>= 1000`。

系统不会仅凭商品页、作者粉丝数或账号累计获赞/收藏宣称“低粉爆款”。商品趋势、公开笔记、公开主页、作者一致性、发布时间和单条笔记互动均满足后，才允许自动升级为 A 级。

## 真实商品链接与后台证据

两类数据用途不同，不能混为一谈：

- 真实商品链接：采集成功时保存到商品的 `share_url`；工作台候选表中的商品标题会打开该链接。未采集到链接时明确显示“链接待采集”。
- 后台证据截图：继续保存本次观察的页面证据，供质量审计、报告和排错使用；候选表不再显示截图入口。

真实链接用于回到公开商品页面，截图用于审计当次识别依据。后台不会删除历史截图，也不会用截图冒充商品链接。

## 质量、摘要与关键词组合 API

工作台提供以下本地 API：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/api/status` | 工作台计数、候选和汇总状态 |
| `GET` | `/api/monitor/status` | 调度状态、阻塞原因和最近运行事件 |
| `POST` | `/api/monitor/run-once` | 人工触发一个受控单轮 |
| `POST` | `/api/monitor/pause` | 暂停后台监控 |
| `POST` | `/api/monitor/resume` | 恢复并启动小时级调度 |
| `GET` | `/api/quality` | 只读证据质量审计 |
| `GET` | `/api/digest/daily` | 每日摘要 |
| `GET` | `/api/digest/weekly` | 每周摘要 |
| `GET` | `/api/portfolio` | 关键词组合、预算、冷却与下一轮计划 |
| `GET` | `/export/candidates.csv` | 下载候选 CSV |
| `GET` | `/reports/latest` | 打开最近一次候选报告 |

质量审计会提示缺标题、缺真实链接、缺截图、趋势冲突、OCR 污染、搜索归属异常、低粉证据缺口和重复证据；它只读提示，不会自动删除或修正真实数据。

日/周摘要基于本地数据库已经采集的记录，包含新增观察、候选、失败任务、趋势、风险、证据缺口、告警和人工复核项，不代表小红书外部平台的实时全量数据。

## 采集与报告命令

```powershell
# 只读探测当前页面，不点击、不输入
.\.venv\Scripts\python.exe -m xhs_scout.cli probe-current-page

# 采集虚拟机当前画面
.\.venv\Scripts\python.exe -m xhs_scout.cli capture-once

# 将当前商品详情页关联到明确任务
.\.venv\Scripts\python.exe -m xhs_scout.cli capture-task --task-id <任务编号> --metrics-strip --require-keyword-match

# 生成候选报告
.\.venv\Scripts\python.exe -m xhs_scout.cli report-candidates --limit 20
```

只有确认当前页属于指定关键词时，才应执行任务关联命令。遇到页面不匹配、风险提示或无法解释的跳转，应停止并保留证据。

## 安装与测试

需要 Python `>= 3.11, < 3.13`。首次安装：

```powershell
cd "C:\Users\Lenovo\Desktop\Codex Agent合集\小红书选品 Agent"
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

运行完整离线测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

按模块快速核对工作台、调度、质量、摘要、关键词组合和链接逻辑：

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests\test_web.py `
  tests\test_workbench_ui.py `
  tests\test_scheduler.py `
  tests\test_quality.py `
  tests\test_digest.py `
  tests\test_keyword_portfolio.py `
  tests\test_product_link.py `
  tests\test_integrated_workstation.py
```

离线测试使用临时目录和临时数据库；它不能替代真实小红书 UI、ADB、剪贴板、小时级调度或长时间运行验证。

## 合规与安全边界

- 不抓包解密，不调用小红书未公开接口；
- 不使用代理池、多账号、设备伪装或其他方式规避平台限制；
- 不绕过登录、验证码、滑块、系统 UAC 或平台风控；
- 不自动点赞、收藏、评论、关注、加购、购买、联系客服或发布内容；
- 只读取正常用户可见的商品、公开笔记和公开账号页面；
- 登录、验证码和风控提示必须由用户本人处理；
- 本地文件和数据库中不保存密码、Cookie、令牌或验证码；
- 遇到风控、账号异常、危险页面或无法解释的跳转时立即暂停；
- 页面展示的销量和趋势按下限保存，不伪造精确值。

## 当前未完成

- 尚未完成 24 小时连续运行验证；
- 小时级调度仍需在真实小红书页面连续完成多个安全轮次；
- 真实商品链接复制、直播/非标准结果卡过滤、首页搜索恢复和指标条页面守卫仍需持续实测；
- 低粉证据仍需更多近 7 天真实样本；
- 相关笔记与作者主页证据默认未接入后台自动调度；
- 高覆盖关键词轮转仍需逐步扩展和人工复核；
- 不支持、也不计划宣称全站穷举。
