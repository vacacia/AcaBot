"""runtime.memory.long_term_memory.source 负责长期记忆检索侧入口."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..memory_broker import MemoryAssemblySpec, MemoryBlock, SharedMemoryRetrievalRequest
from .contracts import MemoryEntry
from .ranking import merge_ranked_entry_hits
from .renderer import CoreSimpleMemRenderer


class RetrievalStore(Protocol):
    """RetrievalStore 定义检索侧需要的最小存储依赖面."""

    def keyword_search(
        self,
        query_text: str,
        *,
        conversation_id: str,
        limit: int,
    ) -> list[MemoryEntry]:
        """执行词法检索."""

    def semantic_search(
        self,
        query_vector: list[float],
        *,
        conversation_id: str,
        limit: int,
    ) -> list[MemoryEntry]:
        """执行语义检索."""

    def structured_search(
        self,
        *,
        conversation_id: str,
        persons: list[str],
        entities: list[str],
        location: str | None,
        time_range: tuple[str | None, str | None] | None,
        limit: int,
    ) -> list[MemoryEntry]:
        """执行结构字段检索."""


class QueryPlannerClient(Protocol):
    """QueryPlannerClient 定义 query planning 依赖面."""

    async def plan_query(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        """为当前检索请求生成一个 retrieval plan."""


class QueryEmbeddingClient(Protocol):
    """QueryEmbeddingClient 定义 query embedding 依赖面."""

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """把查询文本列表变成向量列表."""


@dataclass(slots=True)
class CoreSimpleMemMemorySource:
    """CoreSimpleMemMemorySource 把长期记忆检索成一个统一 block.

    Attributes:
        store (RetrievalStore): 检索侧存储依赖面.
        query_planner (QueryPlannerClient): query planning 客户端.
        embedding_client (QueryEmbeddingClient): query embedding 客户端.
        renderer (CoreSimpleMemRenderer): XML renderer.
        max_entries (int): 最终注入条数上限.
    """

    store: RetrievalStore
    query_planner: QueryPlannerClient
    embedding_client: QueryEmbeddingClient
    renderer: CoreSimpleMemRenderer = field(default_factory=CoreSimpleMemRenderer)
    max_entries: int = 8

    async def __call__(self, request: SharedMemoryRetrievalRequest) -> list[MemoryBlock]:
        """执行一次 query-aware retrieval.

        Args:
            request: 当前共享检索请求.

        Returns:
            统一的 `long_term_memory` block 列表.
        """

        plan = await self.query_planner.plan_query(self._build_plan_request(request))
        conversation_id = str(request.channel_scope or "").strip()
        semantic_hits = await self._semantic_hits(
            conversation_id=conversation_id,
            semantic_queries=list(plan.get("semantic_queries", []) or []),
            fallback_query=str(request.query_text or "").strip(),
        )
        lexical_hits = self._lexical_hits(
            conversation_id=conversation_id,
            lexical_queries=list(plan.get("lexical_queries", []) or []),
            fallback_query=str(request.query_text or "").strip(),
        )
        symbolic_hits = self._symbolic_hits(
            conversation_id=conversation_id,
            symbolic_filters=dict(plan.get("symbolic_filters", {}) or {}),
        )
        ranked_hits = merge_ranked_entry_hits(
            semantic_hits=semantic_hits,
            lexical_hits=lexical_hits,
            symbolic_hits=symbolic_hits,
        )[: self.max_entries]
        if not ranked_hits:
            return []
        return [
            MemoryBlock(
                content=self.renderer.render(ranked_hits),
                source="long_term_memory",
                scope="conversation",
                source_ids=[item.entry.entry_id for item in ranked_hits],
                assembly=MemoryAssemblySpec(target_slot="message_prefix", priority=700),
                metadata={
                    "conversation_id": conversation_id,
                    "hit_count": len(ranked_hits),
                },
            )
        ]

    async def _semantic_hits(
        self,
        *,
        conversation_id: str,
        semantic_queries: list[str],
        fallback_query: str,
    ) -> list[MemoryEntry]:
        """执行语义召回.

        Args:
            conversation_id: 目标对话容器.
            semantic_queries: query planner 产出的语义查询文本.
            fallback_query: planner 没给时的默认查询文本.

        Returns:
            语义命中列表.
        """

        query_texts = [text for text in semantic_queries if str(text or "").strip()]
        if not query_texts and fallback_query:
            query_texts = [fallback_query]
        if not query_texts:
            return []
        vectors = await self.embedding_client.embed_texts(query_texts)
        hits: list[MemoryEntry] = []
        for vector in vectors:
            hits.extend(
                self.store.semantic_search(
                    vector,
                    conversation_id=conversation_id,
                    limit=self.max_entries,
                )
            )
        return hits

    def _lexical_hits(
        self,
        *,
        conversation_id: str,
        lexical_queries: list[str],
        fallback_query: str,
    ) -> list[MemoryEntry]:
        """执行词法召回.

        Args:
            conversation_id: 目标对话容器.
            lexical_queries: query planner 产出的词法查询文本.
            fallback_query: planner 没给时的默认查询文本.

        Returns:
            词法命中列表.
        """

        query_texts = [text for text in lexical_queries if str(text or "").strip()]
        if not query_texts and fallback_query:
            query_texts = [fallback_query]
        hits: list[MemoryEntry] = []
        for query_text in query_texts:
            hits.extend(
                self.store.keyword_search(
                    query_text,
                    conversation_id=conversation_id,
                    limit=self.max_entries,
                )
            )
        return hits

    def _symbolic_hits(
        self,
        *,
        conversation_id: str,
        symbolic_filters: dict[str, Any],
    ) -> list[MemoryEntry]:
        """执行结构字段召回.

        Args:
            conversation_id: 目标对话容器.
            symbolic_filters: query planner 产出的结构过滤条件.

        Returns:
            结构命中列表.
        """

        persons = [
            str(item).strip()
            for item in list(symbolic_filters.get("persons", []) or [])
            if str(item).strip()
        ]
        entities = [
            str(item).strip()
            for item in list(symbolic_filters.get("entities", []) or [])
            if str(item).strip()
        ]
        location = str(symbolic_filters.get("location") or "").strip() or None
        time_range = symbolic_filters.get("time_range")
        normalized_time_range = (
            (
                str(time_range[0] or "").strip() or None,
                str(time_range[1] or "").strip() or None,
            )
            if isinstance(time_range, (list, tuple)) and len(time_range) == 2
            else None
        )
        if normalized_time_range == (None, None):
            normalized_time_range = None
        if not any([persons, entities, location, normalized_time_range]):
            return []
        return self.store.structured_search(
            conversation_id=conversation_id,
            persons=persons,
            entities=entities,
            location=location,
            time_range=normalized_time_range,
            limit=self.max_entries,
        )

    @staticmethod
    def _build_plan_request(request: SharedMemoryRetrievalRequest) -> dict[str, Any]:
        """把共享检索请求转成 query planner 的输入对象.

        Args:
            request: 当前共享检索请求.

        Returns:
            query planner 输入字典.
        """

        return {
            "query_text": request.query_text,
            "conversation_id": request.channel_scope,
            "working_summary": request.working_summary,
            "retained_history": list(request.retained_history),
            "metadata": dict(request.metadata),
        }


__all__ = ["CoreSimpleMemMemorySource", "RetrievalStore"]
