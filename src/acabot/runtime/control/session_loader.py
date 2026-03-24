"""runtime.control.session_loader 负责把会话配置来源读成运行时对象.

这个模块现在支持两类来源:

- `SessionConfigLoader`: 从 `sessions/**/*.yaml` 读取正式会话配置
- `ConfigBackedSessionConfigLoader`: 在纯内存配置场景下生成最小 SessionConfig

两者输出的都是同一套 `SessionConfig` / `SurfaceConfig` / `MatchSpec` 契约.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from acabot.config import Config

from ..contracts import (
    AdmissionDomainConfig,
    ComputerDomainConfig,
    ContextDomainConfig,
    DomainCase,
    ExtractionDomainConfig,
    MatchSpec,
    PersistenceDomainConfig,
    RoutingDomainConfig,
    SessionConfig,
    SurfaceConfig,
)


class SessionConfigLoader:
    """从文件系统加载会话级配置."""

    def __init__(self, *, config_root: str | Path) -> None:
        """初始化 loader.

        Args:
            config_root: `sessions/` 根目录.
        """

        self.config_root = Path(config_root)

    def path_for_session_id(self, session_id: str) -> Path:
        """根据 `session_id` 计算配置文件路径.

        Args:
            session_id: 会话 ID, 例如 `qq:group:123456`.

        Returns:
            Path: 当前会话应该落到的 YAML 文件路径.
        """

        platform, scope_kind, identifier = self._split_session_id(session_id)
        return self.config_root / platform / scope_kind / f"{identifier}.yaml"

    def load_by_session_id(self, session_id: str) -> SessionConfig:
        """按 `session_id` 读取并解析一份会话配置.

        Args:
            session_id: 目标会话 ID.

        Returns:
            SessionConfig: 解析后的会话配置对象.

        Raises:
            FileNotFoundError: 找不到对应配置文件时抛出.
        """

        path = self.path_for_session_id(session_id)
        if not path.exists():
            raise FileNotFoundError(f"session config not found: {session_id}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return self._parse_session_config(raw, path=path, session_id=session_id)

    @staticmethod
    def _split_session_id(session_id: str) -> tuple[str, str, str]:
        """把 `session_id` 拆成平台、范围类型和标识.

        Args:
            session_id: 目标会话 ID.

        Returns:
            tuple[str, str, str]: `(platform, scope_kind, identifier)`.

        Raises:
            ValueError: 形状不是 `platform:scope:id` 时抛出.
        """

        parts = session_id.split(":", 2)
        if len(parts) != 3:
            raise ValueError(f"invalid session_id: {session_id}")
        return parts[0], parts[1], parts[2]

    def _parse_session_config(self, raw: dict[str, Any], *, path: Path, session_id: str) -> SessionConfig:
        """把原始 YAML 数据解析成 `SessionConfig`.

        Args:
            raw: 读出来的原始 YAML 数据.
            path: 配置文件路径.
            session_id: 当前定位使用的 session_id.

        Returns:
            SessionConfig: 规范化后的会话配置对象.
        """

        session_block = dict(raw.get("session", {}))
        frontstage_block = dict(raw.get("frontstage", {}))
        selectors = {
            selector_id: self._parse_match_spec(selector_conf)
            for selector_id, selector_conf in dict(raw.get("selectors", {})).items()
        }
        surfaces = {
            surface_id: self._parse_surface_config(surface_conf)
            for surface_id, surface_conf in dict(raw.get("surfaces", {})).items()
        }
        return SessionConfig(
            session_id=str(session_block.get("id", session_id) or session_id),
            template_id=str(session_block.get("template", "") or ""),
            title=str(session_block.get("title", "") or ""),
            frontstage_profile=str(frontstage_block.get("profile", "") or ""),
            selectors=selectors,
            surfaces=surfaces,
            metadata={"config_path": str(path)},
        )

    def _parse_surface_config(self, raw: object) -> SurfaceConfig:
        """解析一个 surface 配置块.

        Args:
            raw: surface 对应的原始 YAML 片段.

        Returns:
            SurfaceConfig: 规范化后的 surface 配置.
        """

        mapping = dict(raw or {})
        return SurfaceConfig(
            routing=self._parse_domain_config(mapping.get("routing"), RoutingDomainConfig),
            admission=self._parse_domain_config(mapping.get("admission"), AdmissionDomainConfig),
            context=self._parse_domain_config(mapping.get("context"), ContextDomainConfig),
            persistence=self._parse_domain_config(mapping.get("persistence"), PersistenceDomainConfig),
            extraction=self._parse_domain_config(mapping.get("extraction"), ExtractionDomainConfig),
            computer=self._parse_domain_config(mapping.get("computer"), ComputerDomainConfig),
        )

    def _parse_domain_config(self, raw: object, config_type: type) -> object | None:
        """解析某个决策域的 `default + cases`.

        Args:
            raw: 当前决策域的原始 YAML 片段.
            config_type: 目标 domain config 类型.

        Returns:
            object | None: 当前域为空时返回 `None`, 否则返回对应 domain config 对象.
        """

        if raw in (None, ""):
            return None
        mapping = dict(raw or {})
        return config_type(
            default=dict(mapping.get("default", {}) or {}),
            cases=[self._parse_case(item) for item in list(mapping.get("cases", []))],
        )

    def _parse_case(self, raw: object) -> DomainCase:
        """解析单条局部 case.

        Args:
            raw: 原始 case 配置.

        Returns:
            DomainCase: 规范化后的 case 对象.
        """

        mapping = dict(raw or {})
        when_conf = mapping.get("when")
        when = self._parse_match_spec(when_conf) if when_conf not in (None, "") else None
        return DomainCase(
            case_id=str(mapping.get("case_id", "") or ""),
            when=when,
            when_ref=str(mapping.get("when_ref", "") or ""),
            use=dict(mapping.get("use", {}) or {}),
            priority=int(mapping.get("priority", 100)),
            metadata=dict(mapping.get("metadata", {}) or {}),
        )

    @staticmethod
    def _parse_match_spec(raw: object) -> MatchSpec:
        """解析 `MatchSpec`.

        Args:
            raw: 原始匹配条件配置.

        Returns:
            MatchSpec: 规范化后的匹配条件对象.
        """

        mapping = dict(raw or {})
        return MatchSpec(
            platform=_optional_str(mapping.get("platform")),
            event_kind=_optional_str(mapping.get("event_kind")),
            scene=_optional_str(mapping.get("scene")),
            actor_id=_optional_str(mapping.get("actor_id")),
            channel_scope=_optional_str(mapping.get("channel_scope")),
            thread_id=_optional_str(mapping.get("thread_id")),
            targets_self=_optional_bool(mapping.get("targets_self")),
            mentions_self=_optional_bool(mapping.get("mentions_self")),
            reply_targets_self=_optional_bool(mapping.get("reply_targets_self")),
            mentioned_everyone=_optional_bool(mapping.get("mentioned_everyone")),
            sender_roles=[str(item) for item in list(mapping.get("sender_roles", []))],
            attachments_present=_optional_bool(mapping.get("attachments_present")),
            attachment_kinds=[str(item) for item in list(mapping.get("attachment_kinds", []))],
            message_subtype=_optional_str(mapping.get("message_subtype")),
            notice_type=_optional_str(mapping.get("notice_type")),
            notice_subtype=_optional_str(mapping.get("notice_subtype")),
        )


class StaticSessionConfigLoader:
    """把一份固定 SessionConfig 映射给任意 session_id 的 loader."""

    def __init__(self, session: SessionConfig) -> None:
        """初始化静态 session loader.

        Args:
            session: 基础 SessionConfig.
        """

        self.session = session

    def path_for_session_id(self, session_id: str) -> Path:
        """返回一个稳定的内存路径标识.

        Args:
            session_id: 目标会话 ID.

        Returns:
            Path: 内建配置的伪路径.
        """

        return Path(f"<inline-session:{session_id}>")

    def load_by_session_id(self, session_id: str) -> SessionConfig:
        """返回按 session_id 覆盖过 ID 的静态 SessionConfig.

        Args:
            session_id: 目标会话 ID.

        Returns:
            SessionConfig: 覆盖 session_id 后的配置对象.
        """

        return replace(
            self.session,
            session_id=session_id,
            metadata={
                **dict(self.session.metadata),
                "config_path": str(self.path_for_session_id(session_id)),
            },
        )


class ConfigBackedSessionConfigLoader(StaticSessionConfigLoader):
    """从 `Config` 生成最小 SessionConfig 的 loader.

    这个 loader 只服务于没有 `sessions/` 文件真源的纯内存配置场景.
    它输出的仍然是正式 `SessionConfig` 契约.
    """

    def __init__(self, config: Config) -> None:
        """初始化 config-backed session loader.

        Args:
            config: 当前 runtime 配置.
        """

        runtime_conf = dict(config.get("runtime", {}) or {})
        default_agent_id = str(runtime_conf.get("default_agent_id", "default") or "default")
        computer_conf = dict(runtime_conf.get("computer", {}) or {})
        computer_default = {
            "backend": str(computer_conf.get("backend", "host") or "host"),
            "allow_exec": bool(computer_conf.get("allow_exec", True)),
            "allow_sessions": bool(computer_conf.get("allow_sessions", True)),
        }
        session = SessionConfig(
            session_id="inline:default",
            template_id="inline_default",
            title="Inline Default Session",
            frontstage_profile=default_agent_id,
            selectors={},
            surfaces=_default_surfaces(default_agent_id, computer_default),
            metadata={"config_path": "<inline-session:default>"},
        )
        super().__init__(session)


def _default_surfaces(
    default_profile: str,
    computer_default: dict[str, Any],
) -> dict[str, SurfaceConfig]:
    """构造最小默认 surface 集合.

    Args:
        default_profile: 默认前台 profile.
        computer_default: 默认 computer 配置.

    Returns:
        dict[str, SurfaceConfig]: 内建最小 surface 集合.
    """

    def _surface(mode: str = "respond") -> SurfaceConfig:
        return SurfaceConfig(
            routing=RoutingDomainConfig(default={"profile": default_profile}),
            admission=AdmissionDomainConfig(default={"mode": mode}),
            context=ContextDomainConfig(default={}),
            persistence=PersistenceDomainConfig(default={"persist_event": True}),
            extraction=ExtractionDomainConfig(default={"tags": []}),
            computer=ComputerDomainConfig(default=dict(computer_default)),
        )

    return {
        "message.mention": _surface("respond"),
        "message.reply_to_bot": _surface("respond"),
        "message.command": _surface("respond"),
        "message.private": _surface("respond"),
        "message.plain": _surface("respond"),
        "notice.default": _surface("respond"),
    }


def _optional_str(value: object) -> str | None:
    """把可空值转成可选字符串.

    Args:
        value: 原始值.

    Returns:
        str | None: 空值返回 `None`, 否则返回字符串.
    """

    if value in (None, ""):
        return None
    return str(value)


def _optional_bool(value: object) -> bool | None:
    """把原始值转成可选布尔值.

    Args:
        value: 原始值.

    Returns:
        bool | None: 空值返回 `None`, 否则返回布尔值.
    """

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return bool(value)


__all__ = [
    "ConfigBackedSessionConfigLoader",
    "SessionConfigLoader",
    "StaticSessionConfigLoader",
]
