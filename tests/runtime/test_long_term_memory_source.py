import json

from acabot.agent.response import AgentResponse
from acabot.runtime import (
    ModelBinding,
    ModelPreset,
    ModelProvider,
    OpenAICompatibleProviderConfig,
    SharedMemoryRetrievalRequest,
)
from acabot.runtime.memory.long_term_memory.model_clients import LtmQueryPlannerClient
from acabot.runtime.model.model_registry import FileSystemModelRegistryManager
from acabot.runtime.memory.long_term_memory.contracts import LtmSearchHit, MemoryEntry, MemoryProvenance
from acabot.runtime.memory.long_term_memory.ranking import score_hit_channels
from acabot.runtime.memory.long_term_memory.renderer import CoreSimpleMemRenderer
from acabot.runtime.memory.long_term_memory.source import CoreSimpleMemMemorySource
from acabot.runtime.memory.long_term_memory.storage import LanceDbLongTermMemoryStore


class StaticQueryPlanner:
    async def plan_query(self, request_payload: dict[str, object]) -> dict[str, object]:
        _ = request_payload
        return {
            "semantic_queries": [],
            "lexical_queries": ["latte"],
            "symbolic_filters": {"persons": ["Alice"]},
        }


class NullEmbeddingClient:
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        _ = texts
        return []


class EmptyTimeRangePlanner:
    async def plan_query(self, request_payload: dict[str, object]) -> dict[str, object]:
        _ = request_payload
        return {
            "semantic_queries": [],
            "lexical_queries": [],
            "symbolic_filters": {"time_range": ["", ""]},
        }


class RecordingPlannerAgent:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def complete(self, system_prompt, messages, model=None, request_options=None):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": list(messages),
                "model": model,
                "request_options": dict(request_options or {}),
            }
        )
        return AgentResponse(
            text=json.dumps(
                {
                    "semantic_queries": ["Alice 咖啡 偏好", ""],
                    "lexical_queries": ["拿铁", "latte"],
                    "symbolic_filters": {
                        "persons": ["Alice"],
                        "entities": ["AcaBot"],
                        "location": "上海",
                        "time_range": ["2025-01-01", "2025-12-31"],
                    },
                },
                ensure_ascii=False,
            )
        )


def _request(query_text: str = "Alice 喜欢喝什么？") -> SharedMemoryRetrievalRequest:
    return SharedMemoryRetrievalRequest(
        run_id="run:1",
        thread_id="thread:1",
        actor_id="qq:user:10001",
        agent_id="aca",
        channel_scope="qq:group:42",
        event_id="evt-1",
        event_type="message",
        event_timestamp=123,
        query_text=query_text,
    )


def _entry(*, entry_id: str, topic: str, updated_at: int, text: str) -> MemoryEntry:
    return MemoryEntry(
        entry_id=entry_id,
        conversation_id="qq:group:42",
        created_at=100,
        updated_at=updated_at,
        extractor_version="ltm-v1",
        topic=topic,
        lossless_restatement=text,
        keywords=["latte"],
        persons=["Alice"],
        provenance=MemoryProvenance(fact_ids=[f"e:{entry_id}"]),
    )


async def test_long_term_memory_source_returns_single_long_term_memory_block(tmp_path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")
    store.upsert_entries(
        [_entry(entry_id="entry-1", topic="咖啡偏好", updated_at=123, text="Alice 喜欢拿铁。")]
    )
    source = CoreSimpleMemMemorySource(
        store=store,
        query_planner=StaticQueryPlanner(),
        embedding_client=NullEmbeddingClient(),
    )

    blocks = await source(_request())

    assert len(blocks) == 1
    assert blocks[0].source == "long_term_memory"
    assert blocks[0].assembly.target_slot == "message_prefix"
    assert "咖啡偏好" in blocks[0].content


def test_renderer_outputs_xml_in_rank_order() -> None:
    renderer = CoreSimpleMemRenderer()
    xml = renderer.render(
        [
            LtmSearchHit(
                entry=_entry(entry_id="entry-1", topic="咖啡偏好", updated_at=200, text="Alice 喜欢拿铁。"),
                rerank_score=150,
                hit_sources=["symbolic", "semantic", "lexical"],
            ),
            LtmSearchHit(
                entry=_entry(entry_id="entry-2", topic="工作地点", updated_at=100, text="Alice 在上海办公。"),
                rerank_score=100,
                hit_sources=["symbolic"],
            ),
        ]
    )

    assert xml.startswith("<long_term_memory>")
    assert xml.index("咖啡偏好") < xml.index("工作地点")


def test_ranking_prefers_symbolic_semantic_over_lexical_only() -> None:
    scores = score_hit_channels(
        symbolic_hit=True,
        semantic_hit=True,
        lexical_hit=False,
    )
    assert scores.rerank_score == 140


async def test_query_planner_client_uses_ltm_query_plan_target(tmp_path) -> None:
    manager = FileSystemModelRegistryManager(
        providers_dir=tmp_path / "models/providers",
        presets_dir=tmp_path / "models/presets",
        bindings_dir=tmp_path / "models/bindings",
    )
    await manager.upsert_provider(
        ModelProvider(
            provider_id="openai-main",
            kind="openai_compatible",
            config=OpenAICompatibleProviderConfig(
                base_url="https://example.invalid/v1",
                api_key_env="OPENAI_API_KEY",
            ),
        )
    )
    await manager.upsert_preset(
        ModelPreset(
            preset_id="ltm-query-plan-main",
            provider_id="openai-main",
            model="gpt-4.1-mini",
            task_kind="chat",
            capabilities=["structured_output"],
            context_window=128000,
        )
    )
    await manager.upsert_binding(
        ModelBinding(
            binding_id="binding:ltm-query-plan",
            target_id="system:ltm_query_plan",
            preset_ids=["ltm-query-plan-main"],
        )
    )
    agent = RecordingPlannerAgent()
    client = LtmQueryPlannerClient(
        agent=agent,
        model_registry_manager=manager,
    )

    plan = await client.plan_query({"query_text": "Alice 喜欢喝什么？", "conversation_id": "qq:group:42"})

    assert plan["semantic_queries"] == ["Alice 咖啡 偏好"]
    assert plan["lexical_queries"] == ["拿铁", "latte"]
    assert plan["symbolic_filters"] == {
        "persons": ["Alice"],
        "entities": ["AcaBot"],
        "location": "上海",
        "time_range": ["2025-01-01", "2025-12-31"],
    }
    assert agent.calls[0]["model"] == "gpt-4.1-mini"


async def test_long_term_memory_source_ignores_empty_time_range_filter(tmp_path) -> None:
    store = LanceDbLongTermMemoryStore(tmp_path / "lancedb")
    store.upsert_entries(
        [_entry(entry_id="entry-1", topic="咖啡偏好", updated_at=123, text="Alice 喜欢拿铁。")]
    )
    source = CoreSimpleMemMemorySource(
        store=store,
        query_planner=EmptyTimeRangePlanner(),
        embedding_client=NullEmbeddingClient(),
    )

    blocks = await source(_request(query_text=""))

    assert blocks == []
