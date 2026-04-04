"""Helpers for structured notification sends and smoke workspace preparation."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from acabot.config import Config
from acabot.types import EventSource, MsgSegment, StandardEvent

from .bootstrap.config import resolve_runtime_path
from .computer import ComputerRuntimeConfig, WorkspaceManager, WorkspaceState
from .contracts import ResolvedAgent, RouteDecision, RunContext, RunRecord, ThreadState
from .ids import build_event_source_from_conversation_id, build_thread_id_from_conversation_id


async def prepare_notification_run_context(
    *,
    computer_runtime,
    conversation_id: str,
    gateway_self_id: str,
) -> RunContext:
    """Build and prepare a minimal notification run context.

    This follows the same world/workspace preparation logic as `ComputerRuntime.prepare_run_context()`,
    but avoids run-step persistence because notifications do not create a formal pipeline run record.
    """

    thread_id = build_thread_id_from_conversation_id(conversation_id)
    source = build_event_source_from_conversation_id(
        conversation_id,
        actor_user_id=gateway_self_id or "0",
    )
    now = int(time.time())
    ctx = RunContext(
        run=RunRecord(
            run_id=f"notify:{uuid.uuid4().hex}",
            thread_id=thread_id,
            actor_id=conversation_id,
            agent_id="system.notification",
            trigger_event_id=f"evt:{uuid.uuid4().hex}",
            status="running",
            started_at=now,
        ),
        event=StandardEvent(
            event_id=f"evt:{uuid.uuid4().hex}",
            event_type="message",
            platform="qq",
            timestamp=now,
            source=source,
            segments=[MsgSegment(type="text", data={"text": "notification"})],
            raw_message_id="notification",
            sender_nickname="system.notification",
            sender_role=None,
        ),
        decision=RouteDecision(
            thread_id=thread_id,
            actor_id=conversation_id,
            agent_id="system.notification",
            channel_scope=conversation_id,
        ),
        thread=ThreadState(thread_id=thread_id, channel_scope=conversation_id),
        agent=ResolvedAgent(
            agent_id="system.notification",
            name="system.notification",
            prompt_ref="prompt/default",
        ),
    )
    policy = computer_runtime.effective_policy_for_ctx(ctx)
    world_view = computer_runtime.build_world_view(ctx, policy=policy)
    workspace_dir = Path(world_view.workspace_root_host_path)
    backend = computer_runtime.backends[policy.backend]
    await backend.ensure_workspace(
        host_path=workspace_dir,
        visible_root=world_view.execution_view.workspace_path,
    )
    ctx.computer_policy_effective = policy
    ctx.computer_backend_kind = backend.kind
    ctx.world_view = world_view
    ctx.workspace_state = WorkspaceState(
        thread_id=ctx.thread.thread_id,
        agent_id=ctx.agent.agent_id,
        backend_kind=backend.kind,
        workspace_host_path=str(workspace_dir),
        workspace_visible_root="/workspace",
        available_tools=computer_runtime._available_tools(policy, world_view=world_view),
        attachment_count=0,
        mirrored_skill_names=computer_runtime.list_mirrored_skills(ctx.thread.thread_id),
        active_session_ids=computer_runtime.list_session_ids(ctx.thread.thread_id),
    )
    return ctx


def workspace_dir_for_conversation(config: Config, conversation_id: str) -> Path:
    """Return the formal workspace root for a conversation using runtime config."""

    runtime_conf = config.get("runtime", {})
    computer_conf = dict(runtime_conf.get("computer", {}) or {})
    root_dir = resolve_runtime_path(config, computer_conf.get("root_dir", "workspaces"))
    manager = WorkspaceManager(
        ComputerRuntimeConfig(
            root_dir=str(root_dir),
            host_skills_catalog_root_path=str((root_dir / "catalog" / "skills").resolve()),
        )
    )
    return manager.workspace_dir_for_thread(build_thread_id_from_conversation_id(conversation_id))


__all__ = [
    "prepare_notification_run_context",
    "workspace_dir_for_conversation",
]
