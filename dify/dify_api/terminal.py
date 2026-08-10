"""简约终端配色，并在非交互输出时自动关闭。"""

from __future__ import annotations

import os
import re
import sys
from io import TextIOBase

from colorama import just_fix_windows_console


RESET = "\033[0m"
BOLD_CYAN = "\033[1;36m"
CYAN = "\033[36m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"


_MENU_TITLE_RE = re.compile(r"^(\s*┌─\s*)(.+)$")
_MENU_OPTION_RE = re.compile(r"^(\s*[│└]─?\s*)\[([^]]+)](.*)$")


def color_enabled(stream: TextIOBase | None = None) -> bool:
    """判断当前输出是否适合使用 ANSI 颜色。"""
    stream = stream or sys.stdout
    if os.getenv("NO_COLOR") is not None:
        return False
    if os.getenv("FORCE_COLOR") is not None:
        return True
    return bool(getattr(stream, "isatty", lambda: False)())


def style_text(text: str) -> str:
    """对主界面常见文本做轻量着色。"""
    if not text or "\033[" in text:
        return text

    title_match = _MENU_TITLE_RE.match(text)
    if title_match:
        prefix, title = title_match.groups()
        return f"{DIM}{prefix}{RESET}{BOLD_CYAN}{title}{RESET}"

    option_match = _MENU_OPTION_RE.match(text)
    if option_match:
        prefix, key, label = option_match.groups()
        return (
            f"{DIM}{prefix}{RESET}"
            f"{CYAN}[{key}]{RESET}"
            f"{label}"
        )

    stripped = text.lstrip()
    leading = text[: len(text) - len(stripped)]
    if stripped.startswith("!") or "错误:" in stripped or "失败:" in stripped:
        return f"{leading}{RED}{stripped}{RESET}"
    if stripped.startswith("警告:") or "数据不完整" in stripped:
        return f"{leading}{YELLOW}{stripped}{RESET}"
    if stripped.startswith("认证校验成功") or stripped.startswith("Cookie 更新成功"):
        return f"{leading}{GREEN}{stripped}{RESET}"
    if stripped.startswith("请选择") or stripped.startswith("请输入"):
        return f"{CYAN}{text}{RESET}"
    return text


class ColorStream:
    """仅在交互式终端中给输出片段增加颜色。"""

    def __init__(self, wrapped: TextIOBase):
        self.wrapped = wrapped

    def write(self, text: str) -> int:
        return self.wrapped.write(style_text(text))

    def flush(self) -> None:
        self.wrapped.flush()

    def isatty(self) -> bool:
        return bool(getattr(self.wrapped, "isatty", lambda: False)())

    def fileno(self) -> int:
        return self.wrapped.fileno()

    @property
    def encoding(self) -> str | None:
        return getattr(self.wrapped, "encoding", None)

    def reconfigure(self, *args, **kwargs) -> None:
        reconfigure = getattr(self.wrapped, "reconfigure", None)
        if reconfigure:
            reconfigure(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self.wrapped, name)


def install_terminal_theme() -> bool:
    """安装终端配色；返回是否启用。"""
    if not color_enabled(sys.stdout):
        return False
    just_fix_windows_console()
    if not isinstance(sys.stdout, ColorStream):
        sys.stdout = ColorStream(sys.stdout)
    return True
