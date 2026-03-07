# Hook 框架: Hook 基类 + HookRegistry + run_hooks
# 测试: 优先级排序, disabled 过滤, abort 中断链, skip_llm + early_response, 异常隔离

import pytest
from acabot.hook import Hook, HookRegistry, run_hooks
from acabot.types import HookPoint, HookResult, HookContext, StandardEvent, EventSource, MsgSegment, Action, ActionType


def make_ctx(text="hello"):
    """构造测试用的 HookContext."""
    source = EventSource(platform="qq", message_type="private", user_id="1", group_id=None)
    event = StandardEvent(
        event_id="e", event_type="message", platform="qq", timestamp=0,
        source=source, segments=[MsgSegment(type="text", data={"text": text})],
        raw_message_id="m", sender_nickname="T", sender_role=None,
    )
    return HookContext(event=event)

# region SoyHook
class SpyHook(Hook):
    """记录是否被调用的 mock hook."""
    def __init__(self, name, priority=100, result=None):
        self.name = name
        self.priority = priority
        self.enabled = True
        self.called = False
        self._result = result or HookResult()

    async def handle(self, ctx):
        self.called = True
        return self._result

# region hook注册
class TestHookRegistry:
    def test_priority_order(self):
        # 优先级越小越先执行: 10 → 50 → 100
        reg = HookRegistry()
        h1 = SpyHook("a", priority=50)
        h2 = SpyHook("b", priority=10)
        h3 = SpyHook("c", priority=100)
        reg.register(HookPoint.ON_RECEIVE, h1)
        reg.register(HookPoint.ON_RECEIVE, h2)
        reg.register(HookPoint.ON_RECEIVE, h3)
        assert [h.name for h in reg.get(HookPoint.ON_RECEIVE)] == ["b", "a", "c"]

    def test_disabled_skipped(self):
        # enabled=False 的 hook 不会出现在 get() 结果中
        reg = HookRegistry()
        h = SpyHook("x")
        h.enabled = False
        reg.register(HookPoint.ON_RECEIVE, h)
        assert reg.get(HookPoint.ON_RECEIVE) == []

    def test_empty_point(self):
        # 没有注册任何 hook 的点返回空列表
        reg = HookRegistry()
        assert reg.get(HookPoint.PRE_LLM) == []

# region 运行hook
class TestRunHooks:
    async def test_all_continue(self):
        # 所有 hook 返回 continue → 链走完, 最终结果 continue
        reg = HookRegistry()
        h1, h2 = SpyHook("a", 10), SpyHook("b", 20)
        reg.register(HookPoint.ON_RECEIVE, h1)
        reg.register(HookPoint.ON_RECEIVE, h2)
        result = await run_hooks(reg, HookPoint.ON_RECEIVE, make_ctx())
        assert h1.called and h2.called
        assert result.action == "continue"

    async def test_abort_stops_chain(self):
        # abort → 后续 hook 不执行
        reg = HookRegistry()
        h1 = SpyHook("blocker", 10, HookResult(action="abort"))
        h2 = SpyHook("skipped", 20)
        reg.register(HookPoint.ON_RECEIVE, h1)
        reg.register(HookPoint.ON_RECEIVE, h2)
        result = await run_hooks(reg, HookPoint.ON_RECEIVE, make_ctx())
        assert h1.called and not h2.called
        assert result.action == "abort"

    async def test_skip_llm_with_early_response(self):
        # skip_llm + early_response → 跳过 LLM, 直接回复
        reg = HookRegistry()
        target = EventSource(platform="qq", message_type="private", user_id="1", group_id=None)
        early = [Action(action_type=ActionType.SEND_TEXT, target=target, payload={"text": "handled"})]
        h = SpyHook("gate", 10, HookResult(action="skip_llm", early_response=early))
        reg.register(HookPoint.ON_RECEIVE, h)
        result = await run_hooks(reg, HookPoint.ON_RECEIVE, make_ctx())
        assert result.action == "skip_llm"
        assert result.early_response[0].payload["text"] == "handled"

    async def test_hook_exception_does_not_crash(self):
        # 单个 hook 异常 → 链继续执行, 不崩溃
        reg = HookRegistry()

        class BadHook(Hook):
            name = "bad"
            priority = 10
            enabled = True
            async def handle(self, ctx):
                raise RuntimeError("boom")

        h_bad = BadHook()
        h_ok = SpyHook("ok", 20)
        reg.register(HookPoint.ON_RECEIVE, h_bad)
        reg.register(HookPoint.ON_RECEIVE, h_ok)
        result = await run_hooks(reg, HookPoint.ON_RECEIVE, make_ctx())
        assert h_ok.called
        assert result.action == "continue"
