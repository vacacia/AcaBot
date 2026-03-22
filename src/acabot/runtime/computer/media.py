"""runtime.computer.media 负责 computer 里的图片识别和图片返回格式.

这个文件只做两件事:
- 根据文件字节判断是不是当前支持的图片
- 把图片字节转成模型能直接看的消息块

它会被 `runtime.computer.runtime` 调用.
它不负责 world path 解析, 也不负责 tool 文案之外的别的逻辑.
"""

from __future__ import annotations

import base64
from typing import Any


# region detect
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
GIF87A_SIGNATURE = b"GIF87a"
GIF89A_SIGNATURE = b"GIF89a"
RIFF_SIGNATURE = b"RIFF"
WEBP_SIGNATURE = b"WEBP"


def detect_supported_image_mime(data: bytes) -> str:
    """根据文件字节判断是不是当前支持的图片.

    Args:
        data (bytes): 文件原始字节.

    Returns:
        str: 支持的图片 MIME. 不是支持的图片时返回空字符串.
    """

    if data.startswith(PNG_SIGNATURE):
        return "image/png"
    if data.startswith(JPEG_SIGNATURE):
        return "image/jpeg"
    if data.startswith(GIF87A_SIGNATURE) or data.startswith(GIF89A_SIGNATURE):
        return "image/gif"
    if data.startswith(RIFF_SIGNATURE) and len(data) >= 12 and data[8:12] == WEBP_SIGNATURE:
        return "image/webp"
    return ""


# endregion


# region encode

def image_data_uri(data: bytes, mime_type: str) -> str:
    """把图片字节转成 data URI.

    Args:
        data (bytes): 图片原始字节.
        mime_type (str): 图片 MIME.

    Returns:
        str: `data:image/...;base64,...` 形式的字符串.
    """

    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


# endregion


# region blocks

def build_read_image_content(*, data: bytes, mime_type: str) -> list[dict[str, Any]]:
    """把图片文件包装成 read 工具要返回的内容.

    Args:
        data (bytes): 图片原始字节.
        mime_type (str): 图片 MIME.

    Returns:
        list[dict[str, Any]]: 说明文字和图片块.
    """

    return [
        {"type": "text", "text": f"Read image file [{mime_type}]"},
        {"type": "image_url", "image_url": {"url": image_data_uri(data, mime_type)}},
    ]


# endregion


__all__ = [
    "build_read_image_content",
    "detect_supported_image_mime",
    "image_data_uri",
]
