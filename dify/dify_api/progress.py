"""终端进度显示工具。"""

import sys


def progress_characters() -> tuple[str, str]:
    """返回当前终端编码可安全显示的进度字符。"""
    encoding = getattr(sys.stdout, "encoding", None)
    if encoding:
        try:
            "█░".encode(encoding)
        except (LookupError, UnicodeEncodeError):
            return "#", "-"
    return "█", "░"


def format_progress(done: int, total: int, width: int = 20) -> str:
    """生成适合普通终端的 Unicode 进度条。"""
    filled_char, empty_char = progress_characters()
    if total <= 0:
        return f"[{filled_char * width}] 0/0 100%"
    filled = min(width, round(width * done / total))
    percent = round(100 * done / total)
    return (
        f"[{filled_char * filled}{empty_char * (width - filled)}] "
        f"{done}/{total} {percent:>3}%"
    )
