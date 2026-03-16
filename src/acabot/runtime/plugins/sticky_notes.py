"""runtime.plugins.sticky_notes 提供 sticky note 工具插件.

组件关系:

    RuntimePluginManager
            |
            v
     StickyNotesPlugin
            |
            v
     StickyNotesService

这个插件的目标是:
- 把旧 notepad 的核心能力迁成 runtime-native sticky note 工具
- 让 agent 可以按 scope 写入和读取稳定事实
- 不暴露整个 MemoryStore, 只暴露 sticky note 的受控操作
"""

from __future__ import annotations

from typing import Any, cast

from acabot.agent import ToolSpec

from ..plugin_manager import RuntimePlugin, RuntimePluginContext, RuntimeToolRegistration
from ..memory.sticky_notes import StickyNotesService, StickyScope
from ..tool_broker import ToolExecutionContext, ToolResult


# region plugin
class StickyNotesPlugin(RuntimePlugin):
    """sticky note 工具插件.

    Attributes:
        name (str): 插件名.
        _service (StickyNotesService | None): 当前 sticky note 服务.
        _default_scope (StickyScope): 默认写入和查询 scope.
    """

    name = "sticky_notes"

    def __init__(self) -> None:
        """初始化插件状态."""

        self._service: StickyNotesService | None = None
        self._default_scope: StickyScope = "relationship"

    async def setup(self, runtime: RuntimePluginContext) -> None:
        """读取 sticky note 服务和插件配置.

        Args:
            runtime: runtime plugin 上下文.
        """

        self._service = runtime.sticky_notes
        config = runtime.get_plugin_config(self.name)
        scope = str(config.get("default_scope", "relationship") or "relationship")
        if scope in {"relationship", "user", "channel", "global"}:
            self._default_scope = cast(StickyScope, scope)

    def runtime_tools(self) -> list[RuntimeToolRegistration]:
        """返回 runtime-native sticky note 工具定义.

        Returns:
            `sticky_note_put`, `sticky_note_get`, `sticky_note_list`, `sticky_note_delete`.
        """

        return [
            RuntimeToolRegistration(
                spec=ToolSpec(
                    name="sticky_note_put",
                    description="Write or update a sticky note for user, channel, relationship or global scope.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "content": {"type": "string"},
                            "scope": {"type": "string"},
                            "scope_key": {"type": "string"},
                            "edit_mode": {"type": "string"},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "author": {"type": "string"},
                        },
                        "required": ["key", "content"],
                    },
                ),
                handler=self._put_note,
            ),
            RuntimeToolRegistration(
                spec=ToolSpec(
                    name="sticky_note_get",
                    description="Read a sticky note by key from the current or specified scope.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "scope": {"type": "string"},
                            "scope_key": {"type": "string"},
                        },
                        "required": ["key"],
                    },
                ),
                handler=self._get_note,
            ),
            RuntimeToolRegistration(
                spec=ToolSpec(
                    name="sticky_note_list",
                    description="List sticky notes from the current or specified scope.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "scope": {"type": "string"},
                            "scope_key": {"type": "string"},
                            "edit_modes": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "limit": {"type": "integer"},
                        },
                    },
                ),
                handler=self._list_notes,
            ),
            RuntimeToolRegistration(
                spec=ToolSpec(
                    name="sticky_note_delete",
                    description="Delete a sticky note by key from the current or specified scope.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "scope": {"type": "string"},
                            "scope_key": {"type": "string"},
                        },
                        "required": ["key"],
                    },
                ),
                handler=self._delete_note,
            ),
        ]

    # region handlers
    async def _put_note(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        """写入或更新一条 sticky note.

        Args:
            arguments: 工具参数.
            ctx: 当前工具执行上下文.

        Returns:
            一份适合 LLM 消费的 ToolResult.
        """

        service = self._require_service()
        item = await service.put_note(
            ctx=ctx,
            key=str(arguments.get("key", "") or ""),
            content=str(arguments.get("content", "") or ""),
            scope=self._scope(arguments),
            scope_key=str(arguments.get("scope_key", "") or "") or None,
            edit_mode=self._edit_mode(arguments),
            tags=[str(value) for value in list(arguments.get("tags", []) or [])],
            author=str(arguments.get("author", "") or "user"),
        )
        note_key = str(item.metadata.get("note_key", "") or "")
        return ToolResult(
            llm_content=(
                f"Sticky note saved: [{item.scope}] {note_key} -> {item.content}"
            ),
            raw=self._to_payload(item),
            metadata={"memory_id": item.memory_id, "memory_type": item.memory_type},
        )

    async def _get_note(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        """读取一条 sticky note.

        Args:
            arguments: 工具参数.
            ctx: 当前工具执行上下文.

        Returns:
            一份适合 LLM 消费的 ToolResult.
        """

        service = self._require_service()
        item = await service.get_note(
            ctx=ctx,
            key=str(arguments.get("key", "") or ""),
            scope=self._scope(arguments),
            scope_key=str(arguments.get("scope_key", "") or "") or None,
        )
        if item is None:
            return ToolResult(
                llm_content="Sticky note not found.",
                raw={"ok": False, "reason": "not_found"},
            )
        return ToolResult(
            llm_content=(
                f"Sticky note: [{item.scope}] "
                f"{item.metadata.get('note_key', '')} -> {item.content}"
            ),
            raw=self._to_payload(item),
            metadata={"memory_id": item.memory_id, "memory_type": item.memory_type},
        )

    async def _list_notes(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        """列出当前 scope 下的 sticky notes.

        Args:
            arguments: 工具参数.
            ctx: 当前工具执行上下文.

        Returns:
            一份适合 LLM 消费的 ToolResult.
        """

        service = self._require_service()
        edit_modes: list[str] = []
        for value in list(arguments.get("edit_modes", []) or []):
            normalized = self._coerce_edit_mode(value)
            if normalized is None:
                continue
            edit_modes.append(normalized)
        items = await service.list_notes(
            ctx=ctx,
            scope=self._scope(arguments),
            scope_key=str(arguments.get("scope_key", "") or "") or None,
            edit_modes=cast(list[Any], edit_modes) or None,
            limit=int(arguments.get("limit", 20) or 20),
        )
        if not items:
            return ToolResult(
                llm_content="No sticky notes found.",
                raw={"items": []},
            )
        lines = ["Sticky notes:"]
        for item in items:
            lines.append(
                f"- [{item.scope}/{item.edit_mode}] "
                f"{item.metadata.get('note_key', '')}: {item.content}"
            )
        return ToolResult(
            llm_content="\n".join(lines),
            raw={"items": [self._to_payload(item) for item in items]},
            metadata={"count": len(items)},
        )

    async def _delete_note(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        """删除一条 sticky note.

        Args:
            arguments: 工具参数.
            ctx: 当前工具执行上下文.

        Returns:
            一份适合 LLM 消费的 ToolResult.
        """

        service = self._require_service()
        key = str(arguments.get("key", "") or "")
        deleted = await service.delete_note(
            ctx=ctx,
            key=key,
            scope=self._scope(arguments),
            scope_key=str(arguments.get("scope_key", "") or "") or None,
        )
        if not deleted:
            return ToolResult(
                llm_content="Sticky note not found.",
                raw={"ok": False, "reason": "not_found", "key": key},
            )
        return ToolResult(
            llm_content=f"Sticky note deleted: {key}",
            raw={"ok": True, "key": key},
        )

    # endregion

    # region helper
    def _require_service(self) -> StickyNotesService:
        """返回当前可用的 sticky note 服务.

        Returns:
            当前 StickyNotesService.

        Raises:
            RuntimeError: 当前未配置 sticky note 服务.
        """

        if self._service is None:
            raise RuntimeError("sticky notes service is unavailable")
        return self._service

    def _scope(self, arguments: dict[str, Any]) -> StickyScope | None:
        """解析目标 scope.

        Args:
            arguments: 工具参数.

        Returns:
            合法的 StickyScope. 未声明时返回插件默认值.
        """

        raw = str(arguments.get("scope", "") or self._default_scope).strip()
        if raw in {"relationship", "user", "channel", "global"}:
            return cast(StickyScope, raw)
        return self._default_scope

    @staticmethod
    def _coerce_edit_mode(value: Any) -> str | None:
        """把原始 edit_mode 转成合法字符串.

        Args:
            value: 原始 edit_mode 值.

        Returns:
            合法的 edit_mode. 不合法时返回 None.
        """

        text = str(value).strip()
        if text in {"readonly", "draft", "private"}:
            return text
        return None

    def _edit_mode(self, arguments: dict[str, Any]) -> str:
        """解析写入时使用的 edit_mode.

        Args:
            arguments: 工具参数.

        Returns:
            合法的 edit_mode. 缺省时返回 `readonly`.
        """

        return self._coerce_edit_mode(arguments.get("edit_mode", "readonly")) or "readonly"

    @staticmethod
    def _to_payload(item: Any) -> dict[str, Any]:
        """把 MemoryItem 转成结构化 payload.

        Args:
            item: 目标 MemoryItem.

        Returns:
            适合 tool raw 返回的结构化字典.
        """

        return {
            "memory_id": item.memory_id,
            "scope": item.scope,
            "scope_key": item.scope_key,
            "memory_type": item.memory_type,
            "content": item.content,
            "edit_mode": item.edit_mode,
            "author": item.author,
            "tags": list(item.tags),
            "metadata": dict(item.metadata),
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }

    # endregion


# endregion
