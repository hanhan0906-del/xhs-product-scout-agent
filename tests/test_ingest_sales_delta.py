from xhs_scout.ingest import calculate_daily_sales_delta


def test_daily_sales_delta_accepts_consecutive_shanghai_midnight_samples():
    assert calculate_daily_sales_delta(
        previous_exact=1100,
        previous_at="2026-07-30T00:00:00+08:00",
        current_exact=1200,
        current_at="2026-07-31T00:00:00+08:00",
    ) == 100


def test_daily_sales_delta_accepts_up_to_fifteen_minutes_of_scheduler_delay():
    assert calculate_daily_sales_delta(
        previous_exact=1100,
        previous_at="2026-07-30T00:07:30+08:00",
        current_exact=1200,
        current_at="2026-07-31T00:15:00+08:00",
    ) == 100


def test_daily_sales_delta_converts_aware_timestamps_to_shanghai_time():
    assert calculate_daily_sales_delta(
        previous_exact=1100,
        previous_at="2026-07-29T16:05:00Z",
        current_exact=1200,
        current_at="2026-07-30T16:10:00+00:00",
    ) == 100


def test_daily_sales_delta_rejects_fuzzy_or_non_integer_counts():
    assert calculate_daily_sales_delta(
        previous_exact=None,
        previous_at="2026-07-30T00:00:00+08:00",
        current_exact=1200,
        current_at="2026-07-31T00:00:00+08:00",
    ) is None

    assert calculate_daily_sales_delta(
        previous_exact=1100.0,
        previous_at="2026-07-30T00:00:00+08:00",
        current_exact=1200,
        current_at="2026-07-31T00:00:00+08:00",
    ) is None

    assert calculate_daily_sales_delta(
        previous_exact=1100,
        previous_at="2026-07-30T00:00:00+08:00",
        current_exact=True,
        current_at="2026-07-31T00:00:00+08:00",
    ) is None


def test_daily_sales_delta_rejects_counter_decrease():
    assert calculate_daily_sales_delta(
        previous_exact=1200,
        previous_at="2026-07-30T00:00:00+08:00",
        current_exact=1100,
        current_at="2026-07-31T00:00:00+08:00",
    ) is None


def test_daily_sales_delta_rejects_non_midnight_twenty_four_hour_gap():
    assert calculate_daily_sales_delta(
        previous_exact=1100,
        previous_at="2026-07-30T12:00:00+08:00",
        current_exact=1200,
        current_at="2026-07-31T12:00:00+08:00",
    ) is None


def test_daily_sales_delta_rejects_samples_outside_midnight_delay_window():
    assert calculate_daily_sales_delta(
        previous_exact=1100,
        previous_at="2026-07-30T00:00:00+08:00",
        current_exact=1200,
        current_at="2026-07-31T00:15:00.000001+08:00",
    ) is None


def test_daily_sales_delta_rejects_non_consecutive_shanghai_dates():
    assert calculate_daily_sales_delta(
        previous_exact=1100,
        previous_at="2026-07-30T00:00:00+08:00",
        current_exact=1200,
        current_at="2026-08-01T00:00:00+08:00",
    ) is None

    assert calculate_daily_sales_delta(
        previous_exact=1100,
        previous_at="2026-07-30T00:00:00+08:00",
        current_exact=1200,
        current_at="2026-07-30T00:10:00+08:00",
    ) is None


def test_daily_sales_delta_rejects_invalid_or_unreliable_timestamps():
    invalid_pairs = [
        ("not-a-time", "2026-07-31T00:00:00+08:00"),
        ("2026-07-30T00:00:00", "2026-07-31T00:00:00+08:00"),
        ("2026-07-30T00:00:00+08:00", "2026-07-31T00:00:00"),
        ("2026-07-30T00:00:00+08:00", "not-a-time"),
    ]

    for previous_at, current_at in invalid_pairs:
        assert calculate_daily_sales_delta(
            previous_exact=1100,
            previous_at=previous_at,
            current_exact=1200,
            current_at=current_at,
        ) is None
