"""Flow 分组配置与监控时间范围。"""

import json
import os
import re
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

from .settings import CHAT_APP_MODES, FLOW_GROUPS_PATH, MONITOR_TIMEZONE


GROUP_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_flow_groups(groups: object) -> dict[str, dict]:
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


def load_flow_groups(
    config_path: str | Path = FLOW_GROUPS_PATH,
) -> dict[str, dict]:
    try:
        with Path(config_path).open("r", encoding="utf-8") as file:
            config = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取 Flow 组配置 {config_path}: {exc}") from exc
    return _validate_flow_groups(config.get("groups"))


def save_flow_groups(
    groups: dict[str, dict], config_path: str | Path = FLOW_GROUPS_PATH
) -> None:
    """校验并原子保存 Flow 分组，避免中途写入造成配置损坏。"""
    _validate_flow_groups(groups)
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            json.dump({"groups": groups}, file, ensure_ascii=False, indent=2)
            file.write("\n")
            temporary_path = Path(file.name)
        os.replace(temporary_path, path)
    except OSError as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise RuntimeError(f"无法保存 Flow 组配置 {path}: {exc}") from exc


def validate_group_key(group_name: str) -> str:
    normalized = group_name.strip()
    if not normalized:
        raise ValueError("分组代号不能为空")
    if not GROUP_KEY_PATTERN.fullmatch(normalized):
        raise ValueError("分组代号只能包含英文字母、数字、下划线和短横线")
    return normalized


def create_flow_group(
    groups: dict[str, dict], group_name: str, display_name: str
) -> dict[str, dict]:
    group_name = validate_group_key(group_name)
    if group_name in groups:
        raise ValueError(f"分组代号已存在: {group_name}")
    updated = deepcopy(groups)
    updated[group_name] = {
        "display_name": display_name.strip() or group_name,
        "apps": [],
    }
    return updated


def update_flow_group(
    groups: dict[str, dict],
    group_name: str,
    *,
    new_group_name: str | None = None,
    display_name: str | None = None,
) -> dict[str, dict]:
    if group_name not in groups:
        raise ValueError(f"分组不存在: {group_name}")
    target_name = (
        validate_group_key(new_group_name)
        if new_group_name is not None
        else group_name
    )
    if target_name != group_name and target_name in groups:
        raise ValueError(f"分组代号已存在: {target_name}")
    updated: dict[str, dict] = {}
    for name, group in deepcopy(groups).items():
        if name != group_name:
            updated[name] = group
            continue
        if display_name is not None:
            group["display_name"] = display_name.strip() or target_name
        updated[target_name] = group
    return updated


def delete_flow_group(
    groups: dict[str, dict], group_name: str
) -> dict[str, dict]:
    if group_name not in groups:
        raise ValueError(f"分组不存在: {group_name}")
    updated = deepcopy(groups)
    del updated[group_name]
    return updated


def add_app_to_flow_group(
    groups: dict[str, dict], group_name: str, app: dict
) -> dict[str, dict]:
    if group_name not in groups:
        raise ValueError(f"分组不存在: {group_name}")
    app_id = str(app.get("id") or app.get("app_id") or "").strip()
    if not app_id:
        raise ValueError("应用缺少 ID，无法加入业务组")
    mode = str(app.get("mode") or "workflow")
    if mode != "workflow" and mode not in CHAT_APP_MODES:
        raise ValueError(f"暂不支持此应用类型: {mode}")
    if any(
        str(item.get("app_id")) == app_id
        for item in groups[group_name]["apps"]
    ):
        raise ValueError("该应用已经在此业务组中")
    updated = deepcopy(groups)
    updated[group_name]["apps"].append({
        "name": str(app.get("name") or app_id),
        "app_id": app_id,
        "mode": mode,
    })
    return updated


def remove_app_from_flow_group(
    groups: dict[str, dict], group_name: str, app_id: str
) -> dict[str, dict]:
    if group_name not in groups:
        raise ValueError(f"分组不存在: {group_name}")
    updated = deepcopy(groups)
    apps = updated[group_name]["apps"]
    remaining = [app for app in apps if str(app.get("app_id")) != app_id]
    if len(remaining) == len(apps):
        raise ValueError(f"业务组中不存在应用: {app_id}")
    updated[group_name]["apps"] = remaining
    return updated


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
