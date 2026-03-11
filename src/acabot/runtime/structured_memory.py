"""runtime.structured_memory 提供最小 structured memory 实现.

组件关系:

    MemoryBroker
      |
      +--> StoreBackedMemoryRetriever
      |
      `--> StructuredMemoryExtractor
              |
              v
          MemoryStore

这一层先实现最小闭环:
- retrieval 从 MemoryStore 读取长期记忆项
- extraction 在 run 收尾后写入 draft episodic memory

这一版故意不做:
- sticky note 自动提取
- reference 文档切片
- task scratchpad
- 向量检索
"""

from __future__ import annotations

from dataclasses import dataclass

from .memory_broker import (
    MemoryBlock,
    MemoryRetrievalRequest,
    MemoryWriteRequest,
)
from .models import MemoryItem
from .stores import MemoryStore

_KNOWN_MEMORY_SCOPES = ("relationship", "user", "channel", "global")
_KNOWN_MEMORY_TYPES = (
    "sticky_note",
    "semantic",
    "relationship",
    "episodic",
    "reference",
    "task",
)


@dataclass(slots=True)
class _RequestedMemoryHints:
    """从 control plane hint 解析出的 retrieval / extraction 条件.

    Attributes:
        scopes (list[str]): 允许读取或写入的 scope 列表.
        memory_types (list[str]): 允许读取的 memory_type 列表.
    """

    scopes: list[str]
    memory_types: list[str]


# region retrieval
@dataclass(slots=True)
class StoreBackedMemoryRetriever:
    """基于 MemoryStore 的 retriever.

    Attributes:
        store (MemoryStore): 长期记忆项持久化后端.
        per_scope_limit (int): 每个 scope 最多取回多少条记忆项.
    """

    store: MemoryStore
    per_scope_limit: int = 3

    async def __call__(self, request: MemoryRetrievalRequest) -> list[MemoryBlock]:
        """从 MemoryStore 检索长期记忆并转换成 MemoryBlock.

        Args:
            request: 标准化后的 retrieval request.

        Returns:
            一组可注入给 runtime 的 MemoryBlock.
        """

        hints = _parse_requested_memory_hints(
            request.requested_scopes,
            requested_memory_types=request.requested_memory_types,
        )
        blocks: list[MemoryBlock] = []

        for scope in hints.scopes:
            scope_key = _scope_key_for_request(scope=scope, request=request)
            items = await self.store.find(
                scope=scope,
                scope_key=scope_key,
                memory_types=hints.memory_types or None,
                limit=self.per_scope_limit,
            )
            for item in items:
                blocks.append(self._to_block(item))

        return blocks

    @staticmethod
    def _to_block(item: MemoryItem) -> MemoryBlock:
        """把 MemoryItem 转成可注入的 MemoryBlock.

        Args:
            item: 待转换的长期记忆项.

        Returns:
            对应的 MemoryBlock.
        """

        return MemoryBlock(
            title=f"{item.memory_type}:{item.scope}",
            content=item.content,
            scope=item.scope,
            source_ids=[item.memory_id],
            metadata={
                "memory_type": item.memory_type,
                "edit_mode": item.edit_mode,
                "tags": list(item.tags),
                **item.metadata,
            },
        )


# endregion


# region extraction
@dataclass(slots=True)
class StructuredMemoryExtractor:
    """最小 structured memory extractor.

    Attributes:
        store (MemoryStore): 长期记忆项持久化后端.
    """

    store: MemoryStore

    async def __call__(self, request: MemoryWriteRequest) -> None:
        """在 run 收尾后写入最小 episodic memory.

        Args:
            request: 标准化后的 write-back request.
        """

        if not bool(request.metadata.get("extract_to_memory", False)):
            return
        if request.run_status not in {"completed", "completed_with_errors"}:
            return

        content = self._build_episodic_content(request)
        if not content:
            return

        scope = self._pick_scope(request)
        item = MemoryItem(
            memory_id=f"memory:{request.run_id}:episodic",
            scope=scope,
            scope_key=_scope_key_for_request(scope=scope, request=request),
            memory_type="episodic",
            content=content,
            edit_mode="draft",
            author="extractor",
            confidence=self._confidence(request),
            source_run_id=request.run_id,
            source_event_id=request.event_id,
            tags=["episodic", request.event_type, *request.event_tags],
            metadata={
                "run_mode": request.run_mode,
                "run_status": request.run_status,
                "event_type": request.event_type,
                "event_policy_id": request.metadata.get("event_policy_id", ""),
            },
            created_at=request.event_timestamp,
            updated_at=request.event_timestamp,
        )
        await self.store.upsert(item)

    def _pick_scope(self, request: MemoryWriteRequest) -> str:
        """根据 control plane hint 选择本轮写入的 primary scope.

        Args:
            request: 标准化后的 write-back request.

        Returns:
            当前 episodic memory 应写入的 scope.
        """

        hints = _parse_requested_memory_hints(request.requested_scopes)
        if hints.scopes:
            return hints.scopes[0]
        return "relationship"

    @staticmethod
    def _confidence(request: MemoryWriteRequest) -> float:
        """估算本轮 episodic memory 的置信度.

        Args:
            request: 标准化后的 write-back request.

        Returns:
            一个 0 到 1 之间的置信度.
        """

        if request.delivered_messages:
            return 0.6
        return 0.3

    @staticmethod
    def _build_episodic_content(request: MemoryWriteRequest) -> str:
        """把当前 run 投影成一条最小 episodic memory.

        Args:
            request: 标准化后的 write-back request.

        Returns:
            适合持久化的 episodic 文本.
        """

        # region 内容拼装
        lines: list[str] = [f"event_type: {request.event_type}"]
        if request.metadata.get("thread_summary"):
            lines.append(f"thread_summary: {request.metadata['thread_summary']}")
        if request.user_content:
            lines.append(f"user: {request.user_content}")
        for index, message in enumerate(request.delivered_messages, start=1):
            lines.append(f"assistant_{index}: {message}")

        meaningful = [line for line in lines if line.split(": ", 1)[-1].strip()]
        if len(meaningful) <= 1:
            return ""
        return "\n".join(meaningful)
        # endregion


# endregion


# region 共享helper
def _parse_requested_memory_hints(
    values: list[str],
    *,
    requested_memory_types: list[str] | None = None,
) -> _RequestedMemoryHints:
    """把 control plane 给出的 hint 拆成 scopes 和 memory_types.

    Args:
        values: `event_memory_scopes` 当前携带的 hint 列表.
        requested_memory_types: 显式声明的 memory types.

    Returns:
        一份拆分后的 _RequestedMemoryHints.
    """

    scopes = [value for value in values if value in _KNOWN_MEMORY_SCOPES]
    memory_types = list(requested_memory_types or [])
    if not memory_types:
        memory_types = [value for value in values if value in _KNOWN_MEMORY_TYPES]
    if not scopes:
        scopes = ["relationship", "user", "channel", "global"]
    return _RequestedMemoryHints(scopes=scopes, memory_types=memory_types)


def _scope_key_for_request(
    *,
    scope: str,
    request: MemoryRetrievalRequest | MemoryWriteRequest,
) -> str:
    """根据 request 计算某个 scope 的 key.

    Args:
        scope: 目标 scope 名称.
        request: retrieval 或 write-back request.

    Returns:
        对应 scope 的 key.
    """

    if scope == "relationship":
        return f"{request.actor_id}|{request.channel_scope}"
    if scope == "user":
        return request.actor_id
    if scope == "channel":
        return request.channel_scope
    if scope == "global":
        return "global"
    return request.channel_scope


# endregion
