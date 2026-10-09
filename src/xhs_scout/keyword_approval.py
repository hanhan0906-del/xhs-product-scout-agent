from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from xhs_scout.keyword_portfolio import normalize_keyword


STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
ALLOWED_STATUSES = {STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED}

_SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "password",
    "refresh_token",
    "secret",
    "session_token",
}
_PATH_KEY_SUFFIXES = ("_dir", "_directory", "_file", "_path", "_root")
_TRAVERSAL_RE = re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)")
_ABSOLUTE_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SAFE_KEYWORD_RE = re.compile(
    r"^[\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9 ＋+#&（）()·._—–-]+$"
)


@dataclass(frozen=True)
class ApprovalPolicy:
    """Strict limits for a human-only keyword review manifest."""

    max_approved: int = 5
    min_keyword_chars: int = 2
    max_keyword_chars: int = 18

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any] | None,
    ) -> "ApprovalPolicy":
        data = data or {}
        policy = cls(
            max_approved=int(data.get("max_approved", cls.max_approved)),
            min_keyword_chars=int(
                data.get("min_keyword_chars", cls.min_keyword_chars)
            ),
            max_keyword_chars=int(
                data.get("max_keyword_chars", cls.max_keyword_chars)
            ),
        )
        if policy.max_approved < 0:
            raise ValueError("max_approved must be non-negative")
        if policy.min_keyword_chars < 1:
            raise ValueError("min_keyword_chars must be positive")
        if policy.max_keyword_chars < policy.min_keyword_chars:
            raise ValueError(
                "max_keyword_chars must be at least min_keyword_chars"
            )
        return policy


def build_keyword_approval_manifest(
    suggestions: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    *,
    decisions: Iterable[Mapping[str, Any]] = (),
    previous_manifest: Mapping[str, Any] | None = None,
    policy: ApprovalPolicy | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, human-only review manifest.

    A non-pending decision is accepted only when it names a current candidate
    and binds both the current suggestion-set hash and candidate evidence hash.
    Previous decisions are retained only while those same hashes remain stable.
    """

    active_policy = (
        policy
        if isinstance(policy, ApprovalPolicy)
        else ApprovalPolicy.from_mapping(policy)
    )
    _reject_unsafe_input(suggestions, location="suggestions")
    if previous_manifest is not None:
        _reject_unsafe_input(previous_manifest, location="previous_manifest")

    candidates = _candidate_sequence(suggestions)
    entries = _prepare_entries(candidates, policy=active_policy)
    suggestion_set_hash = _hash_json(
        [
            {
                "candidate_id": item["candidate_id"],
                "normalized": item["normalized"],
                "layer": item["layer"],
                "evidence_hash": item["evidence_hash"],
            }
            for item in entries
        ]
    )

    invalidated = 0
    if previous_manifest is not None:
        invalidated = _carry_previous_decisions(
            entries,
            previous_manifest=previous_manifest,
            suggestion_set_hash=suggestion_set_hash,
        )

    normalized_decisions = list(decisions)
    _reject_unsafe_input(normalized_decisions, location="decisions")
    _apply_decisions(
        entries,
        normalized_decisions,
        suggestion_set_hash=suggestion_set_hash,
    )

    approved_count = sum(item["status"] == STATUS_APPROVED for item in entries)
    if approved_count > active_policy.max_approved:
        raise ValueError(
            f"approved candidates exceed max_approved={active_policy.max_approved}"
        )

    return {
        "version": 1,
        "scope": {
            "mode": "offline_human_keyword_approval",
            "human_review_only": True,
            "writes_queue": False,
            "search_execution": False,
            "monitor_authorization": False,
            "soak_authorization": False,
        },
        "policy": {
            "max_approved": active_policy.max_approved,
            "min_keyword_chars": active_policy.min_keyword_chars,
            "max_keyword_chars": active_policy.max_keyword_chars,
        },
        "suggestion_set_hash": suggestion_set_hash,
        "stats": {
            "total": len(entries),
            "core": sum(item["layer"] == "core" for item in entries),
            "exploration": sum(
                item["layer"] == "exploration" for item in entries
            ),
            "pending": sum(item["status"] == STATUS_PENDING for item in entries),
            "approved": approved_count,
            "rejected": sum(
                item["status"] == STATUS_REJECTED for item in entries
            ),
            "invalidated": invalidated,
        },
        "entries": entries,
    }


def validate_keyword_approval_manifest(
    manifest: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    """Return fail-closed validation errors for a generated manifest."""

    errors: list[str] = []
    try:
        _reject_unsafe_input(manifest, location="manifest")
    except (TypeError, ValueError) as exc:
        return False, [str(exc)]

    scope = manifest.get("scope")
    required_scope = {
        "human_review_only": True,
        "writes_queue": False,
        "search_execution": False,
        "monitor_authorization": False,
        "soak_authorization": False,
    }
    if not isinstance(scope, Mapping):
        errors.append("scope must be a mapping")
    else:
        for key, expected in required_scope.items():
            if scope.get(key) is not expected:
                errors.append(f"scope.{key} must be {expected!r}")

    entries = manifest.get("entries")
    if not isinstance(entries, list):
        errors.append("entries must be a list")
        return False, errors
    try:
        rebuilt = build_keyword_approval_manifest(
            [
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
                for item in entries
            ],
            policy=manifest.get("policy"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"entries invalid: {exc}")
        return False, errors

    if rebuilt["suggestion_set_hash"] != manifest.get("suggestion_set_hash"):
        errors.append("suggestion_set_hash mismatch")
    rebuilt_by_id = {
        item["candidate_id"]: item for item in rebuilt["entries"]
    }
    for item in entries:
        candidate_id = item.get("candidate_id")
        expected = rebuilt_by_id.get(candidate_id)
        if expected is None:
            errors.append(f"unknown candidate_id: {candidate_id}")
            continue
        if item.get("evidence_hash") != expected["evidence_hash"]:
            errors.append(f"evidence_hash mismatch: {candidate_id}")
        if item.get("status") not in ALLOWED_STATUSES:
            errors.append(f"invalid status: {candidate_id}")
        binding = item.get("decision_binding")
        if item.get("status") != STATUS_PENDING:
            if not isinstance(binding, Mapping):
                errors.append(f"missing decision binding: {candidate_id}")
            elif (
                binding.get("suggestion_set_hash")
                != manifest.get("suggestion_set_hash")
                or binding.get("evidence_hash") != item.get("evidence_hash")
            ):
                errors.append(f"stale decision binding: {candidate_id}")

    approved_count = sum(
        item.get("status") == STATUS_APPROVED for item in entries
    )
    max_approved = int((manifest.get("policy") or {}).get("max_approved", -1))
    if approved_count > max_approved:
        errors.append("approved candidates exceed max_approved")
    return not errors, errors


def _candidate_sequence(
    suggestions: Mapping[str, Any] | Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    if isinstance(suggestions, Mapping):
        raw = suggestions.get("candidates")
        if not isinstance(raw, list):
            raise TypeError("suggestions.candidates must be a list")
        return raw
    if isinstance(suggestions, (str, bytes)):
        raise TypeError("suggestions must be mappings, not text")
    raw = list(suggestions)
    if not all(isinstance(item, Mapping) for item in raw):
        raise TypeError("every suggestion must be a mapping")
    return raw


def _prepare_entries(
    candidates: Iterable[Mapping[str, Any]],
    *,
    policy: ApprovalPolicy,
) -> list[dict[str, Any]]:
    by_normalized: dict[str, dict[str, Any]] = {}
    normalized_by_id: dict[str, str] = {}
    for position, candidate in enumerate(candidates):
        keyword = _required_text(candidate, "keyword")
        normalized = normalize_keyword(
            str(candidate.get("normalized") or keyword)
        )
        if not normalized:
            raise ValueError(f"candidate {position} has an empty normalized keyword")
        if len(normalized) < policy.min_keyword_chars:
            raise ValueError(f"keyword too short: {keyword!r}")
        if len(normalized) > policy.max_keyword_chars:
            raise ValueError(f"keyword too long: {keyword!r}")
        if not _SAFE_KEYWORD_RE.fullmatch(keyword):
            raise ValueError(f"keyword contains unsafe characters: {keyword!r}")
        if not re.search(r"[\u3400-\u4dbf\u4e00-\u9fffA-Za-z]", normalized):
            raise ValueError(f"keyword has no semantic text: {keyword!r}")

        candidate_id = str(
            candidate.get("candidate_id")
            or hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        ).strip()
        if not candidate_id or not re.fullmatch(r"[A-Za-z0-9._:-]{1,80}", candidate_id):
            raise ValueError(f"candidate_id is unsafe: {candidate_id!r}")
        previous_normalized = normalized_by_id.get(candidate_id)
        if (
            previous_normalized is not None
            and previous_normalized != normalized
        ):
            raise ValueError(
                f"duplicate candidate_id refers to different keywords: {candidate_id}"
            )

        raw_layer = str(
            candidate.get("suggested_layer")
            or candidate.get("layer")
            or ""
        ).strip().lower()
        if raw_layer == "explore":
            layer = "exploration"
        elif raw_layer in {"core", "exploration"}:
            layer = raw_layer
        else:
            raise ValueError(f"unsupported suggested layer: {raw_layer!r}")

        evidence = _canonical_evidence(candidate.get("evidence") or [])
        source_summary = _source_summary(candidate, evidence=evidence)
        evidence_hash = _hash_json(
            {
                "normalized": normalized,
                "source_summary": source_summary,
                "evidence": evidence,
            }
        )
        entry = {
            "candidate_id": candidate_id,
            "keyword": unicodedata.normalize("NFKC", keyword).strip(),
            "normalized": normalized,
            "layer": layer,
            "source_summary": source_summary,
            "evidence": evidence,
            "evidence_hash": evidence_hash,
            "status": STATUS_PENDING,
            "reason": "awaiting_human_review",
            "decision_binding": None,
            "approval_valid": False,
        }
        previous = by_normalized.get(normalized)
        if previous is not None:
            if _hash_json(previous) != _hash_json(entry):
                raise ValueError(
                    f"conflicting duplicate normalized keyword: {normalized}"
                )
            continue
        by_normalized[normalized] = entry
        normalized_by_id[candidate_id] = normalized

    return sorted(
        by_normalized.values(),
        key=lambda item: (
            item["layer"] != "core",
            item["normalized"],
            item["candidate_id"],
        ),
    )


def _canonical_evidence(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise TypeError("candidate evidence must be a list")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError("every evidence item must be a mapping")
        evidence = {
            "source_type": _optional_text(item.get("source_type")),
            "source_id": _optional_text(item.get("source_id")),
            "product_id": _optional_text(item.get("product_id")),
            "source_keyword": _optional_text(item.get("source_keyword")),
        }
        digest = _hash_json(evidence)
        if digest not in seen:
            seen.add(digest)
            result.append(evidence)
    return sorted(
        result,
        key=lambda item: (
            item["source_type"] or "",
            item["source_id"] or "",
            item["product_id"] or "",
            item["source_keyword"] or "",
        ),
    )


def _source_summary(
    candidate: Mapping[str, Any],
    *,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    support = candidate.get("support") or {}
    if not isinstance(support, Mapping):
        raise TypeError("candidate support must be a mapping")
    source_products = sorted(
        {
            str(value).strip()
            for value in candidate.get("source_products") or ()
            if str(value).strip()
        }
        | {
            item["product_id"]
            for item in evidence
            if item["product_id"] is not None
        }
    )
    source_keywords = sorted(
        {
            unicodedata.normalize("NFKC", str(value)).strip()
            for value in candidate.get("source_keywords") or ()
            if str(value).strip()
        }
        | {
            item["source_keyword"]
            for item in evidence
            if item["source_keyword"] is not None
        }
    )
    source_types = sorted(
        {
            str(value).strip()
            for value in support.get("source_types") or ()
            if str(value).strip()
        }
        | {
            item["source_type"]
            for item in evidence
            if item["source_type"] is not None
        }
    )
    return {
        "source_products": source_products,
        "source_keywords": source_keywords,
        "source_types": source_types,
        "evidence_count": len(evidence),
        "support_score": float(support.get("score") or 0.0),
        "risk_flags": sorted(
            {
                str(value).strip()
                for value in candidate.get("risk_flags") or ()
                if str(value).strip()
            }
        ),
    }


def _carry_previous_decisions(
    entries: list[dict[str, Any]],
    *,
    previous_manifest: Mapping[str, Any],
    suggestion_set_hash: str,
) -> int:
    previous_entries = previous_manifest.get("entries")
    if not isinstance(previous_entries, list):
        raise TypeError("previous_manifest.entries must be a list")
    previous_by_id: dict[str, Mapping[str, Any]] = {}
    for item in previous_entries:
        if not isinstance(item, Mapping):
            raise TypeError("previous manifest entries must be mappings")
        candidate_id = _required_text(item, "candidate_id")
        if candidate_id in previous_by_id:
            raise ValueError(f"duplicate previous candidate_id: {candidate_id}")
        previous_by_id[candidate_id] = item

    same_set = (
        previous_manifest.get("suggestion_set_hash") == suggestion_set_hash
    )
    invalidated = 0
    for entry in entries:
        previous = previous_by_id.get(entry["candidate_id"])
        if previous is None:
            continue
        status = str(previous.get("status") or STATUS_PENDING)
        if status not in ALLOWED_STATUSES:
            raise ValueError(
                f"invalid previous status for {entry['candidate_id']}: {status}"
            )
        if status == STATUS_PENDING:
            continue
        binding = previous.get("decision_binding")
        evidence_same = previous.get("evidence_hash") == entry["evidence_hash"]
        binding_valid = (
            isinstance(binding, Mapping)
            and binding.get("suggestion_set_hash") == suggestion_set_hash
            and binding.get("evidence_hash") == entry["evidence_hash"]
        )
        if same_set and evidence_same and binding_valid:
            entry["status"] = status
            entry["reason"] = _required_text(previous, "reason")
            entry["decision_binding"] = {
                "suggestion_set_hash": suggestion_set_hash,
                "evidence_hash": entry["evidence_hash"],
            }
            entry["approval_valid"] = status == STATUS_APPROVED
        else:
            invalidated += 1
            entry["reason"] = (
                "previous_evidence_changed"
                if not evidence_same
                else "previous_suggestion_set_changed"
            )
    return invalidated


def _apply_decisions(
    entries: list[dict[str, Any]],
    decisions: list[Mapping[str, Any]],
    *,
    suggestion_set_hash: str,
) -> None:
    by_id = {item["candidate_id"]: item for item in entries}
    seen: set[str] = set()
    for decision in decisions:
        if not isinstance(decision, Mapping):
            raise TypeError("every decision must be a mapping")
        candidate_id = _required_text(decision, "candidate_id")
        if candidate_id in seen:
            raise ValueError(f"duplicate decision for candidate_id: {candidate_id}")
        seen.add(candidate_id)
        entry = by_id.get(candidate_id)
        if entry is None:
            raise ValueError(
                f"decision references a candidate outside suggestions: {candidate_id}"
            )
        status = str(decision.get("status") or "").strip().lower()
        if status == "pending_review":
            status = STATUS_PENDING
        if status not in ALLOWED_STATUSES:
            raise ValueError(f"unsupported decision status: {status!r}")
        reason = str(decision.get("reason") or "").strip()
        if status == STATUS_PENDING:
            entry["status"] = STATUS_PENDING
            entry["reason"] = reason or "awaiting_human_review"
            entry["decision_binding"] = None
            entry["approval_valid"] = False
            continue
        if not reason:
            raise ValueError(f"{status} decision requires a reason")
        if decision.get("suggestion_set_hash") != suggestion_set_hash:
            raise ValueError(f"stale suggestion_set_hash for {candidate_id}")
        if decision.get("evidence_hash") != entry["evidence_hash"]:
            raise ValueError(f"stale evidence_hash for {candidate_id}")
        entry["status"] = status
        entry["reason"] = reason
        entry["decision_binding"] = {
            "suggestion_set_hash": suggestion_set_hash,
            "evidence_hash": entry["evidence_hash"],
        }
        entry["approval_valid"] = status == STATUS_APPROVED


def _reject_unsafe_input(value: Any, *, location: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).strip().lower()
            if key_text in _SENSITIVE_KEYS:
                raise ValueError(f"sensitive field rejected at {location}.{key}")
            if key_text.endswith(_PATH_KEY_SUFFIXES):
                child_text = str(child or "")
                if _TRAVERSAL_RE.search(child_text) or _ABSOLUTE_PATH_RE.match(
                    child_text
                ):
                    raise ValueError(
                        f"unsafe path field rejected at {location}.{key}"
                    )
            _reject_unsafe_input(child, location=f"{location}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_unsafe_input(child, location=f"{location}[{index}]")
        return
    if isinstance(value, str):
        if _CONTROL_RE.search(value):
            raise ValueError(f"control character rejected at {location}")
        if _TRAVERSAL_RE.search(value):
            raise ValueError(f"path traversal rejected at {location}")


def _required_text(mapping: Mapping[str, Any], key: str) -> str:
    value = str(mapping.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _optional_text(value: Any) -> str | None:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return text or None


def _hash_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
