import pytest

from xhs_scout.ui_automation import find_home_search_entry


@pytest.mark.parametrize(
    ("search_node", "label"),
    [
        ('text="" content-desc="搜索"', "搜索"),
        ('text="" content-desc="搜索商品"', "搜索商品"),
        ('text="查询商品" content-desc=""', "查询商品"),
    ],
)
def test_home_search_entry_accepts_explicit_search_semantics(search_node, label):
    xml = f"""<hierarchy>
      <node text="" content-desc="分享" clickable="true" bounds="[1010,42][1060,92]" />
      <node {search_node} clickable="true" bounds="[900,42][970,92]" />
    </hierarchy>"""

    target = find_home_search_entry(xml)

    assert target is not None
    assert target.label == label
    assert target.reason == "home-search-button"


def test_home_search_entry_accepts_verified_edit_text_query_field():
    xml = """<hierarchy>
      <node class="android.widget.EditText" text="古诗文本" content-desc=""
            clickable="true" focusable="true" bounds="[120,42][920,108]" />
    </hierarchy>"""

    target = find_home_search_entry(xml)

    assert target is not None
    assert target.label == "古诗文本"
    assert target.reason == "home-search-bar"


def test_home_search_entry_accepts_top_right_previous_query_chip():
    xml = """<hierarchy>
      <node class="android.widget.TextView" text="codex的重置" content-desc=""
            clickable="true" focusable="true" bounds="[756,42][1056,87]" />
      <node class="android.widget.TextView" text="发现" content-desc=""
            clickable="true" focusable="true" bounds="[506,45][573,93]" />
    </hierarchy>"""

    target = find_home_search_entry(xml)

    assert target is not None
    assert target.label == "codex的重置"
    assert target.reason == "home-search-bar"


def test_home_search_entry_distinguishes_explicit_long_search_bar():
    xml = """<hierarchy>
      <node class="android.widget.TextView" text="codex 重置" content-desc="搜索"
            clickable="true" focusable="true" bounds="[756,42][1056,87]" />
    </hierarchy>"""

    target = find_home_search_entry(xml)

    assert target is not None
    assert target.label == "codex重置"
    assert target.reason == "home-search-bar"
    assert (target.x, target.y) == (906, 64)


@pytest.mark.parametrize("label", ["扫码", "扫一扫", "直播", "签到", "分享", "发布"])
def test_home_search_entry_rejects_explicitly_unsafe_entries(label):
    xml = f"""<hierarchy>
      <node text="" content-desc="{label}" clickable="true" bounds="[900,42][1060,108]" />
    </hierarchy>"""

    assert find_home_search_entry(xml) is None


def test_home_search_entry_does_not_guess_rightmost_clickable_target():
    xml = """<hierarchy>
      <node text="古诗文本" content-desc="" clickable="true" bounds="[650,42][900,108]" />
      <node text="" content-desc="分享" clickable="true" bounds="[910,42][970,108]" />
      <node text="" content-desc="扫码" clickable="true" bounds="[980,42][1060,108]" />
    </hierarchy>"""

    assert find_home_search_entry(xml) is None


def test_home_search_entry_rejects_dangerous_search_combination():
    xml = """<hierarchy>
      <node text="" content-desc="搜索直播" clickable="true" bounds="[900,42][1060,108]" />
    </hierarchy>"""

    assert find_home_search_entry(xml) is None
