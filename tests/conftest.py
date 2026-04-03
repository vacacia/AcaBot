import sys
import pathlib

import pytest

# extensions/ 在项目根目录, 加入 sys.path 以支持测试中 import 扩展插件
_extensions_dir = str(pathlib.Path(__file__).resolve().parent.parent / "extensions")
if _extensions_dir not in sys.path:
    sys.path.insert(0, _extensions_dir)


@pytest.fixture
def anyio_backend():
    return "asyncio"
