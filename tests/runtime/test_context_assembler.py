"""ContextAssembler 测试."""

from acabot.runtime import (
    AgentProfile,
    MemoryBlock,
    MemoryAssemblySpec,
    MessageProjection,
    RetrievalPlan,
    RouteDecision,
    RunContext,
    RunRecord,
    ThreadState,
    ToolRuntime,
)
from acabot.runtime.context_assembly import ContextAssembler
from acabot.runtime.context_assembly.contracts import AssembledContext, ContextContribution
from acabot.types import EventSource, MsgSegment, StandardEvent


def _assembler_ctx(
    *,
    retrieval_plan: RetrievalPlan | None = None,
    message_projection: MessageProjection | None = None,
    memory_blocks: list[MemoryBlock] | None = None,
) -> RunContext:
    """构造 ContextAssembler 测试使用的最小上下文.

    Args:
        retrieval_plan: 可选的 retrieval 结果.
        message_projection: 可选的消息投影结果.
        memory_blocks: 可选的记忆块列表.

    Returns:
        一份最小 RunContext.
    """

    event = StandardEvent(
        event_id="evt-1",
        event_type="message",
        platform="qq",
        timestamp=123,
        source=EventSource(
            platform="qq",
            message_type="private",
            user_id="10001",
            group_id=None,
        ),
        segments=[MsgSegment(type="text", data={"text": "hello"})],
        raw_message_id="msg-1",
        sender_nickname="acacia",
        sender_role=None,
    )
    return RunContext(
        run=RunRecord(
            run_id="run:1",
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            trigger_event_id=event.event_id,
            status="running",
            started_at=event.timestamp,
        ),
        event=event,
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
        thread=ThreadState(
            thread_id="qq:user:10001",
            channel_scope="qq:user:10001",
        ),
        profile=AgentProfile(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
        ),
        retrieval_plan=retrieval_plan,
        message_projection=message_projection,
        memory_blocks=list(memory_blocks or []),
    )


def test_context_assembly_contracts_expose_minimal_shape() -> None:
    """最小契约对象应该能直接表达上下文结果."""

    contribution = ContextContribution(
        source_kind="sticky_note",
        target_slot="message_prefix",
        priority=800,
        role="system",
        content="用户喜欢短回答",
    )
    assembled = AssembledContext(system_prompt="You are Aca.", messages=[])

    assert contribution.target_slot == "message_prefix"
    assert assembled.system_prompt == "You are Aca."


def test_context_assembler_orders_system_prompt_and_message_slots() -> None:
    """assembler 应该把 message_prefix、history 和当前用户消息排好顺序."""

    assembler = ContextAssembler()
    ctx = _assembler_ctx(
        memory_blocks=[
            MemoryBlock(
                content="retrieved",
                source="long_term_memory",
                scope="relationship",
                assembly=MemoryAssemblySpec(
                    target_slot="message_prefix",
                    priority=700,
                ),
            ),
            MemoryBlock(
                content="self",
                source="self",
                scope="global",
                assembly=MemoryAssemblySpec(
                    target_slot="message_prefix",
                    priority=900,
                ),
            ),
        ],
        retrieval_plan=RetrievalPlan(
            retained_history=[{"role": "user", "content": "older"}],
        ),
        message_projection=MessageProjection(history_text="older", model_content="hello"),
    )

    assembled = assembler.assemble(ctx, base_prompt="base", tool_runtime=ToolRuntime())

    assert assembled.system_prompt == "base"
    assert [item["content"] for item in assembled.messages] == ["self", "retrieved", "hello"]


def test_context_assembler_keeps_model_content_shape() -> None:
    """当前用户消息是多模态结构时, assembler 不应该把它改成字符串."""

    assembler = ContextAssembler()
    multimodal = [{"type": "text", "text": "请看图"}]
    ctx = _assembler_ctx(
        retrieval_plan=RetrievalPlan(retained_history=[]),
        message_projection=MessageProjection(history_text="请看图", model_content=multimodal),
    )

    assembled = assembler.assemble(ctx, base_prompt="base", tool_runtime=ToolRuntime())

    assert assembled.messages[-1]["content"] == multimodal


def test_context_assembler_includes_skill_and_subagent_summaries_in_system_prompt() -> None:
    """skill 和 subagent 摘要应该进入 system prompt."""

    assembler = ContextAssembler()
    tool_runtime = ToolRuntime(
        metadata={
            "visible_skill_summaries": [
                {"skill_name": "memory_append", "description": "记录新的 self 事项"}
            ],
            "visible_subagent_summaries": [
                {"agent_id": "worker", "profile_name": "实现子任务的工作代理"}
            ],
        }
    )
    ctx = _assembler_ctx(
        retrieval_plan=RetrievalPlan(retained_history=[]),
        message_projection=MessageProjection(history_text="hello", model_content="hello"),
    )

    assembled = assembler.assemble(ctx, base_prompt="base", tool_runtime=tool_runtime)

    assert "memory_append" in assembled.system_prompt
    assert "worker" in assembled.system_prompt


def test_context_assembler_uses_memory_block_declared_target_slot() -> None:
    """memory block 应该按 source 自己声明的 target_slot 落位, 而不是 assembler 猜."""

    assembler = ContextAssembler()
    ctx = _assembler_ctx(
        memory_blocks=[
            MemoryBlock(
                content="外部 RAG 要求进入 system prompt",
                source="external_rag:project_docs",
                scope="global",
                assembly=MemoryAssemblySpec(target_slot="system_prompt", priority=880),
            ),
            MemoryBlock(
                content="sticky note",
                source="sticky_notes",
                scope="user",
                assembly=MemoryAssemblySpec(target_slot="message_prefix", priority=500),
            ),
        ],
        retrieval_plan=RetrievalPlan(retained_history=[]),
        message_projection=MessageProjection(history_text="hello", model_content="hello"),
    )

    assembled = assembler.assemble(ctx, base_prompt="base", tool_runtime=ToolRuntime())

    assert "外部 RAG 要求进入 system prompt" in assembled.system_prompt
    assert [item["content"] for item in assembled.messages] == ["sticky note", "hello"]
