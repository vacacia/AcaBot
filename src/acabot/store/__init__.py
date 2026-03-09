"""store package 只导出轻量接口和默认 null implementation.

SQLiteMessageStore 需要显式从 `acabot.store.sqlite` 导入, 避免 package import 时拉起 aiosqlite.
"""

from .base import BaseMessageStore, StoredMessage
from .null import NullMessageStore

__all__ = [
    "BaseMessageStore",
    "NullMessageStore",
    "StoredMessage",
]
