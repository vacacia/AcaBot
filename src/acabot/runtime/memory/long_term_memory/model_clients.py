"""runtime.memory.long_term_memory.model_clients 负责 LTM 模型位点调用."""

from __future__ import annotations

import json
from typing import Any

from acabot.agent.base import BaseAgent

from ...model.model_embedding_runtime import ModelEmbeddingRuntime
from ...model.model_registry import FileSystemModelRegistryManager, RuntimeModelRequest
from ..conversation_facts import ConversationFact
from .contracts import MemoryEntry
from .extractor import (
    WindowExtractionError,
    build_extraction_window_payload,
    parse_extractor_response,
)


class LtmExtractorClient:
    """LtmExtractorClient 通过统一 target 调提取模型."""

    def __init__(
        self,
        *,
        agent: BaseAgent,
        model_registry_manager: FileSystemModelRegistryManager | None,
        extractor_version: str = "ltm-extractor-v1",
    ) -> None:
        """初始化提取客户端.

        Args:
            agent: 底层 completion agent.
            model_registry_manager: 模型注册表管理器.
            extractor_version: 当前提取器版本.
        """

        self.agent = agent
        self.model_registry_manager = model_registry_manager
        self.extractor_version = extractor_version

    async def extract_window(
        self,
        *,
        conversation_id: str,
        facts: list[ConversationFact],
        now_ts: int,
    ) -> list[MemoryEntry]:
        """从一个事实窗口里提取长期记忆.

        Args:
            conversation_id: 所属对话容器.
            facts: 当前窗口事实列表.
            now_ts: 当前时间戳.

        Returns:
            当前窗口产出的长期记忆列表.

        Raises:
            WindowExtractionError: 当 target 未配置或模型输出不合法时抛出.
        """

        request = self._require_target_request("system:ltm_extract")
        payload = build_extraction_window_payload(
            conversation_id=conversation_id,
            facts=facts,
        )
        response = await self.agent.complete(
            system_prompt=payload.system_prompt,
            messages=[{"role": "user", "content": payload.prompt}],
            model=request.model,
            request_options=request.to_request_options(),
        )
        if getattr(response, "error", None):
            raise WindowExtractionError(str(response.error))
        try:
            parsed = json.loads(str(getattr(response, "text", "") or ""))
        except json.JSONDecodeError as exc:
            raise WindowExtractionError(f"extractor response is not valid JSON: {exc}") from exc
        return parse_extractor_response(
            response=parsed,
            anchor_map=payload.anchor_map,
            fact_roles=payload.fact_roles,
            conversation_id=conversation_id,
            extractor_version=self.extractor_version,
            now_ts=now_ts,
        )

    def _require_target_request(self, target_id: str) -> RuntimeModelRequest:
        """读取一个必需的 LTM 模型请求.

        Args:
            target_id: 目标位点.

        Returns:
            已解析的运行时模型请求.

        Raises:
            WindowExtractionError: 当 target 不可用时抛出.
        """

        if self.model_registry_manager is None:
            raise WindowExtractionError("model registry manager is required")
        request = self.model_registry_manager.resolve_target_request(target_id)
        if request is None:
            raise WindowExtractionError(f"model target is not configured: {target_id}")
        return request


class LtmEmbeddingClient:
    """LtmEmbeddingClient 通过统一 target 调 embedding 模型."""

    def __init__(
        self,
        *,
        embedding_runtime: ModelEmbeddingRuntime,
        model_registry_manager: FileSystemModelRegistryManager | None,
    ) -> None:
        """初始化 embedding 客户端.

        Args:
            embedding_runtime: 底层 embedding runtime.
            model_registry_manager: 模型注册表管理器.
        """

        self.embedding_runtime = embedding_runtime
        self.model_registry_manager = model_registry_manager

    async def embed_entries(self, entries: list[MemoryEntry]) -> list[list[float]]:
        """把一批 entry 编成向量.

        Args:
            entries: 待向量化的长期记忆对象列表.

        Returns:
            与输入一一对应的向量列表.
        """

        if not entries:
            return []
        request = self._require_target_request("system:ltm_embed")
        texts = [f"Topic: {entry.topic}. Fact: {entry.lossless_restatement}" for entry in entries]
        return await self.embedding_runtime.embed_texts(request, texts)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """把任意文本列表变成向量.

        Args:
            texts: 待向量化文本列表.

        Returns:
            与输入一一对应的向量列表.
        """

        if not texts:
            return []
        request = self._require_target_request("system:ltm_embed")
        return await self.embedding_runtime.embed_texts(request, texts)

    def _require_target_request(self, target_id: str) -> RuntimeModelRequest:
        """读取一个必需的 LTM embedding 请求.

        Args:
            target_id: 目标位点.

        Returns:
            已解析的运行时模型请求.

        Raises:
            RuntimeError: 当 target 不可用时抛出.
        """

        if self.model_registry_manager is None:
            raise RuntimeError("model registry manager is required")
        request = self.model_registry_manager.resolve_target_request(target_id)
        if request is None:
            raise RuntimeError(f"model target is not configured: {target_id}")
        return request


class LtmQueryPlannerClient:
    """LtmQueryPlannerClient 通过统一 target 调检索规划模型."""

    def __init__(
        self,
        *,
        agent: BaseAgent,
        model_registry_manager: FileSystemModelRegistryManager | None,
    ) -> None:
        """初始化 query planner 客户端.

        Args:
            agent: 底层 completion agent.
            model_registry_manager: 模型注册表管理器.
        """

        self.agent = agent
        self.model_registry_manager = model_registry_manager

    async def plan_query(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        """根据当前检索请求生成 query-aware retrieval plan.

        Args:
            request_payload: 当前检索请求材料.

        Returns:
            规范化后的 retrieval plan.
        """

        request = self._require_target_request("system:ltm_query_plan")
        response = await self.agent.complete(
            system_prompt=(
                "你负责把一次长期记忆检索请求整理成 JSON retrieval plan。"
                "只返回 JSON，对象必须包含 semantic_queries、lexical_queries、symbolic_filters 三个字段。"
            ),
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(request_payload, ensure_ascii=False),
                }
            ],
            model=request.model,
            request_options=request.to_request_options(),
        )
        if getattr(response, "error", None):
            raise RuntimeError(str(response.error))
        try:
            parsed = json.loads(str(getattr(response, "text", "") or ""))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"query planner response is not valid JSON: {exc}") from exc
        if isinstance(parsed, dict) and isinstance(parsed.get("plan"), dict):
            parsed = dict(parsed.get("plan") or {})
        if not isinstance(parsed, dict):
            raise RuntimeError("query planner response must be a JSON object")
        return {
            "semantic_queries": [
                str(item).strip()
                for item in list(parsed.get("semantic_queries", []) or [])
                if str(item).strip()
            ],
            "lexical_queries": [
                str(item).strip()
                for item in list(parsed.get("lexical_queries", []) or [])
                if str(item).strip()
            ],
            "symbolic_filters": self._normalize_symbolic_filters(parsed.get("symbolic_filters", {})),
        }

    def _require_target_request(self, target_id: str) -> RuntimeModelRequest:
        """读取一个必需的 query planner 模型请求.

        Args:
            target_id: 目标位点.

        Returns:
            已解析的运行时模型请求.

        Raises:
            RuntimeError: 当 target 不可用时抛出.
        """

        if self.model_registry_manager is None:
            raise RuntimeError("model registry manager is required")
        request = self.model_registry_manager.resolve_target_request(target_id)
        if request is None:
            raise RuntimeError(f"model target is not configured: {target_id}")
        return request

    @staticmethod
    def _normalize_symbolic_filters(raw_value: Any) -> dict[str, Any]:
        """规范化 query planner 返回的结构过滤条件.

        Args:
            raw_value: 模型原始输出.

        Returns:
            规范化后的结构过滤字典.
        """

        if not isinstance(raw_value, dict):
            return {}
        time_range = raw_value.get("time_range")
        normalized_time_range = None
        if isinstance(time_range, (list, tuple)) and len(time_range) == 2:
            start = str(time_range[0] or "").strip() or None
            end = str(time_range[1] or "").strip() or None
            if start is not None or end is not None:
                normalized_time_range = [start, end]
        return {
            "persons": [
                str(item).strip()
                for item in list(raw_value.get("persons", []) or [])
                if str(item).strip()
            ],
            "entities": [
                str(item).strip()
                for item in list(raw_value.get("entities", []) or [])
                if str(item).strip()
            ],
            "location": str(raw_value.get("location") or "").strip() or None,
            "time_range": normalized_time_range,
        }


__all__ = [
    "LtmEmbeddingClient",
    "LtmExtractorClient",
    "LtmQueryPlannerClient",
]
