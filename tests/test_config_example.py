"""config.example.yaml 同步检查.

这一组测试的目标不是覆盖所有配置分支.
它只保证仓库里的示例配置仍然能组装出新的 runtime 主线.
"""

from __future__ import annotations

from pathlib import Path

from acabot.agent import AgentResponse, BaseAgent
from acabot.config import Config
from acabot.runtime import build_runtime_components

from .runtime.test_outbox import FakeGateway


class ConfigExampleAgent(BaseAgent):
    """用于 config.example 组装测试的最小 agent."""

    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, object]],
        model: str | None = None,
        *,
        request_options=None,
        max_tool_rounds=None,
        tools=None,
        tool_executor=None,
    ) -> AgentResponse:
        """返回一份最小文本响应.

        Args:
            system_prompt: 当前 system prompt.
            messages: 当前消息列表.
            model: 当前模型名.
            request_options: 当前 run 解析好的 request options.
            max_tool_rounds: 当前 run 允许的最大 tool loop 轮数.
            tools: 当前可见 tools.
            tool_executor: 当前 tool executor.

        Returns:
            一份最小 AgentResponse.
        """

        _ = system_prompt, messages, model, request_options, max_tool_rounds, tools, tool_executor
        return AgentResponse(text="ok")

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, object]],
        model: str | None = None,
        request_options=None,
    ) -> AgentResponse:
        """返回一份最小摘要响应.

        Args:
            system_prompt: 当前 system prompt.
            messages: 当前消息列表.
            model: 当前模型名.

        Returns:
            一份最小 AgentResponse.
        """

        _ = system_prompt, messages, model, request_options
        return AgentResponse(text="summary")


async def test_config_example_builds_runtime_components(tmp_path: Path) -> None:
    """验证 config.example.yaml 仍然指向 runtime 主线."""

    config = Config.from_file(str(Path("config.example.yaml")))
    config.get("runtime", {}).setdefault("persistence", {})["sqlite_path"] = str(
        tmp_path / "runtime.db"
    )
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=ConfigExampleAgent(),
    )
    await components.plugin_manager.ensure_started()

    assert components.router.default_agent_id == "aca"
    assert components.prompt_loader.load("prompt/default").strip() == "you are a helpful assistant."
    assert components.plugin_manager.loaded[0].name == "ops_control"
