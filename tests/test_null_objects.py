# NullMessageStore: Null Object 模式的消息存储
# 测试: save 不报错, get 返回空列表, query_raw 返回空列表
# Null Object 让框架在没有真实存储时也能正常运行, 插件无需做 None 检查

import pytest
from acabot.store.null import NullMessageStore
from acabot.store.base import StoredMessage


class TestNullMessageStore:
    async def test_save_does_nothing(self):
        store = NullMessageStore()
        msg = StoredMessage(session_key="key", role="user", content="hi")
        await store.save(msg)

    async def test_get_returns_empty(self):
        store = NullMessageStore()
        msgs = await store.get_messages("key", limit=10)
        assert msgs == []

    async def test_query_raw_returns_empty(self):
        store = NullMessageStore()
        result = await store.query_raw("SELECT * FROM messages")
        assert result == []
