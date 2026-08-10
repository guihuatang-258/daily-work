"""加载通用 Dify 监控配置。"""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
DEFAULT_CONFIG_PATH = PROJECT_DIR / "config.yaml"
CONFIG_ENV_NAME = "DIFY_MONITOR_CONFIG"

DEFAULT_CONFIG: dict[str, Any] = {
    "instance": {
        "name": "default",
        "base_url": "https://dify.example.com",
        "timezone": "Asia/Shanghai",
        "workspace_id": "",
    },
    "authentication": {
        "type": "cookie",
    },
    "collection": {
        "apps_page_size": 30,
        "interactive_log_limit": 10,
        "monitor_page_size": 100,
        "token_stats_workers": 10,
    },
    "token_statistics": {
        "workflow_sample_size": 20,
    },
    "applications": {
        "groups_file": "dify_flow_groups.json",
        "chat_modes": ["advanced-chat", "chat"],
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """深度合并两个字典，优先使用 override 的值。

    Args:
        base (dict[str, Any]): _base 字典，作为默认值_
        override (dict[str, Any]): _override 字典，用户在YAML中配置的值_

    Returns:
        dict[str, Any]: _合并后的字典_
    """
    result = deepcopy(base)  # 深度拷贝 base，避免修改原始字典，相当于创建了一个新的字典对象
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def resolve_config_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser().resolve()
    configured = os.getenv(CONFIG_ENV_NAME)
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_CONFIG_PATH


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """读取 YAML 配置；文件不存在时使用向后兼容默认值。"""
    config_path = resolve_config_path(path)
    if not config_path.exists():
        return deepcopy(DEFAULT_CONFIG)
    try:
        with config_path.open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(f"无法读取监控配置 {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"监控配置格式错误: {config_path} 顶层必须是对象")
    return _deep_merge(DEFAULT_CONFIG, raw)


def get_config_value(config: dict[str, Any], path: str, default: Any = None) -> Any:
    value: Any = config
    # 按照路径逐级获取配置值
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def require_positive_int(config: dict[str, Any], path: str) -> int:
    value = get_config_value(config, path)
    if isinstance(value, bool):
        raise RuntimeError(f"配置 {path} 必须是正整数")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"配置 {path} 必须是正整数") from exc
    if parsed <= 0:
        raise RuntimeError(f"配置 {path} 必须是正整数")
    return parsed
