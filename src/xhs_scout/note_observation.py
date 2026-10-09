from __future__ import annotations

import re
from pathlib import Path

from .config import Settings
from .db import connect, record_note_observation, record_run_event
from .emulator import AdbDevice
from .low_follower import promote_candidate_from_note_observations
from .probe import is_ocr_timeout_probe, probe_current_page
from .signals import detect_risk_stop
from .ui_automation import find_note_author_entry, find_related_note_cards


def _read_ui(probe: dict) -> str:
    probe_dir = Path(probe["probe_dir"])
    xml_path = probe_dir / "window.xml"
    if not xml_path.exists():
        return ""
    return xml_path.read_text(encoding="utf-8", errors="replace")


def _parse_count(raw: str) -> int:
    raw = raw.replace(",", "").strip()
    match = re.search(r"(\d+(?:\.\d+)?)(万)?", raw)
    if not match:
        return 0
    value = float(match.group(1))
    if match.group(2) == "万":
        value *= 10_000
    return int(value)


def parse_note_text(text: str) -> dict:
    compact = re.sub(r"\s+", "", text or "")
    result: dict = {
        "author_name": None,
        "follower_count": None,
        "likes": None,
        "collects": None,
        "comments": None,
        "published_days_ago": None,
    }
    follower = re.search(r"粉丝[:：]?(\d+(?:\.\d+)?万?)", compact)
    if not follower:
        follower = re.search(r"(\d+(?:\.\d+)?万?)粉丝", compact)
    if follower:
        result["follower_count"] = _parse_count(follower.group(1))

    for key, patterns in {
        "likes": (r"点赞[:：]?(\d+(?:\.\d+)?万?)", r"获赞[:：]?(\d+(?:\.\d+)?万?)"),
        "collects": (r"收藏[:：]?(\d+(?:\.\d+)?万?)",),
        "comments": (r"评论[:：]?(\d+(?:\.\d+)?万?)",),
    }.items():
        for pattern in patterns:
            match = re.search(pattern, compact)
            if match:
                result[key] = _parse_count(match.group(1))
                break

    days = re.search(r"(\d+)天前", compact)
    if days:
        result["published_days_ago"] = int(days.group(1))
    elif months := re.search(r"(\d+)个月前", compact):
        result["published_days_ago"] = int(months.group(1)) * 30
    elif "昨天" in compact:
        result["published_days_ago"] = 1
    elif "今天" in compact or "刚刚" in compact:
        result["published_days_ago"] = 0

    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    ignored = {"关注", "赞", "收藏", "评论", "分享", "搜索"}
    if result["likes"] is None:
        for index, line in enumerate(lines):
            if "评论" in line and index > 0 and re.fullmatch(r"\d+(?:\.\d+)?万?", lines[index - 1]):
                result["likes"] = _parse_count(lines[index - 1])
                break
    for line in lines[:12]:
        if re.fullmatch(r"\d{1,2}:\d{2}", line):
            continue
        if line == "开箱精选":
            continue
        candidate = re.sub(r"商家$", "", line)
        if len(candidate) <= 20 and not any(token in candidate for token in ignored):
            result["author_name"] = candidate
            break
    return result


def parse_account_profile_text(text: str) -> dict:
    compact = re.sub(r"\s+", "", text or "")
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    result: dict = {
        "author_name": None,
        "follower_count": None,
        "likes": None,
        "collects": None,
        "comments": None,
        "published_days_ago": None,
    }
    follower = None
    follower_line_index = None
    for index, line in enumerate(lines):
        if "粉丝" not in line:
            continue
        follower = re.search(r"粉丝[:：]?\s*(\d+(?:\.\d+)?万?)", line)
        if not follower:
            follower = re.search(r"(\d+(?:\.\d+)?万?)\s*粉丝", line)
        if follower:
            follower_line_index = index
            break
    if not follower:
        compact_without_profile_id = re.sub(r"小红书号[:：]?[A-Za-z0-9_-]{4,24}", "", compact)
        follower = re.search(r"粉丝[:：]?(\d+(?:\.\d+)?万?)", compact_without_profile_id)
        if not follower:
            follower = re.search(r"(\d+(?:\.\d+)?万?)粉丝", compact_without_profile_id)
    if follower:
        result["follower_count"] = _parse_count(follower.group(1))

    liked = re.search(r"获赞(?:与收藏)?[:：]?(\d+(?:\.\d+)?万?)", compact)
    if liked:
        result["likes"] = _parse_count(liked.group(1))

    if result["follower_count"] is None and ("粉丝" in lines and any("获赞" in line for line in lines)):
        label_start = min(
            index
            for index, line in enumerate(lines)
            if line in {"关注", "粉丝", "获赞与收藏"} or "获赞" in line
        )
        stat_values = [
            line
            for line in lines[max(0, label_start - 8):label_start]
            if re.fullmatch(r"\d+(?:\.\d+)?万?", line)
        ]
        if len(stat_values) >= 3:
            result["follower_count"] = _parse_count(stat_values[-2])
            result["likes"] = _parse_count(stat_values[-1])

    ignored_markers = (
        "关注",
        "粉丝",
        "获赞",
        "收藏",
        "小红书号",
        "IP属地",
        "笔记",
        "商品",
        "赞过",
        "已售",
        "评分",
        "好评率",
        "平均",
        "客服",
        "综合",
        "销量",
        "新品",
        "价格",
        "首页",
        "分类",
        "上新",
    )

    def is_name_candidate(line: str) -> bool:
        if re.fullmatch(r"(?:上午|下午|晚上|凌晨|中午)?\s*\d{1,2}:\d{2}", line):
            return False
        if re.fullmatch(r"\d+(?:\.\d+)?%?", line):
            return False
        if re.fullmatch(r"[★☆⭐\s]+", line):
            return False
        return 1 <= len(line) <= 24 and not any(
            marker in line for marker in ignored_markers
        )

    # 店铺页的名称通常在“粉丝xxxx”上方，状态栏时间、电量、星级和已售量也在同一区域。
    # 从粉丝行向上找能避开这些噪声，同时仍兼容普通账号主页。
    if follower_line_index is not None:
        for line in reversed(lines[max(0, follower_line_index - 8):follower_line_index]):
            if is_name_candidate(line):
                result["author_name"] = line
                break
    if result["author_name"] is None:
        for line in lines[:16]:
            if is_name_candidate(line):
                result["author_name"] = line
                break
    return result


def open_related_note_once(
    settings: Settings,
    device: AdbDevice,
    *,
    product_id: int | None,
    rank: int = 1,
    wait_seconds: float = 6.0,
    max_scrolls: int = 3,
    dry_run: bool = False,
) -> dict:
    run_id = f"note-open-{rank}"
    before = probe_current_page(settings, device, run_id=f"{run_id}-before")
    if is_ocr_timeout_probe(before):
        return before
    if before.get("risk_stop_reason") or before.get("has_anr"):
        raise RuntimeError(before.get("risk_stop_reason") or "ANR detected before note open")
    if before.get("page_kind") != "product_detail":
        return {
            "skipped": True,
            "skip_reason": f"current page is not product_detail: {before.get('page_kind')}",
            "before_probe": before,
        }
    current_probe = before
    cards = []
    for attempt in range(max(0, max_scrolls) + 1):
        xml_text = _read_ui(current_probe)
        cards = find_related_note_cards(xml_text, limit=max(rank, 1))
        if cards or dry_run or attempt >= max_scrolls:
            break
        device.swipe(540, 1620, 540, 1040, 700)
        import time

        time.sleep(wait_seconds)
        current_probe = probe_current_page(settings, device, run_id=f"{run_id}-scroll-{attempt + 1}")
        if is_ocr_timeout_probe(current_probe):
            return current_probe
        if current_probe.get("risk_stop_reason") or current_probe.get("has_anr"):
            raise RuntimeError(current_probe.get("risk_stop_reason") or "ANR detected while searching note card")
        if current_probe.get("page_kind") != "product_detail":
            break
    if not cards or len(cards) < rank:
        return {
            "skipped": True,
            "skip_reason": "related note card not found",
            "before_probe": before,
            "last_probe": current_probe,
        }
    target = cards[rank - 1]
    output = {
        "dry_run": dry_run,
        "target": {
            "x": target.x,
            "y": target.y,
            "bounds": {
                "x1": target.bounds.x1,
                "y1": target.bounds.y1,
                "x2": target.bounds.x2,
                "y2": target.bounds.y2,
            },
            "label": target.label,
        },
        "before_probe": before,
        "target_probe": current_probe,
    }
    if dry_run:
        return output

    device.tap(target.x, target.y)
    import time

    time.sleep(wait_seconds)
    after = probe_current_page(settings, device, run_id=f"{run_id}-after")
    if is_ocr_timeout_probe(after):
        return after
    parsed = parse_note_text(after.get("text") or "")
    risk = detect_risk_stop(after.get("text") or "")
    with connect(settings.db_path) as conn:
        note_observation_id = record_note_observation(
            conn,
            product_id=product_id,
            source="related_note_card",
            screenshot_path=after.get("screenshot"),
            probe_dir=after.get("probe_dir"),
            page_kind=after.get("page_kind"),
            raw_text=after.get("text"),
            raw={"target": output["target"], "risk_stop_reason": risk},
            **parsed,
        )
        promotion = promote_candidate_from_note_observations(conn, product_id) if product_id else None
        record_run_event(
            conn,
            run_id=after["run_id"],
            phase="note_observation",
            event="note_observation_recorded",
            product_id=product_id,
            message=f"note_observation_id={note_observation_id}",
            data={"parsed": parsed, "probe": after, "promotion": promotion},
        )
    output["after_probe"] = after
    output["parsed"] = parsed
    output["note_observation_id"] = note_observation_id
    output["risk_stop_reason"] = risk
    output["promotion"] = promotion
    return output


def open_note_author_profile_once(
    settings: Settings,
    device: AdbDevice,
    *,
    product_id: int | None,
    wait_seconds: float = 6.0,
    dry_run: bool = False,
) -> dict:
    run_id = "note-author-profile"
    before = probe_current_page(settings, device, run_id=f"{run_id}-before")
    if is_ocr_timeout_probe(before):
        return before
    if before.get("risk_stop_reason") or before.get("has_anr"):
        raise RuntimeError(before.get("risk_stop_reason") or "ANR detected before author open")
    if before.get("page_kind") != "note_detail":
        return {
            "skipped": True,
            "skip_reason": f"current page is not note_detail: {before.get('page_kind')}",
            "before_probe": before,
        }
    xml_text = _read_ui(before)
    target = find_note_author_entry(xml_text)
    if not target:
        return {
            "skipped": True,
            "skip_reason": "note author entry not found",
            "before_probe": before,
        }
    output = {
        "dry_run": dry_run,
        "target": {
            "x": target.x,
            "y": target.y,
            "bounds": {
                "x1": target.bounds.x1,
                "y1": target.bounds.y1,
                "x2": target.bounds.x2,
                "y2": target.bounds.y2,
            },
            "label": target.label,
        },
        "before_probe": before,
    }
    if dry_run:
        return output

    device.tap(target.x, target.y)
    import time

    time.sleep(wait_seconds)
    after = probe_current_page(settings, device, run_id=f"{run_id}-after")
    if is_ocr_timeout_probe(after):
        return after
    parsed = parse_account_profile_text(after.get("text") or "")
    risk = detect_risk_stop(after.get("text") or "")
    with connect(settings.db_path) as conn:
        note_observation_id = record_note_observation(
            conn,
            product_id=product_id,
            source="author_profile_from_note",
            screenshot_path=after.get("screenshot"),
            probe_dir=after.get("probe_dir"),
            page_kind=after.get("page_kind"),
            raw_text=after.get("text"),
            raw={"target": output["target"], "risk_stop_reason": risk},
            **parsed,
        )
        record_run_event(
            conn,
            run_id=after["run_id"],
            phase="note_observation",
            event="author_profile_observation_recorded",
            product_id=product_id,
            message=f"note_observation_id={note_observation_id}",
            data={"parsed": parsed, "probe": after},
        )
    output["after_probe"] = after
    output["parsed"] = parsed
    output["note_observation_id"] = note_observation_id
    output["risk_stop_reason"] = risk
    return output
