"""runtime.model.model_embedding_runtime 统一封装 embedding 调用.

这个模块只负责把 `RuntimeModelRequest` 转成 `litellm` embedding 请求:
- 不自己决定用哪个模型
- 不自己解析 target
- 不自己拼接长期记忆语义
"""

from __future__ import annotations

from inspect import isawaitable
from typing import Any

try:
    from litellm import aembedding as _litellm_aembedding
except ImportError:
    _litellm_aembedding = None

from .model_registry import RuntimeModelRequest

aembedding = _litellm_aembedding


class ModelEmbeddingRuntime:
    """ModelEmbeddingRuntime 统一执行 embedding 请求."""

    async def embed_texts(
        self,
        request: RuntimeModelRequest,
        texts: list[str],
    ) -> list[list[float]]:
        """用一个已解析好的模型请求批量生成向量.

        Args:
            request: 已解析好的运行时模型请求.
            texts: 待向量化的文本列表.

        Returns:
            与输入一一对应的向量列表.

        Raises:
            ValueError: 当输入为空或 model 缺失时抛出.
            RuntimeError: 当 `litellm` embedding 依赖不可用时抛出.
        """

        normalized_texts = [str(item or "") for item in list(texts or []) if str(item or "").strip()]
        if not normalized_texts:
            raise ValueError("texts is required")
        if not str(request.model or "").strip():
            raise ValueError("request.model is required")

        embedding = self._get_aembedding()
        kwargs: dict[str, Any] = {
            "model": request.model,
            "input": normalized_texts,
        }
        request_options = dict(request.to_request_options())
        request_options.pop("provider_kind", None)
        kwargs.update(request_options)

        response = embedding(**kwargs)
        if isawaitable(response):
            response = await response
        return self._extract_vectors(response)

    def _extract_vectors(self, response: Any) -> list[list[float]]:
        """从 `litellm` embedding 响应里抽出向量数组.

        Args:
            response: `litellm` 返回对象.

        Returns:
            向量列表.
        """

        data = response.get("data") if isinstance(response, dict) else getattr(response, "data", [])
        vectors: list[list[float]] = []
        for item in list(data or []):
            embedding = item.get("embedding") if isinstance(item, dict) else getattr(item, "embedding", [])
            vectors.append([float(value) for value in list(embedding or [])])
        return vectors

    @staticmethod
    def _get_aembedding():
        """返回可用的 `litellm.aembedding` callable.

        Returns:
            embedding callable.

        Raises:
            RuntimeError: 当 `litellm` 不可用时抛出.
        """

        if aembedding is None:
            raise RuntimeError("litellm dependency is required to run ModelEmbeddingRuntime")
        return aembedding


__all__ = ["ModelEmbeddingRuntime", "aembedding"]
