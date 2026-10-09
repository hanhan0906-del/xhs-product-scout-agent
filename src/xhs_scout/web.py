from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import Settings
from .db import (
    RiskConfirmationError,
    RiskStopActiveError,
    connect,
    dashboard_stats,
    followed_product_sales_snapshot,
    get_monitor_state,
    latest_daily_sales_result,
    recent_run_events,
    resume_monitor_after_risk,
    set_monitor_desired_state,
    set_product_sales_follow,
)
from .monitor import MonitorLimits, monitor_once
from .insights import digest_snapshot, portfolio_snapshot, quality_snapshot
from .keyword_approval import (
    ALLOWED_STATUSES,
    ApprovalPolicy,
    build_keyword_approval_manifest,
    validate_keyword_approval_manifest,
)
from .keyword_discovery import discover_keyword_candidates
from .keyword_combinations import analyze_keyword_combinations
from .keyword_portfolio import build_keyword_candidates
from .low_follower import (
    evaluate_low_follower_evidence,
    promote_candidate_from_note_observations,
)
from .remediation import RemediationPlan, plan_remediation
from .remediation_approval import (
    RemediationApprovalError,
    build_approval_manifest,
    read_approval_manifest,
)
from .scheduler import ContinuousMonitorScheduler
from .signals import gray_metric_items
from .soak_readiness import evaluate_soak_readiness, evaluate_sqlite_readiness
from .workbench_ui import render_workbench_html
from .device_link_open import DeviceLinkOpenError, open_link_on_configured_device
from .product_link import is_supported_product_direct_url


class LowFollowerEvidence(BaseModel):
    author_name: str | None = None
    follower_count: int = Field(ge=0)
    likes: int = Field(default=0, ge=0)
    collects: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    published_days_ago: int | None = Field(default=None, ge=0)
    source_note: str | None = None


class MonitorRunRequest(BaseModel):
    max_keywords: int = Field(default=1, ge=1, le=3)
    max_products_per_keyword: int = Field(default=1, ge=1, le=3)
    wait_seconds: float = Field(default=6.0, ge=3.0, le=20.0)
    metrics_max_frames: int = Field(default=3, ge=1, le=5)
    metrics_swipe: bool = True
    note_evidence: bool = False
    seller_profile: bool = True
    task_id: int | None = Field(default=None, ge=1)
    expected_keyword: str | None = None
    # A controlled single run must be able to target the exact next rank.
    # Only the scheduler derives it from continuous discovery, so without
    # these the endpoint silently re-collects rank 1 and marks a rank 2+
    # task complete.
    search_result_rank: int = Field(default=1, ge=1, le=5)
    search_card_scan_limit: int = Field(default=3, ge=1, le=5)


class RiskResumeRequest(BaseModel):
    confirm_risk_reason: str = Field(min_length=1)


class ProductSalesFollowRequest(BaseModel):
    enabled: bool


_KEYWORD_REVIEW_PRODUCT_LIMIT = 500
_KEYWORD_REVIEW_SEARCH_LIMIT = 1_000
_AUTOMATED_ROUND_INTERVAL_SECONDS = 0
_AUTOMATED_IDLE_BACKOFF_SECONDS = 60
_KEYWORD_REVIEW_OBSERVATION_LIMIT = 1_000
_REMEDIATION_PRODUCT_LIMIT = 2_000
_REMEDIATION_APPROVAL_RELATIVE = (
    Path("approvals") / "remediation-approval.json"
)
_KEYWORD_APPROVAL_RELATIVE = Path("approvals") / "keyword-approval.json"
_KEYWORD_APPROVAL_MAX_AGE_SECONDS = 24 * 60 * 60
_KEYWORD_APPROVAL_FUTURE_SKEW_SECONDS = 5 * 60
_KEYWORD_APPROVAL_MAX_CANDIDATES = 50
_SOAK_ACK_LEDGER_RELATIVE = Path("acks") / "soak-ack.jsonl"
_SCHEDULER_EVIDENCE_LEDGER_RELATIVE = (
    Path("evidence") / "scheduler-evidence.jsonl"
)
_SCHEDULER_EXPECTED_RELATIVE = Path("evidence") / "scheduler-expected.json"
_SOAK_BASELINE_RELATIVE = Path("evidence") / "soak-baseline.json"
_KEYWORD_POOL_DIMENSIONS = (
    ("audience", "人群词"),
    ("function", "功效词"),
    ("scene", "场景词"),
    ("domain", "品类词"),
    ("format", "形式词"),
    ("stage", "阶段词"),
)
_MONITOR_DRILLDOWN_KINDS = {
    "tasks": "待搜索任务",
    "products": "已发现商品",
    "observations": "观察记录",
    "evidence": "笔记/账号证据",
    "candidates": "候选商品",
    "followed": "持续关注商品",
}
_GRAY_METRIC_LABELS = {
    "sales_24h_min": "24小时购买",
    "sales_7d_min": "近7天购买",
    "sales_30d_min": "近30天购买",
    "cart_24h_min": "24小时加购",
    "new_30d_min": "近30天新增",
    "positive_reviews_30d_min": "近30天好评",
    "favorites_30d_min": "近30天收藏",
    "interested_7d_min": "近7天感兴趣",
    "interested_30d_min": "近30天感兴趣",
    "viewers_now": "正在看",
    "sales_surging": "销量上升",
}


def _safe_json_list(value) -> list:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return ["候选理由数据格式异常，需人工复核"]
    return parsed if isinstance(parsed, list) else [str(parsed)]


def _monitor_drilldown_snapshot(settings: Settings, kind: str) -> dict:
    if kind not in _MONITOR_DRILLDOWN_KINDS:
        raise KeyError(kind)

    uri = f"{settings.db_path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        if kind == "tasks":
            rows = conn.execute(
                """
                SELECT id, keyword, source, priority, status, attempts, max_attempts,
                       next_run_at, last_error, created_at
                FROM search_tasks
                WHERE status='pending'
                ORDER BY priority DESC, id
                """
            ).fetchall()
            source_labels = {
                "seed_workbook": "历史种子词",
                "manual": "手动加入",
                "keyword_discovery": "商品标题拆词",
            }
            items = [
                {
                    "id": int(row["id"]),
                    "title": row["keyword"],
                    "subtitle": source_labels.get(row["source"], "其他来源"),
                    "fields": [
                        {"label": "关键词", "value": row["keyword"]},
                        {"label": "当前状态", "value": "待搜索"},
                        {
                            "label": "来源",
                            "value": source_labels.get(row["source"], "其他来源"),
                        },
                        {
                            "label": "已尝试",
                            "value": f'{row["attempts"]}/{row["max_attempts"]} 次',
                        },
                        {"label": "优先级", "value": row["priority"]},
                        {"label": "加入时间", "value": row["created_at"]},
                        {
                            "label": "计划时间",
                            "value": row["next_run_at"] or "尚未安排",
                        },
                        {
                            "label": "最近问题",
                            "value": row["last_error"] or "无",
                        },
                    ],
                }
                for row in rows
            ]
        elif kind == "observations":
            rows = conn.execute(
                """
                SELECT o.*, p.title, p.shop_name
                FROM observations o
                LEFT JOIN products p ON p.id=o.product_id
                ORDER BY o.id DESC
                """
            ).fetchall()
            items = []
            for row in rows:
                from .signals import gray_metric_items

                metric_keys = list(gray_metric_items(row["raw_signals_json"]))
                metric_text = "、".join(
                    _GRAY_METRIC_LABELS.get(key, key) for key in metric_keys
                ) or "无"
                sales_display = (
                    row["cumulative_sales_display"]
                    or row["cumulative_sales_min"]
                    or "未识别"
                )
                items.append(
                    {
                        "id": int(row["id"]),
                        "title": row["title"] or "未识别商品",
                        "subtitle": row["observed_at"],
                        "detail_url": (
                            f'/products/{int(row["product_id"])}/analysis'
                            if row["product_id"] is not None
                            else None
                        ),
                        "detail_label": "查看商品详情",
                        "fields": [
                            {"label": "商品", "value": row["title"] or "未识别"},
                            {"label": "店铺", "value": row["shop_name"] or "未识别"},
                            {"label": "观察时间", "value": row["observed_at"]},
                            {"label": "商品销量", "value": sales_display},
                            {
                                "label": "24小时新增销量",
                                "value": (
                                    row["daily_sales_delta"]
                                    if row["daily_sales_delta"] is not None
                                    else "待计算"
                                ),
                            },
                            {"label": "灰色指标", "value": metric_text},
                        ],
                    }
                )
        elif kind == "evidence":
            rows = conn.execute(
                """
                SELECT no.*, p.title, p.shop_name
                FROM note_observations no
                LEFT JOIN products p ON p.id=no.product_id
                ORDER BY no.id DESC
                """
            ).fetchall()
            source_labels = {
                "seller_profile_from_product": "商品店铺账号",
                "author_profile_from_note": "笔记作者主页",
                "related_note_card": "关联笔记",
            }
            items = []
            for row in rows:
                account_name = (
                    row["shop_name"]
                    if row["source"] == "seller_profile_from_product"
                    else row["author_name"]
                )
                fields = [
                    {"label": "对应商品", "value": row["title"] or "未关联商品"},
                    {
                        "label": "证据类型",
                        "value": source_labels.get(row["source"], "页面证据"),
                    },
                    {"label": "采集时间", "value": row["captured_at"]},
                ]
                optional_values = (
                    ("账号名称", account_name),
                    ("粉丝数", row["follower_count"]),
                    ("获赞数", row["likes"]),
                    ("收藏数", row["collects"]),
                    ("评论数", row["comments"]),
                    ("发布距今天数", row["published_days_ago"]),
                )
                for label, value in optional_values:
                    if value is not None:
                        fields.append({"label": label, "value": value})
                items.append(
                    {
                        "id": int(row["id"]),
                        "title": row["title"] or "未关联商品",
                        "subtitle": source_labels.get(row["source"], "页面证据"),
                        "detail_url": (
                            f'/products/{int(row["product_id"])}/analysis'
                            if row["product_id"] is not None
                            else None
                        ),
                        "detail_label": "查看商品详情",
                        "fields": fields,
                    }
                )
        elif kind == "followed":
            has_daily = conn.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type='table' AND name='daily_sales_plans'
                """
            ).fetchone() is not None
            daily_columns = (
                """
                (SELECT dp.cumulative_sales_display
                 FROM daily_sales_plans dp
                 WHERE dp.product_id=p.id
                   AND dp.status IN ('completed_exact', 'completed_fuzzy')
                 ORDER BY dp.cycle_date DESC, dp.id DESC LIMIT 1
                ) AS tracked_sales_display,
                (SELECT dp.daily_sales_delta
                 FROM daily_sales_plans dp
                 WHERE dp.product_id=p.id AND dp.status='completed_exact'
                 ORDER BY dp.cycle_date DESC, dp.id DESC LIMIT 1
                ) AS tracked_daily_delta
                """
                if has_daily
                else "NULL AS tracked_sales_display, NULL AS tracked_daily_delta"
            )
            rows = conn.execute(
                f"""
                SELECT p.id, p.title, p.shop_name, p.share_url,
                       f.followed_at,
                       o.cumulative_sales_display, o.cumulative_sales_min,
                       {daily_columns}
                FROM product_sales_follows f
                JOIN products p ON p.id=f.product_id
                LEFT JOIN observations o ON o.id=(
                    SELECT id FROM observations latest
                    WHERE latest.product_id=p.id ORDER BY id DESC LIMIT 1
                )
                ORDER BY f.followed_at DESC, p.id DESC
                """
            ).fetchall()
            items = [
                {
                    "id": int(row["id"]),
                    "title": row["title"] or "未命名商品",
                    "subtitle": row["shop_name"] or "店铺待补",
                    "detail_url": f'/products/{int(row["id"])}/analysis',
                    "detail_label": "查看商品详情",
                    "fields": [
                        {"label": "商品名称", "value": row["title"] or "未命名"},
                        {"label": "店铺", "value": row["shop_name"] or "待补"},
                        {
                            "label": "商品销量",
                            "value": (
                                row["tracked_sales_display"]
                                or row["cumulative_sales_display"]
                                or row["cumulative_sales_min"]
                                or "待采集"
                            ),
                        },
                        {
                            "label": "24小时新增销量",
                            "value": (
                                row["tracked_daily_delta"]
                                if row["tracked_daily_delta"] is not None
                                else "待下一次零点计算"
                            ),
                        },
                        {"label": "加入关注", "value": row["followed_at"]},
                    ],
                }
                for row in rows
            ]
        else:
            rows = conn.execute(
                """
                SELECT p.id, p.title, p.shop_name, p.price, p.share_url,
                       p.first_seen_at, p.last_seen_at,
                       o.cumulative_sales_display, o.cumulative_sales_min,
                       o.raw_signals_json,
                       a.evidence_grade, a.score,
                       (SELECT COUNT(*) FROM observations all_o
                        WHERE all_o.product_id=p.id) AS observation_count,
                       (SELECT follower_count FROM note_observations no
                        WHERE no.product_id=p.id
                          AND no.source='seller_profile_from_product'
                        ORDER BY no.id DESC LIMIT 1) AS seller_follower_count,
                       (SELECT CASE
                            WHEN no.follower_count IS NOT NULL THEN 'visible'
                            WHEN json_valid(no.raw_json)
                                 AND json_extract(no.raw_json, '$.follower_display_status')='not_displayed'
                                THEN 'not_displayed'
                            ELSE 'missing'
                        END
                        FROM note_observations no
                        WHERE no.product_id=p.id
                          AND no.source='seller_profile_from_product'
                        ORDER BY no.id DESC LIMIT 1) AS seller_follower_display_status
                FROM products p
                LEFT JOIN observations o ON o.id=(
                    SELECT id FROM observations latest
                    WHERE latest.product_id=p.id ORDER BY id DESC LIMIT 1
                )
                LEFT JOIN candidate_assessments a ON a.id=(
                    SELECT id FROM candidate_assessments latest_a
                    WHERE latest_a.product_id=p.id ORDER BY id DESC LIMIT 1
                )
                ORDER BY p.id DESC
                """
            ).fetchall()
            items = []
            for row in rows:
                from .signals import gray_metric_items

                metric_keys = list(gray_metric_items(row["raw_signals_json"]))
                if kind == "candidates" and len(metric_keys) < 3:
                    continue
                metric_text = "、".join(
                    _GRAY_METRIC_LABELS.get(key, key) for key in metric_keys
                ) or "无"
                sales_display = (
                    row["cumulative_sales_display"]
                    or row["cumulative_sales_min"]
                    or "未识别"
                )
                items.append(
                    {
                        "id": int(row["id"]),
                        "title": row["title"] or "未命名商品",
                        "subtitle": row["shop_name"] or "店铺待补",
                        "detail_url": f'/products/{int(row["id"])}/analysis',
                        "detail_label": "查看商品详情",
                        "fields": [
                            {"label": "商品名称", "value": row["title"] or "未命名"},
                            {"label": "店铺", "value": row["shop_name"] or "待补"},
                            {
                                "label": "价格",
                                "value": (
                                    f'¥{row["price"]:g}'
                                    if row["price"] is not None
                                    else "待补"
                                ),
                            },
                            {"label": "商品销量", "value": sales_display},
                            {"label": "灰色指标", "value": metric_text},
                            {
                                "label": "粉丝数",
                                "value": (
                                    row["seller_follower_count"]
                                    if row["seller_follower_count"] is not None
                                    else (
                                        "页面未显示"
                                        if row["seller_follower_display_status"] == "not_displayed"
                                        else "待补"
                                    )
                                ),
                            },
                            {
                                "label": "观察次数",
                                "value": row["observation_count"],
                            },
                            {"label": "首次发现", "value": row["first_seen_at"]},
                            {"label": "最近观察", "value": row["last_seen_at"]},
                        ],
                    }
                )
    finally:
        conn.close()

    return {
        "kind": kind,
        "label": _MONITOR_DRILLDOWN_KINDS[kind],
        "count": len(items),
        "items": items,
        "scope": {
            "access": "read_only",
            "database_write": False,
            "search_trigger": False,
            "monitor_trigger": False,
        },
    }


def _bounded_rows(conn, sql: str, limit: int) -> tuple[list[dict], int]:
    rows = conn.execute(sql, (limit + 1,)).fetchall()
    truncated = int(len(rows) > limit)
    return [dict(row) for row in rows[:limit]], truncated


def _trend_labels_from_raw(value) -> tuple[list[str | dict], bool]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return [], True
    if not isinstance(parsed, dict):
        return [], True

    labels: list[str | dict] = []
    for key in ("trend_labels", "trend_tags", "tags"):
        current = parsed.get(key)
        if current is None:
            continue
        if isinstance(current, (str, dict)):
            labels.append(current)
        elif isinstance(current, list):
            labels.extend(item for item in current if isinstance(item, (str, dict)))
        else:
            return labels, True
    return labels, False


def _existing_keyword_mappings(settings: Settings) -> tuple[list[dict], str | None]:
    path = settings.root / "config" / "keyword_portfolio.json"
    if not path.is_file():
        return [], None
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("关键词组合配置不是 JSON object")
        return [candidate.to_dict() for candidate in build_keyword_candidates(config)], None
    except (
        OSError,
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        return [], f"keyword_portfolio_unavailable:{type(exc).__name__}"


def _keyword_review_inputs(settings: Settings) -> dict:
    warnings: list[str] = []
    uri = f"{settings.db_path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        products, products_truncated = _bounded_rows(
            conn,
            """
            SELECT p.id, p.title, p.shop_name
            FROM products p
            WHERE EXISTS (
                SELECT 1 FROM observations o WHERE o.product_id=p.id
            )
            ORDER BY p.last_seen_at DESC, p.id DESC
            LIMIT ?
            """,
            _KEYWORD_REVIEW_PRODUCT_LIMIT,
        )
        searches, searches_truncated = _bounded_rows(
            conn,
            """
            SELECT se.id, se.product_id, se.source_keyword AS keyword
            FROM search_result_evidence se
            JOIN products p ON p.id=se.product_id
            WHERE se.id=(
                SELECT se2.id
                FROM search_result_evidence se2
                WHERE se2.product_id=se.product_id
                ORDER BY se2.id DESC
                LIMIT 1
            )
              AND se.valid=1
              AND TRIM(COALESCE(se.source_keyword, '')) <> ''
            ORDER BY se.recorded_at DESC, se.id DESC
            LIMIT ?
            """,
            _KEYWORD_REVIEW_SEARCH_LIMIT,
        )
        observations, observations_truncated = _bounded_rows(
            conn,
            """
            SELECT o.id, o.product_id, o.raw_signals_json,
                   (
                       SELECT se.source_keyword
                       FROM search_result_evidence se
                       WHERE se.id=(
                           SELECT se2.id
                           FROM search_result_evidence se2
                           WHERE se2.product_id=o.product_id
                           ORDER BY se2.id DESC
                           LIMIT 1
                       )
                         AND se.valid=1
                         AND TRIM(COALESCE(se.source_keyword, '')) <> ''
                       ORDER BY se.recorded_at DESC, se.id DESC
                       LIMIT 1
                   ) AS source_keyword
            FROM observations o
            WHERE o.product_id IS NOT NULL
            ORDER BY o.observed_at DESC, o.id DESC
            LIMIT ?
            """,
            _KEYWORD_REVIEW_OBSERVATION_LIMIT,
        )
    finally:
        conn.close()

    product_mappings = [
        {
            "id": str(row["id"]),
            "title": row.get("title"),
            "shop_public_text": row.get("shop_name"),
        }
        for row in products
    ]
    search_mappings = [
        {
            "id": f"search-evidence-{row['id']}",
            "product_id": str(row["product_id"]),
            "keyword": row.get("keyword"),
        }
        for row in searches
    ]
    trend_mappings: list[dict] = []
    malformed_trend_fields = 0
    for row in observations:
        labels, malformed = _trend_labels_from_raw(row.get("raw_signals_json"))
        malformed_trend_fields += int(malformed)
        for index, label in enumerate(labels):
            if isinstance(label, dict):
                mapping = dict(label)
                mapping.setdefault("id", f"observation-{row['id']}-trend-{index + 1}")
                mapping.setdefault("product_id", str(row["product_id"]))
                mapping.setdefault("source_keyword", row.get("source_keyword"))
            else:
                mapping = {
                    "id": f"observation-{row['id']}-trend-{index + 1}",
                    "product_id": str(row["product_id"]),
                    "source_keyword": row.get("source_keyword"),
                    "label": label,
                }
            trend_mappings.append(mapping)

    if malformed_trend_fields:
        warnings.append(f"malformed_trend_fields:{malformed_trend_fields}")
    return {
        "products": product_mappings,
        "successful_searches": search_mappings,
        "trend_labels": trend_mappings,
        "stats": {
            "products_read": len(product_mappings),
            "valid_search_sources_read": len(search_mappings),
            "trend_labels_read": len(trend_mappings),
            "malformed_trend_fields": malformed_trend_fields,
            "source_rows_truncated": {
                "products": products_truncated,
                "valid_search_sources": searches_truncated,
                "trend_observations": observations_truncated,
            },
        },
        "warnings": warnings,
    }


def _keyword_review_scope() -> dict:
    return {
        "mode": "database_backed_keyword_review",
        "database_access": "read_only",
        "production_queue_write": False,
        "keyword_config_write": False,
        "auto_approval": False,
        "search_trigger": False,
        "human_review_required": True,
    }


def _empty_keyword_review_result(*, max_output: int, warning: str) -> dict:
    return {
        "version": 1,
        "scope": _keyword_review_scope(),
        "policy": {"max_output": max_output},
        "stats": {
            "raw_occurrences": 0,
            "unique_candidates_before_cap": 0,
            "returned_candidates": 0,
            "truncated_candidates": 0,
            "filtered_occurrences": 0,
            "existing_portfolio_occurrences": 0,
        },
        "source_stats": {
            "products_read": 0,
            "valid_search_sources_read": 0,
            "trend_labels_read": 0,
            "malformed_trend_fields": 0,
            "source_rows_truncated": {
                "products": 0,
                "valid_search_sources": 0,
                "trend_observations": 0,
            },
        },
        "warnings": [warning],
        "candidates": [],
        "filtered": [],
    }


def _keyword_suggestions_snapshot(
    settings: Settings,
    *,
    max_output: int,
) -> dict:
    inputs = _keyword_review_inputs(settings)
    existing_keywords, config_warning = _existing_keyword_mappings(settings)
    result = discover_keyword_candidates(
        products=inputs["products"],
        successful_searches=inputs["successful_searches"],
        trend_labels=inputs["trend_labels"],
        existing_keywords=existing_keywords,
        policy={"max_output": max_output},
    )
    result["scope"] = _keyword_review_scope()
    result["source_stats"] = inputs["stats"]
    result["warnings"] = [
        *inputs["warnings"],
        *([config_warning] if config_warning else []),
    ]
    return result


def _keyword_approval_scope() -> dict:
    return {
        "mode": "database_backed_keyword_approval_review",
        "database_access": "sqlite_mode_ro_query_only",
        "manifest_location": _KEYWORD_APPROVAL_RELATIVE.as_posix(),
        "manifest_access": "read_only",
        "request_path_override_allowed": False,
        "human_review_only": True,
        "approval_write": False,
        "approval_endpoint": False,
        "writes_queue": False,
        "search_execution": False,
        "monitor_authorization": False,
        "soak_authorization": False,
    }


def _keyword_approval_path(settings: Settings) -> Path:
    project_root = settings.root.resolve(strict=True)
    return _fixed_project_file(
        project_root,
        _KEYWORD_APPROVAL_RELATIVE,
        label="keyword approval manifest",
    )


def _keyword_approval_authorization() -> dict:
    return {
        "writes_queue": False,
        "search_execution": False,
        "monitor_authorization": False,
        "soak_authorization": False,
        "human_confirmation_required": True,
        "statement": (
            "此接口仅只读展示人工关键词审批记录；即使清单当前有效，也不授权"
            "写队列、执行搜索、启动监控或 soak。"
        ),
    }


def _keyword_combination_review_snapshot(settings: Settings) -> dict:
    uri = f"{settings.db_path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        analysis = analyze_keyword_combinations(conn)
    finally:
        conn.close()
    result = analysis.as_dict()
    result["candidates"] = result["candidates"][:50]
    result["candidate_count"] = len(analysis.candidates)
    result["returned_count"] = len(result["candidates"])
    result["truncated"] = len(analysis.candidates) > len(result["candidates"])
    result["scope"].update(
        {
            "database_access": "sqlite_mode_ro_query_only",
            "approval_endpoint": False,
            "writes_queue": False,
            "search_execution": False,
            "soak_authorization": False,
        }
    )
    result["warnings"] = []
    return result


def _keyword_pool_snapshot(settings: Settings) -> dict:
    uri = f"{settings.db_path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute(
            """
            SELECT t.dimension, t.raw_term, t.normalized_term,
                   t.review_status AS term_review_status,
                   r.product_id, r.source_root, p.title
            FROM product_keyword_terms t
            JOIN product_keyword_records r ON r.id=t.record_id
            JOIN products p ON p.id=r.product_id
            WHERE r.decomposition_status='complete'
              AND r.review_status NOT IN ('rejected', 'deprecated')
              AND t.review_status NOT IN ('rejected', 'deprecated')
            ORDER BY t.dimension, t.normalized_term,
                     CASE t.review_status WHEN 'approved' THEN 0 ELSE 1 END,
                     t.id DESC
            """
        ).fetchall()
    finally:
        conn.close()

    dimension_labels = dict(_KEYWORD_POOL_DIMENSIONS)
    terms_by_key: dict[tuple[str, str], dict] = {}
    products: dict[int, dict] = {}
    for row in rows:
        dimension = str(row["dimension"])
        if dimension not in dimension_labels:
            continue
        normalized = str(row["normalized_term"] or "").strip()
        raw_term = str(row["raw_term"] or "").strip()
        if not normalized or not raw_term:
            continue
        key = (dimension, normalized)
        entry = terms_by_key.setdefault(
            key,
            {
                "term": raw_term,
                "normalized": normalized,
                "review_status": str(row["term_review_status"]),
                "source_products": {},
            },
        )
        if row["term_review_status"] == "approved":
            entry["term"] = raw_term
            entry["review_status"] = "approved"
        product_id = int(row["product_id"])
        title = str(row["title"] or f"商品 {product_id}")
        entry["source_products"][product_id] = {
            "product_id": product_id,
            "title": title,
        }
        product = products.setdefault(
            product_id,
            {
                "product_id": product_id,
                "title": title,
                "source_roots": set(),
                "terms": {name: [] for name, _label in _KEYWORD_POOL_DIMENSIONS},
            },
        )
        if row["source_root"]:
            product["source_roots"].add(str(row["source_root"]))
        if raw_term not in product["terms"][dimension]:
            product["terms"][dimension].append(raw_term)

    categories = []
    for dimension, label in _KEYWORD_POOL_DIMENSIONS:
        items = []
        for (item_dimension, _normalized), entry in terms_by_key.items():
            if item_dimension != dimension:
                continue
            source_products = sorted(
                entry["source_products"].values(),
                key=lambda item: item["product_id"],
            )
            items.append(
                {
                    "term": entry["term"],
                    "normalized": entry["normalized"],
                    "review_status": entry["review_status"],
                    "source_product_count": len(source_products),
                    "source_products": source_products,
                }
            )
        items.sort(key=lambda item: (item["review_status"] != "approved", item["term"]))
        categories.append(
            {
                "dimension": dimension,
                "label": label,
                "count": len(items),
                "terms": items,
            }
        )

    product_items = []
    for product in sorted(products.values(), key=lambda item: item["product_id"], reverse=True):
        product_items.append(
            {
                "product_id": product["product_id"],
                "title": product["title"],
                "source_roots": sorted(product["source_roots"]),
                "term_count": sum(len(values) for values in product["terms"].values()),
                "terms": product["terms"],
            }
        )

    return {
        "total_terms": sum(category["count"] for category in categories),
        "source_product_count": len(product_items),
        "categories": categories,
        "source_products": product_items,
        "scope": {
            "database_access": "sqlite_mode_ro_query_only",
            "production_queue_write": False,
            "search_trigger": False,
        },
    }


def _empty_keyword_combination_review(warning: str) -> dict:
    return {
        "generation_stage": "not_ready",
        "product_count": 0,
        "root_count": 0,
        "domain_scene_count": 0,
        "shop_count": 0,
        "context_count": 0,
        "gates": {
            "all_records_traceable": False,
            "small_products": False,
            "small_roots": False,
            "small_domain_or_scene": False,
            "stable_products": False,
            "stable_roots": False,
        },
        "candidates": [],
        "candidate_count": 0,
        "returned_count": 0,
        "truncated": False,
        "dataset_fingerprint": None,
        "scope": {
            "mode": "offline_keyword_combination_analysis",
            "database_access": "sqlite_mode_ro_query_only",
            "production_queue_write": False,
            "approval_write": False,
            "approval_endpoint": False,
            "writes_queue": False,
            "search_trigger": False,
            "search_execution": False,
            "monitor_authorization": False,
            "soak_authorization": False,
            "human_review_required": True,
        },
        "warnings": [warning],
    }


def _empty_keyword_approval_result(
    *,
    manifest_status: str,
    warning: str,
    manifest_present: bool,
) -> dict:
    return {
        "version": 1,
        "scope": _keyword_approval_scope(),
        "review_status": "fail_closed",
        "manifest_status": manifest_status,
        "manifest_present": manifest_present,
        "is_current": False,
        "is_expired": None,
        "manifest_age_seconds": None,
        "validation": {
            "integrity_valid": False,
            "semantic_valid": False,
            "policy_within_bounds": False,
            "suggestion_set_hash_matches": None,
            "evidence_hashes_match": None,
            "layers_match": None,
            "statuses_valid": None,
            "counts_match": None,
            "unknown_candidate_ids": [],
        },
        "stored_stats": None,
        "current_stats": None,
        "entries": [],
        "warnings": [warning],
        "authorization": _keyword_approval_authorization(),
    }


def _keyword_manifest_candidates(manifest: dict) -> list[dict]:
    return [
        {
            "candidate_id": item["candidate_id"],
            "keyword": item["keyword"],
            "normalized": item["normalized"],
            "suggested_layer": item["layer"],
            "source_products": item["source_summary"]["source_products"],
            "source_keywords": item["source_summary"]["source_keywords"],
            "support": {
                "score": item["source_summary"]["support_score"],
                "evidence_count": item["source_summary"]["evidence_count"],
                "source_types": item["source_summary"]["source_types"],
            },
            "risk_flags": item["source_summary"]["risk_flags"],
            "evidence": item["evidence"],
        }
        for item in manifest["entries"]
    ]


def _keyword_manifest_derived_stats(manifest: dict) -> dict:
    entries = manifest["entries"]
    return {
        "total": len(entries),
        "core": sum(item.get("layer") == "core" for item in entries),
        "exploration": sum(
            item.get("layer") == "exploration" for item in entries
        ),
        "pending": sum(item.get("status") == "pending" for item in entries),
        "approved": sum(item.get("status") == "approved" for item in entries),
        "rejected": sum(item.get("status") == "rejected" for item in entries),
        "invalidated": 0,
    }


def _keyword_manifest_policy_within_web_bounds(manifest: dict) -> bool:
    policy = ApprovalPolicy.from_mapping(manifest.get("policy"))
    return (
        policy.max_approved <= ApprovalPolicy.max_approved
        and policy.min_keyword_chars >= ApprovalPolicy.min_keyword_chars
        and policy.max_keyword_chars <= ApprovalPolicy.max_keyword_chars
        and len(manifest["entries"]) <= _KEYWORD_APPROVAL_MAX_CANDIDATES
    )


def _keyword_approval_from_database(settings: Settings) -> dict:
    try:
        manifest_path = _keyword_approval_path(settings)
    except (OSError, ValueError) as exc:
        return _empty_keyword_approval_result(
            manifest_status="invalid",
            warning=f"keyword_approval_path_invalid:{type(exc).__name__}",
            manifest_present=False,
        )
    if not manifest_path.is_file():
        return _empty_keyword_approval_result(
            manifest_status="missing",
            warning="keyword_approval_manifest_missing",
            manifest_present=False,
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise TypeError("keyword approval manifest must be a JSON object")
        integrity_valid, integrity_errors = validate_keyword_approval_manifest(
            manifest
        )
        if not integrity_valid:
            result = _empty_keyword_approval_result(
                manifest_status="invalid",
                warning="keyword_approval_manifest_invalid",
                manifest_present=True,
            )
            result["warnings"].extend(
                f"keyword_approval_integrity:{error}"
                for error in integrity_errors
            )
            return result
        canonical_stored = build_keyword_approval_manifest(
            _keyword_manifest_candidates(manifest),
            previous_manifest=manifest,
            policy=manifest.get("policy"),
        )
        semantic_valid = canonical_stored == manifest
        policy_within_bounds = _keyword_manifest_policy_within_web_bounds(
            manifest
        )
    except (
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        return _empty_keyword_approval_result(
            manifest_status="invalid",
            warning=f"keyword_approval_manifest_invalid:{type(exc).__name__}",
            manifest_present=True,
        )

    if not semantic_valid or not policy_within_bounds:
        result = _empty_keyword_approval_result(
            manifest_status="out_of_bounds",
            warning=(
                "keyword_approval_manifest_semantics_mismatch"
                if not semantic_valid
                else "keyword_approval_policy_out_of_bounds"
            ),
            manifest_present=True,
        )
        result["validation"].update(
            {
                "integrity_valid": True,
                "semantic_valid": semantic_valid,
                "policy_within_bounds": policy_within_bounds,
                "statuses_valid": all(
                    item.get("status") in ALLOWED_STATUSES
                    for item in manifest["entries"]
                ),
                "counts_match": (
                    manifest.get("stats")
                    == _keyword_manifest_derived_stats(manifest)
                ),
            }
        )
        return result

    try:
        stat = manifest_path.stat()
        manifest_age_seconds = max(0.0, time.time() - stat.st_mtime)
        timestamp_in_future = (
            stat.st_mtime - time.time()
            > _KEYWORD_APPROVAL_FUTURE_SKEW_SECONDS
        )
        is_expired = (
            manifest_age_seconds > _KEYWORD_APPROVAL_MAX_AGE_SECONDS
            or timestamp_in_future
        )
        suggestions = _keyword_suggestions_snapshot(
            settings,
            max_output=_KEYWORD_APPROVAL_MAX_CANDIDATES,
        )
        current_pending = build_keyword_approval_manifest(
            suggestions,
            policy=manifest.get("policy"),
        )
        current_with_decisions = build_keyword_approval_manifest(
            suggestions,
            previous_manifest=manifest,
            policy=manifest.get("policy"),
        )
    except (OSError, sqlite3.Error) as exc:
        result = _empty_keyword_approval_result(
            manifest_status="unavailable",
            warning=f"readonly_database_unavailable:{type(exc).__name__}",
            manifest_present=True,
        )
        result["validation"].update(
            {
                "integrity_valid": True,
                "semantic_valid": True,
                "policy_within_bounds": True,
            }
        )
        return result
    except (KeyError, TypeError, ValueError) as exc:
        result = _empty_keyword_approval_result(
            manifest_status="unavailable",
            warning=f"keyword_suggestions_unavailable:{type(exc).__name__}",
            manifest_present=True,
        )
        result["validation"].update(
            {
                "integrity_valid": True,
                "semantic_valid": True,
                "policy_within_bounds": True,
            }
        )
        return result

    stored_by_id = {
        item["candidate_id"]: item for item in manifest["entries"]
    }
    current_by_id = {
        item["candidate_id"]: item for item in current_pending["entries"]
    }
    unknown_candidate_ids = sorted(set(stored_by_id) - set(current_by_id))
    same_candidate_ids = set(stored_by_id) == set(current_by_id)
    suggestion_set_hash_matches = (
        manifest["suggestion_set_hash"]
        == current_pending["suggestion_set_hash"]
    )
    evidence_hashes_match = same_candidate_ids and all(
        stored_by_id[candidate_id]["evidence_hash"]
        == current_by_id[candidate_id]["evidence_hash"]
        for candidate_id in stored_by_id
    )
    layers_match = same_candidate_ids and all(
        stored_by_id[candidate_id]["layer"]
        == current_by_id[candidate_id]["layer"]
        for candidate_id in stored_by_id
    )
    statuses_valid = all(
        item.get("status") in ALLOWED_STATUSES
        for item in manifest["entries"]
    )
    counts_match = (
        manifest.get("stats") == _keyword_manifest_derived_stats(manifest)
        and manifest.get("stats") == current_with_decisions.get("stats")
    )
    is_current = (
        not is_expired
        and suggestion_set_hash_matches
        and evidence_hashes_match
        and layers_match
        and statuses_valid
        and counts_match
        and canonical_stored == current_with_decisions
    )
    warnings: list[str] = []
    if timestamp_in_future:
        warnings.append("keyword_approval_manifest_timestamp_in_future")
    elif is_expired:
        warnings.append("keyword_approval_manifest_expired")
    if not suggestion_set_hash_matches:
        warnings.append("keyword_approval_suggestion_set_drift")
    if not evidence_hashes_match:
        warnings.append("keyword_approval_evidence_drift")
    if not layers_match:
        warnings.append("keyword_approval_layer_drift")
    if not statuses_valid:
        warnings.append("keyword_approval_status_invalid")
    if not counts_match:
        warnings.append("keyword_approval_counts_drift")
    if unknown_candidate_ids:
        warnings.append(
            "keyword_approval_unknown_candidates:"
            + ",".join(unknown_candidate_ids)
        )

    entries = json.loads(
        json.dumps(manifest["entries"], ensure_ascii=False)
    )
    if not is_current:
        for item in entries:
            item["approval_valid"] = False
    return {
        "version": 1,
        "scope": _keyword_approval_scope(),
        "review_status": "current" if is_current else "fail_closed",
        "manifest_status": (
            "current" if is_current else ("expired" if is_expired else "stale")
        ),
        "manifest_present": True,
        "is_current": is_current,
        "is_expired": is_expired,
        "manifest_age_seconds": round(manifest_age_seconds, 3),
        "validation": {
            "integrity_valid": True,
            "semantic_valid": True,
            "policy_within_bounds": True,
            "suggestion_set_hash_matches": suggestion_set_hash_matches,
            "evidence_hashes_match": evidence_hashes_match,
            "layers_match": layers_match,
            "statuses_valid": statuses_valid,
            "counts_match": counts_match,
            "unknown_candidate_ids": unknown_candidate_ids,
        },
        "stored_stats": dict(manifest["stats"]),
        "current_stats": dict(current_with_decisions["stats"]),
        "entries": entries,
        "warnings": warnings,
        "authorization": _keyword_approval_authorization(),
    }


def _soak_readiness_scope(report: dict, *, malformed_json_count: int) -> dict:
    rounds = report.get("record", {}).get("rounds", [])
    timestamps = sorted(
        str(value)
        for row in rounds
        for value in (row.get("started_at"), row.get("finished_at"))
        if value
    )
    return {
        "mode": "database_backed_soak_readiness",
        "database_access": "sqlite_mode_ro_query_only",
        "source": "configured_production_database",
        "tables": [
            "monitor_state",
            "observations",
            "products",
            "run_events",
            "run_leases",
            "search_result_evidence",
            "search_tasks",
        ],
        "first_evidence_at": timestamps[0] if timestamps else None,
        "last_evidence_at": timestamps[-1] if timestamps else None,
        "rounds_read": len(rounds),
        "malformed_json_count": malformed_json_count,
        "database_write": False,
        "schema_creation": False,
        "migration": False,
        "monitor_trigger": False,
        "soak_trigger": False,
    }


def _soak_ack_ledger(settings: Settings) -> tuple[Path, tuple[Path, ...]]:
    project_root = settings.root.resolve(strict=True)
    relative = _SOAK_ACK_LEDGER_RELATIVE
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("ACK ledger path must be a fixed project-relative path")
    ledger = (project_root / relative).resolve(strict=False)
    try:
        ledger.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("ACK ledger resolves outside the project root") from exc
    return ledger, (project_root,)


def _fixed_project_file(
    project_root: Path,
    relative: Path,
    *,
    label: str,
) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} path must be a fixed project-relative path")
    target = (project_root / relative).resolve(strict=False)
    try:
        target.relative_to(project_root)
    except ValueError as exc:
        raise ValueError(f"{label} path resolves outside the project root") from exc
    return target


def _scheduler_evidence_inputs(
    settings: Settings,
) -> tuple[Path, tuple[Path, ...], object, tuple[str, ...]]:
    project_root = settings.root.resolve(strict=True)
    ledger = _fixed_project_file(
        project_root,
        _SCHEDULER_EVIDENCE_LEDGER_RELATIVE,
        label="scheduler evidence ledger",
    )
    expected_path = _fixed_project_file(
        project_root,
        _SCHEDULER_EXPECTED_RELATIVE,
        label="scheduler expected",
    )
    warnings: list[str] = []
    if not ledger.is_file():
        warnings.append("scheduler_evidence_ledger_missing")
    if not expected_path.is_file():
        return (
            ledger,
            (project_root,),
            None,
            tuple(warnings + ["scheduler_expected_missing"]),
        )
    try:
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        warnings.append(f"scheduler_expected_invalid:{type(exc).__name__}")
        # Deliberately pass an invalid value into T49. It preserves database-backed
        # G0/G1 evaluation while making both scheduler gates fail closed.
        expected = "__invalid_scheduler_expected_file__"
    return ledger, (project_root,), expected, tuple(warnings)


def _soak_baseline_inputs(
    settings: Settings,
) -> tuple[Path, tuple[Path, ...], tuple[str, ...]]:
    project_root = settings.root.resolve(strict=True)
    manifest_path = _fixed_project_file(
        project_root,
        _SOAK_BASELINE_RELATIVE,
        label="soak baseline",
    )
    warnings: list[str] = []
    if not manifest_path.is_file():
        warnings.append("soak_baseline_missing")
    return manifest_path, (project_root,), tuple(warnings)


def _scheduler_evidence_warnings(result: dict) -> list[str]:
    scheduler = (result.get("record") or {}).get("scheduler_evidence") or {}
    warnings: list[str] = []
    if scheduler.get("integrity_error"):
        warnings.append(
            f"scheduler_evidence_integrity_error:{scheduler['integrity_error']}"
        )
    for stage, state in (scheduler.get("stages") or {}).items():
        if state.get("ready") is True:
            continue
        reasons = [
            *state.get("missing_reasons", ()),
            *state.get("failed_reasons", ()),
        ]
        if not reasons:
            reasons = ["scheduler evidence 未通过"]
        warnings.extend(
            f"scheduler_evidence:{stage}:{reason}" for reason in reasons
        )
    return warnings


def _soak_baseline_warnings(result: dict) -> list[str]:
    baseline = (result.get("record") or {}).get("baseline") or {}
    if baseline.get("status") == "passed":
        return []
    gaps = list(baseline.get("gaps") or ())
    if not gaps:
        gaps = ["baseline 未通过"]
    return [f"soak_baseline:{reason}" for reason in gaps]


def _scheduler_evidence_view(result: dict) -> None:
    record = result.setdefault("record", {})
    scheduler = record.setdefault("scheduler_evidence", {})
    scheduler.update(
        {
            "ledger_location": _SCHEDULER_EVIDENCE_LEDGER_RELATIVE.as_posix(),
            "expected_location": _SCHEDULER_EXPECTED_RELATIVE.as_posix(),
            "ledger_access": "read_only",
            "expected_access": "read_only",
            "request_path_override_allowed": False,
            "expected_contract": {
                "G2": "non-empty list of timezone-aware ISO-8601 scheduled_at",
                "G4": "non-empty list of timezone-aware ISO-8601 scheduled_at",
            },
        }
    )


def _soak_baseline_view(result: dict) -> None:
    record = result.setdefault("record", {})
    baseline = record.setdefault("baseline", {})
    baseline.update(
        {
            "manifest_location": _SOAK_BASELINE_RELATIVE.as_posix(),
            "manifest_access": "read_only",
            "request_path_override_allowed": False,
            "allowed_root": "project_root",
            "authorizes_start": False,
        }
    )


def _ack_readiness_view(result: dict) -> dict:
    summary = result.get("summary", {})
    required = list(summary.get("ack_required_alert_ids", ()))
    return {
        "required": bool(required),
        "ready": bool(summary.get("ack_ready")),
        "source": summary.get("ack_source", "not_required"),
        "required_alert_ids": required,
        "acknowledged_alert_ids": list(
            summary.get("acknowledged_alert_ids", ())
        ),
        "missing_alert_ids": list(summary.get("ack_missing_alert_ids", ())),
        "unresolved_alert_ids": list(
            summary.get("ack_unresolved_alert_ids", ())
        ),
        "latest_decisions": dict(summary.get("ack_latest_decisions", {})),
        "integrity_error": summary.get("ack_integrity_error"),
        "evidence_mismatches": list(
            summary.get("ack_evidence_mismatches", ())
        ),
        "ledger_location": _SOAK_ACK_LEDGER_RELATIVE.as_posix(),
        "ledger_access": "read_only_when_required",
        "request_path_override_allowed": False,
    }


def _soak_readiness_response(
    report,
    *,
    malformed_json_count: int = 0,
    extra_warnings: tuple[str, ...] = (),
) -> dict:
    result = report.as_dict()
    warnings = list(result.get("warnings", ()))
    if malformed_json_count:
        warnings.append(f"malformed_run_event_json:{malformed_json_count}")
    _scheduler_evidence_view(result)
    _soak_baseline_view(result)
    warnings.extend(_scheduler_evidence_warnings(result))
    warnings.extend(_soak_baseline_warnings(result))
    warnings.extend(extra_warnings)
    result["warnings"] = list(dict.fromkeys(warnings))
    result["gaps"] = [
        {
            "gate": gate,
            "status": decision["status"],
            "reasons": list(decision.get("reasons", ())),
        }
        for gate, decision in result["gates"].items()
        if decision["status"] != "passed"
    ]
    if malformed_json_count:
        result["gaps"].append(
            {
                "gate": "EVIDENCE_INTEGRITY",
                "status": "failed",
                "reasons": [
                    f"{malformed_json_count} 条 run_events.data_json 不是有效 JSON object"
                ],
            }
        )
        result["ready_for_pre_soak"] = False
        result["ready_for_24h_soak"] = False
    result["ack_readiness"] = _ack_readiness_view(result)
    result["evidence_scope"] = _soak_readiness_scope(
        result,
        malformed_json_count=malformed_json_count,
    )
    result["soak_start_authorized"] = False
    result["authorization"] = {
        "soak_start_authorized": False,
        "expansion_authorized": False,
        "human_confirmation_required": True,
        "statement": (
            "此接口仅提供只读准入证据，不授权启动 pre-soak、24 小时 soak、"
            "监控或扩容。"
        ),
    }
    return result


def _malformed_run_event_json_count(conn: sqlite3.Connection) -> int:
    has_table = conn.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='run_events'
        """
    ).fetchone()
    if not has_table:
        return 0
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(run_events)").fetchall()
    }
    if "data_json" not in columns:
        return 0
    malformed = 0
    for (raw,) in conn.execute(
        """
        SELECT data_json FROM run_events
        WHERE data_json IS NOT NULL AND TRIM(data_json) <> ''
        """
    ):
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            malformed += 1
            continue
        malformed += int(not isinstance(parsed, dict))
    return malformed


def _soak_readiness_from_database(settings: Settings) -> dict:
    ack_ledger_path, ack_allowed_roots = _soak_ack_ledger(settings)
    (
        scheduler_ledger_path,
        scheduler_allowed_roots,
        expected_scheduler_scheduled_at,
        scheduler_input_warnings,
    ) = _scheduler_evidence_inputs(settings)
    (
        baseline_manifest_path,
        baseline_allowed_roots,
        baseline_input_warnings,
    ) = _soak_baseline_inputs(settings)
    uri = f"{settings.db_path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    try:
        conn.execute("PRAGMA query_only=ON")
        malformed_json_count = _malformed_run_event_json_count(conn)
        report = evaluate_sqlite_readiness(
            conn,
            target="pre_soak",
            ack_ledger_path=ack_ledger_path,
            ack_allowed_roots=ack_allowed_roots,
            scheduler_evidence_ledger_path=scheduler_ledger_path,
            scheduler_evidence_allowed_roots=scheduler_allowed_roots,
            expected_scheduler_scheduled_at=expected_scheduler_scheduled_at,
            baseline_manifest_path=baseline_manifest_path,
            baseline_allowed_roots=baseline_allowed_roots,
        )
    finally:
        conn.close()
    return _soak_readiness_response(
        report,
        malformed_json_count=malformed_json_count,
        extra_warnings=(
            *scheduler_input_warnings,
            *baseline_input_warnings,
        ),
    )


def _empty_soak_readiness_result(
    *,
    warning: str,
    input_integrity_gap: str | None = None,
) -> dict:
    report = evaluate_soak_readiness(
        {"evidence_kind": "unavailable", "rounds": []},
        target="pre_soak",
    )
    result = _soak_readiness_response(
        report,
        extra_warnings=(
            *(
                (f"soak_input_integrity:{input_integrity_gap}",)
                if input_integrity_gap
                else ()
            ),
            warning,
        ),
    )
    if input_integrity_gap:
        result["gaps"].append(
            {
                "gate": "INPUT_INTEGRITY",
                "status": "failed",
                "reasons": [input_integrity_gap],
            }
        )
    return result


def _remediation_scope() -> dict:
    return {
        "mode": "database_backed_remediation_plan",
        "database_access": "read_only",
        "production_queue_write": False,
        "collection_trigger": False,
        "approval_write": False,
        "execution_endpoint": False,
        "human_review_required": True,
    }


def _metrics_strip_present(value) -> tuple[bool, bool]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return False, True
    if not isinstance(parsed, dict):
        return False, True
    strip = parsed.get("metrics_strip")
    if not isinstance(strip, dict):
        return False, False
    frames = strip.get("frames")
    return isinstance(frames, list) and bool(frames), False


def _valid_optional_datetime(value) -> tuple[str | None, bool]:
    if value is None or value == "":
        return None, False
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None, True
    return str(value), False


def _remediation_plan_inputs(settings: Settings) -> dict:
    uri = f"{settings.db_path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        rows, truncated = _bounded_rows(
            conn,
            """
            WITH latest_assessment AS (
                SELECT a.*
                FROM candidate_assessments a
                WHERE a.id=(
                    SELECT a2.id
                    FROM candidate_assessments a2
                    WHERE a2.product_id=a.product_id
                    ORDER BY a2.id DESC
                    LIMIT 1
                )
            ),
            latest_observation AS (
                SELECT o.*
                FROM observations o
                WHERE o.id=(
                    SELECT o2.id
                    FROM observations o2
                    WHERE o2.product_id=o.product_id
                    ORDER BY o2.id DESC
                    LIMIT 1
                )
            )
            SELECT p.id AS product_id, p.title, p.shop_name, p.share_url,
                   a.status, a.score, o.raw_signals_json,
                   EXISTS(
                       SELECT 1
                       FROM search_result_evidence seh
                       JOIN search_tasks sth ON sth.id=seh.task_id
                       JOIN observations oh ON oh.id=seh.observation_id
                       WHERE seh.product_id=p.id
                         AND oh.product_id=p.id
                         AND seh.valid=1
                         AND TRIM(COALESCE(seh.source_keyword, '')) <> ''
                         AND TRIM(seh.source_keyword)=TRIM(sth.keyword)
                         AND NOT EXISTS (
                             SELECT 1
                             FROM task_results trh
                             WHERE trh.task_id=seh.task_id
                               AND trh.observation_id=seh.observation_id
                               AND trh.valid<>1
                         )
                   ) AS has_valid_search_attribution,
                   CASE
                       WHEN se.id IS NULL THEN NULL
                       WHEN se.valid=1
                        AND se.product_id=p.id
                        AND so.product_id=p.id
                        AND st.id IS NOT NULL
                        AND TRIM(COALESCE(se.source_keyword, '')) <> ''
                        AND TRIM(se.source_keyword)=TRIM(st.keyword)
                        AND NOT EXISTS (
                            SELECT 1
                            FROM task_results tr
                            WHERE tr.task_id=se.task_id
                              AND tr.observation_id=se.observation_id
                              AND tr.valid<>1
                        )
                       THEN 1 ELSE 0
                   END AS latest_search_attribution_valid,
                   EXISTS(
                       SELECT 1 FROM note_observations nn
                       WHERE nn.product_id=p.id
                         AND (
                             nn.page_kind='note_detail'
                             OR nn.source='related_note_card'
                         )
                   ) AS has_note_evidence,
                   EXISTS(
                       SELECT 1 FROM note_observations np
                       WHERE np.product_id=p.id
                         AND np.follower_count IS NOT NULL
                         AND (
                             np.page_kind='account_profile'
                             OR np.source='author_profile_from_note'
                         )
                   ) AS has_profile_evidence,
                   (
                       SELECT nn.author_name FROM note_observations nn
                       WHERE nn.product_id=p.id
                         AND (
                             nn.page_kind='note_detail'
                             OR nn.source='related_note_card'
                         )
                       ORDER BY nn.id DESC LIMIT 1
                   ) AS note_author_name,
                   (
                       SELECT nn.published_days_ago FROM note_observations nn
                       WHERE nn.product_id=p.id
                         AND (
                             nn.page_kind='note_detail'
                             OR nn.source='related_note_card'
                         )
                       ORDER BY nn.id DESC LIMIT 1
                   ) AS note_published_days_ago,
                   (
                       SELECT nn.likes FROM note_observations nn
                       WHERE nn.product_id=p.id
                         AND (
                             nn.page_kind='note_detail'
                             OR nn.source='related_note_card'
                         )
                       ORDER BY nn.id DESC LIMIT 1
                   ) AS note_likes,
                   (
                       SELECT np.follower_count FROM note_observations np
                       WHERE np.product_id=p.id
                         AND np.follower_count IS NOT NULL
                         AND (
                             np.page_kind='account_profile'
                             OR np.source='author_profile_from_note'
                         )
                       ORDER BY np.id DESC LIMIT 1
                   ) AS known_follower_count,
                   (
                       SELECT re.event_at FROM run_events re
                       WHERE re.product_id=p.id AND re.phase='remediation'
                       ORDER BY re.id DESC LIMIT 1
                   ) AS last_remediation_at
            FROM products p
            JOIN latest_assessment a ON a.product_id=p.id
            LEFT JOIN latest_observation o ON o.product_id=p.id
            LEFT JOIN search_result_evidence se
              ON se.id=(
                  SELECT se2.id FROM search_result_evidence se2
                  WHERE se2.product_id=p.id
                  ORDER BY se2.id DESC LIMIT 1
              )
            LEFT JOIN search_tasks st ON st.id=se.task_id
            LEFT JOIN observations so ON so.id=se.observation_id
            ORDER BY
                CASE WHEN a.status='needs_review' THEN 0 ELSE 1 END,
                a.score DESC,
                p.id
            LIMIT ?
            """,
            _REMEDIATION_PRODUCT_LIMIT,
        )
    finally:
        conn.close()

    warnings: list[str] = []
    malformed_metrics_json = 0
    malformed_cooldowns = 0
    mappings: list[dict] = []
    for row in rows:
        has_metrics, malformed_metrics = _metrics_strip_present(
            row.get("raw_signals_json")
        )
        last_remediation_at, malformed_cooldown = _valid_optional_datetime(
            row.get("last_remediation_at")
        )
        malformed_metrics_json += int(malformed_metrics)
        malformed_cooldowns += int(malformed_cooldown)
        mappings.append(
            {
                "product_id": int(row["product_id"]),
                "title": row.get("title"),
                "shop_name": row.get("shop_name"),
                "status": str(row.get("status") or ""),
                "score": float(row.get("score") or 0.0),
                "share_url": row.get("share_url"),
                "has_valid_search_attribution": bool(
                    row.get("has_valid_search_attribution")
                ),
                "latest_search_attribution_valid": (
                    None
                    if row.get("latest_search_attribution_valid") is None
                    else bool(row["latest_search_attribution_valid"])
                ),
                "has_metrics_strip": has_metrics,
                "has_note_evidence": bool(row.get("has_note_evidence")),
                "has_profile_evidence": bool(row.get("has_profile_evidence")),
                "note_author_identifiable": bool(
                    str(row.get("note_author_name") or "").strip()
                ),
                "note_published_days_ago": row.get("note_published_days_ago"),
                "note_likes": row.get("note_likes"),
                "known_follower_count": row.get("known_follower_count"),
                "last_remediation_at": last_remediation_at,
            }
        )

    if malformed_metrics_json:
        warnings.append(f"malformed_metrics_json:{malformed_metrics_json}")
    if malformed_cooldowns:
        warnings.append(f"malformed_remediation_timestamps:{malformed_cooldowns}")
    if truncated:
        warnings.append(f"remediation_products_truncated:{_REMEDIATION_PRODUCT_LIMIT}")
    return {
        "products": mappings,
        "stats": {
            "products_read": len(mappings),
            "malformed_metrics_json": malformed_metrics_json,
            "malformed_remediation_timestamps": malformed_cooldowns,
            "source_rows_truncated": truncated,
        },
        "warnings": warnings,
    }


def _remediation_response(products, *, now, source_stats: dict, warnings: list[str]) -> dict:
    plan = plan_remediation(products, now=now)
    result = json.loads(json.dumps(plan.as_dict(), ensure_ascii=False))
    first_batch = result["batches"][0] if result["batches"] else None
    result.update(
        {
            "version": 1,
            "scope": _remediation_scope(),
            "earliest_executable_stage": (
                first_batch["stage"] if first_batch is not None else None
            ),
            "next_batch": first_batch,
            "blocking_dependencies": [
                {
                    "product_id": item["product_id"],
                    "category": "isolated",
                    "blocked_by": item["blocked_by"],
                }
                for item in result["isolated"]
            ]
            + [
                {
                    "product_id": item["product_id"],
                    "category": item["stage"],
                    "blocked_by": item["blocks"],
                }
                for batch in result["batches"]
                for item in batch["items"]
                if item["blocks"]
            ],
            "budget": {
                "per_batch_limit": result["policy"]["per_batch_limit"],
                "hourly_visit_limit": result["policy"]["hourly_visit_limit"],
                "product_cooldown_hours": result["policy"][
                    "product_cooldown_hours"
                ],
                "planned_product_visits": sum(
                    len(batch["items"]) for batch in result["batches"]
                ),
                "next_batch_items": (
                    len(first_batch["items"]) if first_batch is not None else 0
                ),
            },
            "source_stats": source_stats,
            "warnings": warnings,
        }
    )
    return result


def _empty_remediation_result(*, now, warning: str) -> dict:
    return _remediation_response(
        [],
        now=now,
        source_stats={
            "products_read": 0,
            "malformed_metrics_json": 0,
            "malformed_remediation_timestamps": 0,
            "source_rows_truncated": 0,
        },
        warnings=[warning],
    )


def _remediation_approval_scope() -> dict:
    return {
        "mode": "database_backed_remediation_approval_review",
        "database_access": "sqlite_mode_ro_query_only",
        "manifest_location": _REMEDIATION_APPROVAL_RELATIVE.as_posix(),
        "manifest_access": "read_only",
        "request_path_override_allowed": False,
        "production_queue_write": False,
        "approval_write": False,
        "approval_endpoint": False,
        "execution_endpoint": False,
        "authorizes_execution": False,
        "human_confirmation_required": True,
    }


def _remediation_approval_path(settings: Settings) -> Path:
    project_root = settings.root.resolve(strict=True)
    relative = _REMEDIATION_APPROVAL_RELATIVE
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(
            "remediation approval path must be a fixed project-relative path"
        )
    manifest_path = (project_root / relative).resolve(strict=False)
    try:
        manifest_path.relative_to(project_root)
    except ValueError as exc:
        raise ValueError(
            "remediation approval path resolves outside the project root"
        ) from exc
    return manifest_path


def _approval_plan_hash(plan: RemediationPlan) -> str:
    payload = json.dumps(
        plan.as_dict(),
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _approval_manifest_selections(manifest) -> list[dict]:
    return [
        {
            "batch_id": batch.batch_id,
            "product_ids": [item.product_id for item in batch.items],
        }
        for batch in manifest.selected_batches
    ]


def _approval_manifest_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("approval planner timestamp must include a timezone")
    return parsed


def _empty_remediation_approval_result(
    *,
    manifest_status: str,
    warning: str,
    manifest_present: bool,
) -> dict:
    return {
        "version": 1,
        "scope": _remediation_approval_scope(),
        "review_status": "pending",
        "manifest_status": manifest_status,
        "manifest_present": manifest_present,
        "is_current": False,
        "plan_approval_status": "pending_review",
        "stored_plan_approval_status": None,
        "execution_status": "not_executed",
        "authorizes_execution": False,
        "validation": {
            "integrity_valid": False,
            "semantic_valid": False,
            "planner_hash_matches": None,
        },
        "approval": None,
        "source_stats": None,
        "warnings": [warning],
    }


def _remediation_approval_from_database(settings: Settings) -> dict:
    try:
        manifest_path = _remediation_approval_path(settings)
    except (OSError, ValueError) as exc:
        return _empty_remediation_approval_result(
            manifest_status="invalid",
            warning=f"approval_path_invalid:{type(exc).__name__}",
            manifest_present=False,
        )
    if not manifest_path.is_file():
        return _empty_remediation_approval_result(
            manifest_status="missing",
            warning="approval_manifest_missing",
            manifest_present=False,
        )

    try:
        manifest = read_approval_manifest(manifest_path)
        plan_time = _approval_manifest_time(manifest.source_generated_at)
    except RemediationApprovalError as exc:
        return _empty_remediation_approval_result(
            manifest_status="invalid",
            warning=f"approval_manifest_invalid:{type(exc).__name__}",
            manifest_present=True,
        )
    except (TypeError, ValueError) as exc:
        return _empty_remediation_approval_result(
            manifest_status="invalid",
            warning=f"approval_manifest_semantics_invalid:{type(exc).__name__}",
            manifest_present=True,
        )

    try:
        inputs = _remediation_plan_inputs(settings)
        snapshot_blockers = []
        if inputs["stats"].get("source_rows_truncated"):
            snapshot_blockers.append("source_rows_truncated")
        if inputs["stats"].get("malformed_remediation_timestamps"):
            snapshot_blockers.append("malformed_remediation_timestamps")
        if snapshot_blockers:
            result = _empty_remediation_approval_result(
                manifest_status="unavailable",
                warning=(
                    "remediation_snapshot_incomplete:"
                    + ",".join(snapshot_blockers)
                ),
                manifest_present=True,
            )
            result["validation"]["integrity_valid"] = True
            result["source_stats"] = inputs["stats"]
            return result
        current_plan = plan_remediation(inputs["products"], now=plan_time)
        current_plan_hash = _approval_plan_hash(current_plan)
    except (OSError, sqlite3.Error) as exc:
        result = _empty_remediation_approval_result(
            manifest_status="unavailable",
            warning=f"readonly_database_unavailable:{type(exc).__name__}",
            manifest_present=True,
        )
        result["validation"]["integrity_valid"] = True
        return result
    except (TypeError, ValueError) as exc:
        result = _empty_remediation_approval_result(
            manifest_status="unavailable",
            warning=f"remediation_planning_unavailable:{type(exc).__name__}",
            manifest_present=True,
        )
        result["validation"]["integrity_valid"] = True
        return result

    if manifest.source_plan_hash != current_plan_hash:
        result = _empty_remediation_approval_result(
            manifest_status="stale",
            warning="approval_planner_hash_stale",
            manifest_present=True,
        )
        result["stored_plan_approval_status"] = manifest.plan_approval_status
        result["validation"] = {
            "integrity_valid": True,
            "semantic_valid": False,
            "planner_hash_matches": False,
        }
        result["source_stats"] = inputs["stats"]
        return result

    rebuilt = build_approval_manifest(
        current_plan,
        _approval_manifest_selections(manifest),
        decision=manifest.requested_decision,
        reviewer=manifest.reviewer,
        reviewed_at=manifest.reviewed_at,
        policy=manifest.policy,
    )
    if rebuilt != manifest:
        result = _empty_remediation_approval_result(
            manifest_status="invalid",
            warning="approval_manifest_semantics_mismatch",
            manifest_present=True,
        )
        result["stored_plan_approval_status"] = manifest.plan_approval_status
        result["validation"] = {
            "integrity_valid": True,
            "semantic_valid": False,
            "planner_hash_matches": True,
        }
        result["source_stats"] = inputs["stats"]
        return result

    warnings = list(inputs["warnings"])
    result = {
        "version": 1,
        "scope": _remediation_approval_scope(),
        "review_status": manifest.plan_approval_status,
        "manifest_status": "current",
        "manifest_present": True,
        "is_current": True,
        "plan_approval_status": manifest.plan_approval_status,
        "stored_plan_approval_status": manifest.plan_approval_status,
        "execution_status": "not_executed",
        "authorizes_execution": False,
        "validation": {
            "integrity_valid": True,
            "semantic_valid": True,
            "planner_hash_matches": True,
        },
        "approval": manifest.as_dict(),
        "source_stats": inputs["stats"],
        "warnings": warnings,
    }
    return result


def _candidate_rows(conn):
    rows = conn.execute(
        """
        SELECT p.id AS product_id, p.title, p.share_url, p.shop_name, p.price,
               a.evidence_grade, a.score, a.low_follower_verified,
               a.status AS assessment_status, o.raw_signals_json,
               o.cumulative_sales_min, o.sales_24h_min, o.sales_7d_min,
               o.sales_30d_min, o.cart_24h_min, o.new_30d_min,
               o.positive_reviews_30d_min, o.favorites_30d_min,
               o.interested_7d_min, o.interested_30d_min,
               o.viewers_now, o.observed_at,
               se.source_keyword AS search_source_keyword,
               se.result_rank AS search_result_rank,
               se.search_probe_dir AS search_probe_dir,
               (SELECT author_name FROM note_observations no
                WHERE no.product_id=p.id AND no.source='related_note_card'
                ORDER BY no.id DESC LIMIT 1) AS note_author_name,
               (SELECT likes FROM note_observations no
                WHERE no.product_id=p.id AND no.source='related_note_card'
                ORDER BY no.id DESC LIMIT 1) AS note_likes,
               (SELECT collects FROM note_observations no
                WHERE no.product_id=p.id AND no.source='related_note_card'
                ORDER BY no.id DESC LIMIT 1) AS note_collects,
               (SELECT comments FROM note_observations no
                WHERE no.product_id=p.id AND no.source='related_note_card'
                ORDER BY no.id DESC LIMIT 1) AS note_comments,
               (SELECT published_days_ago FROM note_observations no
                WHERE no.product_id=p.id AND no.source='related_note_card'
                ORDER BY no.id DESC LIMIT 1) AS note_published_days_ago,
               (SELECT follower_count FROM note_observations no
                WHERE no.product_id=p.id AND no.source='author_profile_from_note'
                ORDER BY no.id DESC LIMIT 1) AS profile_follower_count,
               (SELECT likes FROM note_observations no
                WHERE no.product_id=p.id AND no.source='author_profile_from_note'
                ORDER BY no.id DESC LIMIT 1) AS profile_total_likes,
                (SELECT follower_count FROM note_observations no
                 WHERE no.product_id=p.id AND no.source='seller_profile_from_product'
                 ORDER BY no.id DESC LIMIT 1) AS seller_follower_count,
                (SELECT CASE
                    WHEN no.follower_count IS NOT NULL THEN 'visible'
                    WHEN json_valid(no.raw_json)
                         AND json_extract(no.raw_json, '$.follower_display_status')='not_displayed'
                        THEN 'not_displayed'
                    ELSE 'missing'
                 END FROM note_observations no
                 WHERE no.product_id=p.id AND no.source='seller_profile_from_product'
                 ORDER BY no.id DESC LIMIT 1) AS seller_follower_display_status,
               (SELECT probe_dir FROM note_observations no
                WHERE no.product_id=p.id AND no.source='related_note_card'
                ORDER BY no.id DESC LIMIT 1) AS note_probe_dir,
               (SELECT probe_dir FROM note_observations no
                WHERE no.product_id=p.id AND no.source='author_profile_from_note'
                ORDER BY no.id DESC LIMIT 1) AS profile_probe_dir,
               EXISTS(
                   SELECT 1 FROM task_results tr
                   WHERE tr.product_id=p.id
                     AND tr.observation_id=o.id
                     AND tr.valid=1
               ) AS task_result_valid
        FROM products p
        JOIN observations o
          ON o.id=(SELECT id FROM observations WHERE product_id=p.id ORDER BY id DESC LIMIT 1)
        LEFT JOIN candidate_assessments a
          ON a.id=(SELECT id FROM candidate_assessments
                   WHERE product_id=p.id ORDER BY id DESC LIMIT 1)
        LEFT JOIN search_result_evidence se
          ON se.id=(SELECT id FROM search_result_evidence
                    WHERE product_id=p.id AND valid=1 ORDER BY id DESC LIMIT 1)
        ORDER BY a.score DESC, a.id DESC
        """
    ).fetchall()
    candidates = []
    for row in rows:
        item = dict(row)
        item["gray_metric_count"] = len(
            gray_metric_items(item.pop("raw_signals_json", None))
        )
        item["task_result_valid"] = bool(item["task_result_valid"])
        follower_count = item["seller_follower_count"]
        follower_display_status = item["seller_follower_display_status"] or "missing"
        item["seller_follower_display_status"] = follower_display_status
        item["hot_metrics_qualified"] = item["gray_metric_count"] >= 3
        item["low_follower_qualified"] = (
            follower_display_status == "visible"
            and follower_count is not None
            and 1 <= int(follower_count) <= 2_000
        )
        item["candidate_qualified"] = bool(
            item["task_result_valid"]
            and item["hot_metrics_qualified"]
            and item["low_follower_qualified"]
        )
        if item["candidate_qualified"]:
            candidates.append(item)
    return candidates


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    scheduler = ContinuousMonitorScheduler(
        settings,
        interval_seconds=_AUTOMATED_ROUND_INTERVAL_SECONDS,
        idle_interval_seconds=_AUTOMATED_IDLE_BACKOFF_SECONDS,
    )
    insight_cache: dict = {"at": 0.0, "value": None}
    insight_lock = threading.Lock()

    def cached_insights(conn) -> dict:
        now = time.monotonic()
        with insight_lock:
            if insight_cache["value"] is not None and now - insight_cache["at"] < 60:
                return insight_cache["value"]
            quality = quality_snapshot(conn, settings, issue_limit=5)
            value = {
                "quality": {
                    "summary": quality["summary"],
                    "scope": quality["scope"],
                    "audited_at": quality["audited_at"],
                },
                "digest": digest_snapshot(conn, period="daily"),
                "portfolio": portfolio_snapshot(
                    conn,
                    settings,
                    per_round_budget=1,
                ),
            }
            insight_cache.update(at=now, value=value)
            return value

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        with connect(settings.db_path) as conn:
            should_run = get_monitor_state(conn).get("desired_state") == "running"
        if should_run:
            scheduler.start()
        try:
            yield
        finally:
            scheduler.stop()

    app = FastAPI(title="小红书虚拟商品选品工作台", lifespan=lifespan)
    app.state.monitor_scheduler = scheduler

    @app.get("/api/status")
    def status():
        with connect(settings.db_path) as conn:
            data = dashboard_stats(conn)
            data["monitor"] = get_monitor_state(conn)
            data["scheduler"] = scheduler.snapshot()
            data.update(cached_insights(conn))
            for row in data["recent"]:
                row["reasons"] = _safe_json_list(row.pop("reasons_json"))
            return data

    @app.get("/api/quality")
    def quality():
        with connect(settings.db_path) as conn:
            return quality_snapshot(conn, settings, issue_limit=100)

    @app.get("/api/digest/{period}")
    def digest(period: str):
        if period not in {"daily", "weekly"}:
            raise HTTPException(404, "摘要周期只支持 daily 或 weekly")
        with connect(settings.db_path) as conn:
            return digest_snapshot(conn, period=period)

    @app.get("/api/portfolio")
    def portfolio():
        with connect(settings.db_path) as conn:
            return portfolio_snapshot(conn, settings, per_round_budget=1)

    @app.get("/api/keyword-suggestions")
    def keyword_suggestions(limit: int = 20):
        max_output = min(50, max(1, int(limit)))
        try:
            return _keyword_suggestions_snapshot(
                settings,
                max_output=max_output,
            )
        except (OSError, sqlite3.Error) as exc:
            return _empty_keyword_review_result(
                max_output=max_output,
                warning=f"readonly_database_unavailable:{type(exc).__name__}",
            )

    @app.get("/api/keyword-pool")
    def keyword_pool():
        try:
            return _keyword_pool_snapshot(settings)
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            return {
                "total_terms": 0,
                "source_product_count": 0,
                "categories": [
                    {
                        "dimension": dimension,
                        "label": label,
                        "count": 0,
                        "terms": [],
                    }
                    for dimension, label in _KEYWORD_POOL_DIMENSIONS
                ],
                "source_products": [],
                "warnings": [f"readonly_keyword_pool_unavailable:{type(exc).__name__}"],
                "scope": {
                    "database_access": "sqlite_mode_ro_query_only",
                    "production_queue_write": False,
                    "search_trigger": False,
                },
            }

    @app.get("/api/keyword-approval-manifest")
    def keyword_approval():
        return _keyword_approval_from_database(settings)

    @app.get("/api/keyword-combination-review")
    def keyword_combination_review():
        try:
            return _keyword_combination_review_snapshot(settings)
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            return _empty_keyword_combination_review(
                f"readonly_keyword_combination_unavailable:{type(exc).__name__}"
            )

    @app.get("/api/remediation-plan")
    def remediation_plan():
        now = datetime.now().astimezone()
        try:
            inputs = _remediation_plan_inputs(settings)
            return _remediation_response(
                inputs["products"],
                now=now,
                source_stats=inputs["stats"],
                warnings=inputs["warnings"],
            )
        except (OSError, sqlite3.Error) as exc:
            return _empty_remediation_result(
                now=now,
                warning=f"readonly_database_unavailable:{type(exc).__name__}",
            )
        except (TypeError, ValueError) as exc:
            return _empty_remediation_result(
                now=now,
                warning=f"remediation_planning_unavailable:{type(exc).__name__}",
            )

    @app.get("/api/approval-manifest")
    def remediation_approval():
        return _remediation_approval_from_database(settings)

    @app.get("/api/soak-readiness")
    def soak_readiness():
        try:
            return _soak_readiness_from_database(settings)
        except (OSError, sqlite3.Error) as exc:
            return _empty_soak_readiness_result(
                warning=f"readonly_database_unavailable:{type(exc).__name__}",
            )
        except (TypeError, ValueError) as exc:
            return _empty_soak_readiness_result(
                warning=f"soak_evidence_unavailable:{type(exc).__name__}",
                input_integrity_gap=str(exc),
            )

    @app.get("/api/monitor/status")
    def monitor_status():
        with connect(settings.db_path) as conn:
            return {
                "state": get_monitor_state(conn),
                "events": recent_run_events(conn, limit=30),
            }

    @app.get("/api/monitor/details/{kind}")
    def monitor_details(kind: str):
        try:
            return _monitor_drilldown_snapshot(settings, kind)
        except KeyError:
            raise HTTPException(404, "不存在这类监控明细")
        except (OSError, sqlite3.Error) as exc:
            raise HTTPException(503, f"监控明细暂时不可用：{type(exc).__name__}")

    @app.post("/api/monitor/pause")
    def monitor_pause():
        with connect(settings.db_path) as conn:
            set_monitor_desired_state(conn, "paused")
            state = get_monitor_state(conn)
        scheduler.wake()
        return state

    @app.post("/api/monitor/resume")
    def monitor_resume():
        with connect(settings.db_path) as conn:
            try:
                set_monitor_desired_state(conn, "running")
            except RiskStopActiveError as exc:
                raise HTTPException(409, str(exc)) from exc
            state = get_monitor_state(conn)
        scheduler.start()
        return {**state, "scheduler": scheduler.snapshot()}

    @app.post("/api/monitor/risk-resume")
    def monitor_risk_resume(request: RiskResumeRequest):
        with connect(settings.db_path) as conn:
            try:
                state = resume_monitor_after_risk(
                    conn,
                    confirm_risk_reason=request.confirm_risk_reason,
                    actor="web",
                )
            except RiskConfirmationError as exc:
                raise HTTPException(409, str(exc)) from exc
        scheduler.start()
        return {**state, "scheduler": scheduler.snapshot()}

    @app.post("/api/monitor/run-once")
    def monitor_run_once(request: MonitorRunRequest | None = None):
        request = request or MonitorRunRequest()
        with connect(settings.db_path) as conn:
            risk_reason = get_monitor_state(conn).get("risk_stop_reason")
        if risk_reason:
            raise HTTPException(
                409,
                f"风险停止仍生效，需先检查页面并明确恢复：{risk_reason}",
            )
        limits = MonitorLimits(
            max_keywords=request.max_keywords,
            max_products_per_keyword=request.max_products_per_keyword,
            wait_seconds=request.wait_seconds,
            metrics_swipe=request.metrics_swipe,
            metrics_max_frames=request.metrics_max_frames,
            note_evidence=request.note_evidence,
            seller_profile=request.seller_profile,
            task_id=request.task_id,
            expected_keyword=request.expected_keyword,
            search_result_rank=request.search_result_rank,
            search_card_scan_limit=request.search_card_scan_limit,
            dry_run=False,
            requeue_due_keywords=False,
        )
        return monitor_once(settings, limits=limits, ignore_paused=True)

    @app.get("/api/run-events")
    def run_events(limit: int = 50):
        with connect(settings.db_path) as conn:
            return recent_run_events(conn, limit=limit)

    @app.get("/reports/latest")
    def latest_report():
        with connect(settings.db_path) as conn:
            report_path = get_monitor_state(conn).get("last_report_path")
        if not report_path:
            raise HTTPException(404, "尚未生成候选分析报告")
        resolved = Path(report_path).resolve()
        reports_root = settings.reports_dir.resolve()
        if reports_root not in resolved.parents or not resolved.is_file():
            raise HTTPException(404, "候选分析报告不存在")
        return FileResponse(
            resolved,
            media_type="text/markdown; charset=utf-8",
            filename=resolved.name,
        )

    @app.get("/products/{product_id}/analysis", response_class=HTMLResponse)
    def product_analysis(product_id: int):
        with connect(settings.db_path) as conn:
            row = conn.execute(
                """
                SELECT p.id AS product_id, p.title, p.shop_name, p.price, p.share_url,
                       o.cumulative_sales_display, o.cumulative_sales_min,
                       o.daily_sales_delta, o.raw_signals_json,
                       a.evidence_grade, a.score, a.reasons_json,
                       se.source_keyword,
                        (SELECT follower_count FROM note_observations no
                        WHERE no.product_id=p.id
                          AND no.source='seller_profile_from_product'
                         ORDER BY no.id DESC LIMIT 1) AS seller_follower_count,
                        (SELECT CASE
                            WHEN no.follower_count IS NOT NULL THEN 'visible'
                            WHEN json_valid(no.raw_json)
                                 AND json_extract(no.raw_json, '$.follower_display_status')='not_displayed'
                                THEN 'not_displayed'
                            ELSE 'missing'
                         END FROM note_observations no
                         WHERE no.product_id=p.id
                           AND no.source='seller_profile_from_product'
                         ORDER BY no.id DESC LIMIT 1) AS seller_follower_display_status,
                       (SELECT id FROM product_keyword_records kr
                        WHERE kr.product_id=p.id
                        ORDER BY kr.id DESC LIMIT 1) AS keyword_record_id
                FROM products p
                JOIN observations o ON o.id=(
                    SELECT id FROM observations latest
                    WHERE latest.product_id=p.id ORDER BY id DESC LIMIT 1
                )
                LEFT JOIN candidate_assessments a ON a.id=(
                    SELECT id FROM candidate_assessments latest_a
                    WHERE latest_a.product_id=p.id ORDER BY id DESC LIMIT 1
                )
                LEFT JOIN search_result_evidence se ON se.id=(
                    SELECT id FROM search_result_evidence latest_se
                    WHERE latest_se.product_id=p.id AND latest_se.valid=1
                    ORDER BY id DESC LIMIT 1
                )
                WHERE p.id=?
                """,
                (product_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(404, "商品不存在")
            data = dict(row)
            daily_sales = latest_daily_sales_result(
                conn,
                product_id=product_id,
            )
            if daily_sales is not None:
                if daily_sales.get("cumulative_sales_display"):
                    data["cumulative_sales_display"] = daily_sales[
                        "cumulative_sales_display"
                    ]
                if daily_sales.get("cumulative_sales_exact") is not None:
                    data["cumulative_sales_min"] = daily_sales[
                        "cumulative_sales_exact"
                    ]
                if daily_sales.get("daily_sales_delta") is not None:
                    data["daily_sales_delta"] = daily_sales[
                        "daily_sales_delta"
                    ]
            terms: dict[str, list[str]] = {
                key: [] for key in ("audience", "domain", "scene", "format", "stage", "function")
            }
            if data["keyword_record_id"]:
                for term in conn.execute(
                    """
                    SELECT dimension, normalized_term
                    FROM product_keyword_terms
                    WHERE record_id=?
                    ORDER BY dimension, id
                    """,
                    (data["keyword_record_id"],),
                ):
                    terms[term["dimension"]].append(term["normalized_term"])

        gray_labels = {
            "cumulative_sales_min": "商品已售",
            "sales_24h_min": "24小时购买",
            "sales_7d_min": "近7天购买",
            "sales_30d_min": "近30天购买",
            "cart_24h_min": "24小时加购",
            "new_30d_min": "近30天新增",
            "positive_reviews_30d_min": "近30天好评",
            "favorites_30d_min": "近30天收藏",
            "interested_7d_min": "近7天感兴趣",
            "interested_30d_min": "近30天感兴趣",
            "viewers_now": "正在看",
            "sales_surging": "销量上升",
        }
        try:
            raw_signals = json.loads(data["raw_signals_json"] or "{}")
        except json.JSONDecodeError:
            raw_signals = {}
        from .signals import gray_metric_items

        gray_items = gray_metric_items(raw_signals)
        follower_count = data["seller_follower_count"]
        follower_display_status = data["seller_follower_display_status"] or "missing"
        if follower_display_status == "not_displayed":
            follower_result = "非低粉爆款（店铺页面未显示粉丝数）"
        elif follower_count is None:
            follower_result = "店铺账号粉丝待补"
        elif 1 <= follower_count <= 2000:
            follower_result = f"低粉爆款（店铺账号粉丝 {follower_count}）"
        else:
            follower_result = f"非低粉爆款（店铺账号粉丝 {follower_count}）"
        hit_result = "符合小爆款入台标准" if len(gray_items) >= 3 else "暂未达到3条灰色指标"
        sales_display = data["cumulative_sales_display"] or data["cumulative_sales_min"] or "-"
        daily_delta = data["daily_sales_delta"]
        delta_display = str(daily_delta) if daily_delta is not None else "待满24小时后计算"
        dimension_labels = {
            "audience": "人群词",
            "domain": "品类词",
            "scene": "场景词",
            "format": "形式词",
            "stage": "阶段词",
            "function": "功能词",
        }
        term_rows = "".join(
            f"<tr><th>{html.escape(dimension_labels[key])}</th>"
            f"<td>{html.escape('、'.join(values) or '未拆出')}</td></tr>"
            for key, values in terms.items()
        )
        gray_html = "".join(
            f"<li>{html.escape(gray_labels.get(item, item))}</li>" for item in gray_items
        ) or "<li>暂无</li>"
        product_link = (
            f'<a class="primary" href="{html.escape(data["share_url"], quote=True)}" '
            'target="_blank" rel="noopener noreferrer">打开小红书商品</a>'
            if data["share_url"]
            else '<span class="muted">商品链接待补采</span>'
        )
        reasons = "；".join(json.loads(data["reasons_json"] or "[]")) or "按灰色指标数量判断"
        return HTMLResponse(
            f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{html.escape(data["title"] or "商品分析")}</title>
<style>
body{{margin:0;background:#f5f7fb;color:#162238;font-family:"Microsoft YaHei",sans-serif}}
main{{max-width:920px;margin:32px auto;padding:0 20px 48px}}
.card{{background:#fff;border:1px solid #e0e6ef;border-radius:16px;padding:24px;margin:16px 0}}
h1{{font-size:25px;margin:0 0 10px}} h2{{font-size:18px;margin:0 0 14px}}
.result{{display:inline-block;background:#fff1cf;color:#8a5a00;border-radius:999px;padding:7px 12px;margin-right:8px}}
.low{{background:#e9f7ee;color:#187744}} .grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
.metric{{background:#f7f9fc;border-radius:12px;padding:14px}} .metric span{{display:block;color:#68758a;font-size:13px}}
.metric strong{{display:block;font-size:22px;margin-top:5px}} table{{width:100%;border-collapse:collapse}}
th,td{{text-align:left;padding:10px;border-bottom:1px solid #edf0f5}} th{{width:110px;color:#68758a}}
.primary{{display:inline-block;background:#142138;color:#fff;text-decoration:none;padding:10px 16px;border-radius:10px}}
.muted{{color:#7b8798}} @media(max-width:680px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><main>
<div class="card"><h1>{html.escape(data["title"] or "-")}</h1>
<p class="muted">{html.escape(data["shop_name"] or "店铺待补")} · 搜索词：{html.escape(data["source_keyword"] or "-")}</p>
<span class="result">{html.escape(hit_result)}</span>
<span class="result low">{html.escape(follower_result)}</span>
<p>{product_link}</p></div>
<div class="card"><h2>完整指标</h2><div class="grid">
<div class="metric"><span>商品价格</span><strong>{html.escape(f"¥{data['price']}" if data['price'] is not None else "待补")}</strong></div>
<div class="metric"><span>商品销量</span><strong>{html.escape(str(sales_display))}</strong></div>
<div class="metric"><span>24小时新增销量</span><strong>{html.escape(delta_display)}</strong></div>
<div class="metric"><span>店铺账号粉丝</span><strong>{html.escape(str(follower_count if follower_count is not None else ("页面未显示" if follower_display_status == "not_displayed" else "待补")))}</strong></div>
</div><h2 style="margin-top:22px">灰色指标（{len(gray_items)}条）</h2><ul>{gray_html}</ul></div>
<div class="card"><h2>关键词拆解</h2><table>{term_rows}</table></div>
<div class="card"><h2>分析结论</h2>
<p>{html.escape(hit_result)}。当前共识别 {len(gray_items)} 条有效灰色指标；{html.escape(follower_result)}。</p>
<p class="muted">候选依据：{html.escape(reasons)}</p></div>
</main></body></html>"""
        )

    @app.put("/api/products/{product_id}/sales-follow")
    def product_sales_follow(product_id: int, request: ProductSalesFollowRequest):
        with connect(settings.db_path) as conn:
            try:
                result = set_product_sales_follow(
                    conn,
                    product_id=product_id,
                    enabled=request.enabled,
                    actor="workbench",
                )
            except KeyError as exc:
                raise HTTPException(404, "商品不存在") from exc
            except ValueError as exc:
                if str(exc) == "product_share_url_missing":
                    raise HTTPException(409, "商品链接待补，暂时不能加入销量监控") from exc
                if str(exc) == "product_direct_url_missing":
                    raise HTTPException(
                        409,
                        "商品直达地址尚未验证，暂时不能加入销量监控",
                    ) from exc
                raise
            result["followed_product_count"] = len(
                followed_product_sales_snapshot(conn)
            )
            return result

    @app.post("/api/products/{product_id}/open-on-device")
    def product_open_on_device(product_id: int):
        scheduler_state = scheduler.snapshot()
        if scheduler_state.get("thread_alive"):
            raise HTTPException(
                409,
                {"code": "device_busy", "message": "自动采集调度器正在运行"},
            )

        with connect(settings.db_path) as conn:
            product = conn.execute(
                "SELECT direct_url FROM products WHERE id=?",
                (product_id,),
            ).fetchone()
            if product is None:
                raise HTTPException(
                    404,
                    {"code": "product_not_found", "message": "商品不存在"},
                )

            direct_url = product["direct_url"]
            if not is_supported_product_direct_url(direct_url):
                raise HTTPException(
                    409,
                    {"code": "invalid_direct_url", "message": "商品手机链接无效"},
                )

            monitor_state = get_monitor_state(conn)
            if monitor_state.get("risk_stop_reason"):
                raise HTTPException(
                    409,
                    {"code": "risk_stop_active", "message": "风险停止仍生效"},
                )
            if monitor_state.get("desired_state") != "paused":
                raise HTTPException(
                    409,
                    {"code": "device_busy", "message": "自动采集未暂停"},
                )

            task_busy = conn.execute(
                """
                SELECT 1 FROM search_tasks
                WHERE status='running'
                   OR COALESCE(run_owner, '') <> ''
                   OR COALESCE(run_lease_expires_at, '') <> ''
                LIMIT 1
                """
            ).fetchone()
            run_lease = conn.execute("SELECT 1 FROM run_leases LIMIT 1").fetchone()
            if task_busy or run_lease:
                raise HTTPException(
                    409,
                    {"code": "device_busy", "message": "设备正被采集任务占用"},
                )

        try:
            result = open_link_on_configured_device(settings, direct_url)
        except DeviceLinkOpenError as exc:
            raise HTTPException(
                exc.status_code,
                {"code": exc.code, "message": exc.message},
            ) from exc
        return {"product_id": product_id, **result}

    @app.post("/api/verify-low-follower/{product_id}")
    def verify_low_follower(product_id: int, evidence: LowFollowerEvidence):
        with connect(settings.db_path) as conn:
            product = conn.execute("SELECT id FROM products WHERE id=?", (product_id,)).fetchone()
            if not product:
                raise HTTPException(404, "商品不存在")
            latest = conn.execute(
                """
                SELECT score, reasons_json FROM candidate_assessments
                WHERE product_id=? ORDER BY id DESC LIMIT 1
                """,
                (product_id,),
            ).fetchone()
            reasons = _safe_json_list(latest["reasons_json"]) if latest else []
            evaluation = evaluate_low_follower_evidence(
                follower_count=evidence.follower_count,
                likes=evidence.likes,
                collects=evidence.collects,
                comments=evidence.comments,
                published_days_ago=evidence.published_days_ago,
            )
            interactions = evaluation["interactions"]
            evaluation_reason = evaluation["reason"]
            if evaluation["verified"]:
                evaluation_reason = (
                    "手工录入数值达到低粉阈值，但尚未通过公开笔记与作者主页证据链核验"
                )
            reasons.append(evaluation_reason)
            now = datetime.now().astimezone().isoformat(timespec="seconds")
            conn.execute(
                """
                INSERT INTO note_evidence(
                    product_id, recorded_at, author_name, follower_count, likes,
                    collects, comments, published_days_ago, source_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_id,
                    now,
                    evidence.author_name,
                    evidence.follower_count,
                    evidence.likes,
                    evidence.collects,
                    evidence.comments,
                    evidence.published_days_ago,
                    evidence.source_note,
                ),
            )
            promotion = promote_candidate_from_note_observations(conn, product_id)
            if promotion.get("verified"):
                return {
                    "grade": "A",
                    "status": "candidate",
                    "verified": True,
                    "manual_threshold_met": evaluation["verified"],
                    "interactions": interactions,
                    "promotion": promotion,
                    "reasons": reasons,
                }
            status_value, grade = "needs_review", "B"
            manual_reason = "手工录入仅用于人工复核，不能替代公开笔记与作者主页证据链"
            if manual_reason not in reasons:
                reasons.append(manual_reason)
            conn.execute(
                """
                INSERT INTO candidate_assessments(
                    product_id, assessed_at, evidence_grade, score,
                    low_follower_verified, reasons_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_id,
                    now,
                    grade,
                    latest["score"] if latest else 0,
                    0,
                    json.dumps(reasons, ensure_ascii=False),
                    status_value,
                ),
            )
        return {
            "grade": grade,
            "status": status_value,
            "verified": False,
            "manual_threshold_met": evaluation["verified"],
            "interactions": interactions,
            "promotion": promotion,
            "reasons": reasons,
        }

    @app.get("/captures/{observation_id}")
    def capture(observation_id: int):
        with connect(settings.db_path) as conn:
            row = conn.execute(
                "SELECT screenshot_path FROM observations WHERE id=?",
                (observation_id,),
            ).fetchone()
        if not row or not row["screenshot_path"]:
            raise HTTPException(404, "截图不存在")
        resolved = Path(row["screenshot_path"]).resolve()
        capture_root = settings.capture_dir.resolve()
        if capture_root not in resolved.parents or not resolved.is_file():
            raise HTTPException(404, "截图不存在")
        return FileResponse(resolved)

    @app.get("/export/candidates.csv")
    def export_candidates():
        with connect(settings.db_path) as conn:
            rows = _candidate_rows(conn)
        output = io.StringIO()
        output.write("\ufeff")
        writer = csv.writer(output)
        writer.writerow(
            [
                "商品",
                "商品原链接",
                "店铺",
                "价格",
                "证据等级",
                "候选分",
                "已验证低粉",
                "累计销量下限",
                "24小时购买下限",
                "近7天购买下限",
                "近30天购买下限",
                "24小时加购下限",
                "近30天新增下限",
                "近30天新增好评下限",
                "近30天新增收藏下限",
                "近7天感兴趣下限",
                "近30天感兴趣下限",
                "正在看",
                "采集时间",
                "搜索来源关键词",
                "搜索结果位次",
                "搜索证据目录",
                "笔记作者",
                "单条笔记点赞",
                "单条笔记收藏",
                "单条笔记评论",
                "笔记发布距今天数",
                "作者粉丝数",
                "账号累计获赞与收藏",
                "笔记证据目录",
                "账号证据目录",
                "店铺粉丝数",
                "店铺粉丝显示状态",
                "正式候选",
            ]
        )
        export_keys = (
            "title", "share_url", "shop_name", "price", "evidence_grade",
            "score", "low_follower_verified", "cumulative_sales_min",
            "sales_24h_min", "sales_7d_min", "sales_30d_min",
            "cart_24h_min", "new_30d_min", "positive_reviews_30d_min",
            "favorites_30d_min", "interested_7d_min", "interested_30d_min",
            "viewers_now", "observed_at", "search_source_keyword",
            "search_result_rank", "search_probe_dir", "note_author_name",
            "note_likes", "note_collects", "note_comments",
            "note_published_days_ago", "profile_follower_count",
            "profile_total_likes", "note_probe_dir", "profile_probe_dir",
            "seller_follower_count", "seller_follower_display_status",
            "candidate_qualified",
        )
        writer.writerows(tuple(row.get(key) for key in export_keys) for row in rows)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=xhs_candidates.csv"},
        )

    @app.get("/", response_class=HTMLResponse)
    def home():
        return render_workbench_html()
        """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>小红书虚拟商品选品工作台</title>
  <style>
    :root { color-scheme: light; font-family: Inter,"Microsoft YaHei",sans-serif; }
    body { margin:0; background:#f7f7f9; color:#1f2328; }
    header { padding:22px 30px; background:#fff; border-bottom:1px solid #e8e8ec; display:flex; align-items:center; justify-content:space-between; gap:18px; }
    h1 { margin:0 0 6px; font-size:22px; }
    h2 { margin:0 0 14px; font-size:17px; }
    .sub { color:#667085; font-size:13px; }
    .button { border:0; text-decoration:none; background:#ff2442; color:#fff; padding:10px 14px; border-radius:8px; font-weight:650; cursor:pointer; }
    .button.secondary { background:#1f2937; }
    main { padding:24px 30px; }
    .cards { display:grid; grid-template-columns:repeat(6,minmax(120px,1fr)); gap:12px; }
    .card,.panel { background:#fff; border:1px solid #e5e7eb; border-radius:8px; box-shadow:0 3px 14px #1018280a; }
    .card { padding:15px; }
    .label { color:#667085; font-size:12px; }
    .value { font-size:26px; font-weight:700; margin-top:7px; }
    .panel { margin-top:16px; padding:18px; overflow:auto; }
    .toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; }
    table { width:100%; border-collapse:collapse; }
    th,td { text-align:left; padding:10px 8px; border-bottom:1px solid #eef0f3; white-space:nowrap; font-size:13px; }
    th { color:#667085; }
    .tag { display:inline-block; border-radius:999px; padding:3px 8px; background:#fff1f2; color:#e11d48; }
    .grade { display:inline-block; min-width:22px; text-align:center; border-radius:6px; padding:3px 7px; background:#eef2ff; color:#4338ca; font-weight:700; }
    .grade.a { background:#dcfce7; color:#15803d; }
    a.shot { color:#2563eb; text-decoration:none; }
    .verify { border:1px solid #d0d5dd; background:#fff; border-radius:7px; padding:6px 9px; cursor:pointer; white-space:nowrap; }
    .evidence { max-width:280px; overflow:hidden; text-overflow:ellipsis; }
    .empty { color:#98a2b3; padding:20px 0; }
    .status { font-weight:700; }
    .check { display:inline-flex; gap:6px; align-items:center; color:#475467; font-size:13px; }
  </style>
</head>
<body>
  <header>
    <div><h1>小红书虚拟商品选品工作台</h1><div class="sub">模拟器采集 · 趋势指标 · 低粉证据 · 自动监控</div></div>
    <a class="button" href="/export/candidates.csv">下载候选 CSV</a>
  </header>
  <main>
    <section class="cards">
      <div class="card"><div class="label">待搜索任务</div><div id="tasks" class="value">-</div></div>
      <div class="card"><div class="label">已发现商品</div><div id="products" class="value">-</div></div>
      <div class="card"><div class="label">观察记录</div><div id="observations" class="value">-</div></div>
      <div class="card"><div class="label">笔记/账号证据</div><div id="noteObservations" class="value">-</div></div>
      <div class="card"><div class="label">候选品</div><div id="candidates" class="value">-</div></div>
      <div class="card"><div class="label">监控状态</div><div id="monitorState" class="value">-</div></div>
    </section>
    <section class="panel">
      <h2>监控控制</h2>
      <div class="toolbar">
        <button class="button" onclick="setMonitor('resume')">恢复监控</button>
        <button class="button secondary" onclick="setMonitor('pause')">暂停监控</button>
        <button class="button secondary" onclick="runOnce()">执行单轮</button>
        <label class="check"><input id="noteEvidence" type="checkbox">采笔记证据</label>
        <span id="monitorDetail" class="sub"></span>
      </div>
    </section>
    <section class="panel"><h2>最新商品观察</h2><div id="recent" class="empty">读取中...</div></section>
  </main>
  <script>
    const n=v=>v ?? "-";
    const safeUrl=v=>typeof v==="string" && /^https?:\\/\\//i.test(v) ? v : null;
    async function setMonitor(action){
      await fetch(`/api/monitor/${action}`,{method:"POST"});
      refresh();
    }
    async function runOnce(){
      monitorDetail.textContent='单轮监控执行中...';
      const r=await fetch('/api/monitor/run-once',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({max_keywords:1,max_products_per_keyword:1,wait_seconds:6,metrics_max_frames:3,metrics_swipe:true,note_evidence:noteEvidence.checked})});
      const out=await r.json();
      alert(`单轮完成：采集 ${out.captured_products || 0} 个商品，笔记证据 ${(out.note_evidence || []).length} 条${out.blocked ? '\\n阻塞：'+out.blocked : ''}`);
      refresh();
    }
    async function refresh(){
      const s=await fetch("/api/status").then(r=>r.json());
      tasks.textContent=s.pending_tasks; products.textContent=s.products;
      observations.textContent=s.observations; candidates.textContent=s.candidates;
      noteObservations.textContent=s.note_observations;
      monitorState.textContent=s.monitor.desired_state || "paused";
      monitorDetail.textContent=`last: ${n(s.monitor.last_heartbeat)} risk: ${n(s.monitor.risk_stop_reason)} block: ${n(s.monitor.last_block_reason)} skip: ${n(s.monitor.last_skip_reason)} report: ${n(s.monitor.last_report_path)}`;
      if(!s.recent.length){ recent.innerHTML='<div class="empty">暂无采集记录</div>'; }
      else {
        recent.innerHTML='<table><thead><tr><th>等级</th><th>商品</th><th>截图</th><th>价格</th><th>分数</th><th>累计</th><th>30天购买</th><th>30天好评</th><th>搜索来源</th><th>笔记点赞</th><th>发布天数</th><th>作者粉丝</th><th>低粉</th><th>证据</th></tr></thead><tbody>'+
          s.recent.map(x=>{const u=safeUrl(x.share_url); return `<tr><td><span class="grade ${x.evidence_grade==='A'?'a':''}">${n(x.evidence_grade)}</span></td><td>${u?`<a class="shot" href="${u}" target="_blank" rel="noopener noreferrer">${n(x.title)}</a>`:`${n(x.title)} <span class="sub">（链接待采集）</span>`}</td><td><a class="shot" href="/captures/${x.observation_id}" target="_blank">证据截图</a></td><td>${n(x.price)}</td><td>${n(x.score)}</td><td>${n(x.cumulative_sales_min)}</td><td>${n(x.sales_30d_min)}</td><td>${n(x.positive_reviews_30d_min)}</td><td>${n(x.search_source_keyword)} #${n(x.search_result_rank)}</td><td>${n(x.note_likes)}</td><td>${n(x.note_published_days_ago)}</td><td>${n(x.note_author_follower_count)}</td><td><button class="verify" onclick="verifyLowFan(${x.product_id})">录入</button></td><td class="evidence" title="${(x.reasons||[]).join('；')}">${(x.reasons||[]).join('；')||'-'}</td></tr>`}).join('')+
          '</tbody></table>';
      }
    }
    async function verifyLowFan(productId){
      const follower_count=Number(prompt("作者粉丝数")); if(!Number.isFinite(follower_count)) return;
      const likes=Number(prompt("笔记点赞数","0")||0);
      const collects=Number(prompt("笔记收藏数","0")||0);
      const comments=Number(prompt("笔记评论数","0")||0);
      const published_days_ago=Number(prompt("发布距今天数","0")||0);
      const r=await fetch(`/api/verify-low-follower/${productId}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({follower_count,likes,collects,comments,published_days_ago})});
      const out=await r.json(); alert(`核验结果：${out.grade}\\n${out.reasons.join("；")}`); refresh();
    }
    refresh(); setInterval(refresh,10000);
  </script>
</body></html>
"""

    return app


app = create_app()
