import pytest
from fastapi import HTTPException

from xhs_scout.config import Settings
from xhs_scout.db import (
    connect,
    dashboard_stats,
    followed_product_sales_snapshot,
    utcnow,
)
from xhs_scout.web import ProductSalesFollowRequest, create_app


def _insert_product(
    conn,
    *,
    fingerprint: str,
    share_url: str | None,
    direct_url: str | None,
) -> int:
    now = utcnow()
    cursor = conn.execute(
        """
        INSERT INTO products(
            fingerprint, title, shop_name, share_url, direct_url,
            first_seen_at, last_seen_at
        ) VALUES (?, ?, '测试店铺', ?, ?, ?, ?)
        """,
        (fingerprint, f"商品-{fingerprint}", share_url, direct_url, now, now),
    )
    product_id = int(cursor.lastrowid)
    conn.execute(
        """
        INSERT INTO observations(
            product_id, observed_at, source, cumulative_sales_display,
            raw_signals_json
        ) VALUES (?, ?, 'test', '1100', '{}')
        """,
        (product_id, now),
    )
    return product_id


def _follow_route(settings: Settings):
    return {
        route.path: route.endpoint
        for route in create_app(settings).routes
        if hasattr(route, "endpoint")
    }["/api/products/{product_id}/sales-follow"]


def test_follow_toggle_is_idempotent_and_visible_in_dashboard(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        product_id = _insert_product(
            conn,
            fingerprint="followed",
            share_url=None,
            direct_url="xhsdiscover://page/goods/followed",
        )

    route = _follow_route(settings)
    first = route(product_id, ProductSalesFollowRequest(enabled=True))
    second = route(product_id, ProductSalesFollowRequest(enabled=True))

    assert first["sales_followed"] is True
    assert second["sales_followed"] is True
    assert second["followed_product_count"] == 1

    with connect(settings.db_path) as conn:
        snapshot = followed_product_sales_snapshot(conn)
        assert snapshot[0]["product_id"] == product_id
        assert snapshot[0]["share_url"] is None
        assert (
            snapshot[0]["verified_direct_url"]
            == "xhsdiscover://page/goods/followed"
        )
        recent = dashboard_stats(conn)["recent"]
        assert recent[0]["sales_followed"] == 1
        assert recent[0]["direct_url"] == "xhsdiscover://page/goods/followed"

    removed = route(product_id, ProductSalesFollowRequest(enabled=False))
    assert removed["sales_followed"] is False
    assert removed["followed_product_count"] == 0

    with connect(settings.db_path) as conn:
        assert followed_product_sales_snapshot(conn) == []
        assert conn.execute(
            "SELECT COUNT(*) FROM observations WHERE product_id=?",
            (product_id,),
        ).fetchone()[0] == 1


def test_follow_requires_existing_product_with_saved_link(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        product_id = _insert_product(
            conn,
            fingerprint="missing-link",
            share_url=None,
            direct_url=None,
        )

    route = _follow_route(settings)
    with pytest.raises(HTTPException) as missing_link:
        route(product_id, ProductSalesFollowRequest(enabled=True))
    assert missing_link.value.status_code == 409

    with pytest.raises(HTTPException) as missing_product:
        route(9999, ProductSalesFollowRequest(enabled=True))
    assert missing_product.value.status_code == 404


def test_follow_rejects_unresolved_share_link(tmp_path):
    settings = Settings.load(tmp_path)
    with connect(settings.db_path) as conn:
        product_id = _insert_product(
            conn,
            fingerprint="unresolved-link",
            share_url="https://xhslink.com/m/unresolved",
            direct_url=None,
        )

    route = _follow_route(settings)
    with pytest.raises(HTTPException) as unresolved:
        route(product_id, ProductSalesFollowRequest(enabled=True))
    assert unresolved.value.status_code == 409
    assert "直达地址尚未验证" in unresolved.value.detail

    with connect(settings.db_path) as conn:
        unsafe_product_id = _insert_product(
            conn,
            fingerprint="unsafe-direct-link",
            share_url=None,
            direct_url="javascript:alert(1)",
        )

    with pytest.raises(HTTPException) as unsafe:
        route(unsafe_product_id, ProductSalesFollowRequest(enabled=True))
    assert unsafe.value.status_code == 409
    assert "直达地址尚未验证" in unsafe.value.detail
