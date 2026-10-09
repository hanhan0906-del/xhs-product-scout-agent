from __future__ import annotations

import json
from pathlib import Path

from .analysis import analyze_candidate, extract_trend_metrics
from .config import Settings
from .db import connect, utcnow
from .insights import digest_snapshot, quality_snapshot


def _fmt(value) -> str:
    return "未识别" if value is None or value == "" else str(value)


def _safe_json_list(value) -> list:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return ["候选理由数据格式异常，需人工复核"]
    return parsed if isinstance(parsed, list) else [str(parsed)]


def _metric_lines(row: dict) -> list[str]:
    lines = [
        f"- {metric['label']}：{metric['value']}"
        for metric in extract_trend_metrics(row)
    ]
    return lines or ["- 暂未识别到明确趋势指标"]


def _fetch_candidates(settings: Settings, limit: int) -> list[dict]:
    with connect(settings.db_path) as conn:
        rows = conn.execute(
            """
            SELECT p.id AS product_id, p.title, p.shop_name, p.price, p.share_url,
                   o.id AS observation_id, o.observed_at, o.screenshot_path,
                   o.cumulative_sales_min, o.sales_24h_min, o.sales_7d_min,
                   o.sales_30d_min, o.cart_24h_min, o.new_30d_min,
                   o.positive_reviews_30d_min, o.favorites_30d_min,
                   o.interested_7d_min, o.interested_30d_min,
                   o.viewers_now, o.sales_surging,
                   a.evidence_grade, a.score, a.low_follower_verified,
                   a.status AS assessment_status,
                   a.reasons_json,
                   se.source_keyword AS search_source_keyword,
                   se.result_rank AS search_result_rank,
                   se.search_probe_dir AS search_probe_dir,
                   se.search_screenshot_path AS search_screenshot_path,
                   se.valid AS search_evidence_valid,
                   se.invalid_reason AS search_invalid_reason,
                   (SELECT COUNT(*) FROM note_evidence n WHERE n.product_id=p.id) AS note_count,
                   (SELECT COUNT(*) FROM note_observations no WHERE no.product_id=p.id) AS note_observation_count,
                   (SELECT probe_dir FROM note_observations no
                    WHERE no.product_id=p.id AND no.source='related_note_card'
                    ORDER BY no.id DESC LIMIT 1) AS latest_note_probe_dir,
                   (SELECT author_name FROM note_observations no
                    WHERE no.product_id=p.id AND no.source='related_note_card'
                    ORDER BY no.id DESC LIMIT 1) AS latest_note_author_name,
                   (SELECT likes FROM note_observations no
                    WHERE no.product_id=p.id AND no.source='related_note_card'
                    ORDER BY no.id DESC LIMIT 1) AS latest_note_likes,
                   (SELECT collects FROM note_observations no
                    WHERE no.product_id=p.id AND no.source='related_note_card'
                    ORDER BY no.id DESC LIMIT 1) AS latest_note_collects,
                   (SELECT comments FROM note_observations no
                    WHERE no.product_id=p.id AND no.source='related_note_card'
                    ORDER BY no.id DESC LIMIT 1) AS latest_note_comments,
                   (SELECT published_days_ago FROM note_observations no
                    WHERE no.product_id=p.id AND no.source='related_note_card'
                    ORDER BY no.id DESC LIMIT 1) AS latest_note_published_days_ago,
                   (SELECT probe_dir FROM note_observations no
                    WHERE no.product_id=p.id AND no.source='author_profile_from_note'
                    ORDER BY no.id DESC LIMIT 1) AS latest_profile_probe_dir,
                   (SELECT author_name FROM note_observations no
                    WHERE no.product_id=p.id AND no.source='author_profile_from_note'
                    ORDER BY no.id DESC LIMIT 1) AS latest_profile_author_name,
                   (SELECT follower_count FROM note_observations no
                    WHERE no.product_id=p.id AND no.source='author_profile_from_note'
                    ORDER BY no.id DESC LIMIT 1) AS latest_profile_follower_count,
                   (SELECT likes FROM note_observations no
                    WHERE no.product_id=p.id AND no.source='author_profile_from_note'
                    ORDER BY no.id DESC LIMIT 1) AS latest_profile_total_likes
            FROM candidate_assessments a
            JOIN products p ON p.id=a.product_id
            LEFT JOIN observations o
              ON o.id=(SELECT id FROM observations WHERE product_id=p.id ORDER BY id DESC LIMIT 1)
            LEFT JOIN search_result_evidence se
              ON se.id=(SELECT id FROM search_result_evidence
                        WHERE product_id=p.id ORDER BY id DESC LIMIT 1)
            WHERE a.status IN ('candidate', 'needs_review')
              AND a.id=(SELECT id FROM candidate_assessments
                        WHERE product_id=a.product_id ORDER BY id DESC LIMIT 1)
            ORDER BY a.score DESC, o.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def generate_candidate_report(
    settings: Settings,
    *,
    output_path: Path | None = None,
    limit: int = 10,
) -> dict:
    rows = _fetch_candidates(settings, limit)
    generated_at = utcnow()
    output_path = output_path or settings.reports_dir / (
        f"candidates-{generated_at.replace(':', '-')}.md"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(settings.db_path) as conn:
        digest = digest_snapshot(conn, period="daily")
        quality = quality_snapshot(conn, settings, issue_limit=10)
    quality_severity = quality["summary"]["by_severity"]
    needs_review_count = sum(
        row.get("assessment_status") == "needs_review" for row in rows
    )
    candidate_count = len(rows) - needs_review_count

    lines = [
        "# 小红书虚拟商品候选分析报告",
        "",
        f"- 生成时间：{generated_at}",
        f"- 待处理商品数量：{len(rows)}（候选 {candidate_count}，人工复核 {needs_review_count}）",
        "- 说明：本报告只基于本地已采集的公开页面截图/OCR/入库字段，不代表全站穷举。",
        "",
        "## 近 24 小时监控摘要",
        "",
        f"- 新增观察：{digest['stats']['observations_in_window']}",
        f"- 新增候选：{digest['stats']['new_candidates']}",
        f"- 低粉证据闭环候选：{digest['stats']['low_follower_complete']}",
        f"- 人工复核项：{digest['stats']['manual_review_items']}",
        *(f"- 事实：{item}" for item in digest["facts"][:5]),
        *(f"- 风险：{item}" for item in digest["risks"][:5]),
        "",
        "## 数据质量摘要",
        "",
        f"- 审计范围：商品 {quality['scope']['products']}，观察 {quality['scope']['observations']}，笔记/账号证据 {quality['scope']['notes']}。",
        f"- 问题统计：错误 {quality_severity['error']}，警告 {quality_severity['warning']}，提示 {quality_severity['info']}。",
        "- 质量问题只用于提示和人工复核，不会自动删库、改分或删除证据。",
        *(f"- {item['severity']} / {item['code']}：{item['message']}" for item in quality["issues"][:5]),
        "",
    ]
    if not rows:
        lines.extend(["## 暂无待处理商品", "", "当前数据库没有可报告的候选或人工复核商品。"])
    for index, row in enumerate(rows, start=1):
        reasons = _safe_json_list(row.get("reasons_json"))
        analysis = analyze_candidate(row, reasons)
        assessment_status = row.get("assessment_status")
        assessment_label = (
            "人工复核（needs_review）"
            if assessment_status == "needs_review"
            else "候选（candidate）"
        )
        search_is_invalid = row.get("search_evidence_valid") in (0, "0", False)
        search_status = (
            f"已失效，不作为当前归属（{_fmt(row.get('search_invalid_reason'))}）"
            if search_is_invalid
            else "有效"
            if row.get("search_source_keyword")
            else "未建立"
        )
        lines.extend(
            [
                f"## {index}. {_fmt(row.get('title'))}",
                "",
                f"- 店铺：{_fmt(row.get('shop_name'))}",
                f"- 价格：{_fmt(row.get('price'))}",
                f"- 商品原链接：{_fmt(row.get('share_url'))}",
                f"- 证据等级：{_fmt(row.get('evidence_grade'))}",
                f"- 候选分：{_fmt(row.get('score'))}",
                f"- 当前评估状态：{assessment_label}",
                f"- 采集时间：{_fmt(row.get('observed_at'))}",
                f"- 证据截图：{_fmt(row.get('screenshot_path'))}",
                f"- 最新搜索证据状态：{search_status}",
                f"- 搜索来源记录：{_fmt(row.get('search_source_keyword'))} / 第 {_fmt(row.get('search_result_rank'))} 位",
                f"- 搜索页证据：{_fmt(row.get('search_probe_dir'))}",
                f"- 分析标签：{'、'.join(analysis['tags'])}",
                "",
                "### 事实证据",
                *(f"- {fact}" for fact in analysis["facts"]),
                "",
                "### 趋势指标",
                *_metric_lines(row),
                "",
                "### 推断",
                *(f"- {inference}" for inference in analysis["inferences"]),
                "",
                "### 入选理由",
                *(f"- {reason}" for reason in (analysis["selection_reasons"] or ["暂无结构化入选理由"])),
                "",
                "### 风险点",
                *(f"- {risk}" for risk in analysis["risks"]),
                "",
                "### 证据缺口",
                *(f"- {gap}" for gap in analysis["gaps"]),
                "",
                "### 置信度",
                f"- {analysis['confidence']['summary']}",
                "",
                "### 原创化改写方向",
                *(f"- {direction}" for direction in analysis["originality_directions"]),
                "",
                "### 低粉账号/笔记证据",
                (
                    "- 已有关联低粉证据，可进入人工复核。"
                    if row.get("low_follower_verified")
                    else (
                        f"- 已采集公开笔记/账号观察 {row.get('note_observation_count')} 条；粉丝数、单条笔记互动和发布时间未闭环前不能按 A 级处理。"
                        if row.get("note_observation_count")
                        else "- 暂未验证低粉账号/笔记证据，不能按 A 级处理。"
                    )
                ),
                (
                    f"- 单条公开笔记：作者 {_fmt(row.get('latest_note_author_name'))}，点赞 {_fmt(row.get('latest_note_likes'))}，收藏 {_fmt(row.get('latest_note_collects'))}，评论 {_fmt(row.get('latest_note_comments'))}，发布距今 {_fmt(row.get('latest_note_published_days_ago'))} 天，证据 {_fmt(row.get('latest_note_probe_dir'))}。"
                    if row.get("latest_note_author_name") or row.get("latest_note_likes") is not None
                    else "- 尚未采到可解析的单条公开笔记互动。"
                ),
                (
                    f"- 公开账号主页：作者 {_fmt(row.get('latest_profile_author_name'))}，粉丝 {_fmt(row.get('latest_profile_follower_count'))}，账号累计获赞与收藏 {_fmt(row.get('latest_profile_total_likes'))}，证据 {_fmt(row.get('latest_profile_probe_dir'))}。"
                    if row.get("latest_profile_author_name") or row.get("latest_profile_follower_count") is not None
                    else "- 尚未采到可解析的公开账号粉丝数。"
                ),
                "",
            ]
        )

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "report_path": str(output_path),
        "candidate_count": len(rows),
        "active_candidate_count": candidate_count,
        "needs_review_count": needs_review_count,
        "quality_issue_count": quality["summary"]["issue_count"],
        "digest_alert_count": digest["stats"]["alerts"],
    }
