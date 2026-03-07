# Pipeline: 主线消息流 + Hook 集成
# 测试: 基本流程, 错误处理, 多轮上下文, 群聊共享, Hook 中断/修改/跳过

import pytest
from unittest.mock import AsyncMock
from acabot.pipeline import Pipeline
from acabot.session.memory import InMemorySessionManager
from acabot.hook import Hook, HookRegistry
from acabot.agent.response import AgentResponse
from acabot.types import (
    StandardEvent, EventSource, MsgSegment, Action, ActionType,
    HookPoint, HookResult, HookContext,
)


def make_event(text="hello", msg_type="private", user_id="123", group_id=None):
    """构造测试用 StandardEvent."""
    source = EventSource(
        platform="qq", message_type=msg_type,
        user_id=user_id, group_id=group_id,
    )
    return StandardEvent(
        event_id="evt_1", event_type="message", platform="qq", timestamp=0,
        source=source, segments=[MsgSegment(type="text", data={"text": text})],
        raw_message_id="msg_1", sender_nickname="T", sender_role=None,
    )


# region 基本流程
class TestPipelineBasic:
    """Pipeline 基本消息流: 正常回复, 错误处理, 多轮上下文, 群聊共享."""

    @pytest.fixture
    def pipeline(self):
        gw = AsyncMock()
        agent = AsyncMock()
        agent.run = AsyncMock(return_value=AgentResponse(text="Reply!"))
        return Pipeline(
            gateway=gw, agent=agent,
            session_mgr=InMemorySessionManager(),
            system_prompt="You are a bot.",
        )

    # 正常流程: 收到消息 → agent 被调用 → gateway.send 发出回复
    async def test_basic_flow(self, pipeline):
        await pipeline.process(make_event("hi"))
        pipeline.agent.run.assert_called_once()
        pipeline.gateway.send.assert_called_once()
        sent = pipeline.gateway.send.call_args[0][0]
        assert sent.payload["text"] == "Reply!"

    # agent 返回 error + 默认 error_reply → 原始错误不暴露
    async def test_error_sends_friendly_message(self, pipeline):
        pipeline.agent.run = AsyncMock(
            return_value=AgentResponse(error="fail"),
        )
        await pipeline.process(make_event("hi"))
        sent = pipeline.gateway.send.call_args[0][0]
        assert "fail" not in sent.payload["text"]
        assert sent.payload["text"]  # 非空

    # error_reply=None → 不回复用户, 只记日志
    async def test_error_no_reply_when_disabled(self):
        gw = AsyncMock()
        agent = AsyncMock()
        agent.run = AsyncMock(return_value=AgentResponse(error="fail"))
        p = Pipeline(
            gateway=gw, agent=agent,
            session_mgr=InMemorySessionManager(),
            system_prompt="Bot.", error_reply=None,
        )
        await p.process(make_event("hi"))
        gw.send.assert_not_called()

    # 多轮对话: 第二次调用时 messages 包含前一轮的 user+assistant
    async def test_multi_turn(self, pipeline):
        await pipeline.process(make_event("first"))
        # 第一轮: messages 里只有 1 条 user
        assert len(pipeline.agent.run.call_args.kwargs["messages"]) == 1

        pipeline.agent.run = AsyncMock(return_value=AgentResponse(text="R2"))
        await pipeline.process(make_event("second"))
        # 第二轮: 前一轮 user + assistant + 本轮 user = 3 条
        assert len(pipeline.agent.run.call_args.kwargs["messages"]) == 3

    # 群聊共享: 同一 group 不同 user 共享 session
    async def test_group_shared_context(self, pipeline):
        await pipeline.process(make_event("msg A", "group", "A", "grp1"))
        pipeline.agent.run = AsyncMock(return_value=AgentResponse(text="R"))
        await pipeline.process(make_event("msg B", "group", "B", "grp1"))
        # 用户 B 看到的 messages 应包含用户 A 的消息
        assert len(pipeline.agent.run.call_args.kwargs["messages"]) == 3


# region Hook 集成
class TestPipelineWithHooks:
    """Pipeline + Hook 集成: abort 中断, skip_llm 早返回, prompt/model 覆盖, actions 修改."""

    @pytest.fixture
    def pipeline(self):
        gw = AsyncMock()
        agent = AsyncMock()
        agent.run = AsyncMock(return_value=AgentResponse(text="Reply!"))
        hooks = HookRegistry()
        return Pipeline(
            gateway=gw, agent=agent,
            session_mgr=InMemorySessionManager(),
            system_prompt="Base.", hooks=hooks,
        )

    # on_receive abort → agent 不被调用, gateway 不发送
    async def test_on_receive_abort(self, pipeline):
        class Blocker(Hook):
            name = "blocker"
            priority = 10
            enabled = True
            async def handle(self, ctx):
                return HookResult(action="abort")

        pipeline.hooks.register(HookPoint.ON_RECEIVE, Blocker())
        await pipeline.process(make_event("hi"))
        pipeline.agent.run.assert_not_called()
        pipeline.gateway.send.assert_not_called()

    # on_receive skip_llm → agent 不调用, 但 early_response 通过 gateway 发出
    async def test_on_receive_skip_llm(self, pipeline):
        class Gate(Hook):
            name = "gate"
            priority = 10
            enabled = True
            async def handle(self, ctx):
                target = ctx.event.source
                return HookResult(action="skip_llm", early_response=[
                    Action(action_type=ActionType.SEND_TEXT, target=target,
                           payload={"text": "blocked"}),
                ])

        pipeline.hooks.register(HookPoint.ON_RECEIVE, Gate())
        await pipeline.process(make_event("spam"))
        pipeline.agent.run.assert_not_called()
        sent = pipeline.gateway.send.call_args[0][0]
        assert sent.payload["text"] == "blocked"

    # pre_llm hook 修改 system_prompt → agent 收到修改后的 prompt
    async def test_pre_llm_modifies_prompt(self, pipeline):
        class PromptMod(Hook):
            name = "mod"
            priority = 10
            enabled = True
            async def handle(self, ctx):
                ctx.system_prompt = "MODIFIED"
                return HookResult()

        pipeline.hooks.register(HookPoint.PRE_LLM, PromptMod())
        await pipeline.process(make_event("hi"))
        assert pipeline.agent.run.call_args.kwargs["system_prompt"] == "MODIFIED"

    # pre_llm hook 覆盖 model → agent 收到新模型名
    async def test_pre_llm_model_override(self, pipeline):
        class ModelSwitch(Hook):
            name = "switch"
            priority = 10
            enabled = True
            async def handle(self, ctx):
                ctx.model = "claude-sonnet-4-20250514"
                return HookResult()

        pipeline.hooks.register(HookPoint.PRE_LLM, ModelSwitch())
        await pipeline.process(make_event("hi"))
        assert pipeline.agent.run.call_args.kwargs["model"] == "claude-sonnet-4-20250514"

    # post_llm hook 修改 actions → gateway 发送修改后的内容
    async def test_post_llm_modifies_actions(self, pipeline):
        class Upper(Hook):
            name = "upper"
            priority = 10
            enabled = True
            async def handle(self, ctx):
                for a in ctx.actions:
                    if "text" in a.payload:
                        a.payload["text"] = a.payload["text"].upper()
                return HookResult()

        pipeline.hooks.register(HookPoint.POST_LLM, Upper())
        await pipeline.process(make_event("hi"))
        sent = pipeline.gateway.send.call_args[0][0]
        assert sent.payload["text"] == "REPLY!"

    # before_send abort → gateway.send 不被调用
    async def test_before_send_abort(self, pipeline):
        class SendBlocker(Hook):
            name = "send_blocker"
            priority = 10
            enabled = True
            async def handle(self, ctx):
                return HookResult(action="abort")

        pipeline.hooks.register(HookPoint.BEFORE_SEND, SendBlocker())
        await pipeline.process(make_event("hi"))
        # agent 被调用了, 但发送被拦截
        pipeline.agent.run.assert_called_once()
        pipeline.gateway.send.assert_not_called()

    # on_error hook 在异常时被触发
    async def test_on_error_hook_triggered(self, pipeline):
        pipeline.agent.run = AsyncMock(side_effect=RuntimeError("boom"))
        called = {"flag": False}

        class ErrorSpy(Hook):
            name = "error_spy"
            priority = 10
            enabled = True
            async def handle(self, ctx):
                called["flag"] = True
                assert "boom" in ctx.metadata.get("error", "")
                return HookResult()

        pipeline.hooks.register(HookPoint.ON_ERROR, ErrorSpy())
        await pipeline.process(make_event("hi"))  # 不应抛出异常
        assert called["flag"]
