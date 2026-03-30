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


def resolve_summary_request(
    manager: FileSystemModelRegistryManager | None,
) -> RuntimeModelRequest | None:
    """解析 summary target 对应的模型请求."""

    if manager is None:
        return None
    return manager.resolve_target_request("system:compactor_summary")


def resolve_image_caption_request(
    manager: FileSystemModelRegistryManager | None,
) -> RuntimeModelRequest | None:
    """解析 image caption target 对应的模型请求."""

    if manager is None:
        return None
    return manager.resolve_target_request("system:image_caption")


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
    """为当前 agent 快照解析本次 run 与 summary 的模型请求配置."""

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
    summary_model_request = resolve_summary_request(manager)
    return model_request, model_snapshot, summary_model_request


def resolve_image_caption_request_for_agent(
    manager: FileSystemModelRegistryManager | None,
    *,
    agent: ResolvedAgent,
    primary_request: RuntimeModelRequest | None,
) -> RuntimeModelRequest | None:
    """为图片转述解析一份独立的模型请求.

    这里不再读取旧前台身份入口, 只认固定 system target。
    """

    _ = agent, primary_request
    return resolve_image_caption_request(manager)
