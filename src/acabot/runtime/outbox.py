"""runtime.outbox 负责统一出站和 bot 消息入库.

这一版已经支持:
- `SEND_TEXT`
- `SEND_SEGMENTS`
- richer action 的统一发送

同时明确:
- 只有真正产生日志事实的消息动作才写入 MessageStore
- 控制动作如 `GROUP_BAN` 不应伪装成 assistant message
"""

from __future__ import annotations

from dataclasses import replace
import logging
from pathlib import Path
from typing import Any

from acabot.types import Action, ActionType

from .gateway_protocol import GatewayProtocol
from .ids import build_thread_id_from_conversation_id
from .memory.long_term_ingestor import LongTermMemoryIngestor
from .outbound_projection import project_outbound_message, snapshot_source_intent
from .contracts import (
    DispatchReport,
    DeliveryResult,
    MessageRecord,
    OutboxItem,
    RunContext,
)
from .render import RenderService
from .storage.stores import MessageStore

logger = logging.getLogger("acabot.runtime.outbox")


class Outbox:
    """统一出站组件.

    接收 ThreadPipeline 规划好的动作, 调用 gateway 发送, 并把成功送达的 assistant 消息写入 MessageStore.
    """

    def __init__(
        self,
        *,
        gateway: GatewayProtocol,
        store: MessageStore,
        render_service: RenderService | None = None,
        long_term_memory_ingestor: LongTermMemoryIngestor | None = None,
    ) -> None:
        """初始化 Outbox.

        Args:
            gateway: 实际执行发送动作的网关.
            store: 用于保存成功出站消息的消息存储.
            render_service: 负责编译 render 内容的渲染服务.
            long_term_memory_ingestor: 长期记忆写入线入口.
        """

        self.gateway = gateway
        self.store = store
        self.render_service = render_service or RenderService(
            runtime_root=Path.cwd() / "runtime_data",
        )
        self.long_term_memory_ingestor = long_term_memory_ingestor

    async def dispatch(self, ctx: RunContext) -> DispatchReport:
        """发送一个 RunContext 中已经规划好的动作.

        Args:
            ctx: 当前 run 的执行上下文.

        Returns:
            一份批量出站结果汇总.
        """

        return await self.send_items(self._build_items(ctx))

    async def send_items(self, items: list[OutboxItem]) -> DispatchReport:
        """按顺序发送一批 OutboxItem.

        Args:
            items: 待发送的动作列表.

        Returns:
            一份批量出站结果汇总.
        """

        report = DispatchReport()
        for item in items:
            try:
                item = await self._materialize_item(item)
                item = self._ensure_thread_content(item)
                logger.debug(
                    "Outbox send: run_id=%s action_id=%s action_type=%s thread=%s",
                    item.run_id,
                    item.plan.action_id,
                    item.plan.action.action_type,
                    item.thread_id,
                )
                # 发送, 拿发送结果
                raw = await self.gateway.send(item.plan.action)
                if raw is None:
                    logger.warning(
                        "Outbox send failed without ack: run_id=%s action_id=%s",
                        item.run_id,
                        item.plan.action_id,
                    )
                    report.results.append(
                        DeliveryResult(
                            action_id=item.plan.action_id,
                            ok=False,
                            error="no_ack",
                        )
                    )
                    report.failed_action_ids.append(item.plan.action_id)
                    continue

                result = DeliveryResult(
                    action_id=item.plan.action_id,
                    ok=True,
                    platform_message_id=str(raw.get("message_id", "")),
                    raw=raw,
                )
                report.results.append(result)
                report.delivered_items.append(item)
                logger.debug(
                    "Outbox delivered: run_id=%s action_id=%s platform_message_id=%s",
                    item.run_id,
                    item.plan.action_id,
                    result.platform_message_id or "-",
                )
                # region message落库
                if self._should_persist_action(item.plan.action):
                    await self._persist_success(item=item, result=result)
                # endregion
            except Exception as exc:
                logger.exception(
                    "Outbox dispatch crashed: run_id=%s action_id=%s",
                    item.run_id,
                    item.plan.action_id,
                )
                report.results.append(
                    DeliveryResult(
                        action_id=item.plan.action_id,
                        ok=False,
                        error=str(exc),
                    )
                )
                report.failed_action_ids.append(item.plan.action_id)
        return report

    def _build_items(self, ctx: RunContext) -> list[OutboxItem]:
        """把 RunContext 中的 PlannedAction 转成 OutboxItem.

        Args:
            ctx: 当前 run 的执行上下文.

        Returns:
            可直接发送的 OutboxItem 列表.
        """

        return [
            # PlannedAction 只有 action + thread_content, 但发送时需要更多上下文
            OutboxItem(
                thread_id=destination_thread_id,
                run_id=ctx.run.run_id,
                agent_id=ctx.agent.agent_id,
                plan=plan,
                origin_thread_id=ctx.thread.thread_id,
                destination_thread_id=destination_thread_id,
                destination_conversation_id=destination_conversation_id,
                append_to_origin_thread=destination_thread_id == ctx.thread.thread_id,
                metadata={
                    "channel_scope": destination_conversation_id,
                    "origin_thread_id": ctx.thread.thread_id,
                    "destination_conversation_id": destination_conversation_id,
                },
            )
            for plan in ctx.actions
            for destination_conversation_id, destination_thread_id in [
                self._resolve_destination_contract(ctx=ctx, action=plan.action, metadata=plan.metadata)
            ]
        ]

    async def _persist_success(
        self, *, item: OutboxItem, result: DeliveryResult
    ) -> None:
        """把成功送达的 assistant 消息写入 MessageStore.

        Args:
            item: 已送达的 OutboxItem.
            result: 对应的投递结果.
        """

        action = item.plan.action
        source_intent = self._read_source_intent(item.plan.metadata)
        projection = project_outbound_message(
            action=action,
            source_intent=source_intent,
        )
        await self.store.save(
            MessageRecord(
                message_uid=f"{item.run_id}:{item.plan.action_id}",
                thread_id=item.destination_thread_id,
                run_id=item.run_id,
                actor_id=f"agent:{item.agent_id}",
                platform=action.target.platform,
                role="assistant",
                content_text=projection.fact_text,
                content_json=self._extract_content_json(action),
                platform_message_id=result.platform_message_id,
                timestamp=self._extract_timestamp(result.raw),
                metadata={
                    **item.metadata,
                    "action_type": str(action.action_type),
                    "actor_display_name": item.agent_id,
                    "thread_content": item.plan.thread_content,
                    "source_intent": source_intent,
                },
            )
        )
        try:
            if self.long_term_memory_ingestor is not None:
                self.long_term_memory_ingestor.mark_dirty(item.destination_thread_id)
        except Exception:
            logger.exception(
                "Failed to mark long-term memory dirty after message persist: thread=%s",
                item.destination_thread_id,
            )
        logger.debug(
            "Outbox persisted assistant message: run_id=%s action_id=%s thread=%s",
            item.run_id,
            item.plan.action_id,
            item.destination_thread_id,
        )

    async def _materialize_item(self, item: OutboxItem) -> OutboxItem:
        """把高层 send intent 物化成真正可发送的低层消息动作.

        当前 runtime 里只有 `ActionType.SEND_MESSAGE_INTENT` 属于"高层发送意图":
        它来自统一 `message` tool 的 `action="send"`，payload 里还保留
        `text` / `images` / `render` / `at_user` 这类上层字段，说明的是
        "想发什么"，还不是平台已经能直接执行的动作。

        这一步会把高层 send intent 编译成一个真正可发的低层
        `ActionType.SEND_SEGMENTS`。编译后的动作只保留平台发送所需的
        `segments` 和 `reply_to`，后面 Gateway 可以直接把它翻成 OneBot /
        NapCat API payload。

        其他 action 都已经是低层直通动作，不在这里改写，包括:
        - `SEND_TEXT`
        - `SEND_SEGMENTS`
        - `REACTION`
        - `RECALL`
        - `GROUP_BAN`
        - `GROUP_KICK`

        这些动作已经足够接近平台执行面，Outbox 只负责按顺序发送，不再额外
        做一次高层 -> 低层的编译。
        """

        action = item.plan.action
        if action.action_type != ActionType.SEND_MESSAGE_INTENT:
            return item

        plan_metadata = dict(item.plan.metadata)
        plan_metadata.setdefault("source_intent", snapshot_source_intent(action))
        segments = await self._build_send_segments(item=item, action=action)
        materialized_plan = replace(
            item.plan,
            action=Action(
                action_type=ActionType.SEND_SEGMENTS,
                target=action.target,
                payload={"segments": segments},
                reply_to=action.reply_to,
            ),
            metadata=plan_metadata,
        )
        return replace(item, plan=materialized_plan)

    @staticmethod
    def _ensure_thread_content(item: OutboxItem) -> OutboxItem:
        """保证 delivered item 带有可写回 working memory 的 `thread_content`.

        `thread_content` 是 runtime 写回 thread working memory 时使用的稳定文本
        摘要，不要求完整保真，但要求和"这次最终真的发出了什么"保持同一语义。

        当前规则:
        - 如果上游已经明确给了 `plan.thread_content`，这里原样保留
        - 如果上游没给，就根据当前 delivery action 自动生成一个
          `OutboundMessageProjection`
        - facts 用的 `fact_text` 继续偏短摘要，working memory 用的 `thread_text`
          则优先读取 `plan.metadata["source_intent"]`
        - 对 render 来说，`thread_text` 会忠实保留原始 markdown / LaTeX 文本，
          不会只留下最终图片占位符
        - 如果当前 action 无法投影出稳定文本，就继续保持 `None`

        这样做的目的，是把 working memory 摘要统一收口到 Outbox 的最终发送面，
        避免每个 tool 都自己重复维护一套"发出去之后该怎么写回线程"的规则。
        """

        if item.plan.thread_content:
            return item
        projection = project_outbound_message(
            action=item.plan.action,
            source_intent=Outbox._read_source_intent(item.plan.metadata),
        )
        thread_content = projection.thread_text.strip()
        if not thread_content:
            return item
        return replace(
            item,
            plan=replace(
                item.plan,
                thread_content=thread_content,
            ),
        )

    async def _build_send_segments(
        self,
        *,
        item: OutboxItem,
        action: Action,
    ) -> list[dict[str, Any]]:
        """按固定顺序把 send intent payload 编译成 OneBot 段列表."""

        payload = dict(action.payload)
        segments: list[dict[str, Any]] = []

        at_user = str(payload.get("at_user", "") or "").strip()
        if at_user:
            segments.append({"type": "at", "data": {"qq": at_user}})

        text = str(payload.get("text", "") or "").strip()
        if text:
            segments.append({"type": "text", "data": {"text": text}})

        for image in payload.get("images", []) or []:
            file_ref = str(image or "").strip()
            if file_ref:
                segments.append({"type": "image", "data": {"file": file_ref}})

        render = str(payload.get("render", "") or "")
        if render:
            segments.extend(
                await self._build_render_segments(
                    markdown_text=render,
                    conversation_id=item.destination_conversation_id,
                    run_id=item.run_id,
                )
            )

        return segments

    async def _build_render_segments(
        self,
        *,
        markdown_text: str,
        conversation_id: str,
        run_id: str,
    ) -> list[dict[str, Any]]:
        """把 render markdown 编译成图片段, 失败时退回原始文本."""

        try:
            result = await self.render_service.render_markdown_to_image(
                markdown_text=markdown_text,
                conversation_id=conversation_id,
                run_id=run_id,
            )
        except Exception:
            logger.exception(
                "Render service crashed, fallback to raw markdown text: conversation=%s run_id=%s",
                conversation_id,
                run_id,
            )
            return [{"type": "text", "data": {"text": markdown_text}}]

        if result.status == "ok" and result.artifact_path is not None:
            return [{"type": "image", "data": {"file": str(result.artifact_path)}}]

        logger.warning(
            "Render unavailable, fallback to raw markdown text: conversation=%s run_id=%s status=%s error=%s",
            conversation_id,
            run_id,
            result.status,
            result.error,
        )
        return [{"type": "text", "data": {"text": markdown_text}}]

    @staticmethod
    def _resolve_destination_contract(
        *,
        ctx: RunContext,
        action: Action,
        metadata: dict[str, Any],
    ) -> tuple[str, str]:
        """解析本次动作的目标 conversation/thread contract."""

        destination_conversation_id = str(metadata.get("destination_conversation_id", "") or "").strip()
        if not destination_conversation_id:
            destination_conversation_id = Outbox._conversation_id_from_target(action.target)
        destination_thread_id = build_thread_id_from_conversation_id(destination_conversation_id)
        return destination_conversation_id, destination_thread_id

    @staticmethod
    def _conversation_id_from_target(target: Any) -> str:
        """从 Action.target 回推 canonical conversation_id."""

        if getattr(target, "message_type", "") == "group":
            return f"{target.platform}:group:{target.group_id}"
        return f"{target.platform}:user:{target.user_id}"

    @staticmethod
    def _should_persist_action(action: Action) -> bool:
        """判断一个动作是否应该写入 MessageStore.

        Args:
            action: 已成功送达的动作.

        Returns:
            只有真正产生 assistant 消息事实的动作才返回 True.

        这里的规则是 Outbox 自己的"bot 出站消息事实"规则，不读取 session 的
        `PersistenceDecision`。

        当前代码里，session / surface 的 persistence 决策只作用在入站 event
        是否写入 `ChannelEventStore`，对应 `RuntimeApp._should_persist_event()`；
        bot 自己成功送达的消息则由 Outbox 单独决定是否写 `MessageStore`。

        目前的固定策略是:
        - `SEND_TEXT` / `SEND_SEGMENTS` 这类真正形成聊天内容的动作会写
          `MessageStore`
        - `REACTION` / `RECALL` / 群管理动作这类控制动作不会伪装成一条新的
          assistant message

        也就是说，当前 persistence config 主要管"平台上收到的 event 是否记账"，
        还没有扩展到"bot 自己送达的 message fact 是否按 session 配置过滤"。
        """

        return action.action_type in {ActionType.SEND_TEXT, ActionType.SEND_SEGMENTS}

    @staticmethod
    def _read_source_intent(metadata: dict[str, Any]) -> dict[str, Any]:
        """从计划 metadata 中读取高层 send intent 快照.

        Args:
            metadata: `PlannedAction.metadata`.

        Returns:
            一个字典副本. 非 `message.send` 动作会返回空字典.

        `source_intent` 是高层 `SEND_MESSAGE_INTENT` 在 materialize 之前保留
        下来的原始语义快照。Outbox 用它来生成 continuity 导向的 `thread_text`,
        让 render 成功后 working memory 还能看到原始 markdown / LaTeX.
        """

        raw = metadata.get("source_intent", {})
        if not isinstance(raw, dict):
            return {}
        return dict(raw)

    @staticmethod
    def _extract_content_json(action: Action) -> dict[str, Any]:
        """返回适合写入事实表的结构化内容.

        Args:
            action: 已送达的动作.

        Returns:
            对应的 payload 副本.
        """

        return dict(action.payload)

    @staticmethod
    def _extract_timestamp(raw: dict[str, Any] | None) -> int:
        """从网关返回值里提取时间戳.

        Args:
            raw: gateway.send 的原始返回值.

        Returns:
            如果返回值中带 `timestamp`, 则返回该值, 否则返回 0.
        """

        if raw is None:
            return 0
        value = raw.get("timestamp", 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
