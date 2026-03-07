"""SQLiteMessageStore 测试 — 持久化消息的 save / get / query_raw."""

import pytest
from acabot.store.sqlite import SQLiteMessageStore
from acabot.store.base import StoredMessage


class TestSQLiteMessageStore:
    @pytest.fixture
    async def store(self, tmp_path):
        """每个测试用独立的临时数据库."""
        db_path = str(tmp_path / "test.db")
        s = SQLiteMessageStore(db_path=db_path)
        await s.initialize()
        yield s
        await s.close()

    async def test_save_and_get(self, store):
        """save 写入 + get_messages 读取, 验证字段完整性."""
        await store.save(StoredMessage(
            session_key="qq:group:123", role="user", content="hello",
            timestamp=1700000000, sender_id="456", sender_name="Alice",
        ))
        await store.save(StoredMessage(
            session_key="qq:group:123", role="assistant", content="hi there",
            timestamp=1700000001,
        ))
        msgs = await store.get_messages("qq:group:123", limit=10)
        assert len(msgs) == 2
        assert isinstance(msgs[0], StoredMessage)
        assert msgs[0].content == "hello"
        assert msgs[0].sender_id == "456"
        assert msgs[1].content == "hi there"

    async def test_limit(self, store):
        """limit 截断: 20 条只取最后 5 条."""
        for i in range(20):
            await store.save(StoredMessage(
                session_key="key", role="user", content=f"msg{i}",
                timestamp=1700000000 + i,
            ))
        msgs = await store.get_messages("key", limit=5)
        assert len(msgs) == 5
        assert msgs[0].content == "msg15"

    async def test_since_filter(self, store):
        """since 过滤: 只返回时间戳 > since 的消息."""
        await store.save(StoredMessage(session_key="key", role="user", content="old", timestamp=100))
        await store.save(StoredMessage(session_key="key", role="user", content="new", timestamp=200))
        msgs = await store.get_messages("key", since=150)
        assert len(msgs) == 1
        assert msgs[0].content == "new"

    async def test_separate_sessions(self, store):
        """不同 session_key 的消息互不干扰."""
        await store.save(StoredMessage(session_key="a", role="user", content="in a", timestamp=1))
        await store.save(StoredMessage(session_key="b", role="user", content="in b", timestamp=1))
        assert len(await store.get_messages("a", limit=10)) == 1
        assert len(await store.get_messages("b", limit=10)) == 1

    async def test_query_raw(self, store):
        """query_raw: 自由 SELECT 查询, 返回 list[dict]."""
        await store.save(StoredMessage(
            session_key="key", role="user", content="hi",
            timestamp=1, sender_id="u1",
        ))
        rows = await store.query_raw(
            "SELECT content, sender_id FROM messages WHERE session_key = ?",
            ("key",),
        )
        assert len(rows) == 1
        assert rows[0]["content"] == "hi"
        assert rows[0]["sender_id"] == "u1"

    async def test_query_raw_rejects_write(self, store):
        """query_raw 拒绝非 SELECT 语句(安全检查)."""
        with pytest.raises(ValueError, match="SELECT"):
            await store.query_raw("DELETE FROM messages")

    async def test_query_raw_rejects_multiple_statements(self, store):
        """query_raw 拒绝多条语句(防注入 - 不可靠)."""
        with pytest.raises(ValueError, match="multiple"):
            await store.query_raw("SELECT 1; DROP TABLE messages")

    async def test_metadata_roundtrip(self, store):
        """metadata dict 序列化/反序列化."""
        await store.save(StoredMessage(
            session_key="key", role="user", content="hi",
            timestamp=1, metadata={"source": "test", "count": 42},
        ))
        msgs = await store.get_messages("key", limit=10)
        assert msgs[0].metadata == {"source": "test", "count": 42}

    async def test_empty_metadata(self, store):
        """空 metadata 存储后返回空 dict(不是 None)."""
        await store.save(StoredMessage(
            session_key="key", role="user", content="hi", timestamp=1,
        ))
        msgs = await store.get_messages("key", limit=10)
        assert msgs[0].metadata == {}
