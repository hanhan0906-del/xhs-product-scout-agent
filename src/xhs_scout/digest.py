from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .low_follower import evaluate_low_follower_evidence, validate_low_follower_evidence_chain


DigestPeriod = Literal["daily", "weekly"]
Severity = Literal["info", "warning", "critical"]


TREND_FIELDS: tuple[tuple[str, str], ...] = (
    ("cumulative_sales_min", "累计销量下限"),
    ("sales_24h_min", "24小时购买下限"),
    ("sales_7d_min", "近7天购买下限"),
    ("sales_30d_min", "近30天购买下限"),
    ("cart_24h_min", "24小时加购下限"),
    ("positive_reviews_30d_min", "近30天新增好评下限"),
    ("favorites_30d_min", "近30天新增收藏下限"),
    ("interested_7d_min", "近7天感兴趣下限"),
    ("interested_30d_min", "近30天感兴趣下限"),
)

FAILED_TASK_STATUSES = {
    "failed",
    "error",
    "needs_manual_detail",
    "risk_stopped",
    "open_error",
}


@dataclass(frozen=True)
class DigestWindow:
    period: DigestPeriod
    start_at: datetime
    end_at: datetime
    timezone_label: str = "local"


@dataclass(frozen=True)
class ProductObservation:
    product_id: int | str
    title: str = ""
    observed_at: datetime | None = None
    source_keyword: str | None = None
    screenshot_path: str | None = None
    metrics: Mapping[str, int | float | str | bool | None] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "ProductObservation":
        metrics = {
            key: row.get(key)
            for key, _label in TREND_FIELDS
            if row.get(key) is not None
        }
        if row.get("sales_surging") not in (None, "", 0, "0", False):
            metrics["sales_surging"] = True
        return cls(
            product_id=row.get("product_id") or row.get("id") or "",
            title=str(row.get("title") or ""),
            observed_at=_parse_datetime(row.get("observed_at") or row.get("captured_at")),
            source_keyword=_first_text(row, "source_keyword", "search_source_keyword"),
            screenshot_path=_first_text(row, "screenshot_path"),
            metrics=metrics,
        )


@dataclass(frozen=True)
class CandidateSnapshot:
    product_id: int | str
    title: str = ""
    assessed_at: datetime | None = None
    evidence_grade: str = ""
    score: float | None = None
    is_new: bool = False
    low_follower_verified: bool = False
    note_author_name: str | None = None
    note_likes: int | None = None
    note_collects: int | None = None
    note_comments: int | None = None
    note_published_days_ago: int | None = None
    profile_author_name: str | None = None
    profile_follower_count: int | None = None
    note_evidence_path: str | None = None
    profile_evidence_path: str | None = None
    search_source_keyword: str | None = None
    search_result_rank: int | None = None

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "CandidateSnapshot":
        return cls(
            product_id=row.get("product_id") or row.get("id") or "",
            title=str(row.get("title") or ""),
            assessed_at=_parse_datetime(row.get("assessed_at") or row.get("first_seen_at")),
            evidence_grade=str(row.get("evidence_grade") or ""),
            score=_as_float(row.get("score")),
            is_new=_as_bool(row.get("is_new")),
            low_follower_verified=_as_bool(row.get("low_follower_verified")),
            note_author_name=_first_text(row, "note_author_name", "latest_note_author_name"),
            note_likes=_as_int(_first_value(row, "note_likes", "latest_note_likes")),
            note_collects=_as_int(_first_value(row, "note_collects", "latest_note_collects")),
            note_comments=_as_int(_first_value(row, "note_comments", "latest_note_comments")),
            note_published_days_ago=_as_int(
                _first_value(row, "note_published_days_ago", "latest_note_published_days_ago")
            ),
            profile_author_name=_first_text(row, "profile_author_name", "latest_profile_author_name"),
            profile_follower_count=_as_int(
                _first_value(row, "profile_follower_count", "latest_profile_follower_count")
            ),
            note_evidence_path=_first_text(row, "note_evidence_path", "latest_note_probe_dir"),
            profile_evidence_path=_first_text(row, "profile_evidence_path", "latest_profile_probe_dir"),
            search_source_keyword=_first_text(row, "search_source_keyword", "source_keyword"),
            search_result_rank=_as_int(_first_value(row, "search_result_rank", "result_rank")),
        )


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: int | str
    keyword: str
    status: str
    attempts: int = 0
    max_attempts: int = 3
    updated_at: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "TaskSnapshot":
        return cls(
            task_id=row.get("task_id") or row.get("id") or "",
            keyword=str(row.get("keyword") or ""),
            status=str(row.get("status") or ""),
            attempts=_as_int(row.get("attempts")) or 0,
            max_attempts=_as_int(row.get("max_attempts")) or 3,
            updated_at=_parse_datetime(row.get("updated_at") or row.get("last_finished_at")),
            last_error=_first_text(row, "last_error", "invalid_reason"),
            consecutive_failures=_as_int(row.get("consecutive_failures")) or 0,
        )


@dataclass(frozen=True)
class MonitorSnapshot:
    desired_state: str = "paused"
    risk_stop_reason: str | None = None
    last_block_reason: str | None = None
    last_skip_reason: str | None = None
    scheduler_running: bool = False
    next_run_at: datetime | None = None
    last_heartbeat: datetime | None = None
    last_run_id: str | None = None

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any] | None) -> "MonitorSnapshot":
        row = row or {}
        return cls(
            desired_state=str(row.get("desired_state") or "paused"),
            risk_stop_reason=_first_text(row, "risk_stop_reason"),
            last_block_reason=_first_text(row, "last_block_reason"),
            last_skip_reason=_first_text(row, "last_skip_reason"),
            scheduler_running=_as_bool(row.get("scheduler_running")),
            next_run_at=_parse_datetime(row.get("next_run_at")),
            last_heartbeat=_parse_datetime(row.get("last_heartbeat")),
            last_run_id=_first_text(row, "last_run_id"),
        )


@dataclass(frozen=True)
class DigestAlert:
    severity: Severity
    title: str
    facts: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    evidence_gaps: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewItem:
    priority: Severity
    title: str
    reason: str
    product_id: int | str | None = None
    task_id: int | str | None = None
    evidence_needed: tuple[str, ...] = ()


@dataclass(frozen=True)
class MonitoringDigest:
    window: DigestWindow
    generated_at: datetime
    stats: Mapping[str, int | float | str]
    facts: tuple[str, ...]
    inferences: tuple[str, ...]
    risks: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    alerts: tuple[DigestAlert, ...]
    review_items: tuple[ReviewItem, ...]


def build_daily_digest(
    *,
    observations: Sequence[ProductObservation | Mapping[str, Any]] = (),
    candidates: Sequence[CandidateSnapshot | Mapping[str, Any]] = (),
    tasks: Sequence[TaskSnapshot | Mapping[str, Any]] = (),
    monitor: MonitorSnapshot | Mapping[str, Any] | None = None,
    generated_at: datetime | str | None = None,
    timezone_label: str = "local",
    evidence_root: str | Path | None = None,
) -> MonitoringDigest:
    end_at = _coerce_datetime(generated_at) or _now()
    return build_digest(
        period="daily",
        start_at=end_at - timedelta(days=1),
        end_at=end_at,
        timezone_label=timezone_label,
        observations=observations,
        candidates=candidates,
        tasks=tasks,
        monitor=monitor,
        evidence_root=evidence_root,
    )


def build_weekly_digest(
    *,
    observations: Sequence[ProductObservation | Mapping[str, Any]] = (),
    candidates: Sequence[CandidateSnapshot | Mapping[str, Any]] = (),
    tasks: Sequence[TaskSnapshot | Mapping[str, Any]] = (),
    monitor: MonitorSnapshot | Mapping[str, Any] | None = None,
    generated_at: datetime | str | None = None,
    timezone_label: str = "local",
    evidence_root: str | Path | None = None,
) -> MonitoringDigest:
    end_at = _coerce_datetime(generated_at) or _now()
    return build_digest(
        period="weekly",
        start_at=end_at - timedelta(days=7),
        end_at=end_at,
        timezone_label=timezone_label,
        observations=observations,
        candidates=candidates,
        tasks=tasks,
        monitor=monitor,
        evidence_root=evidence_root,
    )


def build_digest(
    *,
    period: DigestPeriod,
    start_at: datetime | str,
    end_at: datetime | str,
    timezone_label: str = "local",
    observations: Sequence[ProductObservation | Mapping[str, Any]] = (),
    candidates: Sequence[CandidateSnapshot | Mapping[str, Any]] = (),
    tasks: Sequence[TaskSnapshot | Mapping[str, Any]] = (),
    monitor: MonitorSnapshot | Mapping[str, Any] | None = None,
    trend_growth_ratio: float = 0.25,
    trend_fall_ratio: float = 0.25,
    failure_rate_threshold: float = 0.30,
    consecutive_failure_threshold: int = 3,
    stale_after_hours: int | None = None,
    evidence_root: str | Path | None = None,
) -> MonitoringDigest:
    window = DigestWindow(
        period=period,
        start_at=_require_datetime(start_at),
        end_at=_require_datetime(end_at),
        timezone_label=timezone_label,
    )
    stale_after = timedelta(hours=stale_after_hours or (30 if period == "daily" else 72))
    observation_items = tuple(_coerce_observation(item) for item in observations)
    candidate_items = tuple(_coerce_candidate(item) for item in candidates)
    task_items = tuple(_coerce_task(item) for item in tasks)
    monitor_item = _coerce_monitor(monitor)
    resolved_evidence_root = Path(evidence_root or Path(__file__).resolve().parents[2] / "data")

    facts: list[str] = []
    inferences: list[str] = []
    risks: list[str] = []
    evidence_gaps: list[str] = []
    alerts: list[DigestAlert] = []
    review_items: list[ReviewItem] = []

    recent_observations = tuple(
        item for item in observation_items if _in_window(item.observed_at, window)
    )
    recent_candidates = tuple(
        item
        for item in candidate_items
        if item.is_new or _in_window(item.assessed_at, window)
    )

    facts.append(
        f"时间口径：{_period_label(period)}，{_fmt_dt(window.start_at)} 至 {_fmt_dt(window.end_at)}（{timezone_label}）。"
    )
    facts.append(f"本窗口新增观察 {len(recent_observations)} 条，新增候选 {len(recent_candidates)} 个。")
    if recent_candidates:
        facts.append("新增候选：" + "；".join(_candidate_label(item) for item in recent_candidates))

    trend_facts, trend_inferences, trend_risks = _summarize_trends(
        observation_items,
        window,
        growth_ratio=trend_growth_ratio,
        fall_ratio=trend_fall_ratio,
    )
    facts.extend(trend_facts)
    inferences.extend(trend_inferences)
    risks.extend(trend_risks)

    low_follower_complete = 0
    for candidate in candidate_items:
        status = _low_follower_status(candidate, resolved_evidence_root)
        if status["complete"]:
            low_follower_complete += 1
        if status["facts"] and (candidate in recent_candidates or not status["complete"]):
            facts.extend(status["facts"])
        evidence_gaps.extend(status["gaps"])
        risks.extend(status["risks"])
        if status["needs_review"]:
            review_items.append(
                ReviewItem(
                    priority="warning",
                    title=f"复核低粉证据：{candidate.title or candidate.product_id}",
                    reason="低粉、近期和单条笔记互动证据尚未闭环。",
                    product_id=candidate.product_id,
                    evidence_needed=tuple(status["gaps"]),
                )
            )

    task_alerts, task_facts, task_risks, task_reviews, failure_rate = _summarize_tasks(
        task_items,
        failure_rate_threshold=failure_rate_threshold,
        consecutive_failure_threshold=consecutive_failure_threshold,
    )
    alerts.extend(task_alerts)
    facts.extend(task_facts)
    risks.extend(task_risks)
    review_items.extend(task_reviews)

    monitor_alerts, monitor_facts, monitor_risks, monitor_gaps = _summarize_monitor(
        monitor_item,
        window.end_at,
        stale_after,
    )
    alerts.extend(monitor_alerts)
    facts.extend(monitor_facts)
    risks.extend(monitor_risks)
    evidence_gaps.extend(monitor_gaps)

    stale_alerts, stale_gaps = _summarize_staleness(
        observation_items,
        window.end_at,
        stale_after,
    )
    alerts.extend(stale_alerts)
    evidence_gaps.extend(stale_gaps)

    if not trend_facts:
        evidence_gaps.append("本窗口没有可比较的趋势变化；需要至少两次同商品观察才能判断增长或回落。")
    if not candidate_items:
        evidence_gaps.append("调用方未传入候选数据，无法生成候选复核清单。")

    stats = {
        "period": period,
        "observations_total": len(observation_items),
        "observations_in_window": len(recent_observations),
        "candidates_total": len(candidate_items),
        "new_candidates": len(recent_candidates),
        "low_follower_complete": low_follower_complete,
        "tasks_total": len(task_items),
        "failed_tasks": sum(1 for task in task_items if _is_failed_task(task)),
        "failure_rate": round(failure_rate, 4),
        "alerts": len(alerts),
        "manual_review_items": len(review_items),
    }

    return MonitoringDigest(
        window=window,
        generated_at=window.end_at,
        stats=stats,
        facts=tuple(_dedupe(facts)),
        inferences=tuple(_dedupe(inferences)),
        risks=tuple(_dedupe(risks)),
        evidence_gaps=tuple(_dedupe(evidence_gaps)),
        alerts=tuple(_sort_alerts(alerts)),
        review_items=tuple(_sort_reviews(review_items)),
    )


def render_digest_markdown(digest: MonitoringDigest) -> str:
    lines = [
        f"# 小红书选品监控{_period_label(digest.window.period)}摘要",
        "",
        f"- 生成时间：{_fmt_dt(digest.generated_at)}",
        f"- 时间口径：{_fmt_dt(digest.window.start_at)} 至 {_fmt_dt(digest.window.end_at)}（{digest.window.timezone_label}）",
        f"- 新增观察：{digest.stats['observations_in_window']}",
        f"- 新增候选：{digest.stats['new_candidates']}",
        f"- 低粉证据闭环候选：{digest.stats['low_follower_complete']}",
        f"- 失败率：{float(digest.stats['failure_rate']) * 100:.1f}%",
        "",
    ]
    lines.extend(_markdown_section("事实", digest.facts))
    lines.extend(_markdown_section("推断", digest.inferences))
    lines.extend(_markdown_section("风险", digest.risks))
    lines.extend(_markdown_section("证据缺口", digest.evidence_gaps))
    lines.extend(_alert_section(digest.alerts))
    lines.extend(_review_section(digest.review_items))
    return "\n".join(lines).rstrip() + "\n"


def _summarize_trends(
    observations: Sequence[ProductObservation],
    window: DigestWindow,
    *,
    growth_ratio: float,
    fall_ratio: float,
) -> tuple[list[str], list[str], list[str]]:
    facts: list[str] = []
    inferences: list[str] = []
    risks: list[str] = []
    grouped: dict[int | str, list[ProductObservation]] = {}
    for item in observations:
        grouped.setdefault(item.product_id, []).append(item)

    for product_observations in grouped.values():
        ordered = sorted(product_observations, key=lambda item: item.observed_at or datetime.min.replace(tzinfo=timezone.utc))
        latest = ordered[-1]
        previous = ordered[-2] if len(ordered) >= 2 else None
        title = latest.title or str(latest.product_id)
        if latest.metrics.get("sales_surging") is True and _in_window(latest.observed_at, window):
            facts.append(f"{title}：页面标记销量飙升。")
            inferences.append(f"{title} 出现平台趋势提示，但仍需结合销量字段和时间窗口复核。")
        if previous is None:
            continue
        for key, label in TREND_FIELDS:
            latest_value = _as_float(latest.metrics.get(key))
            previous_value = _as_float(previous.metrics.get(key))
            if latest_value is None or previous_value is None:
                continue
            delta = latest_value - previous_value
            if previous_value > 0:
                ratio = delta / previous_value
            else:
                ratio = 1.0 if delta > 0 else 0.0
            if delta > 0 and ratio >= growth_ratio and _in_window(latest.observed_at, window):
                facts.append(
                    f"{title}：{label}从 {_fmt_number(previous_value)} 增至 {_fmt_number(latest_value)}。"
                )
                inferences.append(f"{title} 的 {label} 增长明显，适合进入优先人工复核。")
            if delta < 0 and abs(ratio) >= fall_ratio and _in_window(latest.observed_at, window):
                facts.append(
                    f"{title}：{label}从 {_fmt_number(previous_value)} 回落至 {_fmt_number(latest_value)}。"
                )
                risks.append(f"{title} 的 {label} 出现回落，可能错过复刻窗口或采集口径发生变化。")
    return facts, inferences, risks


def _summarize_tasks(
    tasks: Sequence[TaskSnapshot],
    *,
    failure_rate_threshold: float,
    consecutive_failure_threshold: int,
) -> tuple[list[DigestAlert], list[str], list[str], list[ReviewItem], float]:
    if not tasks:
        return [], ["调用方未传入任务状态数据。"], [], [], 0.0
    failed = [task for task in tasks if _is_failed_task(task)]
    failure_rate = len(failed) / len(tasks)
    facts = [f"任务状态：共 {len(tasks)} 个，失败/需人工处理 {len(failed)} 个。"]
    risks: list[str] = []
    alerts: list[DigestAlert] = []
    reviews: list[ReviewItem] = []
    if failure_rate >= failure_rate_threshold and failed:
        alerts.append(
            DigestAlert(
                severity="warning",
                title="任务失败率偏高",
                facts=(f"失败率 {failure_rate * 100:.1f}%，阈值 {failure_rate_threshold * 100:.1f}%。",),
                risks=("继续扩大队列可能放大错链、页面打开失败或人工处理积压。",),
            )
        )
    for task in failed:
        if task.attempts >= task.max_attempts or task.consecutive_failures >= consecutive_failure_threshold:
            alerts.append(
                DigestAlert(
                    severity="warning",
                    title=f"连续失败任务：{task.keyword}",
                    facts=(f"任务 {task.task_id} 状态 {task.status}，attempts={task.attempts}/{task.max_attempts}。",),
                    risks=("继续自动重试前应先复核页面类型、关键词归属和打开页证据。",),
                    evidence_gaps=((task.last_error or "缺少失败原因文本"),),
                )
            )
        reviews.append(
            ReviewItem(
                priority="warning",
                title=f"复核任务：{task.keyword}",
                reason=task.last_error or f"任务状态为 {task.status}",
                task_id=task.task_id,
                evidence_needed=("失败截图或 probe 目录", "页面类型", "关键词归属证据"),
            )
        )
    if failed:
        risks.append("失败任务需要先定位原因，再进入小时级或无人值守调度。")
    return alerts, facts, risks, reviews, failure_rate


def _summarize_monitor(
    monitor: MonitorSnapshot,
    end_at: datetime,
    stale_after: timedelta,
) -> tuple[list[DigestAlert], list[str], list[str], list[str]]:
    facts = [f"监控状态：desired_state={monitor.desired_state}，scheduler_running={monitor.scheduler_running}。"]
    risks: list[str] = []
    gaps: list[str] = []
    alerts: list[DigestAlert] = []
    if monitor.risk_stop_reason:
        alerts.append(
            DigestAlert(
                severity="critical",
                title="风控停机",
                facts=(f"risk_stop_reason={monitor.risk_stop_reason}",),
                risks=("必须人工确认页面、账号和风控状态后才能恢复监控。",),
            )
        )
    if monitor.last_block_reason:
        alerts.append(
            DigestAlert(
                severity="warning",
                title="存在最近阻塞",
                facts=(f"last_block_reason={monitor.last_block_reason}",),
                risks=("阻塞原因未清理前不应扩大任务队列。",),
            )
        )
    if monitor.last_skip_reason:
        facts.append(f"最近跳过原因：{monitor.last_skip_reason}")
    if monitor.last_heartbeat is None:
        gaps.append("缺少 last_heartbeat，无法判断调度器新鲜度。")
    elif end_at - monitor.last_heartbeat > stale_after:
        alerts.append(
            DigestAlert(
                severity="warning",
                title="调度心跳陈旧",
                facts=(f"last_heartbeat={_fmt_dt(monitor.last_heartbeat)}",),
                risks=("调度器可能已停止或状态没有被调用方刷新。",),
            )
        )
    return alerts, facts, risks, gaps


def _summarize_staleness(
    observations: Sequence[ProductObservation],
    end_at: datetime,
    stale_after: timedelta,
) -> tuple[list[DigestAlert], list[str]]:
    observed_times = [item.observed_at for item in observations if item.observed_at is not None]
    if not observed_times:
        return [
            DigestAlert(
                severity="warning",
                title="缺少观察数据",
                evidence_gaps=("调用方未传入任何带 observed_at 的商品观察。",),
            )
        ], ["缺少带时间戳的商品观察，无法判断数据是否陈旧。"]
    latest = max(observed_times)
    if end_at - latest <= stale_after:
        return [], []
    return [
        DigestAlert(
            severity="warning",
            title="商品观察数据陈旧",
            facts=(f"最新商品观察时间为 {_fmt_dt(latest)}。",),
            risks=("当前摘要可能无法反映近实时趋势。",),
        )
    ], [f"最新商品观察已超过 {_fmt_timedelta(stale_after)} 未刷新。"]


def _low_follower_status(
    candidate: CandidateSnapshot,
    evidence_root: str | Path,
) -> dict[str, Any]:
    facts: list[str] = []
    gaps: list[str] = []
    risks: list[str] = []
    complete = False
    if candidate.profile_follower_count is None:
        gaps.append(f"{candidate.title or candidate.product_id} 缺少作者粉丝数。")
    if candidate.note_likes is None:
        gaps.append(f"{candidate.title or candidate.product_id} 缺少单条笔记点赞数。")
    if candidate.note_published_days_ago is None:
        gaps.append(f"{candidate.title or candidate.product_id} 缺少单条笔记发布时间。")
    if not candidate.note_evidence_path:
        gaps.append(f"{candidate.title or candidate.product_id} 缺少公开笔记证据目录。")
    if not candidate.profile_evidence_path:
        gaps.append(f"{candidate.title or candidate.product_id} 缺少作者主页证据目录。")
    chain = validate_low_follower_evidence_chain(
        note_author_name=candidate.note_author_name,
        profile_author_name=candidate.profile_author_name,
        note_evidence_path=candidate.note_evidence_path,
        profile_evidence_path=candidate.profile_evidence_path,
        evidence_root=evidence_root,
    )
    if not candidate.note_author_name or not candidate.profile_author_name:
        gaps.append(f"{candidate.title or candidate.product_id} 缺少笔记作者或主页作者名。")
    elif not chain["authors_match"]:
        gaps.append(f"{candidate.title or candidate.product_id} 的笔记作者与主页作者不一致。")
    if candidate.note_evidence_path and not chain["note_evidence_valid"]:
        gaps.append(f"{candidate.title or candidate.product_id} 的公开笔记证据路径不存在或越界。")
    if candidate.profile_evidence_path and not chain["profile_evidence_valid"]:
        gaps.append(f"{candidate.title or candidate.product_id} 的作者主页证据路径不存在或越界。")

    if candidate.profile_follower_count is not None and candidate.profile_follower_count >= 10000:
        risks.append(f"{candidate.title or candidate.product_id} 作者粉丝不少于1万，存在高权重账号风险。")
    if candidate.note_published_days_ago is not None and candidate.note_published_days_ago > 7:
        risks.append(f"{candidate.title or candidate.product_id} 关联笔记发布距今 {candidate.note_published_days_ago} 天，不符合近7天优先口径。")

    complete = _strict_low_follower_complete(candidate, evidence_root, chain=chain)
    if complete:
        facts.append(f"{candidate.title or candidate.product_id} 已具备近期低粉单条笔记互动闭环。")
    return {
        "complete": complete,
        "facts": facts,
        "gaps": gaps,
        "risks": risks,
        "needs_review": bool(gaps or risks or not complete),
    }


def _strict_low_follower_complete(
    candidate: CandidateSnapshot,
    evidence_root: str | Path,
    *,
    chain: Mapping[str, Any] | None = None,
) -> bool:
    if candidate.profile_follower_count is None or candidate.note_likes is None:
        return False
    if candidate.note_published_days_ago is None or candidate.note_published_days_ago > 7:
        return False
    chain = chain or validate_low_follower_evidence_chain(
        note_author_name=candidate.note_author_name,
        profile_author_name=candidate.profile_author_name,
        note_evidence_path=candidate.note_evidence_path,
        profile_evidence_path=candidate.profile_evidence_path,
        evidence_root=evidence_root,
    )
    if not chain["valid"]:
        return False
    return bool(
        evaluate_low_follower_evidence(
            follower_count=candidate.profile_follower_count,
            likes=candidate.note_likes,
            collects=candidate.note_collects or 0,
            comments=candidate.note_comments or 0,
            published_days_ago=candidate.note_published_days_ago,
        )["verified"]
    )


def _alert_section(alerts: Sequence[DigestAlert]) -> list[str]:
    if not alerts:
        return ["## 告警", "", "- 暂无告警。", ""]
    lines = ["## 告警", ""]
    for alert in alerts:
        lines.append(f"### [{alert.severity}] {alert.title}")
        lines.extend(_prefixed("事实", alert.facts))
        lines.extend(_prefixed("风险", alert.risks))
        lines.extend(_prefixed("证据缺口", alert.evidence_gaps))
        lines.append("")
    return lines


def _review_section(items: Sequence[ReviewItem]) -> list[str]:
    if not items:
        return ["## 下一步人工复核清单", "", "- 暂无必须人工复核项。", ""]
    lines = ["## 下一步人工复核清单", ""]
    for index, item in enumerate(items, start=1):
        target = f"product_id={item.product_id}" if item.product_id is not None else f"task_id={item.task_id}"
        lines.append(f"{index}. [{item.priority}] {item.title}（{target}）")
        lines.append(f"   - 原因：{item.reason}")
        if item.evidence_needed:
            lines.append(f"   - 需补证据：{'；'.join(item.evidence_needed)}")
    lines.append("")
    return lines


def _markdown_section(title: str, items: Sequence[str]) -> list[str]:
    lines = [f"## {title}", ""]
    lines.extend(f"- {item}" for item in (items or ("暂无。",)))
    lines.append("")
    return lines


def _prefixed(label: str, items: Sequence[str]) -> list[str]:
    if not items:
        return []
    return [f"- {label}：{item}" for item in items]


def _coerce_observation(item: ProductObservation | Mapping[str, Any]) -> ProductObservation:
    if isinstance(item, ProductObservation):
        return item
    return ProductObservation.from_mapping(item)


def _coerce_candidate(item: CandidateSnapshot | Mapping[str, Any]) -> CandidateSnapshot:
    if isinstance(item, CandidateSnapshot):
        return item
    return CandidateSnapshot.from_mapping(item)


def _coerce_task(item: TaskSnapshot | Mapping[str, Any]) -> TaskSnapshot:
    if isinstance(item, TaskSnapshot):
        return item
    return TaskSnapshot.from_mapping(item)


def _coerce_monitor(item: MonitorSnapshot | Mapping[str, Any] | None) -> MonitorSnapshot:
    if isinstance(item, MonitorSnapshot):
        return item
    return MonitorSnapshot.from_mapping(item)


def _is_failed_task(task: TaskSnapshot) -> bool:
    return task.status in FAILED_TASK_STATUSES or task.consecutive_failures > 0


def _in_window(value: datetime | None, window: DigestWindow) -> bool:
    return value is not None and window.start_at <= value <= window.end_at


def _period_label(period: DigestPeriod) -> str:
    return "每日" if period == "daily" else "每周"


def _candidate_label(candidate: CandidateSnapshot) -> str:
    score = "" if candidate.score is None else f" / {candidate.score:g}分"
    grade = "" if not candidate.evidence_grade else f" / {candidate.evidence_grade}级"
    return f"{candidate.title or candidate.product_id}{grade}{score}"


def _sort_alerts(alerts: Sequence[DigestAlert]) -> list[DigestAlert]:
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(alerts, key=lambda alert: order[alert.severity])


def _sort_reviews(items: Sequence[ReviewItem]) -> list[ReviewItem]:
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(items, key=lambda item: order[item.priority])


def _dedupe(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _first_value(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _first_text(row: Mapping[str, Any], *keys: str) -> str | None:
    value = _first_value(row, *keys)
    if value is None:
        return None
    return str(value)


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    return _coerce_datetime(value)


def _coerce_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    raise TypeError(f"Unsupported datetime value: {value!r}")


def _require_datetime(value: datetime | str) -> datetime:
    result = _coerce_datetime(value)
    if result is None:
        raise ValueError("datetime value is required")
    return result


def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def _fmt_dt(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _fmt_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:g}"


def _fmt_timedelta(value: timedelta) -> str:
    hours = int(value.total_seconds() // 3600)
    if hours % 24 == 0:
        return f"{hours // 24} 天"
    return f"{hours} 小时"


def _norm_text(value: str) -> str:
    return "".join(str(value or "").split()).casefold()
