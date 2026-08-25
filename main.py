# -*- coding: utf-8 -*-
"""
AI 项目信息收集平台 - 主入口

用法:
  python main.py --once          立即执行一次「抓取 -> 翻译 -> 分类 -> 事件合并 -> 日报+周报」
  python main.py --loop          常驻运行：启动时先跑一次，之后每天 08:30 自动执行
  python main.py --once --open   执行完成后用默认浏览器打开报告
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta

# 保证 Windows 控制台输出中文不乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import cluster
import classifier
import collector
import report
import storage
import config


def _render(date_str):
    """基于库内当日数据完成：事件合并 -> 综述 -> 日报/周报。返回日报路径。"""
    all_items = storage.load_items(date_str)

    # 补全 summary_final（DB 仅存了 summary 列），翻译翻译成中文标题/摘要。
    # --report-only 跳过 process()，在此补足翻译；结果同步回 summary 并落库，
    # 以免每次重建报告都重复调用翻译接口。
    for it in all_items:
        it.setdefault("summary_final", it.get("summary", ""))
    try:
        import translator
        n_tr = translator.translate_items(all_items, max_texts=config.TRANSLATE_MAX_PER_RUN)
        if n_tr:
            for it in all_items:
                if it.get("summary_final"):
                    it["summary"] = it["summary_final"]
            storage.save_items(all_items, date_str)
            print(f"  翻译英文条目 {n_tr} 条（已落库）")
    except Exception as e:
        print(f"    [提示] 翻译环节跳过: {e}")

    # 事件合并：同一事件的多家报道挂到热度最高的主条目上
    merged_groups = cluster.merge_related(all_items)
    # 离线术语本地化：把 image-text-to-text 等英文技术词替换为中文，
    # 即便翻译后端不可用也能缓解中英文混用（幂等，不影响已翻译内容）。
    try:
        import translator
        for it in all_items:
            if it.get("summary"):
                it["summary"] = translator.localize_terms(it["summary"])
            if it.get("title"):
                it["title"] = translator.localize_terms(it["title"])
    except Exception:
        pass
    # 为每条目提炼一句话亮点（优势/评测超越/参数量等），用于卡片补充说明
    try:
        classifier.build_highlights(all_items)
    except Exception:
        pass
    stats = classifier.stats_of(all_items)
    db_total = storage.global_stats()["total_items"]
    print(f"  当日共 {len(all_items)} 条（合并 {merged_groups} 组重复报道），库内累计 {db_total} 条")

    # 今日综述：配置 LLM 则生成编辑导读，否则回退热词展示
    brief = classifier.llm_daily_brief(all_items[:20])
    hot = None
    if brief:
        print("  已生成 LLM 今日综述")
    else:
        hot = classifier.hot_words(all_items)
        print(f"  未配置 LLM，使用热词模式（{len(hot)} 个热词）")

    alerts = storage.get_source_alerts(config.SOURCE_FAIL_ALERT_STREAK)
    daily_path, index_path = report.write_reports(
        date_str, all_items, stats, db_total,
        brief=brief, hot_words=hot,
        merged_groups=merged_groups, source_alerts=alerts)
    print(f"  日报: {daily_path}")
    print(f"  索引: {index_path}")

    start_date = (datetime.strptime(date_str, "%Y-%m-%d")
                  - timedelta(days=config.WEEKLY_WINDOW_DAYS - 1)).strftime("%Y-%m-%d")
    week_items = storage.load_range(start_date, date_str)
    counts = storage.daily_counts(start_date, date_str)
    gains = storage.gh_weekly_gains(start_date, date_str, config.WEEKLY_GH_GAIN_TOP)
    weekly_path = report.write_weekly(start_date, date_str, counts, week_items, gains)
    print(f"  周报: {weekly_path}（窗口内 {len(week_items)} 条）")

    cat_line = "  ".join(f"{config.CATEGORIES[k]['emoji']}{config.CATEGORIES[k]['name']}:{v}"
                         for k, v in stats["by_category"].items() if v)
    print(f"  分布: {cat_line}")
    if alerts:
        print(f"  [警告] 数据源异常: " + ", ".join(
            f"{n}（连续失败 {d} 天" + (f"：{r[:80]}" if r else "") + "）"
            for n, d, r in alerts))
    return daily_path


def run_job():
    """完整执行一轮：抓取 -> 健康记录 -> 翻译/分类/评分 -> 入库 -> 渲染。"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"\n===== AI 情报站任务开始  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====")
    storage.init_db()

    # 1. 抓取（逐源记录健康状态）
    print("[1/6] 抓取数据源 ...")
    raw_items, statuses = collector.collect_all()
    storage.update_source_health(statuses, date_str)
    if not raw_items:
        print("  [警告] 所有数据源均失败，本次跳过。")

    # GitHub 日增星：先对比昨日快照，再随本次入库写入新快照
    deltas = storage.get_star_deltas(raw_items, date_str)
    for it in raw_items:
        gain = deltas.get(it["url"])
        if gain:
            it.setdefault("metrics", {})["stars_gain"] = gain

    # 2. 分类 / 打分 / 摘要 / 翻译 /（可选）LLM 润色
    print("[2/6] 分类、评分、翻译与摘要 ...")
    items = classifier.process(raw_items)

    # 3. 入库（URL 去重，重复条目更新指标与评分）
    print("[3/6] 写入数据库 ...")
    new_cnt = storage.save_items(items, date_str)
    storage.write_star_snapshots(items, date_str)
    print(f"  新增 {new_cnt} 条")

    # 4-6. 渲染日报与周报
    print("[4/6] 事件合并与统计 ...")
    print("[5/6] 今日综述 ...")
    print("[6/6] 生成 HTML 日报与周报 ...")
    daily_path = _render(date_str)

    failed_now = [s["name"] for s in statuses if not s["ok"]]
    if failed_now:
        print(f"  [提示] 本轮失败的源: {'、'.join(failed_now)}")
    print("===== 任务完成 =====\n")
    return daily_path


def seconds_until(hour_minute):
    """距离下一个指定时刻的秒数。"""
    hh, mm = map(int, hour_minute.split(":"))
    now = datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def loop():
    """常驻模式：立即跑一次，然后每天 DAILY_RUN_TIME 定时执行。"""
    print(f"进入常驻模式：每天 {config.DAILY_RUN_TIME} 自动执行（Ctrl+C 退出）")
    run_job()
    while True:
        wait = seconds_until(config.DAILY_RUN_TIME)
        next_t = datetime.now() + timedelta(seconds=wait)
        print(f"下次运行: {next_t.strftime('%Y-%m-%d %H:%M')} （{wait / 3600:.1f} 小时后），休眠中 ...")
        try:
            time.sleep(wait)
        except KeyboardInterrupt:
            print("已手动停止。")
            return
        try:
            run_job()
        except Exception as e:
            print(f"[错误] 本轮任务异常: {e}")


def main():
    parser = argparse.ArgumentParser(description="AI 项目信息收集平台")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="立即执行一次并退出")
    group.add_argument("--loop", action="store_true", help="常驻模式，每天定时执行")
    group.add_argument("--report-only", action="store_true",
                       help="不抓取，仅基于当日库内数据重建日报/周报（用于翻译或清洗后重建）")
    parser.add_argument("--open", action="store_true", help="完成后用浏览器打开报告")
    args = parser.parse_args()

    for d in (config.DATA_DIR, config.REPORT_DIR):
        os.makedirs(d, exist_ok=True)

    path = None
    if args.report_only:
        date_str = datetime.now().strftime("%Y-%m-%d")
        print(f"\n===== 仅重建报告（基于库内 {date_str} 数据）=====")
        storage.init_db()
        path = _render(date_str)
        print("===== 重建完成 =====\n")
    elif args.once:
        path = run_job()

    if args.loop:
        loop()
    elif args.open and path and os.path.exists(path):
        import webbrowser
        webbrowser.open(f"file://{path.replace(os.sep, '/')}")


if __name__ == "__main__":
    main()
