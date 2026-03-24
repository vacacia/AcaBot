"""runtime.memory.file_backed.retrievers 提供文件型记忆适配器.

Retriever 只管适配格式
Source 只管获取数据
"""

from __future__ import annotations

from dataclasses import dataclass

from ...soul import SoulSource
from ..memory_broker import MemoryAssemblySpec, MemoryBlock, SharedMemoryRetrievalRequest
from .sticky_notes import StickyNotesSource


@dataclass(slots=True)
class SelfFileRetriever:
    """把 `/self` 文件内容适配成统一 MemoryBlock."""

    source: SoulSource
    max_daily_files: int = 2

    async def __call__(self, request: SharedMemoryRetrievalRequest) -> list[MemoryBlock]:
        _ = request
        content = self.source.build_recent_context_text(max_daily_files=self.max_daily_files).strip()
        if not content:
            return []
        return [
            MemoryBlock(
                content=content,
                source="self",
                scope="global",
                source_ids=["self:recent"],
                assembly=MemoryAssemblySpec(
                    target_slot="message_prefix",
                    priority=900,
                ),
                metadata={
                    "source_backend": "file_backed",
                },
            )
        ]


@dataclass(slots=True)
class StickyNotesFileRetriever:
    """把 sticky notes 文件真源适配成统一 MemoryBlock."""

    source: StickyNotesSource

    async def __call__(self, request: SharedMemoryRetrievalRequest) -> list[MemoryBlock]:
        raw_allowed_scopes = list(request.metadata.get("sticky_note_scopes", []) or [])
        if not raw_allowed_scopes:
            return []

        allowed_scopes = [
            str(scope)
            for scope in raw_allowed_scopes
            if str(scope) in set(self.source.PRODUCT_SCOPES)
        ]
        if not allowed_scopes:
            return []

        blocks: list[MemoryBlock] = []
        for scope in allowed_scopes:
            scope_key = self._scope_key(scope=scope, request=request)
            if not scope_key:
                continue
            for note in self.source.list_notes(scope=scope, scope_key=scope_key):
                key = str(note.get("key", "") or "").strip()
                if not key:
                    continue
                try:
                    pair = self.source.read_pair(scope=scope, scope_key=scope_key, key=key)
                except FileNotFoundError:
                    continue
                readonly = str(pair.get("readonly", {}).get("content", "") or "").strip()
                editable = str(pair.get("editable", {}).get("content", "") or "").strip()
                if not readonly and not editable:
                    continue
                lines = [f"[{scope}/{scope_key}/{key}]"]
                if readonly:
                    lines.append(f"readonly: {readonly}")
                if editable:
                    lines.append(f"editable: {editable}")
                blocks.append(
                    MemoryBlock(
                        content="\n".join(lines),
                        source="sticky_notes",
                        scope=scope,
                        source_ids=[f"sticky:{scope}:{scope_key}:{key}"],
                        assembly=MemoryAssemblySpec(
                            target_slot="message_prefix",
                            priority=800,
                        ),
                        metadata={
                            "edit_mode": "draft" if editable else "readonly",
                            "note_key": key,
                            "scope_key": scope_key,
                            "source_backend": "file_backed",
                        },
                    )
                )
        return blocks

    @staticmethod
    def _scope_key(*, scope: str, request: SharedMemoryRetrievalRequest) -> str:
        if scope == "user":
            return str(request.actor_id or "")
        if scope == "channel":
            return str(request.channel_scope or "")
        return ""
