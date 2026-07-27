"""标准 Markdown 输出组件。"""

from collections.abc import Sequence
from typing import Literal


Alignment = Literal["left", "center", "right"]
ALIGNMENT_MARKERS: dict[Alignment, str] = {
    "left": ":---",
    "center": ":---:",
    "right": "---:",
}


def cell(value: object) -> str:
    """把任意值转换为安全的 Markdown 表格单元格文本。"""
    if value is None:
        return "—"
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\\", "\\\\").replace("|", "\\|")
    return text.replace("\n", "<br>").replace("\t", " ") or "—"


def section(title: str, level: int = 2) -> str:
    """生成 Markdown 标题。"""
    return f"{'#' * level} {title}"


def table(
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    alignments: Sequence[Alignment] | None = None,
) -> str:
    """生成带列校验和对齐标记的标准 GFM 管道表格。"""
    if not headers:
        raise ValueError("Markdown 表格至少需要一列")
    resolved_alignments = list(alignments or ["left"] * len(headers))
    if len(resolved_alignments) != len(headers):
        raise ValueError("Markdown 表格的对齐配置数必须与列数一致")
    invalid_alignments = set(resolved_alignments) - set(ALIGNMENT_MARKERS)
    if invalid_alignments:
        raise ValueError(f"不支持的 Markdown 对齐方式: {invalid_alignments}")
    for index, row in enumerate(rows, start=1):
        if len(row) != len(headers):
            raise ValueError(
                f"Markdown 表格第 {index} 行有 {len(row)} 列，"
                f"预期 {len(headers)} 列"
            )
    lines = [
        "| " + " | ".join(cell(item) for item in headers) + " |",
        "| " + " | ".join(
            ALIGNMENT_MARKERS[alignment]
            for alignment in resolved_alignments
        ) + " |",
    ]
    lines.extend(
        "| " + " | ".join(cell(item) for item in row) + " |"
        for row in rows
    )
    return "\n".join(lines)


def print_section(title: str) -> None:
    print(section(title))
    print()


def print_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    alignments: Sequence[Alignment] | None = None,
) -> None:
    print(table(headers, rows, alignments))
    print()


def print_urls(urls: dict[str, str]) -> None:
    print_section("构建的 URL")
    for label, url in urls.items():
        print(f"- **{cell(label)}：** <{url}>")
    print()
