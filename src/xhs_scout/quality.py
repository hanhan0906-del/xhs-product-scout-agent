from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field as dataclass_field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


Severity = str

TREND_FIELDS: tuple[str, ...] = (
    "cumulative_sales_min",
    "sales_24h_min",
    "sales_7d_min",
    "sales_30d_min",
    "cart_24h_min",
    "new_30d_min",
    "positive_reviews_30d_min",
    "favorites_30d_min",
    "interested_7d_min",
    "interested_30d_min",
    "viewers_now",
)

OCR_POLLUTION_MARKERS: tuple[str, ...] = (
    "加入购物车",
    "立即购买",
    "客服",
    "购物车",
    "首页",
    "消息",
    "关注",
    "粉丝",
    "说点什么",
    "商品评价",
    "店铺口碑",
    "开箱精选",
)

METRIC_TEXT_MARKERS: tuple[str, ...] = (
    "近7天",
    "近30天",
    "24小时",
    "一周内",
    "购买",
    "加购",
    "好评",
    "收藏",
    "感兴趣",
    "正在看",
    "销量飙升",
)

MAX_REASONABLE_PRICE = 100_000
MAX_REASONABLE_METRIC = 10_000_000
DEFAULT_OBSERVATION_MAX_AGE_DAYS = 30


@dataclass(frozen=True)
class QualityIssue:
    severity: Severity
    code: str
    message: str
    entity_type: str
    entity_id: Any = None
    field: str | None = None
    details: dict[str, Any] = dataclass_field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QualityAuditReport:
    issues: list[QualityIssue]
    summary: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "issues": [issue.as_dict() for issue in self.issues],
            "summary": self.summary,
        }


def audit_evidence_records(
    *,
    observations: Iterable[Mapping[str, Any]] = (),
    products: Iterable[Mapping[str, Any]] = (),
    notes: Iterable[Mapping[str, Any]] = (),
    search_evidence: Iterable[Mapping[str, Any]] = (),
    allowed_keywords: Iterable[str] | None = None,
    now: datetime | str | None = None,
    observation_max_age_days: int = DEFAULT_OBSERVATION_MAX_AGE_DAYS,
) -> QualityAuditReport:
    """Audit caller-supplied evidence records without reading or mutating storage."""

    product_rows = [_copy(row) for row in products]
    observation_rows = [_copy(row) for row in observations]
    note_rows = [_copy(row) for row in notes]
    search_rows = [_copy(row) for row in search_evidence]
    product_by_id = {_id(row): row for row in product_rows if _id(row) is not None}
    notes_by_product = _group_by(note_rows, "product_id")
    search_by_observation = _group_by(search_rows, "observation_id")
    search_by_product = _group_by(search_rows, "product_id")
    observation_product_ids = {row.get("product_id") for row in observation_rows}
    valid_keywords = {_normalize_keyword(keyword) for keyword in allowed_keywords or ()}
    now_dt = _parse_datetime(now) or datetime.now(timezone.utc).astimezone()

    issues: list[QualityIssue] = []
    audited_product_ids: set[Any] = set()

    for product in product_rows:
        product_id = _id(product)
        audited_product_ids.add(product_id)
        issues.extend(_audit_product_identity(product))
        if product_id not in observation_product_ids:
            issues.extend(_audit_low_follower_gap(product, notes_by_product.get(product_id, [])))

    for observation in observation_rows:
        product = product_by_id.get(observation.get("product_id"), {})
        merged = {**product, **observation}
        product_id = observation.get("product_id")
        audited_product_ids.add(product_id)
        issues.extend(_audit_product_identity(merged, fallback_entity="observation"))
        issues.extend(_audit_observation(observation, now_dt, observation_max_age_days))
        issues.extend(_audit_trend_metrics(merged, entity_type="observation", entity_id=_id(observation)))
        issues.extend(_audit_ocr_text(observation))

        relevant_search = [
            *search_by_observation.get(_id(observation), []),
            *search_by_product.get(product_id, []),
        ]
        for search in _dedupe_rows(relevant_search):
            issues.extend(_audit_search_evidence(search, valid_keywords))

        relevant_notes = notes_by_product.get(product_id, [])
        issues.extend(_audit_low_follower_gap(merged, relevant_notes))

    for search in search_rows:
        if search.get("observation_id") is None and search.get("product_id") is None:
            issues.extend(_audit_search_evidence(search, valid_keywords))

    for product_id, product_notes in notes_by_product.items():
        if product_id not in audited_product_ids:
            issues.extend(_audit_low_follower_gap({"product_id": product_id}, product_notes))

    issues.extend(_audit_duplicate_products(product_rows))
    issues.extend(_audit_duplicate_observations(observation_rows))
    issues.extend(_audit_duplicate_notes(note_rows))

    return QualityAuditReport(
        issues=issues,
        summary=_summarize_issues(issues),
    )


def _copy(row: Mapping[str, Any]) -> dict[str, Any]:
    return dict(row)


def _id(row: Mapping[str, Any]) -> Any:
    return row.get("id") or row.get("observation_id") or row.get("product_id")


def _issue(
    severity: Severity,
    code: str,
    message: str,
    entity_type: str,
    entity_id: Any = None,
    *,
    field_name: str | None = None,
    details: dict[str, Any] | None = None,
) -> QualityIssue:
    return QualityIssue(
        severity=severity,
        code=code,
        message=message,
        entity_type=entity_type,
        entity_id=entity_id,
        field=field_name,
        details=details or {},
    )


def _audit_product_identity(
    row: Mapping[str, Any],
    *,
    fallback_entity: str = "product",
) -> list[QualityIssue]:
    entity_type = "product" if row.get("id") is not None else fallback_entity
    entity_id = _id(row)
    issues: list[QualityIssue] = []
    if _blank(row.get("title")):
        issues.append(
            _issue(
                "error",
                "missing_title",
                "商品标题缺失，无法稳定识别或人工复核该证据。",
                entity_type,
                entity_id,
                field_name="title",
            )
        )
    if _as_float(row.get("price")) is None:
        issues.append(
            _issue(
                "warning",
                "missing_price",
                "商品价格缺失，ROI 和同品对比需要人工补证。",
                entity_type,
                entity_id,
                field_name="price",
            )
        )
    elif (_as_float(row.get("price")) or 0) <= 0:
        issues.append(
            _issue(
                "error",
                "invalid_price",
                "商品价格小于或等于 0，疑似解析错误。",
                entity_type,
                entity_id,
                field_name="price",
                details={"value": row.get("price")},
            )
        )
    elif (_as_float(row.get("price")) or 0) > MAX_REASONABLE_PRICE:
        issues.append(
            _issue(
                "warning",
                "abnormal_price",
                "商品价格数量级异常，建议回看截图确认小数点或 OCR。",
                entity_type,
                entity_id,
                field_name="price",
                details={"value": row.get("price")},
            )
        )
    if _blank(row.get("share_url")):
        issues.append(
            _issue(
                "error",
                "missing_link",
                "商品原链接缺失，后续无法可靠回访或复核来源。",
                entity_type,
                entity_id,
                field_name="share_url",
            )
        )
    return issues


def _audit_observation(
    row: Mapping[str, Any],
    now_dt: datetime,
    max_age_days: int,
) -> list[QualityIssue]:
    entity_id = _id(row)
    issues: list[QualityIssue] = []
    screenshot_path = row.get("screenshot_path") or row.get("capture_path")
    screenshot_exists = _optional_bool(row.get("screenshot_exists"))
    if screenshot_exists is False:
        issues.append(
            _issue(
                "error",
                "screenshot_missing",
                "调用方标记证据截图不存在，应重新采集或从报告中显式降权。",
                "observation",
                entity_id,
                field_name="screenshot_path",
                details={"screenshot_path": screenshot_path},
            )
        )
    elif _blank(screenshot_path):
        issues.append(
            _issue(
                "warning",
                "missing_screenshot_path",
                "观察记录缺少截图路径，证据链不完整。",
                "observation",
                entity_id,
                field_name="screenshot_path",
            )
        )

    observed_at = _parse_datetime(row.get("observed_at") or row.get("captured_at"))
    if observed_at is None:
        issues.append(
            _issue(
                "warning",
                "missing_observed_at",
                "观察时间缺失，无法判断趋势证据是否过期。",
                "observation",
                entity_id,
                field_name="observed_at",
            )
        )
    else:
        age_days = max(0, (now_dt - observed_at).total_seconds() / 86_400)
        if age_days > max_age_days:
            severity = "error" if age_days > max_age_days * 3 else "warning"
            issues.append(
                _issue(
                    severity,
                    "observation_stale",
                    f"观察记录已超过 {max_age_days} 天，新近趋势判断应重新采集。",
                    "observation",
                    entity_id,
                    field_name="observed_at",
                    details={"age_days": round(age_days, 1), "max_age_days": max_age_days},
                )
            )
    return issues


def _audit_trend_metrics(
    row: Mapping[str, Any],
    *,
    entity_type: str,
    entity_id: Any,
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    metrics = {field_name: _as_int(row.get(field_name)) for field_name in TREND_FIELDS}

    for field_name, value in metrics.items():
        if value is None:
            continue
        if value < 0:
            issues.append(
                _issue(
                    "error",
                    "negative_metric",
                    "趋势指标出现负数，疑似解析或入参错误。",
                    entity_type,
                    entity_id,
                    field_name=field_name,
                    details={"value": value},
                )
            )
        elif value > MAX_REASONABLE_METRIC:
            issues.append(
                _issue(
                    "warning",
                    "abnormal_metric_magnitude",
                    "趋势指标数量级异常，建议回看 OCR 原文。",
                    entity_type,
                    entity_id,
                    field_name=field_name,
                    details={"value": value},
                )
            )

    comparisons = (
        ("sales_24h_min", "sales_7d_min", "24 小时购买量不应大于近 7 天购买量。"),
        ("sales_24h_min", "sales_30d_min", "24 小时购买量不应大于近 30 天购买量。"),
        ("sales_7d_min", "sales_30d_min", "近 7 天购买量不应大于近 30 天购买量。"),
        ("interested_7d_min", "interested_30d_min", "近 7 天感兴趣人数不应大于近 30 天感兴趣人数。"),
    )
    for smaller_window, larger_window, message in comparisons:
        left = metrics[smaller_window]
        right = metrics[larger_window]
        if left is not None and right is not None and left > right:
            issues.append(
                _issue(
                    "error",
                    "metric_window_conflict",
                    message,
                    entity_type,
                    entity_id,
                    field_name=smaller_window,
                    details={smaller_window: left, larger_window: right},
                )
            )

    cumulative = metrics["cumulative_sales_min"]
    for field_name in ("sales_30d_min", "new_30d_min"):
        value = metrics[field_name]
        if cumulative is not None and value is not None and value > cumulative:
            issues.append(
                _issue(
                    "warning",
                    "metric_total_conflict",
                    "近期销量或新增量大于累计销量，可能是 OCR 字段串位或历史累计未刷新。",
                    entity_type,
                    entity_id,
                    field_name=field_name,
                    details={field_name: value, "cumulative_sales_min": cumulative},
                )
            )
    if metrics["viewers_now"] is not None and metrics["viewers_now"] > 1_000_000:
        issues.append(
            _issue(
                "warning",
                "abnormal_viewer_count",
                "正在看人数数量级异常，建议人工确认。",
                entity_type,
                entity_id,
                field_name="viewers_now",
                details={"value": metrics["viewers_now"]},
            )
        )
    return issues


def _audit_ocr_text(row: Mapping[str, Any]) -> list[QualityIssue]:
    text = str(row.get("raw_text") or row.get("text_excerpt") or "")
    if not text.strip():
        return []
    compact = _compact(text)
    marker_hits = sum(1 for marker in OCR_POLLUTION_MARKERS if marker in compact)
    metric_hits = sum(1 for marker in METRIC_TEXT_MARKERS if marker in compact)
    metric_count = sum(_as_int(row.get(field_name)) is not None for field_name in TREND_FIELDS)
    mixed_context = all(marker in compact for marker in ("加入购物车", "立即购买")) and (
        "粉丝" in compact or "说点什么" in compact or "首页" in compact
    )
    half_metric = any(_looks_like_half_metric_line(line) for line in text.splitlines())

    if mixed_context or marker_hits >= 5 or (metric_hits >= 2 and metric_count == 0 and half_metric):
        return [
            _issue(
                "warning",
                "ocr_half_pollution",
                "OCR 文本疑似混入半截指标条、底部按钮或其它页面片段，趋势字段需要降权复核。",
                "observation",
                _id(row),
                field_name="raw_text",
                details={
                    "marker_hits": marker_hits,
                    "metric_marker_hits": metric_hits,
                    "parsed_metric_fields": metric_count,
                },
            )
        ]
    return []


def _audit_search_evidence(
    row: Mapping[str, Any],
    allowed_keywords: set[str],
) -> list[QualityIssue]:
    entity_id = _id(row)
    issues: list[QualityIssue] = []
    source_keyword = row.get("source_keyword") or row.get("search_source_keyword")
    expected_keyword = row.get("task_keyword") or row.get("expected_keyword") or row.get("keyword")
    valid_flag = _optional_bool(row.get("valid"))

    if valid_flag is False:
        issues.append(
            _issue(
                "error",
                "invalid_search_keyword_attribution",
                "搜索结果证据已被调用方标记为无效归属，不应参与候选评分。",
                "search_evidence",
                entity_id,
                field_name="valid",
                details={"invalid_reason": row.get("invalid_reason")},
            )
        )
    if _blank(source_keyword):
        issues.append(
            _issue(
                "warning",
                "missing_search_keyword",
                "搜索证据缺少来源关键词，无法追溯候选归属。",
                "search_evidence",
                entity_id,
                field_name="source_keyword",
            )
        )
    if source_keyword and allowed_keywords and _normalize_keyword(source_keyword) not in allowed_keywords:
        issues.append(
            _issue(
                "error",
                "invalid_search_keyword_attribution",
                "搜索来源关键词不在调用方允许的关键词集合内。",
                "search_evidence",
                entity_id,
                field_name="source_keyword",
                details={"source_keyword": source_keyword},
            )
        )
    if source_keyword and expected_keyword and _normalize_keyword(source_keyword) != _normalize_keyword(expected_keyword):
        issues.append(
            _issue(
                "warning",
                "search_keyword_mismatch",
                "搜索证据来源关键词与任务关键词不一致，可能存在跨任务污染。",
                "search_evidence",
                entity_id,
                field_name="source_keyword",
                details={"source_keyword": source_keyword, "expected_keyword": expected_keyword},
            )
        )
    screenshot_exists = _optional_bool(
        row["search_screenshot_exists"] if "search_screenshot_exists" in row else row.get("screenshot_exists")
    )
    if screenshot_exists is False:
        issues.append(
            _issue(
                "error",
                "screenshot_missing",
                "调用方标记搜索证据截图不存在。",
                "search_evidence",
                entity_id,
                field_name="search_screenshot_path",
                details={"screenshot_path": row.get("search_screenshot_path") or row.get("screenshot_path")},
            )
        )
    return issues


def _audit_low_follower_gap(
    row: Mapping[str, Any],
    notes: list[Mapping[str, Any]],
) -> list[QualityIssue]:
    claimed = _truthy(row.get("low_follower_verified")) or str(row.get("evidence_grade") or "").upper() == "A"
    candidate_like = claimed or str(row.get("evidence_grade") or "").upper() in {"B", "C"} or _as_float(row.get("score")) is not None
    if not candidate_like:
        return []

    entity_id = row.get("product_id") or row.get("id")
    note = _latest_note(notes, kind="note_detail")
    profile = _latest_note(notes, kind="account_profile")
    severity = "error" if claimed else "warning"
    issues: list[QualityIssue] = []

    if note is None:
        issues.append(
            _issue(
                severity,
                "low_follower_evidence_gap",
                "缺少关联公开笔记证据，不能闭环低粉爆款判断。",
                "product",
                entity_id,
                details={"claimed_low_follower_verified": claimed},
            )
        )
    if profile is None:
        issues.append(
            _issue(
                severity,
                "low_follower_evidence_gap",
                "缺少作者公开主页证据，不能确认粉丝数来源。",
                "product",
                entity_id,
                details={"claimed_low_follower_verified": claimed},
            )
        )
    if note is None or profile is None:
        return issues

    note_author = _normalize_author(note.get("author_name"))
    profile_author = _normalize_author(profile.get("author_name"))
    if note_author and profile_author and note_author != profile_author:
        issues.append(
            _issue(
                "error",
                "low_follower_author_mismatch",
                "关联笔记作者与主页作者不一致，不能作为同一低粉证据链。",
                "product",
                entity_id,
                details={"note_author": note.get("author_name"), "profile_author": profile.get("author_name")},
            )
        )

    follower_count = _as_int(profile.get("follower_count"))
    likes = _as_int(note.get("likes"))
    published_days = _as_int(note.get("published_days_ago"))
    if follower_count is None:
        issues.append(
            _issue(
                severity,
                "low_follower_evidence_gap",
                "缺少作者粉丝数，不能确认低粉条件。",
                "product",
                entity_id,
                field_name="follower_count",
            )
        )
    if likes is None:
        issues.append(
            _issue(
                severity,
                "low_follower_evidence_gap",
                "缺少单条笔记点赞数，不能用账号累计获赞替代。",
                "product",
                entity_id,
                field_name="likes",
            )
        )
    if published_days is None:
        issues.append(
            _issue(
                severity,
                "low_follower_evidence_gap",
                "缺少单条笔记发布时间，不能确认是否为近期爆款。",
                "product",
                entity_id,
                field_name="published_days_ago",
            )
        )
    elif published_days > 7:
        issues.append(
            _issue(
                severity,
                "low_follower_note_stale",
                "关联笔记超过近 7 天窗口，低粉爆款证据需要重新补采。",
                "product",
                entity_id,
                field_name="published_days_ago",
                details={"published_days_ago": published_days},
            )
        )
    if follower_count is not None and likes is not None and not (
        (follower_count < 200 and likes >= 100) or (follower_count <= 2_000 and likes >= 1_000)
    ):
        issues.append(
            _issue(
                severity,
                "low_follower_threshold_not_met",
                "当前粉丝数与单条点赞组合不足以自动通过严格低粉判定。",
                "product",
                entity_id,
                details={"follower_count": follower_count, "likes": likes},
            )
        )
    return issues


def _audit_duplicate_products(rows: list[Mapping[str, Any]]) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    groups: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        key = _product_duplicate_key(row)
        if key:
            groups[key].append(row)
    for key, group in groups.items():
        if len(group) <= 1:
            continue
        issues.append(
            _issue(
                "warning",
                "duplicate_product_evidence",
                "发现疑似同商品重复证据，应合并展示或保留为多次观察而非多个商品。",
                "product",
                [_id(row) for row in group],
                details={"duplicate_key": key, "count": len(group)},
            )
        )
    return issues


def _audit_duplicate_observations(rows: list[Mapping[str, Any]]) -> list[QualityIssue]:
    groups: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        product_id = row.get("product_id")
        screenshot_path = row.get("screenshot_path")
        if product_id is None:
            continue
        if screenshot_path:
            key = f"path:{product_id}:{screenshot_path}"
        else:
            key = f"metrics:{product_id}:{_metric_signature(row)}"
        groups[key].append(row)
    return [
        _issue(
            "info",
            "duplicate_observation_evidence",
            "同一商品存在重复观察证据，调用方可在报告中折叠展示。",
            "observation",
            [_id(row) for row in group],
            details={"count": len(group)},
        )
        for group in groups.values()
        if len(group) > 1
    ]


def _audit_duplicate_notes(rows: list[Mapping[str, Any]]) -> list[QualityIssue]:
    groups: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        product_id = row.get("product_id")
        if product_id is None:
            continue
        author = _normalize_author(row.get("author_name"))
        source = row.get("source") or row.get("page_kind")
        screenshot = row.get("screenshot_path") or row.get("probe_dir")
        if author or screenshot:
            groups[f"{product_id}:{source}:{author}:{screenshot}"].append(row)
    return [
        _issue(
            "info",
            "duplicate_note_evidence",
            "同一商品存在重复笔记或主页证据，调用方可在证据链中去重展示。",
            "note",
            [_id(row) for row in group],
            details={"count": len(group)},
        )
        for group in groups.values()
        if len(group) > 1
    ]


def _summarize_issues(issues: list[QualityIssue]) -> dict[str, Any]:
    by_severity = Counter(issue.severity for issue in issues)
    by_code = Counter(issue.code for issue in issues)
    return {
        "issue_count": len(issues),
        "has_errors": bool(by_severity.get("error")),
        "by_severity": {name: by_severity.get(name, 0) for name in ("error", "warning", "info")},
        "by_code": dict(sorted(by_code.items())),
    }


def _group_by(rows: list[Mapping[str, Any]], field_name: str) -> defaultdict[Any, list[Mapping[str, Any]]]:
    grouped: defaultdict[Any, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row.get(field_name)].append(row)
    return grouped


def _dedupe_rows(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    seen: set[int] = set()
    deduped: list[Mapping[str, Any]] = []
    for row in rows:
        marker = id(row)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(row)
    return deduped


def _blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    return value not in (None, "", 0, "0", False)


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return None


def _parse_datetime(value: datetime | str | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc).astimezone()
    return parsed.astimezone()


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _normalize_keyword(value: Any) -> str:
    return _compact(str(value or "")).casefold()


def _normalize_author(value: Any) -> str:
    return _compact(str(value or "")).casefold()


def _product_duplicate_key(row: Mapping[str, Any]) -> str | None:
    if not _blank(row.get("fingerprint")):
        return f"fingerprint:{str(row['fingerprint']).strip()}"
    if not _blank(row.get("share_url")):
        return f"url:{str(row['share_url']).strip().casefold()}"
    title = _compact(str(row.get("title") or "")).casefold()
    shop = _compact(str(row.get("shop_name") or "")).casefold()
    if title and shop:
        return f"title-shop:{title}|{shop}"
    return None


def _metric_signature(row: Mapping[str, Any]) -> str:
    values = tuple((field_name, _as_int(row.get(field_name))) for field_name in TREND_FIELDS)
    return repr(values)


def _looks_like_half_metric_line(line: str) -> bool:
    compact = _compact(line)
    if not compact:
        return False
    has_metric_marker = any(marker in compact for marker in METRIC_TEXT_MARKERS)
    has_number = bool(re.search(r"\d", compact))
    has_complete_target = any(target in compact for target in ("购买", "加购", "好评", "收藏", "感兴趣", "正在看"))
    return has_metric_marker and (not has_number or not has_complete_target)


def _latest_note(rows: list[Mapping[str, Any]], *, kind: str) -> Mapping[str, Any] | None:
    candidates = []
    for row in rows:
        page_kind = row.get("page_kind")
        source = row.get("source")
        if kind == "note_detail" and (page_kind == "note_detail" or source == "related_note_card"):
            candidates.append(row)
        if kind == "account_profile" and (page_kind == "account_profile" or source == "author_profile_from_note"):
            candidates.append(row)
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: str(row.get("captured_at") or row.get("recorded_at") or ""))[-1]
