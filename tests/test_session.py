# InMemorySessionManager: 内存版会话管理
# 测试: 创建/获取/复用会话, save 空操作, Session 消息追加

import pytest
from acabot.session import BaseSessionManager, Session
from acabot.session.memory import InMemorySessionManager


class TestInMemorySessionManager:
    @pytest.fixture
    def mgr(self):
        return InMemorySessionManager(max_messages=10)

    def test_is_base(self, mgr):
        # 确认实现了 BaseSessionManager 接口
        assert isinstance(mgr, BaseSessionManager)

    async def test_get_or_create_new(self, mgr):
        # 新 key → 创建新 Session
        session = await mgr.get_or_create("qq:user:123")
        assert isinstance(session, Session)
        assert session.session_key == "qq:user:123"

    async def test_get_or_create_same(self, mgr):
        # 同一个 key → 返回同一个对象(by reference)
        s1 = await mgr.get_or_create("qq:user:123")
        s2 = await mgr.get_or_create("qq:user:123")
        assert s1 is s2

    async def test_get_nonexistent(self, mgr):
        # 不存在的 key → 返回 None, 不自动创建
        assert await mgr.get("nonexistent") is None

    async def test_save_is_noop_for_memory(self, mgr):
        # 内存版 save 是空操作(已通过引用自动保存)
        s = await mgr.get_or_create("key")
        await mgr.save(s)  # should not error


class TestSession:
    def test_append_and_get_context(self):
        # Session.messages 是普通 list, 直接 append 即可
        s = Session(session_key="test")
        s.messages.append({"role": "user", "content": "hi"})
        s.messages.append({"role": "assistant", "content": "hello"})
        assert len(s.messages) == 2
