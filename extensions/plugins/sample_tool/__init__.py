"""sample_tool 示例插件.

演示如何用新插件体系编写一个最简单的工具插件.
"""

from __future__ import annotations

from typing import Any

from acabot.agent import ToolSpec
from acabot.runtime.plugin_protocol import (
    RuntimePlugin,
    RuntimePluginContext,
    RuntimeToolRegistration,
)
from acabot.runtime.tool_broker import ToolHandler as RuntimeToolHandler


class Plugin(RuntimePlugin):
    """示例工具插件.

    提供一个 sample_greeting 工具, 返回可配置的问候语.
    """

    name = "sample_tool"

    def __init__(self) -> None:
        self._greeting: str = "Hello from AcaBot"

    async def setup(self, runtime: RuntimePluginContext) -> None:
        """读取 plugin_config 中的 greeting 配置.

        Args:
            runtime: 插件上下文.
        """

        self._greeting = str(
            runtime.plugin_config.get("greeting", self._greeting)
        )

    def runtime_tools(self) -> list[RuntimeToolRegistration]:
        """注册 sample_greeting 工具.

        Returns:
            包含一条 RuntimeToolRegistration 的列表.
        """

        greeting = self._greeting

        async def handler(arguments: dict[str, Any], ctx: Any) -> str:
            """返回问候语.

            Args:
                arguments: 包含 name 字段的参数字典.
                ctx: 工具执行上下文 (此处不使用).

            Returns:
                问候字符串.
            """

            _ = ctx
            name = str(arguments.get("name", "World"))
            return f"{greeting}, {name}!"

        return [
            RuntimeToolRegistration(
                spec=ToolSpec(
                    name="sample_greeting",
                    description="返回一条问候语",
                    parameters={
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "要问候的名字",
                            },
                        },
                        "required": ["name"],
                    },
                ),
                handler=handler,
            ),
        ]
