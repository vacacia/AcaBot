"""runtime plugin sample module.

这个文件专门给 runtime plugin 的 import-path 测试使用.
避免把测试样例写在 test 文件里, 导致 import path 不稳定.
"""

from __future__ import annotations

from acabot.agent import ToolDef
from acabot.runtime import (
    RuntimePlugin,
    RuntimePluginContext,
)


class SampleConfiguredRuntimePlugin(RuntimePlugin):
    """用于 config-driven plugin loading 测试的样例插件."""

    name = "sample_configured_runtime"
    setup_calls = 0
    teardown_calls = 0

    @classmethod
    def reset(cls) -> None:
        """重置类级测试计数器."""

        cls.setup_calls = 0
        cls.teardown_calls = 0

    async def setup(self, runtime: RuntimePluginContext) -> None:
        """记录一次 setup 调用.

        Args:
            runtime: runtime plugin 上下文.
        """

        _ = runtime
        type(self).setup_calls += 1

    def tools(self) -> list[ToolDef]:
        """返回一条测试工具.

        Returns:
            一条 sample tool.
        """

        async def handler(arguments):
            return {"echo": arguments.get("text", "")}

        return [
            ToolDef(
                name="sample_configured_tool",
                description="Sample configured runtime tool.",
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                    },
                    "required": ["text"],
                },
                handler=handler,
            )
        ]

    async def teardown(self) -> None:
        """记录一次 teardown 调用."""

        type(self).teardown_calls += 1


class AnotherConfiguredRuntimePlugin(RuntimePlugin):
    """第二个 config-driven runtime plugin, 用于精确 reload 测试."""

    name = "another_configured_runtime"
    setup_calls = 0
    teardown_calls = 0

    @classmethod
    def reset(cls) -> None:
        """重置类级测试计数器."""

        cls.setup_calls = 0
        cls.teardown_calls = 0

    async def setup(self, runtime: RuntimePluginContext) -> None:
        """记录一次 setup 调用.

        Args:
            runtime: runtime plugin 上下文.
        """

        _ = runtime
        type(self).setup_calls += 1

    async def teardown(self) -> None:
        """记录一次 teardown 调用."""

        type(self).teardown_calls += 1
