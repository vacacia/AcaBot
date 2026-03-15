from pathlib import Path

from acabot.runtime import (
    AgentProfile,
    FileSystemSkillPackageLoader,
    SkillAssignment,
    SkillCatalog,
    SubagentDelegationBroker,
    SubagentExecutorRegistry,
)


def _fixtures_root() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures" / "skills"


def _catalog() -> SkillCatalog:
    catalog = SkillCatalog(FileSystemSkillPackageLoader(_fixtures_root()))
    catalog.reload()
    return catalog


def _profile(*, assignments: list[SkillAssignment]) -> AgentProfile:
    return AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
        skill_assignments=list(assignments),
    )


async def test_subagent_delegation_broker_rejects_missing_assignment() -> None:
    broker = SubagentDelegationBroker(
        skill_catalog=_catalog(),
        executor_registry=SubagentExecutorRegistry(),
    )

    result = await broker.delegate(
        run_id="run:1",
        thread_id="thread:1",
        actor_id="qq:user:10001",
        channel_scope="qq:user:10001",
        parent_agent_id="aca",
        profile=_profile(assignments=[]),
        skill_name="excel_processing",
        payload={"task": "整理表格"},
    )

    assert result.ok is False
    assert "not assigned" in result.error


async def test_subagent_delegation_broker_calls_registered_executor() -> None:
    executors = SubagentExecutorRegistry()

    async def worker(request):
        return {
            "skill_name": request.skill_name,
            "ok": True,
            "delegated_run_id": "subrun:1",
            "summary": f"done: {request.payload.get('task', '')}",
            "artifacts": [{"type": "table", "rows": 3}],
        }

    executors.register("excel_worker", worker, source="test")
    broker = SubagentDelegationBroker(
        skill_catalog=_catalog(),
        executor_registry=executors,
    )

    result = await broker.delegate(
        run_id="run:1",
        thread_id="thread:1",
        actor_id="qq:user:10001",
        channel_scope="qq:user:10001",
        parent_agent_id="aca",
        profile=_profile(
            assignments=[
                SkillAssignment(
                    skill_name="excel_processing",
                    delegation_mode="must_delegate",
                    delegate_agent_id="excel_worker",
                )
            ]
        ),
        skill_name="excel_processing",
        payload={"task": "整理表格"},
    )

    assert result.ok is True
    assert result.delegated_run_id == "subrun:1"
    assert result.summary == "done: 整理表格"
    assert result.metadata["executor_agent_id"] == "excel_worker"
    assert result.metadata["executor_source"] == "test"
