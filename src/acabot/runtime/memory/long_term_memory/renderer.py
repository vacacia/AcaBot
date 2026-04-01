"""runtime.memory.long_term_memory.renderer 负责把命中记忆渲染成 XML.

输出 XML 格式示例：

<long_term_memory>
<!-- 以下是从历史对话中提取的关于用户的长期记忆, 按相关性排序, 靠前的条目与当前话题更相关。自然地使用这些信息, 不要逐条引用。 -->
  <entry topic="小明学钢琴进度" time="2025-03-15T10:00:12Z">小明（qq:user:10001）截至 2025-03-15 已坚持练习钢琴约三个月, 当前阶段在练拜厄练习曲, 长期目标是演奏肖邦夜曲。</entry>
  <entry topic="猫猫北京出差计划" time_start="2025-04-07" time_end="2025-04-09">猫猫（qq:user:40001）于 2025-04-03 表示将于 2025-04-07（周一）前往北京出差, 持续三天至 2025-04-09（周三）。</entry>
  <entry topic="阿华海鲜过敏">阿华（qq:user:20001）对海鲜过敏, 不能食用海鲜。</entry>
</long_term_memory>

注意：
- time_point 和 time_interval 在提取阶段互斥, 一条记忆只会有其中一种。
  单点事件输出 time 属性；区间事件输出 time_start / time_end 属性（只有其中一端时省略另一个）。
- provenance（fact_ids）不输出到 XML —— fact_id 是内部存储 key, 对主模型无语义价值。
- entry 内容是 lossless_restatement, 已在提取阶段强制消歧义, 主模型可以直接引用。

"""

from __future__ import annotations

from xml.sax.saxutils import escape

from .contracts import LtmSearchHit


class LtmRenderer:
    """把 top-k 命中结果渲染成统一 XML."""

    def render(self, hits: list[LtmSearchHit]) -> str:
        """把命中结果渲染成 `long_term_memory` XML.

        Args:
            hits: 已排序的命中列表.

        Returns:
            XML 字符串.
        """

        lines = [
            "<long_term_memory>",
            "<!-- 以下是从历史对话中提取的长期记忆; 按相关性排序, 靠前的条目与当前话题更相关; 自然地使用这些背景信息, 不要逐条引用。 -->",
        ]
        for hit in hits:
            entry = hit.entry
            attrs = [f'topic="{escape(entry.topic)}"']
            if entry.time_point:
                attrs.append(f'time="{escape(entry.time_point)}"')
            elif entry.time_interval_start or entry.time_interval_end:
                if entry.time_interval_start:
                    attrs.append(f'time_start="{escape(entry.time_interval_start)}"')
                if entry.time_interval_end:
                    attrs.append(f'time_end="{escape(entry.time_interval_end)}"')
            lines.append(
                f"  <entry {' '.join(attrs)}>{escape(entry.lossless_restatement)}</entry>"
            )
        lines.append("</long_term_memory>")
        return "\n".join(lines)



__all__ = ["LtmRenderer"]
