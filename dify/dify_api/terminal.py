"""简约终端配色，并在非交互输出时自动关闭。"""

from __future__ import annotations

import os
import re
import shutil
import sys
import unicodedata
from io import TextIOBase
from typing import Callable, TypeVar

from colorama import just_fix_windows_console


RESET = "\033[0m"
BOLD_CYAN = "\033[1;36m"
CYAN = "\033[36m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"


T = TypeVar("T")


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


def read_navigation_key() -> str:
    """读取一次导航按键，并归一化为 up/down/space/enter/cancel。"""
    if os.name == "nt":
        import msvcrt

        char = msvcrt.getwch()
        if char in {"\x00", "\xe0"}:
            return {"H": "up", "P": "down"}.get(msvcrt.getwch(), "other")
        return {
            " ": "space",
            "\r": "enter",
            "\n": "enter",
            "\x1b": "cancel",
            "\x03": "cancel",
            "\x08": "backspace",
            "q": "cancel",
            "Q": "cancel",
        }.get(char, f"digit:{char}" if char.isdigit() else "other")

    import select
    import termios
    import tty

    file_descriptor = sys.stdin.fileno()
    previous_settings = termios.tcgetattr(file_descriptor)
    try:
        tty.setraw(file_descriptor)
        char = sys.stdin.read(1)
        if char == "\x1b":
            sequence = ""
            for _ in range(2):
                ready, _, _ = select.select([sys.stdin], [], [], 0.05)
                if not ready:
                    break
                sequence += sys.stdin.read(1)
            return {"[A": "up", "[B": "down"}.get(sequence, "cancel")
        return {
            " ": "space",
            "\r": "enter",
            "\n": "enter",
            "\x03": "cancel",
            "\x7f": "backspace",
            "q": "cancel",
            "Q": "cancel",
        }.get(char, f"digit:{char}" if char.isdigit() else "other")
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, previous_settings)


def _fallback_choose_multiple(
    items: list[T],
    labels: list[str],
    title: str,
    input_func: Callable[[str], str],
    stream: TextIOBase,
) -> list[T] | None:
    print(f"\n{title}", file=stream)
    for index, label in enumerate(labels, start=1):
        print(f"  [{index}] {label}", file=stream)
    while True:
        raw = input_func(
            "请输入一个或多个编号（用逗号分隔，直接回车取消）› "
        ).strip()
        if not raw:
            return None
        parts = [part.strip() for part in raw.replace("，", ",").split(",")]
        if not all(part.isdigit() for part in parts):
            print(
                "  ! 请输入数字编号，多个编号之间用逗号分隔。",
                file=stream,
            )
            continue
        indexes = [int(part) - 1 for part in parts]
        if any(index < 0 or index >= len(items) for index in indexes):
            print(f"  ! 编号超出范围，请输入 1-{len(items)}。", file=stream)
            continue
        return [items[index] for index in dict.fromkeys(indexes)]


def _display_width(text: str) -> int:
    return sum(
        0 if unicodedata.combining(char)
        else 2 if unicodedata.east_asian_width(char) in {"W", "F"}
        else 1
        for char in text
    )


def _truncate_display(text: str, max_width: int) -> str:
    if _display_width(text) <= max_width:
        return text
    result: list[str] = []
    used_width = 0
    content_width = max(max_width - 1, 0)
    for char in text:
        char_width = _display_width(char)
        if used_width + char_width > content_width:
            break
        result.append(char)
        used_width += char_width
    return "".join(result) + "…"


def choose_multiple(
    items: list[T],
    label_func: Callable[[T], str],
    title: str,
    *,
    key_reader: Callable[[], str] | None = None,
    stream: TextIOBase | None = None,
    input_func: Callable[[str], str] | None = None,
) -> list[T] | None:
    """方向键移动焦点、空格切换选择、回车确认的终端多选列表。"""
    if not items:
        return []
    stream = stream or sys.stdout
    input_func = input_func or input
    labels = [label_func(item) for item in items]
    if key_reader is None and not (
        getattr(sys.stdin, "isatty", lambda: False)()
        and getattr(stream, "isatty", lambda: False)()
    ):
        return _fallback_choose_multiple(items, labels, title, input_func, stream)

    key_reader = key_reader or read_navigation_key
    use_color = color_enabled(stream)
    focus_index = 0
    selected_indexes: set[int] = set()
    rendered = False
    terminal_size = shutil.get_terminal_size(fallback=(100, 24))
    terminal_width = max(terminal_size.columns, 20)
    visible_count = min(len(items), max(terminal_size.lines - 6, 3))
    line_count = visible_count + 4

    def render() -> None:
        nonlocal rendered
        if rendered:
            stream.write(f"\033[{line_count}F")
        viewport_start = min(
            max(focus_index - visible_count // 2, 0),
            len(items) - visible_count,
        )
        viewport_end = viewport_start + visible_count
        lines: list[tuple[str, str]] = [
            (
                f"┌─ {title} · {focus_index + 1}/{len(items)}"
                f" · 已选 {len(selected_indexes)}",
                BOLD_CYAN,
            ),
            (
                "│  ↑/↓ 移动  ·  空格 勾选  ·  Enter 确认  ·  Q 取消",
                CYAN,
            ),
            ("│", DIM),
        ]
        for index in range(viewport_start, viewport_end):
            label = labels[index]
            focus = "›" if index == focus_index else " "
            checkbox = "[✓]" if index in selected_indexes else "[ ]"
            prefix = f"│  {focus} {checkbox} "
            available_width = max(terminal_width - _display_width(prefix) - 1, 1)
            displayed_label = _truncate_display(label, available_width)
            if index == focus_index:
                row_color = BOLD_CYAN
            elif index in selected_indexes:
                row_color = GREEN
            else:
                row_color = ""
            lines.append((f"{prefix}{displayed_label}", row_color))
        lines.append(("└─", DIM))
        for line, line_color in lines:
            line = _truncate_display(line, terminal_width - 1)
            if use_color and line_color:
                line = f"{line_color}{line}{RESET}"
            prefix = "\r\033[2K" if rendered else ""
            if prefix:
                stream.write(prefix)
            stream.write(line)
            stream.write("\n")
        stream.flush()
        rendered = True

    render()
    while True:
        key = key_reader()
        if key == "up":
            focus_index = (focus_index - 1) % len(items)
            render()
        elif key == "down":
            focus_index = (focus_index + 1) % len(items)
            render()
        elif key == "space":
            if focus_index in selected_indexes:
                selected_indexes.remove(focus_index)
            else:
                selected_indexes.add(focus_index)
            render()
        elif key == "enter":
            stream.write("\n")
            stream.flush()
            return [items[index] for index in sorted(selected_indexes)]
        elif key == "cancel":
            stream.write("\n")
            stream.flush()
            return None


def _fallback_choose_menu(
    title: str,
    options: list[tuple[str, str]],
    footer: tuple[str, str] | None,
    prompt: str,
    default_key: str | None,
    input_func: Callable[[str], str],
    stream: TextIOBase,
) -> str | None:
    print(file=stream)
    print(f"┌─ {title}", file=stream)
    for key, label in options:
        print(f"│  [{key}] {label}", file=stream)
    if footer:
        print(f"└─ [{footer[0]}] {footer[1]}", file=stream)
    else:
        print("└─", file=stream)

    valid_keys = {key for key, _ in options}
    if footer and footer[0] != "Enter":
        valid_keys.add(footer[0])
    cancel_key = footer[0] if footer and footer[0] != "Enter" else None
    while True:
        raw = input_func(prompt).strip()
        if not raw:
            return default_key
        if raw in {"q", "Q"}:
            return cancel_key
        if raw in valid_keys:
            return raw
        choices = "、".join(key for key, _ in options)
        if footer and footer[0] != "Enter":
            choices = f"{choices}、{footer[0]}"
        print(f"  ! 请输入 {choices}。", file=stream)


def choose_menu(
    title: str,
    options: list[tuple[str, str]],
    footer: tuple[str, str] | None = None,
    *,
    prompt: str = "请选择操作 › ",
    default_key: str | None = None,
    key_reader: Callable[[], str] | None = None,
    stream: TextIOBase | None = None,
    input_func: Callable[[str], str] | None = None,
) -> str | None:
    """支持方向键和数字输入双向绑定的通用单选菜单。"""
    if not options:
        return None
    stream = stream or sys.stdout
    input_func = input_func or input
    if key_reader is None and not (
        getattr(sys.stdin, "isatty", lambda: False)()
        and getattr(stream, "isatty", lambda: False)()
    ):
        return _fallback_choose_menu(
            title,
            options,
            footer,
            prompt,
            default_key,
            input_func,
            stream,
        )

    entries = list(options)
    cancel_key: str | None = None
    if footer and footer[0] != "Enter":
        entries.append(footer)
        cancel_key = footer[0]
    focus_index = next(
        (
            index
            for index, (key, _) in enumerate(entries)
            if key == default_key
        ),
        0,
    )
    key_reader = key_reader or read_navigation_key
    use_color = color_enabled(stream)
    typed_digits = ""
    rendered = False
    terminal_size = shutil.get_terminal_size(fallback=(100, 24))
    terminal_width = max(terminal_size.columns, 20)
    visible_count = min(len(entries), max(terminal_size.lines - 6, 3))
    line_count = visible_count + 4

    def move_focus_for_number(number: str) -> bool:
        nonlocal focus_index
        exact_index = next(
            (
                index
                for index, (key, _) in enumerate(entries)
                if key == number
            ),
            None,
        )
        if exact_index is not None:
            focus_index = exact_index
            return True
        prefix_index = next(
            (
                index
                for index, (key, _) in enumerate(entries)
                if key.startswith(number)
            ),
            None,
        )
        if prefix_index is not None:
            focus_index = prefix_index
            return True
        return False

    def render() -> None:
        nonlocal rendered
        if rendered:
            stream.write(f"\033[{line_count}F")
        viewport_start = min(
            max(focus_index - visible_count // 2, 0),
            len(entries) - visible_count,
        )
        viewport_end = viewport_start + visible_count
        current_key = entries[focus_index][0]
        input_status = f" · 输入 {typed_digits}" if typed_digits else ""
        footer_label = footer[1] if footer else "取消"
        lines: list[tuple[str, str]] = [
            (
                f"┌─ {title} · 当前 [{current_key}]{input_status}",
                BOLD_CYAN,
            ),
            (
                f"│  ↑/↓ 移动  ·  输入数字跳转  ·  Enter 确认"
                f"  ·  Q {footer_label}",
                CYAN,
            ),
            ("│", DIM),
        ]
        key_width = max(_display_width(key) for key, _ in entries)
        for index in range(viewport_start, viewport_end):
            key, label = entries[index]
            focus = "›" if index == focus_index else " "
            padded_key = key.rjust(key_width)
            prefix = f"│  {focus} [{padded_key}] "
            available_width = max(terminal_width - _display_width(prefix) - 1, 1)
            displayed_label = _truncate_display(label, available_width)
            row_color = BOLD_CYAN if index == focus_index else ""
            lines.append((f"{prefix}{displayed_label}", row_color))
        lines.append((f"└─ [Q] {footer_label}", DIM))
        for line, line_color in lines:
            line = _truncate_display(line, terminal_width - 1)
            if use_color and line_color:
                line = f"{line_color}{line}{RESET}"
            prefix = "\r\033[2K" if rendered else ""
            if prefix:
                stream.write(prefix)
            stream.write(line)
            stream.write("\n")
        stream.flush()
        rendered = True

    render()
    while True:
        key = key_reader()
        if key == "up":
            focus_index = (focus_index - 1) % len(entries)
            typed_digits = ""
            render()
        elif key == "down":
            focus_index = (focus_index + 1) % len(entries)
            typed_digits = ""
            render()
        elif key.startswith("digit:"):
            digit = key.split(":", 1)[1]
            candidate = f"{typed_digits}{digit}"
            if move_focus_for_number(candidate):
                typed_digits = candidate
            elif move_focus_for_number(digit):
                typed_digits = digit
            render()
        elif key == "backspace":
            typed_digits = typed_digits[:-1]
            if typed_digits:
                move_focus_for_number(typed_digits)
            render()
        elif key == "enter":
            stream.write("\n")
            stream.flush()
            return entries[focus_index][0]
        elif key == "cancel":
            stream.write("\n")
            stream.flush()
            return cancel_key


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
