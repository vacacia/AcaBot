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

import logging
from typing import Any

from acabot.types import Action, ActionType

from .gateway_protocol import GatewayProtocol
from .contracts import (
    DispatchReport,
    DeliveryResult,
    MessageRecord,
    OutboxItem,
    RunContext,
)
from .storage.stores import MessageStore

logger = logging.getLogger("acabot.runtime.outbox")


class Outbox:
    """统一出站组件.

    接收 ThreadPipeline 规划好的动作, 调用 gateway 发送, 并把成功送达的 assistant 消息写入 MessageStore.
    """

    def __init__(self, *, gateway: GatewayProtocol, store: MessageStore) -> None:
        """初始化 Outbox.

        Args:
            gateway: 实际执行发送动作的网关.
            store: 用于保存成功出站消息的消息存储.
        """

        self.gateway = gateway
        self.store = store

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
                thread_id=ctx.thread.thread_id,
                run_id=ctx.run.run_id,
                agent_id=ctx.profile.agent_id,
                plan=plan,
            )
            for plan in ctx.actions
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
                thread_id=item.thread_id,
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
                    "thread_content": item.plan.thread_content,
                },
            )
        )
        logger.debug(
            "Outbox persisted assistant message: run_id=%s action_id=%s thread=%s",
            item.run_id,
            item.plan.action_id,
            item.thread_id,
        )

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
