"""runtime.computer.reading 负责文本文件的分页和截断提示.

这个文件给 `runtime.computer.runtime` 提供纯文本 helper:
- 处理 `offset`
- 处理 `limit`
- 处理默认的行数和字节上限
- 生成继续读取的提示文字

它不负责读文件, 也不负责判断图片.
"""

from __future__ import annotations

from dataclasses import dataclass


# region constants
DEFAULT_READ_MAX_LINES = 2000
DEFAULT_READ_MAX_BYTES = 50 * 1024


# endregion


# region data
@dataclass(slots=True)
class TextReadPage:
    """一次文本读取整理后的结果.

    Attributes:
        text (str): 要返回给模型的文字.
    """

    text: str


@dataclass(slots=True)
class TruncatedText:
    """截断后的中间结果.

    Attributes:
        text (str): 当前保留下来的文字.
        output_lines (int): 当前一共保留了多少行.
        truncated (bool): 这次有没有被截断.
        truncated_by (str): 是被行数还是字节数截断.
        first_line_exceeds_limit (bool): 第一行自己就超过上限时为 True.
    """

    text: str
    output_lines: int
    truncated: bool
    truncated_by: str = ""
    first_line_exceeds_limit: bool = False


# endregion


# region helpers

def format_read_text(*, text: str, path: str, offset: int | None = None, limit: int | None = None) -> TextReadPage:
    """把原始文本整理成 read 工具要返回的样子.

    Args:
        text (str): 文件原始文本.
        path (str): 当前 world path.
        offset (int | None): 起始行号, 从 1 开始.
        limit (int | None): 最多返回多少行.

    Returns:
        TextReadPage: 整理后的结果.

    Raises:
        ValueError: 参数不合法或 offset 超过文件结尾时抛错.
    """

    checked_offset = validate_positive_read_number(value=offset, field_name="Offset")
    checked_limit = validate_positive_read_number(value=limit, field_name="Limit")
    all_lines = split_read_lines(text)
    total_file_lines = len(all_lines)
    start_line = (checked_offset or 1) - 1
    start_line_display = start_line + 1
    if start_line >= total_file_lines:
        raise ValueError(f"Offset {offset} is beyond end of file ({total_file_lines} lines total)")

    if checked_limit is not None:
        end_line = min(start_line + checked_limit, total_file_lines)
        selected_text = "\n".join(all_lines[start_line:end_line])
        user_limited_lines = end_line - start_line
    else:
        selected_text = "\n".join(all_lines[start_line:])
        user_limited_lines = None

    truncated = truncate_text_head(selected_text)
    if truncated.first_line_exceeds_limit:
        first_line_size = format_size(len(all_lines[start_line].encode("utf-8")))
        return TextReadPage(
            text=(
                f"[Line {start_line_display} is {first_line_size}, exceeds {format_size(DEFAULT_READ_MAX_BYTES)} limit. "
                f"read cannot return this line in one call: {path}]"
            )
        )

    if truncated.truncated:
        end_line_display = start_line_display + truncated.output_lines - 1
        next_offset = end_line_display + 1
        if truncated.truncated_by == "lines":
            notice = (
                f"[Showing lines {start_line_display}-{end_line_display} of {total_file_lines}. "
                f"Use offset={next_offset} to continue.]"
            )
        else:
            notice = (
                f"[Showing lines {start_line_display}-{end_line_display} of {total_file_lines} "
                f"({format_size(DEFAULT_READ_MAX_BYTES)} limit). Use offset={next_offset} to continue.]"
            )
        return TextReadPage(text=f"{truncated.text}\n\n{notice}")

    if user_limited_lines is not None and start_line + user_limited_lines < total_file_lines:
        remaining = total_file_lines - (start_line + user_limited_lines)
        next_offset = start_line + user_limited_lines + 1
        return TextReadPage(
            text=(
                f"{truncated.text}\n\n"
                f"[{remaining} more lines in file. Use offset={next_offset} to continue.]"
            )
        )

    return TextReadPage(text=truncated.text)


def validate_positive_read_number(*, value: int | None, field_name: str) -> int | None:
    """检查 read 的数字参数是不是正整数.

    Args:
        value (int | None): 传进来的参数值.
        field_name (str): 报错里要显示的字段名.

    Returns:
        int | None: 合法时返回归一化后的整数, 没传时返回 `None`.

    Raises:
        ValueError: 参数不是正整数时抛错.
    """

    if value is None:
        return None
    checked = int(value)
    if checked <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return checked


def split_read_lines(text: str) -> list[str]:
    """把文本拆成 read 工具使用的行列表.

    这里会把文件末尾单独那一个换行收掉, 不把它算成多出来的一行空行.
    但真正的空行会继续保留.

    Args:
        text (str): 原始文本.

    Returns:
        list[str]: 用来做分页和截断的行列表.
    """

    if text == "":
        return [""]
    lines = text.splitlines()
    return lines or [""]


def truncate_text_head(text: str) -> TruncatedText:
    """按默认行数和字节上限截断文本头部.

    Args:
        text (str): 要截断的文本.

    Returns:
        TruncatedText: 截断结果.
    """

    lines = split_read_lines(text)
    kept_lines: list[str] = []
    used_bytes = 0
    for index, line in enumerate(lines):
        candidate = line if not kept_lines else f"\n{line}"
        candidate_bytes = len(candidate.encode("utf-8"))
        if not kept_lines and candidate_bytes > DEFAULT_READ_MAX_BYTES:
            return TruncatedText(
                text="",
                output_lines=0,
                truncated=True,
                truncated_by="bytes",
                first_line_exceeds_limit=True,
            )
        if len(kept_lines) >= DEFAULT_READ_MAX_LINES:
            return TruncatedText(
                text="\n".join(kept_lines),
                output_lines=len(kept_lines),
                truncated=True,
                truncated_by="lines",
            )
        if used_bytes + candidate_bytes > DEFAULT_READ_MAX_BYTES:
            return TruncatedText(
                text="\n".join(kept_lines),
                output_lines=len(kept_lines),
                truncated=True,
                truncated_by="bytes",
            )
        kept_lines.append(line)
        used_bytes += candidate_bytes

    _ = index if lines else 0
    return TruncatedText(
        text="\n".join(kept_lines),
        output_lines=len(kept_lines),
        truncated=False,
    )


def format_size(size_bytes: int) -> str:
    """把字节数格式化成简单可读的文字.

    Args:
        size_bytes (int): 字节数.

    Returns:
        str: 简单大小字符串.
    """

    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    if size_bytes >= 1024:
        return f"{round(size_bytes / 1024)}KB"
    return f"{size_bytes}B"


# endregion


__all__ = [
    "DEFAULT_READ_MAX_BYTES",
    "DEFAULT_READ_MAX_LINES",
    "TextReadPage",
    "format_read_text",
    "format_size",
    "truncate_text_head",
]
