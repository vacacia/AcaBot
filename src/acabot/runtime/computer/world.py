"""runtime.computer.world 负责把 computer policy 变成真正的 Work World 视图.

这个模块和下面几层直接相连:

- `runtime.control.session_runtime` 负责算出 `ComputerPolicyDecision`
- `runtime.computer.workspace` 负责提供 thread workspace、skills 和 self 的宿主机目录
- `runtime.computer.runtime` 后续会把这里构造出的 `WorldView` 放进 `RunContext`
- file tools、shell、attachment staging 后续都会通过 `WorldView.resolve()` 使用统一路径语义

这里不直接做文件读写, 也不直接启动 backend. 它只负责把 `/workspace /skills /self` 这套世界收成稳定的路径解析对象.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .contracts import (
    ComputerPolicyDecision,
    ExecutionView,
    ResolvedWorldPath,
    WorldInputBundle,
    WorldRootPolicy,
    WorldView,
)
from .workspace import WorkspaceManager


# region view implementation
@dataclass(slots=True)
class _WorldViewImpl(WorldView):
    """Work World 视图的最小实现.

    Attributes:
        thread_id (str): 当前 thread ID.
        actor_kind (str): 当前 actor 的 world 身份.
        profile_id (str): 当前 profile ID.
        root_policies (dict[str, WorldRootPolicy]): 当前可见 roots 的权限表.
        workspace_root_host_path (str): `/workspace` 对应的宿主机目录.
        skills_root_host_path (str): `/skills` 对应的宿主机目录.
        self_root_host_path (str): `/self` 对应的宿主机目录.
        visible_skill_names (list[str]): 当前 actor 真正可见的 skill 名.
        execution_view (ExecutionView): shell 看到的执行视图.
    """

    thread_id: str
    actor_kind: str
    profile_id: str
    root_policies: dict[str, WorldRootPolicy]
    workspace_root_host_path: str
    skills_root_host_path: str
    self_root_host_path: str
    visible_skill_names: list[str]
    execution_view: ExecutionView

    def resolve(self, world_path: str) -> ResolvedWorldPath:
        """把 world path 解析成宿主机路径和执行视图路径.

        Args:
            world_path (str): 模型侧使用的 world path.

        Returns:
            ResolvedWorldPath: 解析后的正式路径对象.

        Raises:
            ValueError: 路径格式非法时抛出.
            FileNotFoundError: 路径落在当前 actor 不可见的 root 上时抛出.
        """

        normalized = self._normalize_world_path(world_path)
        root_kind, relative_path = self._split_root(normalized)
        policy = self.root_policies.get(root_kind)
        if policy is None or not policy.visible:
            raise FileNotFoundError(f"world path not visible: {normalized}")
        if root_kind == "skills":
            self._assert_skill_visible(relative_path, normalized)
        root_host_path = self._root_host_path(root_kind)
        host_path = self._resolve_host_path(root_host_path, relative_path)
        if root_kind == "skills" and relative_path and not host_path.exists():
            raise FileNotFoundError(f"skill path not materialized in current world: {normalized}")
        return ResolvedWorldPath(
            world_path=normalized,
            root_kind=root_kind,
            relative_path=relative_path,
            host_path=str(host_path),
            execution_path=self._execution_path(root_kind, relative_path),
            visible=True,
            writable=policy.writable,
        )

    @staticmethod
    def _normalize_world_path(world_path: str) -> str:
        """把传入路径规范化成绝对 world path.

        Args:
            world_path (str): 原始 world path.

        Returns:
            str: 规范化后的绝对路径.

        Raises:
            ValueError: 路径为空或尝试越界时抛出.
        """

        raw = str(world_path or "").strip()
        if not raw:
            raise ValueError("world path is required")
        if not raw.startswith("/"):
            raw = f"/{raw}"
        parts = [part for part in raw.split("/") if part and part != "."]
        normalized_parts: list[str] = []
        for part in parts:
            if part == "..":
                raise ValueError("world path cannot escape root")
            normalized_parts.append(part)
        return "/" + "/".join(normalized_parts)

    @staticmethod
    def _split_root(world_path: str) -> tuple[str, str]:
        """拆出 root kind 和 root 内相对路径.

        Args:
            world_path (str): 规范化后的 world path.

        Returns:
            tuple[str, str]: `(root_kind, relative_path)`.

        Raises:
            ValueError: 路径不在支持的 roots 下时抛出.
        """

        parts = [part for part in world_path.split("/") if part]
        if not parts:
            raise ValueError("world path must include a root")
        root_kind = parts[0]
        if root_kind not in {"workspace", "skills", "self"}:
            raise ValueError(f"unknown world root: {root_kind}")
        relative_path = "/".join(parts[1:])
        return root_kind, relative_path

    def _root_host_path(self, root_kind: str) -> Path:
        """返回指定 root 的宿主机根目录.

        Args:
            root_kind (str): root 名字.

        Returns:
            Path: 对应的宿主机根目录.
        """

        if root_kind == "workspace":
            return Path(self.workspace_root_host_path)
        if root_kind == "skills":
            return Path(self.skills_root_host_path)
        return Path(self.self_root_host_path)

    def _assert_skill_visible(self, relative_path: str, world_path: str) -> None:
        """检查 `/skills/...` 下访问的 skill 是否真的可见.

        Args:
            relative_path (str): `/skills` 根内的相对路径.
            world_path (str): 原始 world path, 用于报错信息.

        Raises:
            FileNotFoundError: 目标 skill 不在当前可见列表里时抛出.
        """

        if not relative_path:
            return
        skill_name = relative_path.split("/", 1)[0]
        if skill_name not in self.visible_skill_names:
            raise FileNotFoundError(f"skill not visible in current world: {world_path}")

    def _execution_path(self, root_kind: str, relative_path: str) -> str:
        """根据当前 execution view 计算 shell 侧路径.

        Args:
            root_kind (str): 命中的 root 名字.
            relative_path (str): root 内相对路径.

        Returns:
            str: shell 侧路径. 当前 shell 不可见时返回空字符串.
        """

        if root_kind == "workspace":
            root_path = self.execution_view.workspace_path
        elif root_kind == "skills":
            root_path = self.execution_view.skills_path
        else:
            root_path = self.execution_view.self_path
        if not root_path:
            return ""
        if not relative_path:
            return root_path
        return str(Path(root_path) / relative_path)

    @staticmethod
    def _resolve_host_path(root_host_path: Path, relative_path: str) -> Path:
        """在 root 之下拼出安全宿主机路径.

        Args:
            root_host_path (Path): 当前 root 的宿主机根目录.
            relative_path (str): root 内相对路径.

        Returns:
            Path: 安全解析后的宿主机路径.

        Raises:
            ValueError: 路径越界时抛出.
        """

        target = (root_host_path / relative_path).resolve()
        root = root_host_path.resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("world path escapes root") from exc
        return target


# endregion


# region builder
class WorkWorldBuilder:
    """根据 world input bundle 构造 `WorldView`.

    Attributes:
        workspace_manager (WorkspaceManager): 提供宿主机目录布局的管理器.
    """

    def __init__(self, workspace_manager: WorkspaceManager) -> None:
        """初始化 builder.

        Args:
            workspace_manager (WorkspaceManager): 提供宿主机目录布局的管理器.
        """

        self.workspace_manager = workspace_manager

    def build(self, bundle: WorldInputBundle) -> WorldView:
        """构造当前 run 使用的 Work World 视图.

        Args:
            bundle (WorldInputBundle): 当前 run 的稳定 world 输入.

        Returns:
            WorldView: 可供 file tools 和 shell 使用的世界视图.
        """

        visible_skill_names = self._visible_skill_names(bundle)
        workspace_root = self.workspace_manager.ensure_workspace_layout(bundle.thread_id)
        skills_root = self.workspace_manager.ensure_skills_view(
            bundle.thread_id,
            self._skills_view_key(bundle, visible_skill_names),
            visible_skill_names,
        )
        self_root = self.workspace_manager.ensure_self_layout(bundle.self_scope_id)
        root_policies = self._root_policies(bundle.computer_policy)
        execution_view = self._execution_view(
            backend=bundle.computer_policy.backend,
            root_policies=root_policies,
            workspace_root=workspace_root,
            skills_root=skills_root,
            self_root=self_root,
        )
        return _WorldViewImpl(
            thread_id=bundle.thread_id,
            actor_kind=bundle.actor_kind,
            profile_id=bundle.profile_id,
            root_policies=root_policies,
            workspace_root_host_path=str(workspace_root),
            skills_root_host_path=str(skills_root),
            self_root_host_path=str(self_root),
            visible_skill_names=visible_skill_names,
            execution_view=execution_view,
        )

    @staticmethod
    def _root_policies(policy: ComputerPolicyDecision) -> dict[str, WorldRootPolicy]:
        """把 computer roots 配置转成正式 root policy.

        Args:
            policy (ComputerPolicyDecision): 当前 run 的 computer policy.

        Returns:
            dict[str, WorldRootPolicy]: 各个 world root 的权限表.
        """

        root_policies: dict[str, WorldRootPolicy] = {}
        for root_kind in ("workspace", "skills", "self"):
            raw = dict(policy.roots.get(root_kind, {}) or {})
            root_policies[root_kind] = WorldRootPolicy(
                root_kind=root_kind,
                visible=bool(raw.get("visible", False)),
                writable=bool(raw.get("writable", False)),
            )
        return root_policies

    @staticmethod
    def _visible_skill_names(bundle: WorldInputBundle) -> list[str]:
        """收口当前 world 真正可见的 skill 列表.

        Args:
            bundle (WorldInputBundle): 当前 world 输入.

        Returns:
            list[str]: 去重并排序后的可见 skill 名列表.
        """

        if bundle.visible_skill_names is None:
            names = list(bundle.computer_policy.visible_skills)
        else:
            names = list(bundle.visible_skill_names)
        return sorted({name for name in names if name})

    @staticmethod
    def _skills_view_key(bundle: WorldInputBundle, visible_skill_names: list[str]) -> str:
        """生成 skills 视图目录使用的稳定键.

        Args:
            bundle (WorldInputBundle): 当前 world 输入.
            visible_skill_names (list[str]): 当前可见 skill 名列表.

        Returns:
            str: skills 视图目录的稳定键.
        """

        joined = ",".join(visible_skill_names)
        return f"{bundle.actor_kind}:{bundle.profile_id}:{joined}"

    @staticmethod
    def _execution_view(
        *,
        backend: str,
        root_policies: dict[str, WorldRootPolicy],
        workspace_root: Path,
        skills_root: Path,
        self_root: Path,
    ) -> ExecutionView:
        """根据 backend 和 root policy 生成当前 shell 看到的执行视图.

        Args:
            backend (str): 当前 backend 名字.
            root_policies (dict[str, WorldRootPolicy]): 当前 roots 的权限表.
            workspace_root (Path): workspace 宿主机根目录.
            skills_root (Path): skills 宿主机根目录.
            self_root (Path): self 宿主机根目录.

        Returns:
            ExecutionView: 当前 shell 侧真实可见的视图摘要.
        """

        if backend == "docker":
            return ExecutionView(
                workspace_path="/workspace" if root_policies["workspace"].visible else "",
                skills_path="",
                self_path="",
                backend=backend,
            )
        return ExecutionView(
            workspace_path=str(workspace_root) if root_policies["workspace"].visible else "",
            skills_path=str(skills_root) if root_policies["skills"].visible else "",
            self_path=str(self_root) if root_policies["self"].visible else "",
            backend=backend,
        )


# endregion


__all__ = ["WorkWorldBuilder", "WorldInputBundle"]
