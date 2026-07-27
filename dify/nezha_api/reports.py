"""把 API 数据和统计结果渲染为 Markdown。"""

import json
from datetime import datetime
from pathlib import Path

from .flow_groups import get_monitoring_time_range, load_flow_group
from .markdown import cell, print_section, print_table, print_urls
from .settings import CHAT_APP_MODES, WORKFLOW_TOKEN_SAMPLE_SIZE
from .stats import (
    collect_flow_group_token_stats,
    collect_quality_workflow_stats,
    get_item_id,
)


def _format_integer(
    value: int, *, estimated: bool = False, incomplete: bool = False
) -> str:
    prefix = "~" if estimated else ""
    suffix = " *" if incomplete else ""
    return f"{prefix}{value:,}{suffix}"


def _format_price(value: float) -> str:
    return f"{value:,.6f}"


def print_workflow_apps(data: dict | None) -> None:
    print_section("API 0 工作流列表")
    if not data:
        print("> 暂无数据。\n")
        return
    print(f"- **顶层字段：** {', '.join(data.keys()) or '-'}")
    print(
        f"- **分页：** 第 {data.get('page')} 页，每页 {data.get('limit')} 条，"
        f"共 {data.get('total')} 条"
    )
    print(f"- **是否有下一页：** {data.get('has_more')}\n")
    print_table(
        ["APP ID", "名称", "模式", "Workflow ID"],
        [
            [app.get("id"), app.get("name"), app.get("mode"), app.get("workflow_id")]
            for app in data.get("data", [])
        ],
    )


def print_workflow_logs(data: dict | None) -> None:
    print_section("API 1 工作流日志返回结果")
    if not data:
        print("> 暂无数据。\n")
        return
    print(f"- **顶层字段：** {', '.join(data.keys()) or '-'}")
    print(
        f"- **分页：** 第 {data.get('page')} 页，每页 {data.get('limit')} 条，"
        f"共 {data.get('total')} 条"
    )
    print(f"- **是否有下一页：** {data.get('has_more')}\n")
    rows = []
    for item in data.get("data", []):
        run = item.get("workflow_run", {})
        rows.append([
            run.get("id"), run.get("status"), run.get("total_steps"),
            run.get("total_tokens"), f"{run.get('elapsed_time')} s",
        ])
    print_table(
        ["运行 ID", "状态", "步骤数", "Tokens", "耗时"],
        rows,
        ["left", "center", "right", "right", "right"],
    )


def print_workflow_run(
    data: dict | None, output_path: str | Path = "api2_response.json"
) -> None:
    print_section("API 2 单次运行详情返回结果")
    if not data:
        print("> 暂无数据。\n")
        return
    inputs = data.get("inputs") or {}
    outputs = data.get("outputs") or {}
    print_table(
        ["项目", "值"],
        [
            ["顶层字段", ", ".join(data.keys())],
            ["运行 ID", data.get("id")],
            ["状态", data.get("status")],
            ["耗时", f"{data.get('elapsed_time')} s"],
            ["Tokens", data.get("total_tokens")],
            ["步骤数", data.get("total_steps")],
            ["创建时间", data.get("created_at")],
            ["完成时间", data.get("finished_at")],
            ["输入字段", ", ".join(inputs.keys())],
            ["输出字段", ", ".join(outputs.keys())],
        ],
        ["left", "left"],
    )
    if data.get("graph"):
        nodes = data["graph"].get("nodes", [])
        print(f"### Graph 节点（{len(nodes)}）\n")
        print_table(
            ["类型", "标题"],
            [
                [node.get("data", {}).get("type"), node.get("data", {}).get("title")]
                for node in nodes
            ],
            ["left", "left"],
        )
    path = Path(output_path)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"> 完整响应已保存到 `{path}`\n")


def print_chat_conversations(conversations: list[dict]) -> None:
    print_section("最近 Chatflow 会话列表")
    print_table(
        ["序号", "会话 ID", "名称/摘要", "创建时间", "更新时间", "消息数"],
        [
            [
                index, get_item_id(item),
                item.get("name") or item.get("summary") or item.get("query"),
                item.get("created_at"), item.get("updated_at"),
                item.get("message_count"),
            ]
            for index, item in enumerate(conversations, start=1)
        ],
        ["right", "left", "left", "left", "left", "right"],
    )


def print_chat_messages(
    data: dict | None, output_path: str | Path
) -> None:
    print_section("Chatflow 消息详情返回结果")
    if not data:
        print("> 暂无数据。\n")
        return
    messages = data.get("data", [])
    print(f"- **顶层字段：** {', '.join(data.keys()) or '-'}")
    print(f"- **消息数：** {len(messages)}\n")
    print_table(
        ["序号", "消息 ID", "创建时间", "问题", "回答长度"],
        [
            [index, message.get("id"), message.get("created_at"),
             message.get("query"), len(message.get("answer") or "")]
            for index, message in enumerate(messages, start=1)
        ],
        ["right", "left", "left", "left", "right"],
    )
    path = Path(output_path)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"> 完整响应已保存到 `{path}`\n")


def print_recent_workflow_logs(logs: list[dict]) -> None:
    print_section("最近日志列表")
    print_table(
        ["序号", "运行 ID", "状态", "创建时间", "耗时", "Tokens"],
        [
            [
                index, run.get("id") or item.get("id"), run.get("status"),
                run.get("created_at") or item.get("created_at"),
                f"{run.get('elapsed_time')} s", run.get("total_tokens"),
            ]
            for index, item in enumerate(logs, start=1)
            for run in [item.get("workflow_run", {})]
        ],
        ["right", "left", "center", "left", "right", "right"],
    )


def print_quality_workflow_token_stats(headers: dict, app_id: str) -> None:
    result = collect_quality_workflow_stats(headers, app_id)
    print_urls({"Token 统计 -> 日志 API": result["url"]})
    if not result["logs"]:
        print("该工作流没有查询到最近日志。")
        return
    user_groups = result["user_groups"]
    print_section("Token 消耗统计（按用户分组）")
    print(f"- **应用 ID：** `{app_id}`")
    print(f"- **用户数：** {len(user_groups)}\n")
    grand_tokens = 0
    grand_price = 0.0
    for user_id, group_rows in user_groups.items():
        user_tokens = sum(row[2] for row in group_rows)
        user_price = sum(row[3] for row in group_rows)
        grand_tokens += user_tokens
        grand_price += user_price
        print(f"### 用户 `{cell(user_id or '?')}`\n")
        print(f"- **质检项数：** {len(group_rows)}")
        print(f"- **Tokens：** {_format_integer(user_tokens)}")
        print(f"- **费用：** ¥{_format_price(user_price)}\n")
        print_table(
            ["质检项", "运行 ID", "状态", "Tokens", "费用（RMB）"],
            [
                [rule_name or "?", run_id, status,
                 _format_integer(tokens) if tokens is not None else "ERROR",
                 _format_price(price) if price is not None else "ERROR"]
                for run_id, status, tokens, price, rule_name in group_rows
            ],
            ["left", "left", "center", "right", "right"],
        )
    print("### 汇总\n")
    print_table(
        ["用户数", "Tokens", "费用（RMB）"],
        [[len(user_groups), _format_integer(grand_tokens), _format_price(grand_price)]],
        ["right", "right", "right"],
    )


def print_apps_token_stats(
    headers: dict,
    display_name: str,
    apps: list[dict],
    period: str,
    now: datetime | None = None,
) -> None:
    """使用统一的分组统计逻辑输出一个或多个应用的 Token 消耗。"""
    label, start, end = get_monitoring_time_range(period, now)
    stats = collect_flow_group_token_stats(headers, apps, start, end)
    print_section(f"{display_name} Token 消耗")
    print(f"- **统计范围：** {label}")
    print(
        f"- **北京时间：** {start.strftime('%Y-%m-%d %H:%M:%S')} "
        f"至 {end.strftime('%Y-%m-%d %H:%M:%S')}\n"
    )
    rows = []
    totals = {
        "records": 0,
        "success": 0,
        "failed": 0,
        "input": 0,
        "output": 0,
        "tokens": 0,
    }
    incomplete_count = missing_io_count = 0
    has_io_values = has_estimated_io = False
    for item in stats:
        data_available = item.get("data_available", True)
        supports_breakdown = item["io_available"]
        has_io_values = has_io_values or (
            data_available and supports_breakdown
        )
        has_estimated_io = has_estimated_io or item["io_estimated"]
        if not supports_breakdown and item["total_tokens"] > 0:
            missing_io_count += 1
        if data_available:
            rows.append([
                item["name"], item["mode"],
                _format_integer(item["records"]),
                _format_integer(
                    item["input_tokens"], estimated=item["io_estimated"]
                ) if supports_breakdown else None,
                _format_integer(
                    item["output_tokens"], estimated=item["io_estimated"]
                ) if supports_breakdown else None,
                _format_integer(
                    item["total_tokens"], incomplete=not item["complete"]
                ),
            ])
        else:
            rows.append([
                item["name"], item["mode"],
                "— *", "— *", "— *", "— *",
            ])
        totals["records"] += item["records"]
        totals["success"] += item.get(
            "success", max(0, item["records"] - item["failed"])
        )
        totals["failed"] += item["failed"]
        totals["input"] += item["input_tokens"]
        totals["output"] += item["output_tokens"]
        totals["tokens"] += item["total_tokens"]
        incomplete_count += int(not item["complete"])
    rows.append([
        "**总计**", None,
        _format_integer(totals["records"], incomplete=bool(incomplete_count)),
        _format_integer(
            totals["input"],
            estimated=has_estimated_io,
            incomplete=bool(incomplete_count),
        )
        if has_io_values else None,
        _format_integer(
            totals["output"],
            estimated=has_estimated_io,
            incomplete=bool(incomplete_count),
        )
        if has_io_values else None,
        _format_integer(totals["tokens"], incomplete=bool(incomplete_count)),
    ])
    print_table(
        ["名称", "类型", "运行/会话", "Input", "Output", "Total"],
        rows,
        ["left", "center", "right", "right", "right", "right"],
    )
    print("### 执行结果\n")
    print(
        f"- **成功次数：** "
        f"{_format_integer(totals['success'], incomplete=bool(incomplete_count))}"
    )
    print(
        f"- **失败次数：** "
        f"{_format_integer(totals['failed'], incomplete=bool(incomplete_count))}\n"
    )
    if has_estimated_io:
        print(
            f"> `~` Workflow input/output 基于每个 Flow 最多 "
            f"{WORKFLOW_TOKEN_SAMPLE_SIZE} 条均匀样本估算；total 为精确值。"
        )
    if any(item["mode"] in CHAT_APP_MODES for item in stats):
        print("> Chatflow input/output/total 均来自消息 usage，为精确值。")
    if missing_io_count:
        print(f"> 有 {missing_io_count} 个 Workflow 未取得有效样本，无法估算 I/O。")
    if incomplete_count:
        print(
            f"> `*` 有 {incomplete_count} 个应用的数据未完整获取，"
            "input/output 或 total 可能偏小。"
        )
    print()


def print_flow_group_token_stats(
    headers: dict,
    group_name: str,
    period: str,
    now: datetime | None = None,
) -> None:
    group = load_flow_group(group_name)
    print_apps_token_stats(
        headers,
        group.get("display_name") or group_name,
        group["apps"],
        period,
        now,
    )
