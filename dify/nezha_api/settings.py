"""应用配置和默认参数。"""

from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import (
    PROJECT_DIR,
    get_config_value,
    load_config,
    require_positive_int,
)


CONFIG = load_config()

BASE_URL = str(get_config_value(CONFIG, "instance.base_url")).rstrip("/")
INSTANCE_NAME = str(get_config_value(CONFIG, "instance.name", "default"))

try:
    MONITOR_TIMEZONE = ZoneInfo(
        str(get_config_value(CONFIG, "instance.timezone", "Asia/Shanghai"))
    )
except ZoneInfoNotFoundError as exc:
    raise RuntimeError("配置 instance.timezone 不是有效的 IANA 时区") from exc

REQUEST_TIMEOUT_SECONDS = require_positive_int(
    CONFIG, "collection.request_timeout_seconds"
)
AUTH_TIMEOUT_SECONDS = require_positive_int(CONFIG, "collection.auth_timeout_seconds")
API0_LIMIT = require_positive_int(CONFIG, "collection.apps_page_size")
INTERACTIVE_LOG_LIMIT = require_positive_int(
    CONFIG, "collection.interactive_log_limit"
)
TOKEN_STATS_LIMIT = require_positive_int(CONFIG, "collection.token_stats_limit")
MONITOR_PAGE_LIMIT = require_positive_int(CONFIG, "collection.monitor_page_size")
TOKEN_STATS_WORKERS = require_positive_int(CONFIG, "collection.token_stats_workers")
FAILURE_CHECK_WORKERS = require_positive_int(
    CONFIG, "collection.failure_check_workers"
)
WORKFLOW_TOKEN_SAMPLE_SIZE = require_positive_int(
    CONFIG, "token_statistics.workflow_sample_size"
)
ESTIMATED_PREFIX = str(
    get_config_value(CONFIG, "token_statistics.estimated_prefix", "~")
)
DEFAULT_MONITOR_PERIOD = str(
    get_config_value(CONFIG, "monitoring.default_period", "today")
)
FAILURE_THRESHOLD = int(get_config_value(CONFIG, "monitoring.failure_threshold", 0))

CHAT_APP_MODES = {
    str(mode)
    for mode in get_config_value(
        CONFIG, "applications.chat_modes", ["advanced-chat", "chat"]
    )
}

groups_file = Path(
    str(get_config_value(CONFIG, "applications.groups_file", "dify_flow_groups.json"))
)
FLOW_GROUPS_PATH = groups_file if groups_file.is_absolute() else PROJECT_DIR / groups_file
ENV_PATH = PROJECT_DIR / ".env"
