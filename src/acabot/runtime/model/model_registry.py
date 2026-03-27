"""runtime.model_registry 模型注册表与控制面数据对象.

这一层负责:
- filesystem-backed provider / preset / binding 真源
- 静态校验
- 运行时模型请求组装
- run 级持久化快照
- 控制面的 impact / delete cascade / reload
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from inspect import isawaitable
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import Any, Literal

import yaml

from .model_targets import (
    ModelCapability,
    ModelTaskKind,
    MutableModelTargetCatalog,
    SUPPORTED_MODEL_CAPABILITIES,
    SUPPORTED_MODEL_TASK_KINDS,
)

ModelProviderKind = Literal["openai_compatible", "anthropic", "google_gemini"]
ModelBindingState = Literal["resolved", "unresolved_target", "invalid_binding"]
ModelEntityType = Literal["provider", "preset", "binding"]

_SUPPORTED_PROVIDER_KINDS: set[str] = {
    "openai_compatible",
    "anthropic",
    "google_gemini",
}
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SUPPORTED_MODEL_TASK_KINDS = set(SUPPORTED_MODEL_TASK_KINDS)
_SUPPORTED_MODEL_CAPABILITIES = set(SUPPORTED_MODEL_CAPABILITIES)


def _normalize_provider_auth_fields(
    *,
    api_key_env: str,
    api_key: str = "",
) -> tuple[str, str]:
    normalized_env = str(api_key_env or "").strip()
    normalized_key = str(api_key or "").strip()
    if normalized_key:
        return normalized_env, normalized_key
    if normalized_env and not _ENV_NAME_RE.fullmatch(normalized_env):
        return "", normalized_env
    return normalized_env, normalized_key


def _normalize_task_kind(value: Any) -> str:
    return str(value or "").strip()


def _normalize_capabilities(values: Any) -> list[str]:
    items = [str(item or "").strip() for item in list(values or [])]
    normalized: list[str] = []
    for item in items:
        if item and item not in normalized:
            normalized.append(item)
    return normalized


# region provider config
@dataclass(slots=True)
class OpenAICompatibleProviderConfig:
    """OpenAI-compatible provider 的静态配置."""

    base_url: str
    api_key_env: str
    api_key: str = ""
    default_headers: dict[str, str] = field(default_factory=dict)
    default_query: dict[str, Any] = field(default_factory=dict)
    default_body: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AnthropicProviderConfig:
    """Anthropic provider 的静态配置."""

    api_key_env: str
    api_key: str = ""
    base_url: str = ""
    anthropic_version: str = ""
    default_headers: dict[str, str] = field(default_factory=dict)
    default_query: dict[str, Any] = field(default_factory=dict)
    default_body: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GoogleGeminiProviderConfig:
    """Google Gemini provider 的静态配置."""

    api_key_env: str
    api_key: str = ""
    base_url: str = ""
    api_version: str = ""
    project_id: str = ""
    location: str = ""
    use_vertex_ai: bool = False
    default_headers: dict[str, str] = field(default_factory=dict)
    default_query: dict[str, Any] = field(default_factory=dict)
    default_body: dict[str, Any] = field(default_factory=dict)


ProviderConfig = (
    OpenAICompatibleProviderConfig
    | AnthropicProviderConfig
    | GoogleGeminiProviderConfig
)


@dataclass(slots=True)
class ModelProvider:
    """一条 provider 定义."""

    provider_id: str
    kind: ModelProviderKind
    config: ProviderConfig
    name: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = {
            "provider_id": self.provider_id,
            "name": self.name or self.provider_id,
            "kind": self.kind,
            **asdict(self.config),
        }
        return data


# endregion


# region preset / binding
@dataclass(slots=True)
class ModelPreset:
    """一条具体模型预设."""

    preset_id: str
    provider_id: str
    model: str
    task_kind: ModelTaskKind
    context_window: int
    capabilities: list[ModelCapability] = field(default_factory=list)
    max_output_tokens: int | None = None
    model_params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "preset_id": self.preset_id,
            "provider_id": self.provider_id,
            "model": self.model,
            "task_kind": self.task_kind,
            "capabilities": list(self.capabilities),
            "context_window": self.context_window,
            "model_params": dict(self.model_params),
        }
        if self.max_output_tokens is not None:
            data["max_output_tokens"] = self.max_output_tokens
        return data


@dataclass(slots=True)
class ModelBinding:
    """一条执行单元到 preset 的绑定."""

    binding_id: str
    target_id: str
    preset_ids: list[str] = field(default_factory=list)
    timeout_sec: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "binding_id": self.binding_id,
            "target_id": self.target_id,
            "preset_ids": list(self.preset_ids),
        }
        if self.timeout_sec is not None:
            data["timeout_sec"] = self.timeout_sec
        return data


# endregion


# region runtime request and snapshots
@dataclass(slots=True)
class RuntimeModelRequest:
    """一次 run 真正拿去发请求的模型配置.
    
    由 ModelRegistry 将 Provider (厂商信息), Preset (模型参数), 
    和 Binding (路由目标) 三者合并拉平后产生的终态对象.

    Attributes:
        provider_kind (str): 供应商类型.
        model (str): 最终解析出的模型名称标识符.
        context_window (int): 该模型声明的最大上下文 token 窗口.
        supports_tools (bool): 该模型是否支持 tool calling.
        supports_vision (bool): 该模型是否支持多模态视觉输入.
        task_kind (str): 该请求对应的主任务类型.
        capabilities (list[str]): 该请求声明的附加能力集合.
        provider_id (str): 解析出此请求的祖先 Provider ID.
        preset_id (str): 解析出此请求的祖先 Preset ID.
        binding_id (str): 触发生成此请求的源头 Binding ID.
        api_key_env (str): 获取真实 API Key 需要读取的环境变量名.
        provider_params (dict[str, Any]): 平台级连接参数 (如 base_url, default_headers).
        model_params (dict[str, Any]): 生成级参数 (如 temperature, max_tokens).
        execution_params (dict[str, Any]): 运行时调度参数 (如 timeout_sec).
        fallback_requests (list[RuntimeModelRequest]): 如果主请求失败, 应尝试的备用请求列表.
    """

    provider_kind: str
    model: str
    context_window: int = 0
    supports_tools: bool = False
    supports_vision: bool = False
    task_kind: str = ""
    capabilities: list[str] = field(default_factory=list)
    provider_id: str = ""
    preset_id: str = ""
    binding_id: str = ""
    api_key_env: str = ""
    api_key: str = ""
    provider_params: dict[str, Any] = field(default_factory=dict)
    model_params: dict[str, Any] = field(default_factory=dict)
    execution_params: dict[str, Any] = field(default_factory=dict)
    fallback_requests: list["RuntimeModelRequest"] = field(default_factory=list)

    def resolved_non_secret_params(self) -> dict[str, Any]:
        """返回可安全持久化的非敏感参数."""

        return {
            **dict(self.provider_params),
            **dict(self.model_params),
            **dict(self.execution_params),
        }

    def to_request_options(self) -> dict[str, Any]:
        """把 RuntimeModelRequest 转成 agent 可消费的 request options."""

        options = self.resolved_non_secret_params()
        provider_kind = str(self.provider_kind or "")
        api_key = ""
        if self.api_key_env:
            api_key = str(os.getenv(self.api_key_env, "") or "")
        if not api_key and self.api_key:
            api_key = str(self.api_key or "")
        if provider_kind == "openai_compatible":
            base_url = str(options.pop("base_url", "") or "")
            default_headers = dict(options.pop("default_headers", {}) or {})
            default_query = dict(options.pop("default_query", {}) or {})
            default_body = dict(options.pop("default_body", {}) or {})
            request_options: dict[str, Any] = {**options}
            if base_url:
                request_options["api_base"] = base_url
            if api_key:
                request_options["api_key"] = api_key
            if default_headers:
                request_options["extra_headers"] = default_headers
            if default_query:
                request_options["query_params"] = default_query
            if default_body:
                request_options["extra_body"] = default_body
            request_options["provider_kind"] = provider_kind
            return request_options

        if provider_kind == "anthropic":
            base_url = str(options.pop("base_url", "") or "")
            anthropic_version = str(options.pop("anthropic_version", "") or "")
            default_headers = dict(options.pop("default_headers", {}) or {})
            default_query = dict(options.pop("default_query", {}) or {})
            default_body = dict(options.pop("default_body", {}) or {})
            request_options = {**options}
            if base_url:
                request_options["api_base"] = base_url
            if api_key:
                request_options["api_key"] = api_key
            if anthropic_version:
                default_headers.setdefault("anthropic-version", anthropic_version)
            if default_headers:
                request_options["extra_headers"] = default_headers
            if default_query:
                request_options["query_params"] = default_query
            if default_body:
                request_options["extra_body"] = default_body
            request_options["provider_kind"] = provider_kind
            return request_options

        if provider_kind == "google_gemini":
            base_url = str(options.pop("base_url", "") or "")
            api_version = str(options.pop("api_version", "") or "")
            project_id = str(options.pop("project_id", "") or "")
            location = str(options.pop("location", "") or "")
            use_vertex_ai = bool(options.pop("use_vertex_ai", False))
            default_headers = dict(options.pop("default_headers", {}) or {})
            default_query = dict(options.pop("default_query", {}) or {})
            default_body = dict(options.pop("default_body", {}) or {})
            request_options = {**options}
            if base_url:
                request_options["api_base"] = base_url
            if api_key:
                request_options["api_key"] = api_key
            if api_version:
                request_options["api_version"] = api_version
            if use_vertex_ai:
                request_options["vertex_project"] = project_id
                request_options["vertex_location"] = location
            if default_headers:
                request_options["extra_headers"] = default_headers
            if default_query:
                request_options["query_params"] = default_query
            if default_body:
                request_options["extra_body"] = default_body
            request_options["provider_kind"] = provider_kind
            return request_options

        # 兼容旧的 raw model fallback
        request_options = {**options}
        request_options["provider_kind"] = provider_kind
        return request_options


@dataclass(slots=True)
class PersistedModelSnapshot:
    """run 落库用的脱敏模型快照."""

    binding_id: str
    provider_id: str
    preset_id: str
    provider_kind: str
    api_key_env: str
    model: str
    context_window: int
    supports_tools: bool
    supports_vision: bool
    task_kind: str = ""
    capabilities: list[str] = field(default_factory=list)
    resolved_non_secret_params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "provider_id": self.provider_id,
            "preset_id": self.preset_id,
            "provider_kind": self.provider_kind,
            "api_key_env": self.api_key_env,
            "model": self.model,
            "context_window": self.context_window,
            "supports_tools": self.supports_tools,
            "supports_vision": self.supports_vision,
            "task_kind": self.task_kind,
            "capabilities": list(self.capabilities),
            "resolved_non_secret_params": dict(self.resolved_non_secret_params),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> PersistedModelSnapshot | None:
        if not raw:
            return None
        return cls(
            binding_id=str(raw.get("binding_id", "") or ""),
            provider_id=str(raw.get("provider_id", "") or ""),
            preset_id=str(raw.get("preset_id", "") or ""),
            provider_kind=str(raw.get("provider_kind", "") or ""),
            api_key_env=str(raw.get("api_key_env", "") or ""),
            model=str(raw.get("model", "") or ""),
            context_window=int(raw.get("context_window", 0) or 0),
            supports_tools=bool(raw.get("supports_tools", False)),
            supports_vision=bool(raw.get("supports_vision", False)),
            task_kind=str(raw.get("task_kind", "") or ""),
            capabilities=[str(item) for item in list(raw.get("capabilities", []) or [])],
            resolved_non_secret_params=dict(raw.get("resolved_non_secret_params", {}) or {}),
        )

    def to_runtime_request(self) -> RuntimeModelRequest:
        return RuntimeModelRequest(
            provider_kind=self.provider_kind,
            model=self.model,
            context_window=self.context_window,
            supports_tools=self.supports_tools,
            supports_vision=self.supports_vision,
            task_kind=self.task_kind,
            capabilities=list(self.capabilities),
            provider_id=self.provider_id,
            preset_id=self.preset_id,
            binding_id=self.binding_id,
            api_key_env=self.api_key_env,
            api_key="",
            execution_params=dict(self.resolved_non_secret_params),
        )


def snapshot_from_runtime_request(request: RuntimeModelRequest) -> PersistedModelSnapshot:
    return PersistedModelSnapshot(
        binding_id=request.binding_id,
        provider_id=request.provider_id,
        preset_id=request.preset_id,
        provider_kind=request.provider_kind,
        api_key_env=request.api_key_env,
        model=request.model,
        context_window=request.context_window,
        supports_tools=request.supports_tools,
        supports_vision=request.supports_vision,
        task_kind=request.task_kind,
        capabilities=list(request.capabilities),
        resolved_non_secret_params=request.resolved_non_secret_params(),
    )


# endregion


# region control-plane dto
@dataclass(slots=True)
class ModelImpactSnapshot:
    """模型对象依赖影响预览."""

    entity_type: ModelEntityType
    entity_id: str
    preset_ids: list[str] = field(default_factory=list)
    binding_ids: list[str] = field(default_factory=list)
    agent_ids: list[str] = field(default_factory=list)
    system_targets: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EffectiveModelSnapshot:
    """控制面查看某个 target 实际会落到哪个模型."""

    target_type: str
    target_id: str
    source: str
    request: RuntimeModelRequest | None = None


@dataclass(slots=True)
class ModelMutationResult:
    """一次 provider / preset / binding 变更结果."""

    ok: bool
    applied: bool
    action: str
    entity_type: ModelEntityType
    entity_id: str
    message: str = ""
    binding_state: ModelBindingState = "resolved"
    impact: ModelImpactSnapshot | None = None
    cascaded_provider_ids: list[str] = field(default_factory=list)
    cascaded_preset_ids: list[str] = field(default_factory=list)
    cascaded_binding_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ModelBindingSnapshot:
    """控制面查看 binding 当前解析状态的派生视图."""

    binding: ModelBinding
    binding_state: ModelBindingState = "resolved"
    target_present: bool = True
    message: str = ""


@dataclass(slots=True)
class ModelHealthCheckResult:
    """一次主动触发的 provider/model 健康检查结果."""

    ok: bool
    provider_id: str
    preset_id: str
    model: str
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelRegistryStatusSnapshot:
    """当前 active registry 的状态."""

    provider_count: int = 0
    preset_count: int = 0
    binding_count: int = 0
    last_error: str = ""


@dataclass(slots=True)
class ModelReloadSnapshot:
    """一次显式 reload_models 的结果."""

    ok: bool
    provider_count: int = 0
    preset_count: int = 0
    binding_count: int = 0
    error: str = ""


# endregion


# region registry
@dataclass(slots=True)
class ModelRegistry:
    """当前生效的 provider / preset / binding 注册表."""

    providers: dict[str, ModelProvider] = field(default_factory=dict)
    presets: dict[str, ModelPreset] = field(default_factory=dict)
    bindings: dict[str, ModelBinding] = field(default_factory=dict)

    def validate(self, *, target_catalog: MutableModelTargetCatalog) -> None:
        target_ids: set[str] = set()
        for provider_id, provider in self.providers.items():
            if provider_id != provider.provider_id:
                raise ValueError(f"provider_id mismatch: {provider_id}")
            self._validate_provider(provider)

        for preset_id, preset in self.presets.items():
            if preset_id != preset.preset_id:
                raise ValueError(f"preset_id mismatch: {preset_id}")
            self._validate_preset(preset)

        for binding_id, binding in self.bindings.items():
            if binding_id != binding.binding_id:
                raise ValueError(f"binding_id mismatch: {binding_id}")
            self._validate_binding(binding, target_catalog=target_catalog)
            if binding.target_id in target_ids:
                raise ValueError(f"duplicate binding target: {binding.target_id}")
            target_ids.add(binding.target_id)

    def binding_for_target(self, target_id: str) -> ModelBinding | None:
        return self._binding_for(target_id)

    def provider_impact(self, provider_id: str) -> ModelImpactSnapshot:
        preset_ids = [
            preset_id
            for preset_id, preset in self.presets.items()
            if preset.provider_id == provider_id
        ]
        impact = ModelImpactSnapshot(
            entity_type="provider",
            entity_id=provider_id,
            preset_ids=sorted(preset_ids),
        )
        for preset_id in preset_ids:
            nested = self.preset_impact(preset_id)
            impact.binding_ids.extend(nested.binding_ids)
            impact.agent_ids.extend(nested.agent_ids)
            impact.system_targets.extend(nested.system_targets)
        impact.binding_ids = sorted(set(impact.binding_ids))
        impact.agent_ids = sorted(set(impact.agent_ids))
        impact.system_targets = sorted(set(impact.system_targets))
        return impact

    def preset_impact(self, preset_id: str) -> ModelImpactSnapshot:
        impact = ModelImpactSnapshot(
            entity_type="preset",
            entity_id=preset_id,
        )
        for binding in self.bindings.values():
            if preset_id not in binding.preset_ids:
                continue
            impact.binding_ids.append(binding.binding_id)
            if binding.target_id.startswith("agent:"):
                impact.agent_ids.append(binding.target_id.removeprefix("agent:"))
            if binding.target_id.startswith("system:"):
                impact.system_targets.append(binding.target_id.removeprefix("system:"))
        impact.binding_ids.sort()
        impact.agent_ids.sort()
        impact.system_targets.sort()
        return impact

    def binding_impact(self, binding_id: str) -> ModelImpactSnapshot:
        binding = self.bindings.get(binding_id)
        impact = ModelImpactSnapshot(
            entity_type="binding",
            entity_id=binding_id,
        )
        if binding is None:
            return impact
        if binding.target_id.startswith("agent:"):
            impact.agent_ids.append(binding.target_id.removeprefix("agent:"))
        if binding.target_id.startswith("system:"):
            impact.system_targets.append(binding.target_id.removeprefix("system:"))
        return impact

    def clone(self) -> ModelRegistry:
        return deepcopy(self)

    def _binding_for(self, target_id: str) -> ModelBinding | None:
        for binding in self.bindings.values():
            if binding.target_id == target_id:
                return binding
        return None

    def _validate_provider(self, provider: ModelProvider) -> None:
        if provider.kind not in _SUPPORTED_PROVIDER_KINDS:
            raise ValueError(f"unsupported provider kind: {provider.kind}")
        provider_id = str(provider.provider_id or "").strip()
        if not provider_id:
            raise ValueError("provider_id is required")
        config = provider.config
        api_key_env, api_key = _normalize_provider_auth_fields(
            api_key_env=str(getattr(config, "api_key_env", "") or ""),
            api_key=str(getattr(config, "api_key", "") or ""),
        )
        if not api_key_env and not api_key:
            raise ValueError(f"provider api_key_env is required: {provider.provider_id}")
        if provider.kind == "openai_compatible":
            base_url = str(getattr(config, "base_url", "") or "").strip()
            if not base_url:
                raise ValueError(f"provider base_url is required: {provider.provider_id}")
        if provider.kind == "google_gemini":
            api_version = str(getattr(config, "api_version", "") or "").strip()
            if api_version and not api_version.startswith("v"):
                raise ValueError(f"google_gemini api_version must start with 'v': {provider.provider_id}")

    def _validate_preset(self, preset: ModelPreset) -> None:
        if not str(preset.preset_id or "").strip():
            raise ValueError("preset_id is required")
        if preset.provider_id not in self.providers:
            raise ValueError(f"unknown provider_id for preset {preset.preset_id}: {preset.provider_id}")
        if not str(preset.model or "").strip():
            raise ValueError(f"model is required for preset {preset.preset_id}")
        normalized_task_kind = _normalize_task_kind(preset.task_kind)
        if normalized_task_kind not in _SUPPORTED_MODEL_TASK_KINDS:
            raise ValueError(f"unsupported preset task_kind: {preset.preset_id}")
        preset.task_kind = normalized_task_kind
        preset.capabilities = _normalize_capabilities(preset.capabilities)
        for capability in preset.capabilities:
            if capability not in _SUPPORTED_MODEL_CAPABILITIES:
                raise ValueError(f"unsupported preset capability entry: {preset.preset_id}:{capability}")
        if int(preset.context_window) <= 0:
            raise ValueError(f"context_window must be positive: {preset.preset_id}")
        if preset.max_output_tokens is not None and int(preset.max_output_tokens) <= 0:
            raise ValueError(f"max_output_tokens must be positive: {preset.preset_id}")

    def _validate_binding(
        self,
        binding: ModelBinding,
        *,
        target_catalog: MutableModelTargetCatalog,
    ) -> None:
        if not str(binding.binding_id or "").strip():
            raise ValueError("binding_id is required")
        if not str(binding.target_id or "").strip():
            raise ValueError(f"target_id is required: {binding.binding_id}")
        if not binding.preset_ids:
            raise ValueError(f"binding preset_ids is required: {binding.binding_id}")
        target = target_catalog.get(binding.target_id)
        if target is None and not binding.target_id.startswith("plugin:"):
            raise ValueError(f"unknown model target: {binding.target_id}")
        required_capabilities = set(target.required_capabilities) if target is not None else set()
        for preset_id in binding.preset_ids:
            preset = self.presets.get(preset_id)
            if preset is None:
                raise ValueError(f"unknown preset_id for binding {binding.binding_id}: {preset_id}")
            if target is not None and preset.task_kind != target.task_kind:
                raise ValueError(
                    f"preset task_kind mismatch for {binding.binding_id}: "
                    f"target={target.task_kind} preset={preset.task_kind}"
                )
            missing_capabilities = sorted(required_capabilities.difference(preset.capabilities))
            if missing_capabilities:
                raise ValueError(
                    f"preset capabilities mismatch for {binding.binding_id}: "
                    f"target={binding.target_id} missing={','.join(missing_capabilities)}"
                )
        if target is not None and not target.allow_fallbacks and len(binding.preset_ids) > 1:
            raise ValueError(f"target does not allow fallbacks: {binding.target_id}")
        if binding.timeout_sec is not None and float(binding.timeout_sec) <= 0:
            raise ValueError(f"timeout_sec must be positive: {binding.binding_id}")


# endregion


# region manager
class FileSystemModelRegistryManager:
    """filesystem-backed 模型注册表管理器."""

    def __init__(
        self,
        *,
        providers_dir: str | Path,
        presets_dir: str | Path,
        bindings_dir: str | Path,
        target_catalog: MutableModelTargetCatalog | None = None,
    ) -> None:
        self.providers_dir = Path(providers_dir)
        self.presets_dir = Path(presets_dir)
        self.bindings_dir = Path(bindings_dir)
        self.target_catalog = target_catalog or MutableModelTargetCatalog()
        self.active_registry = ModelRegistry()
        self.last_error = ""
        self._reload_lock = asyncio.Lock()

    def reload_now(self) -> ModelReloadSnapshot:
        try:
            registry = self._load_registry_from_filesystem()
            registry.validate(target_catalog=self.target_catalog)
        except Exception as exc:
            self.last_error = str(exc)
            return ModelReloadSnapshot(
                ok=False,
                provider_count=len(self.active_registry.providers),
                preset_count=len(self.active_registry.presets),
                binding_count=len(self.active_registry.bindings),
                error=str(exc),
            )

        self.active_registry = registry
        self.last_error = ""
        return ModelReloadSnapshot(
            ok=True,
            provider_count=len(registry.providers),
            preset_count=len(registry.presets),
            binding_count=len(registry.bindings),
        )

    async def reload(self) -> ModelReloadSnapshot:
        async with self._reload_lock:
            return self.reload_now()

    def status(self) -> ModelRegistryStatusSnapshot:
        return ModelRegistryStatusSnapshot(
            provider_count=len(self.active_registry.providers),
            preset_count=len(self.active_registry.presets),
            binding_count=len(self.active_registry.bindings),
            last_error=self.last_error,
        )

    def list_providers(self) -> list[ModelProvider]:
        return [self.active_registry.providers[key] for key in sorted(self.active_registry.providers)]

    def list_presets(self) -> list[ModelPreset]:
        return [self.active_registry.presets[key] for key in sorted(self.active_registry.presets)]

    def list_bindings(self) -> list[ModelBinding]:
        return [self.active_registry.bindings[key] for key in sorted(self.active_registry.bindings)]

    def list_binding_snapshots(self) -> list[ModelBindingSnapshot]:
        """返回 binding 的控制面派生视图."""

        return [self.get_binding_snapshot(binding.binding_id) for binding in self.list_bindings()]

    def get_provider(self, provider_id: str) -> ModelProvider | None:
        return self.active_registry.providers.get(provider_id)

    def get_preset(self, preset_id: str) -> ModelPreset | None:
        return self.active_registry.presets.get(preset_id)

    def get_binding(self, binding_id: str) -> ModelBinding | None:
        return self.active_registry.bindings.get(binding_id)

    def get_binding_snapshot(self, binding_id: str) -> ModelBindingSnapshot:
        """返回某条 binding 当前的解析状态."""

        binding = self.get_binding(binding_id)
        if binding is None:
            raise KeyError(binding_id)
        return self._binding_snapshot(binding)

    def resolve_preset_request(self, preset_id: str) -> RuntimeModelRequest | None:
        """按 preset_id 直接解析一份 RuntimeModelRequest."""

        return self._request_from_preset_id(None, preset_id)

    def resolve_target_request(self, target_id: str) -> RuntimeModelRequest | None:
        """按 target_id 解析一份运行时模型请求."""

        binding = self.active_registry.binding_for_target(target_id)
        if binding is None:
            return None
        binding_snapshot = self._binding_snapshot(binding)
        if binding_snapshot.binding_state != "resolved":
            return None
        return self._request_from_binding(binding)

    def get_provider_impact(self, provider_id: str) -> ModelImpactSnapshot:
        return self.active_registry.provider_impact(provider_id)

    def get_preset_impact(self, preset_id: str) -> ModelImpactSnapshot:
        return self.active_registry.preset_impact(preset_id)

    def get_binding_impact(self, binding_id: str) -> ModelImpactSnapshot:
        return self.active_registry.binding_impact(binding_id)

    async def upsert_provider(self, provider: ModelProvider) -> ModelMutationResult:
        impact = self.get_provider_impact(provider.provider_id)
        return await self._apply_candidate(
            action="upsert",
            entity_type="provider",
            entity_id=provider.provider_id,
            impact=impact,
            mutator=lambda registry: registry.providers.__setitem__(provider.provider_id, provider),
            writer=lambda: self._write_yaml(self.providers_dir / f"{provider.provider_id}.yaml", provider.to_dict()),
        )

    async def upsert_preset(self, preset: ModelPreset) -> ModelMutationResult:
        impact = self.get_preset_impact(preset.preset_id)
        return await self._apply_candidate(
            action="upsert",
            entity_type="preset",
            entity_id=preset.preset_id,
            impact=impact,
            mutator=lambda registry: registry.presets.__setitem__(preset.preset_id, preset),
            writer=lambda: self._write_yaml(self.presets_dir / f"{preset.preset_id}.yaml", preset.to_dict()),
        )

    async def upsert_binding(self, binding: ModelBinding) -> ModelMutationResult:
        impact = self.get_binding_impact(binding.binding_id)
        return await self._apply_candidate(
            action="upsert",
            entity_type="binding",
            entity_id=binding.binding_id,
            impact=impact,
            mutator=lambda registry: registry.bindings.__setitem__(binding.binding_id, binding),
            writer=lambda: self._write_yaml(self.bindings_dir / f"{binding.binding_id}.yaml", binding.to_dict()),
        )

    async def delete_provider(self, provider_id: str, *, force: bool = False) -> ModelMutationResult:
        impact = self.get_provider_impact(provider_id)
        if (impact.preset_ids or impact.binding_ids) and not force:
            return ModelMutationResult(
                ok=False,
                applied=False,
                action="delete",
                entity_type="provider",
                entity_id=provider_id,
                message="provider is still in use",
                impact=impact,
            )
        removed_preset_ids = list(impact.preset_ids) if force else []
        removed_binding_ids = list(impact.binding_ids) if force else []
        return await self._apply_candidate(
            action="delete",
            entity_type="provider",
            entity_id=provider_id,
            impact=impact,
            mutator=lambda registry: self._delete_provider_from_registry(
                registry,
                provider_id=provider_id,
                preset_ids=removed_preset_ids,
                binding_ids=removed_binding_ids,
            ),
            writer=lambda: self._delete_provider_from_files(
                provider_id=provider_id,
                preset_ids=removed_preset_ids,
                binding_ids=removed_binding_ids,
            ),
            cascaded_provider_ids=[provider_id] if self.get_provider(provider_id) is not None else [],
            cascaded_preset_ids=removed_preset_ids,
            cascaded_binding_ids=removed_binding_ids,
        )

    async def delete_preset(self, preset_id: str, *, force: bool = False) -> ModelMutationResult:
        impact = self.get_preset_impact(preset_id)
        if impact.binding_ids and not force:
            return ModelMutationResult(
                ok=False,
                applied=False,
                action="delete",
                entity_type="preset",
                entity_id=preset_id,
                message="preset is still in use",
                impact=impact,
            )
        removed_binding_ids = list(impact.binding_ids) if force else []
        return await self._apply_candidate(
            action="delete",
            entity_type="preset",
            entity_id=preset_id,
            impact=impact,
            mutator=lambda registry: self._delete_preset_from_registry(
                registry,
                preset_id=preset_id,
                binding_ids=removed_binding_ids,
            ),
            writer=lambda: self._delete_preset_from_files(
                preset_id=preset_id,
                binding_ids=removed_binding_ids,
            ),
            cascaded_preset_ids=[preset_id] if self.get_preset(preset_id) is not None else [],
            cascaded_binding_ids=removed_binding_ids,
        )

    async def delete_binding(self, binding_id: str) -> ModelMutationResult:
        impact = self.get_binding_impact(binding_id)
        return await self._apply_candidate(
            action="delete",
            entity_type="binding",
            entity_id=binding_id,
            impact=impact,
            mutator=lambda registry: registry.bindings.pop(binding_id, None),
            writer=lambda: self._delete_file(self.bindings_dir / f"{binding_id}.yaml"),
            cascaded_binding_ids=[binding_id] if self.get_binding(binding_id) is not None else [],
        )

    def resolve_from_snapshot(self, snapshot: PersistedModelSnapshot | None) -> RuntimeModelRequest | None:
        if snapshot is None:
            return None
        return snapshot.to_runtime_request()

    def preview_effective_target(self, target_id: str) -> EffectiveModelSnapshot:
        """预览某个 target 当前解析出来的请求."""

        source = "none"
        request = None
        binding = self.active_registry.binding_for_target(target_id)
        if binding is not None:
            binding_snapshot = self._binding_snapshot(binding)
            if binding_snapshot.binding_state == "resolved":
                request = self._request_from_binding(binding)
                source = request.binding_id or "resolved"
            else:
                source = binding_snapshot.binding_state
        target_type = target_id.split(":", 1)[0] if ":" in target_id else "unknown"
        return EffectiveModelSnapshot(
            target_type=target_type,
            target_id=target_id,
            source=source,
            request=request,
        )

    async def health_check(
        self,
        *,
        preset_id: str,
    ) -> ModelHealthCheckResult:
        preset = self.active_registry.presets.get(preset_id)
        if preset is None:
            return ModelHealthCheckResult(
                ok=False,
                provider_id="",
                preset_id=preset_id,
                model="",
                message="preset not found",
            )
        request = self._request_from_preset_id(None, preset_id)
        if request is None:
            return ModelHealthCheckResult(
                ok=False,
                provider_id=preset.provider_id,
                preset_id=preset_id,
                model=preset.model,
                message="failed to resolve runtime request",
            )
        try:
            from acabot.agent.agent import LitellmAgent
        except Exception as exc:
            return ModelHealthCheckResult(
                ok=False,
                provider_id=request.provider_id,
                preset_id=request.preset_id,
                model=request.model,
                message=str(exc),
            )

        agent = LitellmAgent(max_tool_rounds=0)
        try:
            response = await agent.complete(
                system_prompt="health check",
                messages=[{"role": "user", "content": "ping"}],
                model=request.model,
                request_options=request.to_request_options(),
            )
        except Exception as exc:
            return ModelHealthCheckResult(
                ok=False,
                provider_id=request.provider_id,
                preset_id=request.preset_id,
                model=request.model,
                message=str(exc),
            )
        if getattr(response, "error", None):
            return ModelHealthCheckResult(
                ok=False,
                provider_id=request.provider_id,
                preset_id=request.preset_id,
                model=request.model,
                message=str(response.error),
            )
        return ModelHealthCheckResult(
            ok=True,
            provider_id=request.provider_id,
            preset_id=request.preset_id,
            model=request.model,
            metadata={"model_used": str(getattr(response, "model_used", "") or request.model)},
        )

    async def _apply_candidate(
        self,
        *,
        action: str,
        entity_type: ModelEntityType,
        entity_id: str,
        impact: ModelImpactSnapshot | None,
        mutator,
        writer,
        binding_state: ModelBindingState = "resolved",
        cascaded_provider_ids: list[str] | None = None,
        cascaded_preset_ids: list[str] | None = None,
        cascaded_binding_ids: list[str] | None = None,
    ) -> ModelMutationResult:
        candidate = self.active_registry.clone()
        try:
            mutator(candidate)
            candidate.validate(target_catalog=self.target_catalog)
            result = writer()
            if isawaitable(result):
                await result
        except Exception as exc:
            resolved_binding_state = binding_state
            if entity_type == "binding":
                candidate_binding = candidate.bindings.get(entity_id)
                if candidate_binding is not None:
                    resolved_binding_state = self._binding_snapshot_for_registry(candidate, candidate_binding).binding_state
            return ModelMutationResult(
                ok=False,
                applied=False,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                message=str(exc),
                binding_state=resolved_binding_state,
                impact=impact,
                cascaded_provider_ids=list(cascaded_provider_ids or []),
                cascaded_preset_ids=list(cascaded_preset_ids or []),
                cascaded_binding_ids=list(cascaded_binding_ids or []),
            )

        reload_result = await self.reload()
        resolved_binding_state = binding_state
        if entity_type == "binding":
            resolved_binding_state = self.get_binding_snapshot(entity_id).binding_state
        return ModelMutationResult(
            ok=reload_result.ok,
            applied=reload_result.ok,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            message=reload_result.error,
            binding_state=resolved_binding_state,
            impact=impact,
            cascaded_provider_ids=list(cascaded_provider_ids or []),
            cascaded_preset_ids=list(cascaded_preset_ids or []),
            cascaded_binding_ids=list(cascaded_binding_ids or []),
        )

    def _request_from_binding(self, binding: ModelBinding) -> RuntimeModelRequest:
        requests = [self._request_from_preset_id(binding, preset_id) for preset_id in binding.preset_ids]
        resolved_requests = [item for item in requests if item is not None]
        if not resolved_requests:
            raise ValueError(f"unknown preset_ids for binding: {binding.binding_id}")
        first, *rest = resolved_requests
        first.fallback_requests = list(rest)
        return first

    def _request_from_preset_id(
        self,
        binding: ModelBinding | None,
        preset_id: str,
    ) -> RuntimeModelRequest | None:
        preset = self.active_registry.presets.get(preset_id)
        if preset is None:
            return None
        provider = self.active_registry.providers.get(preset.provider_id)
        if provider is None:
            return None
        provider_params = asdict(provider.config)
        api_key_env, api_key = _normalize_provider_auth_fields(
            api_key_env=str(provider_params.pop("api_key_env", "") or ""),
            api_key=str(provider_params.pop("api_key", "") or ""),
        )
        model_params = dict(preset.model_params)
        execution_params: dict[str, Any] = {}
        if binding is not None and binding.timeout_sec is not None:
            execution_params["timeout"] = binding.timeout_sec
        if preset.max_output_tokens is not None:
            model_params.setdefault("max_tokens", preset.max_output_tokens)
        capabilities = _normalize_capabilities(preset.capabilities)
        return RuntimeModelRequest(
            provider_kind=provider.kind,
            model=self._resolved_model_name(provider.kind, preset.model),
            context_window=preset.context_window,
            supports_tools="tool_calling" in capabilities,
            supports_vision="image_input" in capabilities,
            task_kind=preset.task_kind,
            capabilities=capabilities,
            provider_id=provider.provider_id,
            preset_id=preset.preset_id,
            binding_id=binding.binding_id if binding is not None else "",
            api_key_env=api_key_env,
            api_key=api_key,
            provider_params=provider_params,
            model_params=model_params,
            execution_params=execution_params,
        )

    @staticmethod
    def _legacy_request(model: str, *, binding_id: str) -> RuntimeModelRequest:
        return RuntimeModelRequest(
            provider_kind="legacy",
            model=str(model or ""),
            binding_id=binding_id,
            supports_tools=True,
            supports_vision=False,
            task_kind="chat",
            capabilities=["tool_calling"],
        )

    @staticmethod
    def _resolved_model_name(provider_kind: str, model: str) -> str:
        normalized = str(model or "").strip()
        if provider_kind == "google_gemini" and normalized and "/" not in normalized:
            return f"gemini/{normalized}"
        return normalized

    def _load_registry_from_filesystem(self) -> ModelRegistry:
        registry = ModelRegistry()
        registry.providers = {
            provider.provider_id: provider
            for provider in self._load_provider_files()
        }
        registry.presets = {
            preset.preset_id: preset
            for preset in self._load_preset_files()
        }
        registry.bindings = {
            binding.binding_id: binding
            for binding in self._load_binding_files()
        }
        return registry

    def _load_provider_files(self) -> list[ModelProvider]:
        items: list[ModelProvider] = []
        if not self.providers_dir.exists():
            return items
        for path in sorted(self.providers_dir.glob("*.y*ml")):
            items.append(self._load_provider_file(path))
        return items

    def _load_preset_files(self) -> list[ModelPreset]:
        items: list[ModelPreset] = []
        if not self.presets_dir.exists():
            return items
        for path in sorted(self.presets_dir.glob("*.y*ml")):
            items.append(self._load_preset_file(path))
        return items

    def _load_binding_files(self) -> list[ModelBinding]:
        items: list[ModelBinding] = []
        if not self.bindings_dir.exists():
            return items
        for path in sorted(self.bindings_dir.glob("*.y*ml")):
            items.append(self._load_binding_file(path))
        return items

    @staticmethod
    def _load_provider_file(path: Path) -> ModelProvider:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"provider file must be a mapping: {path}")
        provider_id = str(raw.get("provider_id", "") or path.stem)
        name = str(raw.get("name", "") or provider_id)
        kind = str(raw.get("kind", "") or "")
        if kind == "openai_compatible":
            api_key_env, api_key = _normalize_provider_auth_fields(
                api_key_env=str(raw.get("api_key_env", "") or ""),
                api_key=str(raw.get("api_key", "") or ""),
            )
            config = OpenAICompatibleProviderConfig(
                base_url=str(raw.get("base_url", "") or ""),
                api_key_env=api_key_env,
                api_key=api_key,
                default_headers={
                    str(key): str(value)
                    for key, value in dict(raw.get("default_headers", {}) or {}).items()
                },
                default_query=dict(raw.get("default_query", {}) or {}),
                default_body=dict(raw.get("default_body", {}) or {}),
            )
            return ModelProvider(provider_id=provider_id, kind="openai_compatible", config=config, name=name)
        if kind == "anthropic":
            api_key_env, api_key = _normalize_provider_auth_fields(
                api_key_env=str(raw.get("api_key_env", "") or ""),
                api_key=str(raw.get("api_key", "") or ""),
            )
            config = AnthropicProviderConfig(
                api_key_env=api_key_env,
                api_key=api_key,
                base_url=str(raw.get("base_url", "") or ""),
                anthropic_version=str(raw.get("anthropic_version", "") or ""),
                default_headers={
                    str(key): str(value)
                    for key, value in dict(raw.get("default_headers", {}) or {}).items()
                },
                default_query=dict(raw.get("default_query", {}) or {}),
                default_body=dict(raw.get("default_body", {}) or {}),
            )
            return ModelProvider(provider_id=provider_id, kind="anthropic", config=config, name=name)
        if kind == "google_gemini":
            api_key_env, api_key = _normalize_provider_auth_fields(
                api_key_env=str(raw.get("api_key_env", "") or ""),
                api_key=str(raw.get("api_key", "") or ""),
            )
            config = GoogleGeminiProviderConfig(
                api_key_env=api_key_env,
                api_key=api_key,
                base_url=str(raw.get("base_url", "") or ""),
                api_version=str(raw.get("api_version", "") or ""),
                project_id=str(raw.get("project_id", "") or ""),
                location=str(raw.get("location", "") or ""),
                use_vertex_ai=bool(raw.get("use_vertex_ai", False)),
                default_headers={
                    str(key): str(value)
                    for key, value in dict(raw.get("default_headers", {}) or {}).items()
                },
                default_query=dict(raw.get("default_query", {}) or {}),
                default_body=dict(raw.get("default_body", {}) or {}),
            )
            return ModelProvider(provider_id=provider_id, kind="google_gemini", config=config, name=name)
        raise ValueError(f"unsupported provider kind in {path}: {kind}")

    @staticmethod
    def _load_preset_file(path: Path) -> ModelPreset:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"preset file must be a mapping: {path}")
        return ModelPreset(
            preset_id=str(raw.get("preset_id", "") or path.stem),
            provider_id=str(raw.get("provider_id", "") or ""),
            model=str(raw.get("model", "") or ""),
            task_kind=str(raw.get("task_kind", raw.get("capability", "")) or ""),
            context_window=int(raw.get("context_window", 0) or 0),
            capabilities=_normalize_capabilities(
                raw.get("capabilities")
                if "capabilities" in raw
                else [
                    capability
                    for capability, enabled in (
                        ("tool_calling", raw.get("supports_tools", True)),
                        ("image_input", raw.get("supports_vision", False)),
                    )
                    if enabled
                ]
            ),
            max_output_tokens=(
                None if raw.get("max_output_tokens") in {None, ""} else int(raw.get("max_output_tokens"))
            ),
            model_params=dict(raw.get("model_params", {}) or {}),
        )

    @staticmethod
    def _load_binding_file(path: Path) -> ModelBinding:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"binding file must be a mapping: {path}")
        return ModelBinding(
            binding_id=str(raw.get("binding_id", "") or path.stem),
            target_id=str(raw.get("target_id", "") or ""),
            preset_ids=[str(item) for item in list(raw.get("preset_ids", []) or [])],
            timeout_sec=(
                None if raw.get("timeout_sec") in {None, ""} else float(raw.get("timeout_sec"))
            ),
        )

    def _binding_snapshot(self, binding: ModelBinding) -> ModelBindingSnapshot:
        """根据当前 target 目录和 active registry 计算 binding 的真实状态."""

        return self._binding_snapshot_for_registry(self.active_registry, binding)

    def _binding_snapshot_for_registry(
        self,
        registry: ModelRegistry,
        binding: ModelBinding,
    ) -> ModelBindingSnapshot:
        """根据给定 registry 和当前 target 目录计算 binding 的真实状态."""

        target = self.target_catalog.get(binding.target_id)
        if target is None:
            return ModelBindingSnapshot(
                binding=binding,
                binding_state="unresolved_target",
                target_present=False,
                message=f"target not registered: {binding.target_id}",
            )
        if not binding.preset_ids:
            return ModelBindingSnapshot(
                binding=binding,
                binding_state="invalid_binding",
                target_present=True,
                message=f"binding has no preset_ids: {binding.binding_id}",
            )
        if not target.allow_fallbacks and len(binding.preset_ids) > 1:
            return ModelBindingSnapshot(
                binding=binding,
                binding_state="invalid_binding",
                target_present=True,
                message=f"target does not allow fallbacks: {binding.target_id}",
            )
        required_capabilities = set(target.required_capabilities)
        for preset_id in binding.preset_ids:
            preset = registry.presets.get(preset_id)
            if preset is None:
                return ModelBindingSnapshot(
                    binding=binding,
                    binding_state="invalid_binding",
                    target_present=True,
                    message=f"unknown preset_id for binding {binding.binding_id}: {preset_id}",
                )
            if preset.task_kind != target.task_kind:
                return ModelBindingSnapshot(
                    binding=binding,
                    binding_state="invalid_binding",
                    target_present=True,
                    message=(
                        f"preset task_kind mismatch for {binding.binding_id}: "
                        f"target={target.task_kind} preset={preset.task_kind}"
                    ),
                )
            missing_capabilities = sorted(required_capabilities.difference(preset.capabilities))
            if missing_capabilities:
                return ModelBindingSnapshot(
                    binding=binding,
                    binding_state="invalid_binding",
                    target_present=True,
                    message=(
                        f"preset capabilities mismatch for {binding.binding_id}: "
                        f"target={binding.target_id} missing={','.join(missing_capabilities)}"
                    ),
                )
            provider = registry.providers.get(preset.provider_id)
            if provider is None:
                return ModelBindingSnapshot(
                    binding=binding,
                    binding_state="invalid_binding",
                    target_present=True,
                    message=f"unknown provider_id for preset {preset.preset_id}: {preset.provider_id}",
                )
        return ModelBindingSnapshot(
            binding=binding,
            binding_state="resolved",
            target_present=True,
            message="",
        )

    def _delete_provider_from_registry(
        self,
        registry: ModelRegistry,
        *,
        provider_id: str,
        preset_ids: list[str],
        binding_ids: list[str],
    ) -> None:
        registry.providers.pop(provider_id, None)
        for preset_id in preset_ids:
            registry.presets.pop(preset_id, None)
        for binding_id in binding_ids:
            registry.bindings.pop(binding_id, None)

    def _delete_preset_from_registry(
        self,
        registry: ModelRegistry,
        *,
        preset_id: str,
        binding_ids: list[str],
    ) -> None:
        registry.presets.pop(preset_id, None)
        for binding_id in binding_ids:
            registry.bindings.pop(binding_id, None)

    def _delete_provider_from_files(
        self,
        *,
        provider_id: str,
        preset_ids: list[str],
        binding_ids: list[str],
    ) -> None:
        self._delete_file(self.providers_dir / f"{provider_id}.yaml")
        for preset_id in preset_ids:
            self._delete_file(self.presets_dir / f"{preset_id}.yaml")
        for binding_id in binding_ids:
            self._delete_file(self.bindings_dir / f"{binding_id}.yaml")

    def _delete_preset_from_files(
        self,
        *,
        preset_id: str,
        binding_ids: list[str],
    ) -> None:
        self._delete_file(self.presets_dir / f"{preset_id}.yaml")
        for binding_id in binding_ids:
            self._delete_file(self.bindings_dir / f"{binding_id}.yaml")

    @staticmethod
    def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True)
            temp_path = Path(handle.name)
        temp_path.replace(path)

    @staticmethod
    def _delete_file(path: Path) -> None:
        if path.exists():
            path.unlink()


# endregion
