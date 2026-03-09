"""runtime.outbox 负责统一出站和 bot 消息入库.

这一版只支持纯文本和简单 payload 写回.
"""

from __future__ import annotations

from typing import Any

from .gateway_protocol import GatewayProtocol
from .models import (
    DispatchReport,
    DeliveryResult,
    MessageRecord,
    OutboxItem,
    RunContext,
)
from .stores import MessageStore


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
                # 发送, 拿发送结果
                raw = await self.gateway.send(item.plan.action)
                if raw is None:
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
                # 把成功送达的 assistant 消息写入 MessageStore
                await self._persist_success(item=item, result=result)
            except Exception as exc:
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
                content_text=self._extract_text_content(action.payload),
                content_json=dict(action.payload),
                platform_message_id=result.platform_message_id,
                timestamp=self._extract_timestamp(result.raw),
                metadata={
                    **item.metadata,
                    "action_type": str(action.action_type),
                    "thread_content": item.plan.thread_content,
                },
            )
        )

    @staticmethod
    def _extract_text_content(payload: dict[str, Any]) -> str:
        """从 action payload 中提取便于查询的文本内容.

        Args:
            payload: action 的 payload 数据.

        Returns:
            一个尽量稳定的纯文本表示.
        """

        if "text" in payload:
            return str(payload.get("text", ""))
        if "segments" in payload:
            return str(payload.get("segments", ""))
        return str(payload)

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
