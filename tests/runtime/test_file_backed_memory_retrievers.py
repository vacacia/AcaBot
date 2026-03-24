from acabot.runtime import MemoryAssemblySpec, SharedMemoryRetrievalRequest, SoulSource
from acabot.runtime.memory.file_backed import SelfFileRetriever, StickyNotesFileRetriever, StickyNotesSource


def _request(
    *,
    sticky_note_scopes: list[str] | None = None,
) -> SharedMemoryRetrievalRequest:
    return SharedMemoryRetrievalRequest(
        run_id="run:1",
        thread_id="qq:group:20002",
        actor_id="qq:user:10001",
        agent_id="aca",
        channel_scope="qq:group:20002",
        event_id="evt-1",
        event_type="message",
        event_timestamp=1,
        event_tags=[],
        query_text="hello",
        working_summary="",
        retained_history=[],
        requested_tags=[],
        metadata={"sticky_note_scopes": list(sticky_note_scopes or [])},
    )


async def test_self_file_retriever_returns_self_memory_block(tmp_path) -> None:
    source = SoulSource(root_dir=tmp_path)
    source.append_today_entry("[qq:group:123 time=1] vi 交代了部署任务")
    retriever = SelfFileRetriever(source)

    blocks = await retriever(_request())

    assert blocks[0].source == "self"
    assert blocks[0].scope == "global"
    assert blocks[0].assembly == MemoryAssemblySpec(
        target_slot="message_prefix",
        priority=900,
    )
    assert "today.md" in blocks[0].content


async def test_sticky_notes_file_retriever_returns_scoped_blocks(tmp_path) -> None:
    source = StickyNotesSource(root_dir=tmp_path)
    source.create_note(
        scope="user",
        scope_key="qq:user:10001",
        key="reply_style",
        readonly_content="回答要更直接",
    )
    source.create_note(
        scope="channel",
        scope_key="qq:group:20002",
        key="group_rule",
        readonly_content="不要刷屏",
    )
    retriever = StickyNotesFileRetriever(source)

    blocks = await retriever(_request(sticky_note_scopes=["user"]))

    assert len(blocks) == 1
    assert blocks[0].scope == "user"
    assert blocks[0].source == "sticky_notes"
    assert blocks[0].assembly == MemoryAssemblySpec(
        target_slot="message_prefix",
        priority=800,
    )


async def test_sticky_notes_file_retriever_returns_notes_from_every_allowed_scope(tmp_path) -> None:
    source = StickyNotesSource(root_dir=tmp_path)
    source.create_note(
        scope="user",
        scope_key="qq:user:10001",
        key="reply_style",
        readonly_content="回答要更直接",
    )
    source.create_note(
        scope="channel",
        scope_key="qq:group:20002",
        key="group_rule",
        readonly_content="不要刷屏",
    )
    retriever = StickyNotesFileRetriever(source)

    blocks = await retriever(_request(sticky_note_scopes=["user", "channel"]))

    assert [block.scope for block in blocks] == ["user", "channel"]


async def test_sticky_notes_file_retriever_requires_explicit_sticky_note_scope_allowlist(tmp_path) -> None:
    source = StickyNotesSource(root_dir=tmp_path)
    source.create_note(
        scope="user",
        scope_key="qq:user:10001",
        key="reply_style",
        readonly_content="回答要更直接",
    )
    retriever = StickyNotesFileRetriever(source)

    blocks = await retriever(_request(sticky_note_scopes=[]))

    assert blocks == []


async def test_sticky_notes_file_retriever_ignores_unsupported_sticky_note_scopes(tmp_path) -> None:
    source = StickyNotesSource(root_dir=tmp_path)
    source.create_note(
        scope="user",
        scope_key="qq:user:10001",
        key="reply_style",
        readonly_content="回答要更直接",
    )
    retriever = StickyNotesFileRetriever(source)

    blocks = await retriever(_request(sticky_note_scopes=["relationship"]))

    assert blocks == []


async def test_sticky_notes_file_retriever_skips_missing_note_and_keeps_others(tmp_path) -> None:
    class FlakyStickyNotesSource(StickyNotesSource):
        _delete_on_read = False

        def read_pair(self, *, scope: str, scope_key: str, key: str) -> dict[str, object]:
            if type(self)._delete_on_read and key == "alpha":
                self.delete_note(scope=scope, scope_key=scope_key, key=key)
            return super().read_pair(scope=scope, scope_key=scope_key, key=key)

    source = FlakyStickyNotesSource(root_dir=tmp_path)
    source.create_note(
        scope="user",
        scope_key="qq:user:10001",
        key="alpha",
        readonly_content="alpha",
    )
    source.create_note(
        scope="user",
        scope_key="qq:user:10001",
        key="beta",
        readonly_content="beta",
    )
    type(source)._delete_on_read = True
    retriever = StickyNotesFileRetriever(source)

    blocks = await retriever(_request(sticky_note_scopes=["user"]))

    assert len(blocks) == 1
    assert blocks[0].metadata["note_key"] == "beta"
