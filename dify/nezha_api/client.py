"""哪吒控制台 API 请求与分页查询。"""

import urllib.parse
from datetime import datetime
from typing import Callable

import requests

from .settings import BASE_URL, MONITOR_PAGE_LIMIT


def build_url(path: str, params: dict | None = None) -> str:
    if not params:
        return f"{BASE_URL}{path}"
    return f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"


def request_json(url: str, headers: dict, timeout: int = 30) -> dict | list | None:
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code == 401:
            print(
                "Token 已过期，请从浏览器重新获取 Cookie 并更新 "
                ".env 中的 NEZHA_COOKIE。"
            )
            return None
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"请求失败: {exc}")
        return None


def list_workflow_apps(
    headers: dict, page: int = 1, limit: int = 30, name: str = ""
) -> tuple[str, dict | None]:
    url = build_url(
        "/console/api/apps", {"page": page, "limit": limit, "name": name}
    )
    data = request_json(url, headers)
    return url, data if isinstance(data, dict) else None


def list_all_apps(headers: dict, limit: int = 30) -> tuple[list[str], list[dict]]:
    page = 1
    urls: list[str] = []
    apps: list[dict] = []
    while True:
        url, data = list_workflow_apps(headers, page=page, limit=limit)
        urls.append(url)
        if not data:
            break
        page_apps = data.get("data", [])
        apps.extend(page_apps)
        if data.get("has_more") is False:
            break
        if data.get("has_more") is None and len(page_apps) < limit:
            break
        if not page_apps:
            break
        page += 1
    return urls, apps


def list_workflow_logs(
    headers: dict,
    app_id: str,
    page: int = 1,
    limit: int = 10,
    detail: bool = True,
    status: str | None = None,
    created_at_after: str | None = None,
    created_at_before: str | None = None,
) -> tuple[str, dict | None]:
    params = {"page": page, "limit": limit, "detail": str(detail).lower()}
    if status:
        params["status"] = status
    if created_at_after:
        params["created_at__after"] = created_at_after
    if created_at_before:
        params["created_at__before"] = created_at_before
    url = build_url(f"/console/api/apps/{app_id}/workflow-app-logs", params)
    data = request_json(url, headers)
    return url, data if isinstance(data, dict) else None


def list_chat_conversations(
    headers: dict,
    app_id: str,
    page: int = 1,
    limit: int = 10,
    start: str | None = None,
    end: str | None = None,
    sort_by: str = "-created_at",
    annotation_status: str = "all",
) -> tuple[str, dict | None]:
    params = {
        "page": page,
        "limit": limit,
        "sort_by": sort_by,
        "annotation_status": annotation_status,
    }
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    url = build_url(f"/console/api/apps/{app_id}/chat-conversations", params)
    data = request_json(url, headers)
    return url, data if isinstance(data, dict) else None


def get_workflow_run(
    headers: dict, app_id: str, run_id: str
) -> tuple[str, dict | None]:
    url = build_url(f"/console/api/apps/{app_id}/workflow-runs/{run_id}")
    data = request_json(url, headers)
    return url, data if isinstance(data, dict) else None


def get_chat_messages(
    headers: dict,
    app_id: str,
    conversation_id: str,
    limit: int = 10,
    first_id: str | None = None,
) -> tuple[str, dict | None]:
    params = {"conversation_id": conversation_id, "limit": limit}
    if first_id:
        params["first_id"] = first_id
    url = build_url(f"/console/api/apps/{app_id}/chat-messages", params)
    data = request_json(url, headers)
    return url, data if isinstance(data, dict) else None


def get_node_executions(
    headers: dict, app_id: str, run_id: str
) -> tuple[str, dict | list | None]:
    url = build_url(
        f"/console/api/apps/{app_id}/workflow-runs/{run_id}/node-executions"
    )
    return url, request_json(url, headers)


def _to_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def list_all_workflow_logs_in_range(
    headers: dict,
    app_id: str,
    start: datetime,
    end: datetime,
    limit: int = MONITOR_PAGE_LIMIT,
    status: str | None = None,
    progress_callback: Callable[[int, int, int, int], None] | None = None,
) -> tuple[list[dict], bool]:
    page = 1
    logs: list[dict] = []
    complete = True
    while True:
        _, data = list_workflow_logs(
            headers,
            app_id=app_id,
            page=page,
            limit=limit,
            detail=True,
            status=status,
            created_at_after=start.isoformat(timespec="seconds"),
            created_at_before=end.isoformat(timespec="seconds"),
        )
        if data is None:
            complete = False
            break
        page_logs = data.get("data", [])
        logs.extend(page_logs)
        total = _to_int(data.get("total"))
        actual_limit = _to_int(data.get("limit")) or limit
        total_pages = max(1, (total + actual_limit - 1) // actual_limit)
        if progress_callback:
            progress_callback(page, total_pages, len(logs), total)
        if data.get("has_more") is False:
            break
        if data.get("has_more") is None and len(page_logs) < limit:
            break
        if not page_logs:
            break
        page += 1
    return logs, complete


def list_all_chat_conversations_in_range(
    headers: dict,
    app_id: str,
    start: datetime,
    end: datetime,
    limit: int = MONITOR_PAGE_LIMIT,
    progress_callback: Callable[[int, int, int, int], None] | None = None,
) -> tuple[list[dict], bool]:
    """分页读取 Chatflow 会话；接口时间格式固定到分钟。"""
    page = 1
    conversations: list[dict] = []
    complete = True
    while True:
        _, data = list_chat_conversations(
            headers,
            app_id=app_id,
            page=page,
            limit=limit,
            start=start.strftime("%Y-%m-%d %H:%M"),
            end=end.strftime("%Y-%m-%d %H:%M"),
        )
        if data is None:
            complete = False
            break
        page_items = data.get("data", [])
        conversations.extend(page_items)
        total = _to_int(data.get("total"))
        actual_limit = _to_int(data.get("limit")) or limit
        total_pages = max(1, (total + actual_limit - 1) // actual_limit)
        if progress_callback:
            progress_callback(page, total_pages, len(conversations), total)
        if data.get("has_more") is False:
            break
        if data.get("has_more") is None and len(page_items) < limit:
            break
        if not page_items:
            break
        page += 1
    return conversations, complete
