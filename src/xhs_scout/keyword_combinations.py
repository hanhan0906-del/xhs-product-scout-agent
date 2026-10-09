from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .keyword_portfolio import normalize_keyword
from .product_keyword_terms import ProductKeywordError, TERM_DIMENSIONS


SMALL_PRODUCT_MIN = 30
SMALL_ROOT_MIN = 10
SMALL_DOMAIN_SCENE_MIN = 3
STABLE_PRODUCT_MIN = 100
STABLE_ROOT_MIN = 30
STABLE_CANDIDATE_PRODUCT_MIN = 2


@dataclass(frozen=True)
class CombinationCandidate:
    phrase: str
    candidate_stage: str
    product_count: int
    root_count: int
    shop_count: int
    context_count: int
    support: tuple[Mapping[str, Any], ...]
    risk_flags: tuple[str, ...]
    review_status: str
    source_fingerprint: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["support"] = [dict(item) for item in self.support]
        payload["risk_flags"] = list(self.risk_flags)
        return payload


@dataclass(frozen=True)
class CombinationAnalysis:
    generation_stage: str
    product_count: int
    root_count: int
    domain_scene_count: int
    shop_count: int
    context_count: int
    gates: Mapping[str, bool]
    candidates: tuple[CombinationCandidate, ...]
    dataset_fingerprint: str

    @property
    def scope(self) -> dict[str, bool | str]:
        return {
            "mode": "offline_keyword_combination_analysis",
            "production_queue_write": False,
            "approval_write": False,
            "search_trigger": False,
            "monitor_authorization": False,
            "human_review_required": True,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "generation_stage": self.generation_stage,
            "product_count": self.product_count,
            "root_count": self.root_count,
            "domain_scene_count": self.domain_scene_count,
            "shop_count": self.shop_count,
            "context_count": self.context_count,
            "gates": dict(self.gates),
            "candidates": [item.as_dict() for item in self.candidates],
            "dataset_fingerprint": self.dataset_fingerprint,
            "scope": self.scope,
        }


def analyze_keyword_combinations(conn: sqlite3.Connection) -> CombinationAnalysis:
    records = _load_valid_records(conn)
    product_ids = {item["product_id"] for item in records}
    roots = {item["source_root"] for item in records}
    shops = {item["shop_name"] for item in records if item["shop_name"]}
    contexts = {item["run_id"] for item in records}
    domain_scene_terms = {
        term["normalized_term"]
        for item in records
        for term in item["terms"]
        if term["dimension"] in {"domain", "scene"}
    }
    gates = {
        "all_records_traceable": bool(records)
        and all(item["traceable"] for item in records),
        "small_products": len(product_ids) >= SMALL_PRODUCT_MIN,
        "small_roots": len(roots) >= SMALL_ROOT_MIN,
        "small_domain_or_scene": len(domain_scene_terms)
        >= SMALL_DOMAIN_SCENE_MIN,
        "stable_products": len(product_ids) >= STABLE_PRODUCT_MIN,
        "stable_roots": len(roots) >= STABLE_ROOT_MIN,
    }
    small_ready = all(
        gates[name]
        for name in (
            "all_records_traceable",
            "small_products",
            "small_roots",
            "small_domain_or_scene",
        )
    )
    stable_ready = small_ready and gates["stable_products"] and gates["stable_roots"]
    generation_stage = "stable" if stable_ready else "sample" if small_ready else "not_ready"

    dataset_fingerprint = _sha256(
        [
            {
                "record_id": item["record_id"],
                "source_fingerprint": item["source_fingerprint"],
            }
            for item in records
        ]
    )
    if not small_ready:
        return CombinationAnalysis(
            generation_stage=generation_stage,
            product_count=len(product_ids),
            root_count=len(roots),
            domain_scene_count=len(domain_scene_terms),
            shop_count=len(shops),
            context_count=len(contexts),
            gates=gates,
            candidates=(),
            dataset_fingerprint=dataset_fingerprint,
        )

    support_by_phrase: dict[str, list[dict[str, Any]]] = {}
    for item in records:
        for phrase, dimensions in _natural_phrases(item):
            support_by_phrase.setdefault(phrase, []).append(
                {
                    "record_id": item["record_id"],
                    "product_id": item["product_id"],
                    "source_root": item["source_root"],
                    "shop_name": item["shop_name"],
                    "context_key": item["run_id"],
                    "evidence_path": item["evidence_path"],
                    "dimensions": list(dimensions),
                }
            )

    candidates: list[CombinationCandidate] = []
    for phrase, raw_support in support_by_phrase.items():
        support = _deduplicate_support(raw_support)
        supported_products = {item["product_id"] for item in support}
        supported_roots = {item["source_root"] for item in support}
        supported_shops = {
            item["shop_name"] for item in support if item["shop_name"]
        }
        supported_contexts = {item["context_key"] for item in support}
        candidate_stage = (
            "stable"
            if stable_ready
            and len(supported_products) >= STABLE_CANDIDATE_PRODUCT_MIN
            else "sample"
        )
        fingerprint = _sha256(
            {
                "dataset_fingerprint": dataset_fingerprint,
                "phrase": phrase,
                "support": support,
            }
        )
        candidates.append(
            CombinationCandidate(
                phrase=phrase,
                candidate_stage=candidate_stage,
                product_count=len(supported_products),
                root_count=len(supported_roots),
                shop_count=len(supported_shops),
                context_count=len(supported_contexts),
                support=tuple(support),
                risk_flags=(),
                review_status="pending_review",
                source_fingerprint=fingerprint,
            )
        )
    candidates.sort(
        key=lambda item: (
            -item.product_count,
            -item.context_count,
            -len(item.phrase),
            item.phrase,
        )
    )
    return CombinationAnalysis(
        generation_stage=generation_stage,
        product_count=len(product_ids),
        root_count=len(roots),
        domain_scene_count=len(domain_scene_terms),
        shop_count=len(shops),
        context_count=len(contexts),
        gates=gates,
        candidates=tuple(candidates),
        dataset_fingerprint=dataset_fingerprint,
    )


def persist_keyword_combination_analysis(
    conn: sqlite3.Connection,
    analysis: CombinationAnalysis,
) -> int:
    if analysis.generation_stage not in {"not_ready", "sample", "stable"}:
        raise ProductKeywordError("invalid generation_stage")
    if any(item.review_status != "pending_review" for item in analysis.candidates):
        raise ProductKeywordError("new combination candidates must remain pending_review")
    if analysis.generation_stage == "not_ready" and analysis.candidates:
        raise ProductKeywordError("not_ready analysis cannot contain candidates")
    now = _now()
    conn.execute("SAVEPOINT keyword_combination_persist")
    try:
        conn.execute(
            """
            INSERT INTO keyword_combination_snapshots(
                dataset_fingerprint, generation_stage, product_count,
                root_count, domain_scene_count, shop_count, context_count,
                gates_json, scope_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dataset_fingerprint) DO NOTHING
            """,
            (
                analysis.dataset_fingerprint,
                analysis.generation_stage,
                analysis.product_count,
                analysis.root_count,
                analysis.domain_scene_count,
                analysis.shop_count,
                analysis.context_count,
                _canonical_json(dict(analysis.gates)),
                _canonical_json(analysis.scope),
                now,
            ),
        )
        row = conn.execute(
            """
            SELECT id FROM keyword_combination_snapshots
            WHERE dataset_fingerprint=?
            """,
            (analysis.dataset_fingerprint,),
        ).fetchone()
        snapshot_id = int(row["id"] if isinstance(row, sqlite3.Row) else row[0])
        existing = conn.execute(
            """
            SELECT COUNT(*) FROM keyword_combination_candidates
            WHERE snapshot_id=?
            """,
            (snapshot_id,),
        ).fetchone()[0]
        if not existing:
            for item in analysis.candidates:
                conn.execute(
                    """
                    INSERT INTO keyword_combination_candidates(
                        snapshot_id, phrase, candidate_stage, product_count,
                        root_count, shop_count, context_count, support_json,
                        risk_flags_json, review_status, source_fingerprint,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_review', ?, ?)
                    """,
                    (
                        snapshot_id,
                        item.phrase,
                        item.candidate_stage,
                        item.product_count,
                        item.root_count,
                        item.shop_count,
                        item.context_count,
                        _canonical_json(list(item.support)),
                        _canonical_json(list(item.risk_flags)),
                        item.source_fingerprint,
                        now,
                    ),
                )
        conn.execute("RELEASE SAVEPOINT keyword_combination_persist")
        return snapshot_id
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT keyword_combination_persist")
        conn.execute("RELEASE SAVEPOINT keyword_combination_persist")
        raise


def _load_valid_records(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT r.id AS record_id, r.product_id, r.observation_id, r.task_id,
               r.run_id, r.source_root, r.source_keyword, r.normalized_title,
               r.search_result_rank, r.evidence_path, r.source_fingerprint,
               r.risk_flags_json, r.noise_reasons_json, p.shop_name,
               EXISTS(
                   SELECT 1 FROM search_result_evidence s
                   WHERE s.task_id=r.task_id AND s.product_id=r.product_id
                     AND s.observation_id=r.observation_id
                     AND s.source_keyword=r.source_keyword
                     AND s.result_rank=r.search_result_rank AND s.valid=1
               ) AS has_search_evidence,
               EXISTS(
                   SELECT 1 FROM run_events e
                   WHERE e.run_id=r.run_id
                     AND (e.task_id=r.task_id OR e.product_id=r.product_id
                          OR e.observation_id=r.observation_id)
               ) AS has_run_evidence
        FROM product_keyword_records r
        JOIN products p ON p.id=r.product_id
        WHERE r.decomposition_status='complete'
          AND r.search_context_recovered=1
          AND r.share_url IS NOT NULL
        ORDER BY r.id
        """
    ).fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if json.loads(item.pop("risk_flags_json")):
            continue
        if json.loads(item.pop("noise_reasons_json")):
            continue
        item["traceable"] = bool(
            item.pop("has_search_evidence") and item.pop("has_run_evidence")
        )
        term_rows = conn.execute(
            """
            SELECT dimension, normalized_term
            FROM product_keyword_terms
            WHERE record_id=? AND review_status='pending_review'
            ORDER BY dimension, normalized_term
            """,
            (item["record_id"],),
        ).fetchall()
        item["terms"] = [dict(term) for term in term_rows]
        records.append(item)
    return records


def _natural_phrases(
    record: Mapping[str, Any],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    title = normalize_keyword(record["normalized_title"])
    located: list[tuple[int, int, str]] = []
    for term in record["terms"]:
        value = normalize_keyword(term["normalized_term"])
        start = title.find(value)
        if not value or start < 0:
            continue
        located.append((start, start + len(value), term["dimension"]))
    phrases: set[tuple[str, tuple[str, ...]]] = set()
    for left_index, left in enumerate(located):
        for right in located[left_index + 1 :]:
            first, second = sorted((left, right), key=lambda value: (value[0], value[1]))
            if first[2] == second[2] or first[1] > second[0]:
                continue
            gap = second[0] - first[1]
            if gap > 2:
                continue
            phrase = title[first[0] : second[1]]
            if 4 <= len(phrase) <= 24:
                phrases.add((phrase, tuple(sorted((first[2], second[2])))))
    return tuple(sorted(phrases, key=lambda item: (item[0], item[1])))


def _deduplicate_support(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_product: dict[int, dict[str, Any]] = {}
    for item in sorted(items, key=lambda value: (value["product_id"], value["record_id"])):
        by_product.setdefault(item["product_id"], item)
    return list(by_product.values())


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
