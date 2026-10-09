from types import SimpleNamespace
from urllib.error import HTTPError

import xhs_scout.product_link as product_link
from xhs_scout.product_link import (
    capture_product_share_url,
    extract_product_direct_url,
    extract_share_url,
    is_supported_product_direct_url,
    is_supported_product_url,
    resolve_product_direct_url,
    resolve_product_launch_url,
)


def test_accepts_only_explicit_xiaohongshu_product_formats():
    assert is_supported_product_url("https://xhslink.com/a/AbCd123")
    assert is_supported_product_url("https://xhslink.com/m/5opIwRSMelM")
    assert is_supported_product_url("https://www.xiaohongshu.com/goods/123")
    assert is_supported_product_url(
        "https://xiaohongshu.com/goods-detail/64ff001?xhsshare=CopyLink"
    )


def test_rejects_unknown_or_spoofed_domains():
    assert extract_share_url("https://example.com/goods/123") is None
    assert extract_share_url("https://xhslink.com.evil.test/a/AbCd123") is None
    assert extract_share_url("https://evil.test/xhslink.com/a/AbCd123") is None


def test_rejects_credential_urls_and_non_public_ports():
    assert extract_share_url("https://user:password@xhslink.com/a/AbCd123") is None
    assert extract_share_url("https://xhslink.com:443/a/AbCd123") is None


def test_rejects_official_non_product_links_and_malformed_product_paths():
    rejected = [
        "https://www.xiaohongshu.com/explore/64d4fdb5",
        "https://www.xiaohongshu.com/user/profile/123",
        "https://www.xiaohongshu.com/search_result?keyword=test",
        "https://xhslink.com/a/",
        "https://xhslink.com/not-a-product/AbCd123",
        "https://www.xiaohongshu.com/goods/123/extra",
    ]
    for value in rejected:
        assert extract_share_url(value) is None


def test_daily_direct_target_rejects_expiring_share_links_and_accepts_official_targets():
    assert not is_supported_product_direct_url("https://xhslink.com/m/5opIwRSMelM")
    assert is_supported_product_direct_url(
        "https://www.xiaohongshu.com/goods-detail/64ff001?xhsshare=CopyLink"
    )
    assert is_supported_product_direct_url(
        "xhsdiscover://page/goods/64ff001"
    )
    assert is_supported_product_direct_url(
        "xhsdiscover://goods_detail/64ff001?source=mall_search"
    )
    assert not is_supported_product_direct_url(
        "xhsdiscover://page/user/64ff001"
    )


def test_extracts_current_goods_detail_intent_from_read_only_activity_dump():
    activity_dump = """
    Intent { dat=xhsdiscover://goods_detail/6a64db3ed9bb890015ca9439?ap=3&source=mall_search
      cmp=com.xingin.xhs/com.xingin.commercial.goodsdetail.v2.activity.GoodsDetailActivityV2 }
    """

    assert extract_product_direct_url(activity_dump) == (
        "xhsdiscover://goods_detail/6a64db3ed9bb890015ca9439"
    )


class FakeResponse:
    def __init__(self, *, final_url: str, body: bytes = b""):
        self.final_url = final_url
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self):
        return self.final_url

    def read(self, _limit):
        return self.body


def test_resolve_short_link_keeps_only_official_product_redirect():
    result = resolve_product_direct_url(
        "https://xhslink.com/m/Fresh123",
        opener=lambda _request, timeout: FakeResponse(
            final_url=(
                "https://www.xiaohongshu.com/goods-detail/64ff001"
                "?xhsshare=CopyLink"
            )
        ),
    )

    assert result == {
        "direct_url": (
            "https://www.xiaohongshu.com/goods-detail/64ff001"
            "?xhsshare=CopyLink"
        ),
        "resolution": "public_redirect",
        "skip_reason": None,
    }


def test_resolve_keeps_official_redirect_target_even_if_web_page_returns_404():
    target = (
        "https://www.xiaohongshu.com/goods-detail/67fa3ecf1899f10001df7917"
        "?xsec_source=app_share"
    )

    def open_then_404(_request, timeout):
        raise HTTPError(target, 404, "Not Found", hdrs=None, fp=None)

    result = resolve_product_direct_url(
        "https://xhslink.com/m/7X9KDzX3Dxc",
        opener=open_then_404,
    )

    assert result["direct_url"] == target
    assert result["resolution"] == "public_redirect"
    assert result["skip_reason"] is None


def test_resolve_prefers_canonical_instation_deeplink_over_expiring_web_token():
    target = (
        "https://www.xiaohongshu.com/goods-detail/67fa3ecf1899f10001df7917"
        "?xsec_token=expiring"
        "&instation_link=xhsdiscover%3A%2F%2Fgoods_detail%2F"
        "67fa3ecf1899f10001df7917%3Fsource%3Dmall_search"
    )

    def open_then_404(_request, timeout):
        raise HTTPError(target, 404, "Not Found", hdrs=None, fp=None)

    result = resolve_product_direct_url(
        "https://xhslink.com/m/7X9KDzX3Dxc",
        opener=open_then_404,
    )

    assert result["direct_url"] == (
        "xhsdiscover://goods_detail/67fa3ecf1899f10001df7917"
    )
    assert result["resolution"] == "public_redirect_deeplink"
    assert result["skip_reason"] is None


def test_resolve_short_link_extracts_documented_goods_deeplink_from_public_page():
    result = resolve_product_direct_url(
        "https://xhslink.com/a/Fresh456",
        opener=lambda _request, timeout: FakeResponse(
            final_url="https://xhslink.com/a/Fresh456",
            body=(
                b'<meta content="xhsdiscover:\\/\\/page\\/goods\\/64ff002">'
            ),
        ),
    )

    assert result["direct_url"] == "xhsdiscover://page/goods/64ff002"
    assert result["resolution"] == "public_page"
    assert result["skip_reason"] is None


def test_resolve_short_link_fails_closed_for_non_product_or_non_official_target():
    result = resolve_product_direct_url(
        "https://xhslink.com/m/Fresh789",
        opener=lambda _request, timeout: FakeResponse(
            final_url="https://evil.test/goods-detail/64ff003",
            body=b"https://www.xiaohongshu.com/explore/64ff003",
        ),
    )

    assert result["direct_url"] is None
    assert result["resolution"] == "unresolved"


def test_daily_launch_uses_fresh_official_redirect_only_when_identity_matches():
    target = (
        "https://www.xiaohongshu.com/goods-detail/67fa3ecf1899f10001df7917"
        "?xsec_token=fresh&xsec_source=app_share"
    )
    result = resolve_product_launch_url(
        "https://xhslink.com/m/7X9KDzX3Dxc",
        "xhsdiscover://goods_detail/67fa3ecf1899f10001df7917",
        opener=lambda _request, timeout: FakeResponse(final_url=target),
    )

    assert result["launch_url"] == target
    assert result["resolution"] == "fresh_public_redirect"


def test_daily_launch_fails_closed_when_public_redirect_identity_changes():
    result = resolve_product_launch_url(
        "https://xhslink.com/m/7X9KDzX3Dxc",
        "xhsdiscover://goods_detail/67fa3ecf1899f10001df7917",
        opener=lambda _request, timeout: FakeResponse(
            final_url="https://www.xiaohongshu.com/goods-detail/another-product"
        ),
    )

    assert result["launch_url"] is None
    assert result["resolution"] == "identity_mismatch"


class ClipboardDevice:
    def __init__(self, clipboard_value: str):
        self.clipboard_value = clipboard_value
        self.original_clipboard = clipboard_value
        self.taps = []
        self.dump_count = 0
        self.back_count = 0

    def ui_dump(self):
        self.dump_count += 1
        return "<share-product/>" if self.dump_count == 1 else "<copy-link/>"

    def get_windows_clipboard(self):
        return self.clipboard_value

    def set_windows_clipboard(self, value):
        if value == self.original_clipboard:
            self.clipboard_value = value

    def tap(self, x, y):
        self.taps.append((x, y))

    def back(self):
        self.back_count += 1


class SuccessfulCaptureDevice(ClipboardDevice):
    def __init__(self):
        super().__init__("operator clipboard")
        self.copy_tap_count = 0

    def ui_dump(self):
        self.dump_count += 1
        if self.dump_count == 1:
            return "<share-product/>"
        if self.dump_count == 2:
            return "<copy-link/>"
        return """
        <node text="客服" />
        <node text="购物车" />
        <node text="加入购物车" />
        <node text="领券购买" />
        """

    def tap(self, x, y):
        super().tap(x, y)
        self.copy_tap_count += 1
        if self.copy_tap_count == 2:
            self.clipboard_value = (
                "打开小红书查看商品 https://xhslink.com/m/Fresh123"
            )


class ActivityOnlyCaptureDevice(ClipboardDevice):
    def activity_dump(self):
        return (
            "Intent { dat=xhsdiscover://goods_detail/64ff009"
            "?source=mall_search cmp=com.xingin.xhs/"
            "com.xingin.commercial.goodsdetail.v2.activity.GoodsDetailActivityV2 }"
        )

    def get_windows_clipboard(self):
        raise AssertionError("direct fast path must not read Windows clipboard")

    def set_windows_clipboard(self, _value):
        raise AssertionError("direct fast path must not write Windows clipboard")


def test_capture_rejects_previous_clipboard_url_when_copy_does_not_change_it(
    monkeypatch,
):
    old_url = "https://xhslink.com/a/OldProduct123"
    device = ClipboardDevice(old_url)
    target = SimpleNamespace(x=10, y=20, label="target")
    monkeypatch.setattr(product_link, "find_share_product_button", lambda _xml: target)
    monkeypatch.setattr(product_link, "find_copy_link_button", lambda _xml: target)
    monkeypatch.setattr(product_link.time, "sleep", lambda _seconds: None)

    ticks = iter([0.0, 0.1, 0.2, 0.3])
    monkeypatch.setattr(product_link.time, "monotonic", lambda: next(ticks))

    result = capture_product_share_url(
        device,
        wait_seconds=0,
        clipboard_timeout_seconds=0.25,
    )

    assert result["share_url"] is None
    assert result["skip_reason"] == "clipboard still contains the previous product URL"
    assert device.clipboard_value == old_url
    assert device.back_count == 1


def test_capture_keeps_share_only_fallback_without_verified_direct_identity(monkeypatch):
    device = SuccessfulCaptureDevice()
    target = SimpleNamespace(x=10, y=20, label="target")
    monkeypatch.setattr(product_link, "find_share_product_button", lambda _xml: target)
    monkeypatch.setattr(product_link, "find_copy_link_button", lambda _xml: target)
    monkeypatch.setattr(
        product_link,
        "resolve_product_direct_url",
        lambda _url: {
            "direct_url": None,
            "resolution": None,
            "skip_reason": "share link did not resolve to a verified product identity",
        },
    )
    monkeypatch.setattr(product_link.time, "sleep", lambda _seconds: None)

    result = capture_product_share_url(
        device,
        wait_seconds=0,
        clipboard_timeout_seconds=0.25,
    )

    assert result["share_url"] == "https://xhslink.com/m/Fresh123"
    assert result["direct_url"] is None
    assert result["direct_url_resolution"] is None
    assert result["direct_url_gap"] == (
        "share link did not resolve to a verified product identity"
    )
    assert device.back_count == 0


def test_capture_returns_activity_direct_url_without_ui_or_clipboard_access(monkeypatch):
    device = ActivityOnlyCaptureDevice("operator clipboard")

    result = capture_product_share_url(
        device,
        wait_seconds=0,
        clipboard_timeout_seconds=0.25,
    )

    assert result["share_url"] is None
    assert result["direct_url"] == "xhsdiscover://goods_detail/64ff009"
    assert result["direct_url_resolution"] == "visible_activity_intent"
    assert result["direct_url_gap"] is None
    assert result["skip_reason"] is None
    assert device.dump_count == 0
    assert device.taps == []
    assert device.back_count == 0
    assert device.clipboard_value == "operator clipboard"
