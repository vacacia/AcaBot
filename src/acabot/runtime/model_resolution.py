"""runtime.model_resolution 提供共享的 run 级模型解析 helper."""

from __future__ import annotations

from .model_registry import (
    FileSystemModelRegistryManager,
    PersistedModelSnapshot,
    RuntimeModelRequest,
)
from .models import AgentProfile, RouteDecision


def resolve_model_requests_for_profile(
    manager: FileSystemModelRegistryManager | None,
    *,
    decision: RouteDecision,
    profile: AgentProfile,
) -> tuple[
    RuntimeModelRequest | None,
    PersistedModelSnapshot | None,
    RuntimeModelRequest | None,
]:
    """为当前 profile 解析本次 run 与 summary 的模型请求配置."""

    if manager is None:
        return None, None, None

    explicit_profile_default_model = str(profile.config.get("default_model", "") or "")
    model_request, model_snapshot = manager.resolve_run_request(
        run_mode=decision.run_mode,
        agent_id=profile.agent_id,
        explicit_profile_default_model=explicit_profile_default_model,
        effective_profile_default_model=profile.default_model,
    )
    summary_model_request = manager.resolve_summary_request(
        primary_request=model_request,
        profile_summary_preset_id=str(profile.config.get("summary_model_preset_id", "") or ""),
        profile_summary_model=str(profile.config.get("summary_model", "") or ""),
    )
    return model_request, model_snapshot, summary_model_request
