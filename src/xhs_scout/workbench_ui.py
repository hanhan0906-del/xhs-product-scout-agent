from __future__ import annotations


def render_workbench_html() -> str:
    """Render the standalone workbench page for the FastAPI home route."""
    return r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>小红书虚拟商品选品工作台</title>
  <style>
    :root {
      color-scheme: light;
      --app-bg: #f4f6f8;
      --surface: #ffffff;
      --surface-soft: #f8fafb;
      --surface-hover: #f1f5f7;
      --line: #e2e7ec;
      --line-strong: #d2d9e1;
      --text: #18212d;
      --muted: #687486;
      --muted-light: #909aaa;
      --navy: #172235;
      --navy-hover: #243148;
      --brand: #d33b50;
      --brand-soft: #fff1f3;
      --green: #087a55;
      --green-soft: #e9f8f1;
      --amber: #9a6400;
      --amber-soft: #fff5dc;
      --blue: #1c64bd;
      --blue-soft: #eaf3ff;
      --danger: #c82b40;
      --shadow: 0 10px 30px rgba(22, 34, 53, 0.06);
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
    }
    * { box-sizing: border-box; }
    html, body { width: 100%; min-height: 100%; margin: 0; overflow-x: hidden; }
    body { background: var(--app-bg); color: var(--text); font-size: 14px; }
    button, input, select { font: inherit; }
    button, summary, select { cursor: pointer; }
    a { color: var(--blue); text-decoration: none; }
    a:hover { text-decoration: underline; }
    button:focus-visible, input:focus-visible, select:focus-visible, a:focus-visible {
      outline: 2px solid rgba(28, 100, 189, 0.3);
      outline-offset: 2px;
    }
    [hidden] { display: none !important; }

    .app-shell {
      display: grid;
      grid-template-columns: 214px minmax(0, 1fr);
      min-height: 100vh;
    }
    .sidebar {
      position: sticky;
      top: 0;
      z-index: 20;
      display: flex;
      flex-direction: column;
      height: 100vh;
      padding: 20px 14px 16px;
      background: #fbfcfd;
      border-right: 1px solid var(--line);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      min-height: 42px;
      padding: 0 8px;
    }
    .brand-mark {
      display: grid;
      width: 34px;
      height: 34px;
      place-items: center;
      border-radius: 8px;
      background: var(--navy);
      color: #fff;
      font-size: 16px;
      font-weight: 800;
    }
    .brand-copy { min-width: 0; }
    .brand-name { font-size: 16px; font-weight: 780; line-height: 1.25; }
    .brand-version { color: var(--muted); font-size: 11px; line-height: 1.4; }
    .nav {
      display: grid;
      gap: 5px;
      margin-top: 26px;
    }
    .nav-label {
      padding: 0 10px 5px;
      color: var(--muted-light);
      font-size: 11px;
    }
    .nav-item {
      display: grid;
      grid-template-columns: 28px minmax(0, 1fr) auto;
      align-items: center;
      gap: 7px;
      width: 100%;
      min-height: 42px;
      border: 0;
      border-radius: 7px;
      padding: 7px 10px;
      background: transparent;
      color: #566276;
      text-align: left;
    }
    .nav-item:hover { background: var(--surface-hover); color: var(--text); }
    .nav-item.active {
      background: var(--surface);
      box-shadow: 0 1px 5px rgba(22, 34, 53, 0.08);
      color: var(--text);
      font-weight: 680;
    }
    .nav-symbol {
      display: grid;
      width: 24px;
      height: 24px;
      place-items: center;
      border: 1px solid var(--line-strong);
      border-radius: 6px;
      color: #758197;
      font-size: 11px;
      font-weight: 750;
    }
    .nav-item.active .nav-symbol {
      border-color: #c8d1dc;
      background: var(--navy);
      color: #fff;
    }
    .nav-count {
      min-width: 24px;
      border-radius: 6px;
      padding: 2px 5px;
      background: var(--surface-hover);
      color: var(--muted);
      font-size: 11px;
      text-align: center;
    }
    .nav-item.active .nav-count { background: var(--brand-soft); color: var(--brand); }
    .sidebar-footer {
      display: grid;
      gap: 9px;
      margin-top: auto;
      padding: 12px 9px 0;
      border-top: 1px solid var(--line);
    }
    .service-ready {
      display: flex;
      align-items: center;
      gap: 7px;
      color: var(--muted);
      font-size: 12px;
    }
    .service-ready::before {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--green);
      content: "";
    }

    .workspace {
      min-width: 0;
      padding: 18px;
    }
    .workspace-frame {
      display: flex;
      flex-direction: column;
      min-height: calc(100vh - 36px);
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      box-shadow: var(--shadow);
    }
    .workspace-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      min-height: 68px;
      padding: 12px 18px;
      border-bottom: 1px solid var(--line);
    }
    .page-title-row {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }
    .page-title { margin: 0; font-size: 18px; line-height: 1.3; letter-spacing: 0; }
    .page-description {
      margin-top: 2px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }
    .header-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .state-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 28px;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 4px 9px;
      background: var(--surface-soft);
      color: #536075;
      font-size: 12px;
      font-weight: 680;
      white-space: nowrap;
    }
    .state-chip::before {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--muted-light);
      content: "";
    }
    .state-chip.running {
      border-color: #b8e5d1;
      background: var(--green-soft);
      color: var(--green);
    }
    .state-chip.running::before { background: var(--green); }
    .state-chip.paused {
      border-color: #ead8a1;
      background: var(--amber-soft);
      color: var(--amber);
    }
    .state-chip.paused::before { background: #c48300; }
    .state-chip.risk {
      border-color: #efbec6;
      background: var(--brand-soft);
      color: var(--brand);
    }
    .state-chip.risk::before { background: var(--brand); }
    .button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      border: 1px solid transparent;
      border-radius: 6px;
      padding: 7px 11px;
      background: var(--navy);
      color: #fff;
      font-size: 13px;
      font-weight: 650;
      white-space: nowrap;
    }
    .button:hover { background: var(--navy-hover); text-decoration: none; }
    .button.ghost {
      border-color: var(--line);
      background: var(--surface);
      color: #344054;
    }
    .button.ghost:hover { border-color: var(--line-strong); background: var(--surface-hover); }
    .button.secondary { background: #59677a; }
    .button.secondary:hover { background: #46556a; }
    .button.danger { background: var(--danger); }
    .button.danger:hover { background: #ab2235; }
    .button.compact { min-height: 30px; padding: 5px 9px; font-size: 12px; }
    .button:disabled { opacity: 0.5; cursor: not-allowed; }

    .view { min-width: 0; }
    .view.active { display: block; }
    .view:not(.active) { display: none; }
    .candidate-view { display: flex; flex: 1; flex-direction: column; min-height: 0; }
    .candidate-view:not(.active) { display: none; }
    .tool-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: #fcfdfd;
    }
    .tool-group {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      flex-wrap: wrap;
    }
    .search-box {
      width: min(360px, 38vw);
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 7px 11px;
      background: var(--surface-soft);
      color: var(--text);
    }
    .search-box::placeholder { color: var(--muted-light); }
    .filter-select {
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 30px 6px 10px;
      background: var(--surface);
      color: #3d4859;
    }
    .toggle {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 5px 9px;
      background: var(--surface);
      color: #3d4859;
      font-size: 12px;
      white-space: nowrap;
    }
    .toggle input { accent-color: var(--navy); }
    .result-meta {
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }

    .data-table-wrap {
      flex: 1;
      min-height: 0;
      max-width: 100%;
      overflow: auto;
      scrollbar-color: #c4ccd6 transparent;
      scrollbar-width: thin;
    }
    table {
      width: 100%;
      min-width: 1080px;
      border-collapse: separate;
      border-spacing: 0;
      table-layout: fixed;
    }
    col.grade { width: 48px; }
    col.product { width: 220px; }
    col.price { width: 90px; }
    col.source { width: 125px; }
    col.metrics { width: 280px; }
    col.trend { width: 120px; }
    col.followers { width: 100px; }
    col.status { width: 170px; }
    col.actions { width: 120px; }
    th, td {
      padding: 10px 10px;
      border-bottom: 1px solid var(--line);
      background: var(--surface);
      text-align: left;
      vertical-align: middle;
      font-size: 13px;
    }
    th {
      position: sticky;
      top: 0;
      z-index: 3;
      height: 42px;
      background: #f7f9fa;
      color: var(--muted);
      font-size: 12px;
      font-weight: 680;
      white-space: nowrap;
    }
    tbody tr:hover td { background: #f6f9fa; }
    tbody tr.selected td { background: #eef4f7; }
    th:first-child, td:first-child {
      position: sticky;
      left: 0;
      z-index: 2;
    }
    th:nth-child(2), td:nth-child(2) {
      position: sticky;
      left: 48px;
      z-index: 2;
      box-shadow: 1px 0 0 var(--line);
    }
    th:first-child, th:nth-child(2) { z-index: 4; }
    tbody tr:hover td:first-child, tbody tr:hover td:nth-child(2) { background: #f6f9fa; }
    .grade-badge {
      display: inline-grid;
      width: 28px;
      height: 28px;
      place-items: center;
      border-radius: 6px;
      background: var(--blue-soft);
      color: var(--blue);
      font-weight: 800;
    }
    .grade-badge.a { background: var(--green-soft); color: var(--green); }
    .grade-badge.warn { background: var(--amber-soft); color: var(--amber); }
    .product-cell { min-width: 0; }
    .product-title {
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
      overflow: hidden;
      color: #174f99;
      font-weight: 680;
      line-height: 1.45;
    }
    .product-title:hover { color: var(--blue); }
    .product-title.plain { color: var(--text); }
    .product-meta {
      display: flex;
      align-items: center;
      gap: 7px;
      min-width: 0;
      margin-top: 4px;
      color: var(--muted);
      font-size: 11px;
    }
    .product-meta span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .commercial {
      display: grid;
      justify-items: start;
      gap: 3px;
      font-variant-numeric: tabular-nums;
    }
    .commercial strong { color: #243044; font-size: 15px; }
    .commercial span { color: var(--muted); font-size: 11px; }
    .source-cell { display: grid; gap: 5px; min-width: 0; }
    .shop-name, .keyword {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .shop-name { color: #344054; font-weight: 620; }
    .keyword { color: var(--muted); font-size: 11px; }
    .metric-stack { display: grid; gap: 4px; font-variant-numeric: tabular-nums; }
    .metric-row {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 8px;
      min-width: 0;
    }
    .metric-row span {
      overflow: hidden;
      color: var(--muted);
      font-size: 11px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .metric-row strong { color: #304055; font-size: 12px; white-space: nowrap; }
    .metric-row strong.positive { color: var(--green); }
    .metric-row strong.hot { color: var(--brand); }
    .metric-stack.metrics-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      column-gap: 18px;
      row-gap: 7px;
    }
    .metrics-grid .metric-row { gap: 6px; }
    .metrics-grid .metric-row span {
      overflow: visible;
      text-overflow: clip;
      white-space: nowrap;
    }
    .follower-cell {
      display: grid;
      justify-items: start;
      gap: 7px;
      font-variant-numeric: tabular-nums;
    }
    .follower-count {
      color: #243044;
      font-size: 16px;
      font-weight: 720;
    }
    .trend-badge, .follower-band {
      display: inline-flex;
      align-items: center;
      width: fit-content;
      min-height: 23px;
      border-radius: 5px;
      padding: 3px 7px;
      font-size: 11px;
      font-weight: 680;
    }
    .trend-badge { background: var(--amber-soft); color: var(--amber); }
    .trend-badge.quiet { background: var(--surface-hover); color: var(--muted); }
    .follower-band.core { background: var(--green-soft); color: var(--green); }
    .follower-band.near { background: var(--blue-soft); color: var(--blue); }
    .follower-band.missing { background: var(--surface-hover); color: var(--muted); }
    .evidence-text {
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 3;
      overflow: hidden;
      color: #526074;
      font-size: 12px;
      line-height: 1.5;
      overflow-wrap: anywhere;
    }
    .row-actions {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 6px;
      flex-wrap: nowrap;
    }
    .text-action {
      border: 0;
      padding: 3px 0;
      background: transparent;
      color: var(--blue);
      font-size: 12px;
      font-weight: 620;
      text-align: left;
      white-space: nowrap;
    }
    .text-action:hover { text-decoration: underline; }
    .text-action.following {
      padding: 4px 7px;
      border-radius: 999px;
      background: var(--green-soft);
      color: var(--green);
    }
    .text-action.following:hover { text-decoration: none; }
    .empty {
      padding: 42px 20px;
      color: var(--muted);
      text-align: center;
    }
    .error { color: var(--danger); }

    .detail-view { padding: 18px; }
    .section-heading {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 14px;
      padding-bottom: 14px;
      border-bottom: 1px solid var(--line);
    }
    .section-heading h2 { margin: 0; font-size: 16px; letter-spacing: 0; }
    .section-heading p {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }
    .kpi-strip {
      display: grid;
      grid-template-columns: repeat(6, minmax(110px, 1fr));
      margin-top: 14px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--surface);
      overflow: hidden;
    }
    .kpi {
      position: relative;
      padding: 12px 14px;
      min-width: 0;
    }
    button.kpi {
      border: 0;
      border-radius: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      text-align: left;
      cursor: pointer;
    }
    button.kpi:hover { background: var(--surface-hover); }
    button.kpi.active {
      background: #edf4ff;
      box-shadow: inset 0 -2px 0 #4c78b8;
    }
    button.kpi:focus-visible {
      z-index: 1;
      outline: 2px solid #4c78b8;
      outline-offset: -2px;
    }
    .kpi + .kpi::before {
      position: absolute;
      top: 12px;
      bottom: 12px;
      left: 0;
      width: 1px;
      background: var(--line);
      content: "";
    }
    .kpi-label { color: var(--muted); font-size: 11px; }
    .kpi-value {
      margin-top: 4px;
      overflow: hidden;
      color: #263349;
      font-size: 20px;
      font-weight: 780;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .detail-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(320px, 0.7fr);
      gap: 14px;
      margin-top: 14px;
    }
    .detail-grid.monitor-controls { grid-template-columns: minmax(0, 1fr); }
    .monitor-drilldown { margin-top: 14px; }
    .monitor-drilldown-layout {
      display: grid;
      grid-template-columns: minmax(260px, 0.42fr) minmax(0, 0.58fr);
      min-height: 360px;
    }
    .monitor-record-list {
      max-height: 520px;
      overflow: auto;
      border-right: 1px solid var(--line);
    }
    .monitor-record-button {
      display: grid;
      width: 100%;
      gap: 4px;
      border: 0;
      border-bottom: 1px solid var(--line);
      padding: 11px 12px;
      background: var(--surface);
      color: var(--text);
      text-align: left;
      cursor: pointer;
    }
    .monitor-record-button:last-child { border-bottom: 0; }
    .monitor-record-button:hover { background: var(--surface-hover); }
    .monitor-record-button.active {
      background: #edf4ff;
      box-shadow: inset 3px 0 0 #4c78b8;
    }
    .monitor-record-title {
      overflow: hidden;
      font-size: 13px;
      font-weight: 680;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .monitor-record-subtitle {
      overflow: hidden;
      color: var(--muted);
      font-size: 11px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .monitor-record-detail { min-width: 0; padding: 16px; }
    .monitor-record-detail h4 {
      margin: 0 0 14px;
      font-size: 16px;
      line-height: 1.5;
    }
    .monitor-field-list {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0 18px;
      margin: 0;
    }
    .monitor-field {
      display: grid;
      grid-template-columns: 108px minmax(0, 1fr);
      gap: 10px;
      padding: 9px 0;
      border-bottom: 1px solid var(--line);
    }
    .monitor-field dt { color: var(--muted); font-size: 12px; }
    .monitor-field dd {
      margin: 0;
      overflow-wrap: anywhere;
      font-size: 12px;
      font-weight: 620;
    }
    .monitor-detail-actions { margin-top: 16px; }
    .work-panel {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--surface);
      overflow: hidden;
    }
    .work-panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      min-height: 46px;
      padding: 9px 12px;
      border-bottom: 1px solid var(--line);
      background: var(--surface-soft);
    }
    .work-panel-head h3 { margin: 0; font-size: 14px; letter-spacing: 0; }
    .work-panel-body { padding: 12px; }
    .spaced-panel { margin-top: 14px; }
    .control-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(120px, 1fr));
      gap: 10px;
    }
    .field {
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 12px;
    }
    .field input {
      width: 100%;
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 9px;
      background: var(--surface);
      color: var(--text);
    }
    .check-row {
      display: flex;
      align-items: center;
      gap: 16px;
      margin-top: 12px;
      flex-wrap: wrap;
    }
    .check-row label {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      color: #3c4859;
      font-size: 12px;
    }
    .check-row input { accent-color: var(--navy); }
    .monitor-actions {
      display: flex;
      gap: 8px;
      margin-top: 14px;
      flex-wrap: wrap;
    }
    .status-list { margin: 0; padding: 0; list-style: none; }
    .status-list li {
      display: grid;
      grid-template-columns: 92px minmax(0, 1fr);
      gap: 10px;
      padding: 9px 0;
      border-bottom: 1px solid var(--line);
    }
    .status-list li:last-child { border-bottom: 0; }
    .status-list span { color: var(--muted); font-size: 12px; }
    .status-list strong {
      overflow: hidden;
      font-size: 12px;
      font-weight: 650;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .status-list strong.risk { color: var(--danger); }
    .status-list strong.warning { color: var(--amber); }

    .insight-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 14px;
    }
    .insight {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 14px;
      background: var(--surface);
    }
    .insight-label { color: var(--muted); font-size: 11px; }
    .insight-value {
      margin-top: 6px;
      color: #2a374a;
      font-size: 14px;
      font-weight: 680;
      line-height: 1.55;
      overflow-wrap: anywhere;
    }
    .insight-link { display: inline-block; margin-top: 9px; font-size: 12px; }
    .report-banner {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      margin-top: 14px;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 14px;
      background: var(--surface-soft);
    }
    .report-banner strong { display: block; font-size: 14px; }
    .report-path {
      display: block;
      max-width: 720px;
      margin-top: 4px;
      overflow: hidden;
      color: var(--muted);
      font-size: 11px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .keyword-list {
      display: grid;
      gap: 8px;
      margin: 14px 0 0;
      padding: 0;
      list-style: none;
    }
    .keyword-list li {
      display: grid;
      grid-template-columns: minmax(150px, 1fr) 110px 110px;
      gap: 10px;
      align-items: center;
      min-height: 44px;
      border-bottom: 1px solid var(--line);
      padding: 7px 0;
    }
    .keyword-list li:last-child { border-bottom: 0; }
    .keyword-name { font-weight: 680; }
    .keyword-meta { color: var(--muted); font-size: 12px; }
    .keyword-pool-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      padding: 14px;
    }
    .keyword-category {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 13px;
      background: var(--surface);
    }
    .keyword-category-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 10px;
    }
    .keyword-category-head strong { color: #263349; font-size: 14px; }
    .keyword-category-count { color: var(--muted); font-size: 12px; }
    .keyword-chips {
      display: flex;
      align-items: center;
      gap: 7px;
      flex-wrap: wrap;
      min-height: 30px;
    }
    .keyword-chip {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      border-radius: 6px;
      padding: 4px 9px;
      background: var(--blue-soft);
      color: #275ea8;
      font-size: 12px;
      font-weight: 650;
    }
    .keyword-chip.approved {
      background: var(--green-soft);
      color: var(--green);
    }
    .keyword-category-empty { color: var(--muted); font-size: 12px; }
    .keyword-source-list {
      display: grid;
      gap: 10px;
      margin: 0;
      padding: 14px;
      list-style: none;
    }
    .keyword-source-item {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px 14px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 12px;
      background: var(--surface);
    }
    .keyword-source-title {
      color: #243044;
      font-size: 13px;
      font-weight: 680;
      line-height: 1.5;
    }
    .keyword-source-meta { color: var(--muted); font-size: 12px; }
    .review-boundary {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 14px;
      padding: 12px;
      border-bottom: 1px solid var(--line);
      background: var(--blue-soft);
    }
    .review-boundary strong { display: block; color: #1f4f89; font-size: 13px; }
    .review-boundary p {
      margin: 4px 0 0;
      color: #4f6782;
      font-size: 12px;
      line-height: 1.55;
    }
    .review-status {
      display: inline-flex;
      align-items: center;
      min-height: 25px;
      border: 1px solid #c8dcf4;
      border-radius: 5px;
      padding: 3px 7px;
      background: #fff;
      color: var(--blue);
      font-size: 11px;
      font-weight: 680;
      white-space: nowrap;
    }
    .suggestion-stats {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      border-bottom: 1px solid var(--line);
    }
    .suggestion-stat {
      min-width: 0;
      padding: 10px 12px;
      border-right: 1px solid var(--line);
    }
    .suggestion-stat:last-child { border-right: 0; }
    .suggestion-stat span { display: block; color: var(--muted); font-size: 11px; }
    .suggestion-stat strong {
      display: block;
      margin-top: 3px;
      overflow: hidden;
      color: #29384c;
      font-size: 16px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .suggestion-warning {
      margin: 10px 12px 0;
      border: 1px solid #ecd59a;
      border-radius: 6px;
      padding: 8px 10px;
      background: var(--amber-soft);
      color: #72500a;
      font-size: 12px;
      line-height: 1.5;
      overflow-wrap: anywhere;
    }
    .suggestion-list {
      display: grid;
      gap: 8px;
      margin: 0;
      padding: 12px;
      list-style: none;
    }
    .suggestion-item {
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 11px 12px;
      background: var(--surface);
    }
    .suggestion-main, .suggestion-support, .suggestion-sources {
      display: grid;
      align-content: start;
      gap: 5px;
      min-width: 0;
    }
    .suggestion-keyword {
      color: #243044;
      font-size: 14px;
      font-weight: 730;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }
    .suggestion-badges {
      display: flex;
      align-items: center;
      gap: 5px;
      flex-wrap: wrap;
    }
    .layer-badge, .risk-badge {
      display: inline-flex;
      width: fit-content;
      min-height: 22px;
      align-items: center;
      border-radius: 5px;
      padding: 2px 6px;
      font-size: 11px;
      font-weight: 680;
    }
    .layer-badge.core { background: var(--green-soft); color: var(--green); }
    .layer-badge.explore { background: var(--amber-soft); color: var(--amber); }
    .risk-badge { background: var(--brand-soft); color: var(--brand); }
    .risk-badge.clear { background: var(--surface-hover); color: var(--muted); }
    .suggestion-label { color: var(--muted); font-size: 11px; }
    .suggestion-value {
      color: #455267;
      font-size: 12px;
      line-height: 1.5;
      overflow-wrap: anywhere;
    }
    .suggestion-empty {
      padding: 28px 14px;
      color: var(--muted);
      text-align: center;
    }
    .keyword-approval-manifest {
      border-color: #f1c7be;
      box-shadow: inset 4px 0 0 var(--brand);
    }
    .keyword-approval-manifest.current {
      border-color: #a7d8c2;
      box-shadow: inset 4px 0 0 var(--green);
    }
    .keyword-approval-manifest.missing {
      box-shadow: inset 4px 0 0 var(--amber);
    }
    .keyword-approval-manifest .review-boundary {
      background: #fff8f6;
    }
    .keyword-approval-status-grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      border-bottom: 1px solid var(--line);
    }
    .keyword-approval-detail-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      padding: 12px;
    }
    .keyword-approval-entry-status.approved {
      background: var(--green-soft);
      color: var(--green);
    }
    .keyword-approval-entry-status.rejected {
      background: var(--brand-soft);
      color: var(--brand);
    }
    .keyword-approval-entry-status.pending {
      background: var(--amber-soft);
      color: var(--amber);
    }
    .remediation-stats {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      border-bottom: 1px solid var(--line);
    }
    .remediation-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      padding: 12px;
    }
    .remediation-group {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--surface);
      overflow: hidden;
    }
    .remediation-group.dependencies { grid-column: 1 / -1; }
    .remediation-group h4 {
      margin: 0;
      border-bottom: 1px solid var(--line);
      padding: 9px 11px;
      background: var(--surface-soft);
      color: #2a374a;
      font-size: 12px;
    }
    .remediation-list {
      display: grid;
      gap: 8px;
      margin: 0;
      padding: 10px;
      list-style: none;
    }
    .remediation-item {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      background: #fff;
    }
    .remediation-item-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 6px;
    }
    .remediation-item-head strong {
      color: #263349;
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .stage-badge {
      display: inline-flex;
      width: fit-content;
      min-height: 22px;
      align-items: center;
      border-radius: 5px;
      padding: 2px 6px;
      background: var(--blue-soft);
      color: var(--blue);
      font-size: 11px;
      font-weight: 680;
      white-space: nowrap;
    }
    .stage-badge.isolated { background: var(--amber-soft); color: var(--amber); }
    .stage-badge.skipped { background: var(--surface-hover); color: var(--muted); }
    .remediation-detail {
      color: #4c596c;
      font-size: 11px;
      line-height: 1.55;
      overflow-wrap: anywhere;
    }
    .remediation-detail + .remediation-detail { margin-top: 3px; }
    .remediation-empty {
      padding: 20px 12px;
      color: var(--muted);
      font-size: 12px;
      text-align: center;
    }
    .approval-manifest {
      border-color: #f1c7be;
    }
    .approval-manifest.current {
      border-color: #a7d8c2;
    }
    .approval-manifest.blocked {
      box-shadow: inset 4px 0 0 var(--red);
    }
    .approval-manifest.missing {
      box-shadow: inset 4px 0 0 var(--amber);
    }
    .approval-manifest .review-boundary {
      background: #fff8f6;
    }
    .approval-status-grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      border-bottom: 1px solid var(--line);
    }
    .approval-validation-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      padding: 12px;
    }
    .approval-validation-grid .remediation-group {
      min-height: 100%;
    }
    .soak-readiness-stats {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      border-bottom: 1px solid var(--line);
    }
    .soak-gates {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin: 0;
      padding: 12px;
      list-style: none;
    }
    .soak-gate {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 10px;
      background: var(--surface);
    }
    .soak-gate-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 6px;
    }
    .soak-gate-head strong { color: #263349; font-size: 12px; }
    .gate-status {
      display: inline-flex;
      min-height: 22px;
      align-items: center;
      border-radius: 5px;
      padding: 2px 6px;
      font-size: 11px;
      font-weight: 680;
      white-space: nowrap;
    }
    .gate-status.passed { background: var(--green-soft); color: var(--green); }
    .gate-status.failed { background: var(--red-soft); color: var(--red); }
    .gate-status.insufficient,
    .gate-status.not-reached { background: var(--amber-soft); color: var(--amber); }
    .gate-status.eligible { background: var(--blue-soft); color: var(--blue); }
    .soak-gate-reason {
      color: #4c596c;
      font-size: 11px;
      line-height: 1.5;
      overflow-wrap: anywhere;
    }
    .soak-detail-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      padding: 0 12px 12px;
    }
    .soak-detail {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--surface);
      overflow: hidden;
    }
    .soak-detail h4 {
      margin: 0;
      border-bottom: 1px solid var(--line);
      padding: 9px 11px;
      background: var(--surface-soft);
      color: #2a374a;
      font-size: 12px;
    }
    .soak-detail-list {
      display: grid;
      gap: 6px;
      margin: 0;
      padding: 10px 12px;
      list-style: none;
    }
    .soak-detail-list li {
      color: #4c596c;
      font-size: 11px;
      line-height: 1.5;
      overflow-wrap: anywhere;
    }
    .soak-evidence-grid {
      display: grid;
      grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
      gap: 12px;
      padding: 0 12px 12px;
    }
    .baseline-evidence {
      grid-column: 1 / -1;
      box-shadow: inset 4px 0 0 var(--red);
    }
    .baseline-evidence.ready {
      box-shadow: inset 4px 0 0 var(--green);
    }
    .baseline-overview {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      border-bottom: 1px solid var(--line);
    }
    .baseline-detail-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      padding: 10px;
    }
    .baseline-detail-grid .soak-detail-list {
      padding: 0;
    }
    .soak-evidence-state {
      display: inline-flex;
      min-height: 22px;
      align-items: center;
      border-radius: 5px;
      padding: 2px 6px;
      background: var(--surface-hover);
      color: var(--muted);
      font-size: 11px;
      font-weight: 680;
    }
    .soak-evidence-state.ready { background: var(--green-soft); color: var(--green); }
    .soak-evidence-state.blocked { background: var(--brand-soft); color: var(--brand); }
    .soak-stage-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      padding: 10px;
    }
    .soak-stage {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px;
      background: var(--surface-soft);
    }
    .soak-stage-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 6px;
    }
    .soak-stage-head strong { color: #263349; font-size: 12px; }
    .soak-stage-lines {
      display: grid;
      gap: 4px;
      color: #4c596c;
      font-size: 11px;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }

    .toast {
      position: fixed;
      right: 18px;
      bottom: 18px;
      z-index: 60;
      max-width: min(420px, calc(100vw - 36px));
      border-radius: 7px;
      padding: 11px 13px;
      background: var(--navy);
      box-shadow: 0 12px 32px rgba(15, 23, 42, 0.22);
      color: #fff;
      opacity: 0;
      pointer-events: none;
      transform: translateY(8px);
      transition: opacity 160ms ease, transform 160ms ease;
    }
    .toast.show { opacity: 1; transform: translateY(0); }

    @media (max-width: 1180px) {
      .app-shell { grid-template-columns: 180px minmax(0, 1fr); }
      .detail-grid { grid-template-columns: 1fr; }
      .insight-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .kpi-strip { grid-template-columns: repeat(3, minmax(110px, 1fr)); }
      .suggestion-stats { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .remediation-stats { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .approval-status-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .approval-validation-grid { grid-template-columns: 1fr; }
      .soak-readiness-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .soak-gates { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .soak-detail-grid { grid-template-columns: 1fr; }
      .soak-evidence-grid { grid-template-columns: 1fr; }
      .baseline-overview { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .baseline-detail-grid { grid-template-columns: 1fr; }
      .suggestion-stat:nth-child(3) { border-right: 0; }
      .suggestion-stat:nth-child(-n + 3) { border-bottom: 1px solid var(--line); }
      .suggestion-item { grid-template-columns: minmax(150px, 1fr) minmax(180px, 1.35fr); }
      .suggestion-sources { grid-column: 1 / -1; }
      .kpi:nth-child(4)::before { display: none; }
      .kpi:nth-child(-n + 3) { border-bottom: 1px solid var(--line); }
    }
    @media (max-width: 860px) {
      .app-shell { display: block; }
      .sidebar {
        position: static;
        height: auto;
        padding: 10px 12px;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }
      .brand { min-height: 36px; padding: 0; }
      .brand-mark { width: 30px; height: 30px; }
      .brand-version, .nav-label, .sidebar-footer { display: none; }
      .nav {
        display: flex;
        gap: 6px;
        margin-top: 10px;
        overflow-x: auto;
      }
      .nav-item {
        display: inline-flex;
        width: auto;
        min-width: max-content;
        min-height: 34px;
        padding: 5px 9px;
      }
      .nav-symbol { display: none; }
      .workspace { padding: 10px; }
      .workspace-frame { min-height: calc(100vh - 112px); }
      .workspace-header { min-height: 60px; padding: 10px 12px; }
      .page-description { display: none; }
      .tool-row { align-items: stretch; flex-direction: column; }
      .tool-group { width: 100%; }
      .search-box { width: 100%; }
      .result-meta { align-self: flex-end; }
    }
    @media (max-width: 720px) {
      .workspace-header { align-items: stretch; flex-direction: column; }
      .header-actions { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; }
      .header-actions .state-chip { justify-content: center; }
      .tool-group.filters { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .filter-select, .toggle { width: 100%; }
      .toggle { justify-content: center; }
      .data-table-wrap { padding: 8px; overflow: visible; }
      table, tbody { display: block; min-width: 0; }
      thead { display: none; }
      colgroup { display: none; }
      tbody tr {
        display: grid;
        grid-template-columns: 50px minmax(0, 1fr);
        margin-bottom: 8px;
        overflow: hidden;
        border: 1px solid var(--line);
        border-radius: 7px;
        background: var(--surface);
      }
      tbody tr:last-child { margin-bottom: 0; }
      tbody tr:hover td,
      tbody tr:hover td:first-child,
      tbody tr:hover td:nth-child(2) { background: var(--surface); }
      tbody td {
        position: static !important;
        display: grid;
        grid-template-columns: 92px minmax(0, 1fr);
        gap: 8px;
        width: auto;
        border-bottom: 1px solid var(--line);
        padding: 8px 10px;
        box-shadow: none !important;
      }
      tbody td::before {
        align-self: start;
        color: var(--muted);
        font-size: 11px;
        line-height: 1.5;
        content: attr(data-label);
      }
      tbody td:first-child {
        display: flex;
        grid-column: 1;
        grid-row: 1;
        border-bottom: 0;
      }
      tbody td:first-child::before { display: none; }
      tbody td:nth-child(2) {
        display: block;
        grid-column: 2;
        grid-row: 1;
        min-height: 64px;
        border-bottom: 0;
      }
      tbody td:nth-child(2)::before { display: none; }
      tbody td:nth-child(n + 3) { grid-column: 1 / -1; }
      tbody td:last-child { border-bottom: 0; }
      tbody td.empty { display: block; grid-column: 1 / -1; }
      tbody td.empty::before { display: none; }
      .commercial { justify-items: start; }
      .metric-row { justify-content: flex-start; }
      .metric-row span { width: 90px; }
      .detail-view { padding: 12px; }
      .kpi-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .kpi:nth-child(odd)::before { display: none; }
      .kpi:nth-child(-n + 4) { border-bottom: 1px solid var(--line); }
      .detail-grid, .insight-grid { grid-template-columns: 1fr; }
      .monitor-drilldown-layout { grid-template-columns: 1fr; }
      .monitor-record-list {
        max-height: 300px;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }
      .monitor-field-list { grid-template-columns: 1fr; }
      .control-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .report-banner { align-items: stretch; flex-direction: column; }
      .keyword-list li { grid-template-columns: 1fr; gap: 4px; }
      .keyword-pool-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .keyword-source-item { grid-template-columns: 1fr; }
      .review-boundary { flex-direction: column; }
      .suggestion-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .remediation-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .approval-status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .keyword-approval-status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .suggestion-stat { border-bottom: 1px solid var(--line); }
      .suggestion-stat:nth-child(odd) { border-right: 1px solid var(--line); }
      .suggestion-stat:nth-child(even) { border-right: 0; }
      .suggestion-stat:last-child { border-bottom: 0; }
      .suggestion-item { grid-template-columns: 1fr; }
      .keyword-pool-grid { grid-template-columns: 1fr; }
      .suggestion-sources { grid-column: auto; }
      .keyword-approval-detail-grid { grid-template-columns: 1fr; }
      .remediation-grid { grid-template-columns: 1fr; }
      .remediation-group.dependencies { grid-column: auto; }
      .soak-readiness-stats, .soak-gates { grid-template-columns: 1fr; }
      .baseline-overview { grid-template-columns: 1fr; }
      .soak-stage-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">选</div>
        <div class="brand-copy">
          <div class="brand-name">红选工作站</div>
          <div class="brand-version">虚拟商品观察 Agent</div>
        </div>
      </div>
      <nav class="nav" aria-label="工作区导航">
        <div class="nav-label">工作区</div>
        <button class="nav-item active" type="button" data-view="candidates">
          <span class="nav-symbol">品</span><span>已采集商品</span><span class="nav-count" id="navCandidateCount">-</span>
        </button>
        <button class="nav-item" type="button" data-view="monitor">
          <span class="nav-symbol">监</span><span>监控任务</span><span class="nav-count" id="navPendingCount">-</span>
        </button>
        <button class="nav-item" type="button" data-view="keywords">
          <span class="nav-symbol">词</span><span>关键词池</span>
        </button>
      </nav>
      <div class="sidebar-footer">
        <div class="service-ready">本地服务已连接</div>
        <div class="brand-version">端口 8793 · 安全采集模式</div>
      </div>
    </aside>

    <main class="workspace">
      <div class="workspace-frame">
        <header class="workspace-header">
          <div>
            <div class="page-title-row">
              <h1 class="page-title" id="viewTitle">已采集商品</h1>
              <span class="state-chip" id="headerMonitorState">状态读取中</span>
            </div>
            <div class="page-description" id="viewDescription">已入库商品的筛选、比较与商品直达</div>
          </div>
          <div class="header-actions">
            <span class="result-meta" id="lastUpdatedAt">尚未刷新</span>
            <button class="button ghost" id="refreshButton" type="button">刷新</button>
            <a class="button ghost" href="/export/candidates.csv">导出正式候选 CSV</a>
          </div>
        </header>

        <section class="view candidate-view active" data-view-panel="candidates">
          <div class="tool-row">
            <div class="tool-group">
              <input class="search-box" id="candidateSearch" type="search" placeholder="搜索商品标题、店铺或关键词">
            </div>
            <div class="tool-group filters">
              <select class="filter-select" id="gradeFilter" aria-label="证据等级">
                <option value="">全部等级</option>
                <option value="A">A 级</option>
                <option value="B">B 级</option>
                <option value="C">C 级</option>
                <option value="D">D 级</option>
              </select>
              <label class="toggle"><input id="lowFollowerOnly" type="checkbox">只看低粉</label>
              <label class="toggle"><input id="trendOnly" type="checkbox">有趋势证据</label>
              <label class="toggle"><input id="qualifiedOnly" type="checkbox">仅正式候选</label>
              <select class="filter-select" id="sortBy" aria-label="候选排序">
                <option value="score_desc">分数从高到低</option>
                <option value="observed_desc">采集时间从近到远</option>
                <option value="observed_asc">采集时间从远到近</option>
                <option value="sales30_desc">30天购买优先</option>
                <option value="sales_desc">累计销量优先</option>
                <option value="followers_asc">作者粉丝从低到高</option>
              </select>
              <span class="result-meta" id="candidateResultMeta">读取中</span>
            </div>
          </div>
          <div class="data-table-wrap">
            <table>
              <colgroup>
                <col class="grade"><col class="product"><col class="price">
                <col class="source"><col class="metrics"><col class="trend">
                <col class="followers"><col class="status"><col class="actions">
              </colgroup>
              <thead>
                <tr>
                  <th>等级</th>
                  <th>商品</th>
                  <th>价格 / 分数</th>
                  <th>店铺 / 关键词</th>
                  <th>数据指标</th>
                  <th>近期趋势</th>
                  <th>粉丝数</th>
                  <th>采集 / 资格</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody id="candidateRows">
                <tr><td colspan="9" class="empty">读取中...</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="view detail-view" data-view-panel="monitor">
          <div class="section-heading">
            <div>
              <h2>监控任务</h2>
              <p>单轮受控采集和长期监控状态；硬风控必须核对原因后单独解除。</p>
            </div>
            <span class="state-chip" id="monitorPageState">-</span>
          </div>
          <div class="kpi-strip" aria-label="监控概览">
            <button class="kpi" type="button" data-monitor-kind="tasks" aria-controls="monitorDrilldown"><div class="kpi-label">待搜索任务</div><div class="kpi-value" id="pendingTasks">-</div></button>
            <button class="kpi" type="button" data-monitor-kind="products" aria-controls="monitorDrilldown"><div class="kpi-label">已发现商品</div><div class="kpi-value" id="productCount">-</div></button>
            <button class="kpi" type="button" data-monitor-kind="observations" aria-controls="monitorDrilldown"><div class="kpi-label">观察记录</div><div class="kpi-value" id="observationCount">-</div></button>
            <button class="kpi" type="button" data-monitor-kind="followed" aria-controls="monitorDrilldown"><div class="kpi-label">持续关注</div><div class="kpi-value" id="followedProductCount">-</div></button>
            <button class="kpi" type="button" data-monitor-kind="candidates" aria-controls="monitorDrilldown"><div class="kpi-label">正式候选</div><div class="kpi-value" id="candidateCount">-</div></button>
            <div class="kpi"><div class="kpi-label">下次计划</div><div class="kpi-value" id="nextRunCompact">-</div></div>
          </div>
          <section class="work-panel monitor-drilldown" id="monitorDrilldown" hidden>
            <div class="work-panel-head">
              <h3 id="monitorDrilldownTitle">明细清单</h3>
              <button class="button compact ghost" id="closeMonitorDrilldown" type="button">收起</button>
            </div>
            <div class="monitor-drilldown-layout">
              <div class="monitor-record-list" id="monitorRecordList"></div>
              <div class="monitor-record-detail" id="monitorRecordDetail">
                <div class="empty">请从左侧选择一条记录</div>
              </div>
            </div>
          </section>
          <div class="detail-grid monitor-controls">
            <section class="work-panel">
              <div class="work-panel-head"><h3>单轮参数</h3></div>
              <div class="work-panel-body">
                <div class="control-grid">
                  <label class="field">关键词数 <input id="maxKeywords" type="number" min="1" max="3" value="1"></label>
                  <label class="field">每词商品数 <input id="maxProducts" type="number" min="1" max="3" value="1"></label>
                  <label class="field">页面等待秒数 <input id="waitSeconds" type="number" min="3" max="20" step="1" value="6"></label>
                  <label class="field">指标条帧数 <input id="metricFrames" type="number" min="1" max="5" value="3"></label>
                </div>
                <div class="check-row">
                  <label><input id="metricsSwipe" type="checkbox" checked>采集灰色指标条</label>
                </div>
                <div class="monitor-actions">
                  <button class="button" id="runOnceButton" type="button">执行单轮</button>
                  <button class="button secondary" id="pauseButton" type="button">暂停</button>
                  <button class="button ghost" id="resumeButton" type="button">恢复普通暂停</button>
                  <button class="button danger" id="riskResumeButton" type="button" hidden>确认风险已解除并恢复</button>
                </div>
              </div>
            </section>
          </div>
        </section>

        <section class="view detail-view" data-view-panel="reports" hidden aria-hidden="true">
          <div class="section-heading">
            <div>
              <h2>报告与质量</h2>
              <p>候选分析、证据完整度和近 24 小时监控摘要。</p>
            </div>
            <a class="button" href="/reports/latest" target="_blank" rel="noopener">打开最新报告</a>
          </div>
          <div class="report-banner">
            <div>
              <strong id="latestReportState">最新报告读取中</strong>
              <span class="report-path" id="latestReport">-</span>
            </div>
            <div class="header-actions">
              <button class="button compact ghost" id="copyReportButton" type="button">复制路径</button>
              <a class="button compact ghost" href="/export/candidates.csv">导出正式候选 CSV</a>
            </div>
          </div>
          <div class="insight-grid">
            <article class="insight">
              <div class="insight-label">证据质量</div>
              <div class="insight-value" id="qualitySummary">-</div>
              <a class="insight-link" href="/api/quality" target="_blank" rel="noopener">查看质量问题</a>
            </article>
            <article class="insight">
              <div class="insight-label">近 24 小时摘要</div>
              <div class="insight-value" id="digestSummary">-</div>
              <a class="insight-link" href="/api/digest/daily" target="_blank" rel="noopener">查看结构化摘要</a>
            </article>
            <article class="insight">
              <div class="insight-label">关键词覆盖</div>
              <div class="insight-value" id="portfolioSummary">-</div>
              <a class="insight-link" href="/api/portfolio" target="_blank" rel="noopener">查看轮转计划</a>
            </article>
          </div>
          <section class="work-panel spaced-panel" aria-labelledby="soakReadinessTitle">
            <div class="work-panel-head">
              <h3 id="soakReadinessTitle">pre-soak 只读准入证据</h3>
              <span class="result-meta" id="soakReadinessMeta">读取中</span>
            </div>
            <div class="review-boundary">
              <div>
                <strong>仅展示 G0–G6 证据，不是启动按钮或扩容授权</strong>
                <p>required 告警未记录或未 ACK、scheduler 到期点未记录或不匹配都不能晋级。ready 只表示证据门槛结果；即使门槛通过，也必须另行人工确认。本工作台不启动 pre-soak、24 小时 soak、监控或扩容。</p>
              </div>
              <span class="review-status" id="soakAuthorizationState">soak_start_authorized=false</span>
            </div>
            <div class="soak-readiness-stats" aria-label="soak 准入概览">
              <div class="suggestion-stat"><span>pre-soak</span><strong id="preSoakReadiness">读取中</strong></div>
              <div class="suggestion-stat"><span>24 小时 soak</span><strong id="fullSoakReadiness">读取中</strong></div>
              <div class="suggestion-stat"><span>证据轮次</span><strong id="soakRoundsRead">-</strong></div>
              <div class="suggestion-stat"><span>证据时间范围</span><strong id="soakEvidenceRange">-</strong></div>
            </div>
            <div class="suggestion-warning" id="soakReadinessWarning" hidden></div>
            <ul class="soak-gates" id="soakGateList" aria-label="G0 至 G6">
              <li class="remediation-empty">读取中...</li>
            </ul>
            <div class="soak-detail-grid">
              <section class="soak-detail" aria-labelledby="soakGapsTitle">
                <h4 id="soakGapsTitle">主要 gaps</h4>
                <ul class="soak-detail-list" id="soakGapList">
                  <li>读取中...</li>
                </ul>
              </section>
              <section class="soak-detail" aria-labelledby="soakWarningsTitle">
                <h4 id="soakWarningsTitle">warnings</h4>
                <ul class="soak-detail-list" id="soakWarningList">
                  <li>读取中...</li>
                </ul>
              </section>
              <section class="soak-detail" aria-labelledby="soakEvidenceScopeTitle">
                <h4 id="soakEvidenceScopeTitle">证据范围</h4>
                <ul class="soak-detail-list" id="soakEvidenceScopeList">
                  <li>读取中...</li>
                </ul>
              </section>
            </div>
            <div class="soak-evidence-grid">
              <section class="soak-detail" aria-labelledby="soakAckTitle">
                <div class="work-panel-head">
                  <h4 id="soakAckTitle">人工 ACK 完整性</h4>
                  <span class="soak-evidence-state" id="soakAckState">读取中</span>
                </div>
                <ul class="soak-detail-list" id="soakAckList">
                  <li>读取中...</li>
                </ul>
              </section>
              <section class="soak-detail" aria-labelledby="schedulerEvidenceTitle">
                <div class="work-panel-head">
                  <h4 id="schedulerEvidenceTitle">scheduler evidence · G2 / G4</h4>
                  <span class="soak-evidence-state" id="schedulerEvidenceState">读取中</span>
                </div>
                <div class="soak-stage-grid" id="schedulerEvidenceStages">
                  <div class="remediation-empty">读取中...</div>
                </div>
              </section>
              <section class="soak-detail baseline-evidence" id="baselineEvidencePanel" aria-labelledby="baselineEvidenceTitle">
                <div class="work-panel-head">
                  <h4 id="baselineEvidenceTitle">pre-soak baseline · 只读准入</h4>
                  <span class="soak-evidence-state blocked" id="baselineEvidenceState">读取中</span>
                </div>
                <div class="review-boundary">
                  <div>
                    <strong>真实 baseline 未生成、清单损坏或文件漂移时，不具备准入</strong>
                    <p>这里只读取 record.baseline，不上传、不生成、不编辑、不批准，也不执行或启动 pre-soak / 24 小时 soak。字段缺失或未知一律 fail closed。</p>
                  </div>
                  <span class="review-status" id="baselineAuthorizationBoundary">authorizes_start=false</span>
                </div>
                <div class="baseline-overview" aria-label="baseline 准入概览">
                  <div class="suggestion-stat"><span>status</span><strong id="baselineStatus">读取中</strong></div>
                  <div class="suggestion-stat"><span>source</span><strong id="baselineSource">读取中</strong></div>
                  <div class="suggestion-stat"><span>integrity</span><strong id="baselineIntegrity">读取中</strong></div>
                  <div class="suggestion-stat"><span>baseline_id</span><strong id="baselineId">-</strong></div>
                  <div class="suggestion-stat"><span>manifest_hash</span><strong id="baselineManifestHash">-</strong></div>
                </div>
                <div class="baseline-detail-grid">
                  <section aria-labelledby="baselineFailureTitle">
                    <h4 id="baselineFailureTitle">缺失 / 坏清单 / 文件漂移</h4>
                    <ul class="soak-detail-list" id="baselineFailureList">
                      <li>读取中...</li>
                    </ul>
                  </section>
                  <section aria-labelledby="baselineRequirementTitle">
                    <h4 id="baselineRequirementTitle">硬核对项</h4>
                    <ul class="soak-detail-list" id="baselineRequirementList">
                      <li>读取中...</li>
                    </ul>
                  </section>
                  <section aria-labelledby="baselineGapTitle">
                    <h4 id="baselineGapTitle">baseline gaps / warnings</h4>
                    <ul class="soak-detail-list" id="baselineGapList">
                      <li>读取中...</li>
                    </ul>
                  </section>
                </div>
              </section>
            </div>
          </section>
          <section class="work-panel spaced-panel" aria-labelledby="remediationPlanTitle">
            <div class="work-panel-head">
              <h3 id="remediationPlanTitle">只读补证计划</h3>
              <span class="result-meta" id="remediationPlanMeta">读取中</span>
            </div>
            <div class="review-boundary">
              <div>
                <strong>仅展示计划，不执行、不审批、不写队列</strong>
                <p>阶段、批次、隔离商品和依赖仅供人工复核；本工作台没有补证执行入口。</p>
              </div>
              <span class="review-status" id="remediationScopeMode">只读计划</span>
            </div>
            <div class="remediation-stats" aria-label="补证计划预算与概览">
              <div class="suggestion-stat"><span>最早阶段</span><strong id="remediationEarliestStage">-</strong></div>
              <div class="suggestion-stat"><span>计划批次</span><strong id="remediationBatchCount">-</strong></div>
              <div class="suggestion-stat"><span>隔离商品</span><strong id="remediationIsolatedCount">-</strong></div>
              <div class="suggestion-stat"><span>计划访问</span><strong id="remediationVisitCount">-</strong></div>
              <div class="suggestion-stat"><span>批次 / 小时预算</span><strong id="remediationBudget">-</strong></div>
              <div class="suggestion-stat"><span>商品冷却小时</span><strong id="remediationCooldown">-</strong></div>
            </div>
            <div class="suggestion-warning" id="remediationWarning" hidden></div>
            <div class="remediation-grid">
              <section class="remediation-group" aria-labelledby="remediationBatchesTitle">
                <h4 id="remediationBatchesTitle">阶段与批次</h4>
                <ul class="remediation-list" id="remediationBatchList">
                  <li class="remediation-empty">读取中...</li>
                </ul>
              </section>
              <section class="remediation-group" aria-labelledby="remediationIsolationTitle">
                <h4 id="remediationIsolationTitle">隔离与跳过</h4>
                <ul class="remediation-list" id="remediationIsolationList">
                  <li class="remediation-empty">读取中...</li>
                </ul>
              </section>
              <section class="remediation-group dependencies" aria-labelledby="remediationDependenciesTitle">
                <h4 id="remediationDependenciesTitle">依赖 / 阻塞</h4>
                <ul class="remediation-list" id="remediationDependencyList">
                  <li class="remediation-empty">读取中...</li>
                </ul>
              </section>
            </div>
          </section>
          <section class="work-panel spaced-panel approval-manifest blocked" id="approvalManifestPanel" aria-labelledby="approvalManifestTitle">
            <div class="work-panel-head">
              <h3 id="approvalManifestTitle">补证审批清单 · 只读复核</h3>
              <span class="result-meta" id="approvalManifestMeta">读取中</span>
            </div>
            <div class="review-boundary">
              <div>
                <strong>审批清单不等于执行授权</strong>
                <p>planned_approved 只表示离线计划通过复核；始终必须保持 not_executed、authorizes_execution=false。本卡片不创建清单、不批准、不写队列，也不执行补证。</p>
              </div>
              <span class="review-status" id="approvalExecutionBoundary">authorizes_execution=false</span>
            </div>
            <div class="approval-status-grid" aria-label="补证审批状态概览">
              <div class="suggestion-stat"><span>manifest_status</span><strong id="approvalManifestStatus">读取中</strong></div>
              <div class="suggestion-stat"><span>review_status</span><strong id="approvalReviewStatus">读取中</strong></div>
              <div class="suggestion-stat"><span>source_plan_current</span><strong id="approvalSourcePlanCurrent">读取中</strong></div>
              <div class="suggestion-stat"><span>计划审批</span><strong id="approvalPlanStatus">读取中</strong></div>
              <div class="suggestion-stat"><span>执行状态</span><strong id="approvalExecutionStatus">not_executed</strong></div>
              <div class="suggestion-stat"><span>已选批次 / 商品</span><strong id="approvalSelectionCount">-</strong></div>
            </div>
            <div class="suggestion-warning" id="approvalBlockingState">读取中；审批清单不等于执行授权。</div>
            <div class="approval-validation-grid">
              <section class="remediation-group" aria-labelledby="approvalValidationTitle">
                <h4 id="approvalValidationTitle">完整性与当前计划校验</h4>
                <ul class="remediation-list" id="approvalValidationList">
                  <li class="remediation-empty">读取中...</li>
                </ul>
              </section>
              <section class="remediation-group" aria-labelledby="approvalPolicyTitle">
                <h4 id="approvalPolicyTitle">预算 / 隔离策略</h4>
                <ul class="remediation-list" id="approvalPolicyList">
                  <li class="remediation-empty">读取中...</li>
                </ul>
              </section>
              <section class="remediation-group" aria-labelledby="approvalIssuesTitle">
                <h4 id="approvalIssuesTitle">issues / warnings</h4>
                <ul class="remediation-list" id="approvalIssueList">
                  <li class="remediation-empty">读取中...</li>
                </ul>
              </section>
            </div>
            <div class="remediation-grid">
              <section class="remediation-group dependencies" aria-labelledby="approvalBatchesTitle">
                <h4 id="approvalBatchesTitle">已审批计划批次与依赖 · 仍未执行</h4>
                <ul class="remediation-list" id="approvalBatchList">
                  <li class="remediation-empty">读取中...</li>
                </ul>
              </section>
            </div>
          </section>
        </section>

        <section class="view detail-view" data-view-panel="keywords">
          <div class="section-heading">
            <div>
              <h2>关键词池</h2>
              <p>从已采集商品标题中拆解，并按用途分类保存。</p>
            </div>
            <span class="result-meta" id="keywordPoolSourceCount">已归档商品 -</span>
          </div>
          <div class="kpi-strip" aria-label="关键词池概览">
            <div class="kpi"><div class="kpi-label">关键词总数</div><div class="kpi-value" id="keywordPoolTotal">-</div></div>
            <div class="kpi"><div class="kpi-label">人群词</div><div class="kpi-value" id="keywordPoolAudience">-</div></div>
            <div class="kpi"><div class="kpi-label">功效词</div><div class="kpi-value" id="keywordPoolFunction">-</div></div>
            <div class="kpi"><div class="kpi-label">场景词</div><div class="kpi-value" id="keywordPoolScene">-</div></div>
            <div class="kpi"><div class="kpi-label">品类词</div><div class="kpi-value" id="keywordPoolDomain">-</div></div>
            <div class="kpi"><div class="kpi-label">形式词</div><div class="kpi-value" id="keywordPoolFormat">-</div></div>
          </div>
          <section class="work-panel spaced-panel" aria-labelledby="classifiedKeywordPoolTitle">
            <div class="work-panel-head">
              <h3 id="classifiedKeywordPoolTitle">分类关键词</h3>
              <span class="result-meta" id="keywordPoolMeta">读取中</span>
            </div>
            <div class="keyword-pool-grid" id="keywordPoolGrid">
              <div class="suggestion-empty">读取中...</div>
            </div>
          </section>
          <section class="work-panel spaced-panel" aria-labelledby="keywordSourceProductsTitle">
            <div class="work-panel-head">
              <h3 id="keywordSourceProductsTitle">已归档商品</h3>
            </div>
            <ul class="keyword-source-list" id="keywordSourceProducts">
              <li class="suggestion-empty">读取中...</li>
            </ul>
          </section>
        </section>
      </div>
    </main>
  </div>

  <div class="toast" id="toast" role="status" aria-live="polite"></div>

  <script>
    const API_ROUTES = {
      status: "/api/status",
      pause: "/api/monitor/pause",
      resume: "/api/monitor/resume",
      riskResume: "/api/monitor/risk-resume",
      runOnce: "/api/monitor/run-once",
      monitorDetails: "/api/monitor/details/",
      salesFollow: "/api/products/",
      productAction: "/api/products/",
      keywordPool: "/api/keyword-pool",
      keywordSuggestions: "/api/keyword-suggestions",
      keywordCombinationReview: "/api/keyword-combination-review",
      keywordApprovalManifest: "/api/keyword-approval-manifest",
      remediationPlan: "/api/remediation-plan",
      approvalManifest: "/api/approval-manifest",
      soakReadiness: "/api/soak-readiness"
    };
    const VIEW_META = {
      candidates: ["已采集商品", "展示全部入库商品，并明确正式候选与未入选原因"],
      monitor: ["监控任务", "受控采集参数、调度状态与安全停止"],
      keywords: ["关键词池", "从已采集商品标题中拆解并分类保存"]
    };
    const SOAK_GATE_NAMES = ["G0", "G1", "G2", "G3", "G4", "G5", "G6"];
    const $ = (id) => document.getElementById(id);
    let latestStatus = null;
    let candidateItems = [];
    let activeMonitorKind = null;

    function valueText(value) {
      if (value === null || value === undefined || value === "") return "-";
      return String(value);
    }

    function numericValue(value, fallback = -1) {
      if (value === null || value === undefined || value === "") return fallback;
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : fallback;
    }

    function compareObservedAt(a, b, direction) {
      const aTime = Date.parse(a?.observed_at || "");
      const bTime = Date.parse(b?.observed_at || "");
      const aValid = Number.isFinite(aTime);
      const bValid = Number.isFinite(bTime);
      if (!aValid && !bValid) return 0;
      if (!aValid) return 1;
      if (!bValid) return -1;
      return direction === "asc" ? aTime - bTime : bTime - aTime;
    }

    function compactNumber(value) {
      const number = numericValue(value);
      if (number < 0) return "-";
      if (number >= 10000) return `${(number / 10000).toFixed(number >= 100000 ? 0 : 1)}万`;
      return String(number);
    }

    function minimumMetricText(value) {
      const number = numericValue(value);
      if (number < 0) return "-";
      const compact = compactNumber(number);
      return number > 0 ? `${compact}+` : compact;
    }

    function shortDate(value) {
      if (!value) return "-";
      const text = String(value).replace("T", " ");
      return text.length > 16 ? text.slice(0, 16) : text;
    }

    function numberFromInput(id, fallback) {
      const value = Number($(id).value);
      return Number.isFinite(value) ? value : fallback;
    }

    function safeHttpUrl(value) {
      if (typeof value !== "string") return null;
      try {
        const url = new URL(value);
        return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
      } catch {
        return null;
      }
    }

    function safeProductDirectUrl(value) {
      if (typeof value !== "string") return null;
      try {
        const url = new URL(value);
        if (url.username || url.password || url.port) return null;
        const host = url.hostname.toLowerCase().replace(/\.$/, "");
        if (url.protocol === "https:") {
          if (host !== "xiaohongshu.com" && host !== "www.xiaohongshu.com") return null;
          return /^\/(?:goods|goods-detail)\/[A-Za-z0-9_-]+\/?$/.test(url.pathname)
            ? url.href
            : null;
        }
        if (url.protocol !== "xhsdiscover:") return null;
        const validPath = host === "page"
          ? /^\/goods\/[A-Za-z0-9_-]+\/?$/.test(url.pathname)
          : host === "goods_detail" && /^\/[A-Za-z0-9_-]+\/?$/.test(url.pathname);
        return validPath ? url.href : null;
      } catch {
        return null;
      }
    }

    function safeProductShareUrl(value) {
      if (typeof value !== "string") return null;
      try {
        const url = new URL(value);
        if (url.protocol !== "https:" || url.username || url.password || url.port) return null;
        const host = url.hostname.toLowerCase().replace(/\.$/, "");
        return host === "xhslink.com" && /^\/(?:a|m)\/[A-Za-z0-9_-]+\/?$/.test(url.pathname)
          ? url.href
          : null;
      } catch {
        return null;
      }
    }

    function showToast(message) {
      const toast = $("toast");
      toast.textContent = message;
      toast.classList.add("show");
      window.clearTimeout(showToast.timer);
      showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 3200);
    }

    function appendCell(row, content, label, className) {
      const cell = document.createElement("td");
      if (label) cell.dataset.label = label;
      if (className) cell.className = className;
      if (content instanceof Node) cell.appendChild(content);
      else cell.textContent = valueText(content);
      row.appendChild(cell);
      return cell;
    }

    function makeGradeBadge(grade) {
      const badge = document.createElement("span");
      badge.className = "grade-badge";
      if (grade === "A") badge.classList.add("a");
      if (grade === "C" || grade === "D") badge.classList.add("warn");
      badge.textContent = valueText(grade);
      return badge;
    }

    function makeProduct(item) {
      const wrap = document.createElement("div");
      wrap.className = "product-cell";
      const directUrl = safeProductDirectUrl(item.direct_url);
      const shareUrl = safeProductShareUrl(item.share_url);
      const title = document.createElement("span");
      title.className = "product-title plain";
      title.textContent = valueText(item.title);
      const meta = document.createElement("div");
      meta.className = "product-meta";
      const productId = document.createElement("span");
      productId.textContent = `商品 ${valueText(item.product_id)}`;
      meta.append(productId);
      const linkState = document.createElement("span");
      linkState.textContent = directUrl
        ? "主链接已采集"
        : shareUrl
          ? "仅分享短链·直达待补"
          : "链接待采集";
      meta.appendChild(linkState);
      wrap.append(title, meta);
      return wrap;
    }

    function makeCommercial(item) {
      const wrap = document.createElement("div");
      wrap.className = "commercial";
      const price = document.createElement("strong");
      price.textContent = item.price === null || item.price === undefined ? "-" : `¥${item.price}`;
      const score = document.createElement("span");
      score.textContent = `分数 ${valueText(item.score)}`;
      wrap.append(price, score);
      return wrap;
    }

    function makeSource(item) {
      const wrap = document.createElement("div");
      wrap.className = "source-cell";
      const shop = document.createElement("span");
      shop.className = "shop-name";
      shop.textContent = valueText(item.shop_name);
      const keyword = document.createElement("span");
      keyword.className = "keyword";
      keyword.textContent = `搜索关键词：${valueText(item.search_source_keyword)}`;
      wrap.append(shop, keyword);
      return wrap;
    }

    function makeMetricStack(metrics, className = "") {
      const wrap = document.createElement("div");
      wrap.className = `metric-stack${className ? ` ${className}` : ""}`;
      for (const metric of metrics) {
        const row = document.createElement("div");
        row.className = "metric-row";
        const label = document.createElement("span");
        label.textContent = metric[0];
        const value = document.createElement("strong");
        if (metric[2]) value.className = metric[2];
        value.textContent = metric[3] === "raw"
          ? valueText(metric[1])
          : metric[3] === "minimum"
            ? minimumMetricText(metric[1])
            : compactNumber(metric[1]);
        row.append(label, value);
        wrap.appendChild(row);
      }
      return wrap;
    }

    function trendStrength(item) {
      return Math.max(
        numericValue(item.sales_24h_min, 0),
        numericValue(item.cart_24h_min, 0),
        numericValue(item.sales_7d_min, 0),
        numericValue(item.sales_30d_min, 0)
      );
    }

    function makeTrend(item) {
      const wrap = document.createElement("div");
      wrap.className = "metric-stack";
      const badge = document.createElement("span");
      const strength = trendStrength(item);
      badge.className = `trend-badge${strength > 0 ? "" : " quiet"}`;
      badge.textContent = item.sales_surging
        ? "销量上升"
        : (strength > 0 ? "已采到趋势" : "趋势待补");
      wrap.appendChild(badge);
      wrap.appendChild(makeMetricStack([
        ["24小时新增销量", item.daily_sales_delta ?? "待满24小时", "hot", "raw"],
        ["24h加购", item.cart_24h_min, "positive"]
      ]));
      return wrap;
    }

    function makeFollowerCount(item) {
      const wrap = document.createElement("div");
      wrap.className = "follower-cell";
      const followers = numericValue(item.seller_follower_count);
      const count = document.createElement("strong");
      count.className = "follower-count";
      count.textContent = item.seller_follower_display_status === "not_displayed"
        ? "页面未显示"
        : (followers >= 0 ? compactNumber(followers) : "-");
      wrap.appendChild(count);
      if (followers > 0 && followers <= 2000) {
        const badge = document.createElement("span");
        badge.className = "follower-band core";
        badge.textContent = "低粉店铺";
        wrap.appendChild(badge);
      }
      return wrap;
    }

    function makeQualification(item) {
      const wrap = document.createElement("div");
      wrap.className = "metric-stack";
      const collection = document.createElement("span");
      collection.className = `trend-badge${item.collection_status === "complete" ? "" : " quiet"}`;
      collection.textContent = item.collection_status === "complete" ? "完整采集" : "部分写入";
      const qualification = document.createElement("span");
      qualification.className = `follower-band ${item.candidate_qualified ? "core" : "missing"}`;
      qualification.textContent = item.candidate_qualified ? "正式候选" : "未入选";
      const reason = document.createElement("span");
      const reasons = Array.isArray(item.qualification_reasons)
        ? item.qualification_reasons : [];
      reason.className = "product-meta";
      reason.textContent = reasons.join("；") || "资格原因待补";
      wrap.append(collection, qualification, reason);
      return wrap;
    }

    function makeActions(item) {
      const wrap = document.createElement("div");
      wrap.className = "row-actions";
      const analysis = document.createElement("a");
      analysis.className = "text-action";
      analysis.href = `/products/${encodeURIComponent(item.product_id)}/analysis`;
      analysis.target = "_blank";
      analysis.rel = "noopener noreferrer";
      analysis.textContent = "分析";
      wrap.appendChild(analysis);
      const directUrl = safeProductDirectUrl(item.direct_url);
      const shareUrl = safeProductShareUrl(item.share_url);
      const computerOpen = document.createElement(shareUrl ? "a" : "button");
      computerOpen.className = "text-action";
      computerOpen.textContent = shareUrl ? "电脑打开" : "暂无电脑链接";
      if (shareUrl) {
        computerOpen.href = shareUrl;
        computerOpen.target = "_blank";
        computerOpen.rel = "noopener noreferrer";
      } else {
        computerOpen.type = "button";
        computerOpen.disabled = true;
      }
      wrap.appendChild(computerOpen);

      const phoneOpen = document.createElement("button");
      phoneOpen.className = "text-action";
      phoneOpen.type = "button";
      phoneOpen.textContent = directUrl ? "手机打开" : "暂无手机链接";
      phoneOpen.disabled = !directUrl;
      if (directUrl) {
        phoneOpen.addEventListener("click", () => openProductOnDevice(item, phoneOpen));
      }
      wrap.appendChild(phoneOpen);
      const follow = document.createElement("button");
      const isFollowing = Boolean(item.sales_followed);
      follow.className = `text-action${isFollowing ? " following" : ""}`;
      follow.type = "button";
      follow.textContent = isFollowing ? "已关注" : "持续关注";
      follow.title = isFollowing
        ? "点击取消后，商品将不再进入下一次每日销量监控"
        : "加入每日一次的销量监控名单";
      follow.addEventListener("click", () => toggleSalesFollow(item, follow));
      wrap.appendChild(follow);
      return wrap;
    }

    async function openProductOnDevice(item, button) {
      button.disabled = true;
      try {
        const response = await fetch(
          `${API_ROUTES.productAction}${encodeURIComponent(item.product_id)}/open-on-device`,
          { method: ["P", "O", "S", "T"].join("") }
        );
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          const detail = payload.detail || {};
          throw new Error(detail.message || detail || `HTTP ${response.status}`);
        }
        showToast("已请求在手机打开商品链接");
      } catch (error) {
        showToast(`手机打开失败：${error.message}`);
      } finally {
        button.disabled = false;
      }
    }

    async function toggleSalesFollow(item, button) {
      const enabled = !Boolean(item.sales_followed);
      button.disabled = true;
      try {
        const response = await fetch(
          `${API_ROUTES.salesFollow}${encodeURIComponent(item.product_id)}/sales-follow`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled })
          }
        );
        if (!response.ok) {
          const detail = await response.json().catch(() => ({}));
          throw new Error(detail.detail || `HTTP ${response.status}`);
        }
        const result = await response.json();
        item.sales_followed = Boolean(result.sales_followed);
        showToast(item.sales_followed
          ? "已加入每日销量监控"
          : "已取消持续关注，历史销量仍会保留");
        applyCandidateFilters();
      } catch (error) {
        showToast(`关注状态保存失败：${error.message}`);
        button.disabled = false;
      }
    }

    function renderRows(items) {
      const body = $("candidateRows");
      body.replaceChildren();
      if (!items.length) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.className = "empty";
        cell.colSpan = 9;
        cell.textContent = "没有符合当前筛选条件的已采集商品";
        row.appendChild(cell);
        body.appendChild(row);
        return;
      }
      for (const item of items) {
        const row = document.createElement("tr");
        appendCell(row, makeGradeBadge(item.evidence_grade), "等级");
        appendCell(row, makeProduct(item), "商品");
        appendCell(row, makeCommercial(item), "价格 / 分数");
        appendCell(row, makeSource(item), "店铺 / 关键词");
        appendCell(row, makeMetricStack([
          ["商品销量", item.cumulative_sales_display ?? item.cumulative_sales_min, "", "raw"],
          ["近30天购买", item.sales_30d_min, "positive", "minimum"],
          ["近30天好评", item.positive_reviews_30d_min, "", "minimum"],
          ["近30天收藏", item.favorites_30d_min, "positive", "minimum"],
          ["近7天感兴趣", item.interested_7d_min, "positive", "minimum"]
        ], "metrics-grid"), "数据指标");
        appendCell(row, makeTrend(item), "近期趋势");
        appendCell(row, makeFollowerCount(item), "粉丝数");
        appendCell(row, makeQualification(item), "采集 / 资格");
        appendCell(row, makeActions(item), "操作");
        body.appendChild(row);
      }
    }

    function applyCandidateFilters() {
      const query = $("candidateSearch").value.trim().toLowerCase();
      const grade = $("gradeFilter").value;
      const lowOnly = $("lowFollowerOnly").checked;
      const trendOnly = $("trendOnly").checked;
      const qualifiedOnly = $("qualifiedOnly").checked;
      const sortBy = $("sortBy").value;
      let items = candidateItems.filter((item) => {
        const haystack = [
          item.title,
          item.shop_name,
          item.search_source_keyword
        ].map((value) => valueText(value).toLowerCase()).join(" ");
        if (query && !haystack.includes(query)) return false;
        if (grade && item.evidence_grade !== grade) return false;
        const followers = numericValue(item.seller_follower_count);
        if (lowOnly && !(followers > 0 && followers <= 2000)) return false;
        if (trendOnly && trendStrength(item) <= 0) return false;
        if (qualifiedOnly && !item.candidate_qualified) return false;
        return true;
      });
      const sorters = {
        score_desc: (a, b) => numericValue(b.score, 0) - numericValue(a.score, 0),
        observed_desc: (a, b) => compareObservedAt(a, b, "desc"),
        observed_asc: (a, b) => compareObservedAt(a, b, "asc"),
        sales30_desc: (a, b) => numericValue(b.sales_30d_min, 0) - numericValue(a.sales_30d_min, 0),
        sales_desc: (a, b) => numericValue(b.cumulative_sales_min, 0) - numericValue(a.cumulative_sales_min, 0),
        followers_asc: (a, b) => {
          const av = numericValue(a.seller_follower_count, Number.MAX_SAFE_INTEGER);
          const bv = numericValue(b.seller_follower_count, Number.MAX_SAFE_INTEGER);
          return av - bv;
        }
      };
      items = [...items].sort(sorters[sortBy] || sorters.score_desc);
      $("candidateResultMeta").textContent = `显示 ${items.length} / ${candidateItems.length}`;
      renderRows(items);
    }

    function setMonitorChip(element, text, mode) {
      element.textContent = text;
      element.className = `state-chip ${mode}`;
    }

    function renderKeywordPool(data) {
      const categories = Array.isArray(data?.categories) ? data.categories : [];
      const categoryMap = Object.fromEntries(
        categories.map((category) => [category.dimension, category])
      );
      $("keywordPoolTotal").textContent = valueText(data?.total_terms);
      $("keywordPoolAudience").textContent = valueText(categoryMap.audience?.count);
      $("keywordPoolFunction").textContent = valueText(categoryMap.function?.count);
      $("keywordPoolScene").textContent = valueText(categoryMap.scene?.count);
      $("keywordPoolDomain").textContent = valueText(categoryMap.domain?.count);
      $("keywordPoolFormat").textContent = valueText(categoryMap.format?.count);
      $("keywordPoolSourceCount").textContent =
        `已归档商品 ${valueText(data?.source_product_count)}`;
      $("keywordPoolMeta").textContent = `共 ${valueText(data?.total_terms)} 个分类词`;

      const grid = $("keywordPoolGrid");
      grid.replaceChildren();
      for (const category of categories) {
        const card = document.createElement("section");
        card.className = "keyword-category";
        const head = document.createElement("div");
        head.className = "keyword-category-head";
        const title = document.createElement("strong");
        title.textContent = valueText(category.label);
        const count = document.createElement("span");
        count.className = "keyword-category-count";
        count.textContent = `${valueText(category.count)} 个`;
        head.append(title, count);

        const chips = document.createElement("div");
        chips.className = "keyword-chips";
        const terms = Array.isArray(category.terms) ? category.terms : [];
        if (!terms.length) {
          const empty = document.createElement("span");
          empty.className = "keyword-category-empty";
          empty.textContent = "暂无";
          chips.appendChild(empty);
        }
        for (const term of terms) {
          const chip = document.createElement("span");
          chip.className = `keyword-chip${term.review_status === "approved" ? " approved" : ""}`;
          chip.textContent = valueText(term.term);
          const sourceNames = Array.isArray(term.source_products)
            ? term.source_products.map((item) => item.title).filter(Boolean)
            : [];
          if (sourceNames.length) chip.title = `来自：${sourceNames.join("、")}`;
          chips.appendChild(chip);
        }
        card.append(head, chips);
        grid.appendChild(card);
      }
      if (!categories.length) {
        const empty = document.createElement("div");
        empty.className = "suggestion-empty";
        empty.textContent = "当前还没有已归类关键词。";
        grid.appendChild(empty);
      }

      const products = Array.isArray(data?.source_products) ? data.source_products : [];
      const productList = $("keywordSourceProducts");
      productList.replaceChildren();
      if (!products.length) {
        const empty = document.createElement("li");
        empty.className = "suggestion-empty";
        empty.textContent = "当前还没有完成关键词归档的商品。";
        productList.appendChild(empty);
      }
      for (const item of products) {
        const row = document.createElement("li");
        row.className = "keyword-source-item";
        const title = document.createElement("a");
        title.className = "keyword-source-title";
        title.href = `/products/${encodeURIComponent(item.product_id)}/analysis`;
        title.textContent = valueText(item.title);
        const meta = document.createElement("span");
        meta.className = "keyword-source-meta";
        const roots = Array.isArray(item.source_roots) && item.source_roots.length
          ? item.source_roots.join("、")
          : "-";
        meta.textContent = `检测词：${roots} · 已归类 ${valueText(item.term_count)} 个词`;
        row.append(title, meta);
        productList.appendChild(row);
      }
    }

    async function refreshKeywordPool() {
      try {
        const response = await fetch(API_ROUTES.keywordPool);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        renderKeywordPool(await response.json());
      } catch (_error) {
        renderKeywordPool({
          total_terms: 0,
          source_product_count: 0,
          categories: [],
          source_products: []
        });
      }
    }

    function keywordLayerText(value) {
      return value === "core" ? "重点候选" : "探索候选";
    }

    function keywordReviewText(value) {
      return value === "pending_review" ? "待审核" : valueText(value);
    }

    function joinedValues(values, prefix = "") {
      const items = Array.isArray(values)
        ? values.filter((value) => value !== null && value !== undefined && value !== "")
        : [];
      if (!items.length) return "-";
      return `${prefix}${items.map((value) => String(value)).join("、")}`;
    }

    function makeSuggestionGroup(labelText, value) {
      const wrap = document.createElement("div");
      const label = document.createElement("span");
      label.className = "suggestion-label";
      label.textContent = labelText;
      const content = document.createElement("div");
      content.className = "suggestion-value";
      content.textContent = valueText(value);
      wrap.append(label, content);
      return wrap;
    }

    function renderKeywordSuggestions(data) {
      const sourceStats = data?.source_stats || {};
      const candidates = Array.isArray(data?.candidates) ? data.candidates : [];
      $("keywordSuggestionMeta").textContent = `待审核 ${candidates.length}`;

      const scope = data?.scope || {};
      const scopeIsReadOnly = scope.production_queue_write === false
        && scope.keyword_config_write === false
        && scope.auto_approval === false
        && scope.search_trigger === false
        && scope.human_review_required === true;
      $("keywordReviewMode").textContent = scopeIsReadOnly ? "等待审核" : "暂不可用";

      const backendWarnings = Array.isArray(data?.warnings) ? data.warnings.filter(Boolean) : [];
      const warnings = backendWarnings.length ? ["部分关键词数据暂未就绪"] : [];
      const rowCaps = sourceStats.source_rows_truncated || {};
      const sourceTruncated = Object.entries(rowCaps)
        .filter((entry) => numericValue(entry[1], 0) > 0)
        .map((entry) => `${entry[0]} ${entry[1]}`);
      if (!scopeIsReadOnly) warnings.unshift("关键词建议暂不可用，请稍后刷新");
      if (sourceTruncated.length) warnings.push("部分关键词尚未整理完成");
      const warning = $("keywordSuggestionWarning");
      warning.hidden = warnings.length === 0;
      warning.textContent = warnings.join("；");

      const list = $("keywordSuggestionList");
      list.replaceChildren();
      if (!candidates.length) {
        const empty = document.createElement("li");
        empty.className = "suggestion-empty";
        empty.textContent = warnings.length
          ? "当前没有可供审核的衍生关键词，请先核对上方提示。"
          : "当前没有待审核的衍生关键词。";
        list.appendChild(empty);
        return;
      }

      for (const item of candidates) {
        const row = document.createElement("li");
        row.className = "suggestion-item";

        const main = document.createElement("div");
        main.className = "suggestion-main";
        const keyword = document.createElement("div");
        keyword.className = "suggestion-keyword";
        keyword.textContent = valueText(item.keyword);
        keyword.title = valueText(item.normalized);
        const badges = document.createElement("div");
        badges.className = "suggestion-badges";
        const layer = document.createElement("span");
        const suggestedLayer = item.suggested_layer === "core" ? "core" : "explore";
        layer.className = `layer-badge ${suggestedLayer}`;
        layer.textContent = keywordLayerText(suggestedLayer);
        const review = document.createElement("span");
        review.className = "review-status";
        review.textContent = keywordReviewText(item.review_status);
        badges.append(layer, review);
        main.append(keyword, badges);

        row.append(main);
        list.appendChild(row);
      }
    }

    async function refreshKeywordSuggestions() {
      try {
        const response = await fetch(API_ROUTES.keywordSuggestions);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        renderKeywordSuggestions(await response.json());
      } catch (error) {
        renderKeywordSuggestions({
          scope: {},
          stats: {},
          source_stats: {},
          warnings: [`读取衍生关键词失败：${error.message}`],
          candidates: []
        });
      }
    }

    function keywordApprovalManifestStatusText(value) {
      return ({
        current: "current · 清单当前有效",
        missing: "missing · 清单缺失",
        invalid: "invalid · 坏 JSON、损坏或篡改",
        out_of_bounds: "out_of_bounds · 清单语义或策略越界",
        unavailable: "unavailable · 只读证据不可用",
        expired: "expired · 清单已过期",
        stale: "stale · 建议或证据已漂移"
      })[value] || `${valueText(value)} · 未知状态`;
    }

    function keywordApprovalReviewStatusText(value) {
      return ({
        current: "current · 可供人工复核",
        fail_closed: "fail_closed · 审批失效"
      })[value] || `${valueText(value)} · fail closed`;
    }

    function makeKeywordApprovalCheck(label, value) {
      const row = document.createElement("li");
      row.className = "remediation-item";
      const head = document.createElement("div");
      head.className = "remediation-item-head";
      const title = document.createElement("strong");
      title.textContent = label;
      const badge = document.createElement("span");
      const passed = value === true;
      badge.className = `stage-badge ${passed ? "" : "isolated"}`.trim();
      badge.textContent = passed ? "true · 通过" : value === false ? "false · 阻塞" : "unknown · 阻塞";
      head.append(title, badge);
      row.appendChild(head);
      return row;
    }

    function renderKeywordApprovalManifest(data) {
      const manifestStatus = valueText(data?.manifest_status);
      const reviewStatus = valueText(data?.review_status);
      const validation = data?.validation || {};
      const storedStats = data?.stored_stats || {};
      const currentStats = data?.current_stats || {};
      const entries = Array.isArray(data?.entries) ? data.entries : [];
      const warnings = Array.isArray(data?.warnings) ? data.warnings.filter(Boolean) : [];
      const scope = data?.scope || {};
      const authorization = data?.authorization || {};
      const boundaryConfirmed = scope.manifest_access === "read_only"
        && scope.human_review_only === true
        && scope.approval_write === false
        && scope.approval_endpoint === false
        && scope.writes_queue === false
        && scope.search_execution === false
        && scope.monitor_authorization === false
        && scope.soak_authorization === false
        && authorization.writes_queue === false
        && authorization.search_execution === false
        && authorization.monitor_authorization === false
        && authorization.soak_authorization === false
        && authorization.human_confirmation_required === true;
      const fullyValidated = data?.is_current === true
        && manifestStatus === "current"
        && reviewStatus === "current"
        && validation.integrity_valid === true
        && validation.semantic_valid === true
        && validation.policy_within_bounds === true
        && validation.suggestion_set_hash_matches === true
        && validation.evidence_hashes_match === true
        && validation.layers_match === true
        && validation.statuses_valid === true
        && validation.counts_match === true
        && boundaryConfirmed;

      const panel = $("keywordApprovalManifestPanel");
      panel.classList.remove("current", "missing");
      if (fullyValidated) panel.classList.add("current");
      if (manifestStatus === "missing") panel.classList.add("missing");
      $("keywordApprovalManifestStatus").textContent =
        keywordApprovalManifestStatusText(manifestStatus);
      $("keywordApprovalReviewStatus").textContent =
        keywordApprovalReviewStatusText(reviewStatus);
      $("keywordApprovalLayerCounts").textContent =
        `${valueText(storedStats.core)} / ${valueText(storedStats.exploration)}`;
      $("keywordApprovalApprovedCount").textContent = valueText(storedStats.approved);
      $("keywordApprovalRejectedCount").textContent = valueText(storedStats.rejected);
      $("keywordApprovalPendingCount").textContent = valueText(storedStats.pending);
      $("keywordApprovalManifestMeta").textContent = data?.manifest_present === true
        ? `共 ${valueText(storedStats.total)} 条 · 年龄 ${valueText(data?.manifest_age_seconds)} 秒`
        : "固定路径清单未提供";
      $("keywordApprovalBoundary").textContent = boundaryConfirmed
        ? "writes_queue=false · search_execution=false"
        : "授权字段缺失或越界 · fail closed";

      const blockers = [];
      if (manifestStatus === "missing") blockers.push("审批清单缺失");
      if (manifestStatus === "invalid") blockers.push("坏 JSON、清单损坏或篡改");
      if (manifestStatus === "out_of_bounds") blockers.push("清单语义或策略越界");
      if (manifestStatus === "unavailable") blockers.push("当前只读证据不可用");
      if (manifestStatus === "expired") blockers.push("审批清单已过期");
      if (validation.suggestion_set_hash_matches === false) blockers.push("建议集合漂移");
      if (validation.evidence_hashes_match === false) blockers.push("证据漂移");
      if (validation.layers_match === false) blockers.push("core / exploration 层级漂移");
      if (validation.statuses_valid === false) blockers.push("审批状态异常");
      if (validation.counts_match === false) blockers.push("统计数量漂移");
      if (!boundaryConfirmed) blockers.push("所有授权 false 未完整确认");
      const blockingState = $("keywordApprovalBlockingState");
      blockingState.hidden = false;
      blockingState.textContent = blockers.length
        ? `阻塞态：${blockers.join("；")}。只供人工复核，不写队列、不执行真实搜索。`
        : "清单与当前建议及证据一致；仍只供人工复核，不写队列、不执行真实搜索。";

      const validationList = $("keywordApprovalValidationList");
      validationList.replaceChildren();
      [
        ["integrity_valid", validation.integrity_valid],
        ["semantic_valid", validation.semantic_valid],
        ["policy_within_bounds", validation.policy_within_bounds],
        ["suggestion_set_hash_matches", validation.suggestion_set_hash_matches],
        ["evidence_hashes_match", validation.evidence_hashes_match],
        ["layers_match", validation.layers_match],
        ["statuses_valid", validation.statuses_valid],
        ["counts_match", validation.counts_match]
      ].forEach(([label, value]) => {
        validationList.appendChild(makeKeywordApprovalCheck(label, value));
      });

      const issues = [];
      if (Array.isArray(validation.unknown_candidate_ids)
          && validation.unknown_candidate_ids.length) {
        issues.push(`unknown_candidate_ids：${validation.unknown_candidate_ids.join("、")}`);
      }
      if (storedStats.total !== undefined && currentStats.total !== undefined
          && storedStats.total !== currentStats.total) {
        issues.push(
          `stored_stats.total=${valueText(storedStats.total)}，current_stats.total=${valueText(currentStats.total)}`
        );
      }
      warnings.forEach((warning) => issues.push(`warning：${warning}`));
      appendSoakListItems(
        $("keywordApprovalIssueList"),
        issues,
        fullyValidated ? "无 issues / warnings；仍不构成执行授权。" : "未返回具体原因；按 fail closed 处理。"
      );

      const entryList = $("keywordApprovalEntryList");
      entryList.replaceChildren();
      if (!entries.length) {
        const empty = document.createElement("li");
        empty.className = "suggestion-empty";
        empty.textContent = blockers.length
          ? "没有可展示的有效审批明细；请人工检查清单与只读证据。"
          : "审批清单当前没有候选条目。";
        entryList.appendChild(empty);
        return;
      }
      for (const item of entries) {
        const row = document.createElement("li");
        row.className = "suggestion-item";
        const main = document.createElement("div");
        main.className = "suggestion-main";
        const keyword = document.createElement("div");
        keyword.className = "suggestion-keyword";
        keyword.textContent = valueText(item.keyword);
        keyword.title = valueText(item.normalized);
        const badges = document.createElement("div");
        badges.className = "suggestion-badges";
        const layer = document.createElement("span");
        layer.className = `layer-badge ${item.layer === "core" ? "core" : "explore"}`;
        layer.textContent = item.layer === "core" ? "core" : "exploration";
        const status = document.createElement("span");
        const entryStatus = ["approved", "rejected", "pending"].includes(item.status)
          ? item.status : "pending";
        status.className = `stage-badge keyword-approval-entry-status ${entryStatus}`;
        status.textContent = valueText(item.status);
        badges.append(layer, status);
        main.append(keyword, badges);

        const decision = document.createElement("div");
        decision.className = "suggestion-support";
        decision.append(
          makeSuggestionGroup("人工复核理由", valueText(item.reason)),
          makeSuggestionGroup(
            "approval_valid",
            item.approval_valid === true && fullyValidated
              ? "true · 仅记录有效，不授权执行"
              : "false · 不具备执行授权"
          ),
          makeSuggestionGroup("candidate_id", valueText(item.candidate_id))
        );

        const source = item.source_summary || {};
        const evidence = document.createElement("div");
        evidence.className = "suggestion-sources";
        evidence.append(
          makeSuggestionGroup(
            "来源 / 支持",
            `${valueText(source.evidence_count)} 条 · ${valueText(source.support_score)} 分 · ${joinedValues(source.source_types)}`
          ),
          makeSuggestionGroup("来源商品", joinedValues(source.source_products, "商品 ")),
          makeSuggestionGroup("来源关键词", joinedValues(source.source_keywords)),
          makeSuggestionGroup("evidence_hash", valueText(item.evidence_hash))
        );
        row.append(main, decision, evidence);
        entryList.appendChild(row);
      }
    }

    async function refreshKeywordApprovalManifest() {
      try {
        const response = await fetch(API_ROUTES.keywordApprovalManifest);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        renderKeywordApprovalManifest(await response.json());
      } catch (error) {
        renderKeywordApprovalManifest({
          manifest_status: "unavailable",
          review_status: "fail_closed",
          manifest_present: false,
          is_current: false,
          is_expired: null,
          manifest_age_seconds: null,
          validation: {},
          stored_stats: null,
          current_stats: null,
          entries: [],
          scope: {
            manifest_access: "read_only",
            human_review_only: true,
            approval_write: false,
            approval_endpoint: false,
            writes_queue: false,
            search_execution: false,
            monitor_authorization: false,
            soak_authorization: false
          },
          authorization: {
            writes_queue: false,
            search_execution: false,
            monitor_authorization: false,
            soak_authorization: false,
            human_confirmation_required: true
          },
          warnings: [`读取关键词审批清单失败：${error.message}`]
        });
      }
    }

    function keywordCombinationStageText(value) {
      return ({
        not_ready: "数据门槛未达到",
        sample: "可生成小样候选",
        stable: "已进入稳定统计"
      })[value] || "状态未知，按未就绪处理";
    }

    function renderKeywordCombinationReview(data) {
      const scope = data?.scope || {};
      const gates = data?.gates || {};
      const candidates = Array.isArray(data?.candidates) ? data.candidates : [];
      const warnings = Array.isArray(data?.warnings) ? data.warnings.filter(Boolean) : [];
      const boundaryConfirmed = scope.database_access === "sqlite_mode_ro_query_only"
        && scope.production_queue_write === false
        && scope.approval_write === false
        && scope.approval_endpoint === false
        && scope.writes_queue === false
        && scope.search_trigger === false
        && scope.search_execution === false
        && scope.monitor_authorization === false
        && scope.soak_authorization === false
        && scope.human_review_required === true;

      $("keywordCombinationStage").textContent =
        keywordCombinationStageText(data?.generation_stage);
      $("keywordCombinationProducts").textContent = valueText(data?.product_count);
      $("keywordCombinationRoots").textContent = valueText(data?.root_count);
      $("keywordCombinationCoverage").textContent =
        valueText(data?.domain_scene_count);
      $("keywordCombinationCandidates").textContent =
        valueText(data?.candidate_count);
      $("keywordCombinationContexts").textContent = valueText(data?.context_count);
      $("keywordCombinationReviewMeta").textContent =
        data?.truncated === true
          ? `展示 ${valueText(data?.returned_count)} / ${valueText(data?.candidate_count)} 条`
          : `共 ${valueText(data?.candidate_count)} 条`;
      $("keywordCombinationBoundary").textContent = boundaryConfirmed
        ? "只读 · 待人工审核"
        : "授权边界不完整 · 停止使用";

      const missing = [];
      if (gates.all_records_traceable !== true) missing.push("商品证据链不完整");
      if (gates.small_products !== true) missing.push("有效商品不足 30 个");
      if (gates.small_roots !== true) missing.push("发现根词不足 10 个");
      if (gates.small_domain_or_scene !== true) missing.push("领域或场景不足 3 个");
      if (!boundaryConfirmed) missing.push("只读授权边界未完整确认");
      warnings.forEach((warning) => missing.push(`读取异常：${warning}`));
      $("keywordCombinationWarning").textContent = missing.length
        ? `${missing.join("；")}。当前只积累证据，不生成或执行搜索词。`
        : "已达到小样门槛；候选仍需人工审核，不写队列、不执行搜索。";

      const list = $("keywordCombinationList");
      list.replaceChildren();
      if (!candidates.length) {
        const empty = document.createElement("li");
        empty.className = "suggestion-empty";
        empty.textContent = "当前没有可审核组合；继续积累真实商品与搜索证据。";
        list.appendChild(empty);
        return;
      }
      for (const item of candidates) {
        const row = document.createElement("li");
        row.className = "suggestion-item";
        const main = document.createElement("div");
        main.className = "suggestion-main";
        const keyword = document.createElement("div");
        keyword.className = "suggestion-keyword";
        keyword.textContent = valueText(item.phrase);
        const badges = document.createElement("div");
        badges.className = "suggestion-badges";
        const stage = document.createElement("span");
        stage.className = "stage-badge";
        stage.textContent = item.candidate_stage === "stable"
          ? "多商品稳定支持"
          : "小样候选";
        const review = document.createElement("span");
        review.className = "stage-badge keyword-approval-entry-status pending";
        review.textContent = "待人工审核";
        badges.append(stage, review);
        main.append(keyword, badges);

        const support = document.createElement("div");
        support.className = "suggestion-support";
        support.append(
          makeSuggestionGroup("真实商品支持", `${valueText(item.product_count)} 个`),
          makeSuggestionGroup("来源根词", `${valueText(item.root_count)} 个`),
          makeSuggestionGroup("不同店铺", `${valueText(item.shop_count)} 个`),
          makeSuggestionGroup("独立搜索上下文", `${valueText(item.context_count)} 个`)
        );
        row.append(main, support);
        list.appendChild(row);
      }
    }

    async function refreshKeywordCombinationReview() {
      try {
        const response = await fetch(API_ROUTES.keywordCombinationReview);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        renderKeywordCombinationReview(await response.json());
      } catch (error) {
        renderKeywordCombinationReview({
          generation_stage: "not_ready",
          product_count: 0,
          root_count: 0,
          domain_scene_count: 0,
          context_count: 0,
          candidate_count: 0,
          returned_count: 0,
          truncated: false,
          gates: {},
          candidates: [],
          scope: {
            database_access: "sqlite_mode_ro_query_only",
            production_queue_write: false,
            approval_write: false,
            approval_endpoint: false,
            writes_queue: false,
            search_trigger: false,
            search_execution: false,
            monitor_authorization: false,
            soak_authorization: false,
            human_review_required: true
          },
          warnings: [`${error.message}`]
        });
      }
    }

    function soakGateStatus(value) {
      return ({
        passed: ["passed · 通过", "passed"],
        failed: ["failed · 未通过", "failed"],
        insufficient_evidence: ["insufficient · 证据不足", "insufficient"],
        not_reached: ["not reached · 未到达", "not-reached"],
        eligible_for_evaluation: ["eligible · 可另行评估", "eligible"]
      })[value] || [valueText(value), "insufficient"];
    }

    function appendSoakListItems(list, items, emptyText) {
      list.replaceChildren();
      const values = Array.isArray(items) ? items.filter(Boolean) : [];
      if (!values.length) {
        const empty = document.createElement("li");
        empty.textContent = emptyText;
        list.appendChild(empty);
        return;
      }
      for (const value of values) {
        const row = document.createElement("li");
        row.textContent = String(value);
        list.appendChild(row);
      }
    }

    function ackReadinessView(data) {
      if (data?.ack_readiness && typeof data.ack_readiness === "object") {
        return { present: true, ...data.ack_readiness };
      }
      const summary = data?.summary;
      if (!summary || typeof summary !== "object"
          || !Object.keys(summary).some((key) => key.startsWith("ack_"))) {
        return { present: false };
      }
      const requiredIds = Array.isArray(summary.ack_required_alert_ids)
        ? summary.ack_required_alert_ids : [];
      return {
        present: true,
        required: requiredIds.length > 0,
        ready: summary.ack_ready,
        source: summary.ack_source,
        required_alert_ids: requiredIds,
        acknowledged_alert_ids: summary.acknowledged_alert_ids,
        missing_alert_ids: summary.ack_missing_alert_ids,
        unresolved_alert_ids: summary.ack_unresolved_alert_ids,
        latest_decisions: summary.ack_latest_decisions,
        integrity_error: summary.ack_integrity_error,
        evidence_mismatches: summary.ack_evidence_mismatches
      };
    }

    function schedulerEvidenceView(data) {
      const direct = data?.scheduler_evidence;
      if (direct && typeof direct === "object") return { present: true, ...direct };
      const recorded = data?.record?.scheduler_evidence;
      if (recorded && typeof recorded === "object") return { present: true, ...recorded };
      const summary = data?.summary;
      if (!summary || typeof summary !== "object"
          || !Object.keys(summary).some((key) => key.startsWith("scheduler_evidence_"))) {
        return { present: false, stages: {} };
      }
      return {
        present: true,
        source: summary.scheduler_evidence_source,
        ledger_integrity_ok: summary.scheduler_evidence_integrity_ok,
        integrity_error: summary.scheduler_evidence_integrity_error,
        stages: summary.scheduler_evidence_stages || {}
      };
    }

    function baselineReadinessView(data) {
      const recorded = data?.record?.baseline;
      if (recorded && typeof recorded === "object") {
        return { present: true, ...recorded };
      }
      const summaryBaseline = data?.summary?.baseline;
      if (summaryBaseline && typeof summaryBaseline === "object") {
        return { present: true, ...summaryBaseline };
      }
      return {
        present: false,
        status: "insufficient_evidence",
        source: "not_provided",
        integrity_ok: false,
        gaps: ["接口未返回 record.baseline；真实 baseline 尚未核对。"],
        warnings: ["baseline 字段缺失，工作台按 fail closed 处理。"]
      };
    }

    function baselineReasonFlags(baseline) {
      const reasons = [
        ...(Array.isArray(baseline?.gaps) ? baseline.gaps : []),
        ...(Array.isArray(baseline?.warnings) ? baseline.warnings : [])
      ].filter(Boolean).map(String);
      const joined = reasons.join(" ").toLowerCase();
      return {
        reasons,
        missing: !baseline?.present || baseline?.source === "not_provided"
          || joined.includes("缺少") || joined.includes("missing")
          || joined.includes("not found") || joined.includes("does not exist")
          || joined.includes("不存在"),
        badManifest: baseline?.integrity_ok !== true
          && (joined.includes("清单") || joined.includes("manifest") || joined.includes("json")
            || joined.includes("hash") || joined.includes("损坏") || joined.includes("篡改")),
        fileDrift: joined.includes("文件漂移") || joined.includes("file drift")
          || joined.includes("changed since baseline") || joined.includes("file hash")
          || joined.includes("文件哈希"),
      };
    }

    function baselineRequirementLine(label, baseline, ready, patterns) {
      const reasons = [
        ...(Array.isArray(baseline?.gaps) ? baseline.gaps : []),
        ...(Array.isArray(baseline?.warnings) ? baseline.warnings : [])
      ].filter(Boolean).map(String);
      const matched = reasons.filter((reason) => {
        const lower = reason.toLowerCase();
        return patterns.some((pattern) => lower.includes(pattern));
      });
      if (ready) return `${label}：已由固定清单完整性复核`;
      if (matched.length) return `${label}：缺口 · ${matched.join("；")}`;
      return `${label}：未能独立确认，随 baseline 阻塞`;
    }

    function renderBaselineReadiness(data) {
      const baseline = baselineReadinessView(data);
      const flags = baselineReasonFlags(baseline);
      const identifiersPresent = typeof baseline.baseline_id === "string"
        && baseline.baseline_id.trim().length > 0
        && typeof baseline.manifest_hash === "string"
        && baseline.manifest_hash.trim().length > 0;
      const authorizationClosed = baseline.pre_soak_start_authorized === false
        && baseline.soak_24h_start_authorized === false
        && baseline.scheduler_start_authorized === false
        && baseline.authorizes_start === false;
      const ready = baseline.present
        && baseline.status === "passed"
        && ["path", "manifest"].includes(baseline.source)
        && baseline.integrity_ok === true
        && baseline.files_reverified === true
        && identifiersPresent
        && authorizationClosed;

      const panel = $("baselineEvidencePanel");
      panel.classList.toggle("ready", ready);
      const state = $("baselineEvidenceState");
      state.className = `soak-evidence-state ${ready ? "ready" : "blocked"}`;
      state.textContent = ready
        ? "passed · 清单与文件已复核"
        : flags.missing
          ? "missing · 不具备准入"
          : flags.fileDrift
            ? "file drift · 不具备准入"
            : flags.badManifest
              ? "invalid · 不具备准入"
              : "blocked · 字段不足";
      $("baselineStatus").textContent = valueText(baseline.status);
      $("baselineSource").textContent = valueText(baseline.source);
      $("baselineIntegrity").textContent = baseline.integrity_ok === true
        ? "true · 已复核"
        : baseline.integrity_ok === false
          ? "false · 失败"
          : "unknown · fail closed";
      $("baselineId").textContent = valueText(baseline.baseline_id);
      $("baselineManifestHash").textContent = valueText(baseline.manifest_hash);
      $("baselineAuthorizationBoundary").textContent = authorizationClosed
        ? "authorizes_start=false"
        : "授权字段缺失或越界 · fail closed";

      appendSoakListItems(
        $("baselineFailureList"),
        [
          `真实 baseline：${flags.missing ? "未生成、缺失或未返回" : "已返回固定来源"}`,
          `清单完整性：${flags.badManifest ? "损坏、篡改或无法校验" : baseline.integrity_ok === true ? "通过" : "未知，阻塞"}`,
          `文件复核：${flags.fileDrift ? "发现漂移" : baseline.files_reverified === true ? "已重新校验" : "未确认，阻塞"}`
        ],
        "baseline 缺失，不能晋级。"
      );
      appendSoakListItems(
        $("baselineRequirementList"),
        [
          baselineRequirementLine("owner（8793 / 8765）", baseline, ready, ["owner", "8793", "8765"]),
          baselineRequirementLine("stop-entry", baseline, ready, ["stop_entry", "stop-entry", "停止入口"]),
          baselineRequirementLine("DB quick_check=ok", baseline, ready, ["quick_check", "database", "数据库"]),
          baselineRequirementLine("固定 1×1 参数", baseline, ready, ["1 keyword x 1 product", "max_keywords", "max_products_per_keyword", "1×1"]),
          baselineRequirementLine("interval_seconds", baseline, ready, ["interval_seconds"])
        ],
        "硬核对项未返回，不能晋级。"
      );
      appendSoakListItems(
        $("baselineGapList"),
        flags.reasons.length
          ? flags.reasons
          : ready
            ? ["无 baseline gaps；仍不构成启动授权。"]
            : ["baseline gaps/warnings 未返回；字段不足，按 fail closed 处理。"],
        "baseline gaps/warnings 未返回；字段不足，按 fail closed 处理。"
      );
    }

    function renderAckReadiness(data) {
      const ack = ackReadinessView(data);
      const state = $("soakAckState");
      if (!ack.present) {
        state.className = "soak-evidence-state blocked";
        state.textContent = "未返回 · 兼容空态";
        appendSoakListItems(
          $("soakAckList"),
          ["接口未返回 ack_readiness；ACK 准入尚未核对，不能据此晋级。"],
          "ACK 准入字段未返回。"
        );
        return;
      }

      const required = ack.required === true
        || (Array.isArray(ack.required_alert_ids) && ack.required_alert_ids.length > 0);
      const notRequired = !required && ack.source === "not_required";
      const ready = ack.ready === true && (required || notRequired);
      state.className = `soak-evidence-state ${ready ? "ready" : "blocked"}`;
      state.textContent = notRequired
        ? "not_required · 无需 ACK"
        : required && ready
          ? "required · ACK 完整"
          : required
            ? "required · 未 ACK"
            : "未核对 · 不能晋级";
      const latest = ack.latest_decisions && typeof ack.latest_decisions === "object"
        ? Object.entries(ack.latest_decisions).map(([id, decision]) => `${id}=${decision}`)
        : [];
      appendSoakListItems(
        $("soakAckList"),
        [
          `required：${joinedValues(ack.required_alert_ids)}`,
          `acknowledged：${joinedValues(ack.acknowledged_alert_ids)}`,
          `missing：${joinedValues(ack.missing_alert_ids)}`,
          `unresolved：${joinedValues(ack.unresolved_alert_ids)}`,
          `latest decisions：${latest.length ? latest.join("；") : "-"}`,
          `integrity：${ack.integrity_error ? `损坏 · ${ack.integrity_error}` : "未报告损坏"}`,
          `evidence mismatch：${joinedValues(ack.evidence_mismatches)}`
        ],
        "ACK 准入字段未返回。"
      );
    }

    function schedulerReasonFlags(stage) {
      const reasons = [
        ...(Array.isArray(stage?.missing_reasons) ? stage.missing_reasons : []),
        ...(Array.isArray(stage?.failed_reasons) ? stage.failed_reasons : []),
        ...(Array.isArray(stage?.reasons) ? stage.reasons : [])
      ].filter(Boolean).map(String);
      const joined = reasons.join(" ").toLowerCase();
      return {
        reasons,
        simulated: Number(stage?.simulated_due_point_count || 0) > 0 || joined.includes("simulated") || joined.includes("模拟"),
        late: Number(stage?.max_start_delay_seconds || 0) > 900 || joined.includes("start delay") || joined.includes("延迟"),
        risk: Number(stage?.risk_count || 0) > 0 || Number(stage?.blocked_count || 0) > 0
          || joined.includes("risk") || joined.includes("blocked") || joined.includes("风险"),
        healthMismatch: stage?.t46_ready_for_gate_evaluation === false
          || joined.includes("health") || joined.includes("健康")
          || joined.includes("lease") || joined.includes("db evidence")
          || joined.includes("http evidence") || joined.includes("scheduler/thread")
      };
    }

    function renderSchedulerEvidence(data) {
      const evidence = schedulerEvidenceView(data);
      const state = $("schedulerEvidenceState");
      const stagesRoot = $("schedulerEvidenceStages");
      stagesRoot.replaceChildren();
      if (!evidence.present) {
        state.className = "soak-evidence-state blocked";
        state.textContent = "未返回 · 兼容空态";
        const empty = document.createElement("div");
        empty.className = "remediation-empty";
        empty.textContent = "接口未返回 scheduler evidence；G2/G4 到期点未核对，不能晋级。";
        stagesRoot.appendChild(empty);
        return;
      }

      const stages = evidence.stages && typeof evidence.stages === "object"
        ? evidence.stages : {};
      const allReady = ["G2", "G4"].every((name) => stages[name]?.ready === true);
      const integrityOk = evidence.ledger_integrity_ok === true;
      state.className = `soak-evidence-state ${allReady && integrityOk ? "ready" : "blocked"}`;
      state.textContent = allReady && integrityOk
        ? "evidence 完整"
        : evidence.integrity_error
          ? "integrity 损坏"
          : "evidence 未就绪";

      for (const gateName of ["G2", "G4"]) {
        const stage = stages[gateName] && typeof stages[gateName] === "object"
          ? stages[gateName] : {};
        const expected = Array.isArray(stage.expected_scheduled_at)
          ? stage.expected_scheduled_at.length : stage.expected_due_point_count;
        const recorded = Array.isArray(stage.recorded_scheduled_at)
          ? stage.recorded_scheduled_at.length : stage.recorded_due_point_count;
        const missing = Array.isArray(stage.missing_scheduled_at)
          ? stage.missing_scheduled_at.length
          : Array.isArray(stage.missing_due_point_ids)
            ? stage.missing_due_point_ids.length : null;
        const flags = schedulerReasonFlags(stage);
        const card = document.createElement("article");
        card.className = "soak-stage";
        const head = document.createElement("div");
        head.className = "soak-stage-head";
        const name = document.createElement("strong");
        name.textContent = gateName;
        const badge = document.createElement("span");
        badge.className = `soak-evidence-state ${stage.ready === true ? "ready" : "blocked"}`;
        badge.textContent = stage.ready === true ? "ready" : "不能晋级";
        head.append(name, badge);
        const lines = document.createElement("div");
        lines.className = "soak-stage-lines";
        for (const value of [
          `expected points：${valueText(expected)}`,
          `expected scheduled_at：${joinedValues(stage.expected_scheduled_at)}`,
          `recorded points：${valueText(recorded)}；missing：${valueText(missing)}`,
          `missing scheduled_at：${joinedValues(stage.missing_scheduled_at || stage.missing_due_point_ids)}`,
          `simulated：${flags.simulated ? "有，不能计入" : "未发现"}；count=${valueText(stage.simulated_due_point_count)}`,
          `late：${flags.late ? "有，不能晋级" : "未发现"}；max delay=${valueText(stage.max_start_delay_seconds)}`,
          `risk：${flags.risk ? "有，不能晋级" : "未发现"}；risk/block=${valueText(stage.risk_count)}/${valueText(stage.blocked_count)}`,
          `health mismatch：${flags.healthMismatch ? "有，不能晋级" : "未发现"}`,
          `完整性：${evidence.integrity_error || valueText(evidence.ledger_integrity_ok)}`,
          `原因：${flags.reasons.length ? flags.reasons.join("；") : "接口未提供"}`
        ]) {
          const line = document.createElement("div");
          line.textContent = value;
          lines.appendChild(line);
        }
        card.append(head, lines);
        stagesRoot.appendChild(card);
      }
    }

    function renderSoakReadiness(data) {
      const gates = data?.gates || {};
      const gaps = Array.isArray(data?.gaps) ? data.gaps : [];
      const warnings = Array.isArray(data?.warnings) ? data.warnings.filter(Boolean) : [];
      const scope = data?.evidence_scope || {};
      const authorization = data?.authorization || {};
      const startAuthorized = data?.soak_start_authorized;
      const boundaryConfirmed = startAuthorized === false
        && authorization.soak_start_authorized === false
        && authorization.expansion_authorized === false;
      const scopeIsReadOnly = scope.database_access === "sqlite_mode_ro_query_only"
        && scope.database_write === false
        && scope.monitor_trigger === false
        && scope.soak_trigger === false;

      $("preSoakReadiness").textContent =
        data?.ready_for_pre_soak === true ? "ready · 证据门槛通过" : "insufficient · 尚不具备";
      $("fullSoakReadiness").textContent =
        data?.ready_for_24h_soak === true ? "ready · 证据门槛通过" : "insufficient · 尚不具备";
      $("soakRoundsRead").textContent = valueText(scope.rounds_read);
      const firstEvidence = shortDate(scope.first_evidence_at);
      const lastEvidence = shortDate(scope.last_evidence_at);
      $("soakEvidenceRange").textContent =
        firstEvidence === "-" && lastEvidence === "-" ? "-" : `${firstEvidence} → ${lastEvidence}`;
      $("soakReadinessMeta").textContent =
        data?.generated_at ? `生成 ${shortDate(data.generated_at)}` : "证据不可用";
      $("soakAuthorizationState").textContent =
        boundaryConfirmed ? "soak_start_authorized=false" : "授权边界待核对";

      const boundaryWarnings = [];
      if (!boundaryConfirmed) boundaryWarnings.push("接口未明确返回 soak_start_authorized=false");
      if (!scopeIsReadOnly) boundaryWarnings.push("接口只读证据范围未得到完整确认");
      const warningBanner = $("soakReadinessWarning");
      warningBanner.hidden = boundaryWarnings.length === 0 && warnings.length === 0;
      warningBanner.textContent = [...boundaryWarnings, ...warnings].join("；");

      const gateList = $("soakGateList");
      gateList.replaceChildren();
      for (const gateName of SOAK_GATE_NAMES) {
        const gate = gates[gateName] || {};
        const [statusText, statusClass] = soakGateStatus(gate.status);
        const reasons = Array.isArray(gate.reasons) ? gate.reasons.filter(Boolean) : [];
        const row = document.createElement("li");
        row.className = "soak-gate";
        const head = document.createElement("div");
        head.className = "soak-gate-head";
        const name = document.createElement("strong");
        name.textContent = gateName;
        const status = document.createElement("span");
        status.className = `gate-status ${statusClass}`;
        status.textContent = statusText;
        const reason = document.createElement("div");
        reason.className = "soak-gate-reason";
        reason.textContent = reasons.length ? reasons.join("；") : "接口未提供原因";
        head.append(name, status);
        row.append(head, reason);
        gateList.appendChild(row);
      }

      appendSoakListItems(
        $("soakGapList"),
        gaps.slice(0, 7).map((gap) => {
          const reasons = Array.isArray(gap.reasons) ? gap.reasons.filter(Boolean) : [];
          return `${valueText(gap.gate)} · ${valueText(gap.status)}：${reasons.length ? reasons.join("；") : "未提供原因"}`;
        }),
        "当前没有未通过门槛；这仍不代表已授权启动或扩容。"
      );
      appendSoakListItems($("soakWarningList"), warnings, "当前接口未返回 warnings。");
      appendSoakListItems(
        $("soakEvidenceScopeList"),
        [
          `读取模式：${valueText(scope.database_access)}`,
          `证据来源：${valueText(scope.source)}`,
          `涉及表：${joinedValues(scope.tables)}`,
          `轮次：${valueText(scope.rounds_read)}；坏 JSON：${valueText(scope.malformed_json_count)}`,
          `数据库写入：${valueText(scope.database_write)}；监控触发：${valueText(scope.monitor_trigger)}；soak 触发：${valueText(scope.soak_trigger)}`,
          `授权声明：${valueText(authorization.statement)}`
        ],
        "接口未提供证据范围。"
      );
      renderAckReadiness(data);
      renderSchedulerEvidence(data);
      renderBaselineReadiness(data);
    }

    async function refreshSoakReadiness() {
      try {
        const response = await fetch(API_ROUTES.soakReadiness);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        renderSoakReadiness(await response.json());
      } catch (error) {
        renderSoakReadiness({
          generated_at: null,
          gates: {},
          gaps: [{
            gate: "EVIDENCE_INTEGRITY",
            status: "failed",
            reasons: [`读取 soak 准入证据失败：${error.message}`]
          }],
          warnings: [`读取 soak 准入证据失败：${error.message}`],
          evidence_scope: {},
          ready_for_pre_soak: false,
          ready_for_24h_soak: false,
          soak_start_authorized: false,
          authorization: {
            soak_start_authorized: false,
            expansion_authorized: false,
            statement: "接口读取失败，不授权启动或扩容。"
          }
        });
      }
    }

    function remediationStageText(value) {
      return ({
        identity: "身份与链接",
        metrics: "指标条",
        note: "规范笔记",
        profile: "作者主页"
      })[value] || valueText(value);
    }

    function makeRemediationDetail(label, value) {
      const line = document.createElement("div");
      line.className = "remediation-detail";
      line.textContent = `${label}：${valueText(value)}`;
      return line;
    }

    function appendRemediationEmpty(list, message) {
      const empty = document.createElement("li");
      empty.className = "remediation-empty";
      empty.textContent = message;
      list.appendChild(empty);
    }

    function renderRemediationPlan(data) {
      const batches = Array.isArray(data?.batches) ? data.batches : [];
      const isolated = Array.isArray(data?.isolated) ? data.isolated : [];
      const skipped = Array.isArray(data?.skipped) ? data.skipped : [];
      const dependencies = Array.isArray(data?.blocking_dependencies)
        ? data.blocking_dependencies
        : [];
      const budget = data?.budget || {};
      const nextBatch = data?.next_batch || null;
      $("remediationEarliestStage").textContent =
        remediationStageText(data?.earliest_executable_stage);
      $("remediationBatchCount").textContent = valueText(batches.length);
      $("remediationIsolatedCount").textContent = valueText(isolated.length);
      $("remediationVisitCount").textContent = valueText(budget.planned_product_visits);
      $("remediationBudget").textContent =
        `${valueText(budget.per_batch_limit)} / ${valueText(budget.hourly_visit_limit)}`;
      $("remediationCooldown").textContent = valueText(budget.product_cooldown_hours);
      $("remediationPlanMeta").textContent = nextBatch
        ? `下一批 ${valueText(nextBatch.batch_id)} · ${valueText(budget.next_batch_items)} 项`
        : "当前无可执行批次";

      const scope = data?.scope || {};
      const scopeIsReadOnly = scope.database_access === "read_only"
        && scope.production_queue_write === false
        && scope.collection_trigger === false
        && scope.approval_write === false
        && scope.execution_endpoint === false
        && scope.human_review_required === true;
      $("remediationScopeMode").textContent = scopeIsReadOnly ? "只读计划" : "边界状态待核对";

      const warnings = Array.isArray(data?.warnings) ? data.warnings.filter(Boolean) : [];
      if (!scopeIsReadOnly) warnings.unshift("接口只读边界未得到完整确认");
      const warning = $("remediationWarning");
      warning.hidden = warnings.length === 0;
      warning.textContent = warnings.join("；");

      const batchList = $("remediationBatchList");
      batchList.replaceChildren();
      if (!batches.length) {
        appendRemediationEmpty(
          batchList,
          warnings.length ? "补证计划当前不可用，请先核对上方提示。" : "当前没有待执行的补证批次。"
        );
      }
      for (const batch of batches) {
        const items = Array.isArray(batch.items) ? batch.items : [];
        const row = document.createElement("li");
        row.className = "remediation-item";
        const head = document.createElement("div");
        head.className = "remediation-item-head";
        const title = document.createElement("strong");
        title.textContent = `${valueText(batch.batch_id)} · 第 ${valueText(batch.hour_window)} 小时窗`;
        const stage = document.createElement("span");
        stage.className = "stage-badge";
        stage.textContent = remediationStageText(batch.stage);
        head.append(title, stage);
        row.append(
          head,
          makeRemediationDetail(
            "商品",
            joinedValues(items.map((item) => `#${valueText(item.product_id)}`))
          ),
          makeRemediationDetail(
            "动作",
            joinedValues(items.flatMap(
              (item) => Array.isArray(item.actions) ? item.actions : []
            ))
          ),
          makeRemediationDetail("批次上限", batch.max_items)
        );
        batchList.appendChild(row);
      }

      const isolationList = $("remediationIsolationList");
      isolationList.replaceChildren();
      if (!isolated.length && !skipped.length) {
        appendRemediationEmpty(isolationList, "当前没有隔离或跳过商品。");
      }
      for (const item of isolated) {
        const row = document.createElement("li");
        row.className = "remediation-item";
        const head = document.createElement("div");
        head.className = "remediation-item-head";
        const title = document.createElement("strong");
        title.textContent = `商品 #${valueText(item.product_id)} · ${valueText(item.code)}`;
        const badge = document.createElement("span");
        badge.className = "stage-badge isolated";
        badge.textContent = "隔离";
        head.append(title, badge);
        row.append(
          head,
          makeRemediationDetail("原因", item.reason),
          makeRemediationDetail("阻塞于", joinedValues(item.blocked_by)),
          makeRemediationDetail("可重试时间", item.retry_at)
        );
        isolationList.appendChild(row);
      }
      for (const item of skipped) {
        const row = document.createElement("li");
        row.className = "remediation-item";
        const head = document.createElement("div");
        head.className = "remediation-item-head";
        const title = document.createElement("strong");
        title.textContent = `商品 #${valueText(item.product_id)} · ${valueText(item.code)}`;
        const badge = document.createElement("span");
        badge.className = "stage-badge skipped";
        badge.textContent = "跳过";
        head.append(title, badge);
        row.append(head, makeRemediationDetail("原因", item.reason));
        isolationList.appendChild(row);
      }

      const dependencyList = $("remediationDependencyList");
      dependencyList.replaceChildren();
      if (!dependencies.length) {
        appendRemediationEmpty(dependencyList, "当前没有额外依赖或阻塞。");
      }
      for (const item of dependencies) {
        const row = document.createElement("li");
        row.className = "remediation-item";
        const head = document.createElement("div");
        head.className = "remediation-item-head";
        const title = document.createElement("strong");
        title.textContent = `商品 #${valueText(item.product_id)}`;
        const category = document.createElement("span");
        category.className = `stage-badge${item.category === "isolated" ? " isolated" : ""}`;
        category.textContent = item.category === "isolated"
          ? "隔离依赖"
          : remediationStageText(item.category);
        head.append(title, category);
        row.append(head, makeRemediationDetail("阻塞项", joinedValues(item.blocked_by)));
        dependencyList.appendChild(row);
      }
    }

    async function refreshRemediationPlan() {
      try {
        const response = await fetch(API_ROUTES.remediationPlan);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        renderRemediationPlan(await response.json());
      } catch (error) {
        renderRemediationPlan({
          scope: {},
          earliest_executable_stage: null,
          next_batch: null,
          batches: [],
          isolated: [],
          skipped: [],
          blocking_dependencies: [],
          budget: {},
          warnings: [`读取补证计划失败：${error.message}`]
        });
      }
    }

    function approvalManifestStatusText(value) {
      return ({
        current: "current · 清单与当前计划一致",
        missing: "missing · 清单缺失",
        stale: "stale · 清单已过期",
        invalid: "invalid · 清单损坏或越界",
        unavailable: "unavailable · 当前无法校验"
      })[value] || `${valueText(value)} · 未知状态`;
    }

    function approvalReviewStatusText(value) {
      return ({
        planned_approved: "planned_approved · 仅计划获批",
        pending: "pending · 待复核",
        pending_review: "pending_review · 待复核",
        rejected: "rejected · 计划未通过"
      })[value] || valueText(value);
    }

    function makeApprovalCheck(title, detail, ok) {
      const row = document.createElement("li");
      row.className = "remediation-item";
      const head = document.createElement("div");
      head.className = "remediation-item-head";
      const label = document.createElement("strong");
      label.textContent = title;
      const badge = document.createElement("span");
      badge.className = `stage-badge ${ok ? "" : "isolated"}`.trim();
      badge.textContent = ok ? "已核对" : "阻塞 / 未知";
      head.append(label, badge);
      row.append(head, makeRemediationDetail("结果", detail));
      return row;
    }

    function renderApprovalManifest(data) {
      const manifestStatus = valueText(data?.manifest_status);
      const reviewStatus = valueText(data?.review_status);
      const planApprovalStatus = valueText(data?.plan_approval_status);
      const storedPlanStatus = valueText(data?.stored_plan_approval_status);
      const executionStatus = valueText(data?.execution_status);
      const validation = data?.validation || {};
      const scope = data?.scope || {};
      const approval = data?.approval && typeof data.approval === "object"
        ? data.approval : null;
      const policy = approval?.policy || {};
      const selectedBatches = Array.isArray(approval?.selected_batches)
        ? approval.selected_batches : [];
      const issues = Array.isArray(approval?.issues) ? approval.issues : [];
      const warnings = Array.isArray(data?.warnings) ? data.warnings.filter(Boolean) : [];
      const selectedProducts = selectedBatches.reduce(
        (count, batch) => count + (Array.isArray(batch.items) ? batch.items.length : 0),
        0
      );
      const sourcePlanCurrent = data?.is_current === true
        && validation.planner_hash_matches === true;
      const boundaryConfirmed = executionStatus === "not_executed"
        && data?.authorizes_execution === false
        && scope.manifest_access === "read_only"
        && scope.production_queue_write === false
        && scope.approval_write === false
        && scope.approval_endpoint === false
        && scope.execution_endpoint === false
        && scope.authorizes_execution === false;
      const integrityValid = validation.integrity_valid === true;
      const semanticValid = validation.semantic_valid === true;
      const quarantineIds = Array.isArray(policy.quarantine_product_ids)
        ? policy.quarantine_product_ids : [];
      const stoppedIds = Array.isArray(policy.low_follower_stop_product_ids)
        ? policy.low_follower_stop_product_ids : [];
      const budgetValid = Number(policy.per_batch_limit) <= 2
        && Number(policy.per_batch_limit) > 0
        && Number(policy.hourly_visit_limit) <= 6
        && Number(policy.hourly_visit_limit) > 0;
      const isolationValid = quarantineIds.includes(20)
        && stoppedIds.includes(19) && stoppedIds.includes(20);
      const isCurrent = manifestStatus === "current" && sourcePlanCurrent
        && integrityValid && semanticValid;

      const panel = $("approvalManifestPanel");
      panel.classList.remove("current", "blocked", "missing");
      panel.classList.add(
        isCurrent ? "current" : manifestStatus === "missing" ? "missing" : "blocked"
      );
      $("approvalManifestStatus").textContent = approvalManifestStatusText(manifestStatus);
      $("approvalReviewStatus").textContent = approvalReviewStatusText(reviewStatus);
      $("approvalSourcePlanCurrent").textContent = sourcePlanCurrent
        ? "source_plan_current=true"
        : "source_plan_current=false · 阻塞";
      $("approvalPlanStatus").textContent = approvalReviewStatusText(planApprovalStatus);
      $("approvalExecutionStatus").textContent = executionStatus === "not_executed"
        ? "not_executed · 未执行"
        : `${executionStatus} · 边界异常`;
      $("approvalSelectionCount").textContent =
        `${valueText(selectedBatches.length)} / ${valueText(selectedProducts)}`;
      $("approvalManifestMeta").textContent = approval
        ? `复核 ${shortDate(approval.reviewed_at)} · ${valueText(approval.reviewer)}`
        : manifestStatus === "missing"
          ? "固定路径清单不存在"
          : "清单不可用，审批状态已关闭";
      $("approvalExecutionBoundary").textContent = boundaryConfirmed
        ? "authorizes_execution=false · not_executed"
        : "只读 / 未执行边界异常 · 阻塞";

      const blockers = [];
      if (manifestStatus === "missing") blockers.push("清单缺失，不能视为已审批");
      if (manifestStatus === "stale") blockers.push("源计划已变化，旧审批清单过期");
      if (manifestStatus === "invalid") blockers.push("清单损坏、篡改或语义越界");
      if (manifestStatus === "unavailable") blockers.push("当前只读证据不足，无法校验清单");
      if (!sourcePlanCurrent) blockers.push("source_plan_current=false");
      if (!boundaryConfirmed) blockers.push("未确认 not_executed / authorizes_execution=false");
      if (issues.length) blockers.push(`清单 issues=${issues.length}`);
      const blockingState = $("approvalBlockingState");
      blockingState.hidden = false;
      blockingState.textContent = blockers.length
        ? `阻塞态：${blockers.join("；")}。审批清单不等于执行授权。`
        : reviewStatus === "planned_approved"
          ? "planned_approved 仅表示离线计划获批；当前仍是 not_executed，审批清单不等于执行授权。"
          : "清单当前但尚未 planned_approved；审批清单不等于执行授权。";

      const validationList = $("approvalValidationList");
      validationList.replaceChildren();
      validationList.append(
        makeApprovalCheck(
          "integrity_valid",
          valueText(validation.integrity_valid),
          integrityValid
        ),
        makeApprovalCheck(
          "semantic_valid",
          valueText(validation.semantic_valid),
          semanticValid
        ),
        makeApprovalCheck(
          "planner_hash_matches / source_plan_current",
          `${valueText(validation.planner_hash_matches)} / ${valueText(sourcePlanCurrent)}；source_plan_hash=${valueText(approval?.source_plan_hash)}；source_generated_at=${valueText(approval?.source_generated_at)}`,
          sourcePlanCurrent
        ),
        makeApprovalCheck(
          "只读且无执行授权",
          `database=${valueText(scope.database_access)}；queue_write=${valueText(scope.production_queue_write)}；approval_write=${valueText(scope.approval_write)}；execution_endpoint=${valueText(scope.execution_endpoint)}`,
          boundaryConfirmed
        )
      );

      const policyList = $("approvalPolicyList");
      policyList.replaceChildren();
      if (!approval) {
        appendRemediationEmpty(
          policyList,
          "清单缺失、过期或损坏时不推断预算与隔离校验；当前为阻塞态。"
        );
      } else {
        policyList.append(
          makeApprovalCheck(
            "批次 / 小时硬预算",
            `${valueText(policy.per_batch_limit)} / ${valueText(policy.hourly_visit_limit)}（上限 2 / 6）`,
            budgetValid
          ),
          makeApprovalCheck(
            "强制隔离",
            `quarantine=${joinedValues(quarantineIds)}`,
            isolationValid
          ),
          makeApprovalCheck(
            "低粉停止项",
            `note/profile stop=${joinedValues(stoppedIds)}`,
            isolationValid
          )
        );
      }

      const issueList = $("approvalIssueList");
      issueList.replaceChildren();
      const issueLines = issues.map(
        (issue) => `issue · ${valueText(issue.code)} · ${valueText(issue.path)}：${valueText(issue.message)}`
      );
      const warningLines = warnings.map((warning) => `warning · ${valueText(warning)}`);
      if (!issueLines.length && !warningLines.length) {
        appendRemediationEmpty(issueList, "当前没有 issues / warnings；这不构成执行授权。");
      } else {
        for (const line of [...issueLines, ...warningLines]) {
          const item = document.createElement("li");
          item.className = "remediation-item";
          item.appendChild(makeRemediationDetail("校验", line));
          issueList.appendChild(item);
        }
      }

      const batchList = $("approvalBatchList");
      batchList.replaceChildren();
      if (!selectedBatches.length) {
        appendRemediationEmpty(
          batchList,
          manifestStatus === "missing"
            ? "审批清单缺失，没有可展示的已选批次；不授权执行。"
            : "没有可展示的已选批次；不授权执行。"
        );
      }
      for (const batch of selectedBatches) {
        const items = Array.isArray(batch.items) ? batch.items : [];
        const row = document.createElement("li");
        row.className = "remediation-item";
        const head = document.createElement("div");
        head.className = "remediation-item-head";
        const title = document.createElement("strong");
        title.textContent = `${valueText(batch.batch_id)} · 第 ${valueText(batch.hour_window)} 小时窗`;
        const badge = document.createElement("span");
        badge.className = "stage-badge";
        badge.textContent = `${remediationStageText(batch.stage)} · not_executed`;
        head.append(title, badge);
        row.append(
          head,
          makeRemediationDetail(
            "商品",
            joinedValues(items.map((item) => `#${valueText(item.product_id)} ${valueText(item.status)}`))
          ),
          makeRemediationDetail(
            "动作",
            joinedValues(items.flatMap(
              (item) => Array.isArray(item.actions) ? item.actions : []
            ))
          ),
          makeRemediationDetail(
            "required_before / 依赖",
            joinedValues(items.flatMap(
              (item) => Array.isArray(item.required_before) ? item.required_before : []
            ))
          ),
          makeRemediationDetail("执行授权", "false · 审批清单不等于执行授权")
        );
        batchList.appendChild(row);
      }
    }

    async function refreshApprovalManifest() {
      try {
        const response = await fetch(API_ROUTES.approvalManifest);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        renderApprovalManifest(await response.json());
      } catch (error) {
        renderApprovalManifest({
          review_status: "pending",
          manifest_status: "unavailable",
          manifest_present: false,
          is_current: false,
          plan_approval_status: "pending_review",
          stored_plan_approval_status: null,
          execution_status: "not_executed",
          authorizes_execution: false,
          validation: {
            integrity_valid: false,
            semantic_valid: false,
            planner_hash_matches: null
          },
          approval: null,
          scope: {
            manifest_access: "read_only",
            production_queue_write: false,
            approval_write: false,
            approval_endpoint: false,
            execution_endpoint: false,
            authorizes_execution: false
          },
          warnings: [`读取补证审批清单失败：${error.message}`]
        });
      }
    }

    function closeMonitorDrilldown() {
      activeMonitorKind = null;
      $("monitorDrilldown").hidden = true;
      document.querySelectorAll("[data-monitor-kind]").forEach((button) => {
        button.classList.remove("active");
        button.setAttribute("aria-expanded", "false");
      });
    }

    function renderMonitorRecordDetail(item) {
      const container = $("monitorRecordDetail");
      container.replaceChildren();
      const title = document.createElement("h4");
      title.textContent = valueText(item?.title);
      container.appendChild(title);

      const fields = document.createElement("dl");
      fields.className = "monitor-field-list";
      for (const field of (Array.isArray(item?.fields) ? item.fields : [])) {
        const row = document.createElement("div");
        row.className = "monitor-field";
        const label = document.createElement("dt");
        label.textContent = valueText(field.label);
        const value = document.createElement("dd");
        value.textContent = valueText(field.value);
        row.append(label, value);
        fields.appendChild(row);
      }
      container.appendChild(fields);

      if (item?.detail_url) {
        const actions = document.createElement("div");
        actions.className = "monitor-detail-actions";
        const link = document.createElement("a");
        link.className = "button compact";
        link.href = item.detail_url;
        link.textContent = item.detail_label || "查看详情";
        actions.appendChild(link);
        container.appendChild(actions);
      }
    }

    function setMonitorPlaceholder(container, text, isError = false) {
      const placeholder = document.createElement("div");
      placeholder.className = isError ? "empty error" : "empty";
      placeholder.textContent = text;
      container.replaceChildren(placeholder);
    }

    function renderMonitorDrilldown(data) {
      const items = Array.isArray(data?.items) ? data.items : [];
      $("monitorDrilldownTitle").textContent =
        `${valueText(data?.label)} · 共 ${valueText(data?.count)} 条`;
      const list = $("monitorRecordList");
      list.replaceChildren();
      setMonitorPlaceholder($("monitorRecordDetail"), "点击左侧任意一条查看详情");
      if (!items.length) {
        setMonitorPlaceholder(list, "暂无记录");
        return;
      }
      for (const item of items) {
        const button = document.createElement("button");
        button.className = "monitor-record-button";
        button.type = "button";
        const title = document.createElement("span");
        title.className = "monitor-record-title";
        title.textContent = valueText(item.title);
        const subtitle = document.createElement("span");
        subtitle.className = "monitor-record-subtitle";
        subtitle.textContent = valueText(item.subtitle);
        button.append(title, subtitle);
        button.addEventListener("click", () => {
          list.querySelectorAll(".monitor-record-button").forEach((row) => {
            row.classList.toggle("active", row === button);
          });
          renderMonitorRecordDetail(item);
        });
        list.appendChild(button);
      }
    }

    async function openMonitorDrilldown(kind) {
      activeMonitorKind = kind;
      document.querySelectorAll("[data-monitor-kind]").forEach((button) => {
        const selected = button.dataset.monitorKind === kind;
        button.classList.toggle("active", selected);
        button.setAttribute("aria-expanded", selected ? "true" : "false");
      });
      $("monitorDrilldown").hidden = false;
      $("monitorDrilldownTitle").textContent = "明细读取中...";
      setMonitorPlaceholder($("monitorRecordList"), "读取中...");
      setMonitorPlaceholder($("monitorRecordDetail"), "点击左侧任意一条查看详情");
      try {
        const response = await fetch(
          `${API_ROUTES.monitorDetails}${encodeURIComponent(kind)}`
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        if (activeMonitorKind !== kind) return;
        renderMonitorDrilldown(await response.json());
      } catch (error) {
        if (activeMonitorKind !== kind) return;
        $("monitorDrilldownTitle").textContent = "明细暂时无法读取";
        const message = document.createElement("div");
        message.className = "empty error";
        message.textContent = error.message;
        $("monitorRecordList").replaceChildren(message);
      }
    }

    function renderStatus(data) {
      latestStatus = data;
      candidateItems = Array.isArray(data.recent) ? data.recent : [];
      const qualifiedCount = numericValue(data.qualified_candidates, 0);
      $("navCandidateCount").textContent = valueText(data.products);
      $("navPendingCount").textContent = valueText(data.pending_tasks);
      $("pendingTasks").textContent = valueText(data.pending_tasks);
      $("productCount").textContent = valueText(data.products);
      $("observationCount").textContent = valueText(data.observations);
      $("followedProductCount").textContent = valueText(data.followed_products);
      $("candidateCount").textContent = valueText(qualifiedCount);

      const monitor = data.monitor || {};
      const scheduler = data.scheduler || {};
      const hasRiskStop = Boolean(monitor.risk_stop_reason);
      const running = monitor.desired_state === "running" && scheduler.thread_alive;
      const stateText = hasRiskStop
        ? "风险停止"
        : (running ? "运行中" : (monitor.desired_state === "running" ? "启动中" : "已暂停"));
      const stateMode = hasRiskStop ? "risk" : (running ? "running" : "paused");
      setMonitorChip($("headerMonitorState"), stateText, stateMode);
      setMonitorChip($("monitorPageState"), stateText, stateMode);
      $("nextRunCompact").textContent = monitor.next_run_at ? shortDate(monitor.next_run_at) : "-";
      $("resumeButton").disabled = hasRiskStop;
      $("resumeButton").title = hasRiskStop ? "硬风控仍生效，不能使用普通恢复" : "";
      $("riskResumeButton").hidden = !hasRiskStop;
      $("riskResumeButton").disabled = !hasRiskStop;

      const reportPath = monitor.last_report_path;
      $("latestReport").textContent = valueText(reportPath);
      $("latestReport").title = valueText(reportPath);
      $("latestReportState").textContent = reportPath
        ? `已生成 · ${String(reportPath).split(/[\\/]/).pop()}`
        : "尚未生成候选报告";

      const digest = data.digest || {};
      const digestStats = digest.stats || {};
      $("digestSummary").textContent =
        `新增观察 ${valueText(digestStats.observations_in_window)} · 新增候选 ${valueText(digestStats.new_candidates)} · 待复核 ${valueText(digestStats.manual_review_items)}`;
      const quality = data.quality?.summary || {};
      const severity = quality.by_severity || {};
      $("qualitySummary").textContent =
        `错误 ${valueText(severity.error)} · 警告 ${valueText(severity.warning)} · 提示 ${valueText(severity.info)}`;
      const portfolio = data.portfolio || {};
      const selected = Array.isArray(portfolio.selected) ? portfolio.selected : [];
      const total = portfolio.rotation?.total_candidates;
      const budget = portfolio.budget?.per_round_budget;
      const nextKeyword = selected[0]?.keyword;
      $("portfolioSummary").textContent = selected.length
        ? `候选词 ${valueText(total)} · 下一词 ${valueText(nextKeyword)}`
        : `候选词 ${valueText(total)} · 当前无可运行词`;

      $("lastUpdatedAt").textContent =
        `更新 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
      applyCandidateFilters();
    }

    async function refresh(includeReadOnlyPlans = false) {
      const button = $("refreshButton");
      button.disabled = true;
      button.textContent = "刷新中";
      const readOnlyRequests = includeReadOnlyPlans
        ? Promise.all([
          refreshKeywordPool(),
          refreshRemediationPlan(),
            refreshApprovalManifest(),
            refreshSoakReadiness()
          ])
        : Promise.resolve();
      try {
        const response = await fetch(API_ROUTES.status);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        renderStatus(await response.json());
      } catch (error) {
        const body = $("candidateRows");
        body.replaceChildren();
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.className = "empty error";
        cell.colSpan = 9;
        cell.textContent = `读取工作台状态失败：${error.message}`;
        row.appendChild(cell);
        body.appendChild(row);
      } finally {
        await readOnlyRequests;
        button.disabled = false;
        button.textContent = "刷新";
      }
    }

    function setBusy(isBusy) {
      $("runOnceButton").disabled = isBusy;
      $("pauseButton").disabled = isBusy;
      const hasRiskStop = Boolean(latestStatus?.monitor?.risk_stop_reason);
      $("resumeButton").disabled = isBusy || hasRiskStop;
      $("riskResumeButton").disabled = isBusy || !hasRiskStop;
      $("refreshButton").disabled = isBusy;
    }

    async function setMonitor(action) {
      setBusy(true);
      try {
        const response = await fetch(API_ROUTES[action], { method: "POST" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        showToast(action === "pause" ? "已请求暂停监控" : "已请求恢复监控");
        await refresh();
      } catch (error) {
        showToast(`监控操作失败：${error.message}`);
      } finally {
        setBusy(false);
      }
    }

    async function resumeAfterRisk() {
      const riskReason = latestStatus?.monitor?.risk_stop_reason;
      if (!riskReason) {
        showToast("当前没有需要解除的风险停止");
        return;
      }
      const confirmed = window.confirm(
        `当前硬风控原因：\n${riskReason}\n\n请确认你已检查页面、账号和平台风控状态，且该风险已解除。`
      );
      if (!confirmed) return;
      setBusy(true);
      try {
        const response = await fetch(API_ROUTES.riskResume, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirm_risk_reason: riskReason })
        });
        if (!response.ok) {
          const detail = await response.json().catch(() => ({}));
          throw new Error(detail.detail || `HTTP ${response.status}`);
        }
        showToast("已显式解除风险停止并请求恢复监控");
        await refresh();
      } catch (error) {
        showToast(`风险解除失败：${error.message}`);
      } finally {
        setBusy(false);
      }
    }

    async function runOnce() {
      setBusy(true);
      try {
        const payload = {
          max_keywords: numberFromInput("maxKeywords", 1),
          max_products_per_keyword: numberFromInput("maxProducts", 1),
          wait_seconds: numberFromInput("waitSeconds", 6),
          metrics_max_frames: numberFromInput("metricFrames", 3),
          metrics_swipe: $("metricsSwipe").checked,
          note_evidence: false
        };
        const response = await fetch(API_ROUTES.runOnce, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const result = await response.json();
        const captured = valueText(result.captured_products || 0);
        const notes = Array.isArray(result.note_evidence) ? result.note_evidence.length : 0;
        showToast(result.blocked
          ? `单轮已停止：${result.blocked}`
          : `单轮完成：商品 ${captured} 个，笔记证据 ${notes} 条`);
        await refresh();
      } catch (error) {
        showToast(`单轮执行失败：${error.message}`);
      } finally {
        setBusy(false);
      }
    }

    function switchView(view) {
      const meta = VIEW_META[view] || VIEW_META.candidates;
      document.querySelectorAll("[data-view]").forEach((button) => {
        button.classList.toggle("active", button.dataset.view === view);
      });
      document.querySelectorAll("[data-view-panel]").forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.viewPanel === view);
      });
      $("viewTitle").textContent = meta[0];
      $("viewDescription").textContent = meta[1];
    }

    document.querySelectorAll("[data-view]").forEach((button) => {
      button.addEventListener("click", () => switchView(button.dataset.view));
    });
    document.querySelectorAll("[data-monitor-kind]").forEach((button) => {
      button.setAttribute("aria-expanded", "false");
      button.addEventListener("click", () => openMonitorDrilldown(button.dataset.monitorKind));
    });
    $("closeMonitorDrilldown").addEventListener("click", closeMonitorDrilldown);
    ["candidateSearch", "gradeFilter", "lowFollowerOnly", "trendOnly", "qualifiedOnly", "sortBy"].forEach((id) => {
      $(id).addEventListener(id === "candidateSearch" ? "input" : "change", applyCandidateFilters);
    });
    $("refreshButton").addEventListener("click", () => refresh(true));
    $("pauseButton").addEventListener("click", () => setMonitor("pause"));
    $("resumeButton").addEventListener("click", () => setMonitor("resume"));
    $("riskResumeButton").addEventListener("click", resumeAfterRisk);
    $("runOnceButton").addEventListener("click", runOnce);
    $("copyReportButton").addEventListener("click", async () => {
      const value = latestStatus?.monitor?.last_report_path || "";
      if (!value) {
        showToast("暂无报告路径");
        return;
      }
      try {
        await navigator.clipboard.writeText(value);
        showToast("已复制报告路径");
      } catch {
        showToast(value);
      }
    });

    refresh(true);
    window.setInterval(refresh, 10000);
  </script>
</body>
</html>"""
