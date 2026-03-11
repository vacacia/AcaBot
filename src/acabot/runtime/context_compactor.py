r"""runtime.context_compactor 提供生产向 context compaction 的第一阶段实现.

组件关系:

    ThreadPipeline
        |
        +--> append incoming message
        |
        `--> ContextCompactor.compact()
                  |
                  +--> token budget
                  +--> turn-aware truncation
                  `--> token_stats

当前阶段只完成:

- async compactor seam
- token-aware truncate
- turn integrity protection
- important turn pinning
- LLM-driven summary
- incremental summary update
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from acabot.agent import BaseAgent

from .models import RunContext, ThreadState

try:
    from litellm import get_model_info, token_counter
except ImportError:  # pragma: no cover
    get_model_info = None  # type: ignore[assignment]
    token_counter = None  # type: ignore[assignment]

ContextCompactionStrategy = Literal["truncate", "summarize"]

_FALLBACK_CONTEXT_WINDOW = 64000


# region config
@dataclass(slots=True)
class ContextCompactionConfig:
    """context compaction 的运行配置.

    Attributes:
        enabled (bool): 是否启用 context compaction.
        strategy (ContextCompactionStrategy): 当前压缩策略.
        max_context_ratio (float): 历史消息可用的上下文比例.
        preserve_recent_turns (int): 至少保留最近多少轮完整对话.
        system_prompt_reserve_tokens (int): 为稳定 system prompt 预留的 token.
        prompt_slot_reserve_tokens (int): 为 sticky summary retrieval 这些动态 slot 预留的 token.
        tool_schema_reserve_tokens (int): 为 tool schema 预留的 token.
        summary_model (str): summarize 模式使用的模型. 为空时沿用当前 profile model.
        summary_max_chars (int): 单次 summary 最多保留多少字符.
        summary_system_prompt (str): 首次摘要使用的 system prompt.
        update_summary_system_prompt (str): 增量摘要使用的 system prompt.
        fallback_context_window (int): 模型上下文窗口读取失败时的保守默认值.
    """

    enabled: bool = True
    strategy: ContextCompactionStrategy = "truncate"
    max_context_ratio: float = 0.7
    preserve_recent_turns: int = 6
    system_prompt_reserve_tokens: int = 1500
    prompt_slot_reserve_tokens: int = 2500
    tool_schema_reserve_tokens: int = 3000
    summary_model: str = ""
    summary_max_chars: int = 2400
    summary_system_prompt: str = (
        "You are compacting old conversation history for a long running agent. "
        "Write a concise continuation summary that preserves the user's goals, "
        "important facts, key decisions, open loops, promised follow ups, and "
        "important tool results. Use the dominant language of the conversation. "
        "Do not invent facts. Prefer stable facts over transient chatter."
    )
    update_summary_system_prompt: str = (
        "You are updating an existing continuation summary for a long running agent. "
        "Merge the prior summary with the newly compacted conversation. Keep still relevant "
        "facts, remove contradicted or obsolete details, and preserve goals, decisions, "
        "open loops, promised follow ups, and important tool results. Use the dominant "
        "language of the conversation. Do not invent facts."
    )
    fallback_context_window: int = _FALLBACK_CONTEXT_WINDOW


@dataclass(slots=True)
class ContextCompactionResult:
    """一次 compaction 的标准结果.

    Attributes:
        compressed_messages (list[dict[str, Any]]): compaction 后保留的消息列表.
        dropped_messages (list[dict[str, Any]]): 本次被裁掉的消息列表.
        strategy_used (str): 本次实际使用的策略.
        context_window (int): 当前模型的上下文窗口.
        budget (int): 本次允许历史消息使用的 token 预算.
        before_tokens (int): compaction 前消息 token 数.
        after_tokens (int): compaction 后消息 token 数.
        kept_turns (int): 本次保留的轮次数.
        dropped_turns (int): 本次裁掉的轮次数.
        summary_text (str): 当前 run 应使用的有效 working summary.
    """

    compressed_messages: list[dict[str, Any]]
    dropped_messages: list[dict[str, Any]]
    strategy_used: str
    context_window: int
    budget: int
    before_tokens: int
    after_tokens: int
    kept_turns: int
    dropped_turns: int
    summary_text: str = ""


@dataclass(slots=True)
class ThreadCompactionSnapshot:
    """一次 compaction 使用的 thread 快照.

    Attributes:
        working_messages (list[dict[str, Any]]): 快照时的 working messages.
        working_summary (str): 快照时的 working summary.
        last_event_at (int): 快照时的最后事件时间.
        message_count (int): 快照时的消息条数.
    """

    working_messages: list[dict[str, Any]]
    working_summary: str
    last_event_at: int
    message_count: int


class ContextSummarizer(Protocol):
    """ContextSummarizer 协议.

    后续 summarize 模式会通过这个 seam 接入 LLM compaction.
    """

    async def __call__(
        self,
        *,
        ctx: RunContext,
        dropped_messages: list[dict[str, Any]],
    ) -> str:
        """为被压缩历史生成摘要.

        Args:
            ctx: 当前 run 的执行上下文.
            dropped_messages: 本次被压缩掉的历史消息.

        Returns:
            一段新的 compaction summary.
        """

        ...


@dataclass(slots=True)
class NullContextSummarizer:
    """默认空的 ContextSummarizer."""

    async def __call__(
        self,
        *,
        ctx: RunContext,
        dropped_messages: list[dict[str, Any]],
    ) -> str:
        """返回空摘要.

        Args:
            ctx: 当前 run 的执行上下文.
            dropped_messages: 本次被压缩掉的历史消息.

        Returns:
            空字符串.
        """

        _ = ctx, dropped_messages
        return ""


@dataclass(slots=True)
class ModelContextSummarizer:
    """基于 BaseAgent.complete 的 LLM 摘要器.

    Attributes:
        agent (BaseAgent): 用于执行单次摘要 completion 的 agent.
        config (ContextCompactionConfig): 当前 compaction 配置.
    """

    agent: BaseAgent
    config: ContextCompactionConfig

    async def __call__(
        self,
        *,
        ctx: RunContext,
        dropped_messages: list[dict[str, Any]],
    ) -> str:
        """为被压缩历史生成或更新摘要.

        Args:
            ctx: 当前 run 的执行上下文.
            dropped_messages: 本次被压缩掉的历史消息.

        Returns:
            一段新的 working summary.
        """

        if not dropped_messages:
            return ctx.thread.working_summary.strip()

        system_prompt, user_prompt = self._build_prompts(
            ctx=ctx,
            dropped_messages=dropped_messages,
        )
        response = await self.agent.complete(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            model=self.config.summary_model or ctx.profile.default_model,
        )
        if response.error:
            return ""
        return _truncate_text(response.text or "", self.config.summary_max_chars)

    # region prompt构造
    def _build_prompts(
        self,
        *,
        ctx: RunContext,
        dropped_messages: list[dict[str, Any]],
    ) -> tuple[str, str]:
        """构造摘要或增量摘要的提示词.

        Args:
            ctx: 当前 run 的执行上下文.
            dropped_messages: 本次被压缩掉的历史消息.

        Returns:
            `(system_prompt, user_prompt)`.
        """

        serialized = self._serialize_messages(dropped_messages)
        current_summary = ctx.thread.working_summary.strip()
        if current_summary:
            return (
                self.config.update_summary_system_prompt,
                (
                    "Existing summary:\n"
                    "<summary>\n"
                    f"{current_summary}\n"
                    "</summary>\n\n"
                    "Newly compacted conversation:\n"
                    "<conversation>\n"
                    f"{serialized}\n"
                    "</conversation>\n\n"
                    "Return the updated summary only."
                ),
            )
        return (
            self.config.summary_system_prompt,
            (
                "Compacted conversation history:\n"
                "<conversation>\n"
                f"{serialized}\n"
                "</conversation>\n\n"
                "Return the summary only."
            ),
        )

    def _serialize_messages(self, messages: list[dict[str, Any]]) -> str:
        """把消息列表转成摘要模型可读的纯文本.

        Args:
            messages: 待摘要的历史消息列表.

        Returns:
            纯文本序列化结果.
        """

        lines: list[str] = []
        for message in messages:
            role = str(message.get("role", "unknown") or "unknown")
            content = self._serialize_message_content(message)
            if not content:
                continue
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def _serialize_message_content(self, message: dict[str, Any]) -> str:
        """提取单条消息可供摘要的文本内容.

        Args:
            message: 单条 working memory 消息.

        Returns:
            适合摘要的文本.
        """

        content = message.get("content", "")
        if isinstance(content, str):
            serialized = content.strip()
        else:
            serialized = str(content).strip()
        if message.get("tool_calls"):
            serialized = f"{serialized}\n[tool_calls] {message['tool_calls']}".strip()
        if message.get("tool_call_id"):
            serialized = f"{serialized}\n[tool_call_id] {message['tool_call_id']}".strip()
        return serialized

    # endregion


# endregion


# region compactor
class ContextCompactor:
    """working memory 的 token-aware compactor.

    Attributes:
        config (ContextCompactionConfig): 当前 compactor 配置.
        summarizer (ContextSummarizer): summarize 模式使用的摘要器.
    """

    def __init__(
        self,
        config: ContextCompactionConfig | None = None,
        *,
        summarizer: ContextSummarizer | None = None,
    ) -> None:
        """初始化 ContextCompactor.

        Args:
            config: 可选的 compaction 配置.
            summarizer: 可选的摘要器.
        """

        self.config = config or ContextCompactionConfig()
        self.summarizer = summarizer or NullContextSummarizer()

    def snapshot_thread(self, thread: ThreadState) -> ThreadCompactionSnapshot:
        """为当前 thread 构造 compaction 快照.

        Args:
            thread: 当前 thread 状态.

        Returns:
            一份 ThreadCompactionSnapshot.
        """

        return ThreadCompactionSnapshot(
            working_messages=[dict(message) for message in thread.working_messages],
            working_summary=str(thread.working_summary),
            last_event_at=int(thread.last_event_at),
            message_count=len(thread.working_messages),
        )

    async def compact(
        self,
        ctx: RunContext,
        *,
        snapshot: ThreadCompactionSnapshot | None = None,
    ) -> ContextCompactionResult:
        """对当前 thread working memory 执行 compaction.

        1. 计算 token 预算
        2. 识别对话轮次
        3. 按预算保留/丢弃轮次
        4. (可选)生成摘要
        5. 更新 thread 状态
        6. 返回压缩结果
        
        Args:
            ctx: 当前 run 的执行上下文.
            snapshot: 可选的 thread 快照. 未提供时会即时读取.

        Returns:
            一份 ContextCompactionResult.
        """
        # -----------------------------------------------------
        # 阶段 1: 计算预算
        # -----------------------------------------------------
        active_snapshot = snapshot or self.snapshot_thread(ctx.thread)
        messages = [dict(message) for message in active_snapshot.working_messages]
        model = ctx.profile.default_model
        context_window = self._get_context_window(model)
        budget = self._history_budget(context_window)
        before_tokens = self._count_tokens(model, messages)
        effective_summary = active_snapshot.working_summary.strip()

        # -----------------------------------------------------
        # 阶段 2: 快速返回 - 无需压缩
        # -----------------------------------------------------
        if not self.config.enabled or not messages or before_tokens <= budget:
            result = ContextCompactionResult(
                compressed_messages=messages,
                dropped_messages=[],
                strategy_used="none",
                context_window=context_window,
                budget=budget,
                before_tokens=before_tokens,
                after_tokens=before_tokens,
                kept_turns=len(self._identify_turns(messages)),
                dropped_turns=0,
                summary_text=effective_summary,
            )
            self._write_stats(ctx, result)
            return result
        # -----------------------------------------------------
        # 阶段 3: 轮次识别与选择
        # -----------------------------------------------------
        turns = self._identify_turns(messages)
        # 强制保留最近 N 轮和 pinned 的轮次
        kept_turns = self._fit_turns_to_budget(
            turns=turns,
            messages=messages,
            model=model,
            budget=budget,
        )
        kept_indexes = {
            index
            for turn in kept_turns
            for index in turn
        }
        # -----------------------------------------------------
        # 阶段 4: 分离保留/丢弃的消息
        # -----------------------------------------------------
        # 保留的信息, 已剔除 dropped_messages
        compressed_messages = [
            dict(message)
            for index, message in enumerate(messages)
            if index in kept_indexes
        ]
        # 被 drop 的信息, 丢弃或 summarize
        dropped_messages = [
            dict(message)
            for index, message in enumerate(messages)
            if index not in kept_indexes
        ]
        # -----------------------------------------------------
        # 阶段 5: summarize
        # -----------------------------------------------------
        strategy_used = "truncate"
        if self.config.strategy == "summarize":
            summary = await self.summarizer(ctx=ctx, dropped_messages=dropped_messages)
            if summary.strip():
                effective_summary = summary.strip()
                strategy_used = "summarize"

        # -----------------------------------------------------
        # 阶段 7: 构造返回结果
        # -----------------------------------------------------
        after_tokens = self._count_tokens(model, compressed_messages)
        result = ContextCompactionResult(
            compressed_messages=compressed_messages,
            dropped_messages=dropped_messages,
            strategy_used=strategy_used,
            context_window=context_window,
            budget=budget,
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            kept_turns=len(kept_turns),
            dropped_turns=max(0, len(turns) - len(kept_turns)),
            summary_text=effective_summary,
        )
        self._write_stats(ctx, result)
        return result

    def apply_to_thread(
        self,
        thread: ThreadState,
        *,
        snapshot: ThreadCompactionSnapshot,
        result: ContextCompactionResult,
        timestamp: int,
    ) -> bool:
        """把 compaction 结果回写到 thread.

        只有当 thread 仍然和 snapshot 一致时才应用, 避免在 LLM summary 期间覆盖并发写入.

        Args:
            thread: 当前 thread 状态.
            snapshot: compaction 开始时的 thread 快照.
            result: compaction 结果.
            timestamp: 当前事件时间戳.

        Returns:
            是否成功把结果应用到 thread.
        """
        # 校验 1: 消息数量是否变化
        if len(thread.working_messages) != snapshot.message_count:
            return False
        # 校验 2: 最后事件时间是否变化
        if thread.last_event_at != snapshot.last_event_at:
            return False
        # 校验 3: working_summary 是否变化
        if thread.working_summary != snapshot.working_summary:
            return False

        thread.working_messages = [dict(message) for message in result.compressed_messages]
        thread.working_summary = result.summary_text
        thread.metadata["compressed_at"] = timestamp
        thread.metadata["dropped_message_count"] = len(result.dropped_messages)
        if result.strategy_used == "summarize":
            thread.metadata["summary_updated_at"] = timestamp
        return True

    # region turn切分
    def _identify_turns(self, messages: list[dict[str, Any]]) -> list[list[int]]:
        """识别完整对话轮次.

        Args:
            messages: 当前 working memory 消息列表.

        Returns:
            每一轮对应的消息索引列表.
        """

        turns: list[list[int]] = []
        current: list[int] = []

        for index, message in enumerate(messages):
            role = str(message.get("role", "") or "")
            if role == "user":
                if current:
                    turns.append(current)
                current = [index]
                continue
            if role in {"assistant", "tool"}:
                if not current:
                    current = [index]
                else:
                    current.append(index)
                continue
            if current:
                current.append(index)
            else:
                current = [index]

        if current:
            turns.append(current)
        return turns

    def _fit_turns_to_budget(
        self,
        *,
        turns: list[list[int]],
        messages: list[dict[str, Any]],
        model: str,
        budget: int,
    ) -> list[list[int]]:
        """从最新轮次向前选择能塞进预算的完整轮次.

        Args:
            turns: 当前完整轮次列表.
            messages: 当前 working memory 消息列表.
            model: 当前模型名.
            budget: 可用 token 预算.

        Returns:
            保留的轮次列表.
        """

        preserve_recent = max(1, self.config.preserve_recent_turns)
        forced_turn_indexes = set(range(max(0, len(turns) - preserve_recent), len(turns)))
        forced_turn_indexes.update(self._identify_pinned_turn_indexes(turns, messages))

        kept_turn_indexes: set[int] = set()
        used_tokens = 0
        for turn_index in sorted(forced_turn_indexes):
            kept_turn_indexes.add(turn_index)
            used_tokens += self._count_turn_tokens(model, turns[turn_index], messages)

        for turn_index in range(len(turns) - 1, -1, -1):
            if turn_index in kept_turn_indexes:
                continue
            turn_tokens = self._count_turn_tokens(model, turns[turn_index], messages)
            if used_tokens + turn_tokens <= budget:
                kept_turn_indexes.add(turn_index)
                used_tokens += turn_tokens

        if not kept_turn_indexes and turns:
            kept_turn_indexes.add(len(turns) - 1)

        return [turns[index] for index in sorted(kept_turn_indexes)]

    def _identify_pinned_turn_indexes(
        self,
        turns: list[list[int]],
        messages: list[dict[str, Any]],
    ) -> set[int]:
        """识别包含 pinned message 的轮次.

        Args:
            turns: 当前轮次列表.
            messages: 当前 working memory 消息列表.

        Returns:
            需要强制保留的 turn index 集合.
        """

        pinned_turn_indexes: set[int] = set()
        for turn_index, turn in enumerate(turns):
            for message_index in turn:
                if bool(messages[message_index].get("pinned", False)):
                    pinned_turn_indexes.add(turn_index)
                    break
        return pinned_turn_indexes

    # endregion

    # region token工具
    def _count_turn_tokens(
        self,
        model: str,
        turn: list[int],
        messages: list[dict[str, Any]],
    ) -> int:
        """计算单轮消息 token 数.

        Args:
            model: 当前模型名.
            turn: 单轮消息索引列表.
            messages: 当前 working memory 消息列表.

        Returns:
            该轮消息的 token 数.
        """

        return self._count_tokens(model, [messages[index] for index in turn])

    def _count_tokens(self, model: str, messages: list[dict[str, Any]]) -> int:
        """计算消息列表 token 数.

        Args:
            model: 当前模型名.
            messages: 目标消息列表.

        Returns:
            token 数.
        """

        if token_counter is not None:
            try:
                counted = token_counter(model=model, messages=messages)
                if isinstance(counted, int):
                    return counted
            except Exception:
                pass

        total = 0
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, str):
                total += max(1, len(content) // 3)
            if "tool_calls" in message:
                total += 20
        return total

    def _get_context_window(self, model: str) -> int:
        """读取模型上下文窗口.

        Args:
            model: 当前模型名.

        Returns:
            上下文窗口大小.
        """

        if get_model_info is not None:
            try:
                info = get_model_info(model)
                window = info.get("max_input_tokens")
                if isinstance(window, int) and window > 0:
                    return window
            except Exception:
                pass
        return self.config.fallback_context_window

    def _history_budget(self, context_window: int) -> int:
        """计算历史消息真正可用的 token 预算.

        Args:
            context_window: 模型上下文窗口.

        Returns:
            扣除各类预留后的 history budget.
        """

        total_budget = int(context_window * self.config.max_context_ratio)
        reserved_tokens = (
            self.config.system_prompt_reserve_tokens
            + self.config.prompt_slot_reserve_tokens
            + self.config.tool_schema_reserve_tokens
        )
        return max(1, total_budget - reserved_tokens)

    # endregion

    # region stats
    def _write_stats(self, ctx: RunContext, result: ContextCompactionResult) -> None:
        """把 compaction stats 写回 RunContext.

        Args:
            ctx: 当前 run 的执行上下文.
            result: 本次 compaction 的结果.
        """

        ctx.metadata["token_stats"] = {
            "context_window": result.context_window,
            "budget": result.budget,
            "system_prompt_reserve_tokens": self.config.system_prompt_reserve_tokens,
            "prompt_slot_reserve_tokens": self.config.prompt_slot_reserve_tokens,
            "tool_schema_reserve_tokens": self.config.tool_schema_reserve_tokens,
            "before_compression": result.before_tokens,
            "after_compression": result.after_tokens,
            "messages_dropped": len(result.dropped_messages),
            "turns_kept": result.kept_turns,
            "turns_dropped": result.dropped_turns,
            "strategy_used": result.strategy_used,
            "model": ctx.profile.default_model,
        }

    # endregion


# endregion


# region helpers
def _truncate_text(value: str, limit: int) -> str:
    """按字符数裁剪摘要文本.

    Args:
        value: 原始摘要文本.
        limit: 最大保留字符数.

    Returns:
        裁剪后的摘要文本.
    """

    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


# endregion
