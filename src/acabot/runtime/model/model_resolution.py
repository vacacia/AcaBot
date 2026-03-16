"""runtime.model_resolution 提供共享的 run 级模型解析 helper."""

from __future__ import annotations

from .model_registry import (
    FileSystemModelRegistryManager,
    PersistedModelSnapshot,
    RuntimeModelRequest,
)
from ..contracts import AgentProfile, RouteDecision


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


def resolve_image_caption_request_for_profile(
    manager: FileSystemModelRegistryManager | None,
    *,
    profile: AgentProfile,
    primary_request: RuntimeModelRequest | None,
) -> RuntimeModelRequest | None:
    """为图片转述解析一份独立的模型请求.

    解析顺序:
    1. `profile.config.image_caption.caption_preset_id`
    2. 当前 run 已解析好的 primary_request
    3. 按 profile 的主模型绑定重新解析一份 respond request
    """

    if manager is None:
        return primary_request

    image_caption_conf = dict(profile.config.get("image_caption", {}) or {})
    caption_preset_id = str(image_caption_conf.get("caption_preset_id", "") or "")
    if caption_preset_id:
        request = manager.resolve_preset_request(caption_preset_id)
        if request is not None:
            request.binding_id = "profile:image_caption_preset"
            return request

    if primary_request is not None:
        return primary_request

    fallback_request, _ = manager.resolve_run_request(
        run_mode="respond",
        agent_id=profile.agent_id,
        explicit_profile_default_model=str(profile.config.get("default_model", "") or ""),
        effective_profile_default_model=profile.default_model,
    )
    return fallback_request
