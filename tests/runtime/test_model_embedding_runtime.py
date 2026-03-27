import pytest

from acabot.runtime.model.model_embedding_runtime import ModelEmbeddingRuntime
from acabot.runtime.model.model_registry import RuntimeModelRequest


async def test_model_embedding_runtime_uses_request_options_and_returns_vectors(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    async def fake_aembedding(**kwargs):
        calls.append(dict(kwargs))
        return {
            "data": [
                {"embedding": [0.1, 0.2, 0.3]},
                {"embedding": [0.4, 0.5, 0.6]},
            ]
        }

    monkeypatch.setattr(
        "acabot.runtime.model.model_embedding_runtime.aembedding",
        fake_aembedding,
    )

    runtime = ModelEmbeddingRuntime()
    request = RuntimeModelRequest(
        provider_kind="openai_compatible",
        model="text-embedding-3-large",
        provider_params={"base_url": "https://llm.example.com/v1"},
        api_key_env="OPENAI_API_KEY",
    )

    vectors = await runtime.embed_texts(request, ["Alice likes latte.", "Bob likes coffee."])

    assert len(vectors) == 2
    assert vectors[0] == [0.1, 0.2, 0.3]
    assert calls[0]["model"] == "text-embedding-3-large"
    assert calls[0]["input"] == ["Alice likes latte.", "Bob likes coffee."]
    assert calls[0]["api_base"] == "https://llm.example.com/v1"
    assert "provider_kind" not in calls[0]


async def test_model_embedding_runtime_rejects_empty_text_batch() -> None:
    runtime = ModelEmbeddingRuntime()
    request = RuntimeModelRequest(
        provider_kind="openai_compatible",
        model="text-embedding-3-large",
    )

    with pytest.raises(ValueError):
        await runtime.embed_texts(request, [])
