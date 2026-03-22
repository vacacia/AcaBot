"""runtime.computer.editing 负责文字替换规则.

这个文件只处理文字编辑本身:
- 规范化换行
- 保留 UTF-8 BOM
- 做精确匹配和宽松匹配
- 生成 diff

它给 `runtime.computer.runtime` 提供一个清楚的入口, 让 runtime 只负责
world path 和文件读写, 不用自己揉一堆文字细节.
"""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import unicodedata


# region result
@dataclass(slots=True)
class PreparedTextEdit:
    """一次文字替换算出来的结果.

    Attributes:
        content (str): 最终要写回文件的文字.
        diff (str): 给前台工具看的 diff 文本.
        first_changed_line (int): 第一处改动所在的行号, 从 1 开始.
    """

    content: str
    diff: str
    first_changed_line: int


@dataclass(slots=True)
class TextMatchResult:
    """一次旧文本匹配结果.

    Attributes:
        found (bool): 有没有找到可用的匹配.
        index (int): 匹配起点.
        match_length (int): 匹配长度.
        used_fuzzy_match (bool): 这次是不是走了宽松匹配.
        content_for_replacement (str): 真正用来做替换的文字版本.
    """

    found: bool
    index: int
    match_length: int
    used_fuzzy_match: bool
    content_for_replacement: str


# endregion


# region normalize
def detect_line_ending(content: str) -> str:
    """判断当前文件原本使用的换行风格.

    Args:
        content (str): 原始文字内容.

    Returns:
        str: `\n` 或 `\r\n`.
    """

    crlf_index = content.find("\r\n")
    lf_index = content.find("\n")
    if lf_index == -1:
        return "\n"
    if crlf_index == -1:
        return "\n"
    return "\r\n" if crlf_index < lf_index else "\n"


def normalize_to_lf(text: str) -> str:
    """把各种换行统一成 `\n`.

    Args:
        text (str): 原始文字.

    Returns:
        str: 统一后的文字.
    """

    return text.replace("\r\n", "\n").replace("\r", "\n")


def restore_line_endings(text: str, line_ending: str) -> str:
    """把统一后的 `\n` 恢复成原来的换行风格.

    Args:
        text (str): 已经统一成 `\n` 的文字.
        line_ending (str): 原文件使用的换行风格.

    Returns:
        str: 恢复后的文字.
    """

    if line_ending == "\r\n":
        return text.replace("\n", "\r\n")
    return text


def strip_bom(content: str) -> tuple[str, str]:
    """拆掉开头的 UTF-8 BOM, 方便后面匹配.

    Args:
        content (str): 原始文字.

    Returns:
        tuple[str, str]: `(bom, text)`.
    """

    if content.startswith("\ufeff"):
        return "\ufeff", content[1:]
    return "", content


def normalize_for_fuzzy_match(text: str) -> str:
    """把文字变成更容易匹配的样子.

    这里会做几件事:
    - 统一 Unicode 兼容写法
    - 去掉每行末尾多余空白
    - 把智能引号换成普通引号
    - 把各种横线换成 `-`
    - 把特殊空格换成普通空格

    Args:
        text (str): 原始文字.

    Returns:
        str: 处理后的文字.
    """

    normalized = unicodedata.normalize("NFKC", text)
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    normalized = normalized.replace("\u2018", "'").replace("\u2019", "'")
    normalized = normalized.replace("\u201a", "'").replace("\u201b", "'")
    normalized = normalized.replace("\u201c", '"').replace("\u201d", '"')
    normalized = normalized.replace("\u201e", '"').replace("\u201f", '"')
    for char in ["\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212"]:
        normalized = normalized.replace(char, "-")
    for char in [
        "\u00a0",
        "\u2002",
        "\u2003",
        "\u2004",
        "\u2005",
        "\u2006",
        "\u2007",
        "\u2008",
        "\u2009",
        "\u200a",
        "\u202f",
        "\u205f",
        "\u3000",
    ]:
        normalized = normalized.replace(char, " ")
    return normalized


# endregion


# region match
def find_text_match(content: str, old_text: str) -> TextMatchResult:
    """先精确找, 找不到再试宽松匹配.

    Args:
        content (str): 已经统一成 `\n` 的文件内容.
        old_text (str): 已经统一成 `\n` 的旧文本.

    Returns:
        TextMatchResult: 匹配结果.
    """

    exact_index = content.find(old_text)
    if exact_index != -1:
        return TextMatchResult(
            found=True,
            index=exact_index,
            match_length=len(old_text),
            used_fuzzy_match=False,
            content_for_replacement=content,
        )

    fuzzy_content = normalize_for_fuzzy_match(content)
    fuzzy_old_text = normalize_for_fuzzy_match(old_text)
    if not fuzzy_old_text:
        return TextMatchResult(
            found=False,
            index=-1,
            match_length=0,
            used_fuzzy_match=False,
            content_for_replacement=content,
        )
    fuzzy_index = fuzzy_content.find(fuzzy_old_text)
    if fuzzy_index == -1:
        return TextMatchResult(
            found=False,
            index=-1,
            match_length=0,
            used_fuzzy_match=False,
            content_for_replacement=content,
        )

    return TextMatchResult(
        found=True,
        index=fuzzy_index,
        match_length=len(fuzzy_old_text),
        used_fuzzy_match=True,
        content_for_replacement=fuzzy_content,
    )


def count_text_occurrences(content: str, old_text: str) -> int:
    """按宽松匹配规则统计旧文本出现了几次.

    Args:
        content (str): 已经统一成 `\n` 的文件内容.
        old_text (str): 已经统一成 `\n` 的旧文本.

    Returns:
        int: 匹配次数.
    """

    fuzzy_content = normalize_for_fuzzy_match(content)
    fuzzy_old_text = normalize_for_fuzzy_match(old_text)
    if not fuzzy_old_text:
        return 0
    return fuzzy_content.count(fuzzy_old_text)


# endregion


# region diff
def generate_diff_string(old_content: str, new_content: str) -> tuple[str, int]:
    """生成给前台工具看的 diff 文本.

    Args:
        old_content (str): 替换前的文字.
        new_content (str): 替换后的文字.

    Returns:
        tuple[str, int]: `(diff_text, first_changed_line)`.
    """

    old_lines = old_content.split("\n")
    new_lines = new_content.split("\n")
    line_width = len(str(max(len(old_lines), len(new_lines), 1)))
    output: list[str] = []
    old_line_no = 1
    new_line_no = 1
    first_changed_line = 1
    found_change = False

    for line in difflib.ndiff(old_lines, new_lines):
        if line.startswith("? "):
            continue
        if line.startswith("- "):
            output.append(f"-{str(old_line_no).rjust(line_width)} {line[2:]}")
            if not found_change:
                first_changed_line = new_line_no
                found_change = True
            old_line_no += 1
            continue
        if line.startswith("+ "):
            output.append(f"+{str(new_line_no).rjust(line_width)} {line[2:]}")
            if not found_change:
                first_changed_line = new_line_no
                found_change = True
            new_line_no += 1
            continue
        output.append(f" {str(old_line_no).rjust(line_width)} {line[2:]}")
        old_line_no += 1
        new_line_no += 1

    return "\n".join(output), first_changed_line


# endregion


# region apply
def prepare_text_edit(*, path: str, content: str, old_text: str, new_text: str) -> PreparedTextEdit:
    """按 pi 的规则准备一次文字替换.

    Args:
        path (str): 当前文件的 world path.
        content (str): 文件原始文字.
        old_text (str): 要替换掉的旧文本.
        new_text (str): 要写入的新文本.

    Returns:
        PreparedTextEdit: 算好的编辑结果.

    Raises:
        ValueError: 旧文本找不到、出现多次, 或替换后没有变化时抛出.
    """

    bom, text_without_bom = strip_bom(content)
    line_ending = detect_line_ending(text_without_bom)
    normalized_content = normalize_to_lf(text_without_bom)
    normalized_old_text = normalize_to_lf(old_text)
    normalized_new_text = normalize_to_lf(new_text)

    match = find_text_match(normalized_content, normalized_old_text)
    if not match.found:
        raise ValueError(
            f"Could not find the exact text in {path}. "
            "The old text must match exactly including all whitespace and newlines."
        )

    occurrences = count_text_occurrences(normalized_content, normalized_old_text)
    if occurrences > 1:
        raise ValueError(
            f"Found {occurrences} occurrences of the text in {path}. "
            "The text must be unique. Please provide more context to make it unique."
        )

    base_content = match.content_for_replacement
    updated_content = (
        base_content[:match.index]
        + normalized_new_text
        + base_content[match.index + match.match_length :]
    )
    if base_content == updated_content:
        raise ValueError(
            f"No changes made to {path}. "
            "The replacement produced identical content."
        )

    diff, first_changed_line = generate_diff_string(base_content, updated_content)
    final_content = bom + restore_line_endings(updated_content, line_ending)
    return PreparedTextEdit(
        content=final_content,
        diff=diff,
        first_changed_line=first_changed_line,
    )


# endregion


__all__ = [
    "PreparedTextEdit",
    "TextMatchResult",
    "count_text_occurrences",
    "detect_line_ending",
    "find_text_match",
    "generate_diff_string",
    "normalize_for_fuzzy_match",
    "normalize_to_lf",
    "prepare_text_edit",
    "restore_line_endings",
    "strip_bom",
]
