from pathlib import Path

from acabot.runtime import (
    InMemoryChannelEventStore,
    InMemoryRunManager,
    InMemoryThreadManager,
    Outbox,
    ResolvedAgent,
    RuntimeApp,
    RuntimeRouter,
    SessionConfigLoader,
    SessionRuntime,
    ThreadPipeline,
)
from acabot.types import EventSource, MsgSegment, StandardEvent

from .test_outbox import FakeGateway, FakeMessageStore
from .test_pipeline_runtime import FakeAgentRuntime


class CapturingAgentRuntime(FakeAgentRuntime):
    """在调用父类前先把 RunContext 记下来.

    Attributes:
        last_ctx (object | None): 最近一次执行时收到的上下文.
    """

    def __init__(self) -> None:
        """初始化捕获器."""

        self.last_ctx = None

    async def execute(self, ctx):
        """记录当前上下文并继续执行原有假 agent 逻辑.

        Args:
            ctx: 当前 run 的上下文对象.

        Returns:
            object: 父类执行结果.
        """

        self.last_ctx = ctx
        return await super().execute(ctx)


# region helpers

def _write_session(tmp_path: Path) -> Path:
    """写入一份用于 RuntimeApp 集成测试的 session config.

    Args:
        tmp_path (Path): pytest 提供的临时目录.

    Returns:
        Path: 配置文件路径.
    """

    bundle_dir = tmp_path / "sessions/qq/group/123"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        """
session:
  id: qq:group:123
  template: qq_group
frontstage:
  agent_id: aca.qq.group.default
selectors:
  sender_is_admin:
    sender_roles: [admin]
surfaces:
  message.mention:
    routing:
      default:
        agent_id: aca.qq.group.default
    admission:
      default:
        mode: respond
    persistence:
      default:
        persist_event: true
    extraction:
      default: {}
    computer:
      default:
        backend: docker
        allow_exec: true
        allow_sessions: true
      cases:
        - case_id: admin_host
          when_ref: sender_is_admin
          use:
            backend: host
  message.plain:
    routing:
      default:
        agent_id: aca.qq.group.default
    admission:
      default:
        mode: record_only
    persistence:
      default:
        persist_event: true
""".strip(),
        encoding="utf-8",
    )
    (bundle_dir / "agent.yaml").write_text(
        """
agent_id: aca.qq.group.default
prompt_ref: prompt/aca.qq.group.default
visible_tools:
  - read
visible_skills: []
visible_subagents: []
""".strip(),
        encoding="utf-8",
    )
    return bundle_dir



def _group_event(*, text: str, mentions_self: bool, sender_role: str | None = None) -> StandardEvent:
    """构造一条群消息事件.

    Args:
        text (str): 消息文本.
        mentions_self (bool): 是否显式提到 bot.
        sender_role (str | None): 发送者角色.

    Returns:
        StandardEvent: 测试使用的群消息事件.
    """

    return StandardEvent(
        event_id="evt-1",
        event_type="message",
        platform="qq",
        timestamp=123,
        source=EventSource(platform="qq", message_type="group", user_id="10001", group_id="123"),
        segments=[MsgSegment(type="text", data={"text": text})],
        raw_message_id="msg-1",
        sender_nickname="acacia",
        sender_role=sender_role,
        mentions_self=mentions_self,
        targets_self=mentions_self,
    )



def _agent_loader(decision) -> ResolvedAgent:
    """根据 route decision 构造最小 agent 快照.

    Args:
        decision: 当前事件对应的路由结果.

    Returns:
        ResolvedAgent: 测试使用的 agent 快照.
    """

    return ResolvedAgent(
        agent_id=decision.agent_id,
        prompt_ref=f"prompt/{decision.agent_id}",
    )



def _build_app(
    tmp_path: Path,
) -> tuple[RuntimeApp, InMemoryRunManager, FakeGateway, CapturingAgentRuntime]:
    """构造带 SessionRuntime 的 RuntimeApp.

    Args:
        tmp_path (Path): pytest 提供的临时目录.

    Returns:
        tuple[RuntimeApp, InMemoryRunManager, FakeGateway, CapturingAgentRuntime]:
            app、run_manager、fake gateway 和捕获上下文的 agent runtime.
    """

    _write_session(tmp_path)
    gateway = FakeGateway()
    run_manager = InMemoryRunManager()
    thread_manager = InMemoryThreadManager()
    session_runtime = SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions"))
    agent_runtime = CapturingAgentRuntime()
    app = RuntimeApp(
        gateway=gateway,
        router=RuntimeRouter(default_agent_id="unused", session_runtime=session_runtime),
        thread_manager=thread_manager,
        run_manager=run_manager,
        channel_event_store=InMemoryChannelEventStore(),
        pipeline=ThreadPipeline(
            agent_runtime=agent_runtime,
            outbox=Outbox(gateway=gateway, store=FakeMessageStore()),
            run_manager=run_manager,
            thread_manager=thread_manager,
        ),
        agent_loader=_agent_loader,
    )
    return app, run_manager, gateway, agent_runtime


# endregion


async def test_runtime_app_builds_run_context_with_agent_snapshot(tmp_path: Path) -> None:
    app, run_manager, gateway, agent_runtime = _build_app(tmp_path)

    await app.handle_event(_group_event(text="hello @bot", mentions_self=True, sender_role="admin"))

    runs = await run_manager.list_runs()
    run = runs[0]
    assert run.agent_id == "aca.qq.group.default"
    assert run.metadata["surface_id"] == "message.mention"
    assert run.metadata["admission_mode"] == "respond"
    assert run.metadata["computer_backend"] == "host"
    assert {
        key: value
        for key, value in run.metadata.items()
        if key.startswith("event_")
    } == {
        "event_persist": True,
        "event_tags": [],
    }
    assert agent_runtime.last_ctx is not None
    assert agent_runtime.last_ctx.agent.agent_id == "aca.qq.group.default"
    assert agent_runtime.last_ctx.agent.prompt_ref == "prompt/aca.qq.group.default"
    assert agent_runtime.last_ctx.computer_policy_decision is not None
    assert agent_runtime.last_ctx.computer_policy_decision.backend == "host"
    assert gateway.sent[0].payload["text"] == "hello back"


async def test_runtime_app_respects_record_only_surface_mode(tmp_path: Path) -> None:
    app, run_manager, gateway, _agent_runtime = _build_app(tmp_path)

    await app.handle_event(_group_event(text="just chatting", mentions_self=False, sender_role="member"))

    runs = await run_manager.list_runs()
    run = runs[0]
    assert run.metadata["surface_id"] == "message.plain"
    assert run.metadata["admission_mode"] == "record_only"
    assert gateway.sent == []
