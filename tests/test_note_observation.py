from xhs_scout.note_observation import parse_account_profile_text, parse_note_text


def test_parse_note_text_counts_and_publish_age():
    parsed = parse_note_text(
        """
        树的运营笔记
        粉丝 188
        今天
        用游戏化管理，1个月竟完成这么多副本
        点赞 1200
        收藏 300
        评论 56
        """
    )
    assert parsed["author_name"] == "树的运营笔记"
    assert parsed["follower_count"] == 188
    assert parsed["likes"] == 1200
    assert parsed["collects"] == 300
    assert parsed["comments"] == 56
    assert parsed["published_days_ago"] == 0


def test_parse_note_text_supports_wan_units():
    parsed = parse_note_text("作者A\n1.2万粉丝\n获赞 3.5万\n昨天")
    assert parsed["follower_count"] == 12_000
    assert parsed["likes"] == 35_000
    assert parsed["published_days_ago"] == 1


def test_parse_note_text_skips_status_bar_time_for_author():
    parsed = parse_note_text("8:05\n猫叔英语研究所\n关注\n说点什么..\nW10")
    assert parsed["author_name"] == "猫叔英语研究所"


def test_parse_note_text_embedded_overlay_author_and_counts():
    parsed = parse_note_text(
        """
        8:35
        开箱精选
        小红点点商家
        高中英语读后续写高分句型，建议火速码
        展开
        共6张
        8个月前
        6460
        ?评论
        """
    )
    assert parsed["author_name"] == "小红点点"
    assert parsed["published_days_ago"] == 240
    assert parsed["likes"] == 6460


def test_parse_account_profile_text_counts():
    parsed = parse_account_profile_text(
        """
        8:10
        猫叔英语研究所
        小红书号 123456
        188 粉丝
        获赞与收藏 1.2万
        笔记
        """
    )
    assert parsed["author_name"] == "猫叔英语研究所"
    assert parsed["follower_count"] == 188
    assert parsed["likes"] == 12_000


def test_parse_account_profile_text_vertical_stats():
    parsed = parse_account_profile_text(
        """
        猫叔英语研究所
        32条原创内容
        14
        5600
        6.4万
        关注
        私信
        关注
        粉丝
        获赞与收藏
        """
    )
    assert parsed["follower_count"] == 5600
    assert parsed["likes"] == 64_000


def test_parse_shop_profile_name_around_follower_ignores_status_bar_and_sales():
    parsed = parse_account_profile_text(
        """
        晚上9:43
        24
        大麦美食
        ★★★★☆
        4.4 已售2.7万
        粉丝4439
        238篇笔记
        好评率97.3%
        """
    )

    assert parsed["author_name"] == "大麦美食"
    assert parsed["follower_count"] == 4439
