"""KVStore 测试 — InMemoryKVStore + NullKVStore."""

from __future__ import annotations

from acabot.kv import InMemoryKVStore, NullKVStore


# region InMemoryKVStore


async def test_memory_get_missing_returns_none():
    """不存在的 key 返回 None."""
    store = InMemoryKVStore()
    assert await store.get("no_such_key") is None


async def test_memory_set_then_get():
    """set 后 get 能读回."""
    store = InMemoryKVStore()
    await store.set("k", "v")
    assert await store.get("k") == "v"


async def test_memory_set_overwrites():
    """重复 set 覆盖旧值."""
    store = InMemoryKVStore()
    await store.set("k", "old")
    await store.set("k", "new")
    assert await store.get("k") == "new"


async def test_memory_delete():
    """delete 后 get 返回 None."""
    store = InMemoryKVStore()
    await store.set("k", "v")
    await store.delete("k")
    assert await store.get("k") is None


async def test_memory_delete_missing_key_is_silent():
    """删除不存在的 key 不报错."""
    store = InMemoryKVStore()
    await store.delete("no_such_key")  # 不应抛异常


async def test_memory_update_from_none():
    """update 空 key: updater 收到 None, 写入并返回新值."""
    store = InMemoryKVStore()
    result = await store.update("counter", lambda old: str(int(old or "0") + 1))
    assert result == "1"
    assert await store.get("counter") == "1"


async def test_memory_update_existing():
    """update 已有 key: updater 收到旧值, 写入并返回新值."""
    store = InMemoryKVStore()
    await store.set("counter", "5")
    result = await store.update("counter", lambda old: str(int(old or "0") + 1))
    assert result == "6"
    assert await store.get("counter") == "6"


async def test_memory_update_is_read_modify_write():
    """update 的读-改-写语义: 连续 update 累加."""
    store = InMemoryKVStore()
    for _ in range(3):
        await store.update("n", lambda old: str(int(old or "0") + 1))
    assert await store.get("n") == "3"


# endregion

# region NullKVStore


async def test_null_get_returns_none():
    """NullKVStore.get 永远返回 None."""
    store = NullKVStore()
    await store.set("k", "v")  # 写入被丢弃
    assert await store.get("k") is None


async def test_null_delete_is_noop():
    """NullKVStore.delete 不报错."""
    store = NullKVStore()
    await store.delete("anything")


async def test_null_update_calls_updater_but_discards():
    """NullKVStore.update 调 updater(None), 返回结果但不存储."""
    store = NullKVStore()
    result = await store.update("k", lambda old: f"computed:{old}")
    assert result == "computed:None"
    # 不存储, 再读仍是 None
    assert await store.get("k") is None


# endregion
