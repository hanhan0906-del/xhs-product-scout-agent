from xhs_scout.workbench_ui import render_workbench_html


def test_render_workbench_html_exposes_required_sections_and_api_routes():
    html = render_workbench_html()

    assert "<!doctype html>" in html
    assert "监控概览" in html
    assert "监控任务" in html
    assert "已采集商品" in html
    assert "导出正式候选 CSV" in html
    assert '<button class="nav-item" type="button" data-view="reports">' not in html
    assert 'data-view-panel="reports" hidden aria-hidden="true"' in html
    assert "关键词池" in html
    assert "/api/status" in html
    assert "/api/monitor/pause" in html
    assert "/api/monitor/resume" in html
    assert "/api/monitor/run-once" in html
    assert "/api/products/" in html
    assert "/api/verify-low-follower/" not in html
    assert "/export/candidates.csv" in html
    assert "搜索关键词" in html
    assert "证据截图" not in html


def test_render_workbench_html_uses_existing_status_fields():
    html = render_workbench_html()

    for field in [
        "pending_tasks",
        "products",
        "observations",
        "followed_products",
        "candidates",
        "recent",
        "share_url",
        "direct_url",
        "evidence_grade",
        "sales_30d_min",
        "positive_reviews_30d_min",
        "candidate_qualified",
        "qualification_reasons",
        "collection_status",
        "qualified_candidates",
        "seller_follower_count",
        "seller_follower_display_status",
        "last_report_path",
    ]:
        assert field in html
    assert "item.note_likes" not in html
    assert "item.note_published_days_ago" not in html

    assert "search_result_rank" not in html


def test_render_workbench_html_uses_distinct_computer_and_phone_link_states():
    html = render_workbench_html()

    assert "function safeProductDirectUrl(value)" in html
    assert "function safeProductShareUrl(value)" in html
    assert 'url.protocol !== "xhsdiscover:"' in html
    assert 'url.protocol !== "https:"' in html
    assert 'host !== "xiaohongshu.com"' in html
    assert 'host === "xhslink.com"' in html
    assert "const directUrl = safeProductDirectUrl(item.direct_url);" in html
    assert "const shareUrl = safeProductShareUrl(item.share_url);" in html
    assert 'const title = document.createElement("span");' in html
    product_script = html[
        html.index("function makeProduct(item)"):
        html.index("function makeCommercial(item)")
    ]
    assert "title.href" not in product_script
    assert 'document.createElement(shareUrl ? "a" : "button")' in html
    assert 'shareUrl ? "电脑打开" : "暂无电脑链接"' in html
    assert 'directUrl ? "手机打开" : "暂无手机链接"' in html
    assert "col.actions { width: 120px; }" in html
    assert "flex-direction: column;" in html
    assert "align-items: flex-start;" in html
    assert "white-space: nowrap;" in html
    assert "text-align: left;" in html
    assert "打开主链接" not in html
    assert "打开分享短链" not in html
    assert "computerOpen.href = shareUrl;" in html
    assert "computerOpen.href = directUrl;" not in html
    assert "phoneOpen.href" not in html
    assert "phoneOpen.disabled = !directUrl;" in html
    assert "openProductOnDevice(item, phoneOpen)" in html
    assert "/open-on-device" in html
    assert '{ method: ["P", "O", "S", "T"].join("") }' in html
    assert "body: JSON.stringify" not in html[
        html.index("async function openProductOnDevice"):
        html.index("async function toggleSalesFollow")
    ]


def test_render_workbench_html_keeps_events_out_of_the_page():
    html = render_workbench_html()

    assert "/api/run-events" not in html
    assert "recent_run_events" not in html
    assert "运行事件日志" not in html


def test_render_workbench_html_builds_rows_with_dom_text_nodes():
    html = render_workbench_html()

    assert "document.createElement" in html
    assert "textContent" in html
    assert "safeHttpUrl" in html
    assert "innerHTML" not in html


def test_render_workbench_html_has_desktop_and_mobile_layout_rules():
    html = render_workbench_html()

    assert "grid-template-columns: 214px minmax(0, 1fr)" in html
    assert "@media (max-width: 1180px)" in html
    assert "@media (max-width: 860px)" in html
    assert "@media (max-width: 720px)" in html
    assert "overflow: auto" in html
    assert "content: attr(data-label)" in html
    assert 'class="app-shell"' in html


def test_render_workbench_html_has_candidate_filters_and_views():
    html = render_workbench_html()

    for identifier in [
        'id="candidateSearch"',
        'id="gradeFilter"',
        'id="lowFollowerOnly"',
        'id="trendOnly"',
        'id="qualifiedOnly"',
        'id="sortBy"',
    ]:
        assert identifier in html

    assert "applyCandidateFilters" in html
    assert "switchView" in html
    assert 'data-view="candidates"' in html
    assert 'data-view="monitor"' in html
    assert 'data-view="reports"' not in html
    assert 'data-view="keywords"' in html
    assert "商品销量" in html
    assert "24小时新增销量" in html
    assert "item.seller_follower_count" in html
    assert "持续关注" in html
    assert "已关注" in html
    assert "toggleSalesFollow" in html
    assert "item.sales_followed" in html
    assert '<option value="observed_desc">采集时间从近到远</option>' in html
    assert '<option value="observed_asc">采集时间从远到近</option>' in html
    assert 'observed_desc: (a, b) => compareObservedAt(a, b, "desc")' in html
    assert 'observed_asc: (a, b) => compareObservedAt(a, b, "asc")' in html
    assert 'Date.parse(a?.observed_at || "")' in html


def test_render_workbench_html_shows_all_gray_metrics_with_minimum_marker():
    html = render_workbench_html()

    for label in [
        "近30天购买",
        "近30天好评",
        "近30天收藏",
        "近7天感兴趣",
    ]:
        assert label in html

    assert "item.favorites_30d_min" in html
    assert "item.interested_7d_min" in html
    assert "minimumMetricText" in html
    assert "number > 0 ? `${compact}+` : compact" in html
    assert "<th>候选依据</th>" not in html
    assert 'appendCell(row, makeEvidence(item), "候选依据")' not in html


def test_render_workbench_html_uses_operator_friendly_candidate_layout():
    html = render_workbench_html()

    assert "\n    .commercial {" in html
    commercial_start = html.index("\n    .commercial {")
    commercial_end = html.index("}", commercial_start)
    assert "justify-items: start" in html[commercial_start:commercial_end]
    assert '<col class="grade"><col class="product"><col class="price">' in html
    assert "col.commercial" not in html

    assert ".metric-stack.metrics-grid {" in html
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in html
    assert '], "metrics-grid"), "数据指标");' in html

    assert "<th>粉丝数</th>" in html
    assert "<th>低粉证据</th>" not in html
    assert "function makeFollowerCount(item)" in html
    assert 'item.seller_follower_display_status === "not_displayed"' in html
    assert '"页面未显示"' in html
    assert "followers > 0 && followers <= 2000" in html
    assert 'badge.textContent = "低粉店铺"' in html
    for removed_label in ["核心低粉", "临界低粉", "超过 2000", "粉丝待补"]:
        assert removed_label not in html


def test_render_workbench_html_lists_all_products_and_explains_qualification():
    html = render_workbench_html()

    assert "candidateItems = Array.isArray(data.recent) ? data.recent : [];" in html
    assert ".filter((item) => numericValue(item.gray_metric_count, 0) >= 3)" not in html
    assert '$("navCandidateCount").textContent = valueText(data.products);' in html
    assert 'if (qualifiedOnly && !item.candidate_qualified) return false;' in html
    assert "完整采集" in html
    assert "部分写入" in html
    assert "正式候选" in html
    assert "未入选" in html


def test_render_workbench_html_keeps_monitor_safety_details_internal():
    html = render_workbench_html()

    assert "<h3>安全状态</h3>" not in html
    for internal_id in [
        'id="lastHeartbeat"',
        'id="riskStopReason"',
        'id="lastBlockReason"',
        'id="lastSkipReason"',
        'id="nextRunAt"',
    ]:
        assert internal_id not in html

    assert 'class="detail-grid monitor-controls"' in html
    assert ".detail-grid.monitor-controls { grid-template-columns: minmax(0, 1fr); }" in html


def test_render_workbench_html_makes_monitor_counts_drillable():
    html = render_workbench_html()

    for kind in ("tasks", "products", "observations", "followed", "candidates"):
        assert f'data-monitor-kind="{kind}"' in html
    assert 'id="monitorDrilldown"' in html
    assert 'id="monitorRecordList"' in html
    assert 'id="monitorRecordDetail"' in html
    assert "/api/monitor/details/" in html
    assert "点击左侧任意一条查看详情" in html
    assert 'setMonitorChip($("headerMonitorState"), stateText, stateMode)' in html
    assert 'showToast("当前没有需要解除的风险停止")' in html


def test_render_workbench_html_removes_manual_low_follower_review_flow():
    html = render_workbench_html()

    for removed_text in [
        'id="verifyModal"',
        'id="verifyForm"',
        'id="verifyFollowers"',
        "低粉账号人工复核",
        "保存复核",
        'verify.textContent = "复核"',
        "openVerifyModal",
        "verifyLowFollower",
        "/api/verify-low-follower/",
    ]:
        assert removed_text not in html
    assert 'analysis.textContent = "分析"' in html
    assert 'shareUrl ? "电脑打开" : "暂无电脑链接"' in html
    assert 'directUrl ? "手机打开" : "暂无手机链接"' in html
    assert 'follow.textContent = isFollowing ? "已关注" : "持续关注"' in html
    assert "window.prompt" not in html


def test_render_workbench_html_has_classified_keyword_pool():
    html = render_workbench_html()

    assert "/api/keyword-pool" in html
    assert 'aria-labelledby="classifiedKeywordPoolTitle"' in html
    assert "从已采集商品标题中拆解，并按用途分类保存。" in html
    for label in ["关键词总数", "人群词", "功效词", "场景词", "品类词", "形式词"]:
        assert label in html
    assert 'id="keywordPoolGrid"' in html
    assert 'id="keywordSourceProducts"' in html
    assert "function renderKeywordPool(data)" in html
    assert "async function refreshKeywordPool()" in html
    assert "fetch(API_ROUTES.keywordPool)" in html


def test_render_workbench_html_keeps_keyword_review_evidence_internal():
    html = render_workbench_html()

    assert "renderKeywordSuggestions" in html
    assert "refreshKeywordSuggestions" in html
    render_start = html.index("function renderKeywordSuggestions")
    render_end = html.index("async function refreshKeywordSuggestions", render_start)
    render_script = html[render_start:render_end]
    for internal_field in [
        "risk_flags",
        "support.score",
        "support.evidence_count",
        "support.distinct_products",
        "support.distinct_source_types",
        "source_products",
        "source_keywords",
    ]:
        assert internal_field not in render_script
    assert "document.createElement" in html
    assert "innerHTML" not in html


def test_render_workbench_html_keeps_keyword_review_responsive():
    html = render_workbench_html()

    assert ".suggestion-item {" in html
    assert "grid-template-columns: 1fr" in html
    assert ".suggestion-item { grid-template-columns: 1fr; }" in html
    assert "overflow-wrap: anywhere" in html


def test_render_workbench_html_has_read_only_remediation_plan():
    html = render_workbench_html()

    assert 'aria-labelledby="remediationPlanTitle"' in html
    assert "/api/remediation-plan" in html
    assert "只读补证计划" in html
    assert "仅展示计划，不执行、不审批、不写队列" in html
    assert "production_queue_write === false" in html
    assert "collection_trigger === false" in html
    assert "approval_write === false" in html
    assert "execution_endpoint === false" in html
    assert "human_review_required === true" in html

    panel_start = html.index('aria-labelledby="remediationPlanTitle"')
    panel_end = html.index("</section>", panel_start)
    plan_panel = html[panel_start:panel_end]
    assert "<button" not in plan_panel
    assert "<form" not in plan_panel


def test_render_workbench_html_exposes_remediation_contract_and_states():
    html = render_workbench_html()

    for field in [
        "earliest_executable_stage",
        "next_batch",
        "batches",
        "batch_id",
        "hour_window",
        "max_items",
        "isolated",
        "skipped",
        "blocking_dependencies",
        "blocked_by",
        "retry_at",
        "per_batch_limit",
        "hourly_visit_limit",
        "product_cooldown_hours",
        "planned_product_visits",
        "next_batch_items",
    ]:
        assert field in html

    assert "renderRemediationPlan" in html
    assert "refreshRemediationPlan" in html
    assert "当前没有待执行的补证批次" in html
    assert "补证计划当前不可用" in html
    assert "读取补证计划失败" in html
    assert "document.createElement" in html
    assert "innerHTML" not in html


def test_render_workbench_html_keeps_t29_keyword_review_contract():
    html = render_workbench_html()

    assert "/api/keyword-suggestions" in html
    assert "renderKeywordSuggestions" in html
    assert "refreshKeywordSuggestions" in html
    assert "/api/keyword-pool" in html
    assert "分类关键词" in html
    refresh_start = html.index("async function refresh(includeReadOnlyPlans = false)")
    refresh_end = html.index("function setBusy", refresh_start)
    refresh_script = html[refresh_start:refresh_end]
    assert "refreshKeywordPool()" in refresh_script
    assert "refreshKeywordSuggestions()" not in refresh_script


def test_render_workbench_html_keeps_remediation_plan_responsive():
    html = render_workbench_html()

    assert ".remediation-grid {" in html
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in html
    assert ".remediation-group.dependencies { grid-column: 1 / -1; }" in html
    assert ".remediation-grid { grid-template-columns: 1fr; }" in html
    assert "overflow-wrap: anywhere" in html


def test_render_workbench_html_has_read_only_soak_readiness_panel():
    html = render_workbench_html()

    assert 'aria-labelledby="soakReadinessTitle"' in html
    assert "/api/soak-readiness" in html
    assert "pre-soak 只读准入证据" in html
    assert "仅展示 G0–G6 证据，不是启动按钮或扩容授权" in html
    assert "本工作台不启动 pre-soak、24 小时 soak、监控或扩容" in html
    assert "soak_start_authorized=false" in html
    assert "ready · 证据门槛通过" in html
    assert "insufficient · 尚不具备" in html

    panel_start = html.index('aria-labelledby="soakReadinessTitle"')
    panel_end = html.index("</section>", panel_start)
    readiness_panel = html[panel_start:panel_end]
    assert "<button" not in readiness_panel
    assert "<form" not in readiness_panel


def test_render_workbench_html_exposes_soak_contract_states_and_errors():
    html = render_workbench_html()

    for field in [
        "gates",
        "gaps",
        "warnings",
        "evidence_scope",
        "ready_for_pre_soak",
        "ready_for_24h_soak",
        "soak_start_authorized",
        "authorization",
        "expansion_authorized",
        "database_access",
        "sqlite_mode_ro_query_only",
        "database_write",
        "monitor_trigger",
        "soak_trigger",
        "rounds_read",
        "malformed_json_count",
        "first_evidence_at",
        "last_evidence_at",
    ]:
        assert field in html

    for gate in [f"G{index}" for index in range(7)]:
        assert gate in html

    assert "主要 gaps" in html
    assert "warnings" in html
    assert "证据范围" in html
    assert "当前没有未通过门槛；这仍不代表已授权启动或扩容。" in html
    assert "当前接口未返回 warnings。" in html
    assert "读取 soak 准入证据失败" in html
    assert "renderSoakReadiness" in html
    assert "refreshSoakReadiness" in html
    assert "document.createElement" in html
    assert "innerHTML" not in html


def test_render_workbench_html_keeps_t29_and_t34_when_adding_soak_readiness():
    html = render_workbench_html()

    assert "/api/keyword-suggestions" in html
    assert "/api/keyword-pool" in html
    assert "分类关键词" in html
    assert "/api/remediation-plan" in html
    assert "只读补证计划" in html
    assert "仅展示计划，不执行、不审批、不写队列" in html
    assert "refreshKeywordPool()" in html
    assert "refreshRemediationPlan()" in html
    assert "refreshSoakReadiness()" in html


def test_render_workbench_html_keeps_soak_readiness_responsive():
    html = render_workbench_html()

    assert ".soak-gates {" in html
    assert "grid-template-columns: repeat(4, minmax(0, 1fr))" in html
    assert ".soak-detail-grid {" in html
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in html
    assert ".soak-detail-grid { grid-template-columns: 1fr; }" in html
    assert ".soak-readiness-stats, .soak-gates { grid-template-columns: 1fr; }" in html
    assert "overflow-wrap: anywhere" in html


def test_render_workbench_html_exposes_ack_readiness_without_actions():
    html = render_workbench_html()

    assert 'aria-labelledby="soakAckTitle"' in html
    assert "人工 ACK 完整性" in html
    assert "ack_readiness" in html
    assert "required_alert_ids" in html
    assert "acknowledged_alert_ids" in html
    assert "missing_alert_ids" in html
    assert "unresolved_alert_ids" in html
    assert "latest_decisions" in html
    assert "integrity_error" in html
    assert "evidence_mismatches" in html
    assert "not_required · 无需 ACK" in html
    assert "required · 未 ACK" in html
    assert "ACK 准入尚未核对，不能据此晋级" in html

    panel_start = html.index('aria-labelledby="soakAckTitle"')
    panel_end = html.index("</section>", panel_start)
    ack_panel = html[panel_start:panel_end]
    assert "<button" not in ack_panel
    assert "<form" not in ack_panel


def test_render_workbench_html_exposes_scheduler_evidence_fail_closed_states():
    html = render_workbench_html()

    assert 'aria-labelledby="schedulerEvidenceTitle"' in html
    assert "scheduler evidence · G2 / G4" in html
    for field in [
        "scheduler_evidence",
        "expected_scheduled_at",
        "recorded_scheduled_at",
        "missing_scheduled_at",
        "expected_due_point_count",
        "recorded_due_point_count",
        "missing_due_point_ids",
        "simulated_due_point_count",
        "max_start_delay_seconds",
        "risk_count",
        "blocked_count",
        "t46_ready_for_gate_evaluation",
        "ledger_integrity_ok",
        "integrity_error",
    ]:
        assert field in html

    for state in [
        "expected points",
        "expected scheduled_at",
        "missing",
        "missing scheduled_at",
        "simulated",
        "late",
        "risk",
        "health mismatch",
        "integrity 损坏",
        "不能晋级",
    ]:
        assert state in html

    panel_start = html.index('aria-labelledby="schedulerEvidenceTitle"')
    panel_end = html.index("</section>", panel_start)
    scheduler_panel = html[panel_start:panel_end]
    assert "<button" not in scheduler_panel
    assert "<form" not in scheduler_panel


def test_render_workbench_html_keeps_ack_and_scheduler_compatible_empty_states():
    html = render_workbench_html()

    assert "ackReadinessView" in html
    assert "schedulerEvidenceView" in html
    assert "data?.ack_readiness" in html
    assert "data?.record?.scheduler_evidence" in html
    assert 'key.startsWith("ack_")' in html
    assert 'key.startsWith("scheduler_evidence_")' in html
    assert "未返回 · 兼容空态" in html
    assert "G2/G4 到期点未核对，不能晋级" in html


def test_render_workbench_html_states_ack_and_due_points_are_promotion_gates():
    html = render_workbench_html()

    assert "required 告警未记录或未 ACK、scheduler 到期点未记录或不匹配都不能晋级" in html
    assert "本工作台不启动 pre-soak、24 小时 soak、监控或扩容" in html
    assert "/api/soak-readiness" in html

    panel_start = html.index('aria-labelledby="soakReadinessTitle"')
    panel_end = html.index("</section>", panel_start)
    readiness_panel = html[panel_start:panel_end]
    assert "<button" not in readiness_panel
    assert "<form" not in readiness_panel
    assert 'method: "POST"' not in readiness_panel


def test_render_workbench_html_has_read_only_approval_manifest_panel():
    html = render_workbench_html()

    assert 'aria-labelledby="approvalManifestTitle"' in html
    assert "/api/approval-manifest" in html
    assert "补证审批清单 · 只读复核" in html
    assert "审批清单不等于执行授权" in html
    assert "planned_approved 只表示离线计划通过复核" in html
    assert "不创建清单、不批准、不写队列，也不执行补证" in html
    assert "authorizes_execution=false" in html
    assert "not_executed" in html

    panel_start = html.index('aria-labelledby="approvalManifestTitle"')
    panel_end = html.index('data-view-panel="keywords"', panel_start)
    approval_panel = html[panel_start:panel_end]
    assert "<button" not in approval_panel
    assert "<form" not in approval_panel
    assert 'method: "POST"' not in approval_panel


def test_render_workbench_html_exposes_approval_manifest_contract():
    html = render_workbench_html()

    for field in [
        "manifest_status",
        "review_status",
        "manifest_present",
        "is_current",
        "plan_approval_status",
        "stored_plan_approval_status",
        "execution_status",
        "authorizes_execution",
        "integrity_valid",
        "semantic_valid",
        "planner_hash_matches",
        "source_plan_current",
        "source_plan_hash",
        "source_generated_at",
        "reviewed_at",
        "reviewer",
        "selected_batches",
        "issues",
        "warnings",
    ]:
        assert field in html

    assert "renderApprovalManifest" in html
    assert "refreshApprovalManifest" in html
    assert "document.createElement" in html
    assert "innerHTML" not in html


def test_render_workbench_html_fail_closes_missing_stale_and_bad_manifests():
    html = render_workbench_html()

    for state in [
        "missing · 清单缺失",
        "stale · 清单已过期",
        "invalid · 清单损坏或越界",
        "unavailable · 当前无法校验",
        "清单缺失，不能视为已审批",
        "源计划已变化，旧审批清单过期",
        "清单损坏、篡改或语义越界",
        "当前只读证据不足，无法校验清单",
        "source_plan_current=false · 阻塞",
        "阻塞态",
    ]:
        assert state in html

    assert 'manifest_status: "unavailable"' in html
    assert 'review_status: "pending"' in html
    assert 'plan_approval_status: "pending_review"' in html
    assert 'execution_status: "not_executed"' in html
    assert "authorizes_execution: false" in html
    assert "读取补证审批清单失败" in html


def test_render_workbench_html_shows_budget_isolation_dependencies_and_issues():
    html = render_workbench_html()

    for field in [
        "per_batch_limit",
        "hourly_visit_limit",
        "quarantine_product_ids",
        "low_follower_stop_product_ids",
        "required_before",
        "actions",
        "batch_id",
        "hour_window",
        "product_id",
        "code",
        "path",
        "message",
    ]:
        assert field in html

    assert "批次 / 小时硬预算" in html
    assert "上限 2 / 6" in html
    assert "强制隔离" in html
    assert "低粉停止项" in html
    assert "预算 / 隔离策略" in html
    assert "issues / warnings" in html
    assert "required_before / 依赖" in html
    assert "审批清单不等于执行授权" in html


def test_render_workbench_html_approval_scope_is_strictly_read_only():
    html = render_workbench_html()

    for boundary in [
        'scope.manifest_access === "read_only"',
        "scope.production_queue_write === false",
        "scope.approval_write === false",
        "scope.approval_endpoint === false",
        "scope.execution_endpoint === false",
        "scope.authorizes_execution === false",
        'executionStatus === "not_executed"',
        "data?.authorizes_execution === false",
    ]:
        assert boundary in html

    approval_route = html.index('approvalManifest: "/api/approval-manifest"')
    approval_refresh = html.index("async function refreshApprovalManifest()")
    next_function = html.index("function renderStatus", approval_refresh)
    approval_script = html[approval_route:next_function]
    assert 'method: "POST"' not in approval_script
    assert "fetch(API_ROUTES.approvalManifest)" in approval_script


def test_render_workbench_html_keeps_t29_t34_t40_t50_when_adding_approval():
    html = render_workbench_html()

    assert "/api/keyword-suggestions" in html
    assert "/api/keyword-pool" in html
    assert "分类关键词" in html
    assert "refreshKeywordPool()" in html
    assert "/api/remediation-plan" in html
    assert "只读补证计划" in html
    assert "refreshRemediationPlan()" in html
    assert "/api/soak-readiness" in html
    assert "pre-soak 只读准入证据" in html
    assert "refreshSoakReadiness()" in html
    assert "人工 ACK 完整性" in html
    assert "scheduler evidence · G2 / G4" in html
    assert "refreshApprovalManifest()" in html


def test_render_workbench_html_keeps_approval_manifest_responsive():
    html = render_workbench_html()

    assert ".approval-status-grid {" in html
    assert "grid-template-columns: repeat(6, minmax(0, 1fr))" in html
    assert ".approval-validation-grid {" in html
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in html
    assert ".approval-validation-grid { grid-template-columns: 1fr; }" in html
    assert ".approval-status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }" in html


def test_render_workbench_html_has_read_only_baseline_admission_panel():
    html = render_workbench_html()

    assert 'aria-labelledby="baselineEvidenceTitle"' in html
    assert "pre-soak baseline · 只读准入" in html
    assert "真实 baseline 未生成、清单损坏或文件漂移时，不具备准入" in html
    assert "这里只读取 record.baseline" in html
    assert "不上传、不生成、不编辑、不批准" in html
    assert "authorizes_start=false" in html

    panel_start = html.index('aria-labelledby="baselineEvidenceTitle"')
    panel_end = html.index("</section>", panel_start)
    baseline_panel = html[panel_start:panel_end]
    assert "<button" not in baseline_panel
    assert "<form" not in baseline_panel
    assert "<input" not in baseline_panel
    assert 'method: "POST"' not in baseline_panel


def test_render_workbench_html_exposes_baseline_response_contract():
    html = render_workbench_html()

    for field in [
        "record?.baseline",
        "summary?.baseline",
        "status",
        "source",
        "integrity_ok",
        "baseline_id",
        "manifest_hash",
        "files_reverified",
        "gaps",
        "warnings",
        "pre_soak_start_authorized",
        "soak_24h_start_authorized",
        "scheduler_start_authorized",
        "authorizes_start",
    ]:
        assert field in html

    assert "renderBaselineReadiness" in html
    assert "baselineReadinessView" in html
    assert "baselineReasonFlags" in html
    assert "document.createElement" in html
    assert "innerHTML" not in html


def test_render_workbench_html_fail_closes_baseline_missing_bad_and_drifted_states():
    html = render_workbench_html()

    for state in [
        "missing · 不具备准入",
        "file drift · 不具备准入",
        "invalid · 不具备准入",
        "blocked · 字段不足",
        "字段缺失或未知一律 fail closed",
        "接口未返回 record.baseline；真实 baseline 尚未核对",
        "baseline 字段缺失，工作台按 fail closed 处理",
        "真实 baseline：",
        "清单完整性：",
        "文件复核：",
    ]:
        assert state in html

    for marker in [
        "缺少",
        "missing",
        "not found",
        "清单",
        "manifest",
        "json",
        "hash",
        "损坏",
        "篡改",
        "文件漂移",
        "file drift",
        "changed since baseline",
    ]:
        assert marker in html


def test_render_workbench_html_shows_baseline_hard_requirements_as_gaps():
    html = render_workbench_html()

    for requirement in [
        "owner（8793 / 8765）",
        "stop-entry",
        "DB quick_check=ok",
        "固定 1×1 参数",
        "interval_seconds",
        "未能独立确认，随 baseline 阻塞",
        "baseline gaps / warnings",
        "无 baseline gaps；仍不构成启动授权",
    ]:
        assert requirement in html


def test_render_workbench_html_baseline_is_strictly_fail_closed():
    html = render_workbench_html()

    for condition in [
        'baseline.status === "passed"',
        '["path", "manifest"].includes(baseline.source)',
        "baseline.integrity_ok === true",
        "baseline.files_reverified === true",
        "identifiersPresent",
        "authorizationClosed",
        "baseline.authorizes_start === false",
    ]:
        assert condition in html

    assert "ready_for_pre_soak" not in html[
        html.index("function baselineReadinessView"):
        html.index("function renderBaselineReadiness")
    ]


def test_render_workbench_html_keeps_ack_scheduler_and_approval_with_baseline():
    html = render_workbench_html()

    assert "人工 ACK 完整性" in html
    assert "scheduler evidence · G2 / G4" in html
    assert "补证审批清单 · 只读复核" in html
    assert "renderAckReadiness(data)" in html
    assert "renderSchedulerEvidence(data)" in html
    assert "renderBaselineReadiness(data)" in html
    assert "refreshApprovalManifest()" in html
    assert "refreshSoakReadiness()" in html


def test_render_workbench_html_keeps_baseline_panel_responsive():
    html = render_workbench_html()

    assert ".baseline-evidence {" in html
    assert "grid-column: 1 / -1" in html
    assert ".baseline-overview {" in html
    assert "grid-template-columns: repeat(5, minmax(0, 1fr))" in html
    assert ".baseline-detail-grid {" in html
    assert ".baseline-detail-grid { grid-template-columns: 1fr; }" in html
    assert ".baseline-overview { grid-template-columns: 1fr; }" in html


def test_render_workbench_html_keeps_keyword_approval_manifest_off_user_page():
    html = render_workbench_html()

    assert "/api/keyword-approval-manifest" in html
    assert 'id="keywordApprovalManifestPanel"' not in html
    assert "关键词审批清单 · 只读复核" not in html
    assert "async function refreshKeywordApprovalManifest()" in html


def test_render_workbench_html_exposes_keyword_approval_contract_and_fail_closed_states():
    html = render_workbench_html()

    for field in [
        "manifest_status",
        "review_status",
        "manifest_present",
        "is_current",
        "is_expired",
        "manifest_age_seconds",
        "integrity_valid",
        "semantic_valid",
        "policy_within_bounds",
        "suggestion_set_hash_matches",
        "evidence_hashes_match",
        "layers_match",
        "statuses_valid",
        "counts_match",
        "unknown_candidate_ids",
        "stored_stats",
        "current_stats",
        "entries",
        "warnings",
        "authorization",
    ]:
        assert field in html

    for state in [
        "current · 清单当前有效",
        "missing · 清单缺失",
        "invalid · 坏 JSON、损坏或篡改",
        "out_of_bounds · 清单语义或策略越界",
        "unavailable · 只读证据不可用",
        "expired · 清单已过期",
        "stale · 建议或证据已漂移",
        "建议集合漂移",
        "证据漂移",
        "core / exploration 层级漂移",
        "统计数量漂移",
    ]:
        assert state in html

    assert "renderKeywordApprovalManifest" in html
    assert "refreshKeywordApprovalManifest" in html
    assert "读取关键词审批清单失败" in html
    assert "innerHTML" not in html


def test_render_workbench_html_shows_keyword_approval_layers_counts_and_details():
    html = render_workbench_html()

    for text in [
        "core / exploration",
        "approved",
        "rejected",
        "pending",
        "issues / warnings",
        "人工复核理由",
        "approval_valid",
        "candidate_id",
        "source_summary",
        "evidence_hash",
        "来源商品",
        "来源关键词",
    ]:
        assert text in html

    assert 'item.layer === "core"' in html
    assert '["approved", "rejected", "pending"].includes(item.status)' in html
    assert "storedStats.approved" in html
    assert "storedStats.rejected" in html
    assert "storedStats.pending" in html


def test_render_workbench_html_keyword_approval_authorization_is_strictly_false():
    html = render_workbench_html()

    for boundary in [
        'scope.manifest_access === "read_only"',
        "scope.human_review_only === true",
        "scope.approval_write === false",
        "scope.approval_endpoint === false",
        "scope.writes_queue === false",
        "scope.search_execution === false",
        "scope.monitor_authorization === false",
        "scope.soak_authorization === false",
        "authorization.writes_queue === false",
        "authorization.search_execution === false",
        "authorization.monitor_authorization === false",
        "authorization.soak_authorization === false",
        "authorization.human_confirmation_required === true",
    ]:
        assert boundary in html

    route_start = html.index(
        'keywordApprovalManifest: "/api/keyword-approval-manifest"'
    )
    refresh_start = html.index(
        "async function refreshKeywordApprovalManifest()"
    )
    refresh_end = html.index("function soakGateStatus", refresh_start)
    approval_script = html[route_start:refresh_end]
    assert 'method: "POST"' not in approval_script
    assert "fetch(API_ROUTES.keywordApprovalManifest)" in approval_script


def test_render_workbench_html_keeps_keyword_suggestions_and_read_only_panels():
    html = render_workbench_html()

    assert "/api/keyword-suggestions" in html
    assert "/api/keyword-pool" in html
    assert "分类关键词" in html
    assert "refreshKeywordPool()" in html
    assert "/api/approval-manifest" in html
    assert "补证审批清单 · 只读复核" in html
    assert "refreshApprovalManifest()" in html
    assert "/api/soak-readiness" in html
    assert "pre-soak baseline · 只读准入" in html
    assert "refreshSoakReadiness()" in html
    refresh_start = html.index("async function refresh(includeReadOnlyPlans = false)")
    refresh_end = html.index("function setBusy", refresh_start)
    assert "refreshKeywordApprovalManifest()" not in html[refresh_start:refresh_end]


def test_render_workbench_html_keyword_approval_is_responsive():
    html = render_workbench_html()

    assert ".keyword-approval-status-grid {" in html
    assert "grid-template-columns: repeat(6, minmax(0, 1fr))" in html
    assert ".keyword-approval-detail-grid {" in html
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in html
    assert ".keyword-approval-status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }" in html
    assert ".keyword-approval-detail-grid { grid-template-columns: 1fr; }" in html
