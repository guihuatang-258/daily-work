"""Dify 当前 Workspace 的查询与配置校验。"""

import requests

from .client import build_url
from .settings import WORKSPACE_ID


def get_current_workspace(headers: dict, timeout: int = 15) -> dict:
    """返回当前账号在 Dify 服务端选中的 Workspace。"""
    url = build_url("/console/api/workspaces")
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"无法查询当前 Workspace: {exc}") from exc

    workspaces = data.get("workspaces") if isinstance(data, dict) else None
    if not isinstance(workspaces, list):
        raise RuntimeError("Workspace 查询响应格式异常：缺少 workspaces 数组")
    current = next(
        (
            workspace
            for workspace in workspaces
            if isinstance(workspace, dict) and workspace.get("current") is True
        ),
        None,
    )
    if current is None or not current.get("id"):
        raise RuntimeError("没有查询到当前 Workspace")
    return current


def ensure_expected_workspace(
    headers: dict, *, announce: bool = True
) -> dict | None:
    """确认服务端当前 Workspace 与配置一致；未配置时跳过。"""
    if not WORKSPACE_ID:
        return None

    current = get_current_workspace(headers)
    current_id = str(current["id"])
    current_name = str(current.get("name") or "<未命名>")
    if current_id != WORKSPACE_ID:
        raise RuntimeError(
            f"当前 Workspace 是 {current_name}（{current_id}），"
            f"但 config.yaml 期望的是 {WORKSPACE_ID}。"
            "请在 Dify 网页切回正确的 Workspace 后重新运行。"
        )
    if announce:
        print(f"Workspace 校验成功：{current_name}")
    return current
