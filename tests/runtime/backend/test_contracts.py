from acabot.runtime.backend.contracts import BackendRequest, BackendSourceRef


def test_backend_request_minimal_fields():
    source_ref = BackendSourceRef(
        thread_id="thread:1",
        channel_scope="qq:group:123",
        event_id="event:1",
    )
    req = BackendRequest(
        request_id="req:1",
        source_kind="frontstage_internal",
        request_kind="query",
        source_ref=source_ref,
        summary="查询当前图片说明配置",
        created_at=123,
    )
    assert req.request_id == "req:1"
    assert req.source_kind == "frontstage_internal"
    assert req.request_kind == "query"
    assert req.source_ref.thread_id == "thread:1"
