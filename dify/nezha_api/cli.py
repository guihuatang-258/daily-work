"""命令行交互入口。"""

import argparse
import os
import sys

from .auth import (
    COOKIE_REFRESH_POPUP_ENV,
    ensure_valid_auth_headers,
    load_auth_headers,
    refresh_auth_in_new_console,
    validate_auth_headers,
)
from .client import get_workflow_run, list_all_apps, list_workflow_logs
from .flow_groups import load_flow_group, load_flow_groups
from .markdown import print_urls
from .monitor import print_group_failure_report
from .reports import (
    print_apps_token_stats,
    print_flow_group_token_stats,
    print_quality_workflow_token_stats,
    print_recent_workflow_logs,
    print_workflow_run,
)
from .settings import API0_LIMIT, CHAT_APP_MODES, INTERACTIVE_LOG_LIMIT


TOKEN_PERIOD_OPTIONS = [
    ("1", "今天", "today"),
    ("2", "最近 7 天", "7d"),
    ("3", "昨天", "yesterday"),
    ("4", "最近 3 天", "3d"),
]


def print_console_menu(
    title: str,
    options: list[tuple[str, str]],
    footer: tuple[str, str] | None = None,
) -> None:
    """输出无颜色、可稳定复制的 Unicode 终端菜单。"""
    print()
    print(f"┌─ {title}")
    for key, label in options:
        print(f"│  [{key}] {label}")
    if footer:
        print(f"└─ [{footer[0]}] {footer[1]}")
    else:
        print("└─")


def choose_item(items: list, label: str) -> dict | None:
    if not items:
        print(f"没有可选择的{label}")
        return None
    while True:
        raw = input(f"请选择{label} [Enter 取消] › ").strip()
        if not raw:
            return None
        if not raw.isdigit():
            print("  ! 请输入数字编号。")
            continue
        index = int(raw)
        if 1 <= index <= len(items):
            return items[index - 1]
        print(f"  ! 编号超出范围，请输入 1-{len(items)}。")


def normalize_query_mode(raw: str) -> str | None:
    value = raw.strip().lower()
    if value in {"0", "q", "quit", "exit"}:
        return "exit"
    if value in {"", "1", "workflow", "generic", "generic-workflow"}:
        return "workflow"
    if value in {"2", "chatflow", "chat"}:
        return "chatflow"
    return None


def filter_apps_by_mode(apps: list[dict], query_mode: str) -> list[dict]:
    if query_mode in {"workflow", "quality-workflow"}:
        return [app for app in apps if app.get("mode") == "workflow"]
    if query_mode == "chatflow":
        return [app for app in apps if app.get("mode") in CHAT_APP_MODES]
    return []


def filter_apps_by_name(apps: list[dict], keyword: str) -> list[dict]:
    normalized_keyword = keyword.casefold()
    return [
        app for app in apps
        if normalized_keyword in str(app.get("name") or "").casefold()
    ]


def view_recent_workflow_logs(headers: dict, app_id: str) -> None:
    logs_url, logs_data = list_workflow_logs(
        headers,
        app_id=app_id,
        page=1,
        limit=INTERACTIVE_LOG_LIMIT,
        detail=True,
    )
    print_urls({"最近日志 API": logs_url})
    logs = (logs_data or {}).get("data", [])
    if not logs:
        print("该工作流没有查询到最近日志。")
        return
    print_recent_workflow_logs(logs)
    selected_log = choose_item(logs, "日志")
    if not selected_log:
        print("已取消。")
        return
    workflow_run = selected_log.get("workflow_run", {})
    run_id = workflow_run.get("id") or selected_log.get("id")
    if not run_id:
        print("选中的日志没有找到 run_id，无法获取运行详情。")
        return
    run_url, run_data = get_workflow_run(headers, app_id=app_id, run_id=run_id)
    print_urls({"运行详情 API": run_url})
    print_workflow_run(run_data, output_path=f"workflow_run_{run_id}.json")


def pick_quality_workflow_action(headers: dict, app_id: str) -> None:
    print_console_menu(
        "质检打分 Workflow",
        [
            ("1", "查看最近日志（选一条查看运行详情）"),
            ("2", "按用户和质检项统计最近 Token 消耗"),
        ],
        ("Enter", "取消"),
    )
    choice = input("请选择操作 › ").strip()
    if not choice:
        print("已取消。")
    elif choice == "2":
        print_quality_workflow_token_stats(headers, app_id)
    elif choice == "1":
        view_recent_workflow_logs(headers, app_id)
    else:
        print("无效选择。")


def pick_generic_workflow_action(headers: dict, app: dict) -> None:
    print_console_menu(
        "通用 Workflow",
        [
            ("1", "查看最近日志（选一条查看运行详情）"),
            ("2", "按运行统计最近 Token 消耗"),
        ],
        ("Enter", "取消"),
    )
    choice = input("请选择操作 › ").strip()
    if not choice:
        print("已取消。")
    elif choice == "2":
        pick_app_token_period(headers, app)
    elif choice == "1":
        view_recent_workflow_logs(headers, app["id"])
    else:
        print("无效选择。")


def choose_token_period(display_name: str) -> str | None:
    """显示统一的 Token 统计周期菜单并返回周期代码。"""
    periods = {choice: period for choice, _, period in TOKEN_PERIOD_OPTIONS}
    periods[""] = "today"
    while True:
        print_console_menu(
            f"{display_name} · Token 统计范围",
            [
                (choice, label)
                for choice, label, _ in TOKEN_PERIOD_OPTIONS
            ],
            ("0", "返回主界面"),
        )
        choice = input("请选择统计范围 [默认 1] › ").strip()
        if choice in periods:
            return periods[choice]
        if choice == "0":
            return None
        print("  ! 请输入 0、1、2、3、4，或直接回车。")


def pick_flow_group_token_period(headers: dict, group_name: str) -> None:
    group = load_flow_group(group_name)
    display_name = group.get("display_name") or group_name
    period = choose_token_period(display_name)
    if period:
        print_flow_group_token_stats(headers, group_name, period)


def pick_app_token_period(headers: dict, app: dict) -> None:
    """用分组统计逻辑统计当前选中的单个应用。"""
    app_id = app["id"]
    display_name = app.get("name") or app_id
    period = choose_token_period(display_name)
    if not period:
        return
    print_apps_token_stats(
        headers,
        display_name,
        [{
            "app_id": app_id,
            "name": display_name,
            "mode": app.get("mode") or "workflow",
        }],
        period,
    )


def pick_failure_check_group(headers: dict) -> None:
    """选择单个分组或全部分组并检查失败 Run。"""
    try:
        groups = load_flow_groups()
    except RuntimeError as exc:
        print(f"分组配置错误: {exc}")
        return
    group_choices = {
        str(index): group_name
        for index, group_name in enumerate(groups, start=2)
    }
    options = [("1", "全部分组")]
    options.extend(
        (
            choice,
            groups[group_name].get("display_name") or group_name,
        )
        for choice, group_name in group_choices.items()
    )
    while True:
        print_console_menu(
            "失败 Run 检查范围", options, ("0", "返回主界面")
        )
        choice = input("请选择检查分组 › ").strip()
        if choice == "0" or not choice:
            return
        if choice == "1":
            print_group_failure_report(headers, list(groups))
            return
        if choice in group_choices:
            print_group_failure_report(headers, [group_choices[choice]])
            return
        valid_choices = "、".join(["0", "1", *group_choices])
        print(f"  ! 请输入 {valid_choices}。")


def choose_query_mode() -> str:
    while True:
        try:
            groups = load_flow_groups()
        except RuntimeError as exc:
            print(f"分组配置错误: {exc}")
            groups = {}
        group_choices = {
            str(index): group_name
            for index, group_name in enumerate(groups, start=4)
        }
        options = [
            ("1", "查询 · Workflow"),
            ("2", "查询 · Chatflow"),
            ("3", "检查 · 失败的 Run"),
        ]
        for choice, group_name in group_choices.items():
            group = groups[group_name]
            display_name = group.get("display_name") or group_name
            options.append(
                (choice, f"统计 · {display_name} Token 消耗")
            )
        print_console_menu(
            "Dify 日志查询工具", options, ("0", "退出")
        )
        raw = input("请选择功能 [默认 1] › ").strip()
        if raw == "3":
            return "failure-check"
        if raw in group_choices:
            return f"flow-group:{group_choices[raw]}"
        query_mode = normalize_query_mode(raw)
        if query_mode:
            return query_mode
        valid_choices = "、".join(["0", "1", "2", "3", *group_choices])
        print(f"  ! 请输入 {valid_choices}，或直接回车。")


def interactive_pick_workflow_run(headers: dict, query_mode: str) -> None:
    mode_labels = {
        "quality-workflow": "质检打分 Workflow",
        "workflow": "通用 Workflow",
        "chatflow": "Chatflow",
    }
    mode_label = mode_labels[query_mode]
    app_name = input(
        f"请输入{mode_label}名称关键字，直接回车显示全部: "
    ).strip()
    app_urls, all_apps = list_all_apps(headers, limit=API0_LIMIT)
    print_urls({
        f"应用列表 API（第{index}页）": url
        for index, url in enumerate(app_urls, start=1)
    })
    apps = filter_apps_by_name(
        filter_apps_by_mode(all_apps, query_mode), app_name
    )
    if not apps:
        if app_name:
            print(f"没有找到名称匹配 `{app_name}` 的{mode_label}。")
        else:
            print(f"没有查询到{mode_label}。")
        return
    print_console_menu(
        f"匹配到的{mode_label}",
        [
            (str(index), app.get("name") or "<未命名>")
            for index, app in enumerate(apps, start=1)
        ],
        ("Enter", "取消"),
    )
    selected_app = choose_item(apps, mode_label)
    if not selected_app:
        print("已取消。")
        return
    if query_mode == "quality-workflow":
        pick_quality_workflow_action(headers, selected_app["id"])
    elif query_mode == "workflow":
        pick_generic_workflow_action(headers, selected_app)
    else:
        pick_app_token_period(headers, selected_app)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dify 日志查询与监控工具")
    parser.add_argument(
        "--check-failures",
        nargs="+",
        metavar="GROUP",
        help="非交互检查指定 Flow 组今天是否有失败运行",
    )
    parser.add_argument(
        "--refresh-cookie",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def load_scheduled_auth_headers() -> dict:
    try:
        headers = load_auth_headers()
    except RuntimeError as exc:
        message = str(exc)
        status = "expired"
    else:
        status, message = validate_auth_headers(headers)
    if status == "valid":
        return headers
    if status == "error":
        raise RuntimeError(message)

    print(f"{message}，正在打开 Cookie 更新窗口...")
    if not refresh_auth_in_new_console():
        raise RuntimeError("Cookie 未更新，已取消本次检查")
    headers = load_auth_headers()
    status, message = validate_auth_headers(headers)
    if status != "valid":
        raise RuntimeError(f"Cookie 更新后校验失败: {message}")
    print("Cookie 更新成功，继续执行失败运行检查。")
    return headers


def run_failure_check(group_names: list[str]) -> int:
    try:
        headers = load_scheduled_auth_headers()
        print_group_failure_report(headers, group_names)
        return 0
    except RuntimeError as exc:
        print(f"失败运行检查无法完成: {exc}")
        return 2


def run_cookie_refresh() -> int:
    exit_code = 0
    try:
        ensure_valid_auth_headers()
        print("\nCookie 已更新，原定时检查将自动继续。")
    except (RuntimeError, SystemExit) as exc:
        print(f"\nCookie 更新未完成: {exc}")
        exit_code = 2
    if os.getenv(COOKIE_REFRESH_POPUP_ENV) == "1":
        try:
            input("\n按回车键关闭此窗口...")
        except EOFError:
            pass
    return exit_code


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    args = build_parser().parse_args(argv)
    if args.refresh_cookie:
        return run_cookie_refresh()
    if args.check_failures:
        return run_failure_check(args.check_failures)
    headers = ensure_valid_auth_headers()
    while True:
        query_mode = choose_query_mode()
        if query_mode == "exit":
            print("已退出。")
            return 0
        if query_mode == "failure-check":
            pick_failure_check_group(headers)
            continue
        if query_mode.startswith("flow-group:"):
            pick_flow_group_token_period(headers, query_mode.split(":", 1)[1])
            continue
        interactive_pick_workflow_run(headers, query_mode)
