from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
STAGE_ORDER = ("identity", "metrics", "note", "profile")
STAGE_INDEX = {stage: index for index, stage in enumerate(STAGE_ORDER)}
ACTIVE_STATUSES = frozenset({"candidate", "needs_review"})
DEFAULT_QUARANTINE_PRODUCT_IDS = frozenset({20})
DEFAULT_LOW_FOLLOWER_STOP_PRODUCT_IDS = frozenset({19, 20})
PER_BATCH_HARD_LIMIT = 2
HOURLY_VISIT_HARD_LIMIT = 6
APPROVAL_DECISIONS = frozenset({"pending_review", "approve", "reject"})
APPROVAL_STATUSES = frozenset({"pending_review", "planned_approved", "rejected"})
EXECUTION_STATUS = "not_executed"

_REQUIRED_BEFORE = {
    "identity": (),
    "metrics": ("valid_search_attribution", "supported_product_link"),
    "note": (
        "valid_search_attribution",
        "supported_product_link",
        "metrics_strip",
    ),
    "profile": (
        "valid_search_attribution",
        "supported_product_link",
        "metrics_strip",
        "recent_identifiable_note",
        "note_interaction_gate",
    ),
}
_EXPECTED_BLOCKS = {
    "identity": ("metrics", "note", "profile"),
    "metrics": ("note", "profile"),
    "note": ("profile",),
    "profile": (),
}
_ALLOWED_ACTIONS = {
    "identity": frozenset(
        {
            "rediscover_valid_search_attribution",
            "capture_supported_product_link",
        }
    ),
    "metrics": frozenset({"capture_metrics_strip"}),
    "note": frozenset({"inspect_recent_related_note"}),
    "profile": frozenset({"inspect_matching_author_profile"}),
}
_STOP_SKIP_CODES = frozenset(
    {
        "profile_skipped_known_high_follower",
        "note_author_not_identifiable",
        "note_not_recent",
        "note_interaction_below_profile_gate",
    }
)


class RemediationApprovalError(ValueError):
    """Raised when a stored approval manifest is malformed or tampered with."""


class RemediationApprovalIntegrityError(RemediationApprovalError):
    """Raised when a stored manifest does not match its integrity hash."""


@dataclass(frozen=True)
class ApprovalPolicy:
    per_batch_limit: int = PER_BATCH_HARD_LIMIT
    hourly_visit_limit: int = HOURLY_VISIT_HARD_LIMIT
    quarantine_product_ids: frozenset[int] = DEFAULT_QUARANTINE_PRODUCT_IDS
    low_follower_stop_product_ids: frozenset[int] = (
        DEFAULT_LOW_FOLLOWER_STOP_PRODUCT_IDS
    )

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any] | None = None
    ) -> "ApprovalPolicy":
        value = value or {}
        return cls(
            per_batch_limit=max(
                1,
                min(PER_BATCH_HARD_LIMIT, int(value.get("per_batch_limit", 2))),
            ),
            hourly_visit_limit=max(
                1,
                min(HOURLY_VISIT_HARD_LIMIT, int(value.get("hourly_visit_limit", 6))),
            ),
            quarantine_product_ids=frozenset(
                int(item)
                for item in value.get(
                    "quarantine_product_ids", DEFAULT_QUARANTINE_PRODUCT_IDS
                )
            )
            | DEFAULT_QUARANTINE_PRODUCT_IDS,
            low_follower_stop_product_ids=frozenset(
                int(item)
                for item in value.get(
                    "low_follower_stop_product_ids",
                    DEFAULT_LOW_FOLLOWER_STOP_PRODUCT_IDS,
                )
            )
            | DEFAULT_LOW_FOLLOWER_STOP_PRODUCT_IDS,
        )


@dataclass(frozen=True)
class ApprovalIssue:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class SelectedItem:
    product_id: int
    status: str
    stage: str
    actions: tuple[str, ...]
    required_before: tuple[str, ...]


@dataclass(frozen=True)
class SelectedBatch:
    batch_id: str
    stage: str
    hour_window: int
    items: tuple[SelectedItem, ...]


@dataclass(frozen=True)
class RemediationApprovalManifest:
    schema_version: int
    manifest_id: str
    source_plan_hash: str
    source_generated_at: str
    reviewed_at: str
    reviewer: str
    requested_decision: str
    plan_approval_status: str
    execution_status: str
    authorizes_execution: bool
    policy: ApprovalPolicy
    selected_batches: tuple[SelectedBatch, ...]
    issues: tuple[ApprovalIssue, ...]
    manifest_hash: str

    @property
    def valid(self) -> bool:
        return not self.issues

    @property
    def planned_approved(self) -> bool:
        return self.plan_approval_status == "planned_approved"

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["policy"]["quarantine_product_ids"] = sorted(
            self.policy.quarantine_product_ids
        )
        result["policy"]["low_follower_stop_product_ids"] = sorted(
            self.policy.low_follower_stop_product_ids
        )
        return result

    def to_json(self) -> str:
        return _canonical_json(self.as_dict()) + "\n"


def build_approval_manifest(
    planner_output: Any,
    selections: Mapping[str, Iterable[int]] | Sequence[Mapping[str, Any]],
    *,
    decision: str = "pending_review",
    reviewer: str = "",
    reviewed_at: str | None = None,
    policy: ApprovalPolicy | Mapping[str, Any] | None = None,
) -> RemediationApprovalManifest:
    """Validate a human selection and produce an offline-only approval manifest.

    ``approve`` means only that the selected plan is approved for a later,
    separately controlled integration step. Every result has
    ``execution_status=not_executed`` and ``authorizes_execution=false``.
    """

    effective_policy = (
        policy
        if isinstance(policy, ApprovalPolicy)
        else ApprovalPolicy.from_mapping(policy)
    )
    issues: list[ApprovalIssue] = []
    plan = _normalize_plan(planner_output, issues)
    source_generated_at = _text(plan.get("generated_at"), "")
    reviewed_at_value = _text(reviewed_at, source_generated_at)
    normalized_decision = _normalize_decision(decision, issues)
    normalized_reviewer = _safe_text(reviewer, "reviewer", issues)
    source_plan_hash = hashlib.sha256(
        _canonical_json(plan).encode("utf-8")
    ).hexdigest()

    batch_index, item_locations, stopped_ids = _inspect_plan(
        plan, effective_policy, issues
    )
    requested = _normalize_selections(selections, issues)
    selected_batches = _select_batches(
        requested,
        batch_index,
        item_locations,
        stopped_ids,
        effective_policy,
        issues,
    )
    _validate_selection_order_and_budgets(
        selected_batches, effective_policy, issues
    )

    if not selected_batches:
        _issue(
            issues,
            "empty_selection",
            "selections",
            "At least one planner item must be selected.",
        )

    issues = sorted(
        _deduplicate_issues(issues),
        key=lambda item: (item.path, item.code, item.message),
    )
    if issues or normalized_decision == "reject":
        approval_status = "rejected"
    elif normalized_decision == "approve":
        approval_status = "planned_approved"
    else:
        approval_status = "pending_review"

    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "source_plan_hash": source_plan_hash,
        "source_generated_at": source_generated_at,
        "reviewed_at": reviewed_at_value,
        "reviewer": normalized_reviewer,
        "requested_decision": normalized_decision,
        "plan_approval_status": approval_status,
        "execution_status": EXECUTION_STATUS,
        "authorizes_execution": False,
        "policy": _policy_dict(effective_policy),
        "selected_batches": [_batch_dict(item) for item in selected_batches],
        "issues": [asdict(item) for item in issues],
    }
    content_hash = hashlib.sha256(
        _canonical_json(unsigned).encode("utf-8")
    ).hexdigest()
    manifest_id = f"remediation-approval-{content_hash[:16]}"
    signed = {"manifest_id": manifest_id, **unsigned}
    manifest_hash = hashlib.sha256(
        _canonical_json(signed).encode("utf-8")
    ).hexdigest()
    return RemediationApprovalManifest(
        schema_version=SCHEMA_VERSION,
        manifest_id=manifest_id,
        source_plan_hash=source_plan_hash,
        source_generated_at=source_generated_at,
        reviewed_at=reviewed_at_value,
        reviewer=normalized_reviewer,
        requested_decision=normalized_decision,
        plan_approval_status=approval_status,
        execution_status=EXECUTION_STATUS,
        authorizes_execution=False,
        policy=effective_policy,
        selected_batches=tuple(selected_batches),
        issues=tuple(issues),
        manifest_hash=manifest_hash,
    )


def write_approval_manifest(
    path: str | Path, manifest: RemediationApprovalManifest
) -> Path:
    """Write canonical UTF-8 JSON. This never writes a queue or production state."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(manifest.to_json(), encoding="utf-8", newline="\n")
    return target


def read_approval_manifest(path: str | Path) -> RemediationApprovalManifest:
    """Read a manifest and fail closed if fields or hashes were changed."""

    try:
        payload = json.loads(
            Path(path).read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (OSError, ValueError) as exc:
        raise RemediationApprovalError(f"cannot read approval manifest: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise RemediationApprovalError("approval manifest must be a JSON object")
    expected_fields = {
        "schema_version",
        "manifest_id",
        "source_plan_hash",
        "source_generated_at",
        "reviewed_at",
        "reviewer",
        "requested_decision",
        "plan_approval_status",
        "execution_status",
        "authorizes_execution",
        "policy",
        "selected_batches",
        "issues",
        "manifest_hash",
    }
    if set(payload) != expected_fields:
        raise RemediationApprovalError("approval manifest fields are incomplete or unknown")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise RemediationApprovalError("unsupported approval manifest schema")
    supplied_hash = payload.get("manifest_hash")
    unsigned = dict(payload)
    unsigned.pop("manifest_hash")
    expected_hash = hashlib.sha256(
        _canonical_json(unsigned).encode("utf-8")
    ).hexdigest()
    if supplied_hash != expected_hash:
        raise RemediationApprovalIntegrityError(
            "approval manifest integrity hash does not match"
        )
    try:
        parsed_policy = ApprovalPolicy(
            per_batch_limit=int(payload["policy"]["per_batch_limit"]),
            hourly_visit_limit=int(payload["policy"]["hourly_visit_limit"]),
            quarantine_product_ids=frozenset(
                int(item) for item in payload["policy"]["quarantine_product_ids"]
            ),
            low_follower_stop_product_ids=frozenset(
                int(item)
                for item in payload["policy"]["low_follower_stop_product_ids"]
            ),
        )
        selected_batches = tuple(
            SelectedBatch(
                batch_id=str(batch["batch_id"]),
                stage=str(batch["stage"]),
                hour_window=int(batch["hour_window"]),
                items=tuple(
                    SelectedItem(
                        product_id=int(item["product_id"]),
                        status=str(item["status"]),
                        stage=str(item["stage"]),
                        actions=tuple(str(value) for value in item["actions"]),
                        required_before=tuple(
                            str(value) for value in item["required_before"]
                        ),
                    )
                    for item in batch["items"]
                ),
            )
            for batch in payload["selected_batches"]
        )
        parsed_issues = tuple(
            ApprovalIssue(
                code=str(item["code"]),
                path=str(item["path"]),
                message=str(item["message"]),
            )
            for item in payload["issues"]
        )
        manifest = RemediationApprovalManifest(
            schema_version=SCHEMA_VERSION,
            manifest_id=str(payload["manifest_id"]),
            source_plan_hash=str(payload["source_plan_hash"]),
            source_generated_at=str(payload["source_generated_at"]),
            reviewed_at=str(payload["reviewed_at"]),
            reviewer=str(payload["reviewer"]),
            requested_decision=str(payload["requested_decision"]),
            plan_approval_status=str(payload["plan_approval_status"]),
            execution_status=str(payload["execution_status"]),
            authorizes_execution=bool(payload["authorizes_execution"]),
            policy=parsed_policy,
            selected_batches=selected_batches,
            issues=parsed_issues,
            manifest_hash=str(supplied_hash),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RemediationApprovalError(f"invalid approval manifest: {exc}") from exc
    _validate_stored_manifest(manifest)
    return manifest


def serialize_approval_manifest(manifest: RemediationApprovalManifest) -> str:
    return manifest.to_json()


def _normalize_plan(value: Any, issues: list[ApprovalIssue]) -> dict[str, Any]:
    if hasattr(value, "as_dict") and callable(value.as_dict):
        value = value.as_dict()
    if not isinstance(value, Mapping):
        _issue(issues, "invalid_plan", "planner_output", "Planner output must be a mapping.")
        return {"generated_at": "", "batches": [], "isolated": [], "skipped": []}
    try:
        return json.loads(_canonical_json(dict(value)))
    except (TypeError, ValueError):
        _issue(
            issues,
            "invalid_plan",
            "planner_output",
            "Planner output must contain JSON-serializable values.",
        )
        return {"generated_at": "", "batches": [], "isolated": [], "skipped": []}


def _inspect_plan(
    plan: Mapping[str, Any],
    policy: ApprovalPolicy,
    issues: list[ApprovalIssue],
) -> tuple[dict[str, Mapping[str, Any]], dict[int, str], set[int]]:
    batches = plan.get("batches")
    isolated = plan.get("isolated", [])
    skipped = plan.get("skipped", [])
    if not isinstance(batches, list):
        _issue(issues, "invalid_batches", "planner_output.batches", "batches must be a list.")
        batches = []
    if not isinstance(isolated, list):
        _issue(issues, "invalid_isolated", "planner_output.isolated", "isolated must be a list.")
        isolated = []
    if not isinstance(skipped, list):
        _issue(issues, "invalid_skipped", "planner_output.skipped", "skipped must be a list.")
        skipped = []

    stopped_ids = set(policy.low_follower_stop_product_ids)
    isolated_ids = set(policy.quarantine_product_ids)
    for index, item in enumerate(isolated):
        if not isinstance(item, Mapping):
            _issue(issues, "invalid_isolated_item", f"planner_output.isolated[{index}]", "item must be an object.")
            continue
        product_id = _positive_int(item.get("product_id"))
        if product_id is not None:
            isolated_ids.add(product_id)
    for index, item in enumerate(skipped):
        if not isinstance(item, Mapping):
            _issue(issues, "invalid_skipped_item", f"planner_output.skipped[{index}]", "item must be an object.")
            continue
        product_id = _positive_int(item.get("product_id"))
        code = str(item.get("code") or "")
        if product_id is not None and code in _STOP_SKIP_CODES:
            stopped_ids.add(product_id)

    batch_index: dict[str, Mapping[str, Any]] = {}
    item_locations: dict[int, str] = {}
    last_stage = -1
    for batch_position, batch in enumerate(batches):
        path = f"planner_output.batches[{batch_position}]"
        if not isinstance(batch, Mapping):
            _issue(issues, "invalid_batch", path, "batch must be an object.")
            continue
        batch_id = str(batch.get("batch_id") or "")
        stage = str(batch.get("stage") or "")
        items = batch.get("items")
        hour_window = _positive_int(batch.get("hour_window"))
        if not batch_id:
            _issue(issues, "missing_batch_id", f"{path}.batch_id", "batch_id is required.")
        elif batch_id in batch_index:
            _issue(issues, "duplicate_batch_id", f"{path}.batch_id", f"Duplicate batch_id {batch_id}.")
        else:
            batch_index[batch_id] = batch
        if stage not in STAGE_INDEX:
            _issue(issues, "invalid_stage", f"{path}.stage", f"Unknown stage {stage!r}.")
        else:
            if STAGE_INDEX[stage] < last_stage:
                _issue(issues, "plan_stage_order", path, "Planner batches are not in identity→metrics→note→profile order.")
            last_stage = max(last_stage, STAGE_INDEX[stage])
        if hour_window is None:
            _issue(issues, "invalid_hour_window", f"{path}.hour_window", "hour_window must be a positive integer.")
        if not isinstance(items, list):
            _issue(issues, "invalid_items", f"{path}.items", "items must be a list.")
            continue
        if len(items) > policy.per_batch_limit:
            _issue(issues, "planner_batch_over_budget", f"{path}.items", f"Planner batch exceeds {policy.per_batch_limit} items.")
        for item_position, item in enumerate(items):
            item_path = f"{path}.items[{item_position}]"
            if not isinstance(item, Mapping):
                _issue(issues, "invalid_plan_item", item_path, "item must be an object.")
                continue
            product_id = _positive_int(item.get("product_id"))
            if product_id is None:
                _issue(issues, "invalid_product_id", f"{item_path}.product_id", "product_id must be a positive integer.")
                continue
            if product_id in item_locations:
                _issue(issues, "duplicate_plan_product", f"{item_path}.product_id", f"Product {product_id} appears in multiple planner batches.")
            else:
                item_locations[product_id] = batch_id
            item_stage = str(item.get("stage") or "")
            if item_stage != stage:
                _issue(issues, "item_stage_mismatch", f"{item_path}.stage", "Item stage must match its batch stage.")
            status = str(item.get("status") or "").casefold()
            if status not in ACTIVE_STATUSES:
                _issue(issues, "inactive_product", f"{item_path}.status", "Only candidate/needs_review items can be approved.")
            required = _string_tuple(item.get("required_before"))
            if required != _REQUIRED_BEFORE.get(stage):
                _issue(issues, "dependency_contract_mismatch", f"{item_path}.required_before", "Required stage dependencies are missing or tampered with.")
            blocks = _string_tuple(item.get("blocks"))
            if blocks != _EXPECTED_BLOCKS.get(stage):
                _issue(issues, "stage_blocks_mismatch", f"{item_path}.blocks", "Downstream stage blocks are missing or tampered with.")
            actions = _string_tuple(item.get("actions"))
            if not actions or any(action not in _ALLOWED_ACTIONS.get(stage, ()) for action in actions):
                _issue(issues, "invalid_stage_action", f"{item_path}.actions", "Actions do not match the declared stage.")
            if product_id in isolated_ids:
                _issue(issues, "quarantined_in_plan", item_path, f"Quarantined product {product_id} must not appear in a planner batch.")
            if product_id in stopped_ids and stage in {"note", "profile"}:
                _issue(issues, "low_follower_stop_in_plan", item_path, f"Stopped low-follower product {product_id} must not enter note/profile.")
    return batch_index, item_locations, stopped_ids


def _normalize_selections(
    selections: Mapping[str, Iterable[int]] | Sequence[Mapping[str, Any]],
    issues: list[ApprovalIssue],
) -> list[tuple[str, tuple[int, ...]]]:
    if isinstance(selections, Mapping):
        raw = [
            {"batch_id": batch_id, "product_ids": product_ids}
            for batch_id, product_ids in selections.items()
        ]
    elif isinstance(selections, Sequence) and not isinstance(selections, (str, bytes)):
        raw = list(selections)
    else:
        _issue(issues, "invalid_selections", "selections", "Selections must be a batch mapping or list.")
        return []
    normalized: list[tuple[str, tuple[int, ...]]] = []
    for index, selection in enumerate(raw):
        path = f"selections[{index}]"
        if not isinstance(selection, Mapping):
            _issue(issues, "invalid_selection", path, "Selection must be an object.")
            continue
        batch_id = str(selection.get("batch_id") or "")
        values = selection.get("product_ids")
        if not batch_id:
            _issue(issues, "missing_batch_id", f"{path}.batch_id", "batch_id is required.")
        if not isinstance(values, Iterable) or isinstance(values, (str, bytes, Mapping)):
            _issue(issues, "invalid_product_ids", f"{path}.product_ids", "product_ids must be a list.")
            continue
        product_ids: list[int] = []
        for value in values:
            product_id = _positive_int(value)
            if product_id is None:
                _issue(issues, "invalid_product_id", f"{path}.product_ids", "Every product_id must be a positive integer.")
                continue
            product_ids.append(product_id)
        normalized.append((batch_id, tuple(product_ids)))
    return normalized


def _select_batches(
    requested: Sequence[tuple[str, tuple[int, ...]]],
    batch_index: Mapping[str, Mapping[str, Any]],
    item_locations: Mapping[int, str],
    stopped_ids: set[int],
    policy: ApprovalPolicy,
    issues: list[ApprovalIssue],
) -> list[SelectedBatch]:
    selected: list[SelectedBatch] = []
    seen_products: set[int] = set()
    seen_batches: set[str] = set()
    for selection_index, (batch_id, product_ids) in enumerate(requested):
        path = f"selections[{selection_index}]"
        if batch_id in seen_batches:
            _issue(issues, "duplicate_selected_batch", f"{path}.batch_id", f"Batch {batch_id} was selected more than once.")
        seen_batches.add(batch_id)
        batch = batch_index.get(batch_id)
        if batch is None:
            _issue(issues, "unknown_batch", f"{path}.batch_id", f"Batch {batch_id!r} is not in the planner output.")
            continue
        if len(product_ids) > policy.per_batch_limit:
            _issue(issues, "batch_over_budget", f"{path}.product_ids", f"A selected batch may contain at most {policy.per_batch_limit} products.")
        if not product_ids:
            _issue(issues, "empty_batch_selection", f"{path}.product_ids", "A selected batch must contain a product.")
        stage = str(batch.get("stage") or "")
        item_by_id = {
            _positive_int(item.get("product_id")): item
            for item in batch.get("items", [])
            if isinstance(item, Mapping)
        }
        selected_items: list[SelectedItem] = []
        for product_id in product_ids:
            if product_id in seen_products:
                _issue(issues, "duplicate_selected_product", f"{path}.product_ids", f"Product {product_id} was selected more than once.")
            seen_products.add(product_id)
            if item_locations.get(product_id) != batch_id or product_id not in item_by_id:
                _issue(issues, "product_not_in_batch", f"{path}.product_ids", f"Product {product_id} does not belong to batch {batch_id}.")
                continue
            if product_id in policy.quarantine_product_ids:
                _issue(issues, "quarantined_product", f"{path}.product_ids", f"Product {product_id} is quarantined and cannot be released by approval.")
            if product_id in stopped_ids and stage in {"note", "profile"}:
                _issue(issues, "low_follower_stop", f"{path}.product_ids", f"Product {product_id} is stopped from note/profile remediation.")
            item = item_by_id[product_id]
            selected_items.append(
                SelectedItem(
                    product_id=product_id,
                    status=str(item.get("status") or ""),
                    stage=stage,
                    actions=_string_tuple(item.get("actions")) or (),
                    required_before=_string_tuple(item.get("required_before")) or (),
                )
            )
        if selected_items:
            selected.append(
                SelectedBatch(
                    batch_id=batch_id,
                    stage=stage,
                    hour_window=_positive_int(batch.get("hour_window")) or 0,
                    items=tuple(selected_items),
                )
            )
    return selected


def _validate_selection_order_and_budgets(
    selected: Sequence[SelectedBatch],
    policy: ApprovalPolicy,
    issues: list[ApprovalIssue],
) -> None:
    last_stage = -1
    hourly: dict[int, int] = {}
    for index, batch in enumerate(selected):
        stage_index = STAGE_INDEX.get(batch.stage, -1)
        if stage_index < last_stage:
            _issue(issues, "selection_stage_order", f"selections[{index}]", "Selections must follow identity→metrics→note→profile order.")
        last_stage = max(last_stage, stage_index)
        hourly[batch.hour_window] = hourly.get(batch.hour_window, 0) + len(batch.items)
    for hour_window, count in sorted(hourly.items()):
        if count > policy.hourly_visit_limit:
            _issue(issues, "hourly_over_budget", f"hour_window[{hour_window}]", f"Selected {count} visits; hourly hard limit is {policy.hourly_visit_limit}.")


def _validate_stored_manifest(manifest: RemediationApprovalManifest) -> None:
    if manifest.plan_approval_status not in APPROVAL_STATUSES:
        raise RemediationApprovalError("invalid plan approval status")
    if manifest.execution_status != EXECUTION_STATUS or manifest.authorizes_execution:
        raise RemediationApprovalError("approval manifest must remain explicitly not executed")
    if manifest.planned_approved and manifest.issues:
        raise RemediationApprovalError("an approved plan cannot contain validation issues")
    if manifest.policy.per_batch_limit > PER_BATCH_HARD_LIMIT:
        raise RemediationApprovalError("stored per-batch limit exceeds hard limit")
    if manifest.policy.hourly_visit_limit > HOURLY_VISIT_HARD_LIMIT:
        raise RemediationApprovalError("stored hourly limit exceeds hard limit")
    if not DEFAULT_QUARANTINE_PRODUCT_IDS <= manifest.policy.quarantine_product_ids:
        raise RemediationApprovalError("stored policy removed a mandatory quarantine")
    if not (
        DEFAULT_LOW_FOLLOWER_STOP_PRODUCT_IDS
        <= manifest.policy.low_follower_stop_product_ids
    ):
        raise RemediationApprovalError("stored policy removed a low-follower stop")
    seen_products: set[int] = set()
    hourly: dict[int, int] = {}
    last_stage = -1
    for batch in manifest.selected_batches:
        if batch.stage not in STAGE_INDEX:
            raise RemediationApprovalError("stored manifest has an unknown stage")
        if STAGE_INDEX[batch.stage] < last_stage:
            raise RemediationApprovalError("stored selected batches are out of stage order")
        last_stage = STAGE_INDEX[batch.stage]
        if not batch.items or len(batch.items) > manifest.policy.per_batch_limit:
            raise RemediationApprovalError("stored selected batch violates its item limit")
        hourly[batch.hour_window] = hourly.get(batch.hour_window, 0) + len(batch.items)
        for item in batch.items:
            if item.product_id in seen_products:
                raise RemediationApprovalError("stored manifest repeats a product")
            seen_products.add(item.product_id)
            if item.stage != batch.stage:
                raise RemediationApprovalError("stored item stage differs from batch stage")
            if item.required_before != _REQUIRED_BEFORE[batch.stage]:
                raise RemediationApprovalError("stored item dependency contract is invalid")
            if item.product_id in manifest.policy.quarantine_product_ids:
                raise RemediationApprovalError("stored manifest contains a quarantined product")
            if (
                item.product_id in manifest.policy.low_follower_stop_product_ids
                and batch.stage in {"note", "profile"}
            ):
                raise RemediationApprovalError(
                    "stored manifest contains a stopped low-follower product"
                )
    if any(
        count > manifest.policy.hourly_visit_limit for count in hourly.values()
    ):
        raise RemediationApprovalError("stored manifest exceeds its hourly limit")


def _normalize_decision(value: Any, issues: list[ApprovalIssue]) -> str:
    decision = str(value or "pending_review").strip().casefold()
    aliases = {"approved": "approve", "planned_approved": "approve", "rejected": "reject"}
    decision = aliases.get(decision, decision)
    if decision not in APPROVAL_DECISIONS:
        _issue(issues, "invalid_decision", "decision", "decision must be pending_review, approve, or reject.")
        return "pending_review"
    return decision


def _safe_text(value: Any, path: str, issues: list[ApprovalIssue]) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or any(char in value for char in ("\x00", "\r", "\n")):
        _issue(issues, "invalid_text", path, f"{path} must be a single-line string.")
        return ""
    return value.strip()


def _text(value: Any, default: str) -> str:
    return value if isinstance(value, str) else default


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _string_tuple(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, (list, tuple)):
        return None
    if not all(isinstance(item, str) for item in value):
        return None
    return tuple(value)


def _issue(
    issues: list[ApprovalIssue], code: str, path: str, message: str
) -> None:
    issues.append(ApprovalIssue(code=code, path=path, message=message))


def _deduplicate_issues(issues: Iterable[ApprovalIssue]) -> list[ApprovalIssue]:
    return list(dict.fromkeys(issues))


def _policy_dict(policy: ApprovalPolicy) -> dict[str, Any]:
    return {
        "per_batch_limit": policy.per_batch_limit,
        "hourly_visit_limit": policy.hourly_visit_limit,
        "quarantine_product_ids": sorted(policy.quarantine_product_ids),
        "low_follower_stop_product_ids": sorted(
            policy.low_follower_stop_product_ids
        ),
    }


def _batch_dict(batch: SelectedBatch) -> dict[str, Any]:
    return {
        "batch_id": batch.batch_id,
        "stage": batch.stage,
        "hour_window": batch.hour_window,
        "items": [asdict(item) for item in batch.items],
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")
