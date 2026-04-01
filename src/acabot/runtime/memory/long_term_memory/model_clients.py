"""LTM 的模型调用客户端, 每个 client 对应一个 model target.

已实现的 client:
- LtmExtractorClient     -> target "system:ltm_extract"     写入侧, 从事实窗口提取 MemoryEntry
- LtmEmbeddingClient     -> target "system:ltm_embed"       写入 + 检索两侧, 文本向量化
- LtmQueryPlannerClient  -> target "system:ltm_query_plan"  检索侧, 把检索请求拆成三路查询计划

尚未实现的 target:
- "system:ltm_answer" (答案整合) -- target 已在 model_targets.py 和 WebUI 注册, 但还没有对应的 client. 设计意图是在三路检索命中 top-k 条记忆后, 再调一次 LLM
  作用是整合零散记忆再注入上下文. 问题是检索链路又加了一个 LLM, 耗时太高
  当前第一版跳过了这一步, 由 LtmRenderer 直接把 entry 渲染成 XML 注入.

prompt 文件统一放在同级 prompts/ 目录下, 由 _load_prompt() 加载.
"""

from __future__ import annotations

import json
from pathlib import Path
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

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(filename: str) -> str:
    """从 prompts/ 目录加载一个 prompt 文本文件.

    Args:
        filename: 文件名, 例如 "query_planner_system.txt".

    Returns:
        文件内容字符串.

    Raises:
        RuntimeError: 文件不存在或无法读取时抛出.
    """

    path = _PROMPTS_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"无法加载 prompt 文件 {path}: {exc}") from exc


# region Extractor
class LtmExtractorClient:
    """调 system:ltm_extract 模型, 从事实窗口里提取 MemoryEntry.

    调用链路:
      build_extraction_window_payload() 组装 prompt
      -> agent.complete() 调模型
      -> parse_extractor_response() 校验 + 转成 MemoryEntry

    Attributes:
        agent (BaseAgent): 底层 completion agent.
        model_registry_manager (FileSystemModelRegistryManager | None): 模型注册表管理器.
        extractor_version (str): 写进每条 MemoryEntry 的版本标记,
            用于后续按版本筛选和重新提取.
    """

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
            model_registry_manager: 模型注册表管理器, None 时调用会直接报错.
            extractor_version: 当前提取器版本标记, 默认 "ltm-extractor-v1".
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

        流程:
        1. build_extraction_window_payload() 把 facts 组装成 system prompt + user message
        2. 调 system:ltm_extract 模型拿到 JSON 输出
        3. parse_extractor_response() 做 anchor 解析, evidence 校验, 转成 MemoryEntry

        Args:
            conversation_id: 所属对话容器.
            facts: 当前窗口的事实列表.
            now_ts: 当前时间戳, 写进 MemoryEntry 的 created_at / updated_at.

        Returns:
            当前窗口提取出的 MemoryEntry 列表.

        Raises:
            WindowExtractionError: target 未配置 / 模型返回非法 JSON / entry 校验失败.
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
        """从 model registry 解析一个必需的模型 target.

        Args:
            target_id: 目标位点, 例如 "system:ltm_extract".

        Returns:
            已解析的 RuntimeModelRequest.

        Raises:
            WindowExtractionError: registry 为空或 target 未配置.
        """

        if self.model_registry_manager is None:
            raise WindowExtractionError("model registry manager is required")
        request = self.model_registry_manager.resolve_target_request(target_id)
        if request is None:
            raise WindowExtractionError(f"model target is not configured: {target_id}")
        return request


# endregion


# region Embedding
class LtmEmbeddingClient:
    """调 system:ltm_embed 模型, 把文本变成向量.

    提供两个入口:
    - embed_entries(): 专门给 MemoryEntry 用, 拼接 topic + lossless_restatement 再向量化
    - embed_texts(): 通用文本向量化, 检索侧用这个

    Attributes:
        embedding_runtime (ModelEmbeddingRuntime): 底层 embedding runtime.
        model_registry_manager (FileSystemModelRegistryManager | None): 模型注册表管理器.
    """

    def __init__(
        self,
        *,
        embedding_runtime: ModelEmbeddingRuntime,
        model_registry_manager: FileSystemModelRegistryManager | None,
    ) -> None:
        """初始化 embedding 客户端.

        Args:
            embedding_runtime: 底层 embedding runtime.
            model_registry_manager: 模型注册表管理器, None 时调用会直接报错.
        """

        self.embedding_runtime = embedding_runtime
        self.model_registry_manager = model_registry_manager

    async def embed_entries(self, entries: list[MemoryEntry]) -> list[list[float]]:
        """把一批 MemoryEntry 变成向量, 写入侧用这个.

        每条 entry 拼成 "Topic: {topic}. Fact: {lossless_restatement}" 再送去向量化.

        Args:
            entries: 待向量化的 MemoryEntry 列表.

        Returns:
            与输入一一对应的向量列表, 空输入返回空列表.
        """

        if not entries:
            return []
        request = self._require_target_request("system:ltm_embed")
        texts = [f"Topic: {entry.topic}. Fact: {entry.lossless_restatement}" for entry in entries]
        return await self.embedding_runtime.embed_texts(request, texts)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """把任意文本列表变成向量, 检索侧用这个.

        Args:
            texts: 待向量化的查询文本列表.

        Returns:
            与输入一一对应的向量列表, 空输入返回空列表.
        """

        if not texts:
            return []
        request = self._require_target_request("system:ltm_embed")
        return await self.embedding_runtime.embed_texts(request, texts)

    def _require_target_request(self, target_id: str) -> RuntimeModelRequest:
        """从 model registry 解析一个必需的模型 target.

        Args:
            target_id: 目标位点, 例如 "system:ltm_embed".

        Returns:
            已解析的 RuntimeModelRequest.

        Raises:
            RuntimeError: registry 为空或 target 未配置.
        """

        if self.model_registry_manager is None:
            raise RuntimeError("model registry manager is required")
        request = self.model_registry_manager.resolve_target_request(target_id)
        if request is None:
            raise RuntimeError(f"model target is not configured: {target_id}")
        return request


# endregion


# region Query
class LtmQueryPlannerClient:
    """调 system:ltm_query_plan 模型, 把一条检索请求拆成三路查询计划.

    输入: 检索现场材料 (query_text, conversation_id, working_summary, retained_history)
    输出: {semantic_queries, lexical_queries, symbolic_filters}

    system prompt 从 prompts/query_planner_system.txt 加载,
    检索请求 JSON 作为 user message 发送.

    Attributes:
        agent (BaseAgent): 底层 completion agent.
        model_registry_manager (FileSystemModelRegistryManager | None): 模型注册表管理器.
    """

    def __init__(
        self,
        *,
        agent: BaseAgent,
        model_registry_manager: FileSystemModelRegistryManager | None,
    ) -> None:
        """初始化 query planner 客户端.

        Args:
            agent: 底层 completion agent.
            model_registry_manager: 模型注册表管理器, None 时调用会直接报错.
        """

        self.agent = agent
        self.model_registry_manager = model_registry_manager

    async def plan_query(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        """调模型把检索请求拆成三路查询计划.

        流程:
        1. 加载 query_planner_system.txt 作为 system prompt
        2. 把 request_payload 序列化成 JSON 作为 user message
        3. 解析模型输出, 规范化三个字段

        Args:
            request_payload: 检索现场材料, 包含 query_text / conversation_id /
                working_summary / retained_history / metadata.

        Returns:
            规范化后的查询计划, 固定包含三个字段:
            - semantic_queries: list[str] -- 语义查询文本
            - lexical_queries: list[str] -- 词法查询文本
            - symbolic_filters: dict -- 结构过滤条件 (persons/entities/location/time_range)

        Raises:
            RuntimeError: target 未配置 / 模型返回非法 JSON.
        """

        request = self._require_target_request("system:ltm_query_plan")
        system_prompt = _load_prompt("query_planner_system.txt")
        response = await self.agent.complete(
            system_prompt=system_prompt,
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
        # 兼容模型把结果包在 {"plan": {...}} 里的情况
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
        """从 model registry 解析一个必需的模型 target.

        Args:
            target_id: 目标位点, 例如 "system:ltm_query_plan".

        Returns:
            已解析的 RuntimeModelRequest.

        Raises:
            RuntimeError: registry 为空或 target 未配置.
        """

        if self.model_registry_manager is None:
            raise RuntimeError("model registry manager is required")
        request = self.model_registry_manager.resolve_target_request(target_id)
        if request is None:
            raise RuntimeError(f"model target is not configured: {target_id}")
        return request

    @staticmethod
    def _normalize_symbolic_filters(raw_value: Any) -> dict[str, Any]:
        """规范化模型返回的 symbolic_filters, 清理空值和格式.

        处理逻辑:
        - persons / entities: 过滤空字符串, 去首尾空白
        - location: 空字符串转 None
        - time_range: 只接受长度为 2 的 list/tuple, 两端都是 None 时整个字段设为 None

        Args:
            raw_value: 模型原始输出, 可能不是 dict.

        Returns:
            规范化后的字典, 固定包含 persons / entities / location / time_range.
            输入不是 dict 时返回全空结构.
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


# endregion


__all__ = [
    "LtmEmbeddingClient",
    "LtmExtractorClient",
    "LtmQueryPlannerClient",
]
