"""runtime.model.model_targets 定义统一的模型消费位点目录.

这个模块负责三件事:
- 定义 `model_target` 的正式对象形状
- 固定维护 runtime 内建 target
- 提供 agent / plugin 两类动态 target 的注册入口
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable, Literal

if TYPE_CHECKING:
    from ..contracts.routing import AgentProfile


ModelTaskKind = Literal[
    "chat",
    "embedding",
    "rerank",
    "speech_to_text",
    "text_to_speech",
    "image_generation",
]
ModelCapability = Literal[
    "tool_calling",
    "reasoning",
    "structured_output",
    "image_input",
    "image_output",
    "document_input",
    "audio_input",
    "audio_output",
    "video_input",
    "video_output",
]
ModelTargetSourceKind = Literal["system", "agent", "plugin"]

SUPPORTED_MODEL_TASK_KINDS: tuple[str, ...] = (
    "chat",
    "embedding",
    "rerank",
    "speech_to_text",
    "text_to_speech",
    "image_generation",
)
SUPPORTED_MODEL_CAPABILITIES: tuple[str, ...] = (
    "tool_calling",
    "reasoning",
    "structured_output",
    "image_input",
    "image_output",
    "document_input",
    "audio_input",
    "audio_output",
    "video_input",
    "video_output",
)


# region 正式对象
@dataclass(slots=True)
class ModelTarget:
    """ModelTarget 表示系统里的一个正式模型消费位点.

    Attributes:
        target_id (str): 正式 target 标识, 例如 `agent:aca`.
        task_kind (ModelTaskKind): 这个位点的主任务类型.
        source_kind (ModelTargetSourceKind): 这个 target 的来源分类.
        owner_id (str): 拥有这个 target 的对象 ID.
        description (str): 给控制面展示的人类可读说明.
        required (bool): 这个位点是否属于必填.
        allow_fallbacks (bool): 是否允许绑定 fallback 链.
        required_capabilities (list[ModelCapability]): 这个位点额外要求的能力集合.
        metadata (dict[str, str]): 额外元数据.
    """

    target_id: str
    task_kind: ModelTaskKind
    source_kind: ModelTargetSourceKind
    owner_id: str
    description: str = ""
    required: bool = False
    allow_fallbacks: bool = True
    required_capabilities: list[ModelCapability] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class RuntimePluginModelSlot:
    """RuntimePluginModelSlot 描述插件声明的一个模型槽位.

    Attributes:
        slot_id (str): 插件内的局部槽位 ID.
        task_kind (ModelTaskKind): 这个槽位的主任务类型.
        required (bool): 是否是插件运行的必填槽位.
        allow_fallbacks (bool): 是否允许绑定 fallback 链.
        required_capabilities (list[ModelCapability]): 这个槽位额外要求的能力集合.
        description (str): 槽位说明.
    """

    slot_id: str
    task_kind: ModelTaskKind
    required: bool = False
    allow_fallbacks: bool = True
    required_capabilities: list[ModelCapability] = field(default_factory=list)
    description: str = ""


# endregion


# region 内建目录
SYSTEM_MODEL_TARGETS: tuple[ModelTarget, ...] = (
    ModelTarget(
        target_id="system:compactor_summary",
        task_kind="chat",
        source_kind="system",
        owner_id="compactor_summary",
        description="上下文压缩总结模型",
        required=False,
        allow_fallbacks=True,
    ),
    ModelTarget(
        target_id="system:image_caption",
        task_kind="chat",
        source_kind="system",
        owner_id="image_caption",
        description="图片内容转述模型",
        required=False,
        allow_fallbacks=True,
        required_capabilities=["image_input"],
    ),
    ModelTarget(
        target_id="system:ltm_extract",
        task_kind="chat",
        source_kind="system",
        owner_id="ltm_extract",
        description="长期记忆提取模型",
        required=True,
        allow_fallbacks=True,
    ),
    ModelTarget(
        target_id="system:ltm_query_plan",
        task_kind="chat",
        source_kind="system",
        owner_id="ltm_query_plan",
        description="长期记忆检索规划模型",
        required=True,
        allow_fallbacks=True,
    ),
    ModelTarget(
        target_id="system:ltm_answer",
        task_kind="chat",
        source_kind="system",
        owner_id="ltm_answer",
        description="长期记忆答案整合模型",
        required=False,
        allow_fallbacks=True,
    ),
    ModelTarget(
        target_id="system:ltm_embed",
        task_kind="embedding",
        source_kind="system",
        owner_id="ltm_embed",
        description="长期记忆 embedding 模型",
        required=True,
        allow_fallbacks=True,
    ),
)


def build_agent_model_targets(profiles: Iterable["AgentProfile"]) -> list[ModelTarget]:
    """根据当前 profile 集合构建 `agent:<agent_id>` target 列表.

    Args:
        profiles: 当前 profile 快照集合.

    Returns:
        一组按 agent_id 排序的 target.
    """

    items = sorted(
        {str(profile.agent_id): profile for profile in profiles if str(getattr(profile, "agent_id", "") or "")}.items()
    )
    return [
        ModelTarget(
            target_id=f"agent:{agent_id}",
            task_kind="chat",
            source_kind="agent",
            owner_id=agent_id,
            description=f"{agent_id} 主回复模型",
            required=True,
            allow_fallbacks=True,
        )
        for agent_id, _profile in items
    ]


# endregion


# region catalog
class MutableModelTargetCatalog:
    """MutableModelTargetCatalog 统一管理 system / agent / plugin target.

    这个对象只维护 target 目录, 不持久化 binding.

    Attributes:
        _system_targets (dict[str, ModelTarget]): 固定 system target.
        _agent_targets (dict[str, ModelTarget]): 当前 profile 派生出的 agent target.
        _plugin_targets (dict[str, ModelTarget]): 当前已加载插件注册的 target.
    """

    def __init__(self, *, system_targets: Iterable[ModelTarget] | None = None) -> None:
        """初始化一个 target catalog.

        Args:
            system_targets: 初始的固定 system target 集合.
        """

        self._system_targets = self._index_targets(system_targets or SYSTEM_MODEL_TARGETS)
        self._agent_targets: dict[str, ModelTarget] = {}
        self._plugin_targets: dict[str, ModelTarget] = {}

    def list_targets(self) -> list[ModelTarget]:
        """返回当前可见 target 的稳定列表."""

        merged = {
            **self._system_targets,
            **self._agent_targets,
            **self._plugin_targets,
        }
        return [merged[key] for key in sorted(merged)]

    def get(self, target_id: str) -> ModelTarget | None:
        """按 target_id 获取一个 target."""

        normalized = str(target_id or "").strip()
        if not normalized:
            return None
        for bucket in (self._system_targets, self._agent_targets, self._plugin_targets):
            target = bucket.get(normalized)
            if target is not None:
                return target
        return None

    def replace_agent_targets(self, targets: Iterable[ModelTarget]) -> None:
        """整体替换当前 agent target 集合.

        Args:
            targets: 新的 agent target 集合.
        """

        indexed = self._index_targets(targets)
        for target in indexed.values():
            self._validate_target(target)
            if target.source_kind != "agent":
                raise ValueError(f"agent target source_kind must be 'agent': {target.target_id}")
            if not target.target_id.startswith("agent:"):
                raise ValueError(f"agent target_id must start with 'agent:': {target.target_id}")
        self._agent_targets = indexed

    def register_plugin_slots(
        self,
        *,
        plugin_id: str,
        slots: Iterable[RuntimePluginModelSlot],
    ) -> list[ModelTarget]:
        """注册一个插件声明的模型槽位.

        Args:
            plugin_id: 插件 ID.
            slots: 插件声明的模型槽位.

        Returns:
            新注册的 target 列表.
        """

        normalized_plugin_id = str(plugin_id or "").strip()
        if not normalized_plugin_id:
            raise ValueError("plugin_id is required")
        created: list[ModelTarget] = []
        for slot in slots:
            slot_id = str(slot.slot_id or "").strip()
            if not slot_id:
                raise ValueError(f"plugin model slot_id is required: {plugin_id}")
            self._validate_plugin_slot(slot, plugin_id=normalized_plugin_id)
            target = ModelTarget(
                target_id=f"plugin:{normalized_plugin_id}:{slot_id}",
                task_kind=slot.task_kind,
                source_kind="plugin",
                owner_id=normalized_plugin_id,
                description=str(slot.description or "").strip(),
                required=bool(slot.required),
                allow_fallbacks=bool(slot.allow_fallbacks),
                required_capabilities=list(slot.required_capabilities),
                metadata={"slot_id": slot_id},
            )
            existing = self.get(target.target_id)
            if existing is not None and existing.source_kind != "plugin":
                raise ValueError(f"plugin target conflicts with existing target: {target.target_id}")
            self._plugin_targets[target.target_id] = target
            created.append(target)
        return created

    def unregister_plugin_targets(self, plugin_id: str) -> None:
        """注销某个插件注册过的全部 target.

        Args:
            plugin_id: 插件 ID.
        """

        normalized_plugin_id = str(plugin_id or "").strip()
        prefix = f"plugin:{normalized_plugin_id}:"
        remove_ids = [target_id for target_id in self._plugin_targets if target_id.startswith(prefix)]
        for target_id in remove_ids:
            self._plugin_targets.pop(target_id, None)

    @staticmethod
    def _index_targets(targets: Iterable[ModelTarget]) -> dict[str, ModelTarget]:
        """把 target 列表收成字典并检查重复项.

        Args:
            targets: 一组 target.

        Returns:
            以 target_id 为键的字典.
        """

        items: dict[str, ModelTarget] = {}
        for target in targets:
            target_id = str(target.target_id or "").strip()
            if not target_id:
                raise ValueError("model target target_id is required")
            if target_id in items:
                raise ValueError(f"duplicate model target: {target_id}")
            MutableModelTargetCatalog._validate_target(target)
            items[target_id] = target
        return items

    @staticmethod
    def _validate_target(target: ModelTarget) -> None:
        if target.task_kind not in SUPPORTED_MODEL_TASK_KINDS:
            raise ValueError(f"unsupported model target task_kind: {target.target_id}")
        required_capabilities = list(target.required_capabilities)
        for capability in required_capabilities:
            if capability not in SUPPORTED_MODEL_CAPABILITIES:
                raise ValueError(f"unsupported model target capability: {target.target_id}:{capability}")

    @staticmethod
    def _validate_plugin_slot(slot: RuntimePluginModelSlot, *, plugin_id: str) -> None:
        if slot.task_kind not in SUPPORTED_MODEL_TASK_KINDS:
            raise ValueError(f"unsupported plugin model slot task_kind: {plugin_id}:{slot.slot_id}")
        for capability in list(slot.required_capabilities):
            if capability not in SUPPORTED_MODEL_CAPABILITIES:
                raise ValueError(f"unsupported plugin model slot capability: {plugin_id}:{slot.slot_id}:{capability}")


# endregion


__all__ = [
    "ModelCapability",
    "ModelTaskKind",
    "ModelTarget",
    "ModelTargetSourceKind",
    "MutableModelTargetCatalog",
    "RuntimePluginModelSlot",
    "SUPPORTED_MODEL_CAPABILITIES",
    "SUPPORTED_MODEL_TASK_KINDS",
    "SYSTEM_MODEL_TARGETS",
    "build_agent_model_targets",
]
