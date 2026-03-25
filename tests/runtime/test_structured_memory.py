"""旧 structured memory 导出删除测试."""

import acabot.runtime as runtime


def test_runtime_facade_no_longer_exports_store_backed_memory_retriever() -> None:
    assert not hasattr(runtime, "StoreBackedMemoryRetriever")
