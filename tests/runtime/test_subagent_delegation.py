from acabot.runtime import AgentProfile, SubagentDelegationBroker, SubagentExecutorRegistry


def _profile() -> AgentProfile:
    return AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
    )


async def test_subagent_delegation_broker_rejects_missing_executor() -> None:
    broker = SubagentDelegationBroker(executor_registry=SubagentExecutorRegistry())

    result = await broker.delegate(
        run_id="run:1",
        thread_id="thread:1",
        actor_id="qq:user:10001",
        channel_scope="qq:user:10001",
        parent_agent_id="aca",
        profile=_profile(),
        delegate_agent_id="excel_worker",
        payload={"task": "整理表格"},
    )

    assert result.ok is False
    assert "not found" in result.error


async def test_subagent_delegation_broker_rejects_non_default_agent() -> None:
    executors = SubagentExecutorRegistry()
    executors.register("excel_worker", lambda request: {"ok": True}, source="test")
    broker = SubagentDelegationBroker(
        executor_registry=executors,
        default_agent_id="aca",
    )

    result = await broker.delegate(
        run_id="run:1",
        thread_id="thread:1",
        actor_id="qq:user:10001",
        channel_scope="qq:user:10001",
        parent_agent_id="manager",
        profile=AgentProfile(
            agent_id="manager",
            name="Manager",
            prompt_ref="prompt/default",
            default_model="test-model",
        ),
        delegate_agent_id="excel_worker",
        payload={"task": "整理表格"},
    )

    assert result.ok is False
    assert "cannot delegate" in result.error


async def test_subagent_delegation_broker_calls_registered_executor() -> None:
    executors = SubagentExecutorRegistry()

    async def worker(request):
        return {
            "ok": True,
            "delegated_run_id": "subrun:1",
            "summary": f"done: {request.payload.get('task', '')}",
            "artifacts": [{"type": "table", "rows": 3}],
        }

    executors.register("excel_worker", worker, source="test")
    broker = SubagentDelegationBroker(executor_registry=executors)

    result = await broker.delegate(
        run_id="run:1",
        thread_id="thread:1",
        actor_id="qq:user:10001",
        channel_scope="qq:user:10001",
        parent_agent_id="aca",
        profile=_profile(),
        delegate_agent_id="excel_worker",
        payload={"task": "整理表格"},
    )

    assert result.ok is True
    assert result.delegated_run_id == "subrun:1"
    assert result.summary == "done: 整理表格"
    assert result.metadata["executor_agent_id"] == "excel_worker"
    assert result.metadata["executor_source"] == "test"
