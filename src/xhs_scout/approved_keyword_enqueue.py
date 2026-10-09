from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from .db import enqueue, get_monitor_state
from .keyword_combinations import CombinationAnalysis
from .keyword_portfolio import normalize_keyword
from .product_keyword_terms import ProductKeywordError


ALLOWED_APPROVAL_STATUSES = {
    "pending_review",
    "approved",
    "rejected",
    "deprecated",
}


@dataclass(frozen=True)
class ApprovedKeywordQueuePlan:
    dataset_fingerprint: str
    approval_fingerprint: str
    selected: tuple[str, ...]
    deferred: tuple[Mapping[str, Any], ...]
    rejected: tuple[Mapping[str, Any], ...]
    max_enqueue: int
    cooldown_hours: int
    plan_hash: str

    @property
    def scope(self) -> dict[str, bool | str]:
        return {
            "mode": "approved_keyword_queue_dry_run",
            "dry_run": True,
            "writes_queue": False,
            "search_execution": False,
            "monitor_authorization": False,
            "soak_authorization": False,
            "explicit_execute_confirmation_required": True,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_fingerprint": self.dataset_fingerprint,
            "approval_fingerprint": self.approval_fingerprint,
            "selected": list(self.selected),
            "deferred": [dict(item) for item in self.deferred],
            "rejected": [dict(item) for item in self.rejected],
            "max_enqueue": self.max_enqueue,
            "cooldown_hours": self.cooldown_hours,
            "plan_hash": self.plan_hash,
            "scope": self.scope,
        }


def plan_approved_keyword_enqueue(
    conn: sqlite3.Connection,
    *,
    approval_manifest: Mapping[str, Any],
    analysis: CombinationAnalysis,
    now: datetime | None = None,
    max_enqueue: int = 5,
    cooldown_hours: int = 24,
) -> ApprovedKeywordQueuePlan:
    if analysis.generation_stage == "not_ready":
        raise ProductKeywordError("combination dataset has not reached the sample gate")
    if not isinstance(approval_manifest, Mapping):
        raise ProductKeywordError("approval_manifest must be an object")
    if max_enqueue < 1 or max_enqueue > 5:
        raise ProductKeywordError("max_enqueue must be between 1 and 5")
    if cooldown_hours < 24:
        raise ProductKeywordError("cooldown_hours must be at least 24")
    if approval_manifest.get("dataset_fingerprint") != analysis.dataset_fingerprint:
        raise ProductKeywordError("approval dataset fingerprint is stale")
    scope = approval_manifest.get("scope")
    required_scope = {
        "human_review_only": True,
        "writes_queue": False,
        "search_execution": False,
        "monitor_authorization": False,
        "soak_authorization": False,
    }
    if not isinstance(scope, Mapping) or any(
        scope.get(key) is not expected for key, expected in required_scope.items()
    ):
        raise ProductKeywordError("approval scope is missing or unsafe")
    entries = approval_manifest.get("entries")
    if not isinstance(entries, list):
        raise ProductKeywordError("approval entries must be a list")

    candidates = {item.phrase: item for item in analysis.candidates}
    approved: list[str] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ProductKeywordError("every approval entry must be an object")
        phrase = str(entry.get("phrase") or "").strip()
        status = str(entry.get("status") or "").strip()
        if status not in ALLOWED_APPROVAL_STATUSES:
            raise ProductKeywordError(f"invalid approval status for {phrase!r}")
        candidate = candidates.get(phrase)
        if candidate is None:
            raise ProductKeywordError(f"approval contains unknown phrase: {phrase!r}")
        if entry.get("source_fingerprint") != candidate.source_fingerprint:
            raise ProductKeywordError(f"approval evidence is stale for {phrase!r}")
        normalized = normalize_keyword(phrase)
        if not normalized or normalized in seen:
            raise ProductKeywordError("approval contains an empty or duplicate phrase")
        seen.add(normalized)
        if status == "approved":
            approved.append(phrase)
        else:
            rejected.append({"phrase": phrase, "reason": status})
    if len(approved) > max_enqueue:
        raise ProductKeywordError("approved phrases exceed the enqueue budget")

    current = now or datetime.now(timezone.utc).astimezone()
    if current.tzinfo is None or current.utcoffset() is None:
        raise ProductKeywordError("now must be timezone-aware")
    selected: list[str] = []
    deferred: list[dict[str, Any]] = []
    cooldown_cutoff = current - timedelta(hours=cooldown_hours)
    for phrase in approved:
        active = conn.execute(
            """
            SELECT id, status FROM search_tasks
            WHERE keyword=? AND status IN ('pending', 'running', 'paused')
            ORDER BY id DESC LIMIT 1
            """,
            (phrase,),
        ).fetchone()
        if active is not None:
            deferred.append({"phrase": phrase, "reason": "active_duplicate"})
            continue
        recent = conn.execute(
            """
            SELECT updated_at FROM search_tasks
            WHERE keyword=? AND updated_at>=?
            ORDER BY updated_at DESC LIMIT 1
            """,
            (phrase, cooldown_cutoff.isoformat(timespec="seconds")),
        ).fetchone()
        if recent is not None:
            deferred.append(
                {
                    "phrase": phrase,
                    "reason": "keyword_cooldown",
                    "last_at": recent["updated_at"]
                    if isinstance(recent, sqlite3.Row)
                    else recent[0],
                }
            )
            continue
        selected.append(phrase)

    approval_fingerprint = _hash_json(approval_manifest)
    plan_payload = {
        "dataset_fingerprint": analysis.dataset_fingerprint,
        "approval_fingerprint": approval_fingerprint,
        "selected": selected,
        "deferred": deferred,
        "rejected": rejected,
        "max_enqueue": max_enqueue,
        "cooldown_hours": cooldown_hours,
    }
    return ApprovedKeywordQueuePlan(
        dataset_fingerprint=analysis.dataset_fingerprint,
        approval_fingerprint=approval_fingerprint,
        selected=tuple(selected),
        deferred=tuple(deferred),
        rejected=tuple(rejected),
        max_enqueue=max_enqueue,
        cooldown_hours=cooldown_hours,
        plan_hash=_hash_json(plan_payload),
    )


def discovery_root_source_fingerprint(
    dataset_fingerprint: str,
    phrase: str,
) -> str:
    return _hash_json(
        {
            "dataset_fingerprint": dataset_fingerprint,
            "phrase": normalize_keyword(phrase),
            "source_kind": "discovery_root",
        }
    )


def plan_approved_root_keyword_enqueue(
    conn: sqlite3.Connection,
    *,
    approval_manifest: Mapping[str, Any],
    allowed_roots: Sequence[str],
    root_dataset_fingerprint: str,
    batch_phrases: Sequence[str],
    now: datetime | None = None,
    max_enqueue: int = 5,
    cooldown_hours: int = 24,
) -> ApprovedKeywordQueuePlan:
    if not isinstance(approval_manifest, Mapping):
        raise ProductKeywordError("approval_manifest must be an object")
    if approval_manifest.get("approval_kind") != "discovery_root_pilot":
        raise ProductKeywordError("approval kind is not discovery_root_pilot")
    if approval_manifest.get("dataset_fingerprint") != root_dataset_fingerprint:
        raise ProductKeywordError("approval dataset fingerprint is stale")
    if max_enqueue < 1 or max_enqueue > 5:
        raise ProductKeywordError("max_enqueue must be between 1 and 5")
    if cooldown_hours < 24:
        raise ProductKeywordError("cooldown_hours must be at least 24")
    scope = approval_manifest.get("scope")
    required_scope = {
        "human_review_only": True,
        "writes_queue": False,
        "search_execution": False,
        "monitor_authorization": False,
        "soak_authorization": False,
    }
    if not isinstance(scope, Mapping) or any(
        scope.get(key) is not expected for key, expected in required_scope.items()
    ):
        raise ProductKeywordError("approval scope is missing or unsafe")

    allowed_by_normalized: dict[str, str] = {}
    for phrase in allowed_roots:
        normalized = normalize_keyword(phrase)
        if not normalized or normalized in allowed_by_normalized:
            raise ProductKeywordError("allowed roots contain an empty or duplicate phrase")
        allowed_by_normalized[normalized] = str(phrase).strip()

    entries = approval_manifest.get("entries")
    if not isinstance(entries, list):
        raise ProductKeywordError("approval entries must be a list")
    approved_by_normalized: dict[str, str] = {}
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ProductKeywordError("every approval entry must be an object")
        phrase = str(entry.get("phrase") or "").strip()
        normalized = normalize_keyword(phrase)
        status = str(entry.get("status") or "").strip()
        if status not in ALLOWED_APPROVAL_STATUSES:
            raise ProductKeywordError(f"invalid approval status for {phrase!r}")
        if not normalized or normalized in seen:
            raise ProductKeywordError("approval contains an empty or duplicate phrase")
        seen.add(normalized)
        if normalized not in allowed_by_normalized:
            raise ProductKeywordError(f"approval contains unknown root: {phrase!r}")
        expected_fingerprint = discovery_root_source_fingerprint(
            root_dataset_fingerprint,
            allowed_by_normalized[normalized],
        )
        if entry.get("source_fingerprint") != expected_fingerprint:
            raise ProductKeywordError(f"approval evidence is stale for {phrase!r}")
        if status == "approved":
            approved_by_normalized[normalized] = allowed_by_normalized[normalized]
        else:
            rejected.append({"phrase": phrase, "reason": status})

    if not batch_phrases or len(batch_phrases) > max_enqueue:
        raise ProductKeywordError("root pilot batch must contain between 1 and max_enqueue phrases")
    batch: list[str] = []
    batch_seen: set[str] = set()
    for phrase in batch_phrases:
        normalized = normalize_keyword(phrase)
        if not normalized or normalized in batch_seen:
            raise ProductKeywordError("root pilot batch contains an empty or duplicate phrase")
        batch_seen.add(normalized)
        approved_phrase = approved_by_normalized.get(normalized)
        if approved_phrase is None:
            raise ProductKeywordError(f"root pilot batch is not approved: {phrase!r}")
        batch.append(approved_phrase)

    current = now or datetime.now(timezone.utc).astimezone()
    if current.tzinfo is None or current.utcoffset() is None:
        raise ProductKeywordError("now must be timezone-aware")
    cooldown_cutoff = current - timedelta(hours=cooldown_hours)
    selected: list[str] = []
    deferred: list[dict[str, Any]] = [
        {"phrase": phrase, "reason": "future_batch"}
        for normalized, phrase in approved_by_normalized.items()
        if normalized not in batch_seen
    ]
    for phrase in batch:
        active = conn.execute(
            """
            SELECT id, status FROM search_tasks
            WHERE keyword=? AND status IN ('pending', 'running', 'paused')
            ORDER BY id DESC LIMIT 1
            """,
            (phrase,),
        ).fetchone()
        if active is not None:
            deferred.append({"phrase": phrase, "reason": "active_duplicate"})
            continue
        recent = conn.execute(
            """
            SELECT updated_at FROM search_tasks
            WHERE keyword=? AND updated_at>=?
            ORDER BY updated_at DESC LIMIT 1
            """,
            (phrase, cooldown_cutoff.isoformat(timespec="seconds")),
        ).fetchone()
        if recent is not None:
            deferred.append(
                {
                    "phrase": phrase,
                    "reason": "keyword_cooldown",
                    "last_at": recent["updated_at"]
                    if isinstance(recent, sqlite3.Row)
                    else recent[0],
                }
            )
            continue
        selected.append(phrase)

    approval_fingerprint = _hash_json(approval_manifest)
    plan_payload = {
        "dataset_fingerprint": root_dataset_fingerprint,
        "approval_fingerprint": approval_fingerprint,
        "selected": selected,
        "deferred": deferred,
        "rejected": rejected,
        "max_enqueue": max_enqueue,
        "cooldown_hours": cooldown_hours,
    }
    return ApprovedKeywordQueuePlan(
        dataset_fingerprint=root_dataset_fingerprint,
        approval_fingerprint=approval_fingerprint,
        selected=tuple(selected),
        deferred=tuple(deferred),
        rejected=tuple(rejected),
        max_enqueue=max_enqueue,
        cooldown_hours=cooldown_hours,
        plan_hash=_hash_json(plan_payload),
    )


def apply_approved_keyword_queue_plan(
    conn: sqlite3.Connection,
    plan: ApprovedKeywordQueuePlan,
    *,
    execute: bool = False,
    confirm_plan_hash: str | None = None,
) -> dict[str, Any]:
    if not execute:
        return {
            **plan.as_dict(),
            "execution_status": "not_executed",
            "inserted_count": 0,
        }
    if confirm_plan_hash != plan.plan_hash:
        raise ProductKeywordError("exact plan hash confirmation is required")
    desired_state = get_monitor_state(conn).get("desired_state", "paused")
    if desired_state != "paused":
        raise ProductKeywordError("monitor must be paused before queue write")
    if conn.execute(
        "SELECT COUNT(*) FROM search_tasks WHERE status='running'"
    ).fetchone()[0]:
        raise ProductKeywordError("running tasks block queue write")
    if conn.execute("SELECT COUNT(*) FROM run_leases").fetchone()[0]:
        raise ProductKeywordError("active run leases block queue write")
    if conn.execute(
        "SELECT 1 FROM keyword_queue_audits WHERE plan_hash=?",
        (plan.plan_hash,),
    ).fetchone() is not None:
        raise ProductKeywordError("plan has already been executed")

    conn.execute("SAVEPOINT approved_keyword_enqueue")
    try:
        inserted = enqueue(
            conn,
            plan.selected,
            source="approved_discovery_keyword",
        )
        if inserted != len(plan.selected):
            raise ProductKeywordError(
                "queue changed after dry-run; no partial write is allowed"
            )
        executed_at = datetime.now(timezone.utc).astimezone().isoformat(
            timespec="seconds"
        )
        conn.execute(
            """
            INSERT INTO keyword_queue_audits(
                plan_hash, dataset_fingerprint, approval_fingerprint,
                selected_keywords_json, inserted_count, executed_at, source
            ) VALUES (?, ?, ?, ?, ?, ?, 'approved_discovery_keyword')
            """,
            (
                plan.plan_hash,
                plan.dataset_fingerprint,
                plan.approval_fingerprint,
                json.dumps(
                    list(plan.selected),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                inserted,
                executed_at,
            ),
        )
        conn.execute("RELEASE SAVEPOINT approved_keyword_enqueue")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT approved_keyword_enqueue")
        conn.execute("RELEASE SAVEPOINT approved_keyword_enqueue")
        raise
    return {
        **plan.as_dict(),
        "execution_status": "executed",
        "inserted_count": inserted,
    }


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
