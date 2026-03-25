"""旧 memory store 导出删除测试."""

import acabot.runtime as runtime


def test_runtime_facade_no_longer_exports_legacy_memory_store_types() -> None:
    assert not hasattr(runtime, "MemoryItem")
    assert not hasattr(runtime, "MemoryStore")
    assert not hasattr(runtime, "SQLiteMemoryStore")
    assert not hasattr(runtime, "InMemoryMemoryStore")
