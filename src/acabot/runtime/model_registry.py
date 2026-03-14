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
from tempfile import NamedTemporaryFile
from typing import Any, Literal

import yaml

ModelProviderKind = Literal["openai_compatible", "anthropic", "google_gemini"]
ModelBindingTargetType = Literal["global", "agent", "system"]
ModelEntityType = Literal["provider", "preset", "binding"]

_SUPPORTED_PROVIDER_KINDS: set[str] = {
    "openai_compatible",
    "anthropic",
    "google_gemini",
}
_SUPPORTED_BINDING_TARGETS: set[tuple[str, str]] = {
    ("global", "default"),
    ("system", "compactor_summary"),
}


# region provider config
@dataclass(slots=True)
class OpenAICompatibleProviderConfig:
    """OpenAI-compatible provider 的静态配置."""

    base_url: str
    api_key_env: str
    default_headers: dict[str, str] = field(default_factory=dict)
    default_query: dict[str, Any] = field(default_factory=dict)
    default_body: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AnthropicProviderConfig:
    """Anthropic provider 的静态配置."""

    api_key_env: str
    base_url: str = ""
    anthropic_version: str = ""
    default_headers: dict[str, str] = field(default_factory=dict)
    default_query: dict[str, Any] = field(default_factory=dict)
    default_body: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GoogleGeminiProviderConfig:
    """Google Gemini provider 的静态配置."""

    api_key_env: str
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "kind": self.kind,
            **asdict(self.config),
        }


# endregion


# region preset / binding
@dataclass(slots=True)
class ModelPreset:
    """一条具体模型预设."""

    preset_id: str
    provider_id: str
    model: str
    context_window: int
    supports_tools: bool = True
    supports_vision: bool = False
    max_output_tokens: int | None = None
    model_params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "preset_id": self.preset_id,
            "provider_id": self.provider_id,
            "model": self.model,
            "context_window": self.context_window,
            "supports_tools": self.supports_tools,
            "supports_vision": self.supports_vision,
            "model_params": dict(self.model_params),
        }
        if self.max_output_tokens is not None:
            data["max_output_tokens"] = self.max_output_tokens
        return data


@dataclass(slots=True)
class ModelBinding:
    """一条执行单元到 preset 的绑定."""

    binding_id: str
    target_type: ModelBindingTargetType
    target_id: str
    preset_id: str = ""
    preset_ids: list[str] = field(default_factory=list)
    timeout_sec: float | None = None

    @property
    def target_key(self) -> str:
        return f"{self.target_type}:{self.target_id}"

    def to_dict(self) -> dict[str, Any]:
        data = {
            "binding_id": self.binding_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
        }
        if self.preset_ids:
            data["preset_ids"] = list(self.preset_ids)
        elif self.preset_id:
            data["preset_id"] = self.preset_id
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
    provider_id: str = ""
    preset_id: str = ""
    binding_id: str = ""
    api_key_env: str = ""
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
            resolved_non_secret_params=dict(raw.get("resolved_non_secret_params", {}) or {}),
        )

    def to_runtime_request(self) -> RuntimeModelRequest:
        return RuntimeModelRequest(
            provider_kind=self.provider_kind,
            model=self.model,
            context_window=self.context_window,
            supports_tools=self.supports_tools,
            supports_vision=self.supports_vision,
            provider_id=self.provider_id,
            preset_id=self.preset_id,
            binding_id=self.binding_id,
            api_key_env=self.api_key_env,
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
    impact: ModelImpactSnapshot | None = None
    cascaded_provider_ids: list[str] = field(default_factory=list)
    cascaded_preset_ids: list[str] = field(default_factory=list)
    cascaded_binding_ids: list[str] = field(default_factory=list)


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

    def validate(self) -> None:
        target_keys: set[str] = set()
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
            self._validate_binding(binding)
            if binding.target_key in target_keys:
                raise ValueError(f"duplicate binding target: {binding.target_key}")
            target_keys.add(binding.target_key)

    def binding_for_agent(self, agent_id: str) -> ModelBinding | None:
        return self._binding_for("agent", agent_id) or self._binding_for("global", "default")

    def binding_for_system(self, target_id: str) -> ModelBinding | None:
        return self._binding_for("system", target_id)

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
            if preset_id != binding.preset_id and preset_id not in binding.preset_ids:
                continue
            impact.binding_ids.append(binding.binding_id)
            if binding.target_type == "agent":
                impact.agent_ids.append(binding.target_id)
            if binding.target_type == "system":
                impact.system_targets.append(binding.target_id)
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
        if binding.target_type == "agent":
            impact.agent_ids.append(binding.target_id)
        if binding.target_type == "system":
            impact.system_targets.append(binding.target_id)
        return impact

    def clone(self) -> ModelRegistry:
        return deepcopy(self)

    def _binding_for(self, target_type: str, target_id: str) -> ModelBinding | None:
        for binding in self.bindings.values():
            if binding.target_type == target_type and binding.target_id == target_id:
                return binding
        return None

    def _validate_provider(self, provider: ModelProvider) -> None:
        if provider.kind not in _SUPPORTED_PROVIDER_KINDS:
            raise ValueError(f"unsupported provider kind: {provider.kind}")
        provider_id = str(provider.provider_id or "").strip()
        if not provider_id:
            raise ValueError("provider_id is required")
        config = provider.config
        api_key_env = str(getattr(config, "api_key_env", "") or "").strip()
        if not api_key_env:
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
        if int(preset.context_window) <= 0:
            raise ValueError(f"context_window must be positive: {preset.preset_id}")
        if preset.max_output_tokens is not None and int(preset.max_output_tokens) <= 0:
            raise ValueError(f"max_output_tokens must be positive: {preset.preset_id}")

    def _validate_binding(self, binding: ModelBinding) -> None:
        if not str(binding.binding_id or "").strip():
            raise ValueError("binding_id is required")
        if binding.target_type not in {"global", "agent", "system"}:
            raise ValueError(f"unsupported binding target_type: {binding.target_type}")
        if not str(binding.target_id or "").strip():
            raise ValueError(f"target_id is required: {binding.binding_id}")
        if binding.target_type != "agent" and (binding.target_type, binding.target_id) not in _SUPPORTED_BINDING_TARGETS:
            raise ValueError(f"unsupported binding target: {binding.target_type}:{binding.target_id}")
        if binding.target_type == "system":
            if binding.target_id != "compactor_summary":
                raise ValueError(f"unsupported system target_id: {binding.target_id}")
            if not binding.preset_ids:
                raise ValueError("system/compactor_summary binding requires preset_ids")
            if binding.preset_id:
                raise ValueError("system/compactor_summary binding must not declare preset_id")
            for preset_id in binding.preset_ids:
                if preset_id not in self.presets:
                    raise ValueError(f"unknown preset_id in fallback chain: {preset_id}")
        else:
            if not binding.preset_id:
                raise ValueError(f"binding preset_id is required: {binding.binding_id}")
            if binding.preset_ids:
                raise ValueError(f"binding preset_ids only allowed for system fallback chains: {binding.binding_id}")
            if binding.preset_id not in self.presets:
                raise ValueError(f"unknown preset_id for binding {binding.binding_id}: {binding.preset_id}")
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
        legacy_global_default_model: str = "",
        legacy_summary_model: str = "",
    ) -> None:
        self.providers_dir = Path(providers_dir)
        self.presets_dir = Path(presets_dir)
        self.bindings_dir = Path(bindings_dir)
        self.legacy_global_default_model = str(legacy_global_default_model or "")
        self.legacy_summary_model = str(legacy_summary_model or "")
        self.active_registry = ModelRegistry()
        self.last_error = ""
        self._reload_lock = asyncio.Lock()

    def reload_now(self) -> ModelReloadSnapshot:
        try:
            registry = self._load_registry_from_filesystem()
            registry.validate()
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

    def get_provider(self, provider_id: str) -> ModelProvider | None:
        return self.active_registry.providers.get(provider_id)

    def get_preset(self, preset_id: str) -> ModelPreset | None:
        return self.active_registry.presets.get(preset_id)

    def get_binding(self, binding_id: str) -> ModelBinding | None:
        return self.active_registry.bindings.get(binding_id)

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

    def resolve_run_request(
        self,
        *,
        run_mode: str,
        agent_id: str,
        explicit_profile_default_model: str = "",
        effective_profile_default_model: str = "",
    ) -> tuple[RuntimeModelRequest | None, PersistedModelSnapshot | None]:
        """
        解析 run 模型请求和对应的 snapshot.

        按照 Binding > Profile 显式指定 > 全局默认值 > Profile 隐式指定 的顺序进行匹配

        Args:
            run_mode: 运行模式.
            agent_id: Agent ID.
            explicit_profile_default_model: 显式配置的 Profile 默认模型.
            effective_profile_default_model: 生效的 Profile 默认模型.

        Returns:
            `(model_request, model_snapshot)` 二元组.
        """

        if run_mode == "record_only":
            return None, None
        # 控制面板里给这个 agent_id 专门绑定某个模型预设是最高优先级
        binding = self.active_registry.binding_for_agent(agent_id)
        if binding is not None:
            request = self._request_from_binding(binding)
            return request, snapshot_from_runtime_request(request)

        # 没有绑定的话，看看 profile 里有没有显式指定默认模型
        if explicit_profile_default_model:
            request = self._legacy_request(
                explicit_profile_default_model,
                binding_id="legacy:profile_default_model",
            )
            return request, snapshot_from_runtime_request(request)

        # 配置文件的 agent 节点下有没有写一个全局的 default_model
        if self.legacy_global_default_model:
            request = self._legacy_request(
                self.legacy_global_default_model,
                binding_id="legacy:global_default_model",
            )
            return request, snapshot_from_runtime_request(request)

        if effective_profile_default_model:
            request = self._legacy_request(
                effective_profile_default_model,
                binding_id="legacy:effective_profile_default_model",
            )
            return request, snapshot_from_runtime_request(request)

        return None, None

    def resolve_summary_request(
        self,
        *,
        primary_request: RuntimeModelRequest | None,
    ) -> RuntimeModelRequest | None:
        binding = self.active_registry.binding_for_system("compactor_summary")
        if binding is not None:
            requests = [self._request_from_preset_id(binding, preset_id) for preset_id in binding.preset_ids]
            requests = [item for item in requests if item is not None]
            if requests:
                first, *rest = requests
                for item in [first, *rest]:
                    item.binding_id = binding.binding_id
                    if binding.timeout_sec is not None:
                        item.execution_params = {
                            **dict(item.execution_params),
                            "timeout": binding.timeout_sec,
                        }
                first.fallback_requests = list(rest)
                return first

        if self.legacy_summary_model:
            return self._legacy_request(
                self.legacy_summary_model,
                binding_id="legacy:summary_model",
            )

        if primary_request is None:
            return None
        return RuntimeModelRequest(
            provider_kind=primary_request.provider_kind,
            model=primary_request.model,
            context_window=primary_request.context_window,
            supports_tools=primary_request.supports_tools,
            supports_vision=primary_request.supports_vision,
            provider_id=primary_request.provider_id,
            preset_id=primary_request.preset_id,
            binding_id=primary_request.binding_id,
            api_key_env=primary_request.api_key_env,
            provider_params=dict(primary_request.provider_params),
            model_params=dict(primary_request.model_params),
            execution_params=dict(primary_request.execution_params),
        )

    def resolve_from_snapshot(self, snapshot: PersistedModelSnapshot | None) -> RuntimeModelRequest | None:
        if snapshot is None:
            return None
        return snapshot.to_runtime_request()

    def preview_effective_agent(
        self,
        *,
        agent_id: str,
        explicit_profile_default_model: str = "",
        effective_profile_default_model: str = "",
    ) -> EffectiveModelSnapshot:
        request, _ = self.resolve_run_request(
            run_mode="respond",
            agent_id=agent_id,
            explicit_profile_default_model=explicit_profile_default_model,
            effective_profile_default_model=effective_profile_default_model,
        )
        source = "none"
        if request is not None:
            source = request.binding_id or "resolved"
        return EffectiveModelSnapshot(
            target_type="agent",
            target_id=agent_id,
            source=source,
            request=request,
        )

    def preview_effective_summary(self) -> EffectiveModelSnapshot:
        request = self.resolve_summary_request(primary_request=None)
        source = "none"
        if request is not None:
            source = request.binding_id or "resolved"
        return EffectiveModelSnapshot(
            target_type="system",
            target_id="compactor_summary",
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
        cascaded_provider_ids: list[str] | None = None,
        cascaded_preset_ids: list[str] | None = None,
        cascaded_binding_ids: list[str] | None = None,
    ) -> ModelMutationResult:
        candidate = self.active_registry.clone()
        try:
            mutator(candidate)
            candidate.validate()
            result = writer()
            if isawaitable(result):
                await result
        except Exception as exc:
            return ModelMutationResult(
                ok=False,
                applied=False,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                message=str(exc),
                impact=impact,
                cascaded_provider_ids=list(cascaded_provider_ids or []),
                cascaded_preset_ids=list(cascaded_preset_ids or []),
                cascaded_binding_ids=list(cascaded_binding_ids or []),
            )

        reload_result = await self.reload()
        return ModelMutationResult(
            ok=reload_result.ok,
            applied=reload_result.ok,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            message=reload_result.error,
            impact=impact,
            cascaded_provider_ids=list(cascaded_provider_ids or []),
            cascaded_preset_ids=list(cascaded_preset_ids or []),
            cascaded_binding_ids=list(cascaded_binding_ids or []),
        )

    def _request_from_binding(self, binding: ModelBinding) -> RuntimeModelRequest:
        if binding.target_type == "system":
            raise ValueError("system binding requires fallback-chain resolution")
        request = self._request_from_preset_id(binding, binding.preset_id)
        if request is None:
            raise ValueError(f"unknown preset_id for binding: {binding.binding_id}")
        return request

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
        model_params = dict(preset.model_params)
        execution_params: dict[str, Any] = {}
        if binding is not None and binding.timeout_sec is not None:
            execution_params["timeout"] = binding.timeout_sec
        if preset.max_output_tokens is not None:
            model_params.setdefault("max_tokens", preset.max_output_tokens)
        return RuntimeModelRequest(
            provider_kind=provider.kind,
            model=self._resolved_model_name(provider.kind, preset.model),
            context_window=preset.context_window,
            supports_tools=bool(preset.supports_tools),
            supports_vision=bool(preset.supports_vision),
            provider_id=provider.provider_id,
            preset_id=preset.preset_id,
            binding_id=binding.binding_id if binding is not None else "",
            api_key_env=str(getattr(provider.config, "api_key_env", "") or ""),
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
        kind = str(raw.get("kind", "") or "")
        if kind == "openai_compatible":
            config = OpenAICompatibleProviderConfig(
                base_url=str(raw.get("base_url", "") or ""),
                api_key_env=str(raw.get("api_key_env", "") or ""),
                default_headers={
                    str(key): str(value)
                    for key, value in dict(raw.get("default_headers", {}) or {}).items()
                },
                default_query=dict(raw.get("default_query", {}) or {}),
                default_body=dict(raw.get("default_body", {}) or {}),
            )
            return ModelProvider(provider_id=provider_id, kind="openai_compatible", config=config)
        if kind == "anthropic":
            config = AnthropicProviderConfig(
                api_key_env=str(raw.get("api_key_env", "") or ""),
                base_url=str(raw.get("base_url", "") or ""),
                anthropic_version=str(raw.get("anthropic_version", "") or ""),
                default_headers={
                    str(key): str(value)
                    for key, value in dict(raw.get("default_headers", {}) or {}).items()
                },
                default_query=dict(raw.get("default_query", {}) or {}),
                default_body=dict(raw.get("default_body", {}) or {}),
            )
            return ModelProvider(provider_id=provider_id, kind="anthropic", config=config)
        if kind == "google_gemini":
            config = GoogleGeminiProviderConfig(
                api_key_env=str(raw.get("api_key_env", "") or ""),
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
            return ModelProvider(provider_id=provider_id, kind="google_gemini", config=config)
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
            context_window=int(raw.get("context_window", 0) or 0),
            supports_tools=bool(raw.get("supports_tools", True)),
            supports_vision=bool(raw.get("supports_vision", False)),
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
            target_type=str(raw.get("target_type", "") or ""),
            target_id=str(raw.get("target_id", "") or ""),
            preset_id=str(raw.get("preset_id", "") or ""),
            preset_ids=[str(item) for item in list(raw.get("preset_ids", []) or [])],
            timeout_sec=(
                None if raw.get("timeout_sec") in {None, ""} else float(raw.get("timeout_sec"))
            ),
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
