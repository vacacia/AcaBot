"""runtime.bootstrap.builders 构造基础设施和装配辅助组件."""

from __future__ import annotations

from pathlib import Path

from acabot.agent import BaseAgent
from acabot.config import Config

from ..computer import ComputerPolicy, ComputerRuntime, ComputerRuntimeConfig, parse_computer_policy
from ..contracts import AgentProfile
from ..gateway_protocol import GatewayProtocol
from ..memory.context_compactor import (
    ContextCompactionConfig,
    ContextCompactor,
    ModelContextSummarizer,
)
from ..memory.memory_broker import MemoryBroker
from ..memory.retrieval_planner import PromptAssemblyConfig, RetrievalPlanner
from ..model.model_registry import FileSystemModelRegistryManager
from ..plugin_manager import RuntimePlugin
from ..plugins import BackendBridgeToolPlugin
from ..references import (
    LocalReferenceBackend,
    NullReferenceBackend,
    OpenVikingReferenceBackend,
    ReferenceBackend,
)
from ..skills import FileSystemSkillPackageLoader, SkillCatalog
from ..storage.event_store import InMemoryChannelEventStore
from ..storage.memory_item_store import InMemoryMemoryStore
from ..storage.memory_store import InMemoryMessageStore
from ..storage.runs import InMemoryRunManager, RunManager, StoreBackedRunManager
from ..storage.sqlite_stores import (
    SQLiteChannelEventStore,
    SQLiteMemoryStore,
    SQLiteMessageStore,
    SQLiteRunStore,
    SQLiteThreadStore,
)
from ..storage.stores import ChannelEventStore, MemoryStore, MessageStore
from ..storage.threads import InMemoryThreadManager, StoreBackedThreadManager, ThreadManager
from ..memory.structured_memory import StoreBackedMemoryRetriever, StructuredMemoryExtractor
from ..subagents import SubagentExecutorRegistry
from ..subagents.execution import LocalSubagentExecutionService
from .config import get_persistence_sqlite_path, optional_str, resolve_filesystem_path, resolve_runtime_path


def build_builtin_runtime_plugins(profiles: dict[str, AgentProfile]) -> list[RuntimePlugin]:
    """组装当前仍然走 plugin 生命周期的内置插件.

    Args:
        profiles: 当前 profile 映射. 这里暂时不需要使用它, 但保留签名不改调用方.

    Returns:
        list[RuntimePlugin]: 仍然通过 plugin manager 装配的内置插件列表.
    """

    _ = profiles
    return [BackendBridgeToolPlugin()]


def register_local_subagent_executors(
    *,
    registry: SubagentExecutorRegistry,
    profiles: dict[str, AgentProfile],
    service: LocalSubagentExecutionService,
) -> None:
    """把本地 profile 注册为可用的 subagent executor."""

    for profile in profiles.values():
        metadata = dict(profile.config.get("metadata", {}) or {})
        managed_by = str(metadata.get("managed_by", "") or "").strip()
        if managed_by in {"webui_session", "webui_v2_session"} or str(metadata.get("session_key", "") or "").strip():
            continue
        registry.register(
            profile.agent_id,
            service.execute,
            source="runtime:local_profile",
            metadata={
                "kind": "local_profile",
                "profile_name": profile.name,
            },
        )


def build_model_registry_manager(config: Config) -> FileSystemModelRegistryManager:
    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    manager = FileSystemModelRegistryManager(
        providers_dir=resolve_filesystem_path(
            config,
            fs_conf,
            key="model_providers_dir",
            default="models/providers",
        ),
        presets_dir=resolve_filesystem_path(
            config,
            fs_conf,
            key="model_presets_dir",
            default="models/presets",
        ),
        bindings_dir=resolve_filesystem_path(
            config,
            fs_conf,
            key="model_bindings_dir",
            default="models/bindings",
        ),
        legacy_global_default_model=str(config.get("agent", {}).get("default_model", "") or ""),
        legacy_summary_model=str(config.get("runtime", {}).get("context_compaction", {}).get("summary_model", "") or ""),
    )
    manager.reload_now()
    return manager


def build_default_computer_policy(config: Config) -> ComputerPolicy:
    runtime_conf = config.get("runtime", {})
    computer_conf = dict(runtime_conf.get("computer", {}))
    defaults = ComputerPolicy(
        backend=str(computer_conf.get("backend", "host") or "host"),
        allow_exec=bool(computer_conf.get("allow_exec", True)),
        allow_sessions=bool(computer_conf.get("allow_sessions", True)),
        auto_stage_attachments=bool(computer_conf.get("auto_stage_attachments", True)),
        network_mode=str(computer_conf.get("network_mode", "enabled") or "enabled"),
    )
    return parse_computer_policy(computer_conf, defaults=defaults)


def build_computer_runtime(
    config: Config,
    *,
    gateway: GatewayProtocol,
    run_manager: RunManager,
    skill_catalog=None,
) -> ComputerRuntime:
    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    computer_conf = dict(runtime_conf.get("computer", {}))
    root_dir = resolve_filesystem_path(
        config,
        fs_conf,
        key="computer_root_dir",
        default=str(Path.home() / ".acabot" / "workspaces"),
    )
    skill_catalog_dir = resolve_filesystem_path(
        config,
        fs_conf,
        key="skill_catalog_dir",
        default=str(root_dir / "catalog" / "skills"),
    )
    computer_config = ComputerRuntimeConfig(
        root_dir=str(root_dir),
        skill_catalog_dir=str(skill_catalog_dir),
        max_attachment_size_bytes=int(
            computer_conf.get("max_attachment_size_bytes", 64 * 1024 * 1024)
        ),
        max_total_attachment_bytes_per_run=int(
            computer_conf.get("max_total_attachment_bytes_per_run", 256 * 1024 * 1024)
        ),
        attachment_download_timeout_sec=int(
            computer_conf.get("attachment_download_timeout_sec", 30)
        ),
        attachment_download_retries=int(
            computer_conf.get("attachment_download_retries", 2)
        ),
        exec_stdout_window_bytes=int(
            computer_conf.get("exec_stdout_window_bytes", 256 * 1024)
        ),
        exec_stderr_window_bytes=int(
            computer_conf.get("exec_stderr_window_bytes", 256 * 1024)
        ),
        docker_image=str(computer_conf.get("docker_image", "python:3.12-slim") or "python:3.12-slim"),
        docker_network_mode=str(computer_conf.get("docker_network_mode", "bridge") or "bridge"),
    )
    return ComputerRuntime(
        config=computer_config,
        gateway=gateway,
        run_manager=run_manager,
        default_policy=build_default_computer_policy(config),
        skill_catalog=skill_catalog,
    )


def build_thread_manager(config: Config) -> ThreadManager:
    sqlite_path = get_persistence_sqlite_path(config)
    if sqlite_path is None:
        return InMemoryThreadManager()
    return StoreBackedThreadManager(SQLiteThreadStore(sqlite_path))


def build_run_manager(config: Config) -> RunManager:
    sqlite_path = get_persistence_sqlite_path(config)
    if sqlite_path is None:
        return InMemoryRunManager()
    return StoreBackedRunManager(SQLiteRunStore(sqlite_path))


def build_message_store(config: Config) -> MessageStore:
    sqlite_path = get_persistence_sqlite_path(config)
    if sqlite_path is None:
        return InMemoryMessageStore()
    return SQLiteMessageStore(sqlite_path)


def build_channel_event_store(config: Config) -> ChannelEventStore:
    sqlite_path = get_persistence_sqlite_path(config)
    if sqlite_path is None:
        return InMemoryChannelEventStore()
    return SQLiteChannelEventStore(sqlite_path)


def build_memory_store(config: Config) -> MemoryStore:
    sqlite_path = get_persistence_sqlite_path(config)
    if sqlite_path is None:
        return InMemoryMemoryStore()
    return SQLiteMemoryStore(sqlite_path)


def build_memory_broker(
    config: Config,
    *,
    memory_store: MemoryStore,
) -> MemoryBroker:
    _ = config
    return MemoryBroker(
        retriever=StoreBackedMemoryRetriever(memory_store),
        extractor=StructuredMemoryExtractor(memory_store),
    )


def build_reference_backend(config: Config) -> ReferenceBackend:
    runtime_conf = config.get("runtime", {})
    reference_conf = runtime_conf.get("reference", {})
    if not bool(reference_conf.get("enabled", False)):
        return NullReferenceBackend()

    provider = str(reference_conf.get("provider", "local"))
    if provider == "local":
        local_conf = dict(reference_conf.get("local", {}))
        sqlite_path = (
            local_conf.get("sqlite_path")
            or reference_conf.get("sqlite_path")
            or get_persistence_sqlite_path(config)
            or "data/reference.sqlite3"
        )
        return LocalReferenceBackend(str(resolve_runtime_path(config, sqlite_path)))

    if provider == "openviking":
        openviking_conf = dict(reference_conf.get("openviking", {}))
        return OpenVikingReferenceBackend(
            mode=str(openviking_conf.get("mode", "embedded")),
            path=optional_str(openviking_conf.get("path")),
            base_uri=str(openviking_conf.get("base_uri", "viking://resources/acabot")),
        )

    raise ValueError(f"unsupported runtime.reference provider: {provider}")


def build_retrieval_planner(config: Config) -> RetrievalPlanner:
    runtime_conf = config.get("runtime", {})
    prompt_conf = dict(runtime_conf.get("prompt_assembly", {}))
    return RetrievalPlanner(
        PromptAssemblyConfig(
            sticky_slot_position=str(prompt_conf.get("sticky_slot_position", "system_message")),
            summary_slot_position=str(prompt_conf.get("summary_slot_position", "history_prefix")),
            retrieval_slot_position=str(
                prompt_conf.get("retrieval_slot_position", "system_message")
            ),
            sticky_message_role=str(prompt_conf.get("sticky_message_role", "system")),
            summary_message_role=str(prompt_conf.get("summary_message_role", "user")),
            retrieval_message_role=str(prompt_conf.get("retrieval_message_role", "system")),
            sticky_intro=str(
                prompt_conf.get(
                    "sticky_intro",
                    "以下是稳定事实和长期规则. 默认可信, 除非当前上下文明确冲突.",
                )
            ),
            summary_prefix=str(
                prompt_conf.get(
                    "summary_prefix",
                    (
                        "The conversation history before this point was compacted into the following "
                        "summary:\n\n<summary>\n"
                    ),
                )
            ),
            summary_suffix=str(prompt_conf.get("summary_suffix", "\n</summary>")),
            retrieval_intro=str(
                prompt_conf.get(
                    "retrieval_intro",
                    "以下是按需检索到的记忆. 可能不完全准确, 需要结合当前上下文判断.",
                )
            ),
            default_scopes=[
                str(value) for value in prompt_conf.get(
                    "default_scopes",
                    ["relationship", "user", "channel", "global"],
                )
            ],
            default_memory_types=[
                str(value) for value in prompt_conf.get(
                    "default_memory_types",
                    ["sticky_note", "semantic", "relationship", "episodic"],
                )
            ],
        ),
    )


def build_skill_catalog(config: Config) -> SkillCatalog:
    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    computer_root_dir = resolve_filesystem_path(
        config,
        fs_conf,
        key="computer_root_dir",
        default=str(Path.home() / ".acabot" / "workspaces"),
    )
    skill_catalog_dir = resolve_filesystem_path(
        config,
        fs_conf,
        key="skill_catalog_dir",
        default=str(computer_root_dir / "catalog" / "skills"),
    )
    catalog = SkillCatalog(FileSystemSkillPackageLoader(skill_catalog_dir))
    catalog.reload()
    return catalog


def build_context_compactor(
    config: Config,
    *,
    agent: BaseAgent,
) -> ContextCompactor:
    runtime_conf = config.get("runtime", {})
    compaction_conf = dict(runtime_conf.get("context_compaction", {}))
    compaction_config = ContextCompactionConfig(
        enabled=bool(compaction_conf.get("enabled", True)),
        strategy=str(compaction_conf.get("strategy", "truncate")),
        max_context_ratio=float(compaction_conf.get("max_context_ratio", 0.7)),
        preserve_recent_turns=int(compaction_conf.get("preserve_recent_turns", 6)),
        system_prompt_reserve_tokens=int(
            compaction_conf.get("system_prompt_reserve_tokens", 1500)
        ),
        prompt_slot_reserve_tokens=int(
            compaction_conf.get("prompt_slot_reserve_tokens", 2500)
        ),
        tool_schema_reserve_tokens=int(
            compaction_conf.get("tool_schema_reserve_tokens", 3000)
        ),
        summary_model=str(compaction_conf.get("summary_model", "")),
        summary_max_chars=int(compaction_conf.get("summary_max_chars", 2400)),
        summary_system_prompt=str(
            compaction_conf.get(
                "summary_system_prompt",
                ContextCompactionConfig.summary_system_prompt,
            )
        ),
        update_summary_system_prompt=str(
            compaction_conf.get(
                "update_summary_system_prompt",
                ContextCompactionConfig.update_summary_system_prompt,
            )
        ),
        fallback_context_window=int(
            compaction_conf.get("fallback_context_window", 64000)
        ),
    )
    return ContextCompactor(
        compaction_config,
        summarizer=ModelContextSummarizer(agent=agent, config=compaction_config),
    )


__all__ = [
    "build_builtin_runtime_plugins",
    "build_channel_event_store",
    "build_computer_runtime",
    "build_context_compactor",
    "build_default_computer_policy",
    "build_memory_broker",
    "build_memory_store",
    "build_message_store",
    "build_model_registry_manager",
    "build_reference_backend",
    "build_retrieval_planner",
    "build_run_manager",
    "build_skill_catalog",
    "build_thread_manager",
    "register_local_subagent_executors",
]
