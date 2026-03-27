"""runtime.memory.long_term_memory 导出 Core SimpleMem 的正式对象."""

from .contracts import (
    ConversationFactAnchorMap,
    FailedWindowRecord,
    LtmSearchHit,
    MemoryEntry,
    MemoryProvenance,
)
from .fact_ids import (
    LONG_TERM_MEMORY_NAMESPACE,
    build_fact_anchor_map,
    build_fact_id_from_conversation_fact,
    build_memory_entry_id,
    normalize_fact_ids,
    resolve_anchor_ids,
)
from .extractor import (
    ExtractionWindowPayload,
    WindowExtractionError,
    build_extraction_window_payload,
    parse_extractor_response,
)
from .model_clients import (
    LtmEmbeddingClient,
    LtmExtractorClient,
    LtmQueryPlannerClient,
)
from .ranking import HitChannelScore, merge_ranked_entry_hits, score_hit_channels
from .renderer import CoreSimpleMemRenderer
from .source import CoreSimpleMemMemorySource
from .write_port import (
    CoreSimpleMemWritePort,
    FactWindow,
    build_failed_window_id,
    derive_conversation_id_from_delta,
    slice_fact_windows,
)

__all__ = [
    "ConversationFactAnchorMap",
    "CoreSimpleMemMemorySource",
    "CoreSimpleMemRenderer",
    "CoreSimpleMemWritePort",
    "ExtractionWindowPayload",
    "FactWindow",
    "FailedWindowRecord",
    "HitChannelScore",
    "LONG_TERM_MEMORY_NAMESPACE",
    "LtmEmbeddingClient",
    "LtmSearchHit",
    "LtmExtractorClient",
    "LtmQueryPlannerClient",
    "MemoryEntry",
    "MemoryProvenance",
    "WindowExtractionError",
    "build_fact_anchor_map",
    "build_extraction_window_payload",
    "build_failed_window_id",
    "build_fact_id_from_conversation_fact",
    "build_memory_entry_id",
    "derive_conversation_id_from_delta",
    "merge_ranked_entry_hits",
    "normalize_fact_ids",
    "parse_extractor_response",
    "resolve_anchor_ids",
    "score_hit_channels",
    "slice_fact_windows",
]
