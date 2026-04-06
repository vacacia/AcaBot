from pathlib import Path

from acabot.runtime import (
    ResolvedAgent,
    AnthropicProviderConfig,
    FileSystemModelRegistryManager,
    ModelBinding,
    ModelProvider,
    ModelPreset,
    MutableModelTargetCatalog,
    OpenAICompatibleProviderConfig,
    RuntimePluginModelSlot,
    SYSTEM_MODEL_TARGETS,
    build_agent_model_targets,
)


def _profile(agent_id: str) -> ResolvedAgent:
    return ResolvedAgent(
        agent_id=agent_id,
        name=agent_id.upper(),
        prompt_ref="prompt/default",
    )


def _catalog() -> MutableModelTargetCatalog:
    catalog = MutableModelTargetCatalog(system_targets=SYSTEM_MODEL_TARGETS)
    catalog.replace_agent_targets(build_agent_model_targets([_profile("aca")]))
    return catalog


def _manager(
    tmp_path: Path,
    *,
    target_catalog: MutableModelTargetCatalog | None = None,
) -> FileSystemModelRegistryManager:
    return FileSystemModelRegistryManager(
        providers_dir=tmp_path / "models/providers",
        presets_dir=tmp_path / "models/presets",
        bindings_dir=tmp_path / "models/bindings",
        target_catalog=target_catalog or _catalog(),
    )


async def test_model_registry_manager_resolves_target_binding_and_preview(
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
            preset_id="agent-main",
            provider_id="openai-main",
            model="gpt-agent",
            task_kind="chat",
            capabilities=["tool_calling"],
            context_window=64000,
            model_params={"temperature": 0.2},
        )
    )
    await manager.upsert_binding(
        ModelBinding(
            binding_id="binding:aca",
            target_id="agent:aca",
            preset_ids=["agent-main"],
            timeout_sec=10,
        )
    )

    status = manager.status()
    request = manager.resolve_target_request("agent:aca")
    preview = manager.preview_effective_target("agent:aca")

    assert status.provider_count == 1
    assert status.preset_count == 1
    assert status.binding_count == 1
    assert request is not None
    assert request.model == "openai/gpt-agent"
    assert request.provider_kind == "openai_compatible"
    assert request.execution_params["timeout"] == 10
    assert request.model_params["temperature"] == 0.2
    assert preview.request is not None
    assert preview.source == "binding:aca"


async def test_model_registry_rejects_binding_when_preset_task_kind_mismatches_target(
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
            preset_id="embed-a",
            provider_id="openai-main",
            model="text-embedding-3-large",
            task_kind="embedding",
            context_window=8192,
        )
    )

    result = await manager.upsert_binding(
        ModelBinding(
            binding_id="binding:summary",
            target_id="system:ltm_extract",
            preset_ids=["embed-a"],
        )
    )

    assert result.ok is False
    assert "task_kind" in result.message
    assert result.binding_state == "invalid_binding"


async def test_model_registry_manager_target_binding_supports_fallback_chain(
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
            task_kind="chat",
            context_window=64000,
        )
    )
    await manager.upsert_preset(
        ModelPreset(
            preset_id="summary-b",
            provider_id="openai-main",
            model="gpt-summary-b",
            task_kind="chat",
            context_window=96000,
        )
    )
    await manager.upsert_binding(
        ModelBinding(
            binding_id="binding:summary",
            target_id="system:ltm_extract",
            preset_ids=["summary-a", "summary-b"],
            timeout_sec=12,
        )
    )

    request = manager.resolve_target_request("system:ltm_extract")

    assert request is not None
    assert request.binding_id == "binding:summary"
    assert request.model == "openai/gpt-summary-a"
    assert request.execution_params["timeout"] == 12
    assert [item.model for item in request.fallback_requests] == ["openai/gpt-summary-b"]
    assert all(item.binding_id == "binding:summary" for item in request.fallback_requests)


async def test_model_registry_keeps_plugin_binding_unresolved_until_slot_registers(
    tmp_path: Path,
) -> None:
    catalog = MutableModelTargetCatalog(system_targets=SYSTEM_MODEL_TARGETS)
    manager = _manager(tmp_path, target_catalog=catalog)
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
            preset_id="plugin-main",
            provider_id="openai-main",
            model="gpt-plugin",
            task_kind="chat",
            context_window=64000,
        )
    )

    result = await manager.upsert_binding(
        ModelBinding(
            binding_id="binding:plugin",
            target_id="plugin:demo:extractor",
            preset_ids=["plugin-main"],
        )
    )

    assert result.ok is True
    assert result.binding_state == "unresolved_target"
    assert manager.resolve_target_request("plugin:demo:extractor") is None

    catalog.register_plugin_slots(
        plugin_id="demo",
        slots=[
            RuntimePluginModelSlot(
                slot_id="extractor",
                task_kind="chat",
                required=True,
                allow_fallbacks=True,
                description="demo extractor",
            )
        ],
    )
    reload_result = await manager.reload()
    request = manager.resolve_target_request("plugin:demo:extractor")

    assert reload_result.ok is True
    assert request is not None
    assert request.model == "openai/gpt-plugin"


async def test_model_registry_blocks_plugin_binding_when_slot_task_kind_mismatches(
    tmp_path: Path,
) -> None:
    catalog = MutableModelTargetCatalog(system_targets=SYSTEM_MODEL_TARGETS)
    manager = _manager(tmp_path, target_catalog=catalog)
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
            preset_id="embed-main",
            provider_id="openai-main",
            model="text-embedding-3-large",
            task_kind="embedding",
            context_window=8192,
        )
    )
    await manager.upsert_binding(
        ModelBinding(
            binding_id="binding:plugin",
            target_id="plugin:demo:extractor",
            preset_ids=["embed-main"],
        )
    )

    catalog.register_plugin_slots(
        plugin_id="demo",
        slots=[
            RuntimePluginModelSlot(
                slot_id="extractor",
                task_kind="chat",
                required=True,
                allow_fallbacks=True,
                description="demo extractor",
            )
        ],
    )

    reload_result = await manager.reload()
    snapshot = manager.get_binding_snapshot("binding:plugin")

    assert reload_result.ok is False
    assert "task_kind" in reload_result.error
    assert snapshot.binding_state == "invalid_binding"
    assert "task_kind" in snapshot.message
    assert manager.resolve_target_request("plugin:demo:extractor") is None


async def test_model_registry_rejects_binding_when_required_capabilities_are_missing(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    # 注册 agent target 使 agent:test:image_caption 可用(需要 image_input)
    from acabot.runtime.model.model_targets import build_agent_model_targets, ModelTarget
    from acabot.runtime import ResolvedAgent
    manager.target_catalog.replace_agent_targets(
        build_agent_model_targets([ResolvedAgent(agent_id="test", name="test", prompt_ref="p")])
    )
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
            preset_id="caption-main",
            provider_id="openai-main",
            model="gpt-caption",
            task_kind="chat",
            capabilities=["tool_calling"],
            context_window=64000,
        )
    )

    result = await manager.upsert_binding(
        ModelBinding(
            binding_id="binding:image-caption",
            target_id="agent:test:image_caption",
            preset_ids=["caption-main"],
        )
    )

    assert result.ok is False
    assert "image_input" in result.message
    assert result.binding_state == "invalid_binding"


async def test_model_registry_marks_agent_binding_unresolved_after_target_removal(
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
            preset_id="agent-main",
            provider_id="openai-main",
            model="gpt-agent",
            task_kind="chat",
            context_window=64000,
        )
    )
    await manager.upsert_binding(
        ModelBinding(
            binding_id="binding:aca",
            target_id="agent:aca",
            preset_ids=["agent-main"],
        )
    )

    manager.target_catalog.replace_agent_targets([])
    reload_result = await manager.reload()
    snapshot = manager.get_binding_snapshot("binding:aca")

    assert reload_result.ok is False
    assert snapshot.binding_state == "unresolved_target"
    assert snapshot.target_present is False
    assert "target not registered" in snapshot.message
    assert manager.resolve_target_request("agent:aca") is None


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
            task_kind="chat",
            context_window=64000,
        )
    )
    await manager.upsert_binding(
        ModelBinding(
            binding_id="binding:aca",
            target_id="agent:aca",
            preset_ids=["main"],
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


async def test_model_registry_invalidates_filesystem_cache_after_upsert(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    manager.reload_now()

    result = await manager.upsert_provider(
        ModelProvider(
            provider_id="openai-main",
            kind="openai_compatible",
            config=OpenAICompatibleProviderConfig(
                base_url="https://llm.example.com/v1",
                api_key_env="OPENAI_API_KEY",
            ),
        )
    )

    assert result.ok is True
    assert [item.provider_id for item in manager.list_providers()] == ["openai-main"]
    fetched = manager.get_provider("openai-main")
    assert fetched is not None
    assert fetched.provider_id == "openai-main"


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
            task_kind="chat",
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
    assert result.model == "openai/gpt-main"
    assert manager.status().provider_count == 1


async def test_model_registry_health_check_prefixes_anthropic_models_for_litellm(
    monkeypatch,
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    await manager.upsert_provider(
        ModelProvider(
            provider_id="glm",
            kind="anthropic",
            config=AnthropicProviderConfig(
                base_url="https://open.bigmodel.cn/api/anthropic",
                api_key_env="GLM_API_KEY",
                anthropic_version="2023-06-01",
            ),
        )
    )
    await manager.upsert_preset(
        ModelPreset(
            preset_id="glm-main",
            provider_id="glm",
            model="glm-4.7",
            task_kind="chat",
            context_window=128000,
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

    result = await manager.health_check(preset_id="glm-main")

    assert result.ok is True
    assert result.model == "anthropic/glm-4.7"


async def test_model_registry_supports_inline_api_key_from_provider_payload(
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
task_kind: chat
context_window: 64000
capabilities:
  - tool_calling
""".strip(),
        encoding="utf-8",
    )
    (bindings_dir / "agent-aca.yaml").write_text(
        """
binding_id: binding:aca
target_id: agent:aca
preset_ids:
  - main
""".strip(),
        encoding="utf-8",
    )

    manager = FileSystemModelRegistryManager(
        providers_dir=providers_dir,
        presets_dir=presets_dir,
        bindings_dir=bindings_dir,
        target_catalog=_catalog(),
    )
    await manager.reload()

    request = manager.resolve_target_request("agent:aca")

    assert request is not None
    assert request.api_key == "sk-inline-secret"
    assert request.api_key_env == ""
    assert request.to_request_options()["api_key"] == "sk-inline-secret"
