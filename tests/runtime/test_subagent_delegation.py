from pathlib import Path

from acabot.runtime import (
    ResolvedAgent,
    FileSystemSubagentPackageLoader,
    SubagentCatalog,
    SubagentDelegationBroker,
    SubagentDelegationResult,
)


def _write_subagent(
    tmp_path: Path,
    *,
    name: str,
    description: str = "worker",
    tools: list[str] | None = None,
) -> None:
    subagent_dir = tmp_path / ".agents" / "subagents" / name
    subagent_dir.mkdir(parents=True, exist_ok=True)
    tool_lines = [f"  - {tool_name}" for tool_name in list(tools or [])]
    (subagent_dir / "SUBAGENT.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "tools:",
                *tool_lines,
                "---",
                f"You are {name}.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _catalog(tmp_path: Path) -> SubagentCatalog:
    catalog = SubagentCatalog(
        FileSystemSubagentPackageLoader(tmp_path / ".agents" / "subagents")
    )
    catalog.reload()
    return catalog


def _profile() -> ResolvedAgent:
    return ResolvedAgent(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
    )


async def test_subagent_delegation_broker_rejects_missing_catalog_subagent(
    tmp_path: Path,
) -> None:
    broker = SubagentDelegationBroker(
        catalog=_catalog(tmp_path),
        execution_service=object(),
    )

    result = await broker.delegate(
        run_id="run:1",
        thread_id="thread:1",
        actor_id="qq:user:10001",
        channel_scope="qq:user:10001",
        parent_agent_id="aca",
        agent=_profile(),
        delegate_agent_id="excel_worker",
        payload={"task": "整理表格"},
        visible_subagents=["excel_worker"],
    )

    assert result.ok is False
    assert "not found" in result.error


async def test_subagent_delegation_broker_rejects_target_not_in_session_allowlist(
    tmp_path: Path,
) -> None:
    _write_subagent(tmp_path, name="excel-worker")
    broker = SubagentDelegationBroker(
        catalog=_catalog(tmp_path),
        execution_service=object(),
    )

    result = await broker.delegate(
        run_id="run:1",
        thread_id="thread:1",
        actor_id="qq:user:10001",
        channel_scope="qq:user:10001",
        parent_agent_id="aca",
        agent=_profile(),
        delegate_agent_id="excel-worker",
        payload={"task": "整理表格"},
        visible_subagents=["search-worker"],
    )

    assert result.ok is False
    assert "not visible" in result.error


async def test_subagent_delegation_broker_calls_catalog_execution_service(
    tmp_path: Path,
) -> None:
    _write_subagent(tmp_path, name="excel-worker", tools=["read"])
    captured = {}

    class FakeExecutionService:
        async def execute(self, request):
            captured["request"] = request
            return SubagentDelegationResult(
                ok=True,
                delegated_run_id="subrun:1",
                summary=f"done: {request.payload.get('task', '')}",
                artifacts=[{"type": "table", "rows": 3}],
            )

    broker = SubagentDelegationBroker(
        catalog=_catalog(tmp_path),
        execution_service=FakeExecutionService(),
    )

    result = await broker.delegate(
        run_id="run:1",
        thread_id="thread:1",
        actor_id="qq:user:10001",
        channel_scope="qq:user:10001",
        parent_agent_id="aca",
        agent=_profile(),
        delegate_agent_id="excel-worker",
        payload={"task": "整理表格"},
        visible_subagents=["excel-worker"],
    )

    assert result.ok is True
    assert result.delegated_run_id == "subrun:1"
    assert result.summary == "done: 整理表格"
    assert result.metadata["executor_agent_id"] == "excel-worker"
    assert result.metadata["executor_source"] == "catalog:project"
    assert captured["request"].delegate_agent_id == "excel-worker"


async def test_subagent_delegation_broker_rejects_self_delegate(
    tmp_path: Path,
) -> None:
    _write_subagent(tmp_path, name="aca")
    broker = SubagentDelegationBroker(
        catalog=_catalog(tmp_path),
        execution_service=object(),
    )

    result = await broker.delegate(
        run_id="run:1",
        thread_id="thread:1",
        actor_id="qq:user:10001",
        channel_scope="qq:user:10001",
        parent_agent_id="aca",
        agent=_profile(),
        delegate_agent_id="aca",
        payload={"task": "整理表格"},
        visible_subagents=["aca"],
    )

    assert result.ok is False
    assert "itself" in result.error
