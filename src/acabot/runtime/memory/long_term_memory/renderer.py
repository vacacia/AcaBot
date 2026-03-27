"""runtime.memory.long_term_memory.renderer 负责把命中记忆渲染成 XML."""

from __future__ import annotations

from xml.sax.saxutils import escape

from .contracts import LtmSearchHit


class CoreSimpleMemRenderer:
    """CoreSimpleMemRenderer 把 top-k 命中结果渲染成统一 XML."""

    def render(self, hits: list[LtmSearchHit]) -> str:
        """把命中结果渲染成 `long_term_memory` XML.

        Args:
            hits: 已排序的命中列表.

        Returns:
            XML 字符串.
        """

        lines = ["<long_term_memory>"]
        for hit in hits:
            entry = hit.entry
            attrs = [f'topic="{escape(entry.topic)}"']
            time_value = entry.time_point or entry.time_interval_start or entry.time_interval_end
            if time_value:
                attrs.append(f'time="{escape(time_value)}"')
            lines.append(
                f"  <entry {' '.join(attrs)}>{escape(entry.lossless_restatement)}</entry>"
            )
        lines.append("</long_term_memory>")
        return "\n".join(lines)


__all__ = ["CoreSimpleMemRenderer"]
