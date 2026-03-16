"""runtime.sticky_notes 提供 sticky note 的窄版服务层.

组件关系:

    RuntimePlugin
        |
        v
    StickyNotesService
        |
        v
     MemoryStore

这一层只暴露 sticky note 的受控操作:
- put
- get
- list
- delete

它不暴露整个 MemoryStore, 避免 runtime plugin 绕过 control plane
直接乱写 `semantic / relationship / episodic` 等内部记忆层.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import TYPE_CHECKING, Any, Literal

from ..contracts import MemoryEditMode, MemoryItem
from ..storage.stores import MemoryStore

if TYPE_CHECKING:
    from ..tool_broker import ToolExecutionContext

StickyScope = Literal["relationship", "user", "channel", "global"]
_KNOWN_SCOPES: tuple[StickyScope, ...] = ("relationship", "user", "channel", "global")


# region service
@dataclass(slots=True)
class StickyNotesService:
    """Sticky note 的受控服务层.

    Attributes:
        store (MemoryStore): 长期记忆项持久化后端.
        default_scope (StickyScope): 未显式声明时默认写入的 scope.
    """

    store: MemoryStore
    default_scope: StickyScope = "relationship"

    async def put_note(
        self,
        *,
        ctx: ToolExecutionContext,
        key: str,
        content: str,
        scope: StickyScope | None = None,
        scope_key: str | None = None,
        edit_mode: MemoryEditMode = "readonly",
        tags: list[str] | None = None,
        author: str = "user",
        metadata: dict[str, Any] | None = None,
    ) -> MemoryItem:
        """插入或更新一条 sticky note.

        Args:
            ctx: 当前工具执行上下文.
            key: 这条 sticky note 的稳定键.
            content: sticky note 正文.
            scope: 可选 scope. 缺省时按上下文推断.
            scope_key: 可选 scope_key. 缺省时按上下文推断.
            edit_mode: 当前 sticky note 的编辑模式.
            tags: 附加标签列表.
            author: 写入者标识.
            metadata: 附加元数据.

        Returns:
            已写入的 MemoryItem.
        """

        normalized_key = self._normalize_key(key)
        note_scope = self._resolve_scope(ctx=ctx, scope=scope)
        note_scope_key = self._resolve_scope_key(
            ctx=ctx,
            scope=note_scope,
            scope_key=scope_key,
        )
        now = self._timestamp(ctx)
        item = MemoryItem(
            memory_id=self._build_memory_id(
                scope=note_scope,
                scope_key=note_scope_key,
                key=normalized_key,
            ),
            scope=note_scope,
            scope_key=note_scope_key,
            memory_type="sticky_note",
            content=self._normalize_content(content),
            edit_mode=edit_mode,
            author=str(author).strip() or "user",
            confidence=1.0 if edit_mode == "readonly" else 0.7,
            source_run_id=ctx.run_id,
            source_event_id=str(ctx.metadata.get("event_id", "") or "") or None,
            tags=self._normalize_tags(tags),
            metadata={
                "note_key": normalized_key,
                "platform": str(ctx.metadata.get("platform", "") or ""),
                **dict(metadata or {}),
            },
            created_at=now,
            updated_at=now,
        )
        existing = await self.get_note(
            ctx=ctx,
            key=normalized_key,
            scope=note_scope,
            scope_key=note_scope_key,
        )
        if existing is not None:
            item.created_at = existing.created_at
            item.updated_at = now
        await self.store.upsert(item)
        return item

    async def get_note(
        self,
        *,
        ctx: ToolExecutionContext,
        key: str,
        scope: StickyScope | None = None,
        scope_key: str | None = None,
    ) -> MemoryItem | None:
        """读取一条 sticky note.

        Args:
            ctx: 当前工具执行上下文.
            key: 目标 note_key.
            scope: 可选 scope. 缺省时按上下文推断.
            scope_key: 可选 scope_key. 缺省时按上下文推断.

        Returns:
            命中的 MemoryItem. 不存在时返回 None.
        """

        normalized_key = self._normalize_key(key)
        note_scope = self._resolve_scope(ctx=ctx, scope=scope)
        note_scope_key = self._resolve_scope_key(
            ctx=ctx,
            scope=note_scope,
            scope_key=scope_key,
        )
        items = await self.store.find(
            scope=note_scope,
            scope_key=note_scope_key,
            memory_types=["sticky_note"],
        )
        for item in items:
            if str(item.metadata.get("note_key", "") or "") == normalized_key:
                return item
        return None

    async def list_notes(
        self,
        *,
        ctx: ToolExecutionContext,
        scope: StickyScope | None = None,
        scope_key: str | None = None,
        edit_modes: list[MemoryEditMode] | None = None,
        limit: int = 20,
    ) -> list[MemoryItem]:
        """列出当前 scope 下的 sticky notes.

        Args:
            ctx: 当前工具执行上下文.
            scope: 可选 scope. 缺省时按上下文推断.
            scope_key: 可选 scope_key. 缺省时按上下文推断.
            edit_modes: 可选 edit_mode 过滤列表.
            limit: 最多返回多少条.

        Returns:
            满足条件的 MemoryItem 列表.
        """

        note_scope = self._resolve_scope(ctx=ctx, scope=scope)
        note_scope_key = self._resolve_scope_key(
            ctx=ctx,
            scope=note_scope,
            scope_key=scope_key,
        )
        items = await self.store.find(
            scope=note_scope,
            scope_key=note_scope_key,
            memory_types=["sticky_note"],
            limit=max(1, int(limit)),
        )
        if not edit_modes:
            return items
        allowed = {str(mode) for mode in edit_modes}
        return [item for item in items if item.edit_mode in allowed]

    async def delete_note(
        self,
        *,
        ctx: ToolExecutionContext,
        key: str,
        scope: StickyScope | None = None,
        scope_key: str | None = None,
    ) -> bool:
        """删除一条 sticky note.

        Args:
            ctx: 当前工具执行上下文.
            key: 目标 note_key.
            scope: 可选 scope. 缺省时按上下文推断.
            scope_key: 可选 scope_key. 缺省时按上下文推断.

        Returns:
            当前 sticky note 是否存在并已删除.
        """

        item = await self.get_note(
            ctx=ctx,
            key=key,
            scope=scope,
            scope_key=scope_key,
        )
        if item is None:
            return False
        return await self.store.delete(item.memory_id)

    # region helper
    def _resolve_scope(
        self,
        *,
        ctx: ToolExecutionContext,
        scope: StickyScope | None,
    ) -> StickyScope:
        """解析当前操作使用的 scope.

        Args:
            ctx: 当前工具执行上下文.
            scope: 显式传入的 scope.

        Returns:
            规范化后的 StickyScope.
        """

        value = str(scope or self.default_scope or "relationship").strip()
        if scope is None and value == "relationship":
            message_type = str(ctx.metadata.get("message_type", "") or "")
            if message_type == "private":
                return "user"
        if value in _KNOWN_SCOPES:
            return value  # type: ignore[return-value]
        return self.default_scope

    def _resolve_scope_key(
        self,
        *,
        ctx: ToolExecutionContext,
        scope: StickyScope,
        scope_key: str | None,
    ) -> str:
        """解析当前操作使用的 scope_key.

        Args:
            ctx: 当前工具执行上下文.
            scope: 已解析出的 scope.
            scope_key: 显式传入的 scope_key.

        Returns:
            对应的 scope_key.
        """

        if scope_key:
            return str(scope_key).strip()
        channel_scope = str(ctx.metadata.get("channel_scope", "") or "")
        if scope == "relationship":
            return f"{ctx.actor_id}|{channel_scope}"
        if scope == "user":
            return ctx.actor_id
        if scope == "channel":
            return channel_scope
        return "global"

    @staticmethod
    def _normalize_key(key: str) -> str:
        """规范化 sticky note 键.

        Args:
            key: 原始 note_key.

        Returns:
            去首尾空白后的稳定键.
        """

        normalized = str(key).strip()
        if not normalized:
            raise ValueError("sticky note key cannot be empty")
        return normalized

    @staticmethod
    def _normalize_content(content: str) -> str:
        """规范化 sticky note 正文.

        Args:
            content: 原始正文.

        Returns:
            去首尾空白后的正文.
        """

        normalized = str(content).strip()
        if not normalized:
            raise ValueError("sticky note content cannot be empty")
        return normalized

    @staticmethod
    def _normalize_tags(tags: list[str] | None) -> list[str]:
        """规范化标签列表.

        Args:
            tags: 原始标签列表.

        Returns:
            去重后的标签列表.
        """

        normalized: list[str] = []
        for value in list(tags or []):
            text = str(value).strip()
            if not text or text in normalized:
                continue
            normalized.append(text)
        return normalized

    @staticmethod
    def _build_memory_id(
        *,
        scope: StickyScope,
        scope_key: str,
        key: str,
    ) -> str:
        """构造稳定的 sticky note memory_id.

        Args:
            scope: 当前 sticky note scope.
            scope_key: 当前 sticky note scope_key.
            key: 当前 sticky note 的逻辑键.

        Returns:
            一条稳定的 memory_id.
        """

        digest = hashlib.sha1(
            f"{scope}|{scope_key}|{key}".encode("utf-8"),
            usedforsecurity=False,
        ).hexdigest()[:16]
        return f"memory:sticky:{digest}"

    @staticmethod
    def _timestamp(ctx: ToolExecutionContext) -> int:
        """从工具执行上下文中提取当前事件时间戳.

        Args:
            ctx: 当前工具执行上下文.

        Returns:
            当前事件时间戳. 不存在时返回 0.
        """

        value = ctx.metadata.get("event_timestamp", 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    # endregion


# endregion
