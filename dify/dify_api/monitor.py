"""面向无人值守任务的 Flow 失败运行检查。"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import Lock

from .client import (
    list_all_chat_conversations_in_range,
    list_workflow_logs,
)
from .flow_groups import load_flow_groups
from .markdown import print_table
from .progress import format_progress
from .settings import (
    CHAT_APP_MODES,
    MONITOR_PAGE_LIMIT,
    MONITOR_TIMEZONE,
    TOKEN_STATS_WORKERS,
)


def collect_app_failure_stats(
    headers: dict,
    apps: list[dict],
    start: datetime,
    end: datetime,
) -> list[dict]:
    """统计应用的总 Run 和失败 Run，并标记数据是否完整。"""
    stats_by_app: dict[str, dict] = {}
    progress_lock = Lock()
    total_apps = len(apps)
    print(
        f"正在并行检查 {total_apps} 个应用的失败 Run "
        f"(并发 {TOKEN_STATS_WORKERS}，每页 {MONITOR_PAGE_LIMIT})..."
    )

    def parse_count(value: object) -> int:
        count = int(value)
        if count < 0:
            raise ValueError("count cannot be negative")
        return count

    def summarize_chat_runs(
        conversations: list[dict],
    ) -> tuple[int, int, bool]:
        total_runs = 0
        failed = 0
        complete = True
        for conversation in conversations:
            status_count = conversation.get("status_count")
            if status_count is None or status_count == {}:
                # 部分 Dify 部署不返回状态明细；会话存在至少能证明有运行。
                total_runs += 1
                continue
            if not isinstance(status_count, dict):
                total_runs += 1
                complete = False
                continue
            try:
                failed += parse_count(status_count.get("failed", 0))
                if "total" in status_count:
                    conversation_runs = parse_count(status_count["total"])
                else:
                    conversation_runs = sum(
                        parse_count(value) for value in status_count.values()
                    )
                total_runs += max(1, conversation_runs)
            except (TypeError, ValueError):
                complete = False
        return total_runs, failed, complete

    def load_failure_count(app: dict) -> tuple[dict, int, int, bool]:
        app_id = app["app_id"]
        app_name = app.get("name") or app_id
        mode = app.get("mode") or "workflow"
        if mode in CHAT_APP_MODES:
            def show_page_progress(
                page: int, total_pages: int, loaded: int, total: int
            ) -> None:
                with progress_lock:
                    print(
                        f"  {format_progress(loaded, total)} · "
                        f"[{app_name}] 第 {page}/{total_pages} 页"
                    )

            conversations, complete = list_all_chat_conversations_in_range(
                dict(headers),
                app_id,
                start,
                end,
                limit=MONITOR_PAGE_LIMIT,
                progress_callback=show_page_progress,
            )
            total_runs, failed, counts_complete = summarize_chat_runs(
                conversations
            )
            return app, total_runs, failed, complete and counts_complete

        query_args = {
            "app_id": app_id,
            "page": 1,
            "limit": MONITOR_PAGE_LIMIT,
            "created_at_after": start.isoformat(timespec="seconds"),
            "created_at_before": end.isoformat(timespec="seconds"),
        }
        _, total_data = list_workflow_logs(
            dict(headers),
            **query_args,
            detail=False,
        )
        if total_data is None or "total" not in total_data:
            return app, 0, 0, False
        try:
            total_runs = parse_count(total_data["total"])
        except (TypeError, ValueError):
            return app, 0, 0, False
        if total_runs == 0:
            return app, 0, 0, True

        _, failed_data = list_workflow_logs(
            dict(headers),
            **query_args,
            detail=False,
            status="failed",
        )
        if failed_data is None or "total" not in failed_data:
            return app, total_runs, 0, False
        try:
            failed = parse_count(failed_data["total"])
        except (TypeError, ValueError):
            return app, total_runs, 0, False
        return app, total_runs, failed, True

    with ThreadPoolExecutor(max_workers=TOKEN_STATS_WORKERS) as pool:
        futures = {pool.submit(load_failure_count, app): app for app in apps}
        for done, future in enumerate(as_completed(futures), start=1):
            app = futures[future]
            app_id = app["app_id"]
            try:
                _, total_runs, failed, complete = future.result()
            except Exception:
                total_runs, failed, complete = 0, 0, False
            stats = {
                "app_id": app_id,
                "group_name": app["group_name"],
                "name": app.get("name") or app_id,
                "mode": app.get("mode") or "workflow",
                "total_runs": total_runs,
                "failed": failed,
                "complete": complete,
            }
            stats_by_app[app_id] = stats
            if not complete:
                state = "数据不完整"
            elif total_runs == 0:
                state = "无运行"
            elif failed:
                state = f"运行 {total_runs}，失败 {failed}"
            else:
                state = f"运行 {total_runs}，全部成功"
            with progress_lock:
                print(
                    f"  {format_progress(done, total_apps)} · "
                    f"{stats['name']}：{state}"
                )

    return [stats_by_app[app["app_id"]] for app in apps]


def print_group_failure_report(
    headers: dict,
    group_names: list[str],
    now: datetime | None = None,
) -> bool:
    """输出当日失败运行检查报告；返回是否发现失败。"""
    now = now or datetime.now(MONITOR_TIMEZONE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=MONITOR_TIMEZONE)
    else:
        now = now.astimezone(MONITOR_TIMEZONE)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    groups = load_flow_groups()
    selected_groups = []
    apps = []
    for group_name in group_names:
        group = groups.get(group_name)
        if group is None:
            raise RuntimeError(f"Flow 组不存在: {group_name}")
        display_name = group.get("display_name") or group_name
        selected_groups.append((group_name, display_name))
        apps.extend(
            {
                **app,
                "group_name": group_name,
            }
            for app in group["apps"]
        )

    stats = collect_app_failure_stats(headers, apps, start, now)
    stats_by_group = {group_name: [] for group_name, _ in selected_groups}
    for item in stats:
        stats_by_group[item["group_name"]].append(item)

    print("## Dify 失败运行检查\n")
    print(
        f"- **检查时间：** {now.strftime('%Y-%m-%d %H:%M:%S')}（北京时间）"
    )
    print(
        f"- **检查范围：** {start.strftime('%Y-%m-%d %H:%M:%S')} 至 "
        f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    print(
        f"- **检查分组：** "
        f"{'、'.join(display_name for _, display_name in selected_groups)}\n"
    )

    summary_rows = []
    incomplete_apps = 0
    total_runs = 0
    total_failed = 0
    failed_rows = []
    no_run_rows = []
    display_names = dict(selected_groups)
    for group_name, display_name in selected_groups:
        group_stats = stats_by_group[group_name]
        runs = sum(item["total_runs"] for item in group_stats)
        failed = sum(item["failed"] for item in group_stats)
        incomplete = sum(not item["complete"] for item in group_stats)
        no_run = sum(
            item["complete"] and item["total_runs"] == 0
            for item in group_stats
        )
        incomplete_apps += incomplete
        total_runs += runs
        total_failed += failed
        if not group_stats:
            state = "无应用"
        elif incomplete:
            state = "数据不完整 *"
        elif failed:
            state = "存在失败"
        elif group_stats and no_run == len(group_stats):
            state = "无运行"
        elif no_run:
            state = "部分无运行"
        else:
            state = "全部成功"
        summary_rows.append([
            display_name,
            len(group_stats),
            runs,
            failed,
            state,
        ])
        failed_rows.extend(
            [
                display_names[item["group_name"]],
                item["name"],
                item["mode"],
                item["failed"],
            ]
            for item in group_stats
            if item["failed"]
        )
        no_run_rows.extend(
            [
                display_names[item["group_name"]],
                item["name"],
                item["mode"],
            ]
            for item in group_stats
            if item["complete"] and item["total_runs"] == 0
        )

    print_table(
        ["分组", "检查应用", "总 Run", "失败 Run", "状态"],
        summary_rows,
        ["left", "right", "right", "right", "center"],
    )
    if failed_rows:
        print("### 失败应用\n")
        print_table(
            ["分组", "应用", "类型", "失败次数"],
            failed_rows,
            ["left", "left", "center", "right"],
        )
    if no_run_rows:
        print("### 无运行应用\n")
        print_table(
            ["分组", "应用", "类型"],
            no_run_rows,
            ["left", "left", "center"],
        )
    if total_failed:
        print(
            f"### 结论\n\n共 **{total_runs}** 次运行，发现 "
            f"**{total_failed}** 次失败，请及时检查。\n"
        )
    elif total_runs:
        print(
            f"### 结论\n\n共 **{total_runs}** 次运行，未发现失败运行。\n"
        )
    elif incomplete_apps:
        print(
            "### 结论\n\n未获取到可确认的 Run，且部分应用数据不完整。\n"
        )
    else:
        print("### 结论\n\n检查时段内没有发现 Run。\n")
    if no_run_rows:
        print(
            f"> 有 {len(no_run_rows)} 个应用在检查时段内没有 Run。\n"
        )
    if incomplete_apps:
        print(f"> `*` 有 {incomplete_apps} 个应用的数据未完整获取。\n")
    return total_failed > 0
