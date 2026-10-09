from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import uvicorn

from .config import Settings
from .db import (
    RiskConfirmationError,
    RiskStopActiveError,
    connect,
    dashboard_stats,
    enqueue,
    get_monitor_state,
    resume_monitor_after_risk,
    set_monitor_desired_state,
    set_monitor_state,
)
from .detail_metrics import (
    DEFAULT_FOCUS_TAPS,
    DEFAULT_ROI,
    DEFAULT_SWIPE_MS,
    DEFAULT_SWIPE_PIXELS,
    capture_metrics_strip,
    has_metrics,
    update_observation_with_metrics,
)
from .emulator import AdbDevice, discover_adb
from .ingest import ingest_image
from .monitor import MonitorLimits, monitor_loop, monitor_once
from .note_observation import open_note_author_profile_once, open_related_note_once
from .probe import probe_current_page
from .reports import generate_candidate_report
from .workflow import capture_current_page_for_task, capture_next_current_detail


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="xhs-scout", description="小红书虚拟商品选品 Agent")
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="初始化数据库和目录")

    enqueue_parser = sub.add_parser("enqueue", help="加入搜索关键词")
    enqueue_parser.add_argument("keywords", nargs="+")
    seed_parser = sub.add_parser("seed", help="导入首批监控关键词")
    seed_parser.add_argument("--file", type=Path, default=Path("config/seed_keywords.txt"))

    ingest_parser = sub.add_parser("ingest-images", help="识别手机或虚拟机截图")
    ingest_parser.add_argument("images", nargs="+", type=Path)

    sub.add_parser("status", help="查看数据库状态")

    adb_parser = sub.add_parser("adb-status", help="检查虚拟机 ADB")
    adb_parser.add_argument("--adb")
    adb_parser.add_argument("--serial")
    sub.add_parser("capture-once", help="采集并识别虚拟机当前画面")
    sub.add_parser("probe-current-page", help="只读探测当前小红书页面状态，不点击不输入")
    note = sub.add_parser("open-related-note", help="从当前商品详情页打开一条公开相关笔记并记录观察")
    note.add_argument("--product-id", type=int)
    note.add_argument("--rank", type=int, default=1)
    note.add_argument("--wait-seconds", type=float, default=6.0)
    note.add_argument("--max-scrolls", type=int, default=3)
    note.add_argument("--dry-run", action="store_true")
    author = sub.add_parser("open-note-author", help="从当前公开笔记详情页打开作者主页并记录账号观察")
    author.add_argument("--product-id", type=int)
    author.add_argument("--wait-seconds", type=float, default=6.0)
    author.add_argument("--dry-run", action="store_true")
    capture_task = sub.add_parser("capture-task", help="把当前商品详情页采集到指定搜索任务")
    capture_task.add_argument("--task-id", type=int, required=True)
    capture_task.add_argument("--metrics-strip", action="store_true", help="采集当前详情页后自动预览灰色指标条")
    capture_task.add_argument("--metrics-swipe", action="store_true", help="确认安全后对灰色指标条做一次低频横滑")
    capture_task.add_argument("--metrics-roi", nargs=4, type=int, metavar=("X1", "Y1", "X2", "Y2"))
    capture_task.add_argument("--metrics-max-frames", type=int, default=3)
    capture_task.add_argument("--require-keyword-match", action="store_true", help="当前页必须出现任务关键词才关联任务结果")
    pilot = sub.add_parser("pilot-current-detail", help="只处理当前商品详情页的受控小闭环，不自动搜索")
    pilot.add_argument("--metrics-swipe", action="store_true", help="确认安全后对灰色指标条做一次低频横滑")
    pilot.add_argument("--metrics-max-frames", type=int, default=3)
    pilot.add_argument("--allow-keyword-mismatch", action="store_true", help="允许当前页未出现任务关键词时仍关联任务")
    strip = sub.add_parser("capture-metrics-strip", help="横向滑动采集商品详情页灰色指标条")
    strip.add_argument("--observation-id", type=int)
    strip.add_argument("--roi", nargs=4, type=int, metavar=("X1", "Y1", "X2", "Y2"))
    strip.add_argument("--max-frames", type=int, default=5)
    strip.add_argument("--swipe", action="store_true", help="确认 ROI 后才执行横向滑动")
    strip.add_argument("--focus-taps", type=int, default=DEFAULT_FOCUS_TAPS, help="每次滑动前在 ROI 中心轻点次数")
    strip.add_argument("--swipe-pixels", type=int, default=DEFAULT_SWIPE_PIXELS, help="限制横向滑动像素，避免拖动外层页面")
    strip.add_argument("--swipe-ms", type=int, default=DEFAULT_SWIPE_MS, help="横向滑动持续时间毫秒")

    serve = sub.add_parser("serve", help="启动本地工作台")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8793, type=int)
    serve.add_argument("--project-root", type=Path)
    report = sub.add_parser("report-candidates", help="生成候选商品分析报告")
    report.add_argument("--limit", type=int, default=10)
    report.add_argument("--output", type=Path)
    monitor_once_parser = sub.add_parser("monitor-once", help="执行一轮受控自动监控")
    monitor_once_parser.add_argument("--max-keywords", type=int, default=1)
    monitor_once_parser.add_argument("--max-products-per-keyword", type=int, default=1)
    monitor_once_parser.add_argument("--wait-seconds", type=float, default=5.0)
    monitor_once_parser.add_argument("--metrics-max-frames", type=int, default=5)
    monitor_once_parser.add_argument("--no-metrics-swipe", action="store_true")
    monitor_once_parser.add_argument("--note-evidence", action="store_true", help="采集商品详情页公开相关笔记与作者主页证据")
    monitor_once_parser.add_argument("--note-rank", type=int, default=1)
    monitor_once_parser.add_argument("--note-max-scrolls", type=int, default=3)
    monitor_once_parser.add_argument("--recurring-interval-hours", type=int, default=24)
    monitor_once_parser.add_argument("--dry-run", action="store_true")
    monitor_once_parser.add_argument("--ignore-paused", action="store_true")
    monitor_loop_parser = sub.add_parser("monitor-loop", help="启动受控循环监控")
    monitor_loop_parser.add_argument("--interval-seconds", type=int, default=900)
    monitor_loop_parser.add_argument("--max-rounds", type=int)
    monitor_loop_parser.add_argument("--max-keywords", type=int, default=1)
    monitor_loop_parser.add_argument("--max-products-per-keyword", type=int, default=1)
    monitor_loop_parser.add_argument("--wait-seconds", type=float, default=5.0)
    monitor_loop_parser.add_argument("--metrics-max-frames", type=int, default=5)
    monitor_loop_parser.add_argument("--no-metrics-swipe", action="store_true")
    monitor_loop_parser.add_argument("--note-evidence", action="store_true", help="采集商品详情页公开相关笔记与作者主页证据")
    monitor_loop_parser.add_argument("--note-rank", type=int, default=1)
    monitor_loop_parser.add_argument("--note-max-scrolls", type=int, default=3)
    monitor_loop_parser.add_argument("--recurring-interval-hours", type=int, default=24)
    sub.add_parser("monitor-state", help="查看监控状态")
    sub.add_parser("monitor-pause", help="暂停监控")
    monitor_resume_parser = sub.add_parser(
        "monitor-resume",
        help="恢复普通暂停；解除硬风控时必须显式提交当前风险原因",
    )
    monitor_resume_parser.add_argument(
        "--confirm-risk",
        metavar="CURRENT_RISK_REASON",
        help="显式确认并提交当前风险停止原因，以解除硬风控后恢复",
    )
    return result


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parser().parse_args()
    settings = Settings.load(getattr(args, "project_root", None))
    if args.command == "init":
        with connect(settings.db_path):
            pass
        print(f"已初始化：{settings.db_path}")
    elif args.command == "enqueue":
        with connect(settings.db_path) as conn:
            count = enqueue(conn, args.keywords)
        print(f"已加入 {count} 个搜索任务")
    elif args.command == "seed":
        keywords = [
            line.strip()
            for line in args.file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        with connect(settings.db_path) as conn:
            count = enqueue(conn, keywords, source="seed_workbook")
        print(f"已从关键词库加入 {count} 个搜索任务")
    elif args.command == "ingest-images":
        outputs = [ingest_image(settings, path) for path in args.images]
        print(json.dumps(outputs, ensure_ascii=False, indent=2))
    elif args.command == "status":
        with connect(settings.db_path) as conn:
            print(json.dumps(dashboard_stats(conn), ensure_ascii=False, indent=2))
    elif args.command == "adb-status":
        adb = discover_adb(args.adb)
        print(AdbDevice(adb=adb, serial=args.serial).devices())
    elif args.command == "capture-once":
        config = settings.emulator_config()
        adb = discover_adb(config.get("adb_path"))
        device = AdbDevice(adb=adb, serial=config.get("serial"))
        screenshot = device.screenshot(settings.data_dir / "emulator-current.png")
        output = ingest_image(settings, screenshot, source="android_emulator")
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.command == "probe-current-page":
        config = settings.emulator_config()
        adb = discover_adb(config.get("adb_path"))
        device = AdbDevice(adb=adb, serial=config.get("serial"))
        output = probe_current_page(settings, device)
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.command == "open-related-note":
        config = settings.emulator_config()
        adb = discover_adb(config.get("adb_path"))
        device = AdbDevice(adb=adb, serial=config.get("serial"))
        output = open_related_note_once(
            settings,
            device,
            product_id=args.product_id,
            rank=args.rank,
            wait_seconds=args.wait_seconds,
            max_scrolls=args.max_scrolls,
            dry_run=args.dry_run,
        )
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.command == "open-note-author":
        config = settings.emulator_config()
        adb = discover_adb(config.get("adb_path"))
        device = AdbDevice(adb=adb, serial=config.get("serial"))
        output = open_note_author_profile_once(
            settings,
            device,
            product_id=args.product_id,
            wait_seconds=args.wait_seconds,
            dry_run=args.dry_run,
        )
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.command == "capture-task":
        config = settings.emulator_config()
        adb = discover_adb(config.get("adb_path"))
        device = AdbDevice(adb=adb, serial=config.get("serial"))
        output = capture_current_page_for_task(
            settings,
            device,
            args.task_id,
            capture_metrics=args.metrics_strip or args.metrics_swipe,
            metrics_roi=tuple(args.metrics_roi) if args.metrics_roi else None,
            metrics_swipe=args.metrics_swipe,
            metrics_max_frames=args.metrics_max_frames,
            require_keyword_match=args.require_keyword_match,
        )
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.command == "pilot-current-detail":
        config = settings.emulator_config()
        adb = discover_adb(config.get("adb_path"))
        device = AdbDevice(adb=adb, serial=config.get("serial"))
        output = capture_next_current_detail(
            settings,
            device,
            capture_metrics=True,
            metrics_swipe=args.metrics_swipe,
            metrics_max_frames=args.metrics_max_frames,
            require_keyword_match=not args.allow_keyword_mismatch,
        )
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.command == "capture-metrics-strip":
        config = settings.emulator_config()
        adb = discover_adb(config.get("adb_path"))
        device = AdbDevice(adb=adb, serial=config.get("serial"))
        output = capture_metrics_strip(
            settings,
            device,
            roi=tuple(args.roi) if args.roi else None,
            max_frames=args.max_frames,
            allow_swipe=args.swipe,
            focus_taps=args.focus_taps,
            swipe_pixels=args.swipe_pixels,
            swipe_ms=args.swipe_ms,
        )
        if args.observation_id and has_metrics(output["signals"]):
            output["updated_observation"] = update_observation_with_metrics(
                settings,
                args.observation_id,
                output,
            )
        elif args.observation_id:
            output["updated_observation"] = None
            output["skip_update_reason"] = "指标条 ROI 未识别出可合并指标"
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.command == "serve":
        from .web import create_app

        uvicorn.run(create_app(settings), host=args.host, port=args.port, reload=False)
    elif args.command == "report-candidates":
        output = generate_candidate_report(settings, output_path=args.output, limit=args.limit)
        with connect(settings.db_path) as conn:
            set_monitor_state(conn, "last_report_path", output["report_path"])
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.command == "monitor-once":
        limits = MonitorLimits(
            max_keywords=args.max_keywords,
            max_products_per_keyword=args.max_products_per_keyword,
            wait_seconds=args.wait_seconds,
            metrics_swipe=not args.no_metrics_swipe,
            metrics_max_frames=args.metrics_max_frames,
            note_evidence=args.note_evidence,
            note_rank=args.note_rank,
            note_max_scrolls=args.note_max_scrolls,
            recurring_interval_hours=args.recurring_interval_hours,
            dry_run=args.dry_run,
        )
        output = monitor_once(settings, limits=limits, ignore_paused=args.ignore_paused)
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.command == "monitor-loop":
        limits = MonitorLimits(
            max_keywords=args.max_keywords,
            max_products_per_keyword=args.max_products_per_keyword,
            wait_seconds=args.wait_seconds,
            metrics_swipe=not args.no_metrics_swipe,
            metrics_max_frames=args.metrics_max_frames,
            note_evidence=args.note_evidence,
            note_rank=args.note_rank,
            note_max_scrolls=args.note_max_scrolls,
            recurring_interval_hours=args.recurring_interval_hours,
        )
        output = monitor_loop(
            settings,
            limits=limits,
            interval_seconds=args.interval_seconds,
            max_rounds=args.max_rounds,
        )
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.command == "monitor-state":
        with connect(settings.db_path) as conn:
            print(json.dumps(get_monitor_state(conn), ensure_ascii=False, indent=2))
    elif args.command == "monitor-pause":
        with connect(settings.db_path) as conn:
            set_monitor_desired_state(conn, "paused")
        print(json.dumps({"desired_state": "paused"}, ensure_ascii=False, indent=2))
    elif args.command == "monitor-resume":
        with connect(settings.db_path) as conn:
            try:
                if args.confirm_risk is None:
                    set_monitor_desired_state(conn, "running")
                    state = get_monitor_state(conn)
                else:
                    state = resume_monitor_after_risk(
                        conn,
                        confirm_risk_reason=args.confirm_risk,
                        actor="cli",
                    )
            except (RiskStopActiveError, RiskConfirmationError) as exc:
                raise SystemExit(str(exc)) from exc
        print(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
