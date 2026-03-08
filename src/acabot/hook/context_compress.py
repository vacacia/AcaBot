"""ContextCompressorHook — 上下文截断 + 摘要压缩.

pre_llm hook, 在 LLM 调用前裁剪 ctx.messages.
两种策略:
- truncate: 砍掉旧消息, 只保留最近的(默认)
- summarize: 用 LLM 生成摘要替代旧消息, 写入 session.summary
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from acabot.hook.base import Hook
from acabot.types import HookResult, HookContext

logger = logging.getLogger("acabot.hook.context_compress")

# litellm — 延迟导入失败时走 fallback
try:
    from litellm import token_counter, get_model_info
except ImportError:  # pragma: no cover
    token_counter = None  # type: ignore[assignment]
    get_model_info = None  # type: ignore[assignment]

# 模型信息获取失败时的保守默认值
_FALLBACK_CONTEXT_WINDOW = 64000


# region 轮次识别

def _identify_turns(messages: list[dict[str, Any]]) -> list[list[int]]:
    """识别完整对话轮次, 返回每轮包含的消息索引列表.

    一个完整轮次:
      user + assistant(可能含 tool_calls) + tool(如果有) + assistant(如果有)

    tool/tool_result 必须跟随前面的 assistant(tool_calls), 不可拆散.
    """
    turns: list[list[int]] = []
    current: list[int] = []

    for i, msg in enumerate(messages):
        role = msg.get("role", "")

        if role == "user":
            # 新轮次开始 — 如果有未关闭的旧轮次, 先保存
            if current:
                turns.append(current)
            current = [i]
        elif role in ("assistant", "tool"):
            # assistant/tool 追加到当前轮次
            if not current:
                # 孤立的 assistant/tool(没有 user 开头), 自成一轮
                current = [i]
            else:
                current.append(i)
        else:
            # system 或其他 — 归入当前轮次(如果有)
            if current:
                current.append(i)
            else:
                current = [i]

    if current:
        turns.append(current)

    return turns

# endregion


# region token 工具

def _count_tokens(model: str, messages: list[dict[str, Any]]) -> int:
    """用 litellm 精确计算 token, 失败时用字符估算 fallback."""
    if token_counter is not None:
        try:
            return token_counter(model=model, messages=messages)
        except Exception:
            pass
    # fallback: len / 3(保守, 宁可高估多砍)
    total = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            total += max(1, len(content) // 3)
        if "tool_calls" in m:
            total += 20  # tool_calls 结构估算
    return total


def _get_context_window(model: str) -> int:
    """获取模型上下文窗口大小, 失败时返回保守默认值."""
    if get_model_info is not None:
        try:
            info = get_model_info(model)
            # max_input_tokens 是真正的上下文窗口
            # 不要 fallback 到 max_tokens — 那是 max_output_tokens
            window = info.get("max_input_tokens")
            if window and window > 0:
                return window
        except Exception:
            pass
    logger.warning(
        f"Cannot get context window for model '{model}', "
        f"using fallback {_FALLBACK_CONTEXT_WINDOW}"
    )
    return _FALLBACK_CONTEXT_WINDOW

# endregion


class ContextCompressorHook(Hook):
    """上下文压缩 — pre_llm hook.

    按 token 预算裁剪 ctx.messages, 保证完整轮次不拆散.
    统计数据写入 ctx.metadata["token_stats"], 供 WebUI 面板使用.

    Attributes:
        strategy: "truncate"(砍旧消息) 或 "summarize"(LLM 摘要).
        max_context_ratio: 模型上下文窗口的可用比例(剩余留给 response).
        preserve_recent: 至少保留最近 N 轮.
    """

    name = "context_compressor"
    priority = 80
    enabled = True

    def __init__(
        self,
        strategy: Literal["truncate", "summarize"] = "truncate",
        max_context_ratio: float = 0.7,
        preserve_recent: int = 10,
    ):
        self.strategy = strategy
        self.max_context_ratio = max_context_ratio
        self.preserve_recent = preserve_recent

    async def handle(self, ctx: HookContext) -> HookResult:
        """执行上下文压缩."""
        model = ctx.model
        messages = ctx.messages

        if not messages or not model:
            return HookResult()

        # --- 获取预算 ---
        context_window = _get_context_window(model)
        budget = int(context_window * self.max_context_ratio)

        # --- 识别轮次 ---
        turns = _identify_turns(messages)

        # 从最新轮次向前累积, 直到超预算
        kept_turns = self._fit_turns_to_budget(turns, messages, model, budget)

        # --- 确保 preserve_recent ---
        if len(kept_turns) < min(self.preserve_recent, len(turns)):
            kept_turns = turns[-self.preserve_recent:]

        # --- 重建消息列表 ---
        new_messages = []
        for turn_indices in kept_turns:
            for idx in turn_indices:
                new_messages.append(messages[idx])

        # --- 统计 ---
        dropped = len(messages) - len(new_messages)
        before_tokens = _count_tokens(model, messages)

        if dropped > 0:
            after_tokens = _count_tokens(model, new_messages)
            ctx.messages = new_messages

            # TODO: summarize 模式 — LLM 生成摘要写入 session.summary
            # TODO: session.summary 持久化 — 当前只在内存, 重启丢失.
            #       等 SessionManager 持久化(SQLiteSessionManager)时一并解决.
            # TODO: summarize 实现时, 需要在 hook 内部也更新 ctx.system_prompt,
            #       因为 _build_system_prompt 在 pre_llm 之前已经执行过了.
            if self.strategy == "summarize":
                logger.warning(
                    "strategy='summarize' is not yet implemented, "
                    "falling back to truncate"
                )

            logger.debug(
                f"Context compressed: {dropped} messages dropped "
                f"({before_tokens} → {after_tokens} tokens), "
                f"strategy={self.strategy}"
            )
        else:
            after_tokens = before_tokens

        # --- 写入统计(无论是否压缩) ---
        ctx.metadata["token_stats"] = {
            "context_window": context_window,
            "budget": budget,
            "before_compression": before_tokens,
            "after_compression": after_tokens,
            "messages_dropped": dropped,
            # summarize 未实现, 实际执行的都是 truncate
            "strategy_used": "truncate" if dropped > 0 else "none",
            "model": model,
        }

        return HookResult()

    def _fit_turns_to_budget(
        self,
        turns: list[list[int]],
        messages: list[dict[str, Any]],
        model: str,
        budget: int,
    ) -> list[list[int]]:
        """从最新轮次向前累积, 返回能塞进 budget 的轮次列表."""
        kept: list[list[int]] = []
        accumulated = 0

        for turn_indices in reversed(turns):
            turn_messages = [messages[idx] for idx in turn_indices]
            turn_tokens = _count_tokens(model, turn_messages)

            if accumulated + turn_tokens <= budget:
                kept.insert(0, turn_indices)
                accumulated += turn_tokens
            else:
                # 超预算, 停止添加更多旧轮次
                break

        return kept
