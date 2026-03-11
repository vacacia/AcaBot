"""runtime.memory_broker 定义长期记忆的统一入口.

组件关系:

    ThreadPipeline
        |
        +--> retrieve(ctx) -----------+
        |                             v
        |                       MemoryRetriever
        |
        +--> extract_after_run(ctx) --+
                                      v
                                 MemoryExtractor

这一层不管理 thread working memory.
它只负责:
- 把 RunContext 规范成 retrieval / extraction request
- 调用可替换的 memory backend
- 把 backend 返回结果规范成 MemoryBlock
"""

from __future__ import annotations

from dataclasses import dataclass, field
from inspect import isawaitable
from typing import Any, Protocol

from .models import DispatchReport, RunContext


# region memory对象
@dataclass(slots=True)
class MemoryBlock:
    """注入给 runtime 的记忆块, 最终会进入 LLM 的 prompt.

    Attributes:
        title (str): 当前记忆块标题.
        content (str): 注入给模型的正文内容.
        scope (str): 记忆所属 scope, 例如 `user`, `relationship`, `episodic`.
        source_ids (list[str]): 相关 memory item 或 event 的 source ID 列表.
        metadata (dict[str, Any]): 附加元数据.
    """

    title: str
    content: str
    scope: str = "global"
    source_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryRetrievalRequest:
    """一次 retrieval 的标准输入.

    Attributes:
        run_id (str): 当前 run_id.
        thread_id (str): 当前 thread_id.
        actor_id (str): 当前 actor_id.
        agent_id (str): 当前 agent_id.
        channel_scope (str): 当前 channel scope.
        event_id (str): 当前事件 ID.
        event_type (str): 当前事件类型.
        event_timestamp (int): 当前事件时间戳.
        query_text (str): 当前事件的简短检索文本.
        working_summary (str): 当前 thread 的 working summary.
        requested_scopes (list[str]): control plane 建议读取的 memory scope 列表.
        event_tags (list[str]): 当前事件的 event tags.
        metadata (dict[str, Any]): 其他 retrieval 元数据.
    """

    run_id: str
    thread_id: str
    actor_id: str
    agent_id: str
    channel_scope: str
    event_id: str
    event_type: str
    event_timestamp: int
    query_text: str
    working_summary: str
    requested_scopes: list[str] = field(default_factory=list)
    event_tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryWriteRequest:
    """一次 memory write-back 的标准输入.

    Attributes:
        run_id (str): 当前 run_id.
        thread_id (str): 当前 thread_id.
        actor_id (str): 当前 actor_id.
        agent_id (str): 当前 agent_id.
        channel_scope (str): 当前 channel scope.
        event_id (str): 当前事件 ID.
        event_type (str): 当前事件类型.
        event_timestamp (int): 当前事件时间戳.
        run_mode (str): 当前 run_mode.
        run_status (str): 当前 run 结束状态.
        user_content (str): 当前事件投影后的用户内容.
        delivered_messages (list[str]): 本次真正送达的 assistant 内容列表.
        requested_scopes (list[str]): control plane 建议写入的 memory scope 列表.
        event_tags (list[str]): 当前事件的 event tags.
        metadata (dict[str, Any]): 其他 write-back 元数据.
    """

    run_id: str
    thread_id: str
    actor_id: str
    agent_id: str
    channel_scope: str
    event_id: str
    event_type: str
    event_timestamp: int
    run_mode: str
    run_status: str
    user_content: str
    delivered_messages: list[str] = field(default_factory=list)
    requested_scopes: list[str] = field(default_factory=list)
    event_tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryRetriever(Protocol):
    """MemoryRetriever 协议.

    任意接受 MemoryRetrievalRequest 并返回 MemoryBlock 列表的对象, 都可作为 retriever.
    """

    async def __call__(self, request: MemoryRetrievalRequest) -> list[MemoryBlock]:
        """执行一次 retrieval.

        Args:
            request: 标准化后的 retrieval request.

        Returns:
            一组 MemoryBlock.
        """

        ...


class MemoryExtractor(Protocol):
    """MemoryExtractor 协议.

    任意接受 MemoryWriteRequest 并执行 write-back 的对象, 都可作为 extractor.
    """

    async def __call__(self, request: MemoryWriteRequest) -> None:
        """执行一次 memory write-back.

        Args:
            request: 标准化后的 write-back request.
        """

        ...


@dataclass(slots=True)
class NullMemoryRetriever:
    """默认空 retriever."""

    async def __call__(self, request: MemoryRetrievalRequest) -> list[MemoryBlock]:
        """返回空的 retrieval 结果.

        Args:
            request: 标准化后的 retrieval request.

        Returns:
            空列表.
        """

        _ = request
        return []


@dataclass(slots=True)
class NullMemoryExtractor:
    """默认空 extractor."""

    async def __call__(self, request: MemoryWriteRequest) -> None:
        """忽略一次 write-back.

        Args:
            request: 标准化后的 write-back request.
        """

        _ = request
        return None


class MemoryBroker:
    """统一记忆入口.

    Attributes:
        retriever (MemoryRetriever): 当前使用的 retrieval backend.
        extractor (MemoryExtractor): 当前使用的 extraction backend.
    """

    def __init__(
        self,
        *,
        retriever: MemoryRetriever | None = None,
        extractor: MemoryExtractor | None = None,
    ) -> None:
        """初始化 MemoryBroker.

        Args:
            retriever: 可选的 retrieval backend.
            extractor: 可选的 extraction backend.
        """

        self.retriever = retriever or NullMemoryRetriever()
        self.extractor = extractor or NullMemoryExtractor()

    async def retrieve(self, ctx: RunContext) -> list[MemoryBlock]:
        """为当前 run 检索长期记忆.

        Args:
            ctx: 当前 run 的执行上下文.

        Returns:
            一组 MemoryBlock.
        """

        request = self._build_retrieval_request(ctx)
        result = self.retriever(request)
        if isawaitable(result):
            result = await result
        return list(result)

    async def extract_after_run(self, ctx: RunContext) -> None:
        """在一次 run 结束后触发 memory write-back.

        Args:
            ctx: 当前 run 的执行上下文.
        """

        request = self._build_write_request(ctx)
        result = self.extractor(request)
        if isawaitable(result):
            await result

    # region request构造
    def _build_retrieval_request(self, ctx: RunContext) -> MemoryRetrievalRequest:
        """把 RunContext 规范成 retrieval request.

        Args:
            ctx: 当前 run 的执行上下文.

        Returns:
            一份 MemoryRetrievalRequest.
        """

        return MemoryRetrievalRequest(
            run_id=ctx.run.run_id,
            thread_id=ctx.thread.thread_id,
            actor_id=ctx.decision.actor_id,
            agent_id=ctx.decision.agent_id,
            channel_scope=ctx.decision.channel_scope,
            event_id=ctx.event.event_id,
            event_type=ctx.event.event_type,
            event_timestamp=ctx.event.timestamp,
            query_text=self._user_content(ctx),
            working_summary=ctx.thread.working_summary,
            requested_scopes=list(ctx.decision.metadata.get("event_memory_scopes", [])),
            event_tags=list(ctx.decision.metadata.get("event_tags", [])),
            metadata={
                "run_mode": ctx.decision.run_mode,
                "sender_role": ctx.event.sender_role,
                "event_policy_id": ctx.decision.metadata.get("event_policy_id", ""),
            },
        )

    def _build_write_request(self, ctx: RunContext) -> MemoryWriteRequest:
        """把 RunContext 规范成 write-back request.

        Args:
            ctx: 当前 run 的执行上下文.

        Returns:
            一份 MemoryWriteRequest.
        """

        return MemoryWriteRequest(
            run_id=ctx.run.run_id,
            thread_id=ctx.thread.thread_id,
            actor_id=ctx.decision.actor_id,
            agent_id=ctx.decision.agent_id,
            channel_scope=ctx.decision.channel_scope,
            event_id=ctx.event.event_id,
            event_type=ctx.event.event_type,
            event_timestamp=ctx.event.timestamp,
            run_mode=ctx.decision.run_mode,
            run_status=str(ctx.run.status),
            user_content=self._user_content(ctx),
            delivered_messages=self._delivered_messages(ctx.delivery_report),
            requested_scopes=list(ctx.decision.metadata.get("event_memory_scopes", [])),
            event_tags=list(ctx.decision.metadata.get("event_tags", [])),
            metadata={
                "event_policy_id": ctx.decision.metadata.get("event_policy_id", ""),
                "extract_to_memory": ctx.decision.metadata.get("event_extract_to_memory", False),
                "thread_summary": ctx.thread.working_summary,
            },
        )

    @staticmethod
    def _delivered_messages(report: DispatchReport | None) -> list[str]:
        """从 DeliveryReport 提取真正送达的 thread 内容.

        Args:
            report: 本次出站的 DeliveryReport.

        Returns:
            真正送达的 assistant 内容列表.
        """

        if report is None:
            return []
        delivered: list[str] = []
        for item in report.delivered_items:
            if item.plan.thread_content:
                delivered.append(item.plan.thread_content)
        return delivered

    @staticmethod
    def _user_content(ctx: RunContext) -> str:
        """提取当前事件投影后的用户内容.

        Args:
            ctx: 当前 run 的执行上下文.

        Returns:
            一条简短的用户内容字符串.
        """

        nickname = ctx.event.sender_nickname or ""
        user_id = ctx.event.source.user_id
        prefix = f"[{nickname}/{user_id}]" if nickname else f"[{user_id}]"
        
        if ctx.event.is_message:
            return f"{prefix} {ctx.event.text}"

        event_label = ctx.event.event_type
        if ctx.event.event_type == "poke":
            event_label = "notice:poke"
        elif ctx.event.event_type == "recall":
            target = ctx.event.target_message_id or ""
            event_label = f"notice:recall target={target}".strip()
        # [昵称/用户ID] [notice:recall target=msg_789]
        return f"{prefix} [{event_label}]"

    # endregion


# endregion
