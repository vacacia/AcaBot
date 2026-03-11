from pathlib import Path

from acabot.config import Config
from acabot.runtime import (
    AgentProfile,
    LocalReferenceBackend,
    ReferenceToolsPlugin,
    RuntimePluginManager,
    ToolBroker,
    build_runtime_components,
)

from .test_model_agent_runtime import FakeAgent, _context
from .test_bootstrap import FakeAgentResponse
from .test_outbox import FakeGateway


def _profile() -> AgentProfile:
    return AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
        enabled_tools=[
            "reference_add_document",
            "reference_search",
            "reference_read",
        ],
    )


async def test_reference_tools_plugin_can_add_search_and_read(tmp_path: Path) -> None:
    backend = LocalReferenceBackend(str(tmp_path / "reference.sqlite3"))
    config = Config(
        {
            "plugins": {
                "reference_tools": {
                    "default_tenant_id": "qq",
                    "default_space_id": "group-123",
                    "default_mode": "readonly_reference",
                },
            },
        }
    )
    broker = ToolBroker()
    manager = RuntimePluginManager(
        config=config,
        gateway=FakeGateway(),
        tool_broker=broker,
        reference_backend=backend,
        plugins=[ReferenceToolsPlugin()],
    )
    await manager.ensure_started()

    ctx = _context()
    ctx.profile = _profile()
    execution_ctx = broker._build_execution_context(ctx)

    created = await broker.execute(
        tool_name="reference_add_document",
        arguments={
            "title": "实习要求",
            "content": "十个月的只需要实习成果鉴定, 不用实习证明.",
            "overview": "十个月实习材料要求",
            "tags": ["internship", "faq"],
        },
        ctx=execution_ctx,
    )
    searched = await broker.execute(
        tool_name="reference_search",
        arguments={
            "query": "十个月 实习 证明",
            "body": "overview",
        },
        ctx=execution_ctx,
    )
    ref_id = created.raw["ref_id"]
    read_back = await broker.execute(
        tool_name="reference_read",
        arguments={"ref_id": ref_id},
        ctx=execution_ctx,
    )

    assert "实习要求" in created.llm_content
    assert "十个月实习材料要求" in searched.llm_content
    assert "不用实习证明" in read_back.llm_content


async def test_build_runtime_components_can_load_reference_tools_plugin_from_config(
    tmp_path: Path,
) -> None:
    config = Config(
        {
            "agent": {
                "default_model": "test-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "plugins": [
                    "acabot.runtime.plugins.reference_tools:ReferenceToolsPlugin",
                ],
                "reference": {
                    "enabled": True,
                    "provider": "local",
                    "local": {
                        "sqlite_path": str(tmp_path / "reference.sqlite3"),
                    },
                },
            },
            "plugins": {
                "reference_tools": {
                    "default_tenant_id": "qq",
                    "default_space_id": "group-123",
                    "default_mode": "readonly_reference",
                },
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    await components.plugin_manager.ensure_started()

    ctx = _context()
    ctx.profile = _profile()
    execution_ctx = components.tool_broker._build_execution_context(ctx)
    result = await components.tool_broker.execute(
        tool_name="reference_add_document",
        arguments={
            "title": "群规摘要",
            "content": "新人入群后先看精华和群公告.",
        },
        ctx=execution_ctx,
    )

    assert "群规摘要" in result.llm_content
