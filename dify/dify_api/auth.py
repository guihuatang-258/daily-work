"""Cookie/CSRF 或 Authorization 认证的加载、校验和更新。"""

import os
import subprocess
import sys
from getpass import getpass
from http.cookies import SimpleCookie
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key

from .client import build_url
from .markdown import print_section, print_table
from .settings import AUTH_TYPE, BASE_URL, ENV_PATH, PROJECT_DIR


COOKIE_REFRESH_POPUP_ENV = "DIFY_COOKIE_REFRESH_POPUP"
LEGACY_COOKIE_REFRESH_POPUP_ENV = "NEZHA_COOKIE_REFRESH_POPUP"
AUTH_ENV_NAMES = {
    "cookie": "DIFY_COOKIE",
    "authorization": "DIFY_AUTHORIZATION",
}
LEGACY_AUTH_ENV_NAMES = {
    "cookie": ("NEZHA_COOKIE",),
    "authorization": (),
}
AUTH_DISPLAY_NAMES = {
    "cookie": "Cookie",
    "authorization": "Authorization",
}


def _resolve_auth_type(auth_type: str | None = None) -> str:
    selected_type = auth_type or AUTH_TYPE
    if selected_type not in AUTH_ENV_NAMES:
        raise RuntimeError("认证类型只能是 cookie 或 authorization")
    return selected_type


def parse_cookie_header(cookie_header: str) -> dict[str, str]:
    cookie = SimpleCookie()
    cookie.load(cookie_header)
    return {key: morsel.value for key, morsel in cookie.items()}


def mask_secret(value: str | None, head: int = 8, tail: int = 6) -> str:
    if not value:
        return "<missing>"
    if len(value) <= head + tail:
        return "*" * len(value)
    return f"{value[:head]}...{value[-tail:]}"


def print_auth_diagnostics(headers: dict) -> None:
    authorization = headers.get("Authorization")
    if authorization:
        print_section("认证诊断")
        print_table(
            ["项目", "值"],
            [
                ["认证方式", "Authorization"],
                ["Authorization", mask_secret(authorization)],
            ],
        )
        return
    cookies = parse_cookie_header(headers.get("Cookie", ""))
    csrf_header = headers.get("X-CSRF-Token")
    csrf_cookie = cookies.get("__Host-csrf_token")
    print_section("认证诊断")
    print_table(
        ["项目", "值"],
        [
            ["Cookie 字段数", len(cookies)],
            ["CSRF header", mask_secret(csrf_header)],
            ["CSRF cookie", mask_secret(csrf_cookie)],
            ["CSRF 匹配", csrf_header == csrf_cookie],
        ],
    )


def get_env_path() -> str:
    return str(ENV_PATH)


def _common_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Referer": f"{BASE_URL}/console/apps",
    }


def build_auth_headers(
    credential: str, auth_type: str | None = None
) -> dict[str, str]:
    selected_type = _resolve_auth_type(auth_type)
    credential = credential.strip().strip('"').strip("'")
    env_name = AUTH_ENV_NAMES[selected_type]
    if not credential:
        raise RuntimeError(f"Missing required environment variable: {env_name}")
    headers = _common_headers()
    if selected_type == "authorization":
        headers["Authorization"] = credential
        return headers

    cookie = credential
    cookies = parse_cookie_header(cookie)
    csrf_token = cookies.get("__Host-csrf_token")
    if not csrf_token:
        raise RuntimeError(
            "DIFY_COOKIE 中缺少 __Host-csrf_token，请检查 Cookie 是否完整"
        )
    headers["Cookie"] = cookie
    headers["X-CSRF-Token"] = csrf_token
    return headers


def load_auth_headers(
    env_path: str | Path | None = None,
    auth_type: str | None = None,
) -> dict[str, str]:
    path = str(env_path or ENV_PATH)
    load_dotenv(path, override=True)
    selected_type = _resolve_auth_type(auth_type)
    env_name = AUTH_ENV_NAMES[selected_type]
    credential = os.getenv(env_name, "")
    if not credential:
        for legacy_name in LEGACY_AUTH_ENV_NAMES[selected_type]:
            credential = os.getenv(legacy_name, "")
            if credential:
                break
    return build_auth_headers(credential, selected_type)


def validate_auth_headers(
    headers: dict, timeout: int = 15
) -> tuple[str, str]:
    url = build_url("/console/api/apps", {"page": 1, "limit": 1, "name": ""})
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        return "error", f"认证校验请求失败: {exc}"
    if response.status_code in {401, 403}:
        return "expired", f"认证已过期（HTTP {response.status_code}）"
    try:
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        return "error", f"认证校验响应异常: {exc}"
    if not isinstance(data, dict):
        return "error", "认证校验响应格式异常"
    return "valid", "认证有效"


def save_cookie_to_env(
    cookie: str, env_path: str | Path | None = None
) -> None:
    save_auth_to_env(cookie, env_path, "cookie")


def save_auth_to_env(
    credential: str,
    env_path: str | Path | None = None,
    auth_type: str | None = None,
) -> None:
    selected_type = _resolve_auth_type(auth_type)
    env_name = AUTH_ENV_NAMES[selected_type]
    path = str(env_path or ENV_PATH)
    set_key(path, env_name, credential, quote_mode="always")
    os.environ[env_name] = credential


def ensure_valid_auth_headers(
    env_path: str | Path | None = None,
) -> dict[str, str]:
    path = str(env_path or ENV_PATH)
    auth_display_name = AUTH_DISPLAY_NAMES[AUTH_TYPE]
    try:
        headers = load_auth_headers(path)
    except RuntimeError as exc:
        print(f"认证配置无效: {exc}")
    else:
        status, message = validate_auth_headers(headers)
        if status == "valid":
            print("认证校验成功。")
            return headers
        if status == "error":
            raise RuntimeError(message)
        print(message)

    while True:
        credential = getpass(
            f"请粘贴最新的完整 {auth_display_name} 值"
            "（输入内容不会显示，直接回车退出）: "
        ).strip().strip('"').strip("'")
        if not credential:
            raise SystemExit("未更新认证信息，程序已退出。")
        try:
            candidate_headers = build_auth_headers(credential)
        except RuntimeError as exc:
            print(f"{auth_display_name} 格式无效: {exc}")
            continue
        status, message = validate_auth_headers(candidate_headers)
        if status == "valid":
            save_auth_to_env(credential, path)
            print(f"认证校验成功，已更新 {path}")
            return candidate_headers
        print(message)
        if status == "error":
            print("网络或服务异常，未覆盖 .env 中的认证信息。")


def refresh_auth_in_new_console() -> bool:
    """在新的可见命令行窗口中更新认证信息，并等待用户完成操作。"""
    if os.name != "nt":
        return False
    entry_script = PROJECT_DIR / "main.py"
    child_env = dict(os.environ)
    child_env[COOKIE_REFRESH_POPUP_ENV] = "1"
    try:
        result = subprocess.run(
            [sys.executable, str(entry_script), "--refresh-cookie"],
            cwd=str(PROJECT_DIR),
            env=child_env,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            check=False,
        )
    except OSError as exc:
        print(f"无法打开认证信息更新窗口: {exc}")
        return False
    return result.returncode == 0
