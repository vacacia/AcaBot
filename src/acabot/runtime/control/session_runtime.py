"""runtime.control.session_runtime 负责把事件事实映射成会话级决策.

这个模块站在 `StandardEvent` 和 `RuntimeRouter` 中间, 主要做这几件事:

- 把平台事件标准化成 `EventFacts`
- 定位当前消息对应的 `SessionConfig`
- 解析当前消息命中的 surface
- 从 surface 的各决策域里算出 routing / admission / persistence / extraction / computer 结果

它不直接操作文件系统, 也不直接构造 Work World. 它只把“上游消息”收成“稳定决策结果”, 给后面的 app / computer 使用.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from acabot.types import StandardEvent

from ..contracts import (
    AdmissionDecision,
    ComputerPolicyDecision,
    ContextDecision,
    DomainCase,
    DomainConfig,
    EventFacts,
    ExtractionDecision,
    MatchSpec,
    PersistenceDecision,
    RoutingDecision,
    SessionConfig,
    SessionLocatorResult,
    SurfaceConfig,
    SurfaceResolution,
)
from .session_loader import SessionConfigLoader


# region session runtime
class SessionRuntime:
    """会话配置驱动的决策运行时.

    Attributes:
        loader (SessionConfigLoader): 读取 session config 的 loader.
    """

    def __init__(self, loader: SessionConfigLoader) -> None:
        """初始化运行时.

        Args:
            loader (SessionConfigLoader): 会话配置 loader.
        """

        self.loader = loader

    def build_facts(self, event: StandardEvent) -> EventFacts:
        """把平台事件标准化成 `EventFacts`.

        Args:
            event (StandardEvent): 当前收到的标准事件.

        Returns:
            EventFacts: 供后续 matcher 和 session runtime 使用的事实对象.
        """

        sender_roles = [event.sender_role] if event.sender_role else []
        attachment_kinds = sorted({attachment.type for attachment in event.attachments if attachment.type})
        return EventFacts(
            platform=event.platform,
            event_kind=event.event_type,
            scene=self._derive_scene(event),
            actor_id=self.build_actor_id(event),
            channel_scope=self.build_channel_scope(event),
            thread_id=self.build_thread_id(event),
            targets_self=event.targets_self,
            mentions_self=event.mentions_self,
            reply_targets_self=event.reply_targets_self,
            mentioned_everyone=event.mentioned_everyone,
            sender_roles=sender_roles,
            attachments_present=bool(event.attachments),
            attachment_kinds=attachment_kinds,
            message_subtype=event.message_subtype or "",
            notice_type=event.notice_type or "",
            notice_subtype=event.notice_subtype or "",
            metadata={
                "text": event.text,
                "event_id": event.event_id,
            },
        )

    def locate_session(self, facts: EventFacts) -> SessionLocatorResult:
        """根据事实定位会话配置.

        Args:
            facts (EventFacts): 当前事件事实.

        Returns:
            SessionLocatorResult: 定位结果.
        """

        path = self.loader.path_for_session_id(facts.channel_scope)
        return SessionLocatorResult(
            session_id=facts.channel_scope,
            template_id="",
            config_path=str(path),
            channel_scope=facts.channel_scope,
            thread_id=facts.thread_id,
        )

    def load_session(self, facts: EventFacts) -> SessionConfig:
        """读取当前事实对应的会话配置.

        Args:
            facts (EventFacts): 当前事件事实.

        Returns:
            SessionConfig: 解析后的会话配置.
        """

        locator = self.locate_session(facts)
        session = self.loader.load_by_session_id(locator.session_id)
        return replace(
            session,
            metadata={
                **dict(session.metadata),
                "locator_config_path": locator.config_path,
            },
        )

    def resolve_surface(self, facts: EventFacts, session: SessionConfig) -> SurfaceResolution:
        """解析当前消息命中的 surface.

        Args:
            facts (EventFacts): 当前事件事实.
            session (SessionConfig): 当前会话配置.

        Returns:
            SurfaceResolution: 当前消息命中的 surface 信息.
        """

        for candidate in self._surface_candidates(facts):
            if candidate in session.surfaces:
                return SurfaceResolution(
                    surface_id=candidate,
                    exists=True,
                    source="facts",
                    metadata={"candidate_chain": self._surface_candidates(facts)},
                )
        fallback = self._surface_candidates(facts)[0]
        return SurfaceResolution(
            surface_id=fallback,
            exists=False,
            source="facts",
            metadata={"candidate_chain": self._surface_candidates(facts)},
        )

    def resolve_routing(
        self,
        facts: EventFacts,
        session: SessionConfig,
        surface: SurfaceResolution,
    ) -> RoutingDecision:
        """解析 routing 决策.

        Args:
            facts (EventFacts): 当前事件事实.
            session (SessionConfig): 当前会话配置.
            surface (SurfaceResolution): 当前消息命中的 surface.

        Returns:
            RoutingDecision: 本次 routing 结果.
        """

        domain = self._surface_config(session, surface).routing
        payload, case_id, priority, specificity = self._resolve_single_domain(
            facts=facts,
            selectors=session.selectors,
            domain=domain,
        )
        profile_id = str(payload.get("profile", session.frontstage_profile) or session.frontstage_profile)
        actor_lane = str(payload.get("actor_lane", "frontstage") or "frontstage")
        return RoutingDecision(
            actor_lane=actor_lane,
            profile_id=profile_id,
            reason="surface case" if case_id else "surface default",
            source_case_id=case_id,
            priority=priority,
            specificity=specificity,
        )

    def resolve_admission(
        self,
        facts: EventFacts,
        session: SessionConfig,
        surface: SurfaceResolution,
    ) -> AdmissionDecision:
        """解析 admission 决策.

        Args:
            facts (EventFacts): 当前事件事实.
            session (SessionConfig): 当前会话配置.
            surface (SurfaceResolution): 当前消息命中的 surface.

        Returns:
            AdmissionDecision: 本次 admission 结果.
        """

        domain = self._surface_config(session, surface).admission
        payload, case_id, priority, specificity = self._resolve_single_domain(
            facts=facts,
            selectors=session.selectors,
            domain=domain,
        )
        mode = self._parse_admission_mode(payload.get("mode", "respond"))
        return AdmissionDecision(
            mode=mode,
            reason="surface case" if case_id else "surface default",
            source_case_id=case_id,
            priority=priority,
            specificity=specificity,
        )

    def resolve_context(
        self,
        facts: EventFacts,
        session: SessionConfig,
        surface: SurfaceResolution,
    ) -> ContextDecision:
        """解析 context 决策.

        Args:
            facts (EventFacts): 当前事件事实.
            session (SessionConfig): 当前会话配置.
            surface (SurfaceResolution): 当前消息命中的 surface.

        Returns:
            ContextDecision: 当前消息需要补的上下文结果.
        """

        domain = self._surface_config(session, surface).context
        payload, _, _, _ = self._resolve_single_domain(
            facts=facts,
            selectors=session.selectors,
            domain=domain,
        )
        return ContextDecision(
            sticky_note_scopes=list(payload.get("sticky_note_scopes", [])),
            prompt_slots=list(payload.get("prompt_slots", [])),
            retrieval_tags=list(payload.get("retrieval_tags", [])),
            context_labels=list(payload.get("context_labels", [])),
            notes=list(payload.get("notes", [])),
        )

    def resolve_persistence(
        self,
        facts: EventFacts,
        session: SessionConfig,
        surface: SurfaceResolution,
    ) -> PersistenceDecision:
        """解析 persistence 决策.

        Args:
            facts (EventFacts): 当前事件事实.
            session (SessionConfig): 当前会话配置.
            surface (SurfaceResolution): 当前消息命中的 surface.

        Returns:
            PersistenceDecision: 当前消息的持久化结果.
        """

        domain = self._surface_config(session, surface).persistence
        payload, case_id, priority, specificity = self._resolve_single_domain(
            facts=facts,
            selectors=session.selectors,
            domain=domain,
        )
        return PersistenceDecision(
            persist_event=bool(payload.get("persist_event", True)),
            reason="surface case" if case_id else "surface default",
            source_case_id=case_id,
            priority=priority,
            specificity=specificity,
        )

    def resolve_extraction(
        self,
        facts: EventFacts,
        session: SessionConfig,
        surface: SurfaceResolution,
    ) -> ExtractionDecision:
        """解析长期记忆提取决策.

        Args:
            facts (EventFacts): 当前事件事实.
            session (SessionConfig): 当前会话配置.
            surface (SurfaceResolution): 当前消息命中的 surface.

        Returns:
            ExtractionDecision: 当前消息的记忆提取结果.
        """

        domain = self._surface_config(session, surface).extraction
        payload, case_id, priority, specificity = self._resolve_single_domain(
            facts=facts,
            selectors=session.selectors,
            domain=domain,
        )
        return ExtractionDecision(
            extract_to_memory=bool(payload.get("extract_to_memory", False)),
            memory_scopes=list(payload.get("scopes", payload.get("memory_scopes", []))),
            tags=list(payload.get("tags", [])),
            reason="surface case" if case_id else "surface default",
            source_case_id=case_id,
            priority=priority,
            specificity=specificity,
        )

    def resolve_computer(
        self,
        facts: EventFacts,
        session: SessionConfig,
        surface: SurfaceResolution,
    ) -> ComputerPolicyDecision:
        """解析 computer 决策.

        Args:
            facts (EventFacts): 当前事件事实.
            session (SessionConfig): 当前会话配置.
            surface (SurfaceResolution): 当前消息命中的 surface.

        Returns:
            ComputerPolicyDecision: 当前消息的 computer 结果.
        """

        domain = self._surface_config(session, surface).computer
        payload, case_id, priority, specificity = self._resolve_single_domain(
            facts=facts,
            selectors=session.selectors,
            domain=domain,
        )
        actor_kind = str(payload.get("actor_kind", "frontstage_agent") or "frontstage_agent")
        roots = dict(payload.get("roots", {}) or {}) or self._default_roots(actor_kind)
        return ComputerPolicyDecision(
            actor_kind=actor_kind,
            backend=str(payload.get("backend", "host") or "host"),
            allow_exec=bool(payload.get("allow_exec", True)),
            allow_sessions=bool(payload.get("allow_sessions", True)),
            roots=roots,
            visible_skills=list(payload.get("visible_skills", [])),
            notes=self._computer_notes(payload),
            reason="surface case" if case_id else "surface default",
            source_case_id=case_id,
            priority=priority,
            specificity=specificity,
        )

    @staticmethod
    def build_actor_id(event: StandardEvent) -> str:
        """构造 canonical actor_id.

        Args:
            event (StandardEvent): 当前标准事件.

        Returns:
            str: canonical actor_id.
        """

        return f"{event.platform}:user:{event.source.user_id}"

    @staticmethod
    def build_channel_scope(event: StandardEvent) -> str:
        """构造 canonical channel scope.

        Args:
            event (StandardEvent): 当前标准事件.

        Returns:
            str: 当前会话的 canonical channel scope.
        """

        if event.is_group:
            return f"{event.platform}:group:{event.source.group_id}"
        return f"{event.platform}:user:{event.source.user_id}"

    @classmethod
    def build_thread_id(cls, event: StandardEvent) -> str:
        """构造 thread_id.

        Args:
            event (StandardEvent): 当前标准事件.

        Returns:
            str: 当前消息落到的 thread_id.
        """

        return cls.build_channel_scope(event)

    @staticmethod
    def _derive_scene(event: StandardEvent) -> str:
        """推导当前事件场景.

        Args:
            event (StandardEvent): 当前标准事件.

        Returns:
            str: 当前场景名.
        """

        if event.event_type != "message":
            return "notice"
        if event.is_group:
            return "group"
        return "private"

    def _surface_candidates(self, facts: EventFacts) -> list[str]:
        """给当前事实生成 surface 候选链.

        Args:
            facts (EventFacts): 当前事件事实.

        Returns:
            list[str]: 从更具体到更一般的候选 surface 列表.
        """

        text = str(facts.metadata.get("text", "") or "").strip()
        if facts.event_kind != "message":
            candidates = []
            if facts.notice_type:
                candidates.append(f"notice.{facts.notice_type}")
            candidates.append("notice.default")
            return candidates
        if facts.scene == "private":
            if text.startswith("/"):
                return ["message.command", "message.private", "message.plain"]
            return ["message.private", "message.plain"]
        if facts.mentions_self:
            return ["message.mention", "message.plain"]
        if facts.reply_targets_self:
            return ["message.reply_to_bot", "message.plain"]
        if text.startswith("/"):
            return ["message.command", "message.plain"]
        return ["message.plain"]

    @staticmethod
    def _surface_config(session: SessionConfig, surface: SurfaceResolution) -> SurfaceConfig:
        """读取当前 surface 的配置块.

        Args:
            session (SessionConfig): 当前会话配置.
            surface (SurfaceResolution): 当前消息命中的 surface.

        Returns:
            SurfaceConfig: 当前 surface 的配置. 缺失时返回空配置对象.
        """

        return session.surfaces.get(surface.surface_id, SurfaceConfig())

    def _resolve_single_domain(
        self,
        *,
        facts: EventFacts,
        selectors: dict[str, MatchSpec],
        domain: DomainConfig | None,
    ) -> tuple[dict[str, Any], str, int, int]:
        """解析单一胜者型决策域.

        Args:
            facts (EventFacts): 当前事件事实.
            selectors (dict[str, MatchSpec]): 可复用 selector 表.
            domain (DomainConfig | None): 当前决策域配置.

        Returns:
            tuple[dict[str, Any], str, int, int]:
                合成后的 payload、命中的 case_id、priority、specificity.
        """

        if domain is None:
            return {}, "", 100, 0

        payload = dict(domain.default)
        best_case: DomainCase | None = None
        best_spec: MatchSpec | None = None
        for case in domain.cases:
            spec = self._case_spec(case, selectors)
            if spec is None or not spec.matches(facts):
                continue
            if best_case is None:
                best_case = case
                best_spec = spec
                continue
            current_key = (case.priority, spec.specificity())
            best_key = (best_case.priority, best_spec.specificity() if best_spec is not None else 0)
            if current_key > best_key:
                best_case = case
                best_spec = spec
                continue
            if current_key == best_key:
                raise ValueError(
                    f"ambiguous cases in domain: {best_case.case_id} conflicts with {case.case_id}"
                )

        if best_case is None:
            return payload, "", 100, 0

        payload.update(best_case.use)
        return payload, best_case.case_id, best_case.priority, best_spec.specificity() if best_spec is not None else 0

    @staticmethod
    def _case_spec(case: DomainCase, selectors: dict[str, MatchSpec]) -> MatchSpec | None:
        """取出 case 实际使用的匹配条件.

        Args:
            case (DomainCase): 当前 case.
            selectors (dict[str, MatchSpec]): 可复用 selector 表.

        Returns:
            MatchSpec | None: 当前 case 的匹配条件. 没有条件时返回 `None`.

        Raises:
            ValueError: `when_ref` 指向了不存在的 selector 时抛出.
        """

        if case.when is not None:
            return case.when
        if case.when_ref:
            spec = selectors.get(case.when_ref)
            if spec is None:
                raise ValueError(f"unknown selector: {case.when_ref}")
            return spec
        return MatchSpec()

    @staticmethod
    def _default_roots(actor_kind: str) -> dict[str, dict[str, bool]]:
        """给指定 actor kind 生成默认 roots 权限.

        Args:
            actor_kind (str): 当前 actor kind.

        Returns:
            dict[str, dict[str, bool]]: 默认 root 权限表.
        """

        if actor_kind == "subagent":
            return {
                "workspace": {"visible": True, "writable": True},
                "skills": {"visible": True, "writable": False},
                "self": {"visible": False, "writable": False},
            }
        return {
            "workspace": {"visible": True, "writable": True},
            "skills": {"visible": True, "writable": False},
            "self": {"visible": True, "writable": True},
        }

    @staticmethod
    def _computer_notes(payload: dict[str, Any]) -> list[str]:
        """把 computer payload 里的补充信息收成说明列表.

        Args:
            payload (dict[str, Any]): 当前 computer payload.

        Returns:
            list[str]: 当前决策附带的说明列表.
        """

        notes = list(payload.get("notes", []))
        preset = str(payload.get("preset", "") or "")
        if preset:
            notes.append(f"preset:{preset}")
        return notes

    @staticmethod
    def _parse_admission_mode(raw: object) -> str:
        """校验 admission mode.

        Args:
            raw (object): 原始 admission mode 值.

        Returns:
            str: 规范化后的 admission mode.

        Raises:
            ValueError: mode 不在支持范围内时抛出.
        """

        mode = str(raw or "respond")
        if mode not in {"respond", "record_only", "silent_drop"}:
            raise ValueError(f"unsupported admission mode: {mode}")
        return mode


# endregion


__all__ = ["SessionRuntime"]
