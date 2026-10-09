from xhs_scout.signals import (
    candidate_score,
    classify_page_text,
    detect_risk_stop,
    gray_metric_items,
    has_product_evidence,
    parse_product_text,
)


def test_gray_metric_items_counts_distinct_valid_strip_entries_only():
    raw = {
        "metrics_strip": {
            "frames": [
                {
                    "metric_like": True,
                    "ignored": False,
                    "repeated": False,
                    "signals": {
                        "cart_24h_min": 20,
                        "positive_reviews_30d_min": 30,
                        "interested_7d_min": 100,
                    },
                },
                {
                    "metric_like": True,
                    "ignored": True,
                    "repeated": False,
                    "signals": {"sales_30d_min": 999},
                },
                {
                    "metric_like": True,
                    "ignored": False,
                    "repeated": False,
                    "signals": {"cart_24h_min": 20},
                },
            ]
        }
    }

    assert gray_metric_items(raw) == (
        "cart_24h_min",
        "positive_reviews_30d_min",
        "interested_7d_min",
    )


def test_product_detail_signals():
    text = """
    ￥9.9 已售1.1万+
    小学作文30次小练笔 适合3456年级 电子资料
    24小时内100+人购买过
    24小时内100+人加购
    近30天新增200+
    24小时销量飙升
    付款后自动发货
    """
    parsed = parse_product_text(text)
    assert parsed.price == 9.9
    assert parsed.cumulative_sales_min == 11_000
    assert parsed.cumulative_sales_display == "1.1万+"
    assert parsed.cumulative_sales_exact is None
    assert parsed.sales_24h_min == 100
    assert parsed.cart_24h_min == 100
    assert parsed.new_30d_min == 200
    assert parsed.sales_surging is True
    assert parsed.is_virtual is True
    score, reasons, grade = candidate_score(parsed)
    assert score >= 60
    assert reasons
    assert grade == "B"


def test_review_signal_does_not_become_sales():
    parsed = parse_product_text("近30天新增1500+条好评 51人正在看")
    assert parsed.positive_reviews_30d_min == 1500
    assert parsed.new_30d_min is None
    assert parsed.sales_24h_min is None
    assert parsed.viewers_now == 51


def test_favorite_signal_does_not_become_sales():
    parsed = parse_product_text("近30天新增200+人收藏 24小时内100+人购买过")
    assert parsed.favorites_30d_min == 200
    assert parsed.new_30d_min is None
    assert parsed.sales_24h_min == 100


def test_30d_interest_and_purchase_do_not_become_generic_new_sales():
    parsed = parse_product_text(
        "近30天新增750+条好评 近30天3000+人感兴趣 近30天内600+人购买"
    )
    assert parsed.positive_reviews_30d_min == 750
    assert parsed.interested_30d_min == 3000
    assert parsed.sales_30d_min == 600
    assert parsed.new_30d_min is None


def test_partial_generic_30d_new_label_is_ignored():
    parsed = parse_product_text("近30天新增200 近30天新增200+人收藏")
    assert parsed.new_30d_min is None
    assert parsed.favorites_30d_min == 200


def test_extract_title():
    parsed = parse_product_text(
        "￥9.9\n小学作文30次小练笔适合3456年级电子资料\n24小时内100+人购买过"
    )
    assert parsed.title == "小学作文30次小练笔适合3456年级电子资料"


def test_detail_title_prefers_named_lecture_pack_after_price():
    parsed = parse_product_text(
        """
        电子版/可打印/可编辑
        ￥29.9
        已售4067
        小学语文二升三升四升五升六年级阅读理解暑假讲义
        近30天新增2000+条好评
        """
    )
    assert parsed.title == "小学语文二升三升四升五升六年级阅读理解暑假讲义"
    assert parsed.price == 29.9
    assert parsed.cumulative_sales_min == 4067
    assert parsed.cumulative_sales_display == "4067"
    assert parsed.cumulative_sales_exact == 4067


def test_sales_display_is_found_after_title_and_only_plain_integer_is_exact():
    vague = parse_product_text("￥29.9\n高情商应答模板通用场景版\n目前已售1.9万+")
    exact = parse_product_text("￥9.9\n虚拟资料模板合集\n目前已售1100")

    assert vague.cumulative_sales_display == "1.9万+"
    assert vague.cumulative_sales_min == 19_000
    assert vague.cumulative_sales_exact is None
    assert exact.cumulative_sales_display == "1100"
    assert exact.cumulative_sales_min == 1100
    assert exact.cumulative_sales_exact == 1100


def test_social_growth_detail_prefers_final_product_title_and_sale_price():
    parsed = parse_product_text(
        """
        电子资料
        4.被夸/被怼/被盘问？高情商应答模板（通用+场景版）
        ￥39.8
        到手价￥19.8
        已售1.9万+
        普通人社会化成长指南-i人社交技巧-人情世故保姆级攻略
        近7天1000+人感兴趣
        """
    )

    assert parsed.title == "普通人社会化成长指南-i人社交技巧-人情世故保姆级攻略"
    assert parsed.price == 19.8
    assert parsed.cumulative_sales_display == "1.9万+"


def test_price_alone_is_not_product_evidence():
    parsed = parse_product_text("夏日来袭\n单月卡 原价 ￥1580\n首页 市集 消息 我")
    assert parsed.price == 1580
    assert has_product_evidence(parsed) is False


def test_sales_or_title_is_product_evidence():
    assert has_product_evidence(parse_product_text("￥9.9 已售1.1万+")) is True
    assert has_product_evidence(parse_product_text("小学作文30次小练笔适合3456年级电子资料")) is True


def test_real_detail_prefers_title_over_review_and_extracts_showcase():
    text = """
    ￥29.9
    已售1.2万+
    商家券满89减30
    职场新人快速成长指南知识库|求职+入职+认知+方法+SOP+思维模版
    来自囍财的橱窗>
    近30天新增1500+条好评
    近7天2000+人感兴趣
    一周内300+人购买
    商品评价6500+
    买这六篇文档，是我今年做过最值的一件事。买完过后一边读一边疯狂记笔记，每篇都全部是干货
    """
    parsed = parse_product_text(text)
    assert parsed.title == "职场新人快速成长指南知识库|求职+入职+认知+方法+SOP+思维模版"
    assert parsed.shop_name == "囍财"
    assert parsed.cumulative_sales_min == 12_000
    assert parsed.positive_reviews_30d_min == 1_500
    assert parsed.interested_7d_min == 2_000
    assert parsed.sales_7d_min == 300
    score, reasons, grade = candidate_score(parsed)
    assert score >= 75
    assert "累计销量至少12000" in reasons
    assert grade == "B"


def test_real_detail_title_ignores_review_after_product_section():
    text = """
    ￥199
    到手价￥149
    已售1177
    限时立减40元
    商家券新客立减10元
    【1年学习】商学提升计划|0-1搭建商业认知体系·商业思维课程
    近期店铺销量TOP1
    一周内300+人购买
    店铺商品回购第3名
    24小时内200+人加购
    近30天新增200+人收藏
    预计1小时内发货
    已选：1年学习
    商品评价450+
    评分4.6
    第一次接触这类内容，没有想象中的那么晦涩。母题拆解得很系统也挺好理解，很适合每天花点时间补补脑子，打算每周找
    """
    parsed = parse_product_text(text)
    assert parsed.title == "【1年学习】商学提升计划|0-1搭建商业认知体系·商业思维课程"
    assert parsed.price == 149
    assert parsed.cumulative_sales_min == 1177
    assert parsed.sales_7d_min == 300
    assert parsed.cart_24h_min == 200
    assert parsed.favorites_30d_min == 200


def test_real_food_detail_uses_strict_header_fallback_for_title():
    parsed = parse_product_text(
        """
        ￥25.9
        到手价￥8.9
        七夕大集
        全场好礼88折起
        已售721
        跨店每满200减30
        限时立减16
        从160斤到105斤，30天减脂烹饪食谱分享！！
        最晚8月13日发货，晚发必赔
        商品评价150+
        内容挺丰富的，希望能瘦个10斤
        """
    )

    assert parsed.title == "从160斤到105斤，30天减脂烹饪食谱分享！！"
    assert parsed.price == 8.9
    assert parsed.cumulative_sales_exact == 721


def test_risk_stop_detection_is_specific():
    assert detect_risk_stop("请完成安全验证后继续访问") == "安全验证"
    assert detect_risk_stop("操作频繁，请稍后再试") == "操作频繁"
    assert detect_risk_stop("验证码资料模板 自动发货") is None


def test_page_kind_classification():
    assert classify_page_text("￥149 已售1177 【1年学习】课程 已选：1年学习 商品评价450+ 预计1小时内发货 加入购物车 立即购买") == "product_detail"
    assert classify_page_text("综合 销量 新品 价格 【1年学习】课程 ￥149已售1177 【2年学习】课程 ￥249已售84 没有更多商品了") == "shop_product_list"
    assert classify_page_text("请完成安全验证后继续访问") == "risk_stop"
    assert classify_page_text("带货赚佣金 选品中心 选品加橱窗") == "forbidden_interaction_area"
    assert classify_page_text("搜索 历史记录 虚拟资料 作文模板 猜你想搜 热门虚拟资料") == "search_input"
    assert classify_page_text("常在网上混，总有卡住的时候 返回") == "open_error"
    assert classify_page_text("猫叔英语研究所 关注 7天无痛背完高考高频词 说点什么..") == "note_detail"
    assert classify_page_text("开箱精选 小红点点 高中英语读后续写高分句型 展开 共6张 6460 评论") == "note_detail"
    assert classify_page_text("猫叔英语研究所 小红书号 关注 128 粉丝 3200 获赞与收藏 笔记") == "account_profile"
    assert classify_page_text("南波老师资料库 粉丝2054 62篇笔记 综合 销量 新品 价格 商品A ￥9.9已售670 商品B ￥9.9已售4067") == "shop_product_list"
    assert classify_page_text("大麦美食 粉丝4437 好评率97.3% 平均1小时发货 恭喜获得双重福利 关注并领取 综合 销量 价格 ￥8.9 已售721 首页") == "shop_product_list"
    assert classify_page_text(
        "顾顾敌川 ★★★★★4.8已售3.1万 粉丝2.1万 好评率99.1% "
        "店铺粉丝 送你一张优惠券 关注领 综合 销量 新品 全店通用 "
        "￥10.9 已售2173 没有更多商品了 首页 上新"
    ) == "shop_product_list"
    assert classify_page_text("首页 关注 综合 销量 新品 热门内容") == "home_feed"
    assert classify_page_text("古诗文 搜索 综合 商品 笔记同款 温故知新的店粉丝2万+ 已售4891") == "search_results"
