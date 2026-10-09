import json

import pytest

from xhs_scout.config import Settings
from xhs_scout.db import connect, record_note_observation, utcnow
from xhs_scout.digest import CandidateSnapshot, build_daily_digest
from xhs_scout.low_follower import promote_candidate_from_note_observations


def _seed_candidate(settings, *, reasons_json='["trend"]'):
    with connect(settings.db_path) as conn:
        now = utcnow()
        conn.execute(
            """
            INSERT INTO products(fingerprint, title, first_seen_at, last_seen_at)
            VALUES ('evidence-integrity', 'Evidence candidate', ?, ?)
            """,
            (now, now),
        )
        product_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO candidate_assessments(
                product_id, assessed_at, evidence_grade, score,
                low_follower_verified, reasons_json, status
            ) VALUES (?, ?, 'B', 60, 0, ?, 'candidate')
            """,
            (product_id, now, reasons_json),
        )
    return product_id


def _record_chain(
    settings,
    product_id,
    *,
    note_author="Author A",
    profile_author="Author A",
    note_path=None,
    profile_path=None,
):
    with connect(settings.db_path) as conn:
        record_note_observation(
            conn,
            product_id=product_id,
            source="related_note_card",
            screenshot_path=None,
            probe_dir=str(note_path) if note_path is not None else None,
            page_kind="note_detail",
            raw_text="note",
            author_name=note_author,
            likes=1200,
            published_days_ago=2,
        )
        record_note_observation(
            conn,
            product_id=product_id,
            source="author_profile_from_note",
            screenshot_path=None,
            probe_dir=str(profile_path) if profile_path is not None else None,
            page_kind="account_profile",
            raw_text="profile",
            author_name=profile_author,
            follower_count=188,
        )


def _existing_evidence_dirs(settings):
    note_path = settings.data_dir / "probes" / "note"
    profile_path = settings.data_dir / "probes" / "profile"
    note_path.mkdir(parents=True)
    profile_path.mkdir(parents=True)
    return note_path, profile_path


def test_promotion_requires_existing_in_root_matching_author_evidence(tmp_path):
    settings = Settings.load(tmp_path)
    product_id = _seed_candidate(settings)
    note_path, profile_path = _existing_evidence_dirs(settings)
    _record_chain(settings, product_id, note_path=note_path, profile_path=profile_path)

    with connect(settings.db_path) as conn:
        result = promote_candidate_from_note_observations(conn, product_id)
        latest = conn.execute(
            "SELECT evidence_grade FROM candidate_assessments "
            "WHERE product_id=? ORDER BY id DESC LIMIT 1",
            (product_id,),
        ).fetchone()

    assert result["verified"] is True
    assert latest["evidence_grade"] == "A"


@pytest.mark.parametrize(
    ("note_author", "note_path_factory", "expected_reason"),
    [
        (None, "valid", "note/profile author mismatch"),
        ("Author A", "missing", "note/profile evidence path invalid"),
        ("Author A", "outside", "note/profile evidence path invalid"),
        ("Author A", "empty", "note/profile evidence path invalid"),
    ],
)
def test_promotion_rejects_incomplete_or_out_of_root_evidence(
    tmp_path, note_author, note_path_factory, expected_reason
):
    settings = Settings.load(tmp_path)
    product_id = _seed_candidate(settings)
    valid_note, profile_path = _existing_evidence_dirs(settings)
    if note_path_factory == "valid":
        note_path = valid_note
    elif note_path_factory == "missing":
        note_path = settings.data_dir / "probes" / "does-not-exist"
    elif note_path_factory == "outside":
        note_path = tmp_path / "outside"
        note_path.mkdir()
    else:
        note_path = None
    _record_chain(
        settings,
        product_id,
        note_author=note_author,
        note_path=note_path,
        profile_path=profile_path,
    )

    with connect(settings.db_path) as conn:
        result = promote_candidate_from_note_observations(conn, product_id)

    assert result == {"verified": False, "skip_reason": expected_reason}


@pytest.mark.parametrize("bad_reasons", ["", "not-json", '{"reason": "trend"}', "null"])
def test_bad_reasons_json_safely_degrades_to_empty_list(tmp_path, bad_reasons):
    settings = Settings.load(tmp_path)
    product_id = _seed_candidate(settings, reasons_json=bad_reasons)
    note_path, profile_path = _existing_evidence_dirs(settings)
    _record_chain(settings, product_id, note_path=note_path, profile_path=profile_path)

    with connect(settings.db_path) as conn:
        result = promote_candidate_from_note_observations(conn, product_id)
        reasons = conn.execute(
            "SELECT reasons_json FROM candidate_assessments "
            "WHERE product_id=? ORDER BY id DESC LIMIT 1",
            (product_id,),
        ).fetchone()["reasons_json"]

    assert result["verified"] is True
    assert json.loads(reasons) == [result["reason"]]


def test_digest_does_not_trust_claim_without_same_strict_evidence(tmp_path):
    settings = Settings.load(tmp_path)
    note_path, profile_path = _existing_evidence_dirs(settings)
    base = dict(
        product_id=1,
        title="Digest candidate",
        low_follower_verified=True,
        note_author_name="Author A",
        profile_author_name="Author A",
        note_likes=1200,
        note_published_days_ago=2,
        profile_follower_count=188,
        note_evidence_path=str(note_path),
        profile_evidence_path=str(profile_path),
    )

    complete = build_daily_digest(
        candidates=[CandidateSnapshot(**base)],
        evidence_root=settings.data_dir,
    )
    missing_author = build_daily_digest(
        candidates=[CandidateSnapshot(**{**base, "note_author_name": None})],
        evidence_root=settings.data_dir,
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    out_of_root = build_daily_digest(
        candidates=[CandidateSnapshot(**{**base, "note_evidence_path": str(outside)})],
        evidence_root=settings.data_dir,
    )

    assert complete.stats["low_follower_complete"] == 1
    assert missing_author.stats["low_follower_complete"] == 0
    assert out_of_root.stats["low_follower_complete"] == 0
