from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import unicodedata
from dataclasses import dataclass


BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

DANGER_TEXT = (
    "\u52a0\u5165\u8d2d\u7269\u8f66",
    "\u7acb\u5373\u8d2d\u4e70",
    "\u8d2d\u7269\u8f66",
    "\u5ba2\u670d",
    "\u9009\u54c1\u52a0\u6a71\u7a97",
    "\u5e26\u8d27\u8d5a\u4f63\u91d1",
    "\u63d0\u9192\u5546\u5bb6\u5f00\u901a",
    "\u6536\u85cf",
    "\u5fc3\u613f\u5355",
)

NONSTANDARD_PRODUCT_MARKERS = (
    "\u76f4\u64ad\u4e2d",
    "\u6b63\u5728\u76f4\u64ad",
    "\u8fdb\u5165\u76f4\u64ad\u95f4",
)

HOME_SEARCH_SEMANTIC_MARKERS = ("\u641c\u7d22", "\u67e5\u8be2")

HOME_SEARCH_REJECT_MARKERS = (
    "\u626b\u7801",
    "\u626b\u4e00\u626b",
    "\u76f4\u64ad",
    "\u7b7e\u5230",
    "\u5206\u4eab",
    "\u53d1\u5e03",
)

PRODUCT_DETAIL_CONTROL_LABELS = (
    "\u5ba2\u670d",
    "\u8d2d\u7269\u8f66",
    "\u52a0\u5165\u8d2d\u7269\u8f66",
)


def product_detail_controls_present(xml_text: str) -> bool:
    """Identify product detail by stable bottom controls, not purchase copy."""
    return all(f'text="{label}"' in xml_text for label in PRODUCT_DETAIL_CONTROL_LABELS)


@dataclass(frozen=True)
class Bounds:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def center(self) -> tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)


@dataclass(frozen=True)
class UiTarget:
    x: int
    y: int
    bounds: Bounds
    label: str
    reason: str


def parse_bounds(raw: str | None) -> Bounds | None:
    if not raw:
        return None
    match = BOUNDS_RE.fullmatch(raw)
    if not match:
        return None
    x1, y1, x2, y2 = (int(group) for group in match.groups())
    if x2 <= x1 or y2 <= y1:
        return None
    return Bounds(x1, y1, x2, y2)


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "").replace("\u200b", ""))


def parse_ui(xml_text: str) -> ET.Element:
    return ET.fromstring(xml_text)


def node_label(node: ET.Element) -> str:
    return normalize_text(node.attrib.get("text")) or normalize_text(node.attrib.get("content-desc"))


def node_blob(node: ET.Element) -> str:
    chunks: list[str] = []
    for item in node.iter():
        chunks.append(normalize_text(item.attrib.get("text")))
        chunks.append(normalize_text(item.attrib.get("content-desc")))
    return "".join(chunk for chunk in chunks if chunk)


def is_dangerous_node(node: ET.Element) -> bool:
    blob = node_blob(node)
    return any(marker in blob for marker in DANGER_TEXT)


def _target_from_node(node: ET.Element, reason: str) -> UiTarget | None:
    bounds = parse_bounds(node.attrib.get("bounds"))
    if not bounds:
        return None
    x, y = bounds.center
    return UiTarget(x=x, y=y, bounds=bounds, label=node_label(node), reason=reason)


def find_exact_text(xml_text: str, text: str) -> UiTarget | None:
    root = parse_ui(xml_text)
    target = normalize_text(text)
    for node in root.iter():
        if normalize_text(node.attrib.get("text")) == target and not is_dangerous_node(node):
            found = _target_from_node(node, f"text={text}")
            if found:
                return found
    return None


def find_product_shop_entry(xml_text: str) -> UiTarget | None:
    """Find the bottom-left shop button, including zero-sized text children."""

    direct = find_exact_text(xml_text, "店铺")
    if direct:
        return direct

    root = parse_ui(xml_text)
    root_bounds = max(
        (
            bounds
            for item in root.iter()
            if (bounds := parse_bounds(item.attrib.get("bounds"))) is not None
        ),
        key=lambda bounds: bounds.area,
        default=None,
    )
    if not root_bounds:
        return None
    parents = {child: parent for parent in root.iter() for child in parent}
    for node in root.iter():
        if normalize_text(node.attrib.get("text")) != "店铺":
            continue
        candidate = parents.get(node)
        while candidate is not None:
            bounds = parse_bounds(candidate.attrib.get("bounds"))
            if candidate.attrib.get("clickable") == "true" and bounds:
                in_bottom_band = bounds.y1 >= root_bounds.y1 + int(root_bounds.height * 0.85)
                in_left_band = bounds.x2 <= root_bounds.x1 + int(root_bounds.width * 0.25)
                if in_bottom_band and in_left_band:
                    x, y = bounds.center
                    return UiTarget(
                        x=x,
                        y=y,
                        bounds=bounds,
                        label="店铺",
                        reason="text=店铺 clickable-ancestor",
                    )
                break
            candidate = parents.get(candidate)
    return None


SHOP_HEADER_REJECT_MARKERS = (
    "粉丝",
    "已售",
    "评分",
    "好评率",
    "客服",
    "退款",
    "优惠券",
    "综合",
    "销量",
    "新品",
    "价格",
    "首页",
    "分类",
    "上新",
)


def _clean_shop_header_name(value: str) -> str:
    cleaned = re.sub(r"\s+", "", value or "")
    while cleaned and (
        unicodedata.category(cleaned[-1]).startswith("S")
        or cleaned[-1] in "·•|｜>》）)]}"
    ):
        cleaned = cleaned[:-1]
    return cleaned.strip()


def find_shop_header_name(xml_text: str) -> str | None:
    """Read a shop name only from the dedicated top header layout.

    Shop rating, sales and follower metrics sit directly below the name.  They
    are deliberately rejected rather than treated as fallback text.
    """

    try:
        root = parse_ui(xml_text)
    except ET.ParseError:
        return None
    root_bounds = max(
        (
            bounds
            for item in root.iter()
            if (bounds := parse_bounds(item.attrib.get("bounds"))) is not None
        ),
        key=lambda bounds: bounds.area,
        default=None,
    )
    if root_bounds is None:
        return None

    header_top = root_bounds.y1 + int(root_bounds.height * 0.10)
    header_bottom = root_bounds.y1 + int(root_bounds.height * 0.19)
    header_left = root_bounds.x1 + int(root_bounds.width * 0.18)
    candidates: list[tuple[int, int, str]] = []
    for node in root.iter():
        if not node.attrib.get("class", "").endswith("TextView"):
            continue
        bounds = parse_bounds(node.attrib.get("bounds"))
        if bounds is None:
            continue
        if bounds.x1 < header_left or bounds.y1 < header_top or bounds.y2 > header_bottom:
            continue
        candidate = _clean_shop_header_name(
            node.attrib.get("text") or node.attrib.get("content-desc") or ""
        )
        if not (2 <= len(candidate) <= 40):
            continue
        if re.fullmatch(r"[★☆⭐\s\d.,%+-]+", candidate):
            continue
        if re.fullmatch(r"(?:上午|下午|晚上|凌晨|中午)?\d{1,2}:\d{2}", candidate):
            continue
        if any(marker in candidate for marker in SHOP_HEADER_REJECT_MARKERS):
            continue
        candidates.append((bounds.y1, bounds.x1, candidate))

    unique = {candidate for _, _, candidate in candidates}
    if len(unique) != 1:
        return None
    return candidates[0][2]


def find_exact_content_desc(xml_text: str, content_desc: str) -> UiTarget | None:
    root = parse_ui(xml_text)
    target = normalize_text(content_desc)
    for node in root.iter():
        if normalize_text(node.attrib.get("content-desc")) == target and not is_dangerous_node(node):
            found = _target_from_node(node, f"content-desc={content_desc}")
            if found:
                return found
    return None


def find_search_product_button(xml_text: str) -> UiTarget | None:
    return find_exact_content_desc(xml_text, "\u641c\u7d22\u5546\u54c1")


def find_share_product_button(xml_text: str) -> UiTarget | None:
    return find_exact_content_desc(xml_text, "\u5206\u4eab\u5546\u54c1")


def find_copy_link_button(xml_text: str) -> UiTarget | None:
    return find_exact_text(xml_text, "\u590d\u5236\u94fe\u63a5") or find_exact_content_desc(
        xml_text, "\u590d\u5236\u94fe\u63a5"
    )


def find_home_search_entry(xml_text: str) -> UiTarget | None:
    root = parse_ui(xml_text)
    candidates: list[tuple[int, UiTarget]] = []
    for node in root.iter():
        if node.attrib.get("clickable") != "true" or is_dangerous_node(node):
            continue
        bounds = parse_bounds(node.attrib.get("bounds"))
        if not bounds or bounds.y1 < 0 or bounds.y2 > 180:
            continue
        blob = node_blob(node)
        if any(marker in blob for marker in HOME_SEARCH_REJECT_MARKERS):
            continue
        direct_semantics = "".join(
            (
                normalize_text(node.attrib.get("text")),
                normalize_text(node.attrib.get("content-desc")),
            )
        )
        class_name = node.attrib.get("class", "")
        has_search_semantics = any(
            marker in direct_semantics for marker in HOME_SEARCH_SEMANTIC_MARKERS
        )
        is_standalone_search_button = has_search_semantics and bounds.width <= 140
        is_explicit_search_bar = has_search_semantics and bounds.width >= 160
        is_verified_query_field = (
            class_name.rsplit(".", 1)[-1] == "EditText"
            and bounds.width >= 120
            and node.attrib.get("focusable") == "true"
        )
        is_verified_home_search_bar = (
            class_name.rsplit(".", 1)[-1] == "TextView"
            and bounds.x1 >= 700
            and bounds.width >= 240
            and bounds.height <= 72
            and node.attrib.get("focusable") == "true"
            and bool(normalize_text(node.attrib.get("text")))
        )
        if (
            not is_standalone_search_button
            and not is_explicit_search_bar
            and not is_verified_query_field
            and not is_verified_home_search_bar
        ):
            continue
        reason = (
            "home-search-button"
            if is_standalone_search_button
            else "home-search-bar"
        )
        target = _target_from_node(node, reason)
        if target:
            candidates.append(
                (
                    0
                    if is_standalone_search_button
                    else 1
                    if is_explicit_search_bar or is_verified_query_field
                    else 2,
                    target,
                )
            )
    candidates.sort(key=lambda item: (item[0], item[1].bounds.y1, item[1].bounds.x1))
    return candidates[0][1] if candidates else None


def find_search_box(xml_text: str) -> UiTarget | None:
    root = parse_ui(xml_text)
    candidates: list[UiTarget] = []
    for node in root.iter():
        label = node_label(node)
        bounds = parse_bounds(node.attrib.get("bounds"))
        if not bounds or is_dangerous_node(node):
            continue
        class_name = node.attrib.get("class", "")
        if "EditText" in class_name or "\u641c\u7d22" in label:
            target = _target_from_node(node, "search-box")
            if target:
                candidates.append(target)
    candidates.sort(key=lambda item: (item.bounds.y1, item.bounds.x1))
    return candidates[0] if candidates else None


def find_top_query_field(xml_text: str) -> UiTarget | None:
    root = parse_ui(xml_text)
    candidates: list[UiTarget] = []
    for node in root.iter():
        bounds = parse_bounds(node.attrib.get("bounds"))
        if not bounds or is_dangerous_node(node):
            continue
        if bounds.y1 > 130 or bounds.width < 160:
            continue
        if node.attrib.get("clickable") == "true" or node.attrib.get("focusable") == "true":
            target = _target_from_node(node, "top-query-field")
            if target:
                candidates.append(target)
    candidates.sort(key=lambda item: (item.bounds.y1, -item.bounds.width))
    return candidates[0] if candidates else None


def find_top_query_text(xml_text: str) -> str | None:
    input_value = find_search_input_query_text(xml_text)
    if input_value:
        return input_value

    # Results pages expose the submitted query as a clickable TextView, while
    # broad focusable containers (for example the ViewPager) can appear above
    # it in the accessibility tree.  Read only a non-empty top text widget so
    # an empty full-page container cannot mask the exact submitted query.
    root = parse_ui(xml_text)
    candidates: list[tuple[int, int, str]] = []
    for node in root.iter():
        node_class = node.attrib.get("class", "")
        if not (node_class.endswith("TextView") or node_class.endswith("EditText")):
            continue
        bounds = parse_bounds(node.attrib.get("bounds"))
        if not bounds or bounds.y1 > 220 or bounds.width < 160:
            continue
        value = normalize_text(node.attrib.get("text"))
        for prefix in ("搜索,", "搜索，"):
            if value.startswith(prefix):
                value = value[len(prefix) :].strip()
                break
        if not value or value in {"搜索", "搜索商品"}:
            continue
        candidates.append((bounds.y1, bounds.x1, value))
    candidates.sort(key=lambda item: (item[0], item[1]))
    if candidates:
        return candidates[0][2]

    # Preserve the legacy generic-node contract used by older UI fixtures and
    # BlueStacks layouts, but accept it only when the selected node has text.
    target = find_top_query_field(xml_text)
    if not target:
        return None
    label = normalize_text(target.label)
    return label if label and label not in {"搜索", "搜索商品"} else None


def find_search_input_query_text(xml_text: str) -> str | None:
    """Read the exact query value from the focused search EditText.

    Xiaomi accessibility exposes this field as ``搜索, <query>`` rather than
    only the entered value.  Strip only that known semantic prefix; do not use
    fuzzy containment or OCR body text as input confirmation.
    """

    root = parse_ui(xml_text)
    candidates: list[tuple[int, str]] = []
    for node in root.iter():
        if not node.attrib.get("class", "").endswith("EditText"):
            continue
        bounds = parse_bounds(node.attrib.get("bounds"))
        if not bounds or bounds.y1 > 220:
            continue
        value = normalize_text(node.attrib.get("text"))
        for prefix in ("搜索,", "搜索，"):
            if value.startswith(prefix):
                value = value[len(prefix) :].strip()
                break
        if not value or value in {"搜索", "搜索商品"}:
            continue
        candidates.append((bounds.y1, value))
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1] if candidates else None


def find_clear_query_button(xml_text: str) -> UiTarget | None:
    return find_exact_content_desc(xml_text, "\u5168\u90e8\u5220\u9664")


def find_history_keyword(xml_text: str, keyword: str) -> UiTarget | None:
    return find_exact_text(xml_text, keyword)


def find_product_tab(xml_text: str) -> UiTarget | None:
    return find_exact_text(xml_text, "\u5546\u54c1")


def find_product_cards(xml_text: str, *, limit: int = 3) -> list[UiTarget]:
    # uiautomator can transiently return an empty/truncated dump even when the
    # screenshot and OCR succeeded.  Card discovery is a selector, so malformed
    # input must fail closed as no cards instead of leaking ElementTree's
    # ParseError through the HTTP endpoint.  The monitor owns bounded re-grab
    # and infrastructure-attempt refund semantics.
    try:
        root = parse_ui(xml_text)
    except (ET.ParseError, TypeError):
        return []
    cards: list[UiTarget] = []
    for node in root.iter():
        if node.attrib.get("clickable") != "true":
            continue
        bounds = parse_bounds(node.attrib.get("bounds"))
        if not bounds:
            continue
        # Recent Xiaohongshu builds may report the first product row as starting
        # behind the fixed search header (for example y1=78) even though the
        # card is visibly laid out below it.  Reject nodes wholly contained in
        # the header and nodes starting in the bottom overlay area instead of
        # requiring the card's reported top edge to clear the header.
        if bounds.y2 <= 342 or bounds.y1 >= 1920 or bounds.area < 20_000 or bounds.area > 650_000:
            continue
        blob = node_blob(node)
        # Search cards can legitimately show social-proof copy such as
        # ``100+人收藏``.  It is not the favourite action itself.  Continue to
        # reject every transactional control marker, but do not disqualify the
        # whole card merely because its statistics contain 收藏.
        card_danger_markers = tuple(marker for marker in DANGER_TEXT if marker != "收藏")
        if any(marker in blob for marker in card_danger_markers):
            continue
        if any(marker in blob for marker in NONSTANDARD_PRODUCT_MARKERS):
            continue
        has_price = "\u00a5" in blob or "\uffe5" in blob
        has_sales = "\u5df2\u552e" in blob
        has_product_name = len(blob) >= 12
        if has_product_name and (has_price or has_sales):
            x, y = bounds.center
            cards.append(UiTarget(x=x, y=y, bounds=bounds, label=blob[:80], reason="product-card"))
    cards.sort(key=lambda item: (item.bounds.y1, item.bounds.x1))
    deduped: list[UiTarget] = []
    seen: set[tuple[int, int, int, int]] = set()
    for card in cards:
        key = (card.bounds.x1 // 10, card.bounds.y1 // 10, card.bounds.x2 // 10, card.bounds.y2 // 10)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(card)
        if len(deduped) >= limit:
            break
    return deduped


def find_related_note_cards(xml_text: str, *, limit: int = 3) -> list[UiTarget]:
    root = parse_ui(xml_text)
    cards: list[tuple[int, UiTarget]] = []
    root_blob = node_blob(root)
    has_note_section = "\u5f00\u7bb1\u7cbe\u9009" in root_blob or "\u672c\u5e97\u76f8\u5173\u7b14\u8bb0" in root_blob
    note_markers = (
        "\u5f00\u7bb1\u7cbe\u9009",
        "\u76f8\u5173\u7b14\u8bb0",
        "\u672c\u5e97\u76f8\u5173",
        "\u7b14\u8bb0",
        "\u4e2a\u6708",
        "App",
    )
    for node in root.iter():
        if node.attrib.get("clickable") != "true" or is_dangerous_node(node):
            continue
        bounds = parse_bounds(node.attrib.get("bounds"))
        if not bounds:
            continue
        if bounds.y1 < 1300 or bounds.y2 > 1836 or bounds.area < 8_000:
            continue
        blob = node_blob(node)
        if "\u5e97\u94fa\u53e3\u7891" in blob or "\u5546\u54c1\u8bc4\u4ef7" in blob:
            continue
        is_text_note = len(blob) >= 12 and any(marker in blob for marker in note_markers)
        is_visual_note_card = (
            has_note_section
            and 220 <= bounds.width <= 420
            and bounds.height >= 250
            and bounds.y1 >= 1350
            and len(blob) >= 4
            and not any(marker in blob for marker in ("\u5f00\u7bb1\u7cbe\u9009", "\u672c\u5e97\u76f8\u5173"))
        )
        if is_text_note or is_visual_note_card:
            x, y = bounds.center
            priority = 0 if is_visual_note_card else 1
            cards.append((priority, UiTarget(x=x, y=y, bounds=bounds, label=blob[:120], reason="related-note-card")))
    cards.sort(key=lambda item: (item[0], item[1].bounds.y1, item[1].bounds.x1, -item[1].bounds.area))
    deduped: list[UiTarget] = []
    seen: set[tuple[int, int, int, int]] = set()
    for _, card in cards:
        key = (card.bounds.x1 // 10, card.bounds.y1 // 10, card.bounds.x2 // 10, card.bounds.y2 // 10)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(card)
        if len(deduped) >= limit:
            break
    return deduped


def find_note_author_entry(xml_text: str) -> UiTarget | None:
    root = parse_ui(xml_text)
    ignored = {
        "\u5173\u6ce8",
        "\u5206\u4eab",
        "\u8fd4\u56de",
        "\u66f4\u591a",
        "\u641c\u7d22",
        "\u5546\u5bb6",
        "\u5c55\u5f00",
        "\u5f00\u7bb1\u7cbe\u9009",
    }
    candidates: list[UiTarget] = []
    for node in root.iter():
        label = node_label(node)
        bounds = parse_bounds(node.attrib.get("bounds"))
        if not label or not bounds or is_dangerous_node(node):
            continue
        if bounds.y1 > 190 or bounds.x1 < 70 or bounds.x2 > 900:
            continue
        if label in ignored or any(token in label for token in ignored):
            continue
        if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", label):
            continue
        target = _target_from_node(node, "note-author-entry")
        if target:
            candidates.append(target)
    candidates.sort(key=lambda item: (item.bounds.y1, item.bounds.x1, len(item.label)))
    return candidates[0] if candidates else None
