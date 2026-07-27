"""Cookie/CSRF 认证的加载、校验和更新。"""

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
from .settings import BASE_URL, ENV_PATH, PROJECT_DIR


COOKIE_REFRESH_POPUP_ENV = "NEZHA_COOKIE_REFRESH_POPUP"


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


def build_auth_headers(cookie: str) -> dict[str, str]:
    cookie = cookie.strip().strip('"').strip("'")
    if not cookie:
        raise RuntimeError("Missing required environment variable: NEZHA_COOKIE")
    cookies = parse_cookie_header(cookie)
    csrf_token = cookies.get("__Host-csrf_token")
    if not csrf_token:
        raise RuntimeError(
            "NEZHA_COOKIE 中缺少 __Host-csrf_token，请检查 Cookie 是否完整"
        )
    return {
        "Cookie": cookie,
        "X-CSRF-Token": csrf_token,
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Referer": f"{BASE_URL}/console/apps",
    }


def load_auth_headers(env_path: str | Path | None = None) -> dict[str, str]:
    path = str(env_path or ENV_PATH)
    load_dotenv(path, override=True)
    return build_auth_headers(os.getenv("NEZHA_COOKIE", ""))


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
    path = str(env_path or ENV_PATH)
    set_key(path, "NEZHA_COOKIE", cookie, quote_mode="always")
    os.environ["NEZHA_COOKIE"] = cookie


def ensure_valid_auth_headers(
    env_path: str | Path | None = None,
) -> dict[str, str]:
    path = str(env_path or ENV_PATH)
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
        cookie = getpass(
            "请粘贴最新的完整 Cookie（输入内容不会显示，直接回车退出）: "
        ).strip().strip('"').strip("'")
        if not cookie:
            raise SystemExit("未更新认证信息，程序已退出。")
        try:
            candidate_headers = build_auth_headers(cookie)
        except RuntimeError as exc:
            print(f"Cookie 格式无效: {exc}")
            continue
        status, message = validate_auth_headers(candidate_headers)
        if status == "valid":
            save_cookie_to_env(cookie, path)
            print(f"认证校验成功，已更新 {path}")
            return candidate_headers
        print(message)
        if status == "error":
            print("网络或服务异常，未覆盖 .env 中的认证信息。")


def refresh_auth_in_new_console() -> bool:
    """在新的可见命令行窗口中更新 Cookie，并等待用户完成操作。"""
    if os.name != "nt":
        return False
    entry_script = PROJECT_DIR / "analyze_nezha_apis.py"
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
        print(f"无法打开 Cookie 更新窗口: {exc}")
        return False
    return result.returncode == 0
