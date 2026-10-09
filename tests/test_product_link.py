from xhs_scout.product_link import extract_share_url


def test_extract_share_url_from_xiaohongshu_copy_text():
    text = "打开小红书查看商品 https://xhslink.com/a/AbCd123 复制后打开"
    assert extract_share_url(text) == "https://xhslink.com/a/AbCd123"


def test_extract_share_url_strips_chinese_punctuation():
    assert extract_share_url("商品链接：https://www.xiaohongshu.com/goods/123。") == (
        "https://www.xiaohongshu.com/goods/123"
    )
