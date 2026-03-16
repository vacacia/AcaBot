"""runtime.agent_runtime 定义 AgentRuntime 接口.

先不关心具体模型实现, 只约束 ThreadPipeline 依赖什么样的执行器.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .contracts import AgentRuntimeResult, RunContext


class AgentRuntime(ABC):
    """agent runtime 执行接口.

    ThreadPipeline 不直接依赖旧的 BaseAgent.
    它只要求注入一个能接收 RunContext 并产出 AgentRuntimeResult 的对象.
    """

    @abstractmethod
    async def execute(self, ctx: RunContext) -> AgentRuntimeResult:
        """执行一次 agent runtime.

        Args:
            ctx: 本次 run 的完整执行上下文.

        Returns:
            系统级执行结果, 包含状态, 动作, 错误和审批上下文.
        """

        ...
