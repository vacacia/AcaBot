"""runtime 发布检查级集成测试.

组件关系:

    Config + build_runtime_components()
                  |
                  v
         RuntimeApp / ControlPlane
                  |
                  v
      SQLite stores + restart recovery

这一组测试不关注某个局部组件.
它验证当前 runtime 主线在真实组装条件下是否已经形成 release checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from acabot.agent import AgentResponse, BaseAgent, ToolSpec
from acabot.config import Config
from acabot.runtime import (
    ResolvedAgent,
    FileSystemModelRegistryManager,
    ModelBinding,
    ModelPreset,
    ModelProvider,
    OpenAICompatibleProviderConfig,
    ToolBroker,
    ToolPolicyDecision,
    build_agent_model_targets,
    build_runtime_components,
)
from acabot.types import EventSource, MsgSegment, StandardEvent

from .test_outbox import FakeGateway


# region fake agents
@dataclass
class EchoCheckpointAgent(BaseAgent):
    """用于发布检查的最小文本 agent.

    Attributes:
        reply_text (str): 正常回复文本.
        summary_text (str): compaction 摘要文本.
        calls (list[dict[str, Any]]): run 调用记录.
    """

    reply_text: str = "hello back"
    summary_text: str = "summary"
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        *,
        request_options=None,
        max_tool_rounds=None,
        tools=None,
        tool_executor=None,
    ) -> AgentResponse:
        """执行一次最小文本调用.

        Args:
            system_prompt: 当前 system prompt.
            messages: 当前消息列表.
            model: 当前模型名.
            request_options: 当前 run 解析好的 request options.
            max_tool_rounds: 当前 run 允许的最大 tool loop 轮数.
            tools: 当前 run 暴露的 tools.
            tool_executor: 当前 run 的 tool executor.

        Returns:
            一份普通文本 AgentResponse.
        """

        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": list(messages),
                "model": model,
                "request_options": dict(request_options or {}),
                "max_tool_rounds": max_tool_rounds,
                "tools": list(tools or []),
                "tool_executor": tool_executor,
            }
        )
        return AgentResponse(
            text=self.reply_text,
            model_used=model or "",
        )

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        request_options=None,
    ) -> AgentResponse:
        """执行一次最小摘要调用.

        Args:
            system_prompt: 当前 system prompt.
            messages: 当前消息列表.
            model: 当前模型名.

        Returns:
            一份普通摘要响应.
        """

        _ = system_prompt, messages, request_options
        return AgentResponse(text=self.summary_text, model_used=model or "")


@dataclass
class ApprovalCheckpointAgent(BaseAgent):
    """用于审批恢复检查的 tool-calling agent.

    Attributes:
        summary_text (str): compaction 摘要文本.
        calls (list[dict[str, Any]]): run 调用记录.
    """

    summary_text: str = "summary"
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        *,
        request_options=None,
        max_tool_rounds=None,
        tools=None,
        tool_executor=None,
    ) -> AgentResponse:
        """执行一次会触发审批的 tool 调用.

        Args:
            system_prompt: 当前 system prompt.
            messages: 当前消息列表.
            model: 当前模型名.
            request_options: 当前 run 解析好的 request options.
            max_tool_rounds: 当前 run 允许的最大 tool loop 轮数.
            tools: 当前 run 暴露的 tools.
            tool_executor: 当前 run 的 tool executor.

        Returns:
            正常情况下的一份空响应.
        """

        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": list(messages),
                "model": model,
                "request_options": dict(request_options or {}),
                "max_tool_rounds": max_tool_rounds,
                "tools": list(tools or []),
                "tool_executor": tool_executor,
            }
        )
        if tool_executor is not None:
            await tool_executor("restricted", {"cmd": "ls"})
        return AgentResponse(model_used=model or "")

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        request_options=None,
    ) -> AgentResponse:
        """执行一次最小摘要调用.

        Args:
            system_prompt: 当前 system prompt.
            messages: 当前消息列表.
            model: 当前模型名.

        Returns:
            一份普通摘要响应.
        """

        _ = system_prompt, messages, request_options
        return AgentResponse(text=self.summary_text, model_used=model or "")


# endregion


# region helpers
def _event(*, event_id: str = "evt-1", text: str = "hello") -> StandardEvent:
    """构造最小标准事件.

    Args:
        event_id: 事件 ID.
        text: 文本消息内容.

    Returns:
        一份 StandardEvent.
    """

    return StandardEvent(
        event_id=event_id,
        event_type="message",
        platform="qq",
        timestamp=123,
        source=EventSource(
            platform="qq",
            message_type="private",
            user_id="10001",
            group_id=None,
        ),
        segments=[MsgSegment(type="text", data={"text": text})],
        raw_message_id=f"msg-{event_id}",
        sender_nickname="acacia",
        sender_role=None,
    )


def _write_session_bundle(db_path: Path, *, session_id: str, agent_id: str, prompt_ref: str, enabled_tools: list[str] | None = None) -> None:
    base = db_path.parent
    platform, scope_kind, identifier = session_id.split(":", 2)
    bundle_dir = base / "sessions" / platform / scope_kind / identifier
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        "\n".join(
            [
                "session:",
                f"  id: {session_id}",
                "frontstage:",
                f"  agent_id: {agent_id}",
            ]
        ),
        encoding="utf-8",
    )
    tools_yaml = "\n".join(f"  - {t}" for t in (enabled_tools or []))
    (bundle_dir / "agent.yaml").write_text(
        "\n".join(
            [
                f"agent_id: {agent_id}",
                f"prompt_ref: {prompt_ref}",
                "visible_tools:",
                tools_yaml if tools_yaml else "  []",
                "visible_skills: []",
                "visible_subagents: []",
            ]
        ),
        encoding="utf-8",
    )


def _write_prompt_file(db_path: Path, *, ref: str, body: str) -> None:
    base = db_path.parent
    prompts_dir = base / "prompts"
    parts = ref.split("/", 1)
    if len(parts) == 2:
        prompt_file = prompts_dir / f"{parts[1]}.md"
    else:
        prompt_file = prompts_dir / f"{ref}.md"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(body, encoding="utf-8")


def _config(db_path: Path, *, enabled_tools: list[str] | None = None) -> Config:
    """构造带 SQLite 持久化的 runtime 配置.

    Args:
        db_path: SQLite 数据库路径.
        enabled_tools: 可选的 profile enabled_tools.

    Returns:
        一份 Config.
    """

    base = db_path.parent
    _write_prompt_file(db_path, ref="prompt/default", body="You are Aca.")
    _write_session_bundle(
        db_path,
        session_id="qq:user:10001",
        agent_id="aca",
        prompt_ref="prompt/default",
        enabled_tools=enabled_tools,
    )
    return Config(
        {
            "runtime": {
                "filesystem": {
                    "base_dir": str(base),
                },
                "profiles": {
                    "aca": {
                        "name": "Aca",
                        "prompt_ref": "prompt/default",
                        "enabled_tools": list(enabled_tools or []),
                    }
                },
                "persistence": {
                    "sqlite_path": str(db_path),
                },
            }
        }
    )


async def _model_registry_manager(tmp_path: Path) -> FileSystemModelRegistryManager:
    """构造 release checkpoint 测试用的最小模型注册表.

    Args:
        tmp_path: pytest 临时目录.

    Returns:
        FileSystemModelRegistryManager: 绑定好 `agent:aca` 的模型注册表.
    """

    manager = FileSystemModelRegistryManager(
        providers_dir=tmp_path / "models" / "providers",
        presets_dir=tmp_path / "models" / "presets",
        bindings_dir=tmp_path / "models" / "bindings",
    )
    manager.target_catalog.replace_agent_targets(
        build_agent_model_targets(
            [
                ResolvedAgent(
                    agent_id="aca",
                    name="Aca",
                    prompt_ref="prompt/default",
                )
            ]
        )
    )
    await manager.upsert_provider(
        ModelProvider(
            provider_id="openai-main",
            kind="openai_compatible",
            config=OpenAICompatibleProviderConfig(
                base_url="https://example.invalid/v1",
                api_key_env="OPENAI_API_KEY",
            ),
        )
    )
    await manager.upsert_preset(
        ModelPreset(
            preset_id="aca-main",
            provider_id="openai-main",
            model="runtime-model",
            task_kind="chat",
            capabilities=["tool_calling"],
            context_window=128000,
        )
    )
    await manager.upsert_binding(
        ModelBinding(
            binding_id="binding:aca",
            target_id="agent:aca",
            preset_ids=["aca-main"],
        )
    )
    return manager


def _close_runtime_components(components: Any) -> None:
    """关闭 runtime 组件树里的 SQLite 连接.

    Args:
        components: build_runtime_components 返回的 RuntimeComponents.
    """

    closables = [
        getattr(getattr(components, "thread_manager", None), "store", None),
        getattr(getattr(components, "run_manager", None), "store", None),
        getattr(components, "channel_event_store", None),
        getattr(components, "message_store", None),
    ]
    seen_ids: set[int] = set()
    for item in closables:
        if item is None:
            continue
        item_id = id(item)
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        close = getattr(item, "close", None)
        if callable(close):
            close()


# endregion


# region release checkpoint
async def test_release_checkpoint_runtime_persists_facts_across_restart(
    tmp_path: Path,
) -> None:
    """验证默认主线在重启后仍能恢复事实层数据.

    Args:
        tmp_path: pytest 临时目录.
    """

    db_path = tmp_path / "runtime.db"

    gateway1 = FakeGateway()
    components1 = build_runtime_components(
        _config(db_path),
        gateway=gateway1,
        agent=EchoCheckpointAgent(),
        model_registry_manager=await _model_registry_manager(tmp_path),
    )
    try:
        components1.app.install()
        await gateway1.handler(_event())
    finally:
        await components1.app.stop()
        _close_runtime_components(components1)

    gateway2 = FakeGateway()
    components2 = build_runtime_components(
        _config(db_path),
        gateway=gateway2,
        agent=EchoCheckpointAgent(reply_text="unused"),
        model_registry_manager=await _model_registry_manager(tmp_path),
    )
    try:
        thread = await components2.thread_manager.get("qq:user:10001")
        events = await components2.channel_event_store.get_thread_events("qq:user:10001")
        messages = await components2.message_store.get_thread_messages("qq:user:10001")
        status = await components2.control_plane.get_status()
    finally:
        await components2.app.stop()
        _close_runtime_components(components2)

    assert thread is not None
    assert thread.working_messages[-2]["role"] == "user"
    assert thread.working_messages[-2]["content"] == "[acacia/10001] hello"
    assert thread.working_messages[-1]["role"] == "assistant"
    assert thread.working_messages[-1]["content"] == "hello back"
    assert len(events) == 1
    assert events[0].event_type == "message"
    assert events[0].content_text == "hello"
    assert len(messages) == 1
    assert messages[0].content_text == "hello back"
    assert status.active_run_count == 0
    assert status.pending_approval_count == 0


async def test_release_checkpoint_runtime_recovers_pending_approval_after_restart(
    tmp_path: Path,
) -> None:
    """验证 waiting_approval run 能穿过完整重启恢复.

    Args:
        tmp_path: pytest 临时目录.
    """

    class ApprovalPolicy:
        async def allow(self, *, spec, arguments, ctx) -> ToolPolicyDecision:
            _ = spec, arguments, ctx
            return ToolPolicyDecision(
                allowed=True,
                requires_approval=True,
                reason="needs admin approval",
                metadata={"risk_level": "dangerous"},
            )

    db_path = tmp_path / "runtime.db"
    broker1 = ToolBroker(policy=ApprovalPolicy())
    broker1.register_tool(
        ToolSpec(
            name="restricted",
            description="Restricted tool",
            parameters={"type": "object", "properties": {}},
        ),
        lambda arguments, ctx: {"ok": True},
    )

    gateway1 = FakeGateway()
    components1 = build_runtime_components(
        _config(db_path, enabled_tools=["restricted"]),
        gateway=gateway1,
        agent=ApprovalCheckpointAgent(),
        tool_broker=broker1,
        model_registry_manager=await _model_registry_manager(tmp_path),
    )
    try:
        components1.app.install()
        await gateway1.handler(_event(text="run restricted tool"))
        status1 = await components1.control_plane.get_status()
    finally:
        await components1.app.stop()
        _close_runtime_components(components1)

    assert status1.active_run_count == 1
    assert status1.pending_approval_count == 0
    assert gateway1.sent[0].payload["text"].startswith("[审批]")

    broker2 = ToolBroker(policy=ApprovalPolicy())
    broker2.register_tool(
        ToolSpec(
            name="restricted",
            description="Restricted tool",
            parameters={"type": "object", "properties": {}},
        ),
        lambda arguments, ctx: {"ok": True},
    )
    gateway2 = FakeGateway()
    components2 = build_runtime_components(
        _config(db_path, enabled_tools=["restricted"]),
        gateway=gateway2,
        agent=ApprovalCheckpointAgent(),
        tool_broker=broker2,
        model_registry_manager=await _model_registry_manager(tmp_path),
    )
    try:
        await components2.app.start()
        status2 = await components2.control_plane.get_status()
        pending = components2.app.list_pending_approvals()
    finally:
        await components2.app.stop()
        _close_runtime_components(components2)

    assert status2.active_run_count == 1
    assert status2.pending_approval_count == 1
    assert pending[0].approval_context["tool_name"] == "restricted"
    assert pending[0].approval_context["reason"] == "needs admin approval"


# endregion
