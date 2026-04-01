"""runtime.model_resolution 提供共享的 run 级模型解析 helper."""

from __future__ import annotations

from .model_registry import (
    FileSystemModelRegistryManager,
    PersistedModelSnapshot,
    RuntimeModelRequest,
    snapshot_from_runtime_request,
)
from ..contracts import ResolvedAgent, RouteDecision


def resolve_run_request_for_agent(
    manager: FileSystemModelRegistryManager | None,
    *,
    run_mode: str,
    agent_id: str,
) -> tuple[RuntimeModelRequest | None, PersistedModelSnapshot | None]:
    """按 agent target 解析当前 run 的模型请求.

    Args:
        manager: 模型注册表管理器.
        run_mode: 当前 run mode.
        agent_id: 当前 agent ID.

    Returns:
        `(model_request, model_snapshot)` 二元组.
    """

    if manager is None:
        return None, None
    if run_mode == "record_only":
        return None, None
    request = manager.resolve_target_request(f"agent:{agent_id}")
    if request is None:
        return None, None
    return request, snapshot_from_runtime_request(request)


def resolve_model_requests_for_agent(
    manager: FileSystemModelRegistryManager | None,
    *,
    decision: RouteDecision,
    agent: ResolvedAgent,
) -> tuple[
    RuntimeModelRequest | None,
    PersistedModelSnapshot | None,
    RuntimeModelRequest | None,
]:
    """为当前 agent 快照解析本次 run 与 summary 的模型请求配置.

    summary_model_request 直接等于 model_request(压缩用主模型).
    """

    if manager is None:
        return None, None, None

    model_target = str(agent.config.get("model_target", "") or "").strip()
    if decision.run_mode == "record_only":
        model_request = None
        model_snapshot = None
    elif model_target:
        model_request = manager.resolve_target_request(model_target)
        model_snapshot = (
            snapshot_from_runtime_request(model_request)
            if model_request is not None
            else None
        )
    else:
        model_request, model_snapshot = resolve_run_request_for_agent(
            manager,
            run_mode=decision.run_mode,
            agent_id=agent.agent_id,
        )
    # 压缩直接用主模型, 不再查独立 target
    summary_model_request = model_request
    return model_request, model_snapshot, summary_model_request


def resolve_image_caption_request_for_agent(
    manager: FileSystemModelRegistryManager | None,
    *,
    agent: ResolvedAgent,
    primary_request: RuntimeModelRequest | None,
) -> RuntimeModelRequest | None:
    """为图片转述解析模型请求.

    优先查 agent:{agent_id}:image_caption 绑定;
    没有绑定时回退到主模型 primary_request(需要多模态能力才生效).
    """

    if manager is not None:
        agent_caption = manager.resolve_target_request(
            f"agent:{agent.agent_id}:image_caption"
        )
        if agent_caption is not None:
            return agent_caption
    return primary_request
