"""runtime.plugins.ops_control 提供最小本地运维命令插件.

组件关系:

    RuntimePluginManager
            |
            v
      OpsControlPlugin
            |
            v
      RuntimeControlPlane

目标:
- 把 control plane 能力暴露成可操作命令
- 先支持最小运维面
- 不在这里引入 WebUI 或复杂权限系统
"""

from __future__ import annotations

import shlex

from acabot.types import Action, ActionType

from ..control_plane import PluginReloadSnapshot
from ..models import PlannedAction, RunContext
from ..plugin_manager import RuntimeHook, RuntimeHookPoint, RuntimeHookResult, RuntimePlugin, RuntimePluginContext


# region hook
class OpsCommandHook(RuntimeHook):
    """在 PRE_AGENT 阶段拦截本地 ops 命令."""

    name = "ops_command"

    def __init__(self, plugin: OpsControlPlugin) -> None:
        """初始化 ops command hook.

        Args:
            plugin: 当前 hook 所属的插件实例.
        """

        self.plugin = plugin

    async def handle(self, ctx: RunContext) -> RuntimeHookResult:
        """尝试处理一次 ops 命令.

        Args:
            ctx: 当前 run 上下文.

        Returns:
            命中 ops 命令时返回 `skip_agent`, 否则继续主线.
        """

        reply_text = await self.plugin.handle_command(ctx)
        if reply_text is None:
            return RuntimeHookResult()
        ctx.actions = [self.plugin.build_reply_action(ctx, reply_text)]
        return RuntimeHookResult(action="skip_agent")


# endregion


class OpsControlPlugin(RuntimePlugin):
    """最小本地运维命令插件.

    Attributes:
        name (str): 插件名.
        _prefix (str): 命令前缀.
        _allowed_actor_ids (set[str]): 允许使用 ops 命令的 actor 白名单.
        _control_plane: 当前 runtime 的 control plane.
    """

    name = "ops_control"

    def __init__(self) -> None:
        """初始化插件状态."""

        self._prefix = "/"
        self._allowed_actor_ids: set[str] = set()
        self._control_plane = None

    async def setup(self, runtime: RuntimePluginContext) -> None:
        """读取配置并保存 control plane 引用.

        Args:
            runtime: runtime plugin 上下文.
        """

        config = runtime.get_plugin_config(self.name)
        self._prefix = str(config.get("prefix", "/") or "/")
        self._allowed_actor_ids = {
            str(actor_id)
            for actor_id in list(config.get("allowed_actor_ids", []) or [])
            if str(actor_id)
        }
        self._control_plane = runtime.control_plane

    def hooks(self) -> list[tuple[RuntimeHookPoint, RuntimeHook]]:
        """返回 ops 插件需要注册的 hooks.

        Returns:
            一条 PRE_AGENT hook.
        """

        return [(RuntimeHookPoint.PRE_AGENT, OpsCommandHook(self))]

    async def handle_command(self, ctx: RunContext) -> str | None:
        """尝试把当前消息当作 ops 命令处理.

        Args:
            ctx: 当前 run 上下文.

        Returns:
            命中并处理时返回回复文本. 非 ops 命令时返回 None.
        """

        if not self._should_handle(ctx):
            return None
        if self._control_plane is None:
            return "ops control plane unavailable"

        try:
            parts = shlex.split(ctx.event.text.strip())
        except ValueError as exc:
            return f"invalid ops command: {exc}"
        if not parts:
            return None

        command = parts[0][len(self._prefix):]
        arguments = parts[1:]

        if command == "status":
            status = await self._control_plane.get_status()
            return (
                f"active_runs={status.active_run_count}\n"
                f"pending_approvals={status.pending_approval_count}\n"
                f"loaded_plugins={','.join(status.loaded_plugins) or '-'}\n"
                f"loaded_skills={','.join(status.loaded_skills) or '-'}\n"
                f"interrupted_runs={','.join(status.interrupted_run_ids) or '-'}"
            )

        if command == "skills":
            if arguments:
                items = await self._control_plane.list_agent_skills(arguments[0])
                if not items:
                    return f"skills: no assignments for {arguments[0]}"
                lines = [f"skills for {arguments[0]}:"]
                for item in items:
                    tools = ",".join(item.tool_names) or "-"
                    lines.append(
                        f"- {item.skill_name} [{item.skill_type}] "
                        f"mode={item.delegation_mode} delegate={item.delegate_agent_id or '-'} "
                        f"tools={tools}"
                    )
                return "\n".join(lines)

            items = await self._control_plane.list_skills()
            if not items:
                return "skills: no registered skills"
            lines = ["skills:"]
            for item in items:
                tools = ",".join(item.tool_names) or "-"
                lines.append(
                    f"- {item.skill_name} [{item.skill_type}] tools={tools}"
                )
            return "\n".join(lines)

        if command == "reload_plugins":
            result = await self._control_plane.reload_plugins()
            return self._format_reload_result(result)

        if command == "reload_plugin":
            if not arguments:
                return "usage: /reload_plugin <plugin_name> [plugin_name2 ...]"
            result = await self._control_plane.reload_plugins(arguments)
            return self._format_reload_result(result)

        if command == "switch_agent":
            if not arguments:
                return "usage: /switch_agent <agent_id>"
            result = await self._control_plane.switch_thread_agent(
                thread_id=ctx.thread.thread_id,
                agent_id=arguments[0],
            )
            if result.ok:
                return f"thread agent switched to {result.agent_id}"
            return f"switch_agent failed: {result.message}"

        if command == "clear_agent":
            result = await self._control_plane.clear_thread_agent_override(
                thread_id=ctx.thread.thread_id,
            )
            if result.ok:
                return "thread agent override cleared"
            return f"clear_agent failed: {result.message}"

        if command == "memory" and arguments[:1] == ["show"]:
            if len(arguments) < 3:
                return "usage: /memory show <scope> <scope_key> [memory_type1,memory_type2]"
            memory_types = None
            if len(arguments) >= 4 and arguments[3].strip():
                memory_types = [item for item in arguments[3].split(",") if item]
            result = await self._control_plane.show_memory(
                scope=arguments[1],
                scope_key=arguments[2],
                memory_types=memory_types,
            )
            if not result.items:
                return f"memory: no items for {result.scope}:{result.scope_key}"
            return "\n".join(
                [
                    f"{item.memory_type}/{item.edit_mode}: {item.content}"
                    for item in result.items
                ]
            )

        return f"unknown ops command: {command}"

    def build_reply_action(self, ctx: RunContext, text: str) -> PlannedAction:
        """为 ops 命令构造一条纯文本回复.

        Args:
            ctx: 当前 run 上下文.
            text: 回复文本.

        Returns:
            一条 PlannedAction.
        """

        return PlannedAction(
            action_id=f"action:{ctx.run.run_id}:ops",
            action=Action(
                action_type=ActionType.SEND_TEXT,
                target=ctx.event.source,
                payload={"text": text},
            ),
            thread_content=text,
            metadata={"origin": "ops_control_plugin"},
        )

    def _should_handle(self, ctx: RunContext) -> bool:
        """判断当前消息是否应交给 ops 插件处理.

        Args:
            ctx: 当前 run 上下文.

        Returns:
            当前消息是否是允许处理的 ops 命令.
        """

        if not ctx.event.is_message:
            return False
        text = ctx.event.text.strip()
        if not text.startswith(self._prefix):
            return False
        if ctx.event.is_group and not ctx.event.targets_self:
            return False
        return ctx.run.actor_id in self._allowed_actor_ids

    @staticmethod
    def _format_reload_result(result: PluginReloadSnapshot) -> str:
        """格式化 plugin reload 结果.

        Args:
            result: control plane 返回的 PluginReloadSnapshot.

        Returns:
            可直接回给用户的纯文本.
        """

        lines = [f"reloaded_plugins={','.join(result.loaded_plugins) or '-'}"]
        if result.missing_plugins:
            lines.append(f"missing_plugins={','.join(result.missing_plugins)}")
        return "\n".join(lines)
