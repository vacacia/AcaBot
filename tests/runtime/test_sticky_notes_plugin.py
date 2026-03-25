"""旧 sticky notes plugin 删除测试."""

import acabot.runtime as runtime


def test_runtime_facade_no_longer_exports_sticky_notes_plugin() -> None:
    assert not hasattr(runtime, "StickyNotesPlugin")
