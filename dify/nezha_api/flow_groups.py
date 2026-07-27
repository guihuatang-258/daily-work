"""Flow 分组配置与监控时间范围。"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from .settings import CHAT_APP_MODES, FLOW_GROUPS_PATH, MONITOR_TIMEZONE


def load_flow_groups(
    config_path: str | Path = FLOW_GROUPS_PATH,
) -> dict[str, dict]:
    try:
        with Path(config_path).open("r", encoding="utf-8") as file:
            config = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取 Flow 组配置 {config_path}: {exc}") from exc
    groups = config.get("groups")
    if not isinstance(groups, dict):
        raise RuntimeError("Flow 组配置格式错误: groups 必须是对象")
    for group_name, group in groups.items():
        if not isinstance(group, dict) or not isinstance(group.get("apps"), list):
            raise RuntimeError(
                f"Flow 组配置格式错误: groups.{group_name}.apps 必须是数组"
            )
        seen_app_ids: set[str] = set()
        for index, app in enumerate(group["apps"], start=1):
            if not isinstance(app, dict) or not app.get("app_id"):
                raise RuntimeError(
                    f"Flow 组 {group_name} 第 {index} 项缺少 app_id"
                )
            app_id = str(app["app_id"])
            if app_id in seen_app_ids:
                raise RuntimeError(
                    f"Flow 组 {group_name} 存在重复 app_id: {app_id}"
                )
            seen_app_ids.add(app_id)
            mode = app.get("mode") or "workflow"
            if mode != "workflow" and mode not in CHAT_APP_MODES:
                raise RuntimeError(
                    f"Flow 组 {group_name} 的 {app_id} 使用了不支持的 mode: {mode}"
                )
    return groups


def load_flow_group(
    group_name: str, config_path: str | Path = FLOW_GROUPS_PATH
) -> dict:
    group = load_flow_groups(config_path).get(group_name)
    if group is None:
        raise RuntimeError(f"Flow 组不存在: {group_name}")
    return group


def get_monitoring_time_range(
    period: str, now: datetime | None = None
) -> tuple[str, datetime, datetime]:
    now = now or datetime.now(MONITOR_TIMEZONE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=MONITOR_TIMEZONE)
    else:
        now = now.astimezone(MONITOR_TIMEZONE)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=0)
    if period == "today":
        return "今天", today_start, today_end
    if period == "yesterday":
        yesterday_start = today_start - timedelta(days=1)
        yesterday_end = today_end - timedelta(days=1)
        return "昨天", yesterday_start, yesterday_end
    if period == "3d":
        return "最近 3 天", today_start - timedelta(days=2), today_end
    if period == "7d":
        return "最近 7 天", today_start - timedelta(days=6), today_end
    raise ValueError(f"不支持的统计周期: {period}")
