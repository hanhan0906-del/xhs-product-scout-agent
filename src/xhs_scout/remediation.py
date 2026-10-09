from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from .product_link import is_supported_product_url


STAGE_ORDER = ("identity", "metrics", "note", "profile")
ACTIVE_STATUSES = frozenset({"candidate", "needs_review"})
DEFAULT_QUARANTINE_PRODUCT_IDS = frozenset({20})
_SAFE_TABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True)
class RemediationPolicy:
    per_batch_limit: int = 2
    hourly_visit_limit: int = 6
    product_cooldown_hours: int = 24
    note_max_age_days: int = 7
    profile_min_likes_core: int = 100
    profile_min_likes_borderline: int = 1_000
    low_follower_core_max: int = 199
    low_follower_borderline_max: int = 2_000
    quarantine_product_ids: frozenset[int] = DEFAULT_QUARANTINE_PRODUCT_IDS

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "RemediationPolicy":
        value = value or {}
        quarantine_ids = value.get("quarantine_product_ids", cls.quarantine_product_ids)
        return cls(
            per_batch_limit=max(1, min(2, int(value.get("per_batch_limit", 2)))),
            hourly_visit_limit=max(1, min(6, int(value.get("hourly_visit_limit", 6)))),
            product_cooldown_hours=max(
                1, int(value.get("product_cooldown_hours", 24))
            ),
            note_max_age_days=max(0, int(value.get("note_max_age_days", 7))),
            profile_min_likes_core=max(
                0, int(value.get("profile_min_likes_core", 100))
            ),
            profile_min_likes_borderline=max(
                0, int(value.get("profile_min_likes_borderline", 1_000))
            ),
            low_follower_core_max=max(
                0, int(value.get("low_follower_core_max", 199))
            ),
            low_follower_borderline_max=max(
                0, int(value.get("low_follower_borderline_max", 2_000))
            ),
            quarantine_product_ids=frozenset(int(item) for item in quarantine_ids),
        )


@dataclass(frozen=True)
class PlanItem:
    product_id: int
    status: str
    stage: str
    actions: tuple[str, ...]
    reasons: tuple[str, ...]
    required_before: tuple[str, ...]
    blocks: tuple[str, ...]
    priority: int
    score: float


@dataclass(frozen=True)
class RemediationBatch:
    batch_id: str
    stage: str
    hour_window: int
    max_items: int
    items: tuple[PlanItem, ...]


@dataclass(frozen=True)
class IsolatedItem:
    product_id: int
    code: str
    reason: str
    blocked_by: tuple[str, ...]
    retry_at: str | None = None


@dataclass(frozen=True)
class SkippedItem:
    product_id: int
    code: str
    reason: str


@dataclass(frozen=True)
class RemediationPlan:
    generated_at: str
    policy: RemediationPolicy
    batches: tuple[RemediationBatch, ...]
    isolated: tuple[IsolatedItem, ...]
    skipped: tuple[SkippedItem, ...]
    completed_product_ids: tuple[int, ...]
    excluded_product_ids: tuple[int, ...]

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["policy"]["quarantine_product_ids"] = sorted(
            self.policy.quarantine_product_ids
        )
        return result


def read_fixture_rows(
    connection: sqlite3.Connection,
    *,
    table: str = "remediation_products",
) -> list[dict[str, Any]]:
    """Read a caller-owned SQLite fixture table without changing the connection."""

    if not _SAFE_TABLE_NAME.fullmatch(table):
        raise ValueError("fixture table name must be a simple SQLite identifier")
    cursor = connection.execute(f'SELECT * FROM "{table}"')
    columns = [description[0] for description in cursor.description or ()]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def plan_remediation(
    products: Iterable[Mapping[str, Any]] | sqlite3.Connection,
    *,
    now: datetime | str,
    policy: RemediationPolicy | Mapping[str, Any] | None = None,
    fixture_table: str = "remediation_products",
) -> RemediationPlan:
    """Build an offline plan; this function performs no collection or queue writes."""

    effective_policy = (
        policy
        if isinstance(policy, RemediationPolicy)
        else RemediationPolicy.from_mapping(policy)
    )
    now_dt = _parse_datetime(now)
    rows = (
        read_fixture_rows(products, table=fixture_table)
        if isinstance(products, sqlite3.Connection)
        else [dict(row) for row in products]
    )

    planned: dict[str, list[PlanItem]] = {stage: [] for stage in STAGE_ORDER}
    isolated: list[IsolatedItem] = []
    skipped: list[SkippedItem] = []
    completed: list[int] = []
    excluded: list[int] = []
    seen_ids: set[int] = set()

    for row in rows:
        product_id = _product_id(row)
        if product_id in seen_ids:
            raise ValueError(f"duplicate product_id in remediation input: {product_id}")
        seen_ids.add(product_id)

        status = str(row.get("status") or "candidate").strip().casefold()
        if status not in ACTIVE_STATUSES:
            excluded.append(product_id)
            continue

        isolation = _isolation_for(row, product_id, now_dt, effective_policy)
        if isolation is not None:
            isolated.append(isolation)
            continue

        item = _plan_item(row, product_id, effective_policy)
        if item is None:
            completed.append(product_id)
        elif isinstance(item, SkippedItem):
            skipped.append(item)
        else:
            planned[item.stage].append(item)

    for items in planned.values():
        items.sort(key=_item_sort_key)
    isolated.sort(key=lambda item: (item.product_id, item.code))
    skipped.sort(key=lambda item: (item.product_id, item.code))

    batches = _make_batches(planned, effective_policy)
    return RemediationPlan(
        generated_at=now_dt.isoformat(timespec="seconds"),
        policy=effective_policy,
        batches=tuple(batches),
        isolated=tuple(isolated),
        skipped=tuple(skipped),
        completed_product_ids=tuple(sorted(completed)),
        excluded_product_ids=tuple(sorted(excluded)),
    )


def _isolation_for(
    row: Mapping[str, Any],
    product_id: int,
    now: datetime,
    policy: RemediationPolicy,
) -> IsolatedItem | None:
    latest_search_valid = _optional_bool(row.get("latest_search_attribution_valid"))
    explicitly_quarantined = _bool(row.get("quarantined"))
    forced_snapshot_quarantine = (
        product_id in policy.quarantine_product_ids
        and not _bool(row.get("quarantine_released"))
    )
    if explicitly_quarantined or forced_snapshot_quarantine or latest_search_valid is False:
        return IsolatedItem(
            product_id=product_id,
            code="search_attribution_quarantine",
            reason=(
                "Latest search attribution is invalid or the product is in the "
                "audited quarantine set; only a newly valid search discovery can release it."
            ),
            blocked_by=("new_valid_search_discovery", "manual_release"),
        )

    last_attempt = _parse_optional_datetime(row.get("last_remediation_at"))
    if last_attempt is not None:
        retry_at = last_attempt + timedelta(hours=policy.product_cooldown_hours)
        if now < retry_at:
            return IsolatedItem(
                product_id=product_id,
                code="product_cooldown",
                reason=(
                    f"Product remediation is limited to once every "
                    f"{policy.product_cooldown_hours} hours."
                ),
                blocked_by=("product_cooldown_elapsed",),
                retry_at=retry_at.isoformat(timespec="seconds"),
            )
    return None


def _plan_item(
    row: Mapping[str, Any],
    product_id: int,
    policy: RemediationPolicy,
) -> PlanItem | SkippedItem | None:
    has_search = _bool(row.get("has_valid_search_attribution"))
    has_link = _supported_link(row)
    has_metrics = _has_metrics_strip(row)
    has_note = _bool(row.get("has_note_evidence"))
    has_profile = _bool(row.get("has_profile_evidence"))
    priority = int(row.get("priority") or 0)
    score = float(row.get("score") or 0.0)
    status = str(row.get("status") or "candidate").strip().casefold()

    if not has_search or not has_link:
        actions: list[str] = []
        reasons: list[str] = []
        if not has_search:
            actions.append("rediscover_valid_search_attribution")
            reasons.append("missing_valid_search_attribution")
        if not has_link:
            actions.append("capture_supported_product_link")
            reasons.append("missing_supported_product_link")
        return PlanItem(
            product_id=product_id,
            status=status,
            stage="identity",
            actions=tuple(actions),
            reasons=tuple(reasons),
            required_before=(),
            blocks=("metrics", "note", "profile"),
            priority=priority,
            score=score,
        )

    if not has_metrics:
        return PlanItem(
            product_id=product_id,
            status=status,
            stage="metrics",
            actions=("capture_metrics_strip",),
            reasons=("missing_metrics_strip",),
            required_before=("valid_search_attribution", "supported_product_link"),
            blocks=("note", "profile"),
            priority=priority,
            score=score,
        )

    if not has_note:
        return PlanItem(
            product_id=product_id,
            status=status,
            stage="note",
            actions=("inspect_recent_related_note",),
            reasons=("missing_normalized_note_evidence",),
            required_before=(
                "valid_search_attribution",
                "supported_product_link",
                "metrics_strip",
            ),
            blocks=("profile",),
            priority=priority,
            score=score,
        )

    if has_profile:
        return None

    follower_count = _optional_int(row.get("known_follower_count"))
    if follower_count is not None and follower_count > policy.low_follower_borderline_max:
        return SkippedItem(
            product_id=product_id,
            code="profile_skipped_known_high_follower",
            reason=(
                f"Known follower count {follower_count} exceeds the strict "
                f"low-follower ceiling {policy.low_follower_borderline_max}."
            ),
        )

    profile_reason = _profile_gate_reason(row, policy)
    if profile_reason is not None:
        return SkippedItem(
            product_id=product_id,
            code=profile_reason,
            reason="The normalized note evidence does not pass the profile-visit gate.",
        )

    return PlanItem(
        product_id=product_id,
        status=status,
        stage="profile",
        actions=("inspect_matching_author_profile",),
        reasons=("note_passed_profile_gate",),
        required_before=(
            "valid_search_attribution",
            "supported_product_link",
            "metrics_strip",
            "recent_identifiable_note",
            "note_interaction_gate",
        ),
        blocks=(),
        priority=priority,
        score=score,
    )


def _profile_gate_reason(
    row: Mapping[str, Any],
    policy: RemediationPolicy,
) -> str | None:
    if not _bool(row.get("note_author_identifiable")):
        return "note_author_not_identifiable"
    age = _optional_int(row.get("note_published_days_ago"))
    if age is None or age < 0 or age > policy.note_max_age_days:
        return "note_not_recent"
    likes = _optional_int(row.get("note_likes"))
    if likes is None or likes < policy.profile_min_likes_core:
        return "note_interaction_below_profile_gate"
    follower_ceiling = _optional_int(row.get("potential_follower_ceiling"))
    if follower_ceiling is not None:
        threshold = (
            policy.profile_min_likes_core
            if follower_ceiling <= policy.low_follower_core_max
            else policy.profile_min_likes_borderline
        )
        if follower_ceiling > policy.low_follower_borderline_max or likes < threshold:
            return "note_interaction_below_profile_gate"
    return None


def _make_batches(
    planned: Mapping[str, list[PlanItem]],
    policy: RemediationPolicy,
) -> list[RemediationBatch]:
    batches: list[RemediationBatch] = []
    visit_offset = 0
    for stage in STAGE_ORDER:
        items = planned[stage]
        for index in range(0, len(items), policy.per_batch_limit):
            chunk = tuple(items[index : index + policy.per_batch_limit])
            batches.append(
                RemediationBatch(
                    batch_id=f"{stage}-{index // policy.per_batch_limit + 1:02d}",
                    stage=stage,
                    hour_window=visit_offset // policy.hourly_visit_limit + 1,
                    max_items=policy.per_batch_limit,
                    items=chunk,
                )
            )
            visit_offset += len(chunk)
    return batches


def _item_sort_key(item: PlanItem) -> tuple[int, int, float, int]:
    needs_review_first = 0 if item.status == "needs_review" else 1
    return (needs_review_first, -item.priority, -item.score, item.product_id)


def _supported_link(row: Mapping[str, Any]) -> bool:
    explicit = _optional_bool(row.get("has_supported_product_link"))
    if explicit is not None:
        return explicit
    return is_supported_product_url(row.get("share_url"))


def _has_metrics_strip(row: Mapping[str, Any]) -> bool:
    explicit = _optional_bool(row.get("has_metrics_strip"))
    if explicit is not None:
        return explicit
    value = row.get("raw_signals_json")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return False
    if not isinstance(value, Mapping):
        return False
    strip = value.get("metrics_strip")
    return isinstance(strip, Mapping) and bool(strip.get("frames"))


def _product_id(row: Mapping[str, Any]) -> int:
    value = row.get("product_id", row.get("id"))
    if value is None:
        raise ValueError("each remediation row requires product_id or id")
    return int(value)


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y"}
    return bool(value)


def _optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    return _bool(value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    return _parse_datetime(value)


def _parse_datetime(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
