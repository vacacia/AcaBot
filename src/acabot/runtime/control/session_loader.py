"""runtime.control.session_loader 负责把会话配置来源读成运行时对象.

这个模块现在只支持文件系统来源:

- `SessionConfigLoader`: 从 `sessions/<platform>/<scope>/<id>/session.yaml` 读取正式会话配置
- `StaticSessionConfigLoader`: 用于测试等场景的静态内存 loader

输出的都是同一套 `SessionConfig` / `SurfaceConfig` / `MatchSpec` 契约.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

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


def _validate_session_id_part(part: str, *, session_id: str) -> str:
    """校验单段 session_id 片段，避免路径穿越和歧义值."""
    normalized = str(part or "").strip()
    if not normalized:
        raise ValueError(f"invalid session_id: {session_id}")
    if normalized in {".", ".."}:
        raise ValueError(f"invalid session_id: {session_id}")
    if "/" in normalized or "\\" in normalized or "\x00" in normalized:
        raise ValueError(f"invalid session_id: {session_id}")
    return normalized


def _require_mapping(raw: object, *, label: str, path: Path) -> dict[str, Any]:
    """确保 raw 是一个 dict，否则报错。None/{} 均返回空 dict。"""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    raise ValueError(f"{label} must be a mapping, got {type(raw).__name__}: {path}")


def _require_list(raw: object, *, label: str, path: Path) -> list[Any]:
    """确保 raw 是一个 list，否则报错。None/[] 均返回空 list。"""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    raise ValueError(f"{label} must be a list, got {type(raw).__name__}: {path}")


def _require_string_list(raw: object, *, label: str, path: Path) -> list[str]:
    """确保 raw 是一个字符串列表。"""
    items = _require_list(raw, label=label, path=path)
    return [str(item) for item in items]


def _reject_routing_agent_override(payload: dict[str, Any], *, label: str, path: Path) -> None:
    """不允许在 surface 级别覆盖 routing agent_id。"""
    if payload.get("agent_id"):
        raise ValueError(f"routing agent_id override is not supported in {label}: {path}")


def _optional_str(value: object) -> str | None:
    """转换为可选字符串。"""
    if value is None or value == "":
        return None
    return str(value)


def _optional_bool(value: object) -> bool | None:
    """转换为可选布尔值。"""
    if value is None:
        return None
    return bool(value)


class SessionConfigLoader:
    """从文件系统加载会话级配置."""

    def __init__(self, *, config_root: str | Path) -> None:
        """初始化 loader.

        Args:
            config_root: `sessions/` 根目录.
        """

        self.config_root = Path(config_root)

    def path_for_session_id(self, session_id: str) -> Path:
        """根据 `session_id` 计算 `session.yaml` 路径.

        Args:
            session_id: 会话 ID, 例如 `qq:group:123456`.

        Returns:
            Path: 当前会话目录里的 `session.yaml` 路径.
        """

        platform, scope_kind, identifier = self._split_session_id(session_id)
        return self.config_root / platform / scope_kind / identifier / "session.yaml"

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
        if not isinstance(raw, dict):
            raise ValueError(f"Session config file must be a mapping: {path}")
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
        platform, scope_kind, identifier = parts
        return (
            _validate_session_id_part(platform, session_id=session_id),
            _validate_session_id_part(scope_kind, session_id=session_id),
            _validate_session_id_part(identifier, session_id=session_id),
        )

    def _parse_session_config(self, raw: dict[str, Any], *, path: Path, session_id: str) -> SessionConfig:
        """把原始 YAML 数据解析成 `SessionConfig`.

        Args:
            raw: 读出来的原始 YAML 数据.
            path: 配置文件路径.
            session_id: 当前定位使用的 session_id.

        Returns:
            SessionConfig: 规范化后的会话配置对象.
        """

        session_block = _require_mapping(raw.get("session", {}), label="session", path=path)
        frontstage_block = _require_mapping(raw.get("frontstage", {}), label="frontstage", path=path)
        selectors = {
            selector_id: self._parse_match_spec(
                selector_conf,
                label=f"selectors.{selector_id}",
                path=path,
            )
            for selector_id, selector_conf in _require_mapping(raw.get("selectors", {}), label="selectors", path=path).items()
        }
        surfaces = {
            surface_id: self._parse_surface_config(
                surface_conf,
                label=f"surfaces.{surface_id}",
                path=path,
            )
            for surface_id, surface_conf in _require_mapping(raw.get("surfaces", {}), label="surfaces", path=path).items()
        }
        frontstage_agent_id = str(frontstage_block.get("agent_id", "") or "").strip()
        if not frontstage_agent_id:
            raise ValueError(f"frontstage.agent_id is required: {path}")
        declared_session_id = str(session_block.get("id", session_id) or session_id)
        if declared_session_id != session_id:
            raise ValueError(f"session.id does not match requested session_id: {path}")
        context_block = _require_mapping(raw.get("context", {}), label="context", path=path)
        context_strategy = str(context_block.get("strategy", "truncate") or "truncate")
        if context_strategy not in ("truncate", "summarize"):
            context_strategy = "truncate"
        context_preserve_recent = int(context_block.get("preserve_recent", 12) or 12)
        return SessionConfig(
            session_id=declared_session_id,
            template_id=str(session_block.get("template", "") or ""),
            title=str(session_block.get("title", "") or ""),
            frontstage_agent_id=frontstage_agent_id,
            selectors=selectors,
            surfaces=surfaces,
            context_strategy=context_strategy,
            context_preserve_recent=max(1, context_preserve_recent),
            metadata={"config_path": str(path)},
        )

    def _parse_surface_config(self, raw: object, *, label: str, path: Path) -> SurfaceConfig:
        """解析一个 surface 配置块.

        Args:
            raw: surface 对应的原始 YAML 片段.

        Returns:
            SurfaceConfig: 规范化后的 surface 配置.
        """

        mapping = _require_mapping(raw, label=label, path=path)
        return SurfaceConfig(
            routing=self._parse_domain_config(mapping.get("routing"), RoutingDomainConfig, label=f"{label}.routing", path=path),
            admission=self._parse_domain_config(
                mapping.get("admission"),
                AdmissionDomainConfig,
                label=f"{label}.admission",
                path=path,
            ),
            context=self._parse_domain_config(mapping.get("context"), ContextDomainConfig, label=f"{label}.context", path=path),
            persistence=self._parse_domain_config(
                mapping.get("persistence"),
                PersistenceDomainConfig,
                label=f"{label}.persistence",
                path=path,
            ),
            extraction=self._parse_domain_config(
                mapping.get("extraction"),
                ExtractionDomainConfig,
                label=f"{label}.extraction",
                path=path,
            ),
            computer=self._parse_domain_config(mapping.get("computer"), ComputerDomainConfig, label=f"{label}.computer", path=path),
        )

    def _parse_domain_config(self, raw: object, config_type: type, *, label: str, path: Path) -> object | None:
        """解析某个决策域的 `default + cases`.

        Args:
            raw: 当前决策域的原始 YAML 片段.
            config_type: 目标 domain config 类型.

        Returns:
            object | None: 当前域为空时返回 `None`, 否则返回对应 domain config 对象.
        """

        if raw in (None, ""):
            return None
        mapping = _require_mapping(raw, label=label, path=path)
        default_payload = _require_mapping(mapping.get("default", {}), label=f"{label}.default", path=path)
        if config_type is RoutingDomainConfig:
            _reject_routing_agent_override(default_payload, label=f"{label}.default", path=path)
        return config_type(
            default=default_payload,
            cases=[
                self._parse_case(
                    item,
                    label=f"{label}.cases[{index}]",
                    path=path,
                    for_routing=(config_type is RoutingDomainConfig),
                )
                for index, item in enumerate(_require_list(mapping.get("cases", []), label=f"{label}.cases", path=path))
            ],
        )

    def _parse_case(
        self,
        raw: object,
        *,
        label: str,
        path: Path,
        for_routing: bool = False,
    ) -> DomainCase:
        """解析单条局部 case.

        Args:
            raw: 原始 case 配置.

        Returns:
            DomainCase: 规范化后的 case 对象.
        """

        mapping = _require_mapping(raw, label=label, path=path)
        when_conf = mapping.get("when")
        when = (
            self._parse_match_spec(when_conf, label=f"{label}.when", path=path)
            if when_conf not in (None, "")
            else None
        )
        use_payload = _require_mapping(mapping.get("use", {}), label=f"{label}.use", path=path)
        if for_routing:
            _reject_routing_agent_override(use_payload, label=f"{label}.use", path=path)
        return DomainCase(
            case_id=str(mapping.get("case_id", "") or ""),
            when=when,
            when_ref=str(mapping.get("when_ref", "") or ""),
            use=use_payload,
            priority=int(mapping.get("priority", 100)),
            metadata=_require_mapping(mapping.get("metadata", {}), label=f"{label}.metadata", path=path),
        )

    @staticmethod
    def _parse_match_spec(raw: object, *, label: str, path: Path) -> MatchSpec:
        """解析 `MatchSpec`.

        Args:
            raw: 原始匹配条件配置.

        Returns:
            MatchSpec: 规范化后的匹配条件对象.
        """

        mapping = _require_mapping(raw, label=label, path=path)
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
            is_bot_admin=_optional_bool(mapping.get("is_bot_admin")),
            sender_roles=_require_string_list(mapping.get("sender_roles", []), label=f"{label}.sender_roles", path=path),
            attachments_present=_optional_bool(mapping.get("attachments_present")),
            attachment_kinds=_require_string_list(
                mapping.get("attachment_kinds", []),
                label=f"{label}.attachment_kinds",
                path=path,
            ),
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


__all__ = [
    "SessionConfigLoader",
    "StaticSessionConfigLoader",
]
