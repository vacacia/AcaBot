from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Awaitable

# async handler: 接收 LLM 解析出的参数 dict, 返回任意结果
ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass
class ToolDef:
    """注册给 Agent 的工具定义.

    Attributes:
        name: 工具名, LLM 通过此名字调用.
        description: 工具描述, 帮助 LLM 理解何时使用.
        parameters: JSON Schema 格式的参数定义(与 OpenAI function calling 一致).
        handler: 实际执行函数.
    """
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
