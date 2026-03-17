from acabot.runtime.backend.mode_registry import BackendModeRegistry


def test_backend_mode_registry_tracks_private_maintain_mode():
    registry = BackendModeRegistry()
    assert registry.is_backend_mode("thread:1") is False
    registry.enter_backend_mode(thread_id="thread:1", actor_id="admin:1", entered_at=1)
    assert registry.is_backend_mode("thread:1") is True
    registry.exit_backend_mode("thread:1")
    assert registry.is_backend_mode("thread:1") is False


def test_backend_mode_registry_get_backend_mode_roundtrip():
    registry = BackendModeRegistry()
    registry.enter_backend_mode(thread_id="thread:1", actor_id="admin:1", entered_at=1)
    state = registry.get_backend_mode("thread:1")
    assert state is not None
    assert state.thread_id == "thread:1"
    assert state.actor_id == "admin:1"
    assert state.entered_at == 1
