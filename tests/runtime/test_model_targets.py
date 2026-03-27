from acabot.runtime import (
    AgentProfile,
    MutableModelTargetCatalog,
    RuntimePluginModelSlot,
    SYSTEM_MODEL_TARGETS,
    build_agent_model_targets,
)


def _profile(agent_id: str) -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id,
        name=agent_id.upper(),
        prompt_ref="prompt/default",
    )


def test_model_target_catalog_rebuilds_agent_targets_from_profile_registry() -> None:
    catalog = MutableModelTargetCatalog(system_targets=SYSTEM_MODEL_TARGETS)
    catalog.replace_agent_targets(build_agent_model_targets([_profile("aca"), _profile("worker")]))

    aca = catalog.get("agent:aca")
    summary = catalog.get("system:compactor_summary")
    image_caption = catalog.get("system:image_caption")

    assert aca is not None
    assert aca.task_kind == "chat"
    assert aca.source_kind == "agent"
    assert summary is not None
    assert summary.allow_fallbacks is True
    assert image_caption is not None
    assert image_caption.required_capabilities == ["image_input"]


def test_model_target_catalog_registers_and_unregisters_plugin_slots() -> None:
    catalog = MutableModelTargetCatalog(system_targets=[])
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

    target = catalog.get("plugin:demo:extractor")
    assert target is not None
    assert target.source_kind == "plugin"
    assert target.required is True

    catalog.unregister_plugin_targets("demo")

    assert catalog.get("plugin:demo:extractor") is None
