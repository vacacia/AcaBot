import sys
import pathlib

import pytest

# plugins/ 在项目根目录, 加入 sys.path 以支持测试中 import 插件
_plugins_dir = str(pathlib.Path(__file__).resolve().parent.parent / "plugins")
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)


@pytest.fixture
def anyio_backend():
    return "asyncio"
