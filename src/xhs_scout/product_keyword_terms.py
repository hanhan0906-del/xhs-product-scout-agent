from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .keyword_portfolio import normalize_keyword


TERM_DIMENSIONS = ("domain", "scene", "audience", "format", "stage", "function")
REVIEW_STATUSES = {"pending_review", "approved", "rejected", "deprecated"}
DECOMPOSITION_STATUSES = {"complete", "evidence_gap", "risk_blocked"}

_DIMENSION_TERMS: Mapping[str, tuple[str, ...]] = {
    "domain": (
        "新媒体运营",
        "电商运营",
        "私域运营",
        "内容运营",
        "人力资源",
        "家庭教育",
        "教师发展",
        "小学语文",
        "小学数学",
        "初中语文",
        "初中数学",
        "初中英语",
        "高中语文",
        "高中数学",
        "高中英语",
        "职场",
        "社交",
        "人际关系",
        "人情世故",
        "求职",
        "运营",
        "电商",
        "设计",
        "亲子",
        "餐饮",
        "婚礼",
        "财务",
        "法律",
        "心理",
        "健康",
        "摄影",
        "编程",
        "销售",
        "管理",
        "创业",
        "语文",
        "数学",
        "英语",
    ),
    "scene": (
        "月度复盘",
        "年度复盘",
        "工作汇报",
        "述职汇报",
        "面试",
        "入职",
        "职场生存",
        "社交",
        "人际交往",
        "亲戚盘问",
        "饭局",
        "酒局",
        "备课",
        "开店",
        "招聘",
        "婚礼",
        "考试",
        "预习",
        "复习",
        "会议",
        "直播",
        "短视频",
        "记账",
        "营销",
        "策划",
        "复盘",
    ),
    "audience": (
        "职场新人",
        "普通人",
        "i人",
        "新员工",
        "小学生",
        "初中生",
        "高中生",
        "大学生",
        "创业者",
        "设计师",
        "运营人",
        "宝妈",
        "家长",
        "教师",
        "老师",
        "学生",
        "店主",
        "销售",
        "HR",
    ),
    "stage": (
        "零基础",
        "新手入门",
        "开业",
        "年度",
        "月度",
        "周度",
        "暑假",
        "寒假",
        "节日",
        "备考",
        "冲刺",
        "入门",
        "新手",
        "新人",
        "上册",
        "下册",
        "一年级",
        "二年级",
        "三年级",
        "四年级",
        "五年级",
        "六年级",
        "初一",
        "初二",
        "初三",
        "高一",
        "高二",
        "高三",
    ),
    "function": (
        "客户管理",
        "项目管理",
        "时间管理",
        "数据分析",
        "成本测算",
        "获客",
        "复盘",
        "核对",
        "测算",
        "管理",
        "规划",
        "记录",
        "分析",
        "提分",
        "备课",
        "招聘",
        "记忆",
        "练习",
        "统计",
        "排期",
        "应答",
        "沟通",
        "社交",
        "拒绝",
        "避坑",
        "成长",
    ),
}

_FORMAT_FALLBACKS = (
    "Excel模板",
    "PPT模板",
    "Word模板",
    "Notion模板",
    "飞书模板",
    "电子表格",
    "电子书",
    "资料包",
    "工具包",
    "提示词包",
    "课程包",
    "复盘表",
    "计划表",
    "清单",
    "表格",
    "模板",
    "手册",
    "指南",
    "攻略",
    "笔记",
    "方案",
    "题库",
    "课件",
    "教案",
    "脚本",
    "教程",
    "资料库",
)

_HARD_RISKS: Mapping[str, re.Pattern[str]] = {
    "contact_or_diversion": re.compile(
        r"(加微|微信|微.?信|vx|v信|私聊|私信领取|联系我|引流)",
        re.IGNORECASE,
    ),
    "transaction_prompt": re.compile(r"(拍下|下单|购买链接|付款|卡密|自动发货)"),
    "piracy_or_evasion": re.compile(r"(破解版|盗版|破解软件|绕过|免登录)"),
}
_NOISE_PATTERNS: Mapping[str, re.Pattern[str]] = {
    "url": re.compile(r"(?:https?://|www\.)", re.IGNORECASE),
    "price": re.compile(r"(?:￥|¥)\s*\d"),
    "marketing_noise": re.compile(r"(限时|全网最低|优惠券|包邮|好评返现)"),
    "ocr_gibberish": re.compile(r"(资枓|模扳|课桯|^[lI1O0|]{4,})"),
}
_TITLE_SEPARATORS = re.compile(r"[|｜/\\,，;；:：\s]+")


class ProductKeywordError(ValueError):
    """Raised when keyword decomposition evidence is incomplete or inconsistent."""


@dataclass(frozen=True)
class KeywordTerm:
    dimension: str
    raw_term: str
    normalized_term: str
    evidence_excerpt: str
    risk_flags: tuple[str, ...] = ()
    review_status: str = "pending_review"

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["risk_flags"] = list(self.risk_flags)
        return value


@dataclass(frozen=True)
class ProductKeywordDecomposition:
    source_root: str
    source_keyword: str
    run_id: str
    task_id: int
    product_id: int
    observation_id: int
    raw_title: str
    normalized_title: str
    search_result_rank: int
    search_context_recovered: bool
    share_url: str | None
    link_gap: str | None
    evidence_path: str
    evidence: Mapping[str, Any]
    terms: Mapping[str, tuple[KeywordTerm, ...]]
    risk_flags: tuple[str, ...]
    noise_reasons: tuple[str, ...]
    decomposition_status: str
    review_status: str
    source_fingerprint: str

    @property
    def scope(self) -> dict[str, bool | str]:
        return {
            "mode": "offline_product_keyword_decomposition",
            "production_queue_write": False,
            "approval_write": False,
            "search_trigger": False,
            "monitor_authorization": False,
            "human_review_required": True,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_root": self.source_root,
            "source_keyword": self.source_keyword,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "product_id": self.product_id,
            "observation_id": self.observation_id,
            "raw_title": self.raw_title,
            "normalized_title": self.normalized_title,
            "search_result_rank": self.search_result_rank,
            "search_context_recovered": self.search_context_recovered,
            "share_url": self.share_url,
            "link_gap": self.link_gap,
            "evidence_path": self.evidence_path,
            "evidence": _jsonable(self.evidence),
            "terms": {
                name: [term.as_dict() for term in self.terms.get(name, ())]
                for name in TERM_DIMENSIONS
            },
            "risk_flags": list(self.risk_flags),
            "noise_reasons": list(self.noise_reasons),
            "decomposition_status": self.decomposition_status,
            "review_status": self.review_status,
            "source_fingerprint": self.source_fingerprint,
            "scope": self.scope,
        }


def load_discovery_roots(
    path: str | Path,
    *,
    expected_count: int | None = 100,
) -> tuple[str, ...]:
    source = Path(path).resolve(strict=True)
    values = tuple(
        line.strip()
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    normalized = [normalize_keyword(item) for item in values]
    if any(not item for item in normalized):
        raise ProductKeywordError("discovery roots contain an empty normalized term")
    if len(set(normalized)) != len(normalized):
        raise ProductKeywordError("discovery roots must be unique after normalization")
    if expected_count is not None and len(values) != expected_count:
        raise ProductKeywordError(
            f"discovery roots must contain exactly {expected_count} terms"
        )
    return values


def decompose_product_keywords(
    *,
    source_root: str,
    source_keyword: str,
    run_id: str,
    task_id: int,
    product_id: int,
    observation_id: int,
    raw_title: str,
    search_result_rank: int,
    search_context_recovered: bool,
    evidence_path: str | Path,
    evidence: Mapping[str, Any],
    discovery_roots: Iterable[str],
    share_url: str | None = None,
    link_gap: str | None = None,
) -> ProductKeywordDecomposition:
    roots = tuple(_required_text(item, "discovery_root") for item in discovery_roots)
    root_by_normalized = {normalize_keyword(item): item for item in roots}
    root_normalized = normalize_keyword(_required_text(source_root, "source_root"))
    if root_normalized not in root_by_normalized:
        raise ProductKeywordError("source_root is not in the active discovery root set")
    source_root = root_by_normalized[root_normalized]
    source_keyword = _required_text(source_keyword, "source_keyword")
    run_id = _required_text(run_id, "run_id")
    raw_title = _required_text(raw_title, "raw_title")
    evidence_path_text = _required_text(str(evidence_path), "evidence_path")
    if not isinstance(search_context_recovered, bool) or not search_context_recovered:
        raise ProductKeywordError(
            "search context must be explicitly recovered before decomposition"
        )
    for label, value in (
        ("task_id", task_id),
        ("product_id", product_id),
        ("observation_id", observation_id),
        ("search_result_rank", search_result_rank),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ProductKeywordError(f"{label} must be a positive integer")
    if not isinstance(evidence, Mapping) or not evidence:
        raise ProductKeywordError("evidence must be a non-empty object")
    share_url = _optional_text(share_url)
    link_gap = _optional_text(link_gap)
    if share_url is None and link_gap is None:
        raise ProductKeywordError("missing share_url requires an explicit link_gap")

    normalized_title = _normalize_title(raw_title)
    risk_flags = tuple(
        name for name, pattern in _HARD_RISKS.items() if pattern.search(raw_title)
    )
    noise_reasons = tuple(
        name for name, pattern in _NOISE_PATTERNS.items() if pattern.search(raw_title)
    )
    terms = _extract_terms(
        normalized_title,
        discovery_roots=roots,
        risk_flags=risk_flags,
    )
    term_count = sum(len(items) for items in terms.values())
    if risk_flags:
        status = "risk_blocked"
    elif share_url is None or not term_count:
        status = "evidence_gap"
    else:
        status = "complete"
    fingerprint_payload = {
        "source_root": source_root,
        "source_keyword": source_keyword,
        "run_id": run_id,
        "task_id": task_id,
        "product_id": product_id,
        "observation_id": observation_id,
        "raw_title": raw_title,
        "normalized_title": normalized_title,
        "search_result_rank": search_result_rank,
        "share_url": share_url,
        "link_gap": link_gap,
        "evidence_path": evidence_path_text,
        "terms": {
            name: [term.as_dict() for term in terms[name]]
            for name in TERM_DIMENSIONS
        },
        "risk_flags": list(risk_flags),
        "noise_reasons": list(noise_reasons),
    }
    return ProductKeywordDecomposition(
        source_root=source_root,
        source_keyword=source_keyword,
        run_id=run_id,
        task_id=task_id,
        product_id=product_id,
        observation_id=observation_id,
        raw_title=raw_title,
        normalized_title=normalized_title,
        search_result_rank=search_result_rank,
        search_context_recovered=True,
        share_url=share_url,
        link_gap=link_gap,
        evidence_path=evidence_path_text,
        evidence=_jsonable(evidence),
        terms=terms,
        risk_flags=risk_flags,
        noise_reasons=noise_reasons,
        decomposition_status=status,
        review_status="pending_review",
        source_fingerprint=_sha256(fingerprint_payload),
    )


def persist_product_keyword_decomposition(
    conn: sqlite3.Connection,
    decomposition: ProductKeywordDecomposition,
    *,
    evidence_allowed_roots: Sequence[str | Path],
) -> int:
    if decomposition.review_status != "pending_review":
        raise ProductKeywordError("new decompositions must remain pending_review")
    if decomposition.decomposition_status not in DECOMPOSITION_STATUSES:
        raise ProductKeywordError("invalid decomposition_status")
    evidence_path = _resolve_evidence_path(
        decomposition.evidence_path,
        evidence_allowed_roots,
    )
    _validate_database_chain(conn, decomposition)
    now = _now()

    conn.execute("SAVEPOINT product_keyword_persist")
    try:
        conn.execute(
            """
            INSERT INTO product_keyword_records(
                product_id, observation_id, task_id, run_id, source_root,
                source_keyword, raw_title, normalized_title, search_result_rank,
                search_context_recovered, share_url, link_gap, evidence_path,
                evidence_json, risk_flags_json, noise_reasons_json,
                decomposition_status, review_status, source_fingerprint,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_id, observation_id, source_root) DO UPDATE SET
                task_id=excluded.task_id,
                run_id=excluded.run_id,
                source_keyword=excluded.source_keyword,
                raw_title=excluded.raw_title,
                normalized_title=excluded.normalized_title,
                search_result_rank=excluded.search_result_rank,
                search_context_recovered=1,
                share_url=excluded.share_url,
                link_gap=excluded.link_gap,
                evidence_path=excluded.evidence_path,
                evidence_json=excluded.evidence_json,
                risk_flags_json=excluded.risk_flags_json,
                noise_reasons_json=excluded.noise_reasons_json,
                decomposition_status=excluded.decomposition_status,
                review_status='pending_review',
                source_fingerprint=excluded.source_fingerprint,
                updated_at=excluded.updated_at
            """,
            (
                decomposition.product_id,
                decomposition.observation_id,
                decomposition.task_id,
                decomposition.run_id,
                decomposition.source_root,
                decomposition.source_keyword,
                decomposition.raw_title,
                decomposition.normalized_title,
                decomposition.search_result_rank,
                decomposition.share_url,
                decomposition.link_gap,
                str(evidence_path),
                _canonical_json(decomposition.evidence),
                _canonical_json(list(decomposition.risk_flags)),
                _canonical_json(list(decomposition.noise_reasons)),
                decomposition.decomposition_status,
                decomposition.review_status,
                decomposition.source_fingerprint,
                now,
                now,
            ),
        )
        row = conn.execute(
            """
            SELECT id FROM product_keyword_records
            WHERE product_id=? AND observation_id=? AND source_root=?
            """,
            (
                decomposition.product_id,
                decomposition.observation_id,
                decomposition.source_root,
            ),
        ).fetchone()
        record_id = int(row["id"] if isinstance(row, sqlite3.Row) else row[0])
        conn.execute(
            "DELETE FROM product_keyword_terms WHERE record_id=?",
            (record_id,),
        )
        for dimension in TERM_DIMENSIONS:
            for term in decomposition.terms.get(dimension, ()):
                conn.execute(
                    """
                    INSERT INTO product_keyword_terms(
                        record_id, dimension, raw_term, normalized_term,
                        evidence_excerpt, risk_flags_json, review_status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'pending_review', ?)
                    """,
                    (
                        record_id,
                        term.dimension,
                        term.raw_term,
                        term.normalized_term,
                        term.evidence_excerpt,
                        _canonical_json(list(term.risk_flags)),
                        now,
                    ),
                )
        conn.execute("RELEASE SAVEPOINT product_keyword_persist")
        return record_id
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT product_keyword_persist")
        conn.execute("RELEASE SAVEPOINT product_keyword_persist")
        raise


def load_product_keyword_decomposition(
    conn: sqlite3.Connection,
    record_id: int,
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM product_keyword_records WHERE id=?",
        (record_id,),
    ).fetchone()
    if row is None:
        return None
    payload = dict(row)
    for field in ("evidence_json", "risk_flags_json", "noise_reasons_json"):
        payload[field.removesuffix("_json")] = json.loads(payload.pop(field))
    terms = {name: [] for name in TERM_DIMENSIONS}
    for term in conn.execute(
        """
        SELECT dimension, raw_term, normalized_term, evidence_excerpt,
               risk_flags_json, review_status
        FROM product_keyword_terms
        WHERE record_id=?
        ORDER BY dimension, normalized_term
        """,
        (record_id,),
    ):
        item = dict(term)
        item["risk_flags"] = json.loads(item.pop("risk_flags_json"))
        terms[item["dimension"]].append(item)
    payload["terms"] = terms
    payload["scope"] = {
        "production_queue_write": False,
        "approval_write": False,
        "search_trigger": False,
        "monitor_authorization": False,
    }
    return payload


def _extract_terms(
    normalized_title: str,
    *,
    discovery_roots: Sequence[str],
    risk_flags: tuple[str, ...],
) -> dict[str, tuple[KeywordTerm, ...]]:
    compact = normalize_keyword(normalized_title)
    result: dict[str, tuple[KeywordTerm, ...]] = {}
    for dimension in TERM_DIMENSIONS:
        if dimension == "format":
            candidates = tuple(dict.fromkeys((*_FORMAT_FALLBACKS, *discovery_roots)))
        else:
            candidates = _DIMENSION_TERMS[dimension]
        found: list[KeywordTerm] = []
        seen: set[str] = set()
        for raw_term in sorted(candidates, key=lambda value: (-len(value), value)):
            normalized = normalize_keyword(raw_term)
            if not normalized or normalized not in compact or normalized in seen:
                continue
            seen.add(normalized)
            found.append(
                KeywordTerm(
                    dimension=dimension,
                    raw_term=raw_term,
                    normalized_term=normalized,
                    evidence_excerpt=normalized_title,
                    risk_flags=risk_flags,
                )
            )
        result[dimension] = tuple(found)
    return result


def _validate_database_chain(
    conn: sqlite3.Connection,
    decomposition: ProductKeywordDecomposition,
) -> None:
    product = conn.execute(
        "SELECT id, title, share_url FROM products WHERE id=?",
        (decomposition.product_id,),
    ).fetchone()
    if product is None:
        raise ProductKeywordError("product_id does not exist")
    observation = conn.execute(
        "SELECT product_id FROM observations WHERE id=?",
        (decomposition.observation_id,),
    ).fetchone()
    if observation is None:
        raise ProductKeywordError("observation_id does not exist")
    observation_product = (
        observation["product_id"]
        if isinstance(observation, sqlite3.Row)
        else observation[0]
    )
    if observation_product != decomposition.product_id:
        raise ProductKeywordError("observation does not belong to product")
    if conn.execute(
        "SELECT 1 FROM search_tasks WHERE id=?",
        (decomposition.task_id,),
    ).fetchone() is None:
        raise ProductKeywordError("task_id does not exist")
    search = conn.execute(
        """
        SELECT 1 FROM search_result_evidence
        WHERE task_id=? AND product_id=? AND observation_id=?
          AND source_keyword=? AND result_rank=? AND valid=1
        """,
        (
            decomposition.task_id,
            decomposition.product_id,
            decomposition.observation_id,
            decomposition.source_keyword,
            decomposition.search_result_rank,
        ),
    ).fetchone()
    if search is None:
        raise ProductKeywordError(
            "valid search evidence does not match task/product/observation"
        )
    run = conn.execute(
        """
        SELECT 1 FROM run_events
        WHERE run_id=?
          AND (task_id=? OR product_id=? OR observation_id=?)
        LIMIT 1
        """,
        (
            decomposition.run_id,
            decomposition.task_id,
            decomposition.product_id,
            decomposition.observation_id,
        ),
    ).fetchone()
    if run is None:
        raise ProductKeywordError("run_id is not linked to the supplied evidence")


def _resolve_evidence_path(
    value: str | Path,
    roots: Sequence[str | Path],
) -> Path:
    if not roots:
        raise ProductKeywordError("evidence_allowed_roots must not be empty")
    resolved_roots = tuple(Path(root).resolve(strict=True) for root in roots)
    candidate = Path(value)
    if not candidate.is_absolute():
        if len(resolved_roots) != 1:
            raise ProductKeywordError(
                "relative evidence_path requires exactly one allowed root"
            )
        candidate = resolved_roots[0] / candidate
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file():
        raise ProductKeywordError("evidence_path must be an existing file")
    if not any(_is_relative_to(resolved, root) for root in resolved_roots):
        raise ProductKeywordError("evidence_path resolves outside allowed roots")
    return resolved


def _normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).strip()
    return _TITLE_SEPARATORS.sub(" ", text).strip()


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProductKeywordError(f"{label} must be a non-empty string")
    text = value.strip()
    if any(character in text for character in ("\r", "\n", "\x00")):
        raise ProductKeywordError(f"{label} contains a forbidden control character")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return _required_text(value, "optional_text")


def _jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ProductKeywordError("evidence must be finite JSON data") from exc


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
