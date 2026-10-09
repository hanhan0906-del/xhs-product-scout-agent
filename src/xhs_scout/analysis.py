from __future__ import annotations

import re
from typing import Any


METRIC_FIELDS: tuple[tuple[str, str], ...] = (
    ("cumulative_sales_min", "累计销量下限"),
    ("sales_24h_min", "24小时购买下限"),
    ("sales_7d_min", "近7天购买下限"),
    ("sales_30d_min", "近30天购买下限"),
    ("cart_24h_min", "24小时加购下限"),
    ("positive_reviews_30d_min", "近30天新增好评下限"),
    ("favorites_30d_min", "近30天新增收藏下限"),
    ("interested_7d_min", "近7天感兴趣下限"),
    ("interested_30d_min", "近30天感兴趣下限"),
    ("viewers_now", "正在看"),
)


def _has_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword.casefold() in text.casefold() for keyword in keywords)


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _truthy(value: Any) -> bool:
    return value not in (None, "", 0, "0", False)


def _normalize_author(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _metric_value(row: dict[str, Any], key: str) -> int | None:
    return _as_int(row.get(key))


def _search_evidence_is_invalid(row: dict[str, Any]) -> bool:
    return row.get("search_evidence_valid") in (0, "0", False)


def extract_trend_metrics(row: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = [
        {"key": key, "label": label, "value": value}
        for key, label in METRIC_FIELDS
        if (value := _metric_value(row, key)) is not None
    ]
    if _truthy(row.get("sales_surging")):
        metrics.append({"key": "sales_surging", "label": "页面标记", "value": "销量飙升"})
    return metrics


def _classify_product(row: dict[str, Any]) -> list[str]:
    title = str(row.get("title") or "")
    tags: list[str] = []
    if _has_any(title, ("小学", "初中", "高中", "高考", "中考", "语文", "英语", "阅读理解", "作文", "古诗", "考研", "雅思", "讲义", "知识点")):
        tags.append("学习资料")
    if _has_any(title, ("面试", "求职", "职场", "实习", "秋招", "简历", "入职", "interview", "resume", "job", "career")):
        tags.append("职场求职")
    if _has_any(title, ("人生管理", "效率", "计划", "复盘", "自律", "情绪", "陪伴", "习惯")):
        tags.append("效率管理")
    if _has_any(title, ("飞书", "notion", "excel", "模板", "知识库", "sop", "提示词", "ai")):
        tags.append("模板工具")
    if _has_any(title, ("商学", "商业", "认知", "思维", "副业", "增长")):
        tags.append("商业认知")
    if not tags:
        tags.append("虚拟资料")
    return tags


def _trend_facts(row: dict[str, Any]) -> list[str]:
    metrics = extract_trend_metrics(row)
    if not metrics:
        return ["暂无可量化趋势指标，只能作为待复核样本。"]
    return [f"{metric['label']}：{metric['value']}" for metric in metrics]


def _trend_inferences(row: dict[str, Any]) -> list[str]:
    inferences: list[str] = []
    cumulative = _metric_value(row, "cumulative_sales_min") or 0
    sales_30d = _metric_value(row, "sales_30d_min") or 0
    sales_7d = _metric_value(row, "sales_7d_min") or 0
    interested_30d = _metric_value(row, "interested_30d_min") or 0
    interested_7d = _metric_value(row, "interested_7d_min") or 0
    reviews = _metric_value(row, "positive_reviews_30d_min") or 0
    favorites = _metric_value(row, "favorites_30d_min") or 0
    score = _as_float(row.get("score"))

    if sales_7d >= 300 or interested_7d >= 2000:
        inferences.append("短周期成交或兴趣信号较强，适合优先做人工复核。")
    if sales_30d >= 1000 or reviews >= 1000:
        inferences.append("近30天新增指标突出，商品不是只靠历史累计销量支撑。")
    if cumulative >= 10000 and sales_30d < 500 and sales_7d < 100:
        inferences.append("累计销量高但近期成交弱，可能是长尾老品，需要谨慎判断复刻窗口。")
    if interested_30d >= 5000 and sales_30d < 500:
        inferences.append("兴趣人数高于成交增量，可能存在价格、交付或信任门槛。")
    if favorites >= 100 and sales_30d < 500:
        inferences.append("收藏信号存在但购买不足，适合观察详情页卖点和评价是否有转化阻塞。")
    if _truthy(row.get("sales_surging")):
        inferences.append("页面出现销量飙升标记，但仍需销量字段和时间窗口交叉验证。")
    if score < 60:
        inferences.append("候选分低于强趋势阈值，当前更像观察样本而非直接执行品。")
    return inferences or ["当前趋势字段可支持候选入池，但还不足以单独证明低粉爆款。"]


def _evidence_gaps(row: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if not row.get("screenshot_path"):
        gaps.append("缺少商品详情页截图证据。")
    if _search_evidence_is_invalid(row):
        reason = str(row.get("search_invalid_reason") or "未记录失效原因")
        gaps.append(f"最新搜索证据已失效（{reason}），不能沿用更早记录作为当前关键词归属。")
    elif not row.get("search_source_keyword"):
        gaps.append("缺少有效搜索来源关键词或搜索结果位次。")
    if not extract_trend_metrics(row):
        gaps.append("缺少销量、加购、收藏、好评或感兴趣等趋势指标。")
    if not row.get("share_url"):
        gaps.append("缺少可人工复核的商品原链接。")
    if not row.get("latest_note_author_name"):
        gaps.append("缺少关联公开笔记证据，无法判断爆量来源。")
    if row.get("latest_note_likes") is None:
        gaps.append("缺少单条笔记点赞数，不能用账号累计获赞替代。")
    if row.get("latest_note_published_days_ago") is None:
        gaps.append("缺少单条笔记发布时间，不能判断是否为近7天爆款。")
    if not row.get("latest_profile_author_name"):
        gaps.append("缺少作者公开主页证据。")
    if row.get("latest_profile_follower_count") is None:
        gaps.append("缺少作者粉丝数，不能完成低粉闭环。")

    note_author = _normalize_author(row.get("latest_note_author_name"))
    profile_author = _normalize_author(row.get("latest_profile_author_name"))
    if note_author and profile_author and note_author != profile_author:
        gaps.append("公开笔记作者与主页作者不一致，需要人工核验。")
    if not _truthy(row.get("low_follower_verified")):
        gaps.append("尚未通过近期、低粉和单条笔记互动三项闭环，不能自动升 A。")
    return gaps


def _risk_points(row: dict[str, Any], tags: list[str]) -> list[str]:
    title = str(row.get("title") or "")
    risks = [
        "低粉账号/笔记证据未闭环前，只能按候选观察，不应当成 A 级低粉爆款。",
    ]
    follower_count = _as_int(row.get("latest_profile_follower_count"))
    published_days = _as_int(row.get("latest_note_published_days_ago"))
    score = _as_float(row.get("score"))

    if str(row.get("assessment_status") or "") == "needs_review":
        risks.append("最新评估状态为 needs_review，必须由人工复核，不能按普通候选直接采用。")
    if _search_evidence_is_invalid(row):
        risks.append("最新搜索证据链已失效，当前关键词归属未成立，禁止用更早有效记录替代。")
    if follower_count is not None and follower_count >= 10000:
        risks.append("作者粉丝已达到或超过1万，爆量可能来自账号权重，应按高权重账号风险处理。")
    if published_days is not None and published_days > 7:
        risks.append(f"关联笔记发布距今 {published_days} 天，不符合近7天低粉爆款优先标准。")
    if score < 60:
        risks.append("候选分未达到强趋势阈值，投入制作前应先补一次真实页面复核。")
    if "学习资料" in tags:
        risks.append("学习资料必须核查版权、年份版本、题源和更新频率，不能搬运现成题库或讲义。")
    if "职场求职" in tags:
        risks.append("求职/职场资料容易夸大结果，不能承诺录用、涨薪或包过。")
    if "模板工具" in tags:
        risks.append("模板类商品同质化强，若只改标题和封面，复刻价值很低。")
    if "商业认知" in tags:
        risks.append("商业认知类内容容易空泛，必须用可执行练习和案例验证交付价值。")
    if _has_any(title, ("电子版", "资料", "讲义", "题库", "知识点")):
        risks.append("电子资料类交付需避免侵权素材、盗版课程、虚假授权和售后无法兑现。")
    return risks


def _originality_directions(row: dict[str, Any], tags: list[str]) -> list[str]:
    title = str(row.get("title") or "")
    directions: list[str] = []

    if "学习资料" in tags:
        directions.extend(
            [
                "做年级/阶段分层：按基础薄弱、冲刺提分、假期预习分别设计目录、练习量和检查表。",
                "把资料包改成闭环工具：诊断题、每日任务、错题归因表、复盘页和家长/学生使用说明一起交付。",
                "用原创讲解、例题改写和学习路径替代搬运题库，封面与详情页明确适用年级、版本和更新日期。",
            ]
        )
    if "职场求职" in tags:
        directions.extend(
            [
                "按岗位和阶段拆分：校招、转行、实习、入职30天分别做话术、SOP和复盘模板。",
                "把模板做成可填写流程：问题清单、面试追问库、作品集检查表和一页式行动计划。",
                "展示匿名化样例和使用前后对照，不写包过、保录、必涨薪等无法验证承诺。",
            ]
        )
    if "效率管理" in tags:
        directions.extend(
            [
                "围绕一个高频场景做轻量系统，例如学生周计划、打工人复盘、情绪记录或副业任务看板。",
                "加入可自动复制的周期模板、提醒规则、复盘问题和失败补救动作，让买家当天能用。",
            ]
        )
    if "模板工具" in tags:
        directions.extend(
            [
                "把模板从单文件升级为组合工作流：录入页、看板页、复盘页、示例数据和清空说明分开交付。",
                "提供3个真实使用场景的预填样例，突出结构设计和操作体验，而不是只卖空白表格。",
            ]
        )
    if "商业认知" in tags:
        directions.extend(
            [
                "把抽象课程改成案例练习卡：定价、选题、账号增长、产品拆解各配一页可填模板。",
                "用小任务替代大而全课程，例如每天30分钟完成一个商业案例复盘。",
            ]
        )
    if not directions:
        directions.append("从目标人群、使用场景、交付格式和更新机制四处重做，不复制原商品标题、目录或素材。")
    if _has_any(title, ("阅读理解", "作文", "古诗")):
        directions.append("语文类可增加答案解析步骤、常见失分点和家长检查口径，避免只卖答案。")
    if _has_any(title, ("英语", "高考", "考研", "雅思")):
        directions.append("英语/考试类可增加词汇诊断、错因标签、跟练节奏和考前冲刺版本。")
    return list(dict.fromkeys(directions))


def _confidence(row: dict[str, Any], gaps: list[str]) -> dict[str, Any]:
    score = 20
    candidate_score = _as_float(row.get("score"))
    grade = str(row.get("evidence_grade") or "").upper()
    metrics = extract_trend_metrics(row)

    if grade == "A":
        score += 25
    elif grade == "B":
        score += 15
    elif grade == "C":
        score += 6
    if candidate_score >= 75:
        score += 20
    elif candidate_score >= 60:
        score += 14
    elif candidate_score >= 40:
        score += 8
    if metrics:
        score += min(18, len(metrics) * 3)
    if (
        not _search_evidence_is_invalid(row)
        and row.get("search_source_keyword")
        and row.get("search_result_rank") is not None
    ):
        score += 8
    if row.get("screenshot_path"):
        score += 5
    if row.get("latest_note_author_name") and row.get("latest_profile_author_name"):
        score += 8
    if row.get("latest_note_likes") is not None and row.get("latest_profile_follower_count") is not None:
        score += 8
    if _truthy(row.get("low_follower_verified")):
        score += 15
    elif grade != "A":
        score = min(score, 70)
    if not metrics:
        score = min(score, 50)
    score = max(0, min(100, score - min(20, len(gaps) * 2)))
    level = "高" if score >= 75 else "中" if score >= 45 else "低"
    return {
        "score": score,
        "level": level,
        "summary": f"{level}置信度（{score}/100）",
    }


def analyze_candidate(row: dict[str, Any], reasons: list[str] | None = None) -> dict[str, Any]:
    tags = _classify_product(row)
    gaps = _evidence_gaps(row)
    confidence = _confidence(row, gaps)
    search_status = (
        f"已失效（{row.get('search_invalid_reason') or '未记录失效原因'}）"
        if _search_evidence_is_invalid(row)
        else "有效"
        if row.get("search_source_keyword")
        else "未建立"
    )
    return {
        "tags": tags,
        "facts": [
            f"商品类型推断：{'、'.join(tags)}",
            f"最新评估状态：{row.get('assessment_status') or '未识别'}。",
            f"商品证据：商品页截图 {row.get('screenshot_path') or '未采集'}；原链接 {row.get('share_url') or '未识别'}。",
            f"搜索证据：状态 {search_status}；记录关键词 {row.get('search_source_keyword') or '未识别'}；结果位次 {row.get('search_result_rank') if row.get('search_result_rank') is not None else '未识别'}；证据目录 {row.get('search_probe_dir') or '未采集'}。",
        ],
        "trend_metrics": _trend_facts(row),
        "inferences": _trend_inferences(row),
        "selection_reasons": reasons or [],
        "risks": _risk_points(row, tags),
        "gaps": gaps or ["关键商品、趋势、搜索和低粉证据已具备，进入人工复核即可。"],
        "confidence": confidence,
        "originality_directions": _originality_directions(row, tags),
    }
