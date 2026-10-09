from pathlib import Path

from xhs_scout.ui_automation import (
    Bounds,
    find_history_keyword,
    find_home_search_entry,
    find_clear_query_button,
    find_copy_link_button,
    find_product_cards,
    find_product_shop_entry,
    find_shop_header_name,
    find_product_tab,
    find_note_author_entry,
    find_related_note_cards,
    find_search_product_button,
    find_share_product_button,
    find_top_query_field,
    find_top_query_text,
    parse_bounds,
)


def test_parse_bounds_and_center():
    bounds = parse_bounds("[846,48][888,90]")
    assert bounds is not None
    assert bounds.center == (867, 69)


def test_find_search_product_button_by_content_desc():
    xml = """<hierarchy>
      <node text="" content-desc="搜索商品" clickable="true" bounds="[846,48][888,90]" />
      <node text="" content-desc="带货赚佣金" clickable="true" bounds="[904,48][946,90]" />
    </hierarchy>"""
    target = find_search_product_button(xml)
    assert target is not None
    assert (target.x, target.y) == (867, 69)


def test_find_share_and_copy_link_buttons():
    detail_xml = """<hierarchy>
      <node text="" content-desc="分享商品" clickable="true" bounds="[1020,48][1062,90]" />
    </hierarchy>"""
    share_xml = """<hierarchy>
      <node text="复制链接" content-desc="" clickable="true" bounds="[840,1460][1030,1560]" />
    </hierarchy>"""
    share = find_share_product_button(detail_xml)
    copy = find_copy_link_button(share_xml)
    assert share is not None
    assert copy is not None
    assert share.reason == "content-desc=分享商品"
    assert copy.reason == "text=复制链接"


def test_find_product_shop_entry_uses_bottom_left_clickable_ancestor():
    xml = """<hierarchy>
      <node bounds="[0,0][1080,2218]">
        <node clickable="true" bounds="[22,2142][143,2218]">
          <node text="店铺" clickable="false" bounds="[0,0][0,0]" />
        </node>
        <node clickable="true" bounds="[143,2142][264,2218]">
          <node text="客服" clickable="false" bounds="[0,0][0,0]" />
        </node>
      </node>
    </hierarchy>"""
    target = find_product_shop_entry(xml)
    assert target is not None
    assert (target.x, target.y) == (82, 2180)
    assert target.reason == "text=店铺 clickable-ancestor"


def test_find_shop_header_name_uses_real_product58_layout():
    xml_path = (
        Path(__file__).resolve().parents[1]
        / "data/probes/monitor-26845cb66dbe-seller-after-138/window.xml"
    )

    assert find_shop_header_name(xml_path.read_text(encoding="utf-8")) == "爱做PPT的小熊猫"


def test_find_shop_header_name_rejects_metrics_and_missing_name():
    xml = """<hierarchy bounds="[0,0][1080,2218]">
      <node class="android.widget.TextView" text="★★★★★4.8" bounds="[275,268][560,340]" />
      <node class="android.widget.TextView" text="已售2.3万" bounds="[583,346][725,395]" />
      <node class="android.widget.TextView" text="粉丝2637" bounds="[275,407][430,462]" />
    </hierarchy>"""

    assert find_shop_header_name(xml) is None


def test_find_shop_header_name_fails_closed_when_header_has_multiple_names():
    xml = """<hierarchy bounds="[0,0][1080,2218]">
      <node class="android.widget.TextView" text="店铺甲" bounds="[275,268][430,340]" />
      <node class="android.widget.TextView" text="店铺乙" bounds="[450,268][605,340]" />
    </hierarchy>"""

    assert find_shop_header_name(xml) is None


def test_find_history_keyword_and_product_tab():
    xml = """<hierarchy>
      <node text="虚拟资料" content-desc="" clickable="true" bounds="[24,186][148,234]" />
      <node text="商品" content-desc="" clickable="true" bounds="[198,114][282,180]" />
    </hierarchy>"""
    history = find_history_keyword(xml, "虚拟资料")
    tab = find_product_tab(xml)
    assert history is not None
    assert tab is not None
    assert (history.x, history.y) == (86, 210)
    assert (tab.x, tab.y) == (240, 147)


def test_product_cards_ignore_transaction_buttons():
    xml = """<hierarchy>
      <node text="" content-desc="" clickable="true" bounds="[12,250][354,920]">
        <node text="【1年学习】商学提升计划" content-desc="" bounds="[24,700][330,740]" />
        <node text="¥149 已售1202" content-desc="" bounds="[24,780][330,820]" />
      </node>
      <node text="加入购物车" content-desc="" clickable="true" bounds="[350,1836][700,1920]" />
    </hierarchy>"""
    cards = find_product_cards(xml)
    assert len(cards) == 1
    assert cards[0].x == 183


def test_product_cards_fail_closed_for_empty_or_malformed_ui_tree():
    assert find_product_cards("") == []
    assert find_product_cards("<hierarchy>") == []


def test_product_cards_skip_live_result_and_keep_normal_product():
    xml = """<hierarchy>
      <node text="" content-desc="" clickable="true" bounds="[7,252][357,808]">
        <node text="直播中" content-desc="" bounds="[14,260][90,292]" />
        <node text="古诗文会员" content-desc="" bounds="[24,700][330,740]" />
        <node text="¥398 已售7" content-desc="" bounds="[24,780][330,802]" />
      </node>
      <node text="" content-desc="" clickable="true" bounds="[365,252][715,808]">
        <node text="古诗文学习资料电子版" content-desc="" bounds="[382,700][690,740]" />
        <node text="¥29.9 已售1200" content-desc="" bounds="[382,780][690,802]" />
      </node>
    </hierarchy>"""
    cards = find_product_cards(xml, limit=1)
    assert len(cards) == 1
    assert cards[0].bounds.x1 == 365
    assert "直播中" not in cards[0].label


def test_product_cards_accept_first_row_reported_behind_fixed_header():
    xml = """<hierarchy>
      <node text="" content-desc="" clickable="true" bounds="[0,78][1080,342]">
        <node text="开学" content-desc="" bounds="[166,89][786,210]" />
        <node text="商品" content-desc="" bounds="[366,256][454,307]" />
      </node>
      <node text="" content-desc="" clickable="true" bounds="[13,78][534,852]">
        <node text="直观的一年级新生开学第一课常规训练ppt课件" content-desc="" bounds="[41,500][506,560]" />
        <node text="¥9.9 已售3735" content-desc="" bounds="[41,650][506,710]" />
      </node>
    </hierarchy>"""

    cards = find_product_cards(xml)

    assert len(cards) == 1
    assert cards[0].bounds == Bounds(13, 78, 534, 852)
    assert "已售3735" in cards[0].label


def test_find_home_search_entry_uses_top_right_visible_query():
    xml = """<hierarchy>
      <node text="" content-desc="发现" clickable="true" bounds="[506,45][573,93]" />
      <node text="古诗文本" content-desc="搜索" clickable="true" bounds="[756,42][1056,87]" />
      <node text="" content-desc="发布" clickable="true" bounds="[432,1852][648,1920]" />
    </hierarchy>"""
    target = find_home_search_entry(xml)
    assert target is not None
    assert target.label == "古诗文本"
    assert target.reason == "home-search-bar"
    assert (target.x, target.y) == (906, 64)


def test_related_note_cards_ignore_bottom_transaction_area():
    xml = """<hierarchy>
      <node text="" content-desc="" clickable="true" bounds="[24,1700][1056,1788]">
        <node text="树的运营笔记" content-desc="" bounds="[54,1706][162,1727]" />
        <node text="用游戏化管理，1个月竟完成这么多副本 我最近彻底戒掉了那种打开App就焦虑的待办清单" content-desc="" bounds="[24,1733][1056,1756]" />
      </node>
      <node text="" content-desc="" clickable="true" bounds="[0,1528][1080,1616]">
        <node text="店铺口碑6000+" content-desc="" bounds="[24,1530][180,1552]" />
        <node text="本店相关笔记和商品评价" content-desc="" bounds="[24,1570][260,1592]" />
      </node>
      <node text="加入购物车" content-desc="" clickable="true" bounds="[228,1848][644,1908]" />
      <node text="" content-desc="商品未加入心愿单" clickable="true" bounds="[962,48][1004,90]" />
    </hierarchy>"""
    cards = find_related_note_cards(xml)
    assert len(cards) == 1
    assert cards[0].reason == "related-note-card"
    assert cards[0].y < 1836


def test_related_note_cards_accept_author_only_visual_cards_under_note_section():
    xml = """<hierarchy>
      <node text="开箱精选" content-desc="" clickable="true" bounds="[0,1343][1080,1418]" />
      <node text="" content-desc="" clickable="false" bounds="[0,1418][1080,1836]">
        <node text="" content-desc="" clickable="true" bounds="[24,1418][362,1836]">
          <node text="猫叔英语研究所" content-desc="" bounds="[42,1780][220,1810]" />
        </node>
        <node text="" content-desc="" clickable="true" bounds="[370,1418][709,1836]">
          <node text="猫叔英语研究所" content-desc="" bounds="[388,1780][566,1810]" />
        </node>
        <node text="" content-desc="" clickable="true" bounds="[717,1418][1056,1836]">
          <node text="猫叔英语研究所" content-desc="" bounds="[735,1780][913,1810]" />
        </node>
      </node>
      <node text="加入购物车" content-desc="" clickable="true" bounds="[228,1848][644,1908]" />
    </hierarchy>"""
    cards = find_related_note_cards(xml)
    assert len(cards) == 3
    assert cards[0].bounds.x1 == 24
    assert cards[0].bounds.width == 338


def test_find_note_author_entry_prefers_author_text_not_follow_button():
    xml = """<hierarchy>
      <node text="" content-desc="" clickable="true" bounds="[23,51][77,105]" />
      <node text="" content-desc="" clickable="true" bounds="[77,36][1080,120]">
        <node text="猫叔英语研究所" content-desc="" clickable="false" bounds="[167,64][328,91]" />
        <node text="关注" content-desc="" clickable="false" bounds="[909,57][1003,99]" />
      </node>
    </hierarchy>"""
    target = find_note_author_entry(xml)
    assert target is not None
    assert target.label == "猫叔英语研究所"
    assert target.x == 247


def test_find_note_author_entry_in_embedded_note_overlay():
    xml = """<hierarchy>
      <node text="开箱精选" content-desc="" clickable="false" bounds="[492,51][588,87]" />
      <node text="小红点点" content-desc="" clickable="false" bounds="[90,129][174,159]" />
      <node text="商家" content-desc="" clickable="false" bounds="[183,133][221,154]" />
      <node text="展开" content-desc="" clickable="true" bounds="[90,255][138,295]" />
    </hierarchy>"""
    target = find_note_author_entry(xml)
    assert target is not None
    assert target.label == "小红点点"
    assert target.x == 132


def test_find_top_query_field_and_clear_button():
    xml = """<hierarchy>
      <node text="虚拟资料" content-desc="" clickable="true" focusable="true" bounds="[90,42][919,108]" />
      <node text="" content-desc="全部删除" clickable="true" bounds="[928,62][955,89]" />
    </hierarchy>"""
    query = find_top_query_field(xml)
    clear = find_clear_query_button(xml)
    assert query is not None
    assert clear is not None
    assert (query.x, query.y) == (504, 75)
    assert (clear.x, clear.y) == (941, 75)
    assert find_top_query_text(xml) == "虚拟资料"
