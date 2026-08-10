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
    """通过服务端 status=failed 过滤统计应用的失败 Run。"""
    stats_by_app: dict[str, dict] = {}
    progress_lock = Lock()
    total_apps = len(apps)
    print(
        f"正在并行检查 {total_apps} 个应用的失败 Run "
        f"(并发 {TOKEN_STATS_WORKERS}，每页 {MONITOR_PAGE_LIMIT})..."
    )

    def load_failure_count(app: dict) -> tuple[dict, int, bool]:
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
            failed = sum(
                int(
                    ((conversation.get("status_count") or {}).get("failed"))
                    or 0
                )
                for conversation in conversations
            )
            return app, failed, complete
        _, data = list_workflow_logs(
            dict(headers),
            app_id=app_id,
            page=1,
            limit=MONITOR_PAGE_LIMIT,
            detail=True,
            status="failed",
            created_at_after=start.isoformat(timespec="seconds"),
            created_at_before=end.isoformat(timespec="seconds"),
        )
        if data is None:
            return app, 0, False
        try:
            failed = int(data.get("total") or 0)
        except (TypeError, ValueError):
            return app, 0, False
        return app, failed, True

    with ThreadPoolExecutor(max_workers=TOKEN_STATS_WORKERS) as pool:
        futures = {pool.submit(load_failure_count, app): app for app in apps}
        for done, future in enumerate(as_completed(futures), start=1):
            app = futures[future]
            app_id = app["app_id"]
            try:
                _, failed, complete = future.result()
            except Exception:
                failed, complete = 0, False
            stats = {
                "app_id": app_id,
                "group_name": app["group_name"],
                "name": app.get("name") or app_id,
                "mode": app.get("mode") or "workflow",
                "failed": failed,
                "complete": complete,
            }
            stats_by_app[app_id] = stats
            state = "完成" if complete else "数据不完整"
            with progress_lock:
                print(
                    f"  {format_progress(done, total_apps)} · "
                    f"{stats['name']}：{state}，失败 {failed}"
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
    total_failed = 0
    failed_rows = []
    display_names = dict(selected_groups)
    for group_name, display_name in selected_groups:
        group_stats = stats_by_group[group_name]
        failed = sum(item["failed"] for item in group_stats)
        incomplete = sum(not item["complete"] for item in group_stats)
        incomplete_apps += incomplete
        total_failed += failed
        summary_rows.append([
            display_name,
            len(group_stats),
            failed,
            "数据不完整 *" if incomplete else "检查完成",
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

    print_table(
        ["分组", "检查应用", "失败 Run", "状态"],
        summary_rows,
        ["left", "right", "right", "center"],
    )
    if failed_rows:
        print("### 失败应用\n")
        print_table(
            ["分组", "应用", "类型", "失败次数"],
            failed_rows,
            ["left", "left", "center", "right"],
        )
        print(f"### 结论\n\n发现 **{total_failed}** 次失败运行，请及时检查。\n")
    else:
        print("### 结论\n\n未发现失败运行。\n")
    if incomplete_apps:
        print(f"> `*` 有 {incomplete_apps} 个应用的数据未完整获取。\n")
    return total_failed > 0
