# HookPoint/HookResult: hook 机制的类型定义
# 测试: 
    # 9 个 hook 点的枚举值
    # HookResult 默认行为(continue + 无 early_response)

from acabot.types import HookPoint, HookResult


def test_hook_points():
    assert HookPoint.ON_RECEIVE.value == "on_receive"
    assert HookPoint.PRE_LLM.value == "pre_llm"
    assert HookPoint.ON_TOOL_CALL.value == "on_tool_call"
    assert HookPoint.BEFORE_SEND.value == "before_send"


def test_hook_result_defaults():
    r = HookResult()
    assert r.action == "continue"
    assert r.early_response is None
