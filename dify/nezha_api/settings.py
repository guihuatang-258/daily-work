"""应用配置和默认参数。"""

from datetime import timedelta, timezone
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent

BASE_URL = "https://nezha.cn-pgcloud.com"
API0_LIMIT = 30
INTERACTIVE_LOG_LIMIT = 10
TOKEN_STATS_LIMIT = 20
TOKEN_STATS_WORKERS = 10
WORKFLOW_TOKEN_SAMPLE_SIZE = 20
CHAT_APP_MODES = {"advanced-chat", "chat"}
FLOW_GROUPS_PATH = PROJECT_DIR / "dify_flow_groups.json"
ENV_PATH = PROJECT_DIR / ".env"
MONITOR_PAGE_LIMIT = 100
MONITOR_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
