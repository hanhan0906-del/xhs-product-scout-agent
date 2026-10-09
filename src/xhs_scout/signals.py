from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass


VIRTUAL_TERMS = (
    "资料",
    "电子",
    "模板",
    "课件",
    "教案",
    "讲义",
    "题库",
    "音频",
    "课程",
    "训练营",
    "软件",
    "小程序",
    "系统",
    "表格",
    "文档",
    "自动发货",
    "网盘",
    "知识库",
    "指南",
    "攻略",
    "模版",
)

RISK_STOP_MARKERS = (
    # 已知平台安全页使用的完整短语。不要把单独的“异常”加入词表，
    # 否则普通商品标题或故障排查资料也会触发硬风控停止。
    "安全限制",
    "设备异常",
    "风险插件",
    "登录异常",
    "请完成验证",
    "安全验证",
    "滑块验证",
    "操作频繁",
    "访问过于频繁",
    "账号异常",
    "请稍后再试",
    "网络异常",
)


@dataclass
class ProductSignals:
    title: str | None = None
    shop_name: str | None = None
    price: float | None = None
    cumulative_sales_display: str | None = None
    cumulative_sales_exact: int | None = None
    cumulative_sales_min: int | None = None
    sales_24h_min: int | None = None
    sales_7d_min: int | None = None
    sales_30d_min: int | None = None
    cart_24h_min: int | None = None
    new_30d_min: int | None = None
    positive_reviews_30d_min: int | None = None
    favorites_30d_min: int | None = None
    interested_7d_min: int | None = None
    interested_30d_min: int | None = None
    viewers_now: int | None = None
    sales_surging: bool = False
    is_virtual: bool | None = None
    virtual_confidence: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


GRAY_METRIC_FIELDS = (
    "cumulative_sales_min",
    "sales_24h_min",
    "sales_7d_min",
    "sales_30d_min",
    "cart_24h_min",
    "new_30d_min",
    "positive_reviews_30d_min",
    "favorites_30d_min",
    "interested_7d_min",
    "interested_30d_min",
    "viewers_now",
)


def gray_metric_items(value: dict | str | None) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return ()
    if not isinstance(value, dict):
        return ()
    metrics_strip = value.get("metrics_strip", value)
    if not isinstance(metrics_strip, dict):
        return ()
    frames = metrics_strip.get("frames")
    if not isinstance(frames, list):
        return ()
    found: set[str] = set()
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        if frame.get("ignored") or frame.get("repeated"):
            continue
        if frame.get("metric_like") is False:
            continue
        signals = frame.get("signals")
        if not isinstance(signals, dict):
            continue
        found.update(
            field
            for field in GRAY_METRIC_FIELDS
            if signals.get(field) is not None
        )
        if signals.get("sales_surging"):
            found.add("sales_surging")
    return tuple(field for field in (*GRAY_METRIC_FIELDS, "sales_surging") if field in found)


def _number(raw: str, unit: str | None = None) -> int:
    value = float(raw)
    if unit == "万":
        value *= 10_000
    return int(value)


def _first(patterns: tuple[str, ...], text: str):
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match
    return None


def parse_product_text(text: str) -> ProductSignals:
    raw_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines() if line.strip()]
    normalized = "\n".join(raw_lines).replace(",", "").replace("，", "")
    signals = ProductSignals()

    excluded_title_markers = (
        "小时",
        "近30天",
        "已售",
        "加购",
        "自动发货",
        "搜索",
        "退款",
        "已选",
        "商品评价",
        "用户已注销",
        "买完",
        "今年",
        "老师",
        "第一次",
        "超级好用",
        "打算",
        "希望",
        "觉得",
        "感觉",
        "喜欢",
        "评论",
        "店铺口碑",
        "综合最新",
        "开箱精选",
        "本店相关",
    )

    def is_title_candidate(line: str) -> bool:
        return (
            8 <= len(line) <= 80
            and any(term in line for term in VIRTUAL_TERMS)
            and not any(marker in line for marker in excluded_title_markers)
        )

    # 商品详情页的正式标题通常紧跟价格/已售区域。先限制在这个局部区域，
    # 避免把下方包含“文档、模板”等词的长评论误识别成标题。
    anchors = [
        index
        for index, line in enumerate(raw_lines)
        if re.search(r"[¥￥]\s*\d", line) or re.search(r"已售\s*\d", line)
    ]
    review_section_markers = ("商品评价", "评分", "本店相关笔记", "开箱精选")
    title_candidates: list[tuple[float, str, int]] = []
    last_review_marker = -1
    for index, line in enumerate(raw_lines):
        if any(marker in line for marker in review_section_markers):
            last_review_marker = index
        if not is_title_candidate(line) or line.startswith("来自"):
            continue
        preceding_anchors = [anchor for anchor in anchors if anchor < index]
        distance = index - max(preceding_anchors) if preceding_anchors else 99
        anchor_score = max(0, 36 - distance * 6) if distance <= 8 else 0
        nearby_context = "\n".join(raw_lines[max(0, index - 6): index + 3])
        context_score = 0
        if re.search(r"[¥￥]\s*\d|已售\s*\d|到手价|商家券|限时立减|自动发货", nearby_context):
            context_score += 16
        if re.search(r"预计.*发货|承诺.*发货|7天无理由|已选", nearby_context):
            context_score += 8
        term_score = sum(term in line for term in VIRTUAL_TERMS) * 4
        structure_score = 0
        if "【" in line and "】" in line:
            structure_score += 14
        if "|" in line or "｜" in line:
            structure_score += 8
        if len(line) >= 18:
            structure_score += 8
        if len(line) <= 10:
            structure_score -= 18
        review_penalty = 35 if last_review_marker >= 0 and last_review_marker < index else 0
        title_candidates.append(
            (
                anchor_score
                + context_score
                + term_score
                + structure_score
                + min(len(line), 60) / 20
                - review_penalty,
                line,
                index,
            )
        )
    title_index = None
    if title_candidates:
        best_title = max(title_candidates, key=lambda item: item[0])
        signals.title = best_title[1]
        title_index = best_title[2]

    # 部分虚拟商品的详情标题本身不含“资料/模板/课程”等词，例如电子食谱只展示
    # “30天减脂烹饪食谱分享”。仅在强价格/已售锚点后的狭窄商品头部区域启用兜底，
    # 并排除优惠、发货、评价和购买控件，避免把下方评论当成标题。
    has_sold_anchor = any(
        re.search(r"已售\s*\d", raw_lines[index]) for index in anchors
    )
    if signals.title is None and anchors and has_sold_anchor:
        last_anchor = max(anchors)
        fallback_excluded_markers = (
            *excluded_title_markers,
            "到手价",
            "全场",
            "跨店",
            "每满",
            "立减",
            "商家券",
            "新客",
            "折起",
            "七夕",
            "发货",
            "退换",
            "评分",
            "加入购物车",
            "立即购买",
            "客服",
            "购物车",
        )
        fallback_candidates: list[tuple[int, int, str, int]] = []
        for index in range(last_anchor + 1, min(len(raw_lines), last_anchor + 9)):
            line = raw_lines[index]
            if not 8 <= len(line) <= 80:
                continue
            if any(marker in line for marker in fallback_excluded_markers):
                continue
            if re.search(r"[¥￥]\s*\d|已售\s*\d", line):
                continue
            fallback_candidates.append(
                (len(line), -(index - last_anchor), line, index)
            )
        if fallback_candidates:
            _, _, signals.title, title_index = max(fallback_candidates)

    showcase = _first((r"来自\s*(.+?)\s*的橱窗",), normalized)
    if showcase:
        signals.shop_name = showcase.group(1).strip(" >")

    shop_candidates = [
        re.sub(r"\s*加购的店.*$", "的店", line)
        for line in raw_lines
        if line.endswith("的店") or "加购的店" in line
    ]
    if shop_candidates and not signals.shop_name:
        signals.shop_name = shop_candidates[0]

    sold = _first(
        (
            r"(?:目前)?已售\s*(\d+(?:\.\d+)?)\s*(万)?\s*(\+)?",
            r"累计(?:销量|售出)\s*(\d+(?:\.\d+)?)\s*(万)?\s*(\+)?",
        ),
        normalized,
    )
    if sold:
        raw_number, unit, plus = sold.group(1), sold.group(2), sold.group(3)
        signals.cumulative_sales_display = f"{raw_number}{unit or ''}{plus or ''}"
        signals.cumulative_sales_min = _number(raw_number, unit)
        if unit is None and plus is None and "." not in raw_number:
            signals.cumulative_sales_exact = int(raw_number)

    purchase = _first(
        (
            r"24\s*小时(?:内)?\s*(\d+(?:\.\d+)?)\s*(万)?\s*\+?\s*人(?:购买|买过|购买过)",
            r"24\s*小时(?:销量)?\s*(\d+(?:\.\d+)?)\s*(万)?\s*\+?",
        ),
        normalized,
    )
    if purchase:
        signals.sales_24h_min = _number(purchase.group(1), purchase.group(2))

    weekly_purchase = _first(
        (r"(?:近\s*7\s*天|一周内)\s*(\d+(?:\.\d+)?)\s*(万)?\s*\+?\s*人购买",),
        normalized,
    )
    if weekly_purchase:
        signals.sales_7d_min = _number(
            weekly_purchase.group(1),
            weekly_purchase.group(2),
        )

    monthly_purchase = _first(
        (r"近\s*30\s*天(?:内)?\s*(\d+(?:\.\d+)?)\s*(万)?\s*\+?\s*人购买",),
        normalized,
    )
    if monthly_purchase:
        signals.sales_30d_min = _number(
            monthly_purchase.group(1),
            monthly_purchase.group(2),
        )

    cart = _first(
        (r"24\s*小时(?:内)?\s*(\d+(?:\.\d+)?)\s*(万)?\s*\+?\s*人加购",),
        normalized,
    )
    if cart:
        signals.cart_24h_min = _number(cart.group(1), cart.group(2))

    reviews = _first(
        (r"近\s*30\s*天新增\s*(\d+(?:\.\d+)?)\s*(万)?\s*\+?\s*条好评",),
        normalized,
    )
    if reviews:
        signals.positive_reviews_30d_min = _number(reviews.group(1), reviews.group(2))

    favorites = _first(
        (r"近\s*30\s*天新增\s*(\d+(?:\.\d+)?)\s*(万)?\s*\+?\s*人?收藏",),
        normalized,
    )
    if favorites:
        signals.favorites_30d_min = _number(favorites.group(1), favorites.group(2))

    interested = _first(
        (r"近\s*7\s*天\s*(\d+(?:\.\d+)?)\s*(万)?\s*\+?\s*人感兴趣",),
        normalized,
    )
    if interested:
        signals.interested_7d_min = _number(interested.group(1), interested.group(2))

    interested_30d = _first(
        (r"近\s*30\s*天(?:内)?\s*(\d+(?:\.\d+)?)\s*(万)?\s*\+?\s*人感兴趣",),
        normalized,
    )
    if interested_30d:
        signals.interested_30d_min = _number(interested_30d.group(1), interested_30d.group(2))

    sales_text = re.sub(
        r"近\s*30\s*天新增\s*\d+(?:\.\d+)?\s*万?\s*\+?\s*条好评",
        "",
        normalized,
    )
    sales_text = re.sub(
        r"近\s*30\s*天新增\s*\d+(?:\.\d+)?\s*万?\s*\+?\s*人?收藏",
        "",
        sales_text,
    )
    sales_text = re.sub(
        r"近\s*30\s*天(?:内)?\s*\d+(?:\.\d+)?\s*万?\s*\+?\s*人感兴趣",
        "",
        sales_text,
    )
    sales_text = re.sub(
        r"近\s*30\s*天(?:内)?\s*\d+(?:\.\d+)?\s*万?\s*\+?\s*人购买",
        "",
        sales_text,
    )
    new_30d = _first(
        (r"近\s*30\s*天(?:新增)?\s*(\d+(?:\.\d+)?)\s*(万)?\s*\+",),
        sales_text,
    )
    if new_30d:
        signals.new_30d_min = _number(new_30d.group(1), new_30d.group(2))

    viewers = re.search(r"(\d+)\s*人正在看", normalized)
    if viewers:
        signals.viewers_now = int(viewers.group(1))

    signals.sales_surging = "销量飙升" in normalized or "爆卖" in normalized

    price_text = normalized
    if title_index is not None:
        price_text = "\n".join(raw_lines[max(0, title_index - 8): title_index + 3])
    price = _first(
        (
            r"到手价\s*[¥￥]\s*(\d+(?:\.\d+)?)",
            r"[¥￥]\s*(\d+(?:\.\d+)?)",
            r"价格\s*(\d+(?:\.\d+)?)",
        ),
        price_text,
    )
    if price:
        signals.price = float(price.group(1))

    virtual_hits = sum(term in normalized for term in VIRTUAL_TERMS)
    signals.virtual_confidence = min(1.0, virtual_hits / 3)
    signals.is_virtual = virtual_hits > 0
    return signals


def has_product_evidence(signals: ProductSignals) -> bool:
    """Return True only when the page contains evidence stronger than a bare price."""
    return any(
        (
            signals.title,
            signals.shop_name,
            signals.cumulative_sales_min,
            signals.sales_24h_min,
            signals.sales_7d_min,
            signals.sales_30d_min,
            signals.cart_24h_min,
            signals.new_30d_min,
            signals.positive_reviews_30d_min,
            signals.favorites_30d_min,
            signals.interested_7d_min,
            signals.interested_30d_min,
            signals.sales_surging,
        )
    )


def detect_risk_stop(text: str) -> str | None:
    """Return the visible stop reason when the page shows risk-control or blocking UI."""
    normalized = re.sub(r"\s+", "", text)
    for marker in RISK_STOP_MARKERS:
        if marker in normalized:
            return marker
    return None


def classify_page_text(text: str) -> str:
    normalized = re.sub(r"\s+", "", text)
    if detect_risk_stop(text):
        return "risk_stop"
    if "带货赚佣金" in normalized or "选品加橱窗" in normalized or "提醒商家开通" in normalized:
        return "forbidden_interaction_area"
    if "常在网上混" in normalized and "卡住的时候" in normalized:
        return "open_error"
    if "说点什么" in normalized and "关注" in normalized:
        return "note_detail"
    if "开箱精选" in normalized and "展开" in normalized and "评论" in normalized and re.search(r"共\d+张", normalized):
        return "note_detail"
    shop_sort_markers = (
        "综合" in normalized
        and "销量" in normalized
        and ("价格" in normalized or "新品" in normalized)
    )
    if shop_sort_markers and (
        (
            "新品" in normalized
            and ("没有更多商品" in normalized or normalized.count("已售") >= 2)
        )
        or (
            "粉丝" in normalized
            and ("好评率" in normalized or "平均" in normalized)
            and "已售" in normalized
        )
    ):
        return "shop_product_list"
    if "粉丝" in normalized and (
        "小红书号" in normalized
        or ("获赞与收藏" in normalized and "关注" in normalized)
    ):
        return "account_profile"
    if "历史记录" in normalized and "猜你想搜" in normalized and "搜索" in normalized:
        return "search_input"
    detail_score = 0
    if re.search(r"[¥￥]\d+(?:\.\d+)?", normalized):
        detail_score += 1
    if "已售" in normalized:
        detail_score += 1
    if "已选" in normalized:
        detail_score += 2
    if "商品评价" in normalized or "评分" in normalized:
        detail_score += 1
    if "预计" in normalized and "发货" in normalized:
        detail_score += 1
    if "7天无理由" in normalized or "晚发必赔" in normalized:
        detail_score += 1
    if "加入购物车" in normalized or "立即购买" in normalized:
        detail_score += 1
    if detail_score >= 4:
        return "product_detail"
    if "搜索" in normalized and ("综合" in normalized or "筛选" in normalized):
        return "search_results"
    if "首页" in normalized and ("关注" in normalized or "发现" in normalized):
        return "home_feed"
    return "unknown"


def fingerprint(title: str | None, shop_name: str | None, share_url: str | None = None) -> str:
    if share_url:
        source = share_url.strip()
    else:
        source = f"{(title or '').strip().lower()}|{(shop_name or '').strip().lower()}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def candidate_score(signals: ProductSignals) -> tuple[float, list[str], str]:
    score = 0.0
    reasons: list[str] = []
    if signals.cumulative_sales_min:
        score += min(25.0, signals.cumulative_sales_min / 400)
        reasons.append(f"累计销量至少{signals.cumulative_sales_min}")
    if signals.sales_24h_min:
        score += min(35.0, signals.sales_24h_min / 4)
        reasons.append(f"24小时销量至少{signals.sales_24h_min}")
    if signals.sales_7d_min:
        score += min(25.0, signals.sales_7d_min / 12)
        reasons.append(f"近7天购买至少{signals.sales_7d_min}")
    if signals.sales_30d_min:
        score += min(18.0, signals.sales_30d_min / 40)
        reasons.append(f"近30天购买至少{signals.sales_30d_min}")
    if signals.cart_24h_min:
        score += min(15.0, signals.cart_24h_min / 10)
        reasons.append(f"24小时加购至少{signals.cart_24h_min}")
    if signals.new_30d_min:
        score += min(20.0, signals.new_30d_min / 25)
        reasons.append(f"近30天新增至少{signals.new_30d_min}")
    if signals.positive_reviews_30d_min:
        score += min(10.0, signals.positive_reviews_30d_min / 150)
        reasons.append(f"近30天新增好评至少{signals.positive_reviews_30d_min}")
    if signals.favorites_30d_min:
        score += min(8.0, signals.favorites_30d_min / 50)
        reasons.append(f"近30天新增收藏至少{signals.favorites_30d_min}")
    if signals.interested_7d_min:
        score += min(10.0, signals.interested_7d_min / 200)
        reasons.append(f"近7天感兴趣至少{signals.interested_7d_min}")
    if signals.interested_30d_min:
        score += min(8.0, signals.interested_30d_min / 500)
        reasons.append(f"近30天感兴趣至少{signals.interested_30d_min}")
    if signals.sales_surging:
        score += 20
        reasons.append("页面标记销量飙升")
    if signals.is_virtual:
        score += 10
        reasons.append("符合虚拟商品特征")
    grade = (
        "B"
        if (signals.cumulative_sales_min or 0) >= 100
        or signals.sales_24h_min
        or signals.sales_7d_min
        or signals.sales_30d_min
        or signals.new_30d_min
        else "C"
    )
    return round(min(score, 100), 1), reasons, grade
