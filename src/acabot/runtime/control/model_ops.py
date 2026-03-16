"""RuntimeControlPlane 的模型管理子模块."""

from __future__ import annotations

from ..model.model_registry import (
    EffectiveModelSnapshot,
    FileSystemModelRegistryManager,
    ModelBinding,
    ModelHealthCheckResult,
    ModelImpactSnapshot,
    ModelMutationResult,
    ModelProvider,
    ModelPreset,
    ModelRegistryStatusSnapshot,
    ModelReloadSnapshot,
)
from .profile_loader import AgentProfileRegistry


class RuntimeModelControlOps:
    """封装 RuntimeControlPlane 的模型管理能力."""

    def __init__(
        self,
        *,
        model_registry_manager: FileSystemModelRegistryManager | None,
        profile_registry: AgentProfileRegistry | None,
    ) -> None:
        self.model_registry_manager = model_registry_manager
        self.profile_registry = profile_registry

    async def list_model_providers(self) -> list[ModelProvider]:
        if self.model_registry_manager is None:
            return []
        return self.model_registry_manager.list_providers()

    async def list_model_presets(self) -> list[ModelPreset]:
        if self.model_registry_manager is None:
            return []
        return self.model_registry_manager.list_presets()

    async def list_model_bindings(self) -> list[ModelBinding]:
        if self.model_registry_manager is None:
            return []
        return self.model_registry_manager.list_bindings()

    async def get_model_provider(self, provider_id: str) -> ModelProvider | None:
        if self.model_registry_manager is None:
            return None
        return self.model_registry_manager.get_provider(provider_id)

    async def get_model_preset(self, preset_id: str) -> ModelPreset | None:
        if self.model_registry_manager is None:
            return None
        return self.model_registry_manager.get_preset(preset_id)

    async def get_model_binding(self, binding_id: str) -> ModelBinding | None:
        if self.model_registry_manager is None:
            return None
        return self.model_registry_manager.get_binding(binding_id)

    async def get_model_provider_impact(self, provider_id: str) -> ModelImpactSnapshot:
        if self.model_registry_manager is None:
            return ModelImpactSnapshot(entity_type="provider", entity_id=provider_id)
        return self.model_registry_manager.get_provider_impact(provider_id)

    async def get_model_preset_impact(self, preset_id: str) -> ModelImpactSnapshot:
        if self.model_registry_manager is None:
            return ModelImpactSnapshot(entity_type="preset", entity_id=preset_id)
        return self.model_registry_manager.get_preset_impact(preset_id)

    async def get_model_binding_impact(self, binding_id: str) -> ModelImpactSnapshot:
        if self.model_registry_manager is None:
            return ModelImpactSnapshot(entity_type="binding", entity_id=binding_id)
        return self.model_registry_manager.get_binding_impact(binding_id)

    async def preview_effective_agent_model(self, agent_id: str) -> EffectiveModelSnapshot:
        if self.model_registry_manager is None:
            return EffectiveModelSnapshot(target_type="agent", target_id=agent_id, source="none")
        explicit = ""
        effective = ""
        if self.profile_registry is not None and self.profile_registry.has_agent(agent_id):
            profile = self.profile_registry.profiles[agent_id]
            explicit = str(profile.config.get("default_model", "") or "")
            effective = str(profile.default_model or "")
        return self.model_registry_manager.preview_effective_agent(
            agent_id=agent_id,
            explicit_profile_default_model=explicit,
            effective_profile_default_model=effective,
        )

    async def preview_effective_summary_model(self) -> EffectiveModelSnapshot:
        if self.model_registry_manager is None:
            return EffectiveModelSnapshot(
                target_type="system",
                target_id="compactor_summary",
                source="none",
            )
        return self.model_registry_manager.preview_effective_summary()

    async def upsert_model_provider(self, provider: ModelProvider) -> ModelMutationResult:
        if self.model_registry_manager is None:
            return ModelMutationResult(
                ok=False,
                applied=False,
                action="upsert",
                entity_type="provider",
                entity_id=provider.provider_id,
                message="model registry unavailable",
            )
        return await self.model_registry_manager.upsert_provider(provider)

    async def upsert_model_preset(self, preset: ModelPreset) -> ModelMutationResult:
        if self.model_registry_manager is None:
            return ModelMutationResult(
                ok=False,
                applied=False,
                action="upsert",
                entity_type="preset",
                entity_id=preset.preset_id,
                message="model registry unavailable",
            )
        return await self.model_registry_manager.upsert_preset(preset)

    async def upsert_model_binding(self, binding: ModelBinding) -> ModelMutationResult:
        if self.model_registry_manager is None:
            return ModelMutationResult(
                ok=False,
                applied=False,
                action="upsert",
                entity_type="binding",
                entity_id=binding.binding_id,
                message="model registry unavailable",
            )
        return await self.model_registry_manager.upsert_binding(binding)

    async def delete_model_provider(self, provider_id: str, *, force: bool = False) -> ModelMutationResult:
        if self.model_registry_manager is None:
            return ModelMutationResult(
                ok=False,
                applied=False,
                action="delete",
                entity_type="provider",
                entity_id=provider_id,
                message="model registry unavailable",
            )
        return await self.model_registry_manager.delete_provider(provider_id, force=force)

    async def delete_model_preset(self, preset_id: str, *, force: bool = False) -> ModelMutationResult:
        if self.model_registry_manager is None:
            return ModelMutationResult(
                ok=False,
                applied=False,
                action="delete",
                entity_type="preset",
                entity_id=preset_id,
                message="model registry unavailable",
            )
        return await self.model_registry_manager.delete_preset(preset_id, force=force)

    async def delete_model_binding(self, binding_id: str) -> ModelMutationResult:
        if self.model_registry_manager is None:
            return ModelMutationResult(
                ok=False,
                applied=False,
                action="delete",
                entity_type="binding",
                entity_id=binding_id,
                message="model registry unavailable",
            )
        return await self.model_registry_manager.delete_binding(binding_id)

    async def health_check_model_preset(self, preset_id: str) -> ModelHealthCheckResult:
        if self.model_registry_manager is None:
            return ModelHealthCheckResult(
                ok=False,
                provider_id="",
                preset_id=preset_id,
                model="",
                message="model registry unavailable",
            )
        return await self.model_registry_manager.health_check(preset_id=preset_id)

    async def reload_models(self) -> ModelReloadSnapshot:
        if self.model_registry_manager is None:
            return ModelReloadSnapshot(ok=False, error="model registry unavailable")
        return await self.model_registry_manager.reload()

    async def get_model_registry_status(self) -> ModelRegistryStatusSnapshot:
        if self.model_registry_manager is None:
            return ModelRegistryStatusSnapshot(last_error="model registry unavailable")
        return self.model_registry_manager.status()
