from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from xhs_scout.keyword_portfolio import normalize_keyword


SOURCE_WEIGHTS = {
    "successful_search": 2.0,
    "product_title": 1.0,
    "shop_public_text": 0.75,
    "trend_label": 1.25,
}

DOMAIN_ENDINGS = (
    "工作流模板",
    "学习资料",
    "复习资料",
    "备课资料",
    "运营资料",
    "课程资料",
    "资料包",
    "工具包",
    "提示词包",
    "课程包",
    "模板",
    "资料",
    "课件",
    "题库",
    "教案",
    "手册",
    "课程",
    "训练",
    "素材",
    "试卷",
    "笔记",
    "清单",
    "表格",
    "方案",
    "提示词",
    "工作流",
    "电子书",
    "量表",
    "测评",
    "脚本",
    "合同",
    "简历",
)

HARD_RISK_PATTERNS = {
    "contact_or_diversion": re.compile(
        r"(加微|微信|微.?信|vx|v信|私聊|私信领取|联系我|引流)",
        re.IGNORECASE,
    ),
    "transaction_prompt": re.compile(r"(拍下|下单|购买链接|付款|卡密|自动发货)"),
    "piracy_or_evasion": re.compile(r"(破解版|盗版|破解软件|绕过|免登录)"),
}

JUNK_PATTERNS = {
    "marketing_noise": re.compile(
        r"(限时|秒[发杀]|全网最低|仅售|优惠券|包邮|已售|销量|好评返现|爆款|同款)"
    ),
    "store_boilerplate": re.compile(
        r"(欢迎光临|官方旗舰店|专营店|客服在线|点击查看|更多详情|进店看看)"
    ),
    "price_or_count": re.compile(
        r"(^|\D)(?:￥|¥)\s*\d|^\d+(?:\.\d+)?(?:元|份|套|人付款|人已购)?$"
    ),
    "url": re.compile(r"(?:https?://|www\.|[a-z0-9-]+\.(?:com|cn)(?:/|$))", re.IGNORECASE),
}

SOFT_RISK_PATTERNS = {
    "free_claim": re.compile(r"(免费领|免费送|0元|零元)"),
    "copyright_unclear": re.compile(r"(内部资料|独家整理|全套合集|全网合集)"),
}

_SPLIT_RE = re.compile(r"[\r\n|｜,，。;；:：!?！？/\\]+")
_BRACKET_RE = re.compile(r"[\(\（\[【{《<][^\)\）\]】}》>]{0,40}[\)\）\]】}》>]")
_SPACE_RE = re.compile(r"\s+")
_LEADING_NOISE_RE = re.compile(
    r"^(?:新品|爆款|推荐|限时|现货|正版|电子版|可打印|可编辑|202\d年?)+"
)
_TRAILING_NOISE_RE = re.compile(
    r"(?:电子版|可打印|可编辑|高清|完整版|全套|合集|秒发|自动发货)+$"
)
_WINDOW_LEADING_FRAGMENT_RE = re.compile(
    r"^(?:适用于|适合于|专为|针对|面向|适合|为|给|供)"
)
_OCR_HAN_CONFUSIONS = ("资枓", "模扳", "课桯")
_OCR_ASCII_CONFUSABLE_PREFIX_RE = re.compile(r"^[lI1O0|]{4,}")


@dataclass(frozen=True)
class DiscoveryPolicy:
    """Finite, offline-only discovery limits."""

    max_output: int = 20
    max_phrases_per_field: int = 6
    min_keyword_chars: int = 2
    max_keyword_chars: int = 18
    extraction_window_chars: int = 14
    core_min_support_score: float = 3.0
    core_min_source_types: int = 2

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any] | None,
    ) -> "DiscoveryPolicy":
        data = data or {}
        return cls(
            max_output=max(0, int(data.get("max_output", cls.max_output))),
            max_phrases_per_field=max(
                1,
                int(data.get("max_phrases_per_field", cls.max_phrases_per_field)),
            ),
            min_keyword_chars=max(
                1,
                int(data.get("min_keyword_chars", cls.min_keyword_chars)),
            ),
            max_keyword_chars=max(
                2,
                int(data.get("max_keyword_chars", cls.max_keyword_chars)),
            ),
            extraction_window_chars=max(
                2,
                int(data.get("extraction_window_chars", cls.extraction_window_chars)),
            ),
            core_min_support_score=max(
                0.0,
                float(data.get("core_min_support_score", cls.core_min_support_score)),
            ),
            core_min_source_types=max(
                1,
                int(data.get("core_min_source_types", cls.core_min_source_types)),
            ),
        )


def discover_keyword_candidates(
    *,
    products: Iterable[Mapping[str, Any]] = (),
    successful_searches: Iterable[str | Mapping[str, Any]] = (),
    trend_labels: Iterable[str | Mapping[str, Any]] = (),
    existing_keywords: Iterable[str | Mapping[str, Any]] = (),
    policy: DiscoveryPolicy | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return bounded keyword suggestions without opening a DB or writing a queue.

    Inputs are intentionally plain mappings so callers can supply database rows,
    JSON exports, or test fixtures. The function has no persistence side effects.
    """

    active_policy = (
        policy
        if isinstance(policy, DiscoveryPolicy)
        else DiscoveryPolicy.from_mapping(policy)
    )
    existing = {
        normalize_keyword(_keyword_value(item))
        for item in existing_keywords
        if normalize_keyword(_keyword_value(item))
    }
    evidence_by_keyword: dict[str, list[dict[str, Any]]] = {}
    display_by_keyword: dict[str, str] = {}
    filtered: list[dict[str, Any]] = []
    raw_occurrences = 0

    def add_phrase(
        phrase: str,
        *,
        source_type: str,
        source_id: str,
        product_id: str | None = None,
        source_keyword: str | None = None,
    ) -> None:
        nonlocal raw_occurrences
        raw_occurrences += 1
        cleaned = _clean_phrase(phrase)
        normalized = normalize_keyword(cleaned)
        rejection = _rejection_reason(cleaned, normalized, active_policy)
        evidence = {
            "source_type": source_type,
            "source_id": source_id,
            "product_id": product_id,
            "source_keyword": _clean_phrase(source_keyword or "") or None,
        }
        if rejection:
            filtered.append(
                {
                    "keyword": cleaned or str(phrase or "").strip(),
                    "normalized": normalized,
                    "reason": rejection,
                    "source_type": source_type,
                    "source_id": source_id,
                }
            )
            return
        if normalized in existing:
            filtered.append(
                {
                    "keyword": cleaned,
                    "normalized": normalized,
                    "reason": "already_in_portfolio",
                    "source_type": source_type,
                    "source_id": source_id,
                }
            )
            return
        display_by_keyword.setdefault(normalized, cleaned)
        bucket = evidence_by_keyword.setdefault(normalized, [])
        evidence_key = (
            source_type,
            source_id,
            product_id,
            normalize_keyword(evidence["source_keyword"] or ""),
        )
        if evidence_key not in {
            (
                item["source_type"],
                item["source_id"],
                item["product_id"],
                normalize_keyword(item["source_keyword"] or ""),
            )
            for item in bucket
        }:
            bucket.append(evidence)

    for index, product in enumerate(products):
        product_id = _first_text(
            product.get("product_id"),
            product.get("id"),
            f"product-{index + 1}",
        )
        source_keyword = _first_text(
            product.get("source_keyword"),
            product.get("search_keyword"),
        )
        if source_keyword:
            add_phrase(
                source_keyword,
                source_type="successful_search",
                source_id=f"product-search:{product_id}",
                product_id=product_id,
                source_keyword=source_keyword,
            )

        for field in ("title", "product_title"):
            value = _first_text(product.get(field))
            if value:
                for phrase in _extract_text_phrases(value, policy=active_policy):
                    add_phrase(
                        phrase,
                        source_type="product_title",
                        source_id=f"{product_id}:{field}",
                        product_id=product_id,
                        source_keyword=source_keyword,
                    )
                break

        shop_text = _first_text(
            product.get("shop_public_text"),
            product.get("shop_text"),
            product.get("store_public_text"),
        )
        if shop_text:
            for phrase in _extract_text_phrases(shop_text, policy=active_policy):
                add_phrase(
                    phrase,
                    source_type="shop_public_text",
                    source_id=f"{product_id}:shop_public_text",
                    product_id=product_id,
                    source_keyword=source_keyword,
                )

        for label_index, label in enumerate(
            _as_sequence(product.get("trend_labels") or product.get("trend_tags"))
        ):
            add_phrase(
                _keyword_value(label),
                source_type="trend_label",
                source_id=f"{product_id}:trend:{label_index + 1}",
                product_id=product_id,
                source_keyword=source_keyword,
            )

    for index, item in enumerate(successful_searches):
        keyword = _keyword_value(item)
        mapping = item if isinstance(item, Mapping) else {}
        product_id = _first_text(mapping.get("product_id")) or None
        source_id = _first_text(mapping.get("id"), f"successful-search-{index + 1}")
        add_phrase(
            keyword,
            source_type="successful_search",
            source_id=source_id,
            product_id=product_id,
            source_keyword=keyword,
        )

    for index, item in enumerate(trend_labels):
        mapping = item if isinstance(item, Mapping) else {}
        add_phrase(
            _keyword_value(item),
            source_type="trend_label",
            source_id=_first_text(mapping.get("id"), f"trend-{index + 1}"),
            product_id=_first_text(mapping.get("product_id")) or None,
            source_keyword=_first_text(mapping.get("source_keyword")),
        )

    candidates = [
        _build_candidate(normalized, display_by_keyword[normalized], evidence, active_policy)
        for normalized, evidence in evidence_by_keyword.items()
    ]
    candidates.sort(
        key=lambda item: (
            item["suggested_layer"] != "core",
            -item["support"]["score"],
            -item["support"]["distinct_products"],
            item["normalized"],
        )
    )
    total_before_cap = len(candidates)
    selected = candidates[: active_policy.max_output]

    return {
        "version": 1,
        "scope": {
            "mode": "offline_keyword_suggestions",
            "database_access": False,
            "production_queue_write": False,
            "search_trigger": False,
            "human_review_required": True,
        },
        "policy": {
            "max_output": active_policy.max_output,
            "max_phrases_per_field": active_policy.max_phrases_per_field,
            "min_keyword_chars": active_policy.min_keyword_chars,
            "max_keyword_chars": active_policy.max_keyword_chars,
            "core_min_support_score": active_policy.core_min_support_score,
            "core_min_source_types": active_policy.core_min_source_types,
        },
        "stats": {
            "raw_occurrences": raw_occurrences,
            "unique_candidates_before_cap": total_before_cap,
            "returned_candidates": len(selected),
            "truncated_candidates": max(0, total_before_cap - len(selected)),
            "filtered_occurrences": len(filtered),
            "existing_portfolio_occurrences": sum(
                item["reason"] == "already_in_portfolio" for item in filtered
            ),
        },
        "candidates": selected,
        "filtered": filtered,
    }


def _build_candidate(
    normalized: str,
    keyword: str,
    evidence: list[dict[str, Any]],
    policy: DiscoveryPolicy,
) -> dict[str, Any]:
    source_types = sorted({item["source_type"] for item in evidence})
    source_products = sorted(
        {item["product_id"] for item in evidence if item["product_id"] is not None}
    )
    source_keywords = sorted(
        {item["source_keyword"] for item in evidence if item["source_keyword"]}
    )
    score = round(
        sum(SOURCE_WEIGHTS.get(item["source_type"], 0.5) for item in evidence),
        2,
    )
    risk_flags = sorted(
        name
        for name, pattern in SOFT_RISK_PATTERNS.items()
        if pattern.search(keyword)
    )
    enough_independent_support = (
        len(source_products) >= 2 or len(source_types) >= policy.core_min_source_types
    )
    suggested_layer = (
        "core"
        if score >= policy.core_min_support_score
        and enough_independent_support
        and not risk_flags
        else "explore"
    )
    return {
        "candidate_id": hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16],
        "keyword": keyword,
        "normalized": normalized,
        "suggested_layer": suggested_layer,
        "review_status": "pending_review",
        "risk_flags": risk_flags,
        "support": {
            "score": score,
            "evidence_count": len(evidence),
            "distinct_products": len(source_products),
            "distinct_source_types": len(source_types),
            "source_types": source_types,
        },
        "source_products": source_products,
        "source_keywords": source_keywords,
        "evidence": sorted(
            evidence,
            key=lambda item: (
                item["source_type"],
                item["source_id"],
                item["product_id"] or "",
            ),
        ),
    }


def _extract_text_phrases(
    value: str,
    *,
    policy: DiscoveryPolicy,
) -> list[str]:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = _BRACKET_RE.sub(" ", text)
    results: list[str] = []
    seen: set[str] = set()
    for segment in _SPLIT_RE.split(text):
        compact = _SPACE_RE.sub("", segment).strip("#*~-—_")
        if not compact:
            continue
        matches: list[str] = []
        if (
            len(compact) <= policy.max_keyword_chars
            and any(ending in compact for ending in DOMAIN_ENDINGS)
        ):
            matches.append(compact)
        else:
            for ending in DOMAIN_ENDINGS:
                start = 0
                while True:
                    position = compact.find(ending, start)
                    if position < 0:
                        break
                    end = position + len(ending)
                    window_start = max(0, end - policy.extraction_window_chars)
                    window = compact[window_start:end]
                    matches.append(_WINDOW_LEADING_FRAGMENT_RE.sub("", window))
                    start = position + 1
        for phrase in matches:
            phrase = _LEADING_NOISE_RE.sub("", phrase)
            phrase = _TRAILING_NOISE_RE.sub("", phrase)
            normalized = normalize_keyword(phrase)
            if normalized and normalized not in seen:
                seen.add(normalized)
                results.append(phrase)
            if len(results) >= policy.max_phrases_per_field:
                return results
    return results


def _rejection_reason(
    cleaned: str,
    normalized: str,
    policy: DiscoveryPolicy,
) -> str | None:
    if not normalized:
        return "empty"
    if len(normalized) < policy.min_keyword_chars:
        return "too_short"
    if len(normalized) > policy.max_keyword_chars:
        return "too_long"
    for reason, pattern in HARD_RISK_PATTERNS.items():
        if pattern.search(cleaned):
            return reason
    for reason, pattern in JUNK_PATTERNS.items():
        if pattern.search(cleaned):
            return reason
    if _looks_like_ocr_gibberish(cleaned):
        return "ocr_gibberish"
    if not re.search(r"[\u4e00-\u9fffA-Za-z]", normalized):
        return "no_semantic_text"
    return None


def _looks_like_ocr_gibberish(value: str) -> bool:
    if sum(confusion in value for confusion in _OCR_HAN_CONFUSIONS) >= 2:
        return True
    prefix = _OCR_ASCII_CONFUSABLE_PREFIX_RE.match(value)
    if not prefix:
        return False
    text = prefix.group(0)
    return bool(re.search(r"[lIO]", text) and re.search(r"[10]", text))


def _clean_phrase(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = text.lstrip("#＃")
    text = _BRACKET_RE.sub("", text)
    text = _SPACE_RE.sub(" ", text)
    return text.strip(" \t\r\n|｜,，.。:：;；!?！？/\\_-—–·*")


def _keyword_value(item: str | Mapping[str, Any]) -> str:
    if isinstance(item, Mapping):
        return _first_text(
            item.get("keyword"),
            item.get("normalized"),
            item.get("label"),
            item.get("tag"),
            item.get("text"),
        )
    return str(item or "")


def _as_sequence(value: Any) -> Sequence[Any]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    if isinstance(value, Sequence):
        return value
    return tuple(value)


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
