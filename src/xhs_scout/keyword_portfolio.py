from __future__ import annotations

import hashlib
import math
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping


LAYER_CORE = "core"
LAYER_EXPLORE = "explore"
DEFAULT_LAYER_ORDER = (LAYER_CORE, LAYER_EXPLORE)
DIMENSION_ORDER = (
    "product_forms",
    "audiences",
    "scenarios",
    "stage_modifiers",
)
DIMENSION_JOIN_ORDER = {
    "product_forms": "suffix",
    "audiences": "prefix",
    "scenarios": "prefix",
    "stage_modifiers": "suffix",
}


@dataclass(frozen=True)
class PortfolioPolicy:
    hourly_budget: int = 6
    per_round_budget: int = 2
    keyword_cooldown_hours: int = 24
    core_share: float = 0.7
    min_explore_per_round: int = 1
    max_generated_per_category: int = 12
    max_total_candidates: int = 128
    max_consecutive_failures: int = 2
    failure_pause_hours: int = 3
    risk_pause_requires_manual_resume: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "PortfolioPolicy":
        data = data or {}
        return cls(
            hourly_budget=max(0, int(data.get("hourly_budget", cls.hourly_budget))),
            per_round_budget=max(0, int(data.get("per_round_budget", cls.per_round_budget))),
            keyword_cooldown_hours=max(
                0,
                int(data.get("keyword_cooldown_hours", cls.keyword_cooldown_hours)),
            ),
            core_share=min(1.0, max(0.0, float(data.get("core_share", cls.core_share)))),
            min_explore_per_round=max(
                0,
                int(data.get("min_explore_per_round", cls.min_explore_per_round)),
            ),
            max_generated_per_category=max(
                0,
                int(data.get("max_generated_per_category", cls.max_generated_per_category)),
            ),
            max_total_candidates=max(
                0,
                int(data.get("max_total_candidates", cls.max_total_candidates)),
            ),
            max_consecutive_failures=max(
                1,
                int(data.get("max_consecutive_failures", cls.max_consecutive_failures)),
            ),
            failure_pause_hours=max(
                0,
                int(data.get("failure_pause_hours", cls.failure_pause_hours)),
            ),
            risk_pause_requires_manual_resume=bool(
                data.get(
                    "risk_pause_requires_manual_resume",
                    cls.risk_pause_requires_manual_resume,
                )
            ),
        )


@dataclass(frozen=True)
class KeywordCandidate:
    keyword: str
    normalized: str
    category_id: str
    category_label: str
    layer: str
    source_seed: str
    modifier: str | None
    priority: int
    stable_key: str
    combination_kind: str = "seed"
    components: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "keyword": self.keyword,
            "normalized": self.normalized,
            "category_id": self.category_id,
            "category_label": self.category_label,
            "layer": self.layer,
            "source_seed": self.source_seed,
            "modifier": self.modifier,
            "priority": self.priority,
            "stable_key": self.stable_key,
            "combination_kind": self.combination_kind,
            "components": list(self.components),
            "source_ids": list(self.source_ids),
        }


def normalize_keyword(value: str) -> str:
    """Normalize human-maintained keywords for stable dedupe and cooldown keys."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    separators = " \t\r\n\u3000|｜/\\_-—–·,，.。:：;；()（）[]【】{}<>《》\"'“”‘’"
    return "".join(ch for ch in text if ch not in separators)


def build_keyword_candidates(config: Mapping[str, Any]) -> list[KeywordCandidate]:
    """Build a finite offline portfolio; this is not a full-site enumeration."""
    policy = PortfolioPolicy.from_mapping(config.get("policy"))
    categories = config.get("categories") or []
    seen: dict[str, KeywordCandidate] = {}
    order = 0

    for category in categories:
        category_id = str(category["id"])
        category_label = str(category.get("label") or category_id)
        layer = str(category.get("layer") or LAYER_EXPLORE)
        priority = int(category.get("priority", 50))
        seeds = _clean_terms(category.get("seed_terms") or ())
        legacy_modifiers = _clean_terms(category.get("modifiers") or ())
        seed_source_ids = tuple(_clean_terms(category.get("seed_source_ids") or ()))
        dimension_source_ids = tuple(
            _clean_terms(category.get("dimension_source_ids") or seed_source_ids)
        )
        max_generated = int(category.get("max_generated", policy.max_generated_per_category))
        dimension_budgets = category.get("dimension_budgets") or {}

        generated = 0
        for seed in seeds:
            order += 1
            candidate = _candidate(
                seed,
                category_id=category_id,
                category_label=category_label,
                layer=layer,
                source_seed=seed,
                modifier=None,
                priority=priority,
                order=order,
                combination_kind="seed",
                components=(seed,),
                source_ids=seed_source_ids,
            )
            _keep_best_candidate(seen, candidate)

        dimensions: list[tuple[str, list[str]]] = []
        if legacy_modifiers:
            dimensions.append(("product_forms", legacy_modifiers))
        for dimension in DIMENSION_ORDER:
            terms = _clean_terms(category.get(dimension) or ())
            if terms:
                dimensions.append((dimension, terms))

        for dimension, terms in dimensions:
            if generated >= max_generated or not seeds:
                break
            default_budget = len(terms)
            dimension_budget = max(
                0,
                int(dimension_budgets.get(dimension, default_budget)),
            )
            dimension_budget = min(dimension_budget, max_generated - generated)
            for offset in range(dimension_budget):
                order += 1
                generated += 1
                seed = seeds[offset % len(seeds)]
                modifier = terms[offset % len(terms)]
                phrase = _join_dimension_keyword(seed, modifier, dimension)
                candidate = _candidate(
                    phrase,
                    category_id=category_id,
                    category_label=category_label,
                    layer=layer,
                    source_seed=seed,
                    modifier=modifier,
                    priority=priority - 5,
                    order=order,
                    combination_kind=dimension,
                    components=(seed, modifier),
                    source_ids=dimension_source_ids,
                )
                _keep_best_candidate(seen, candidate)

        explore_terms = _clean_terms(category.get("explore_terms") or ())
        explore_budget = min(
            max(0, int(dimension_budgets.get("explore_terms", len(explore_terms)))),
            max(0, max_generated - generated),
        )
        for term in explore_terms[:explore_budget]:
            order += 1
            generated += 1
            candidate = _candidate(
                term,
                category_id=category_id,
                category_label=category_label,
                layer=LAYER_EXPLORE,
                source_seed=term,
                modifier=None,
                priority=priority - 10,
                order=order,
                combination_kind="explore_term",
                components=(term,),
                source_ids=dimension_source_ids,
            )
            _keep_best_candidate(seen, candidate)

    ordered = stable_rotation_order(seen.values())
    return _cap_candidates(ordered, policy=policy)


def stable_rotation_order(candidates: Iterable[KeywordCandidate]) -> list[KeywordCandidate]:
    grouped: dict[tuple[str, str], list[KeywordCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault((candidate.layer, candidate.category_id), []).append(candidate)

    ordered: list[KeywordCandidate] = []
    for layer in DEFAULT_LAYER_ORDER:
        category_keys = sorted(
            [key for key in grouped if key[0] == layer],
            key=lambda key: (-max(item.priority for item in grouped[key]), key[1]),
        )
        for items in grouped.values():
            items.sort(key=lambda item: (-item.priority, item.stable_key, item.keyword))
        while category_keys:
            next_keys = []
            for key in category_keys:
                bucket = grouped[key]
                if bucket:
                    ordered.append(bucket.pop(0))
                if bucket:
                    next_keys.append(key)
            category_keys = next_keys

    remaining_layers = sorted({candidate.layer for candidate in candidates} - set(DEFAULT_LAYER_ORDER))
    for layer in remaining_layers:
        for key in sorted([key for key in grouped if key[0] == layer], key=lambda key: key[1]):
            ordered.extend(sorted(grouped[key], key=lambda item: (-item.priority, item.stable_key, item.keyword)))
    return ordered


def build_rotation_plan(
    config: Mapping[str, Any],
    *,
    now: datetime | str,
    keyword_history: Mapping[str, Any] | None = None,
    hourly_used: int = 0,
    rotation_cursor: int = 0,
    pause_input: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    policy = PortfolioPolicy.from_mapping(config.get("policy"))
    now_dt = _parse_datetime(now)
    pause = decide_pause(pause_input or {}, now=now_dt, policy=policy)
    candidates = build_keyword_candidates(config)
    remaining_hourly = max(0, policy.hourly_budget - max(0, int(hourly_used)))
    round_budget = min(policy.per_round_budget, remaining_hourly)

    plan = {
        "version": int(config.get("version", 1)),
        "generated_at": _iso(now_dt),
        "paused": pause["paused"],
        "pause": pause,
        "scope": {
            "mode": "finite_offline_portfolio",
            "full_site_exhaustive": False,
            "production_queue_write": False,
        },
        "budget": {
            "hourly_budget": policy.hourly_budget,
            "hourly_used": max(0, int(hourly_used)),
            "hourly_remaining": remaining_hourly,
            "per_round_budget": policy.per_round_budget,
            "round_budget": round_budget,
            "keyword_cooldown_hours": policy.keyword_cooldown_hours,
            "core_share": policy.core_share,
            "min_explore_per_round": policy.min_explore_per_round,
            "max_total_candidates": policy.max_total_candidates,
        },
        "circuit_breaker": {
            "max_consecutive_failures": policy.max_consecutive_failures,
            "failure_pause_hours": policy.failure_pause_hours,
            "risk_pause_requires_manual_resume": policy.risk_pause_requires_manual_resume,
        },
        "rotation": {
            "input_cursor": max(0, int(rotation_cursor)),
            "next_cursor": max(0, int(rotation_cursor)),
            "total_candidates": len(candidates),
            "core_candidates": sum(item.layer == LAYER_CORE for item in candidates),
            "explore_candidates": sum(item.layer == LAYER_EXPLORE for item in candidates),
        },
        "selected": [],
        "deferred": [],
    }
    if pause["paused"] or round_budget <= 0 or not candidates:
        return plan

    selected, deferred, next_cursor = _select_candidates(
        candidates,
        now=now_dt,
        policy=policy,
        keyword_history=keyword_history or {},
        limit=round_budget,
        cursor=max(0, int(rotation_cursor)),
    )
    plan["rotation"]["next_cursor"] = next_cursor
    plan["selected"] = [item.to_dict() for item in selected]
    plan["deferred"] = deferred
    return plan


def decide_pause(
    pause_input: Mapping[str, Any],
    *,
    now: datetime | str,
    policy: PortfolioPolicy | None = None,
) -> dict[str, Any]:
    policy = policy or PortfolioPolicy()
    now_dt = _parse_datetime(now)
    risk_reason = _first_text(
        pause_input.get("risk_stop_reason"),
        pause_input.get("risk_reason"),
        pause_input.get("captcha_reason"),
    )
    if risk_reason:
        return {
            "paused": True,
            "scope": "global",
            "severity": "risk",
            "reason": risk_reason,
            "resume_at": None
            if policy.risk_pause_requires_manual_resume
            else _iso(now_dt + timedelta(hours=policy.failure_pause_hours)),
            "manual_resume_required": policy.risk_pause_requires_manual_resume,
        }

    failures = int(pause_input.get("consecutive_failures") or 0)
    if failures >= policy.max_consecutive_failures:
        return {
            "paused": True,
            "scope": "global",
            "severity": "failure",
            "reason": f"consecutive failures reached {failures}",
            "resume_at": _iso(now_dt + timedelta(hours=policy.failure_pause_hours)),
            "manual_resume_required": False,
        }

    return {
        "paused": False,
        "scope": None,
        "severity": None,
        "reason": None,
        "resume_at": None,
        "manual_resume_required": False,
    }


def _select_candidates(
    candidates: list[KeywordCandidate],
    *,
    now: datetime,
    policy: PortfolioPolicy,
    keyword_history: Mapping[str, Any],
    limit: int,
    cursor: int,
) -> tuple[list[KeywordCandidate], list[dict[str, Any]], int]:
    rotated = _rotate(candidates, cursor)
    core_limit = min(limit, math.ceil(limit * policy.core_share))
    explore_limit = limit - core_limit
    if limit > 1 and policy.min_explore_per_round:
        explore_limit = min(
            limit,
            max(explore_limit, policy.min_explore_per_round),
        )
        core_limit = limit - explore_limit
    selected: list[KeywordCandidate] = []
    deferred: list[dict[str, Any]] = []

    for layer, layer_limit in ((LAYER_CORE, core_limit), (LAYER_EXPLORE, explore_limit)):
        for candidate in rotated:
            if len([item for item in selected if item.layer == layer]) >= layer_limit:
                break
            if candidate.layer != layer or candidate in selected:
                continue
            cooldown_until = keyword_cooldown_until(
                candidate.normalized,
                keyword_history,
                policy=policy,
            )
            if cooldown_until and cooldown_until > now:
                deferred.append(
                    {
                        "keyword": candidate.keyword,
                        "normalized": candidate.normalized,
                        "category_id": candidate.category_id,
                        "layer": candidate.layer,
                        "reason": "keyword_cooldown",
                        "cooldown_until": _iso(cooldown_until),
                    }
                )
                continue
            selected.append(candidate)

    if len(selected) < limit:
        for candidate in rotated:
            if len(selected) >= limit:
                break
            if candidate in selected:
                continue
            cooldown_until = keyword_cooldown_until(
                candidate.normalized,
                keyword_history,
                policy=policy,
            )
            if cooldown_until and cooldown_until > now:
                if not any(item["normalized"] == candidate.normalized for item in deferred):
                    deferred.append(
                        {
                            "keyword": candidate.keyword,
                            "normalized": candidate.normalized,
                            "category_id": candidate.category_id,
                            "layer": candidate.layer,
                            "reason": "keyword_cooldown",
                            "cooldown_until": _iso(cooldown_until),
                        }
                    )
                continue
            selected.append(candidate)

    next_cursor = cursor
    if candidates:
        normalized_selected = {item.normalized for item in selected}
        for offset, candidate in enumerate(rotated, start=1):
            if candidate.normalized in normalized_selected:
                next_cursor = (cursor + offset) % len(candidates)
    return selected, deferred, next_cursor


def keyword_cooldown_until(
    normalized_keyword: str,
    keyword_history: Mapping[str, Any],
    *,
    policy: PortfolioPolicy,
) -> datetime | None:
    state = keyword_history.get(normalized_keyword) or keyword_history.get(normalize_keyword(normalized_keyword))
    if state is None:
        return None
    last_at = state.get("last_started_at") if isinstance(state, Mapping) else state
    if not last_at:
        return None
    return _parse_datetime(last_at) + timedelta(hours=policy.keyword_cooldown_hours)


def _candidate(
    keyword: str,
    *,
    category_id: str,
    category_label: str,
    layer: str,
    source_seed: str,
    modifier: str | None,
    priority: int,
    order: int,
    combination_kind: str = "seed",
    components: tuple[str, ...] = (),
    source_ids: tuple[str, ...] = (),
) -> KeywordCandidate:
    normalized = normalize_keyword(keyword)
    digest = hashlib.sha1(f"{category_id}|{layer}|{normalized}|{order}".encode("utf-8")).hexdigest()[:12]
    return KeywordCandidate(
        keyword=keyword,
        normalized=normalized,
        category_id=category_id,
        category_label=category_label,
        layer=layer,
        source_seed=source_seed,
        modifier=modifier,
        priority=priority,
        stable_key=digest,
        combination_kind=combination_kind,
        components=components,
        source_ids=source_ids,
    )


def _keep_best_candidate(seen: dict[str, KeywordCandidate], candidate: KeywordCandidate) -> None:
    if not candidate.normalized:
        return
    previous = seen.get(candidate.normalized)
    if previous is None:
        seen[candidate.normalized] = candidate
        return
    previous_rank = (previous.layer != LAYER_CORE, -previous.priority, previous.stable_key)
    candidate_rank = (candidate.layer != LAYER_CORE, -candidate.priority, candidate.stable_key)
    if candidate_rank < previous_rank:
        seen[candidate.normalized] = candidate


def _clean_terms(values: Iterable[Any]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        text = unicodedata.normalize("NFKC", str(value or "")).strip()
        if not text:
            continue
        key = normalize_keyword(text)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _join_keyword(seed: str, modifier: str) -> str:
    if normalize_keyword(modifier) in normalize_keyword(seed):
        return seed
    return f"{seed} {modifier}"


def _join_dimension_keyword(seed: str, modifier: str, dimension: str) -> str:
    if DIMENSION_JOIN_ORDER.get(dimension) == "prefix":
        return _join_keyword(modifier, seed)
    return _join_keyword(seed, modifier)


def _cap_candidates(
    candidates: list[KeywordCandidate],
    *,
    policy: PortfolioPolicy,
) -> list[KeywordCandidate]:
    cap = policy.max_total_candidates
    if cap <= 0:
        return []
    if len(candidates) <= cap:
        return candidates

    core = [item for item in candidates if item.layer == LAYER_CORE]
    explore = [item for item in candidates if item.layer == LAYER_EXPLORE]
    core_target = min(len(core), math.ceil(cap * policy.core_share))
    explore_target = min(len(explore), cap - core_target)
    selected = core[:core_target] + explore[:explore_target]
    selected_keys = {item.normalized for item in selected}

    for candidate in candidates:
        if len(selected) >= cap:
            break
        if candidate.normalized not in selected_keys:
            selected.append(candidate)
            selected_keys.add(candidate.normalized)
    return stable_rotation_order(selected)


def _rotate(items: list[KeywordCandidate], cursor: int) -> list[KeywordCandidate]:
    if not items:
        return []
    start = cursor % len(items)
    return items[start:] + items[:start]


def _parse_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None
