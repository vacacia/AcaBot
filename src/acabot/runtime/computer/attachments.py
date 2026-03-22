"""runtime.computer.attachments 负责把外部附件拉进 Work World.

模块和下面几层相连:
- `ComputerRuntime.stage_attachments()`
- `GatewayAttachmentResolver` 先尝试直接 URL, 再尝试 gateway API 二次解析
- 附件落地后会生成 `AttachmentSnapshot`, 供 runtime、tools 和 prompt 使用

这里会把聊天里的附件下载到当前 thread 的 workspace 下面:
- 宿主机目录大致是 `.../threads/<thread>/workspace/attachments/<category>/<event_id>/<filename>`
- 前台工具该用的路径是 `/workspace/attachments/<category>/<event_id>/<filename>`

现在 runtime 会同时记住几种信息:
- `staged_path`: 宿主机上的真实文件路径
- `metadata["world_path"]`: 给前台文件工具用的 `/workspace/...` 路径
- `metadata["execution_path"]`: shell 那边实际会看到的路径

把“平台附件引用”变成“宿主机上的真实文件”, 再接进前台能用的工作区路径.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from acabot.types import EventAttachment

from .contracts import (
    AttachmentSnapshot,
    AttachmentResolver,
    ComputerRuntimeConfig,
)
from .workspace import sanitize_filename


# region resolver
class UrlAttachmentResolver:
    """处理直接 URL 和 file URL 的附件解析器."""

    async def stage(
        self,
        *,
        attachment: EventAttachment,
        event_id: str,
        attachment_index: int,
        target_dir: Path,
        config: ComputerRuntimeConfig,
        gateway: Any | None,
    ) -> AttachmentSnapshot:
        """把一个 URL/file URL 类型附件拉到宿主机目录里.

        Args:
            attachment (EventAttachment): 当前附件对象.
            event_id (str): 当前事件 ID.
            attachment_index (int): 当前附件在事件里的顺序.
            target_dir (Path): 附件最终写入目录.
            config (ComputerRuntimeConfig): computer 运行配置.
            gateway (Any | None): 当前 gateway. 这里不会使用, 只是保持协议一致.

        Returns:
            AttachmentSnapshot: 当前附件的落地结果.
        """

        _ = gateway
        source = str(attachment.source or "")
        snapshot = AttachmentSnapshot(
            event_id=event_id,
            attachment_index=attachment_index,
            type=attachment.type,
            original_source=source,
            source_kind=infer_source_kind(source),
            metadata=dict(attachment.metadata),
        )
        parsed = urlparse(source)
        if parsed.scheme in {"http", "https", "file"}:
            filename = sanitize_filename(attachment.name or f"attachment-{attachment_index}")
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / filename
            last_error = ""
            for _attempt in range(config.attachment_download_retries + 1):
                try:
                    size = await asyncio.wait_for(
                        asyncio.to_thread(
                            download_attachment,
                            source,
                            target,
                            config.max_attachment_size_bytes,
                        ),
                        timeout=config.attachment_download_timeout_sec,
                    )
                    snapshot.staged_path = str(target)
                    snapshot.size_bytes = size
                    snapshot.download_status = "staged"
                    return snapshot
                except Exception as exc:  # noqa: PERF203
                    last_error = str(exc)
            snapshot.download_status = "failed"
            snapshot.error = last_error or "download failed"
            return snapshot

        snapshot.download_status = "failed"
        snapshot.error = "unsupported attachment source"
        return snapshot


class GatewayAttachmentResolver:
    """先尝试 URL, 不行再尝试 gateway.call_api 二次解析."""

    def __init__(self) -> None:
        """初始化 gateway 附件解析器."""

        self.url_resolver = UrlAttachmentResolver()

    async def stage(
        self,
        *,
        attachment: EventAttachment,
        event_id: str,
        attachment_index: int,
        target_dir: Path,
        config: ComputerRuntimeConfig,
        gateway: Any | None,
    ) -> AttachmentSnapshot:
        """把一个附件解析并落地.

        这里会先尝试把附件当成 URL 直接下载.
        如果失败, 再尝试通过 gateway API 把平台文件 ID 解成真实 URL.

        Args:
            attachment (EventAttachment): 当前附件对象.
            event_id (str): 当前事件 ID.
            attachment_index (int): 当前附件在事件里的顺序.
            target_dir (Path): 附件最终写入目录.
            config (ComputerRuntimeConfig): computer 运行配置.
            gateway (Any | None): 当前 gateway, 需要支持 `call_api()` 才能做二次解析.

        Returns:
            AttachmentSnapshot: 当前附件的落地结果.
        """

        direct = await self.url_resolver.stage(
            attachment=attachment,
            event_id=event_id,
            attachment_index=attachment_index,
            target_dir=target_dir,
            config=config,
            gateway=gateway,
        )
        if direct.download_status == "staged":
            return direct
        if gateway is None or not callable(getattr(gateway, "call_api", None)):
            return direct

        source = str(attachment.source or attachment.metadata.get("id") or "")
        if not source:
            return direct
        for action in attachment_api_candidates(attachment.type):
            try:
                response = await gateway.call_api(action, {"file_id": source})
            except Exception as exc:  # noqa: PERF203
                direct.error = str(exc)
                continue
            if str(response.get("status", "")) != "ok":
                continue
            resolved = extract_resolved_attachment_source(response.get("data"))
            if not resolved:
                continue
            resolved_attachment = EventAttachment(
                type=attachment.type,
                source=resolved,
                name=attachment.name,
                mime_type=attachment.mime_type,
                metadata={
                    **dict(attachment.metadata),
                    "resolved_via": action,
                },
            )
            staged = await self.url_resolver.stage(
                attachment=resolved_attachment,
                event_id=event_id,
                attachment_index=attachment_index,
                target_dir=target_dir,
                config=config,
                gateway=gateway,
            )
            if staged.download_status == "staged":
                staged.source_kind = "platform_api_resolved"
                return staged
        return direct


# endregion


# region helpers
def infer_source_kind(source: str) -> str:
    """推断当前附件来源属于哪一种来源类型.

    Args:
        source (str): 原始附件来源字符串.

    Returns:
        str: 当前来源类型.
    """

    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        return "direct_url"
    if parsed.scheme == "file":
        return "platform_api_resolved"
    if source:
        return "platform_file_id"
    return "unknown"


def attachment_api_candidates(attachment_type: str) -> list[str]:
    """给指定附件类型返回可能可用的 gateway API 名字列表.

    Args:
        attachment_type (str): 当前附件类型, 例如 `image` 或 `file`.

    Returns:
        list[str]: 按优先顺序尝试的 API 名列表.
    """

    mapping = {
        "image": ["get_image", "get_file", "get_msg"],
        "file": ["get_file", "get_group_file_url"],
        "audio": ["get_record", "get_file"],
        "video": ["get_video", "get_file"],
    }
    return list(mapping.get(attachment_type, ["get_file"]))


def extract_resolved_attachment_source(data: Any) -> str:
    """从 gateway API 返回值里尽量提取出真实附件地址.

    Args:
        data (Any): gateway API 返回的 `data` 字段.

    Returns:
        str: 解析出来的 URL / path. 解析失败时返回空字符串.
    """

    if isinstance(data, str):
        return data
    if not isinstance(data, dict):
        return ""
    for key in ("url", "download_url", "file", "path", "src"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    inner_file = data.get("file")
    if isinstance(inner_file, dict):
        for key in ("url", "download_url", "path"):
            value = inner_file.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def download_attachment(source: str, target: Path, max_size_bytes: int) -> int:
    """把附件下载到目标文件.

    Args:
        source (str): 附件来源地址, 支持 `http/https/file` URL.
        target (Path): 目标文件路径.
        max_size_bytes (int): 允许的最大文件大小.

    Returns:
        int: 实际下载字节数.

    Raises:
        RuntimeError: 下载超出大小限制时抛出.
        Exception: 网络、文件系统或 URL 打开失败时, 异常会继续抛给上层处理.
    """

    request = Request(source, headers={"User-Agent": "AcaBot/1.0"})
    size = 0
    with urlopen(request) as resp, target.open("wb") as handle:
        while True:
            chunk = resp.read(1024 * 64)
            if not chunk:
                break
            size += len(chunk)
            if size > max_size_bytes:
                raise RuntimeError("attachment exceeds max size")
            handle.write(chunk)
    return size


# endregion


__all__ = [
    "AttachmentResolver",
    "GatewayAttachmentResolver",
    "UrlAttachmentResolver",
]
