"""LTM 检索侧入口: 接收 MemoryBroker 的检索请求, 三路召回后返回 MemoryBlock。

调用链路: 
  MemoryBroker → LtmMemorySource.__call__()
    1. QueryPlannerClient 把原始请求拆成 semantic / lexical / symbolic 三组查询
    2. 三路分别向 RetrievalStore 发起检索
    3. ranking.merge_ranked_entry_hits 按 entry_id 去重、位权排序
    4. LtmRenderer 渲染成 XML, 包成 MemoryBlock 返回

依赖面用 Protocol 定义: 
- RetrievalStore: 三种检索方法（keyword / semantic / structured）
- QueryPlannerClient: 调 LLM 生成 retrieval plan
- QueryEmbeddingClient: 把查询文本变成向量
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time
from typing import Any, Protocol

import structlog

from ..memory_broker import MemoryAssemblySpec, MemoryBlock, SharedMemoryRetrievalRequest
from .contracts import MemoryEntry
from .ranking import merge_ranked_entry_hits
from .renderer import LtmRenderer


logger = logging.getLogger("acabot.runtime.memory.long_term_memory")
slog = structlog.get_logger("acabot.runtime.memory.long_term_memory.source")


class RetrievalStore(Protocol):
    """检索侧的最小存储接口, 当前实现是 LanceDbLongTermMemoryStore。"""

    def keyword_search(
        self,
        query_text: str,
        *,
        conversation_id: str,
        limit: int,
    ) -> list[MemoryEntry]:
        """用 FTS 全文索引做词法检索。

        Args:
            query_text: 词法查询文本。
            conversation_id: 限定在哪个对话容器内搜索。
            limit: 返回条数上限。

        Returns:
            命中的 MemoryEntry 列表。
        """

    def semantic_search(
        self,
        query_vector: list[float],
        *,
        conversation_id: str,
        limit: int,
    ) -> list[MemoryEntry]:
        """用向量余弦相似度做语义检索。

        Args:
            query_vector: 查询向量（由 QueryEmbeddingClient 生成）。
            conversation_id: 限定在哪个对话容器内搜索。
            limit: 返回条数上限。

        Returns:
            命中的 MemoryEntry 列表。
        """

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
        """用结构字段（人物、实体、地点、时间区间）做精确匹配检索。

        Args:
            conversation_id: 限定在哪个对话容器内搜索。
            persons: 要求 entry.persons 包含的人物集合（子集匹配）。
            entities: 要求 entry.entities 包含的实体集合（子集匹配）。
            location: 地点精确匹配, None 表示不过滤。
            time_range: (start, end) 时间区间, 和 entry 的时间做重叠判断。
            limit: 返回条数上限。

        Returns:
            命中的 MemoryEntry 列表。
        """


class QueryPlannerClient(Protocol):
    """调 LLM 把一条模糊检索请求拆成三路查询计划。

    返回结构固定为 {semantic_queries, lexical_queries, symbolic_filters}。
    当前唯一实现是 model_clients.LtmQueryPlannerClient。
    """

    async def plan_query(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        """根据检索现场材料生成 retrieval plan。

        Args:
            request_payload: 包含 query_text、conversation_id、
                working_summary、retained_history 等现场材料。

        Returns:
            包含 semantic_queries / lexical_queries / symbolic_filters 的字典。
        """


class QueryEmbeddingClient(Protocol):
    """把查询文本变成向量, 供语义检索使用。

    当前唯一实现是 model_clients.LtmEmbeddingClient。
    """

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量把文本变成向量。

        Args:
            texts: 待向量化的查询文本列表。

        Returns:
            与输入一一对应的向量列表。
        """


@dataclass(slots=True)
class LtmMemorySource:
    """长期记忆的 MemorySource 实现, 被 MemoryBroker 当作记忆来源调用。

    执行流程: 
    1. query_planner 把原始请求拆成三组查询（semantic / lexical / symbolic）
    2. 三路分别向 store 发起检索
    3. merge_ranked_entry_hits 按 entry_id 去重、位权排序
    4. renderer 渲染成 XML, 包成 MemoryBlock 返回

    Attributes:
        store (RetrievalStore): 底层存储, 提供三种检索方法。
        query_planner (QueryPlannerClient): 调 LLM 生成 retrieval plan。
        embedding_client (QueryEmbeddingClient): 把查询文本变成向量。
        renderer (LtmRenderer): 把命中结果渲染成 XML 注入上下文。
        max_entries (int): 最终返回的最大命中条数, 默认 8。
    """

    store: RetrievalStore
    query_planner: QueryPlannerClient
    embedding_client: QueryEmbeddingClient
    renderer: LtmRenderer = field(default_factory=LtmRenderer)
    max_entries: int = 8

    async def __call__(self, request: SharedMemoryRetrievalRequest) -> list[MemoryBlock]:
        """执行一次完整的 query-aware 三路检索。

        Args:
            request: MemoryBroker 传入的共享检索请求, 包含 query_text、
                channel_scope、working_summary、retained_history 等现场材料。

        Returns:
            包含一个 MemoryBlock 的列表（source="long_term_memory", 
            priority=700）, 没有命中时返回空列表。
        """
        started_at = time.monotonic()
        conversation_id = str(request.channel_scope or "").strip()
        try:
            # 第一步: 让 query planner 把原始请求拆成三组查询
            plan = await self.query_planner.plan_query(self._build_plan_request(request))
            slog.info(
                "LTM query plan generated",
                conversation_id=conversation_id,
                semantic_queries=len(list(plan.get("semantic_queries", []) or [])),
                lexical_queries=len(list(plan.get("lexical_queries", []) or [])),
                has_symbolic=bool(dict(plan.get("symbolic_filters", {}) or {})),
                duration_ms=round((time.monotonic() - started_at) * 1000, 1),
            )

            # 第二步: 三路召回
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

            # 第三步: 去重 + 位权排序 + 截断
            ranked_hits = merge_ranked_entry_hits(
                semantic_hits=semantic_hits,
                lexical_hits=lexical_hits,
                symbolic_hits=symbolic_hits,
            )[: self.max_entries]
            slog.info(
                "LTM retrieval completed",
                conversation_id=conversation_id,
                semantic_hits=len(semantic_hits),
                lexical_hits=len(lexical_hits),
                symbolic_hits=len(symbolic_hits),
                ranked_total=len(ranked_hits),
                returned_blocks=1 if ranked_hits else 0,
                duration_ms=round((time.monotonic() - started_at) * 1000, 1),
            )
            if not ranked_hits:
                return []

            # 第四步: 渲染成 XML, 包成 MemoryBlock
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
        except Exception:
            slog.exception(
                "LTM retrieval failed",
                conversation_id=conversation_id,
                duration_ms=round((time.monotonic() - started_at) * 1000, 1),
            )
            return []

    async def _semantic_hits(
        self,
        *,
        conversation_id: str,
        semantic_queries: list[str],
        fallback_query: str,
    ) -> list[MemoryEntry]:
        """语义召回: 把查询文本变成向量, 然后做余弦相似度检索。

        如果 planner 没有给出 semantic_queries, 退回到原始 query_text。
        每条查询文本分别做一次向量检索, 结果合并返回（去重由上层 ranking 处理）。

        Args:
            conversation_id: 限定搜索的对话容器。
            semantic_queries: query planner 产出的语义查询文本列表。
            fallback_query: planner 没给时退回使用的原始 query_text。

        Returns:
            所有语义查询的命中结果合并列表。
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
        """词法召回: 用 FTS 全文索引做关键词匹配。

        如果 planner 没有给出 lexical_queries, 退回到原始 query_text。
        每条查询文本分别做一次 FTS 检索, 结果合并返回。

        Args:
            conversation_id: 限定搜索的对话容器。
            lexical_queries: query planner 产出的词法查询文本列表。
            fallback_query: planner 没给时退回使用的原始 query_text。

        Returns:
            所有词法查询的命中结果合并列表。
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
        """结构字段召回: 用 persons / entities / location / time_range 做精确匹配。

        从 planner 输出的 symbolic_filters 里提取四类条件, 至少有一类非空才发起检索。
        time_range 会被规范化成 (start, end) 元组, 两端都是 None 时视为无条件。

        Args:
            conversation_id: 限定搜索的对话容器。
            symbolic_filters: query planner 产出的结构过滤条件字典, 
                包含 persons / entities / location / time_range。

        Returns:
            结构匹配的命中列表, 四类条件全空时返回空列表。
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
        """把 MemoryBroker 的共享检索请求转成 query planner 需要的输入格式。

        Args:
            request: 当前共享检索请求。

        Returns:
            包含 query_text / conversation_id / working_summary /
            retained_history / metadata 的字典。
        """

        return {
            "query_text": request.query_text,
            "conversation_id": request.channel_scope,
            "working_summary": request.working_summary,
            "retained_history": list(request.retained_history),
            "metadata": dict(request.metadata),
        }


__all__ = ["LtmMemorySource", "RetrievalStore"]
