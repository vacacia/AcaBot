"""runtime.bootstrap.builders 构造基础设施和装配辅助组件."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from acabot.agent import BaseAgent
from acabot.config import Config

from ..context_assembly import PayloadJsonWriter
from ..computer import ComputerPolicy, ComputerRuntime, ComputerRuntimeConfig, parse_computer_policy
from ..gateway_protocol import GatewayProtocol
from ..memory.context_compactor import (
    ContextCompactionConfig,
    ContextCompactor,
    ModelContextSummarizer,
)
from ..memory.conversation_facts import StoreBackedConversationFactReader
from ..memory.file_backed import SelfFileRetriever, StickyNoteFileStore, StickyNoteRetriever
from ..memory.long_term_ingestor import LongTermMemoryIngestor, LongTermMemoryWritePort
from ..memory.long_term_memory import (
    LtmMemorySource,
    LtmWritePort,
    LtmEmbeddingClient,
    LtmExtractorClient,
    LtmQueryPlannerClient,
)
from ..memory.memory_broker import MemoryBroker, MemorySource, MemorySourceRegistry
from ..memory.retrieval_planner import RetrievalPlanner
from ..memory.sticky_note_renderer import StickyNoteRenderer
from ..model.model_embedding_runtime import ModelEmbeddingRuntime
from ..model.model_registry import FileSystemModelRegistryManager
from ..model.model_targets import MutableModelTargetCatalog
from ..plugin_manager import RuntimePlugin
from ..plugins import BackendBridgeToolPlugin
from ..skills import FileSystemSkillPackageLoader, SkillCatalog
from ..storage.event_store import InMemoryChannelEventStore
from ..storage.memory_store import InMemoryMessageStore
from ..storage.runs import InMemoryRunManager, RunManager, StoreBackedRunManager
from ..storage.sqlite_stores import (
    SQLiteChannelEventStore,
    SQLiteMessageStore,
    SQLiteRunStore,
    SQLiteThreadStore,
)
from ..storage.stores import ChannelEventStore, MessageStore
from ..storage.threads import InMemoryThreadManager, StoreBackedThreadManager, ThreadManager
from ..subagents import (
    FileSystemSubagentPackageLoader,
    SubagentCatalog,
)
from ..soul import SoulSource
from .config import (
    get_persistence_sqlite_path,
    optional_str,
    resolve_filesystem_path,
    resolve_runtime_path,
    resolve_skill_catalog_dirs,
    resolve_subagent_catalog_dirs,
)

if TYPE_CHECKING:
    from ..memory.long_term_memory.storage import LanceDbLongTermMemoryStore


def build_builtin_runtime_plugins(_agents: object | None = None) -> list[RuntimePlugin]:
    """组装当前仍然走 plugin 生命周期的内置插件.

    Returns:
        list[RuntimePlugin]: 仍然通过 plugin manager 装配的内置插件列表.
    """
    return [BackendBridgeToolPlugin()]

def build_model_registry_manager(
    config: Config,
    *,
    target_catalog: MutableModelTargetCatalog | None = None,
) -> FileSystemModelRegistryManager:
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
        target_catalog=target_catalog,
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
    computer_conf = dict(runtime_conf.get("computer", {}))
    root_dir = resolve_runtime_path(
        config,
        computer_conf.get("root_dir", "workspaces"),
    )
    computer_config = ComputerRuntimeConfig(
        root_dir=str(root_dir),
        host_skills_catalog_root_path=str((root_dir / "catalog" / "skills").resolve()),
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


# region 长期记忆 builders
def build_long_term_memory_store(config: Config) -> LanceDbLongTermMemoryStore:
    """按当前配置构造长期记忆的 LanceDB 存储.

    Args:
        config: 当前 runtime 配置.

    Returns:
        LanceDbLongTermMemoryStore: 已准备好的 LanceDB 存储对象.
    """

    long_term_memory_conf = _long_term_memory_config(config)
    storage_dir = resolve_runtime_path(
        config,
        long_term_memory_conf.get("storage_dir", "long_term_memory/lancedb"),
    )
    try:
        from ..memory.long_term_memory.storage import LanceDbLongTermMemoryStore
    except ModuleNotFoundError as exc:
        missing_module = str(getattr(exc, "name", "") or "lancedb")
        raise RuntimeError(
            "runtime.long_term_memory.enabled=true requires LanceDB runtime dependencies; "
            f"missing module: {missing_module}"
        ) from exc
    return LanceDbLongTermMemoryStore(storage_dir)


def build_long_term_memory_source(
    config: Config,
    *,
    agent: BaseAgent,
    store: LanceDbLongTermMemoryStore,
    model_registry_manager: FileSystemModelRegistryManager,
) -> LtmMemorySource:
    """构造长期记忆检索侧 source.

    Args:
        config: 当前 runtime 配置.
        store: 长期记忆存储层.
        model_registry_manager: 模型注册表管理器.

    Returns:
        LtmMemorySource: 已接上 query planner 和 embedding 的检索入口.
    """

    long_term_memory_conf = _long_term_memory_config(config)
    return LtmMemorySource(
        store=store,
        query_planner=LtmQueryPlannerClient(
            agent=agent,
            model_registry_manager=model_registry_manager,
        ),
        embedding_client=LtmEmbeddingClient(
            embedding_runtime=ModelEmbeddingRuntime(),
            model_registry_manager=model_registry_manager,
        ),
        max_entries=int(long_term_memory_conf.get("max_entries", 8)),
    )


def build_long_term_memory_write_port(
    config: Config,
    *,
    agent: BaseAgent,
    store: LanceDbLongTermMemoryStore,
    model_registry_manager: FileSystemModelRegistryManager,
) -> LongTermMemoryWritePort:
    """构造长期记忆写侧端口.

    Args:
        config: 当前 runtime 配置.
        agent: 当前模型 agent.
        store: 长期记忆存储层.
        model_registry_manager: 模型注册表管理器.

    Returns:
        LongTermMemoryWritePort: 已接上 extractor 和 embedding 的写侧端口.
    """

    long_term_memory_conf = _long_term_memory_config(config)
    return LtmWritePort(
        store=store,
        extractor=LtmExtractorClient(
            agent=agent,
            model_registry_manager=model_registry_manager,
            extractor_version=str(
                long_term_memory_conf.get("extractor_version", "ltm-extractor-v1")
            ),
        ),
        embedding_client=LtmEmbeddingClient(
            embedding_runtime=ModelEmbeddingRuntime(),
            model_registry_manager=model_registry_manager,
        ),
        window_size=int(long_term_memory_conf.get("window_size", 50)),
        overlap_size=int(long_term_memory_conf.get("overlap_size", 10)),
    )


def build_long_term_memory_ingestor(
    *,
    thread_manager: ThreadManager,
    fact_reader: StoreBackedConversationFactReader,
    write_port: LongTermMemoryWritePort,
) -> LongTermMemoryIngestor:
    """构造长期记忆写入编排器.

    Args:
        thread_manager: thread 管理器.
        fact_reader: 统一事实读取器.
        write_port: 长期记忆写侧端口.

    Returns:
        LongTermMemoryIngestor: 已准备好的写入编排器.
    """

    return LongTermMemoryIngestor(
        thread_manager=thread_manager,
        fact_reader=fact_reader,
        write_port=write_port,
    )


def _long_term_memory_config(config: Config) -> dict[str, Any]:
    """读取长期记忆配置块.

    Args:
        config: 当前 runtime 配置.

    Returns:
        dict[str, Any]: 规范化后的长期记忆配置字典.
    """

    runtime_conf = config.get("runtime", {})
    return dict(runtime_conf.get("long_term_memory", {}))


# endregion
def build_memory_broker(
    config: Config,
    *,
    soul_source: SoulSource,
    sticky_notes_source: StickyNoteFileStore,
    long_term_memory_source: MemorySource | None = None,
) -> MemoryBroker:
    _ = config
    registry = MemorySourceRegistry()
    registry.register("self", SelfFileRetriever(soul_source))
    registry.register(
        "sticky_notes",
        StickyNoteRetriever(
            store=sticky_notes_source,
            renderer=StickyNoteRenderer(),
        ),
    )
    if long_term_memory_source is not None:
        registry.register("long_term_memory", long_term_memory_source)
    return MemoryBroker(registry=registry)


def build_retrieval_planner(config: Config) -> RetrievalPlanner:
    _ = config
    return RetrievalPlanner()


def build_payload_json_writer(config: Config) -> PayloadJsonWriter:
    """按当前 runtime 配置构造 payload json writer."""

    runtime_conf = config.get("runtime", {})
    root_dir = resolve_runtime_path(
        config,
        runtime_conf.get("payload_json_dir", "debug/model_payloads"),
    )
    return PayloadJsonWriter(root_dir=root_dir)


def build_skill_catalog(config: Config) -> SkillCatalog:
    """按当前配置构造统一 skill catalog.

    Args:
        config: 当前 runtime 配置.

    Returns:
        SkillCatalog: 已经完成一次 reload 的 skill catalog.
    """

    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    skill_catalog_dirs = resolve_skill_catalog_dirs(
        config,
        fs_conf,
        defaults=["./extensions/skills"],
    )
    catalog = SkillCatalog(FileSystemSkillPackageLoader(skill_catalog_dirs))
    catalog.reload()
    return catalog


def build_subagent_catalog(config: Config) -> SubagentCatalog:
    """按当前配置构造统一 subagent catalog.

    Args:
        config: 当前 runtime 配置.

    Returns:
        SubagentCatalog: 已经完成一次 reload 的 subagent catalog.
    """

    runtime_conf = config.get("runtime", {})
    fs_conf = dict(runtime_conf.get("filesystem", {}))
    subagent_catalog_dirs = resolve_subagent_catalog_dirs(
        config,
        fs_conf,
        defaults=["./extensions/subagents"],
    )
    catalog = SubagentCatalog(FileSystemSubagentPackageLoader(subagent_catalog_dirs))
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
    "build_long_term_memory_ingestor",
    "build_long_term_memory_source",
    "build_long_term_memory_store",
    "build_long_term_memory_write_port",
    "build_memory_broker",
    "build_message_store",
    "build_model_registry_manager",
    "build_payload_json_writer",
    "build_retrieval_planner",
    "build_run_manager",
    "build_skill_catalog",
    "build_subagent_catalog",
    "build_thread_manager",
]
