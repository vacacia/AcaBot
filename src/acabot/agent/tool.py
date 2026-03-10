"""agent.tool 定义 agent runtime 侧的 tool 契约.

这里把:
- LLM 可见的 `ToolSpec`
- 外部执行器 `ToolExecutor`
- legacy convenience 的 `ToolDef`

拆开.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from .response import Attachment

ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


# region spec
@dataclass(slots=True)
class ToolSpec:
    """提供给模型看的 tool schema."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(slots=True)
class ToolExecutionResult:
    """一次 tool 执行后的标准化结果.
    
    Agent 侧的标准接口协议, 不依赖 AcaBot 运行
    """

    content: str | list[dict[str, Any]] = ""
    attachments: list[Attachment] = field(default_factory=list)
    raw: Any = None


class ToolExecutor(Protocol):
    """外部 tool executor 协议."""

    async def __call__(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolExecutionResult:
        """执行一条 tool call.

        Args:
            tool_name: LLM 请求执行的 tool name.
            arguments: LLM 解析出的参数 dict.

        Returns:
            一份标准化的 ToolExecutionResult.
        """

        ...


# endregion


# region legacy convenience
@dataclass(slots=True)
class ToolDef:
    """legacy convenience 的工具定义.

    仍然允许把 schema 和 handler 打包在一起, 但这只是注册便利层.
    真正的执行权在 `ToolExecutor`.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def to_spec(self) -> ToolSpec:
        """提取这条工具定义的模型可见部分.

        Returns:
            对应的 ToolSpec.
        """

        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=dict(self.parameters),
        )


def normalize_tool_result(result: Any) -> ToolExecutionResult:
    """把 legacy handler 返回值归一化成 ToolExecutionResult.

    Args:
        result: legacy tool handler 的原始返回值.

    Returns:
        标准化后的 ToolExecutionResult.
    """

    if isinstance(result, ToolExecutionResult):
        return result

    if isinstance(result, str):
        return ToolExecutionResult(content=result, raw=result)

    if not isinstance(result, dict):
        return ToolExecutionResult(
            content=json.dumps(result, ensure_ascii=False),
            raw=result,
        )

    payload = dict(result)
    attachments: list[Attachment] = []
    if "attachments" in payload:
        raw_attachments = payload.pop("attachments") or []
        attachments = [
            Attachment(
                type=str(item.get("type", "file")),
                url=str(item.get("url", "")),
                data=str(item.get("data", "")),
                metadata=dict(item.get("metadata", {})),
            )
            for item in raw_attachments
        ]

    return ToolExecutionResult(
        content=json.dumps(payload, ensure_ascii=False),
        attachments=attachments,
        raw=result,
    )


# endregion
