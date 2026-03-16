"""runtime.computer.attachments 处理附件 staging."""

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


def infer_source_kind(source: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        return "direct_url"
    if parsed.scheme == "file":
        return "platform_api_resolved"
    if source:
        return "platform_file_id"
    return "unknown"


def attachment_api_candidates(attachment_type: str) -> list[str]:
    mapping = {
        "image": ["get_image", "get_file", "get_msg"],
        "file": ["get_file", "get_group_file_url"],
        "audio": ["get_record", "get_file"],
        "video": ["get_video", "get_file"],
    }
    return list(mapping.get(attachment_type, ["get_file"]))


def extract_resolved_attachment_source(data: Any) -> str:
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


__all__ = [
    "AttachmentResolver",
    "GatewayAttachmentResolver",
    "UrlAttachmentResolver",
]
