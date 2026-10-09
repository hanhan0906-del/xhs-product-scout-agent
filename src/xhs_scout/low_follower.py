from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .db import utcnow


LOW_FOLLOWER_CORE_MAX = 1_000
LOW_FOLLOWER_NEAR_MAX = 2_000


def evaluate_low_follower_evidence(
    *,
    follower_count: int,
    likes: int,
    collects: int = 0,
    comments: int = 0,
    published_days_ago: int | None,
) -> dict:
    interactions = likes + collects + comments
    recent_ok = published_days_ago is not None and published_days_ago <= 7
    strict_ok = follower_count < 200 and likes >= 100
    standard_ok = follower_count <= LOW_FOLLOWER_NEAR_MAX and likes >= 1_000
    verified = recent_ok and (strict_ok or standard_ok)
    if follower_count > LOW_FOLLOWER_NEAR_MAX:
        reason = "账号粉丝超过 2000，不属于当前低粉样本"
    elif published_days_ago is None:
        reason = "缺少单条笔记发布时间，不能判定近期爆款"
    elif published_days_ago > 7:
        reason = f"单条笔记发布于 {published_days_ago} 天前，不属于近 7 天爆款"
    elif not (strict_ok or standard_ok):
        reason = "账号粉丝较低，但单条笔记点赞尚未达到低粉爆款阈值"
    else:
        band = "核心低粉" if follower_count <= LOW_FOLLOWER_CORE_MAX else "临界低粉"
        reason = f"低粉验证通过（{band}）：粉丝 {follower_count}，单条笔记互动 {interactions}"
    return {
        "verified": verified,
        "interactions": interactions,
        "recent_ok": recent_ok,
        "strict_ok": strict_ok,
        "standard_ok": standard_ok,
        "follower_band": (
            "core"
            if follower_count <= LOW_FOLLOWER_CORE_MAX
            else "near"
            if follower_count <= LOW_FOLLOWER_NEAR_MAX
            else "above"
        ),
        "reason": reason,
    }


def _normalized_author(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "").casefold()


def validate_low_follower_evidence_chain(
    *,
    note_author_name: str | None,
    profile_author_name: str | None,
    note_evidence_path: str | None,
    profile_evidence_path: str | None,
    evidence_root: str | Path,
) -> dict[str, Any]:
    note_author = _normalized_author(note_author_name)
    profile_author = _normalized_author(profile_author_name)
    authors_match = bool(note_author and profile_author and note_author == profile_author)
    note_path_valid = _evidence_path_is_valid(note_evidence_path, evidence_root)
    profile_path_valid = _evidence_path_is_valid(profile_evidence_path, evidence_root)
    return {
        "valid": authors_match and note_path_valid and profile_path_valid,
        "authors_match": authors_match,
        "note_evidence_valid": note_path_valid,
        "profile_evidence_valid": profile_path_valid,
    }


def _evidence_path_is_valid(value: str | None, evidence_root: str | Path) -> bool:
    if not value or not str(value).strip():
        return False
    root = Path(evidence_root).resolve()
    candidate = Path(str(value).strip())
    if not candidate.is_absolute():
        candidate = root.parent / candidate if candidate.parts[:1] == (root.name,) else root / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return False
    return resolved.exists()


def _connection_evidence_root(conn: sqlite3.Connection) -> Path:
    database_path = next(
        (row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main" and row[2]),
        "",
    )
    if database_path:
        return Path(database_path).resolve().parent
    return Path(__file__).resolve().parents[2] / "data"


def _safe_json_list(value: Any) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return list(parsed) if isinstance(parsed, list) else []


def promote_candidate_from_note_observations(
    conn: sqlite3.Connection,
    product_id: int,
) -> dict:
    note = conn.execute(
        """
        SELECT id, author_name, likes, collects, comments, published_days_ago,
               probe_dir, screenshot_path
        FROM note_observations
        WHERE product_id=?
          AND source='related_note_card'
          AND page_kind='note_detail'
          AND likes IS NOT NULL
          AND published_days_ago IS NOT NULL
        ORDER BY id DESC LIMIT 1
        """,
        (product_id,),
    ).fetchone()
    profile = conn.execute(
        """
        SELECT id, author_name, follower_count, probe_dir, screenshot_path
        FROM note_observations
        WHERE product_id=?
          AND source='author_profile_from_note'
          AND page_kind='account_profile'
          AND follower_count IS NOT NULL
        ORDER BY id DESC LIMIT 1
        """,
        (product_id,),
    ).fetchone()
    if note is None or profile is None:
        return {"verified": False, "skip_reason": "note/profile evidence incomplete"}

    evidence_root = _connection_evidence_root(conn)
    chain = validate_low_follower_evidence_chain(
        note_author_name=note["author_name"],
        profile_author_name=profile["author_name"],
        note_evidence_path=note["probe_dir"] or note["screenshot_path"],
        profile_evidence_path=profile["probe_dir"] or profile["screenshot_path"],
        evidence_root=evidence_root,
    )
    if not chain["authors_match"]:
        return {"verified": False, "skip_reason": "note/profile author mismatch"}
    if not chain["note_evidence_valid"] or not chain["profile_evidence_valid"]:
        return {"verified": False, "skip_reason": "note/profile evidence path invalid"}

    evaluation = evaluate_low_follower_evidence(
        follower_count=int(profile["follower_count"]),
        likes=int(note["likes"] or 0),
        collects=int(note["collects"] or 0),
        comments=int(note["comments"] or 0),
        published_days_ago=note["published_days_ago"],
    )
    result = {
        **evaluation,
        "note_observation_id": note["id"],
        "profile_observation_id": profile["id"],
    }
    if not evaluation["verified"]:
        return result

    latest = conn.execute(
        """
        SELECT id, score, reasons_json, low_follower_verified
        FROM candidate_assessments
        WHERE product_id=? ORDER BY id DESC LIMIT 1
        """,
        (product_id,),
    ).fetchone()
    if latest is None:
        return {**result, "verified": False, "skip_reason": "candidate assessment missing"}
    if latest["low_follower_verified"]:
        return {**result, "already_verified": True}

    source_note = f"auto:note_observation:{note['id']}:profile:{profile['id']}"
    existing = conn.execute(
        "SELECT id FROM note_evidence WHERE product_id=? AND source_note=?",
        (product_id, source_note),
    ).fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO note_evidence(
                product_id, recorded_at, author_name, follower_count, likes,
                collects, comments, published_days_ago, source_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product_id,
                utcnow(),
                profile["author_name"],
                profile["follower_count"],
                note["likes"] or 0,
                note["collects"] or 0,
                note["comments"] or 0,
                note["published_days_ago"],
                source_note,
            ),
        )

    reasons = _safe_json_list(latest["reasons_json"])
    if evaluation["reason"] not in reasons:
        reasons.append(evaluation["reason"])
    cur = conn.execute(
        """
        INSERT INTO candidate_assessments(
            product_id, assessed_at, evidence_grade, score,
            low_follower_verified, reasons_json, status
        ) VALUES (?, ?, 'A', ?, 1, ?, 'candidate')
        """,
        (
            product_id,
            utcnow(),
            min(100.0, float(latest["score"]) + 30),
            json.dumps(reasons, ensure_ascii=False),
        ),
    )
    return {**result, "assessment_id": int(cur.lastrowid)}
