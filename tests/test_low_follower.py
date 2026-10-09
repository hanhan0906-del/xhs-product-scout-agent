import json

from xhs_scout.db import connect, record_note_observation, utcnow
from xhs_scout.low_follower import (
    evaluate_low_follower_evidence,
    promote_candidate_from_note_observations,
)


def test_evaluate_low_follower_requires_recent_publish_age():
    result = evaluate_low_follower_evidence(
        follower_count=188,
        likes=1200,
        published_days_ago=None,
    )
    assert result["verified"] is False
    assert "发布时间" in result["reason"]


def test_evaluate_low_follower_uses_1000_to_2000_near_band():
    core = evaluate_low_follower_evidence(
        follower_count=1000,
        likes=1000,
        published_days_ago=2,
    )
    near = evaluate_low_follower_evidence(
        follower_count=2000,
        likes=1000,
        published_days_ago=2,
    )
    above = evaluate_low_follower_evidence(
        follower_count=2001,
        likes=5000,
        published_days_ago=2,
    )
    assert core["verified"] is True
    assert core["follower_band"] == "core"
    assert "核心低粉" in core["reason"]
    assert near["verified"] is True
    assert near["follower_band"] == "near"
    assert "临界低粉" in near["reason"]
    assert above["verified"] is False
    assert above["follower_band"] == "above"
    assert "超过 2000" in above["reason"]


def test_promote_candidate_uses_note_likes_not_profile_total(tmp_path):
    (tmp_path / "note-probe").mkdir()
    (tmp_path / "profile-probe").mkdir()
    with connect(tmp_path / "test.sqlite3") as conn:
        now = utcnow()
        conn.execute(
            """
            INSERT INTO products(
                fingerprint, title, first_seen_at, last_seen_at
            ) VALUES ('low-follower-fp', 'Test product', ?, ?)
            """,
            (now, now),
        )
        product_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO candidate_assessments(
                product_id, assessed_at, evidence_grade, score,
                low_follower_verified, reasons_json, status
            ) VALUES (?, ?, 'B', 60, 0, '["trend"]', 'candidate')
            """,
            (product_id, now),
        )
        record_note_observation(
            conn,
            product_id=product_id,
            source="related_note_card",
            screenshot_path=None,
            probe_dir="note-probe",
            page_kind="note_detail",
            raw_text="Author A",
            author_name="Author A",
            likes=1200,
            published_days_ago=2,
        )
        record_note_observation(
            conn,
            product_id=product_id,
            source="author_profile_from_note",
            screenshot_path=None,
            probe_dir="profile-probe",
            page_kind="account_profile",
            raw_text="Author A",
            author_name="Author A",
            follower_count=188,
            likes=99_999,
        )

        result = promote_candidate_from_note_observations(conn, product_id)
        latest = conn.execute(
            """
            SELECT evidence_grade, score, low_follower_verified, reasons_json
            FROM candidate_assessments WHERE product_id=? ORDER BY id DESC LIMIT 1
            """,
            (product_id,),
        ).fetchone()
        evidence = conn.execute(
            "SELECT likes, follower_count FROM note_evidence WHERE product_id=?",
            (product_id,),
        ).fetchone()

    assert result["verified"] is True
    assert latest["evidence_grade"] == "A"
    assert latest["score"] == 90
    assert latest["low_follower_verified"] == 1
    assert "单条笔记互动 1200" in json.loads(latest["reasons_json"])[-1]
    assert evidence["likes"] == 1200
    assert evidence["follower_count"] == 188
