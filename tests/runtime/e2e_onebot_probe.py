from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import websockets


@dataclass
class ProbeResult:
    payload: dict[str, Any]
    local_file_read_ok: bool
    validation_error: str = ""
    captured_file_refs: list[str] = field(default_factory=list)


class OneBotProbe:
    def __init__(self, *, url: str, self_id: str = "10000") -> None:
        self.url = url
        self.self_id = self_id
        self._conn = None
        self._task: asyncio.Task[None] | None = None
        self.results: asyncio.Queue[ProbeResult] = asyncio.Queue()
        self.errors: list[str] = []
        self._message_id = 0

    async def connect(self) -> None:
        self._conn = await websockets.connect(
            self.url,
            additional_headers={"X-Self-ID": self.self_id},
        )
        self._task = asyncio.create_task(self._serve())

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._conn is not None:
            await self._conn.close()

    async def next_result(self, *, timeout: float = 5.0) -> ProbeResult:
        return await asyncio.wait_for(self.results.get(), timeout=timeout)

    async def _serve(self) -> None:
        assert self._conn is not None
        async for raw in self._conn:
            payload = json.loads(raw)
            result = self._validate_payload(payload)
            await self.results.put(result)
            if result.validation_error:
                self.errors.append(result.validation_error)
                # Intentionally do not ack negative cases; caller should observe timeout / no-ack.
                continue
            self._message_id += 1
            await self._conn.send(
                json.dumps(
                    {
                        "status": "ok",
                        "retcode": 0,
                        "message_id": f"probe-msg-{self._message_id}",
                        "echo": payload.get("echo"),
                    }
                )
            )

    def _validate_payload(self, payload: dict[str, Any]) -> ProbeResult:
        action = str(payload.get("action", "") or "")
        params = dict(payload.get("params", {}) or {})
        messages = list(params.get("message", []) or [])
        captured_file_refs: list[str] = []
        for segment in messages:
            seg_type = str(segment.get("type", "") or "")
            if seg_type not in {"image", "file", "record", "video"}:
                continue
            data = dict(segment.get("data", {}) or {})
            file_ref = str(data.get("file", "") or "").strip()
            if not file_ref:
                return ProbeResult(
                    payload=payload,
                    local_file_read_ok=False,
                    validation_error="empty file ref",
                )
            captured_file_refs.append(file_ref)
            if file_ref.startswith(("http://", "https://", "data:", "base64://")):
                continue
            local_path = self._file_ref_to_local_path(file_ref)
            if local_path is None or not local_path.exists() or not local_path.is_file():
                return ProbeResult(
                    payload=payload,
                    local_file_read_ok=False,
                    validation_error=f"local file unreadable: {file_ref}",
                    captured_file_refs=captured_file_refs,
                )
            local_path.read_bytes()
        return ProbeResult(
            payload=payload,
            local_file_read_ok=True,
            captured_file_refs=captured_file_refs,
        )

    @staticmethod
    def _file_ref_to_local_path(file_ref: str) -> Path | None:
        if file_ref.startswith("file://"):
            parsed = urlparse(file_ref)
            return Path(unquote(parsed.path))
        if file_ref.startswith("/"):
            return Path(file_ref)
        return None
