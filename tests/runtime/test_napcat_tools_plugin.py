"""NapCat runtime plugin 测试.

验证目标:
- 查询类 QQ tools 能以 runtime plugin 形态注册到 ToolBroker
- 插件配置里的 enabled_tools 会影响最终注册结果
- build_runtime_components 能按配置加载内置 NapCat plugin
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acabot.config import Config
from acabot.runtime import (
    ResolvedAgent,
    NapCatToolsPlugin,
    RuntimePluginManager,
    ToolBroker,
    build_runtime_components,
)

from ._agent_fakes import FakeAgent, FakeAgentResponse
from .test_model_agent_runtime import _context
from .test_outbox import FakeGateway


# region gateway fake
class ToolGateway(FakeGateway):
    """带 API 假响应的 gateway fake.

    Attributes:
        api_calls (list[tuple[str, dict[str, object]]]): 调用记录.
    """

    def __init__(self) -> None:
        """初始化 API 假响应表."""

        super().__init__()
        self.api_calls: list[tuple[str, dict[str, object]]] = []

    async def call_api(self, action: str, params: dict[str, object]) -> dict[str, object]:
        """按 action 返回固定响应.

        Args:
            action: 平台 API 名称.
            params: API 参数.

        Returns:
            一份模拟的 OneBot API 返回.
        """

        self.api_calls.append((action, dict(params)))
        if action == "get_stranger_info":
            return {
                "status": "ok",
                "data": {
                    "user_id": params["user_id"],
                    "nickname": "Acacia",
                },
            }
        if action == "get_group_info":
            return {
                "status": "ok",
                "data": {
                    "group_id": params["group_id"],
                    "group_name": "AcaBot",
                },
            }
        if action == "get_group_member_info":
            return {
                "status": "ok",
                "data": {
                    "user_id": params["user_id"],
                    "group_id": params["group_id"],
                    "card": "Acacia",
                    "role": "admin",
                },
            }
        if action == "get_group_member_list":
            return {
                "status": "ok",
                "data": [
                    {"user_id": 10001, "nickname": "Acacia", "role": "admin"},
                    {"user_id": 10002, "nickname": "Bob", "role": "member"},
                ],
            }
        if action == "get_msg":
            return {
                "status": "ok",
                "data": {
                    "message_id": params["message_id"],
                    "message": [{"type": "text", "data": {"text": "hello"}}],
                },
            }
        return {
            "status": "failed",
            "msg": f"unknown action {action}",
        }


# endregion


def _profile(*, enabled_tools: list[str]) -> ResolvedAgent:
    """构造最小 profile.

    Args:
        enabled_tools: 当前 agent 启用的工具列表.

    Returns:
        一份 ResolvedAgent.
    """

    return ResolvedAgent(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        enabled_tools=list(enabled_tools),
    )


async def test_napcat_tools_plugin_registers_runtime_tools() -> None:
    """验证 NapCatToolsPlugin 能注册查询类运行时工具."""

    gateway = ToolGateway()
    broker = ToolBroker()
    manager = RuntimePluginManager(
        config=Config({}),
        gateway=gateway,
        tool_broker=broker,
        plugins=[NapCatToolsPlugin()],
    )
    await manager.ensure_started()

    ctx = _context()
    ctx.agent = _profile(
        enabled_tools=[
            "get_user_info",
            "get_group_info",
            "get_group_member_info",
            "get_group_member_list",
            "get_message",
        ]
    )
    execution_ctx = broker._build_execution_context(ctx)

    user_info = await broker.execute(
        tool_name="get_user_info",
        arguments={"user_id": 10001},
        ctx=execution_ctx,
    )
    group_info = await broker.execute(
        tool_name="get_group_info",
        arguments={"group_id": 20002},
        ctx=execution_ctx,
    )
    member_info = await broker.execute(
        tool_name="get_group_member_info",
        arguments={"group_id": 20002, "user_id": 10001},
        ctx=execution_ctx,
    )
    member_list = await broker.execute(
        tool_name="get_group_member_list",
        arguments={"group_id": 20002},
        ctx=execution_ctx,
    )
    message = await broker.execute(
        tool_name="get_message",
        arguments={"message_id": 12345},
        ctx=execution_ctx,
    )

    assert "Acacia" in user_info.llm_content
    assert "avatar_url" in user_info.llm_content
    assert "AcaBot" in group_info.llm_content
    assert "admin" in member_info.llm_content
    assert '"members"' in member_list.llm_content
    assert '"message_id": 12345' in message.llm_content
    assert [action for action, _ in gateway.api_calls] == [
        "get_stranger_info",
        "get_group_info",
        "get_group_member_info",
        "get_group_member_list",
        "get_msg",
    ]


async def test_napcat_tools_plugin_respects_enabled_tools_config() -> None:
    """验证插件配置能过滤实际注册工具."""

    gateway = ToolGateway()
    broker = ToolBroker()
    manager = RuntimePluginManager(
        config=Config(
            {
                "plugins": {
                    "napcat_tools": {
                        "enabled_tools": ["get_group_info"],
                    }
                }
            }
        ),
        gateway=gateway,
        tool_broker=broker,
        plugins=[NapCatToolsPlugin()],
    )
    await manager.ensure_started()

    visible = broker.visible_tools(_profile(enabled_tools=["get_group_info", "get_user_info"]))

    assert [tool.name for tool in visible] == ["get_group_info"]


async def test_build_runtime_components_can_load_napcat_tools_plugin_from_config(
    tmp_path: Path,
) -> None:
    """验证默认组装路径能按配置加载内置 NapCat plugin."""

    config = Config(
        {
            "agent": {
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "plugins": [
                    "acabot.runtime.plugins.napcat_tools:NapCatToolsPlugin",
                ],
                "profiles": {
                    "aca": {
                        "name": "Aca",
                        "prompt_ref": "prompt/default",
                        "enabled_tools": ["get_group_info"],
                    }
                },
                "prompts": {
                    "prompt/default": "You are Aca.",
                },
                "persistence": {
                    "sqlite_path": str(tmp_path / "runtime.db"),
                },
            },
            "plugins": {
                "napcat_tools": {
                    "enabled_tools": ["get_group_info"],
                }
            },
        }
    )

    gateway = ToolGateway()
    components = build_runtime_components(
        config,
        gateway=gateway,
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    await components.plugin_manager.ensure_started()

    visible = components.tool_broker.visible_tools(_profile(enabled_tools=["get_group_info"]))
    ctx = _context()
    ctx.agent = _profile(enabled_tools=["get_group_info"])
    result = await components.tool_broker.execute(
        tool_name="get_group_info",
        arguments={"group_id": 20002},
        ctx=components.tool_broker._build_execution_context(ctx),
    )

    assert [tool.name for tool in visible] == ["get_group_info"]
    assert "AcaBot" in result.llm_content
