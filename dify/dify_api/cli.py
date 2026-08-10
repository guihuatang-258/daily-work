"""命令行交互入口。"""

import argparse
import os
import sys
from collections.abc import Callable

from .auth import (
    COOKIE_REFRESH_POPUP_ENV,
    LEGACY_COOKIE_REFRESH_POPUP_ENV,
    ensure_valid_auth_headers,
    load_auth_headers,
    refresh_auth_in_new_console,
    validate_auth_headers,
)
from .client import get_workflow_run, list_all_apps, list_workflow_logs
from .flow_groups import (
    add_app_to_flow_group,
    create_flow_group,
    delete_flow_group,
    load_flow_group,
    load_flow_groups,
    remove_app_from_flow_group,
    save_flow_groups,
    update_flow_group,
)
from .markdown import print_urls
from .monitor import print_group_failure_report
from .reports import (
    print_apps_token_stats,
    print_flow_group_token_stats,
    print_quality_workflow_token_stats,
    print_recent_workflow_logs,
    print_workflow_run,
)
from .settings import (
    API0_LIMIT,
    CHAT_APP_MODES,
    FLOW_GROUPS_PATH,
    INTERACTIVE_LOG_LIMIT,
)
from .terminal import choose_menu, choose_multiple
from .workspace import ensure_expected_workspace


TOKEN_PERIOD_OPTIONS = [
    ("1", "今天", "today"),
    ("2", "最近 7 天", "7d"),
    ("3", "昨天", "yesterday"),
    ("4", "最近 3 天", "3d"),
]


def choose_item(
    items: list,
    label: str,
    *,
    title: str | None = None,
    label_func: Callable[[dict], str] | None = None,
) -> dict | None:
    if not items:
        print(f"没有可选择的{label}")
        return None
    label_func = label_func or (
        lambda item: str(item.get("name") or item.get("id") or "<未命名>")
    )
    choice = choose_menu(
        title or f"选择{label}",
        [
            (str(index), label_func(item))
            for index, item in enumerate(items, start=1)
        ],
        ("0", "取消"),
        prompt=f"请选择{label} [Enter 取消] › ",
    )
    if not choice or choice == "0":
        return None
    return items[int(choice) - 1]


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
    selected_log = choose_item(
        logs,
        "日志",
        title="选择运行日志",
        label_func=lambda item: (
            f"{(item.get('workflow_run') or {}).get('id') or item.get('id')}"
            f" · {(item.get('workflow_run') or {}).get('status') or '未知状态'}"
        ),
    )
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
    choice = choose_menu(
        "质检打分 Workflow",
        [
            ("1", "查看最近日志（选一条查看运行详情）"),
            ("2", "按用户和质检项统计最近 Token 消耗"),
        ],
        ("0", "取消"),
    )
    if not choice or choice == "0":
        print("已取消。")
    elif choice == "2":
        print_quality_workflow_token_stats(headers, app_id)
    elif choice == "1":
        view_recent_workflow_logs(headers, app_id)
    else:
        print("无效选择。")


def pick_generic_workflow_action(headers: dict, app: dict) -> None:
    choice = choose_menu(
        "通用 Workflow",
        [
            ("1", "查看最近日志（选一条查看运行详情）"),
            ("2", "按运行统计最近 Token 消耗"),
        ],
        ("0", "取消"),
    )
    if not choice or choice == "0":
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
    choice = choose_menu(
        f"{display_name} · Token 统计范围",
        [(choice, label) for choice, label, _ in TOKEN_PERIOD_OPTIONS],
        ("0", "返回主界面"),
        prompt="请选择统计范围 [默认 1] › ",
        default_key="1",
    )
    if not choice or choice == "0":
        return None
    return periods[choice]


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
    choice = choose_menu(
        "失败 Run 检查范围",
        options,
        ("0", "返回主界面"),
        prompt="请选择检查分组 › ",
    )
    if choice == "0" or not choice:
        return
    if choice == "1":
        print_group_failure_report(headers, list(groups))
        return
    print_group_failure_report(headers, [group_choices[choice]])


def load_groups_for_management() -> dict[str, dict] | None:
    if not FLOW_GROUPS_PATH.exists():
        return {}
    try:
        return load_flow_groups()
    except RuntimeError as exc:
        print(f"分组配置错误: {exc}")
        print("请先修复配置文件，工具不会覆盖现有内容。")
        return None


def print_flow_groups(groups: dict[str, dict]) -> None:
    if not groups:
        print("\n还没有业务组，可以选择“新增业务组”创建。")
        return
    print("\n业务组列表")
    for group_name, group in groups.items():
        display_name = group.get("display_name") or group_name
        apps = group.get("apps", [])
        print(f"\n- {display_name}（代号: {group_name}，应用: {len(apps)} 个）")
        if not apps:
            print("  暂无应用")
        for app in apps:
            print(
                f"  - {app.get('name') or '<未命名>'}"
                f" [{app.get('mode') or 'workflow'}]"
                f" · {app.get('app_id')}"
            )


def choose_flow_group(groups: dict[str, dict]) -> str | None:
    if not groups:
        print("还没有业务组。")
        return None
    items = [
        {"group_name": name, "display_name": group.get("display_name") or name}
        for name, group in groups.items()
    ]
    selected = choose_item(
        items,
        "业务组",
        title="选择业务组",
        label_func=lambda item: (
            f"{item['display_name']}（{item['group_name']}）"
        ),
    )
    return selected["group_name"] if selected else None


def save_group_changes(groups: dict[str, dict]) -> bool:
    try:
        save_flow_groups(groups)
    except RuntimeError as exc:
        print(f"保存失败: {exc}")
        return False
    print(f"已保存到 {FLOW_GROUPS_PATH.name}。")
    return True


def create_flow_group_interactively(groups: dict[str, dict]) -> None:
    group_name = input(
        "请输入分组代号（英文、数字、下划线或短横线，Enter 取消）› "
    ).strip()
    if not group_name:
        print("已取消。")
        return
    display_name = input("请输入分组显示名称 [默认使用分组代号] › ").strip()
    try:
        updated = create_flow_group(groups, group_name, display_name)
    except ValueError as exc:
        print(f"无法新增业务组: {exc}")
        return
    if save_group_changes(updated):
        print("业务组已新增。可进入“修改业务组”添加应用。")


def add_group_app_interactively(
    headers: dict, groups: dict[str, dict], group_name: str
) -> None:
    keyword = input("请输入应用名称关键字，直接回车显示全部 › ").strip()
    try:
        app_urls, all_apps = list_all_apps(headers, limit=API0_LIMIT)
    except RuntimeError as exc:
        print(f"无法读取 Dify 应用: {exc}")
        return
    print_urls({
        f"应用列表 API（第{index}页）": url
        for index, url in enumerate(app_urls, start=1)
    })
    apps = filter_apps_by_name(all_apps, keyword)
    existing_app_ids = {
        str(app.get("app_id")) for app in groups[group_name].get("apps", [])
    }
    supported_apps = [
        app
        for app in apps
        if (
            app.get("mode") == "workflow" or app.get("mode") in CHAT_APP_MODES
        )
        and str(app.get("id")) not in existing_app_ids
    ]
    if not supported_apps:
        print("没有找到尚未加入该组的 Workflow 或 Chatflow 应用。")
        return
    selected_apps = choose_multiple(
        supported_apps,
        lambda app: f"{app.get('name') or '<未命名>'} [{app.get('mode')}]",
        "选择要添加的应用",
    )
    if selected_apps is None:
        print("已取消。")
        return
    if not selected_apps:
        print("没有选择应用。")
        return
    updated = groups
    try:
        for app in selected_apps:
            updated = add_app_to_flow_group(updated, group_name, app)
    except ValueError as exc:
        print(f"无法添加应用: {exc}")
        return
    if save_group_changes(updated):
        print(f"已将 {len(selected_apps)} 个应用加入业务组。")


def remove_group_app_interactively(
    groups: dict[str, dict], group_name: str
) -> None:
    apps = groups[group_name].get("apps", [])
    if not apps:
        print("这个业务组中还没有应用。")
        return
    selected = choose_item(
        apps,
        "应用",
        title="选择要移除的应用",
        label_func=lambda app: app.get("name") or str(app.get("app_id")),
    )
    if not selected:
        print("已取消。")
        return
    confirm = input(
        f"确认从业务组移除“{selected.get('name')}”？输入 y 确认 › "
    ).strip().lower()
    if confirm != "y":
        print("已取消。")
        return
    try:
        updated = remove_app_from_flow_group(
            groups, group_name, str(selected.get("app_id"))
        )
    except ValueError as exc:
        print(f"无法移除应用: {exc}")
        return
    if save_group_changes(updated):
        print("应用已从业务组移除，不会删除 Dify 中的应用。")


def edit_flow_group_interactively(headers: dict, group_name: str) -> None:
    while True:
        groups = load_groups_for_management()
        if groups is None or group_name not in groups:
            return
        group = groups[group_name]
        display_name = group.get("display_name") or group_name
        choice = choose_menu(
            f"修改业务组 · {display_name}",
            [
                ("1", "修改分组代号"),
                ("2", "修改显示名称"),
                ("3", "添加应用"),
                ("4", "移除应用"),
            ],
            ("0", "返回"),
        )
        if choice == "0" or not choice:
            return
        if choice == "1":
            new_name = input("请输入新的分组代号 [Enter 取消] › ").strip()
            if not new_name:
                print("已取消。")
                continue
            try:
                updated = update_flow_group(
                    groups, group_name, new_group_name=new_name
                )
            except ValueError as exc:
                print(f"无法修改分组代号: {exc}")
                continue
            if save_group_changes(updated):
                group_name = new_name.strip()
                print("分组代号已修改。")
        elif choice == "2":
            new_display_name = input(
                "请输入新的显示名称 [Enter 取消] › "
            ).strip()
            if not new_display_name:
                print("已取消。")
                continue
            updated = update_flow_group(
                groups, group_name, display_name=new_display_name
            )
            if save_group_changes(updated):
                print("显示名称已修改。")
        elif choice == "3":
            add_group_app_interactively(headers, groups, group_name)
        elif choice == "4":
            remove_group_app_interactively(groups, group_name)
        else:
            print("  ! 请输入 0、1、2、3 或 4。")


def delete_flow_group_interactively(groups: dict[str, dict]) -> None:
    group_name = choose_flow_group(groups)
    if not group_name:
        return
    display_name = groups[group_name].get("display_name") or group_name
    confirm = input(
        f"确认删除业务组“{display_name}”？输入 DELETE 确认 › "
    ).strip()
    if confirm != "DELETE":
        print("已取消。")
        return
    updated = delete_flow_group(groups, group_name)
    if save_group_changes(updated):
        print("业务组已删除，不会删除 Dify 中的应用。")


def manage_flow_groups(headers: dict) -> None:
    while True:
        groups = load_groups_for_management()
        if groups is None:
            return
        choice = choose_menu(
            "管理业务组",
            [
                ("1", "查看业务组"),
                ("2", "新增业务组"),
                ("3", "修改业务组及应用"),
                ("4", "删除业务组"),
            ],
            ("0", "返回主界面"),
        )
        if choice == "0" or not choice:
            return
        if choice == "1":
            print_flow_groups(groups)
        elif choice == "2":
            create_flow_group_interactively(groups)
        elif choice == "3":
            group_name = choose_flow_group(groups)
            if group_name:
                edit_flow_group_interactively(headers, group_name)
        elif choice == "4":
            delete_flow_group_interactively(groups)
        else:
            print("  ! 请输入 0、1、2、3 或 4。")


def choose_query_mode() -> str:
    while True:
        try:
            groups = load_flow_groups()
        except RuntimeError as exc:
            if FLOW_GROUPS_PATH.exists():
                print(f"分组配置错误: {exc}")
            groups = {}
        group_choices = {
            str(index): group_name
            for index, group_name in enumerate(groups, start=5)
        }
        options = [
            ("1", "查询 · Workflow"),
            ("2", "查询 · Chatflow"),
            ("3", "检查 · 失败的 Run"),
            ("4", "管理 · 业务组"),
        ]
        for choice, group_name in group_choices.items():
            group = groups[group_name]
            display_name = group.get("display_name") or group_name
            options.append(
                (choice, f"统计 · {display_name} Token 消耗")
            )
        raw = choose_menu(
            "Dify 日志查询工具",
            options,
            ("0", "退出"),
            prompt="请选择功能 [默认 1] › ",
            default_key="1",
        )
        if raw == "3":
            return "failure-check"
        if raw == "4":
            return "manage-groups"
        if raw in group_choices:
            return f"flow-group:{group_choices[raw]}"
        query_mode = normalize_query_mode(raw or "")
        if query_mode:
            return query_mode
        valid_choices = "、".join(
            ["0", "1", "2", "3", "4", *group_choices]
        )
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
    selected_app = choose_item(
        apps,
        mode_label,
        title=f"匹配到的{mode_label}",
        label_func=lambda app: app.get("name") or "<未命名>",
    )
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
        ensure_expected_workspace(headers)
        return headers
    if status == "error":
        raise RuntimeError(message)

    print(f"{message}，正在打开认证信息更新窗口...")
    if not refresh_auth_in_new_console():
        raise RuntimeError("认证信息未更新，已取消本次检查")
    headers = load_auth_headers()
    status, message = validate_auth_headers(headers)
    if status != "valid":
        raise RuntimeError(f"认证信息更新后校验失败: {message}")
    print("认证信息更新成功，继续执行失败运行检查。")
    ensure_expected_workspace(headers)
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
        print("\n认证信息已更新，原定时检查将自动继续。")
    except (RuntimeError, SystemExit) as exc:
        print(f"\n认证信息更新未完成: {exc}")
        exit_code = 2
    popup_env_names = (
        COOKIE_REFRESH_POPUP_ENV,
        LEGACY_COOKIE_REFRESH_POPUP_ENV,
    )
    if exit_code != 0 and any(
        os.getenv(name) == "1" for name in popup_env_names
    ):
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
    try:
        ensure_expected_workspace(headers)
    except RuntimeError as exc:
        print(f"程序无法启动: {exc}")
        return 2
    while True:
        query_mode = choose_query_mode()
        if query_mode == "exit":
            print("已退出。")
            return 0
        if query_mode == "failure-check":
            pick_failure_check_group(headers)
            continue
        if query_mode == "manage-groups":
            manage_flow_groups(headers)
            continue
        if query_mode.startswith("flow-group:"):
            pick_flow_group_token_period(headers, query_mode.split(":", 1)[1])
            continue
        interactive_pick_workflow_run(headers, query_mode)
