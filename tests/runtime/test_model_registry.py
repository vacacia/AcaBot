from pathlib import Path

from acabot.runtime import (
    FileSystemModelRegistryManager,
    ModelBinding,
    ModelProvider,
    ModelPreset,
    OpenAICompatibleProviderConfig,
)


def _manager(tmp_path: Path) -> FileSystemModelRegistryManager:
    return FileSystemModelRegistryManager(
        providers_dir=tmp_path / "models/providers",
        presets_dir=tmp_path / "models/presets",
        bindings_dir=tmp_path / "models/bindings",
        legacy_global_default_model="legacy-global",
        legacy_summary_model="legacy-summary",
    )


async def test_model_registry_manager_loads_filesystem_layout_and_resolves_agent_binding(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    await manager.upsert_provider(
        ModelProvider(
            provider_id="openai-main",
            kind="openai_compatible",
            config=OpenAICompatibleProviderConfig(
                base_url="https://llm.example.com/v1",
                api_key_env="OPENAI_API_KEY",
            ),
        )
    )
    await manager.upsert_preset(
        ModelPreset(
            preset_id="default-main",
            provider_id="openai-main",
            model="gpt-main",
            context_window=128000,
            supports_tools=True,
        )
    )
    await manager.upsert_preset(
        ModelPreset(
            preset_id="agent-main",
            provider_id="openai-main",
            model="gpt-agent",
            context_window=64000,
            supports_tools=True,
            model_params={"temperature": 0.2},
        )
    )
    await manager.upsert_binding(
        ModelBinding(
            binding_id="binding:global",
            target_type="global",
            target_id="default",
            preset_id="default-main",
            timeout_sec=30,
        )
    )
    await manager.upsert_binding(
        ModelBinding(
            binding_id="binding:aca",
            target_type="agent",
            target_id="aca",
            preset_id="agent-main",
            timeout_sec=10,
        )
    )

    status = manager.status()
    request, snapshot = manager.resolve_run_request(
        run_mode="respond",
        agent_id="aca",
        explicit_profile_default_model="profile-explicit",
        effective_profile_default_model="profile-effective",
    )
    preview = manager.preview_effective_agent(
        agent_id="aca",
        explicit_profile_default_model="profile-explicit",
        effective_profile_default_model="profile-effective",
    )

    assert status.provider_count == 1
    assert status.preset_count == 2
    assert status.binding_count == 2
    assert request is not None
    assert request.model == "gpt-agent"
    assert request.provider_kind == "openai_compatible"
    assert request.execution_params["timeout"] == 10
    assert request.model_params["temperature"] == 0.2
    assert snapshot is not None
    assert snapshot.binding_id == "binding:aca"
    assert snapshot.provider_id == "openai-main"
    assert preview.request is not None
    assert preview.source == "binding:aca"


async def test_model_registry_manager_uses_legacy_fallback_when_no_binding_exists(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)

    request, snapshot = manager.resolve_run_request(
        run_mode="respond",
        agent_id="aca",
        explicit_profile_default_model="profile-explicit",
        effective_profile_default_model="profile-effective",
    )

    assert request is not None
    assert request.provider_kind == "legacy"
    assert request.model == "profile-explicit"
    assert snapshot is not None
    assert snapshot.binding_id == "legacy:profile_default_model"


async def test_model_registry_manager_summary_binding_supports_fallback_chain(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    await manager.upsert_provider(
        ModelProvider(
            provider_id="openai-main",
            kind="openai_compatible",
            config=OpenAICompatibleProviderConfig(
                base_url="https://llm.example.com/v1",
                api_key_env="OPENAI_API_KEY",
            ),
        )
    )
    await manager.upsert_preset(
        ModelPreset(
            preset_id="summary-a",
            provider_id="openai-main",
            model="gpt-summary-a",
            context_window=64000,
            supports_tools=False,
        )
    )
    await manager.upsert_preset(
        ModelPreset(
            preset_id="summary-b",
            provider_id="openai-main",
            model="gpt-summary-b",
            context_window=96000,
            supports_tools=False,
        )
    )
    await manager.upsert_binding(
        ModelBinding(
            binding_id="binding:summary",
            target_type="system",
            target_id="compactor_summary",
            preset_ids=["summary-a", "summary-b"],
            timeout_sec=12,
        )
    )

    request = manager.resolve_summary_request(primary_request=None)

    assert request is not None
    assert request.binding_id == "binding:summary"
    assert request.model == "gpt-summary-a"
    assert request.execution_params["timeout"] == 12
    assert [item.model for item in request.fallback_requests] == ["gpt-summary-b"]
    assert all(item.binding_id == "binding:summary" for item in request.fallback_requests)


async def test_model_registry_manager_prefers_profile_summary_preset_over_global_summary_binding(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    await manager.upsert_provider(
        ModelProvider(
            provider_id="openai-main",
            kind="openai_compatible",
            config=OpenAICompatibleProviderConfig(
                base_url="https://llm.example.com/v1",
                api_key_env="OPENAI_API_KEY",
            ),
        )
    )
    await manager.upsert_preset(
        ModelPreset(
            preset_id="summary-global",
            provider_id="openai-main",
            model="gpt-summary-global",
            context_window=32000,
            supports_tools=False,
        )
    )
    await manager.upsert_preset(
        ModelPreset(
            preset_id="summary-profile",
            provider_id="openai-main",
            model="gpt-summary-profile",
            context_window=16000,
            supports_tools=False,
        )
    )
    await manager.upsert_binding(
        ModelBinding(
            binding_id="binding:summary",
            target_type="system",
            target_id="compactor_summary",
            preset_ids=["summary-global"],
        )
    )

    request = manager.resolve_summary_request(
        primary_request=None,
        profile_summary_preset_id="summary-profile",
    )

    assert request is not None
    assert request.model == "gpt-summary-profile"
    assert request.binding_id == "profile:summary_model_preset"


async def test_model_registry_manager_blocks_delete_without_force_and_cascades_with_force(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    await manager.upsert_provider(
        ModelProvider(
            provider_id="openai-main",
            kind="openai_compatible",
            config=OpenAICompatibleProviderConfig(
                base_url="https://llm.example.com/v1",
                api_key_env="OPENAI_API_KEY",
            ),
        )
    )
    await manager.upsert_preset(
        ModelPreset(
            preset_id="main",
            provider_id="openai-main",
            model="gpt-main",
            context_window=64000,
        )
    )
    await manager.upsert_binding(
        ModelBinding(
            binding_id="binding:aca",
            target_type="agent",
            target_id="aca",
            preset_id="main",
        )
    )

    blocked = await manager.delete_provider("openai-main")
    deleted = await manager.delete_provider("openai-main", force=True)

    assert blocked.ok is False
    assert blocked.impact is not None
    assert blocked.impact.preset_ids == ["main"]
    assert blocked.impact.binding_ids == ["binding:aca"]
    assert blocked.impact.agent_ids == ["aca"]
    assert deleted.ok is True
    assert manager.list_providers() == []
    assert manager.list_presets() == []
    assert manager.list_bindings() == []


async def test_model_registry_manager_health_check_is_explicit_and_optional(
    monkeypatch,
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    await manager.upsert_provider(
        ModelProvider(
            provider_id="openai-main",
            kind="openai_compatible",
            config=OpenAICompatibleProviderConfig(
                base_url="https://llm.example.com/v1",
                api_key_env="OPENAI_API_KEY",
            ),
        )
    )
    await manager.upsert_preset(
        ModelPreset(
            preset_id="main",
            provider_id="openai-main",
            model="gpt-main",
            context_window=64000,
        )
    )

    async def fake_complete(self, system_prompt, messages, model=None, request_options=None):
        _ = self, system_prompt, messages, request_options
        return type(
            "Response",
            (),
            {
                "error": None,
                "model_used": model or "",
            },
        )()

    monkeypatch.setattr("acabot.agent.agent.LitellmAgent.complete", fake_complete)

    result = await manager.health_check(preset_id="main")

    assert result.ok is True
    assert result.model == "gpt-main"
    assert manager.status().provider_count == 1


async def test_model_registry_supports_inline_api_key_and_legacy_misfilled_env_field(
    tmp_path: Path,
) -> None:
    providers_dir = tmp_path / "models/providers"
    presets_dir = tmp_path / "models/presets"
    bindings_dir = tmp_path / "models/bindings"
    providers_dir.mkdir(parents=True)
    presets_dir.mkdir(parents=True)
    bindings_dir.mkdir(parents=True)

    (providers_dir / "inline.yaml").write_text(
        """
provider_id: inline
kind: openai_compatible
base_url: https://llm.example.com/v1
api_key_env: sk-inline-secret
default_headers: {}
default_query: {}
default_body: {}
""".strip(),
        encoding="utf-8",
    )
    (presets_dir / "main.yaml").write_text(
        """
preset_id: main
provider_id: inline
model: gpt-main
context_window: 64000
supports_tools: true
""".strip(),
        encoding="utf-8",
    )
    (bindings_dir / "global.yaml").write_text(
        """
binding_id: global-default
target_type: global
target_id: default
preset_id: main
""".strip(),
        encoding="utf-8",
    )

    manager = FileSystemModelRegistryManager(
        providers_dir=providers_dir,
        presets_dir=presets_dir,
        bindings_dir=bindings_dir,
    )
    await manager.reload()

    request, snapshot = manager.resolve_run_request(
        run_mode="respond",
        agent_id="aca",
        explicit_profile_default_model="",
        effective_profile_default_model="",
    )

    assert request is not None
    assert request.api_key == "sk-inline-secret"
    assert request.api_key_env == ""
    assert request.to_request_options()["api_key"] == "sk-inline-secret"
    assert snapshot is not None
    assert snapshot.api_key_env == ""
