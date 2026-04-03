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
        await self.store.save(
            MessageRecord(
                message_uid=f"{item.run_id}:{item.plan.action_id}",
                thread_id=item.destination_thread_id,
                run_id=item.run_id,
                actor_id=f"agent:{item.agent_id}",
                platform=action.target.platform,
                role="assistant",
                content_text=self._extract_text_content(action),
                content_json=self._extract_content_json(action),
                platform_message_id=result.platform_message_id,
                timestamp=self._extract_timestamp(result.raw),
                metadata={
                    **item.metadata,
                    "action_type": str(action.action_type),
                    "actor_display_name": item.agent_id,
                    "thread_content": item.plan.thread_content,
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
        """把高层 send intent 物化成真正可发送的低层消息动作."""

        action = item.plan.action
        if action.action_type != ActionType.SEND_MESSAGE_INTENT:
            return item

        segments = await self._build_send_segments(item=item, action=action)
        materialized_plan = replace(
            item.plan,
            action=Action(
                action_type=ActionType.SEND_SEGMENTS,
                target=action.target,
                payload={"segments": segments},
                reply_to=action.reply_to,
            ),
        )
        return replace(item, plan=materialized_plan)

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
            只有真正产生消息事实的动作才返回 True.
        """

        return action.action_type in {ActionType.SEND_TEXT, ActionType.SEND_SEGMENTS}

    @staticmethod
    def _extract_text_content(action: Action) -> str:
        """从 action payload 中提取便于查询的文本内容.

        Args:
            action: 已送达的动作.

        Returns:
            一个尽量稳定的纯文本表示.
        """

        payload = action.payload
        if action.action_type == ActionType.SEND_TEXT:
            return str(payload.get("text", ""))
        if action.action_type != ActionType.SEND_SEGMENTS:
            return ""

        parts: list[str] = []
        for seg in payload.get("segments", []):
            seg_type = str(seg.get("type", "") or "")
            seg_data = dict(seg.get("data", {}) or {})
            if seg_type == "text":
                parts.append(str(seg_data.get("text", "")))
            elif seg_type == "image":
                parts.append("[图片]")
            else:
                parts.append(f"[{seg_type}]")
        return "".join(parts)

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
