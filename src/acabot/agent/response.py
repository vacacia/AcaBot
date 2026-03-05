from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Attachment:
    """Tool 产出的富内容附件.

    Agent 层不感知平台消息格式,
    由 post_llm hook 负责把 Attachment 转成对应的 MsgSegment.

    Attributes:
        type: 附件类型, 如 "image" | "file" | "audio".
            参照 OpenAI里content的type, 保留裸字符串 可扩展
        url: URL 或本地文件路径.
        data: base64 数据(url 为空时用) -> 内部 API 不考虑 url/data 互相约束
        metadata: 附加信息, 如 {"width": 800, "height": 600}.
    """

    type: str
    url: str = ""
    data: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallRecord:
    """一次 tool call 的结构化记录.

    Attributes:
        name: 工具名.
        arguments: LLM 传入的参数.
        result: 工具执行结果.
    """

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result: Any = None


@dataclass
class AgentResponse:
    """LLM 一次调用的完整结果.

    Attributes:
        text: 文本回复.
        attachments: tool 产出的富内容附件列表.
        error: 错误信息. None 表示正常, 有值表示出错.
        usage: token 用量, 如 {"prompt_tokens": 100, "completion_tokens": 50}.
        tool_calls_made: 本次调用中执行过的 tool call 记录.
        model_used: 实际使用的模型名.
        raw: LLM 原始返回, 调试用.
    """

    text: str = ""
    attachments: list[Attachment] = field(default_factory=list)
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls_made: list[ToolCallRecord] = field(default_factory=list)
    model_used: str = ""
    raw: Any = None
